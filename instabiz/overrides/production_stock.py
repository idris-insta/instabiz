"""instabiz.overrides.production_stock

When a production run finishes, post it to stock (IB Stock Settings →
"Post production to stock", on by default):

  one Repack Stock Entry per run
    out  the run's source material — source item × source qty, from the run's
         source warehouse (the jumbo / film actually loaded, wastage included)
    out  anything else the finished item's IB Production Recipe lists (core,
         carton, adhesive…), recipe qty × produced qty
    in   every output — produced qty in its unit, into the finished-goods
         warehouse for the location (IB Stock Settings) or the source warehouse

ERPNext spreads the cost of what went out over what came in, so finished goods
carry the real material cost including wastage. Machine time is added on top as
an additional cost: hours of each stage × the machine's Running Cost per Hour
(or IB Stock Settings default), booked to Expenses Included In Valuation. If the entry can't be
submitted (short stock, missing conversion…) it is kept as a draft, the run
still completes, and stock managers get a bell with the reason. Cancelling the
run cancels / deletes the entry.
"""
import frappe
from frappe import _
from frappe.utils import flt

from instabiz.overrides import ib_settings
from instabiz.overrides.utils import roll_area

LOC_FIELD = {"maharashtra": "fg_warehouse_maharashtra", "gujarat": "fg_warehouse_gujarat", "chennai": "fg_warehouse_chennai"}


def _leaf_warehouse(wh):
	"""A group warehouse (e.g. GUJARAT - IB) → its first real warehouse."""
	if not wh or not frappe.db.get_value("Warehouse", wh, "is_group"):
		return wh
	lft, rgt = frappe.db.get_value("Warehouse", wh, ["lft", "rgt"])
	return frappe.db.get_value("Warehouse", {"lft": [">", lft], "rgt": ["<", rgt], "is_group": 0, "disabled": 0}, "name", order_by="lft")


def _source_warehouse(doc):
	from instabiz.overrides.production_run import _batch_source_warehouse
	from instabiz.overrides.utils import LOCATION_WAREHOUSE

	wh = doc.source_warehouse or (doc.source_batch and _batch_source_warehouse(doc.source_batch))
	return _leaf_warehouse(wh or LOCATION_WAREHOUSE.get((doc.location or "").lower()))


def _stock_qty(item_code, qty, uom):
	from erpnext.stock.get_item_details import get_conversion_factor

	stock_uom = frappe.get_cached_value("Item", item_code, "stock_uom")
	if not uom or uom == stock_uom:
		return flt(qty)
	cf = flt((get_conversion_factor(item_code, uom) or {}).get("conversion_factor"))
	return flt(qty) * cf if cf else flt(qty)


def build_entry(doc):
	src_wh = _source_warehouse(doc)
	fg_wh = _leaf_warehouse(ib_settings.get(LOC_FIELD.get((doc.location or "").lower(), ""), None)) or src_wh
	company = frappe.db.get_value("Warehouse", src_wh or fg_wh, "company") or frappe.db.get_single_value("Global Defaults", "default_company")
	se = frappe.new_doc("Stock Entry")
	se.stock_entry_type = "Repack"
	se.purpose = "Repack"
	se.company = company
	se.posting_date = frappe.utils.today()
	se.remarks = _("Production run {0} ({1})").format(doc.name, doc.sales_order or doc.order_sheet or "")
	used = set()
	if doc.source_item and flt(doc.source_qty) > 0:
		se.append("items", {"item_code": doc.source_item, "qty": flt(doc.source_qty), "s_warehouse": src_wh})
		used.add(doc.source_item)
	extra = {}
	for o in doc.outputs:
		if flt(o.produced_qty) <= 0:
			continue
		area = roll_area(o.item_code, o.uom, o.width_mm, o.length_mtr)
		stock_out = flt(o.produced_qty) * area if area else _stock_qty(o.item_code, o.produced_qty, o.uom)
		for r in frappe.get_all("IB Production Recipe", filters={"finished_item": o.item_code},
				fields=["recipe_item", "qty_per"]):
			if r.recipe_item not in used:
				extra[r.recipe_item] = extra.get(r.recipe_item, 0) + flt(r.qty_per) * stock_out
	for item, qty in extra.items():
		if qty > 0:
			se.append("items", {"item_code": item, "qty": round(qty, 3), "s_warehouse": src_wh})
	consumed = len(se.items)
	for o in doc.outputs:
		if flt(o.produced_qty) > 0:
			row = {"item_code": o.item_code, "qty": flt(o.produced_qty), "t_warehouse": fg_wh, "is_finished_item": 1}
			if o.uom:
				row["uom"] = o.uom
				area = roll_area(o.item_code, o.uom, o.width_mm, o.length_mtr)
				if area:  # rolls of an SQMT item → m² per roll
					row["conversion_factor"] = area
			se.append("items", row)
	if consumed:
		_add_conversion_cost(se, doc, company)
	if not consumed:
		# nothing to take out (no source item, no recipe): receive the goods at their own rate
		se.stock_entry_type = se.purpose = "Material Receipt"
		for r in se.items:
			r.is_finished_item = 0
			if not flt(frappe.get_cached_value("Item", r.item_code, "valuation_rate")):
				r.allow_zero_valuation_rate = 1
	return se, consumed


