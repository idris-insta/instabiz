"""Order ↔ production ↔ dispatch reconciliation.

For every Sales Order line: ordered qty, what production runs made for it
(IB WO Output.sales_order_item on completed runs), what is still in a run, and
what has been dispatched (Delivery Notes). Differences beyond the tolerance in
IB Stock Settings are flagged:

  Dispatched more than produced   — factory order shipped beyond what the runs made
  Dispatched without production   — factory order shipped with no finished run
  Over-dispatched                 — more shipped than ordered
  Produced short                  — runs finished below the order, nothing left running
  Produced over                   — runs made more than ordered
  Ready, not dispatched           — made, but not shipped N days after the last run

Checked on Delivery Note submit and when a run completes (bell to Factory
Management + the sales person, once per line and flag, plus a comment on the
order), daily for "ready, not dispatched", and shown in full in the
IB Order Reconciliation report.
"""
import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, get_datetime, now_datetime

from instabiz.overrides.ib_settings import get_check, get_float, get_int

MARK = "[ib-reco-{0}-{1}]"
NOTIFY_ROLES = ("Factory Management",)


def tolerance():
	return get_float("reco_tolerance_pct", 5.0) / 100


def lines(sales_orders=None, so_details=None, open_only=True, from_date=None, to_date=None, sales_person=None):
	"""One row per Sales Order line with ordered / produced / in run / dispatched and its flags."""
	cond, args = ["so.docstatus = 1"], {}
	for field, op, value in (("transaction_date", ">=", from_date), ("transaction_date", "<=", to_date),
			("custom_sales_person_user", "=", sales_person)):
		if value:
			cond.append(f"so.{field} {op} %({field}{len(args)})s")
			args[f"{field}{len(args)}"] = value
	if sales_orders:
		cond.append("so.name IN %(sos)s")
		args["sos"] = tuple(sales_orders)
	if so_details:
		cond.append("soi.name IN %(sods)s")
		args["sods"] = tuple(so_details)
	if open_only and not (sales_orders or so_details):
		from instabiz.overrides.ib_status import stored_statuses

		cond.append("so.status NOT IN %(closed)s")
		args["closed"] = stored_statuses("Sales Order", "Closed", "Cancelled")
	rows = frappe.db.sql(f"""
		SELECT soi.name AS so_detail, so.name AS sales_order, so.customer, so.customer_name, so.transaction_date,
		       so.delivery_date, so.custom_location AS location, so.set_warehouse, so.custom_sales_person_user AS sales_person,
		       soi.item_code, soi.item_name, soi.uom, soi.qty AS ordered, IFNULL(soi.delivered_qty, 0) AS dispatched
		FROM `tabSales Order Item` soi JOIN `tabSales Order` so ON so.name = soi.parent
		WHERE {' AND '.join(cond)}
		ORDER BY so.transaction_date DESC, so.name, soi.idx""", args, as_dict=True)
	if not rows:
		return []
	made = {r.sales_order_item: r for r in frappe.db.sql("""
		SELECT o.sales_order_item,
		       SUM(IF(wo.status = 'Completed', o.produced_qty, 0)) AS produced,
		       SUM(IF(wo.status NOT IN ('Completed', 'Cancelled'), o.planned_qty, 0)) AS in_run,
		       SUM(IF(wo.status NOT IN ('Completed', 'Cancelled'), 1, 0)) AS open_runs,
		       SUM(IF(wo.status = 'Completed', 1, 0)) AS done_runs,
		       MAX(IF(wo.status = 'Completed', wo.completed_at, NULL)) AS last_done,
		       GROUP_CONCAT(DISTINCT IF(wo.status != 'Cancelled', wo.name, NULL)) AS runs,
		       GROUP_CONCAT(DISTINCT UPPER(o.uom)) AS uoms
		FROM `tabIB WO Output` o JOIN `tabIB Work Order` wo ON wo.name = o.parent
		WHERE o.sales_order_item IN %s GROUP BY o.sales_order_item""", (tuple(r.so_detail for r in rows),), as_dict=True)}
	factory = {}
	tol, ready_days = tolerance(), get_int("reco_ready_days", 3)
	for r in rows:
		m = made.get(r.so_detail) or frappe._dict()
		r.produced, r.in_run = flt(m.produced), flt(m.in_run)
		r.open_runs, r.done_runs, r.last_done, r.runs = cint(m.open_runs), cint(m.done_runs), m.last_done, m.runs or ""
		# runs record output in their own unit; compare quantities only when it is the order's unit
		r.same_unit = not m.uoms or (r.uom or "").upper() in (m.uoms or "").split(",")
		key = r.set_warehouse or (r.location or "").lower()
		if key not in factory:
			factory[key] = _needs_production(r.set_warehouse, r.location)
		r.production = factory[key] or bool(r.runs)
		r.pending_dispatch = max(flt(r.ordered) - flt(r.dispatched), 0)
		r.flags = _flags(r, tol, ready_days)
	return rows


