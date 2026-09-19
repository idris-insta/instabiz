"""instabiz.overrides.briefing — the 9 AM morning briefing.

One message a day to the roles in IB Messaging Settings (default System Manager,
Sales Manager, Accounts Manager, Factory Management) with only what needs action:
  orders      yesterday's new orders; orders past their delivery date
  production  runs on hold; runs with no movement for 2 days; stages above wastage norm
  stock       items short for open orders (projected qty below zero)
  money       yesterday's collections; customers owing above the limit
  approvals   everything waiting in IB Pending Approvals
  customers   big customers (last 12 months) with no order for 45+ days
When there is Claude credit, three lines "act on this first" go on top.
Sent as a bell (full briefing inside) and by email when an outgoing account exists.
"""
import frappe
from frappe import _
from frappe.utils import add_days, flt, fmt_money, getdate, now_datetime, nowdate

from instabiz.overrides import ib_settings, llm

DEFAULT_ROLES = ["System Manager", "Sales Manager", "Accounts Manager", "Factory Management"]


def _money(v):
	return fmt_money(flt(v), precision=0, currency="INR")


def collect():
	from instabiz.overrides.ib_status import stored_statuses

	today = getdate(nowdate())
	yday = add_days(today, -1)
	S = []

	# orders
	new = frappe.db.sql("""SELECT COUNT(*), COALESCE(SUM(base_grand_total), 0) FROM `tabSales Order`
		WHERE docstatus = 1 AND transaction_date = %s""", yday)[0]
	closed = stored_statuses("Sales Order", "Completed", "Closed", "Cancelled")
	late = frappe.db.sql("""SELECT name, customer_name, delivery_date, base_grand_total FROM `tabSales Order`
		WHERE docstatus = 1 AND delivery_date < %s AND IFNULL(per_delivered, 0) < 100 AND status NOT IN %s
		ORDER BY delivery_date LIMIT 200""", (today, closed), as_dict=True)
	S.append({"title": _("Orders"), "items": [
		_("{0} new orders yesterday, {1}").format(int(new[0]), _money(new[1])),
		_("{0} orders past their delivery date").format(len(late)) + (
			": " + "; ".join(f"{r.name} {r.customer_name} (due {frappe.utils.formatdate(r.delivery_date)})" for r in late[:5])
			if late else ""),
	], "count": len(late)})

	# production
	hold = frappe.get_all("IB Work Order", filters={"status": "On Hold"}, fields=["name", "current_stage"], limit=50)
	stuck = frappe.get_all("IB Work Order", filters={"status": "In Progress", "modified": ["<", add_days(now_datetime(), -2)]},
		fields=["name", "current_stage"], limit=50)
	from instabiz.overrides.wastage_watch import norm_for

	events = frappe.db.sql("""SELECT e.parent, e.stage, e.machine, e.wastage_pct FROM `tabIB WO Stage Event` e
		WHERE e.skipped = 0 AND DATE(e.completed_at) = %s""", yday, as_dict=True)
	over = [e for e in events if flt(e.wastage_pct) > norm_for(e.machine)]
	prod = []
	if hold:
		prod.append(_("{0} runs on hold: {1}").format(len(hold), ", ".join(f"{h.name} ({h.current_stage})" for h in hold[:5])))
	if stuck:
		prod.append(_("{0} runs with no movement for 2 days: {1}").format(len(stuck), ", ".join(
			f"{h.name} ({h.current_stage})" for h in stuck[:5])))
	if over:
		prod.append(_("{0} stages above wastage norm yesterday: {1}").format(len(over), ", ".join(
			f"{e.parent} {e.stage} {flt(e.wastage_pct)}%" for e in over[:5])))
	S.append({"title": _("Production"), "items": prod or [_("Nothing stuck.")], "count": len(hold) + len(stuck) + len(over)})

	# stock
	short = frappe.db.sql("""SELECT item_code, warehouse, projected_qty FROM `tabBin`
		WHERE projected_qty < 0 ORDER BY projected_qty LIMIT 200""", as_dict=True)
	S.append({"title": _("Stock"), "items": [_("{0} item-warehouses short for open orders").format(len(short)) + (
		": " + "; ".join(f"{r.item_code} @ {r.warehouse.split(' - ')[0]} {flt(r.projected_qty):g}" for r in short[:5])
		if short else "")], "count": len(short)})

	# money
	coll = frappe.db.sql("""SELECT COALESCE(SUM(base_received_amount), 0) FROM `tabPayment Entry`
		WHERE docstatus = 1 AND payment_type = 'Receive' AND posting_date = %s""", yday)[0][0]
	limit = ib_settings.get_float("briefing_min_overdue", 50000)
	owing = frappe.get_all("Customer", filters={"custom_outstanding_amount": [">", limit], "disabled": 0},
		fields=["name", "customer_name", "custom_outstanding_amount"], order_by="custom_outstanding_amount desc", limit=200) \
		if frappe.db.has_column("Customer", "custom_outstanding_amount") else []
	S.append({"title": _("Money"), "items": [
		_("Collected yesterday: {0}").format(_money(coll)),
		_("{0} customers owe more than {1}, total {2}").format(len(owing), _money(limit),
			_money(sum(flt(c.custom_outstanding_amount) for c in owing))) + (
			": " + "; ".join(f"{c.customer_name} {_money(c.custom_outstanding_amount)}" for c in owing[:5]) if owing else ""),
	], "count": len(owing)})

	# approvals
	try:
		from instabiz.overrides.approvals import get_pending

		pending = get_pending("Administrator")
	except Exception:
		pending = []
	if pending:
		kinds = {}
		for p in pending:
			kinds[p.kind] = kinds.get(p.kind, 0) + 1
		S.append({"title": _("Approvals"), "items": [", ".join(f"{n} {k}" for k, n in kinds.items())], "count": len(pending)})

	# big customers gone quiet
	quiet = frappe.db.sql("""SELECT customer, customer_name, SUM(base_grand_total) AS value, MAX(transaction_date) AS last
		FROM `tabSales Order` WHERE docstatus = 1 AND transaction_date >= %s GROUP BY customer, customer_name
		HAVING MAX(transaction_date) < %s ORDER BY value DESC LIMIT 5""", (add_days(today, -365), add_days(today, -45)), as_dict=True)
	if quiet:
		S.append({"title": _("Big customers gone quiet"), "items": ["; ".join(
			f"{q.customer_name} ({_money(q.value)} in 12 months, last {frappe.utils.formatdate(q.last)})" for q in quiet)],
			"count": len(quiet)})
	return S


