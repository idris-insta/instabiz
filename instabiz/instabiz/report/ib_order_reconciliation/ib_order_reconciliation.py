"""IB Order Reconciliation — each Sales Order line: ordered, produced by finished
runs, still in a run, dispatched, pending, and the flags from
instabiz.overrides.production_reco (differences beyond the tolerance in
IB Stock Settings)."""
import frappe
from frappe import _
from frappe.utils import getdate

from instabiz.overrides.production_reco import lines


def execute(filters=None):
	f = frappe._dict(filters or {})
	from instabiz.overrides.own_data import locked_user

	own = locked_user()
	rows = lines(open_only=not f.include_closed, from_date=f.from_date, to_date=f.to_date, sales_person=own)
	out = []
	for r in rows:
		if own and r.sales_person != own:
			continue
		if f.from_date and getdate(r.transaction_date) < getdate(f.from_date):
			continue
		if f.to_date and getdate(r.transaction_date) > getdate(f.to_date):
			continue
		if any(f.get(key) and r.get(key) != f.get(key) for key in ("customer", "item_code", "sales_order")):
			continue
		if f.location and (r.location or "").upper() != f.location.upper():
			continue
		if f.flag and f.flag not in r.flags:
			continue
		if f.only_flagged and not r.flags:
			continue
		if f.production_only and not r.production:
			continue
		out.append(dict(r, flag=" | ".join(r.flags), status=_status(r)))
	flagged = [r for r in out if r["flag"]]
	summary = [
		{"label": _("Lines"), "value": len(out), "datatype": "Int"},
		{"label": _("Flagged"), "value": len(flagged), "datatype": "Int", "indicator": "red" if flagged else "green"},
		{"label": _("Ready, not dispatched"), "value": sum(1 for r in out if "Ready, not dispatched" in r["flag"]),
			"datatype": "Int", "indicator": "orange"},
		{"label": _("Dispatched more than produced"), "value": sum(1 for r in out if "more than produced" in r["flag"]),
			"datatype": "Int", "indicator": "red"},
	]
	counts = {}
	for r in flagged:
		for fl in r["flag"].split(" | "):
			counts[fl] = counts.get(fl, 0) + 1
	chart = {"data": {"labels": list(counts), "datasets": [{"name": _("Lines"), "values": list(counts.values())}]},
		"type": "bar", "colors": ["#d97757"]} if counts else None
	return _columns(), out, None, chart, summary


def _status(r):
	if r.dispatched >= r.ordered and r.ordered:
		return _("Dispatched")
	if r.open_runs:
		return _("In production")
	if r.produced:
		return _("Made — to dispatch")
	return _("Not started") if r.production else _("From stock")


def _columns():
	flt = lambda label, fn, w=95: {"label": label, "fieldname": fn, "fieldtype": "Float", "width": w}
	return [
		{"label": _("Sales Order"), "fieldname": "sales_order", "fieldtype": "Link", "options": "Sales Order", "width": 150},
		{"label": _("Date"), "fieldname": "transaction_date", "fieldtype": "Date", "width": 95},
		{"label": _("Customer"), "fieldname": "customer_name", "fieldtype": "Data", "width": 180},
		{"label": _("Location"), "fieldname": "location", "fieldtype": "Data", "width": 95},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 160},
		{"label": _("UOM"), "fieldname": "uom", "fieldtype": "Data", "width": 60},
		flt(_("Ordered"), "ordered"), flt(_("Produced"), "produced"), flt(_("In Run"), "in_run", 80),
		flt(_("Dispatched"), "dispatched"), flt(_("To Dispatch"), "pending_dispatch"),
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 120},
		{"label": _("Flag"), "fieldname": "flag", "fieldtype": "Data", "width": 240},
		{"label": _("Runs"), "fieldname": "runs", "fieldtype": "Data", "width": 160},
	]
