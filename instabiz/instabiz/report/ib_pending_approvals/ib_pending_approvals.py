"""IB Pending Approvals — everything waiting on an approver in one place:
journal entries and payments sent for approval, advances on orders, leave,
overtime and expense claims. Journal / payment rows can be approved or
rejected right here; the others open their document."""
import frappe
from frappe import _

from instabiz.overrides.approvals import get_pending


def execute(filters=None):
	f = frappe._dict(filters or {})
	rows = get_pending()
	if f.kind:
		rows = [r for r in rows if r.kind == f.kind]
	if f.only_mine:
		rows = [r for r in rows if r.can_act]
	for r in rows:
		r.action = r.name if r.can_act else ""
	cols = [
		{"label": _("What"), "fieldname": "kind", "fieldtype": "Data", "width": 140},
		{"label": _("Type"), "fieldname": "doctype", "fieldtype": "Data", "hidden": 1},
		{"label": _("Document"), "fieldname": "name", "fieldtype": "Dynamic Link", "options": "doctype", "width": 170},
		{"label": _("Date"), "fieldname": "date", "fieldtype": "Date", "width": 95},
		{"label": _("Party / Employee"), "fieldname": "who", "fieldtype": "Data", "width": 200},
		{"label": _("Amount / Days / Hours"), "fieldname": "amount", "fieldtype": "Float", "width": 130},
		{"label": _("Made By"), "fieldname": "by", "fieldtype": "Link", "options": "User", "width": 170},
		{"label": _("Action"), "fieldname": "action", "fieldtype": "Data", "width": 170},
	]
	kinds = {}
	for r in rows:
		kinds[r.kind] = kinds.get(r.kind, 0) + 1
	summary = [{"label": k, "value": v, "datatype": "Int", "indicator": "orange"} for k, v in kinds.items()] or [
		{"label": _("Waiting"), "value": 0, "datatype": "Int", "indicator": "green"}]
	return cols, rows, None, None, summary


@frappe.whitelist()
def pending_count():
	"""Number card: items the current user can act on."""
	return sum(1 for r in get_pending() if r.can_act)