def render(sections, ai=None):
	e = frappe.utils.escape_html
	html = [f"<h3 style='margin:0 0 8px'>{e(_('Morning briefing'))} — {frappe.utils.formatdate(nowdate())}</h3>"]
	if ai:
		html.append("<div style='background:#fdf1ec;border-left:3px solid #d97757;padding:8px 12px;margin-bottom:10px'>"
			f"<b>{e(_('Act on first'))}</b><br>{e(ai).replace(chr(10), '<br>')}</div>")
	for s in sections:
		html.append(f"<h4 style='margin:12px 0 4px'>{e(s['title'])}</h4><ul style='margin:0;padding-left:18px'>")
		html.extend(f"<li>{e(i)}</li>" for i in s["items"])
		html.append("</ul>")
	return "".join(html)


def _text(sections):
	return "\n".join(f"{s['title']}: " + " | ".join(s["items"]) for s in sections)


def _ai_summary(sections):
	if not ib_settings.get_check("briefing_use_ai", True) or not llm.is_enabled():
		return None
	return llm.complete(
		"You are the operations assistant of an Indian adhesive-tape manufacturer. From the briefing below, "
		"write exactly three short lines (no bullets, no preamble), each one concrete action for today with the "
		"name / number it concerns, most money or customer impact first. Use only facts in the briefing.",
		_text(sections), max_tokens=250)


def _recipients():
	raw = ib_settings.get("briefing_roles", "") or ""
	roles = [r.strip() for r in raw.replace(",", "\n").splitlines() if r.strip()] or DEFAULT_ROLES
	users = set(frappe.get_all("Has Role", filters={"role": ["in", roles], "parenttype": "User"}, pluck="parent"))
	return sorted(u for u in users if u not in ("Administrator", "Guest")
		and frappe.db.get_value("User", u, ["enabled", "user_type"]) == (1, "System User"))


def build():
	sections = collect()
	ai = _ai_summary(sections)
	headline = ", ".join(f"{s['count']} {s['title'].lower()}" for s in sections if s.get("count"))
	return {"sections": sections, "ai": ai, "html": render(sections, ai),
		"subject": (_("Morning briefing: ") + (headline or _("all clear")))[:140]}


def run_morning_briefing():
	if not ib_settings.get_check("morning_briefing", True):
		return
	b = build()
	users = _recipients()
	for u in users:
		frappe.get_doc({"doctype": "Notification Log", "for_user": u, "type": "Alert", "subject": b["subject"],
			"email_content": b["html"]}).insert(ignore_permissions=True)
	if users and frappe.db.exists("Email Account", {"enable_outgoing": 1, "default_outgoing": 1}):
		emails = [e for e in (frappe.db.get_value("User", u, "email") for u in users) if e]
		try:
			frappe.sendmail(recipients=emails, subject=b["subject"], message=b["html"])
		except Exception:
			frappe.log_error("IB morning briefing email", frappe.get_traceback())
	frappe.db.commit()


@frappe.whitelist()
def preview(send=0):
	frappe.only_for(["System Manager", "Sales Manager", "Accounts Manager", "Factory Management"])
	if frappe.utils.cint(send):
		run_morning_briefing()
	return build()