def run_conversion_cost(doc):
	"""[(stage, machine, hours, rate, amount)] for the run's completed stages."""
	default_rate = ib_settings.get_float("default_machine_cost_per_hour", 0)
	out = []
	for ev in doc.get("stage_log") or []:
		if ev.skipped or not ev.started_at or not ev.completed_at:
			continue
		hours = max(frappe.utils.time_diff_in_seconds(ev.completed_at, ev.started_at), 0) / 3600.0
		rate = flt(ev.machine and frappe.get_cached_value("IB Machine", ev.machine, "cost_per_hour")) or default_rate
		if hours > 0 and rate > 0:
			out.append((ev.stage, ev.machine, round(hours, 2), rate, round(hours * rate, 2)))
	return out


def _add_conversion_cost(se, doc, company):
	lines = run_conversion_cost(doc)
	account = frappe.get_cached_value("Company", company, "expenses_included_in_valuation")
	if not lines or not account:
		return
	for stage, machine, hours, rate, amount in lines:
		se.append("additional_costs", {"expense_account": account, "amount": amount,
			"description": _("{0} on {1}: {2} h × ₹{3}").format(stage, machine or "-", hours, rate)})


def post_run_stock(doc):
	"""Called at the end of a run. Never raises; returns a short note for the completion message."""
	if not ib_settings.get_check("production_posts_stock", True) or doc.get("stock_entry"):
		return None
	if not any(flt(o.produced_qty) > 0 for o in doc.outputs):
		return None
	se, consumed = build_entry(doc)
	if not se.items:
		return None
	submit = (ib_settings.get("production_stock_mode", "Submit") or "Submit") == "Submit"
	frappe.db.savepoint("ib_run_stock")
	try:
		se.insert(ignore_permissions=True)
		if submit:
			se.submit()
		note = None if consumed else _("no source material or recipe — goods received only")
	except Exception as e:
		frappe.db.rollback(save_point="ib_run_stock")
		reason = frappe.utils.strip_html(str(e))[:300]
		se, _consumed = build_entry(doc)
		try:
			se.insert(ignore_permissions=True)
		except Exception:
			frappe.log_error("IB run stock entry", f"{doc.name}\n{frappe.get_traceback()}")
			_tell_stock(doc, None, reason)
			return _("stock not posted: {0}").format(reason)
		_tell_stock(doc, se.name, reason)
		note = _("stock entry {0} left as draft: {1}").format(se.name, reason)
	frappe.db.set_value("IB Work Order", doc.name, "stock_entry", se.name, update_modified=False)
	if se.docstatus == 0 and not note:
		note = _("stock entry {0} is a draft for the store to submit").format(se.name)
	return note


def _tell_stock(doc, entry, reason):
	users = {u for u in frappe.get_all("Has Role", filters={"role": ["in", ["Stock Manager", "Factory Management"]],
		"parenttype": "User"}, pluck="parent") if u != "Administrator" and frappe.db.get_value("User", u, "enabled")}
	subject = _("Run {0}: stock not posted — {1}").format(doc.name, reason)[:140]
	for u in users:
		frappe.get_doc({"doctype": "Notification Log", "for_user": u, "type": "Alert", "subject": subject,
			"document_type": "Stock Entry" if entry else "IB Work Order", "document_name": entry or doc.name}).insert(ignore_permissions=True)


def reverse_run_stock_entry(work_order):
	name = frappe.db.get_value("IB Work Order", work_order, "stock_entry")
	if not name or not frappe.db.exists("Stock Entry", name):
		return
	se = frappe.get_doc("Stock Entry", name)
	if se.docstatus == 1:
		se.flags.ignore_permissions = True
		se.cancel()
	elif se.docstatus == 0:
		frappe.delete_doc("Stock Entry", name, ignore_permissions=True)
	frappe.db.set_value("IB Work Order", work_order, "stock_entry", None, update_modified=False)
