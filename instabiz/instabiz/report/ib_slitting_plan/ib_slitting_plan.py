"""IB Slitting Plan — see instabiz.overrides.slitting_plan."""
import frappe
from frappe import _

from instabiz.overrides.production import _require_production_role
from instabiz.overrides.slitting_plan import plan


def execute(filters=None):
	_require_production_role()
	f = frappe._dict(filters or {})
	res = plan(location=f.location, order_sheet=f.order_sheet, source_batch=f.source_batch)
	data = res["rows"]
	if f.show_unplanned:
		data = data + [{**u, "pass_no": None, "widths": f"{u.get('width_mm') or 0:g}", "note": u["reason"],
			"items": f"{u['item_code']} ×{u['planned_qty']:g}"} for u in res["unplanned"]]
	cols = [
		{"label": _("Order Sheet"), "fieldname": "order_sheet", "fieldtype": "Link", "options": "IB Order Sheet", "width": 140},
		{"label": _("Sales Order"), "fieldname": "sales_order", "fieldtype": "Link", "options": "Sales Order", "width": 140},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 160},
		{"label": _("Delivery"), "fieldname": "delivery_date", "fieldtype": "Date", "width": 90},
		{"label": _("Jumbo Batch"), "fieldname": "source_batch", "fieldtype": "Link", "options": "IB Batch", "width": 170},
		{"label": _("Jumbo mm"), "fieldname": "jumbo_width", "fieldtype": "Float", "width": 85},
		{"label": _("Pass"), "fieldname": "pass_no", "fieldtype": "Int", "width": 55},
		{"label": _("Widths (mm)"), "fieldname": "widths", "fieldtype": "Data", "width": 170},
		{"label": _("Trim mm"), "fieldname": "trim_mm", "fieldtype": "Float", "width": 80},
		{"label": _("Trim %"), "fieldname": "trim_pct", "fieldtype": "Percent", "width": 75},
		{"label": _("Items"), "fieldname": "items", "fieldtype": "Data", "width": 260},
		{"label": _("Not planned because"), "fieldname": "note", "fieldtype": "Data", "width": 240},
		{"label": _("Action"), "fieldname": "action", "fieldtype": "Data", "width": 110},
		{"label": "osi", "fieldname": "osi", "fieldtype": "Data", "hidden": 1},
	]
	passes = res["rows"]
	total_w = sum(r["jumbo_width"] for r in passes)
	summary = [
		{"label": _("Passes"), "value": len(passes), "datatype": "Int"},
		{"label": _("Trim waste"), "value": round(sum(r["trim_mm"] for r in passes) / total_w * 100, 2) if total_w else 0,
			"datatype": "Percent"},
		{"label": _("Lines not planned"), "value": len(res["unplanned"]), "datatype": "Int",
			"indicator": "orange" if res["unplanned"] else "green"},
		{"label": _("Edge trim / knives"), "value": f"{res['trim_mm']:g} mm / {res['knives'] or '∞'}", "datatype": "Data"},
	]
	msg = None
	if not passes and not res["unplanned"]:
		msg = _("No open order lines that need slitting.")
	return cols, data, msg, None, summary