def _needs_production(set_warehouse, location):
	"""Same rule as manufacturing_site.so_needs_production, without loading each order."""
	from instabiz.overrides.manufacturing_site import is_factory, location_has_factory

	try:
		if set_warehouse:
			return bool(is_factory(set_warehouse))
		return bool(location and location_has_factory(location))
	except Exception:
		return False


def _flags(r, tol, ready_days):
	out = []
	ordered, produced, dispatched = flt(r.ordered), flt(r.produced), flt(r.dispatched)
	if dispatched > ordered * (1 + tol) + 1e-9:
		out.append("Over-dispatched")
	if not r.production or not r.same_unit:
		return out
	if dispatched > 0 and not r.done_runs:
		if r.open_runs or r.runs:
			out.append("Dispatched without production")
	elif r.done_runs and dispatched > produced * (1 + tol) + 1e-9:
		out.append("Dispatched more than produced")
	if r.done_runs and not r.open_runs:
		if produced < ordered * (1 - tol) and dispatched < ordered * (1 - tol):
			out.append("Produced short")
		elif produced > ordered * (1 + tol):
			out.append("Produced over")
	if (r.done_runs and not r.open_runs and r.last_done and produced > 0 and dispatched < produced * (1 - tol)
			and get_datetime(r.last_done) < add_days(now_datetime(), -ready_days)):
		out.append("Ready, not dispatched")
	return out


def _explain(r, flag):
	return _("{0}: {1} {2} — ordered {3}, produced {4}, in run {5}, dispatched {6} {7}").format(
		flag, r.sales_order, r.item_code, _q(r.ordered), _q(r.produced), _q(r.in_run), _q(r.dispatched), r.uom or "")


def _q(v):
	return f"{flt(v):g}"


def _alert(rows, only=None):
	"""Comment on the order + bell (once per line and flag)."""
	notify = get_check("reco_notify", True)
	managers = None
	for r in rows:
		for flag in r.flags:
			if only and flag not in only:
				continue
			mark = MARK.format(r.so_detail, frappe.scrub(flag))
			if frappe.db.exists("Comment", {"reference_doctype": "Sales Order", "reference_name": r.sales_order,
					"content": ["like", f"%{mark}%"]}):
				continue
			text = _explain(r, flag)
			frappe.get_doc({"doctype": "Comment", "comment_type": "Info", "reference_doctype": "Sales Order",
				"reference_name": r.sales_order, "content": f"{text} {mark}"}).insert(ignore_permissions=True)
			if not notify:
				continue
			if managers is None:
				managers = _users_with(NOTIFY_ROLES)
			for user in set(managers) | ({r.sales_person} if r.sales_person else set()):
				frappe.get_doc({"doctype": "Notification Log", "for_user": user, "type": "Alert",
					"subject": text[:140], "document_type": "Sales Order", "document_name": r.sales_order,
					"email_content": text}).insert(ignore_permissions=True)


def _users_with(roles):
	return [u for u in frappe.get_all("Has Role", filters={"role": ["in", list(roles)], "parenttype": "User"},
		pluck="parent", distinct=True) if u != "Administrator" and frappe.db.get_value("User", u, "enabled")]


# ── triggers ───────────────────────────────────────────────────────────────────

def check_delivery_note(doc, method=None):
	"""Delivery Note on_submit: the lines just shipped."""
	sods = [r.so_detail for r in doc.items if r.get("so_detail")]
	if not sods:
		return
	try:
		_alert(lines(so_details=sods), only={"Over-dispatched", "Dispatched more than produced",
			"Dispatched without production"})
	except Exception:
		frappe.log_error(title="IB order reconciliation (DN)", message=frappe.get_traceback())


def check_run(doc, method=None):
	"""IB Work Order on_update: once a run completes, compare what it made with the order."""
	if doc.status != "Completed" or not doc.has_value_changed("status"):
		return
	sods = [o.sales_order_item for o in doc.get("outputs") or [] if o.get("sales_order_item")]
	if not sods:
		return
	try:
		_alert(lines(so_details=sods), only={"Produced short", "Produced over", "Dispatched more than produced"})
	except Exception:
		frappe.log_error(title="IB order reconciliation (run)", message=frappe.get_traceback())


def run_daily():
	"""Scheduler: lines made but not shipped after the set days (and anything else still open)."""
	sos = frappe.db.sql_list("""SELECT DISTINCT wo.sales_order FROM `tabIB Work Order` wo
		WHERE wo.status = 'Completed' AND wo.completed_at >= %s AND IFNULL(wo.sales_order, '') != ''""",
		add_days(now_datetime(), -90))
	if sos:
		_alert(lines(sales_orders=sos))
