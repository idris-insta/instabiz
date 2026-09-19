"""IB Gate Pass Register — every gate pass for the dates with its items, and
returnables still out with days out."""
import frappe
from frappe import _
from frappe.utils import date_diff, flt, today


def execute(filters=None):
	f = frappe._dict(filters or {})
	cond, args = ["gp.docstatus = 1", "gp.posting_date BETWEEN %(from_date)s AND %(to_date)s"], {"from_date": f.from_date, "to_date": f.to_date}
	for k in ("gate_pass_type", "purpose", "location", "party"):
		if f.get(k):
			cond.append(f"gp.{k} = %({k})s")
			args[k] = f.get(k)
	if f.vehicle_no:
		cond.append("gp.vehicle_no LIKE %(vehicle)s")
		args["vehicle"] = f"%{f.vehicle_no}%"
	if f.only_pending:
		cond.append("gp.status IN ('Open', 'Partly Returned')")
	rows = frappe.db.sql(f"""SELECT gp.name, gp.posting_date, gp.gate_time, gp.gate_pass_type, gp.purpose, gp.location, gp.party_name,
		gp.vehicle_no, gp.driver_name, gp.lr_no, gp.reference_doctype, gp.reference_name, gp.status, gp.expected_return_date,
		i.item_code, i.description, i.qty, i.uom, i.returned_qty, i.packages
		FROM `tabIB Gate Pass` gp JOIN `tabIB Gate Pass Item` i ON i.parent = gp.name
		WHERE {' AND '.join(cond)} ORDER BY gp.posting_date DESC, gp.name, i.idx""", args, as_dict=True)
	for r in rows:
		r.pending = flt(r.qty) - flt(r.returned_qty) if r.status in ("Open", "Partly Returned") else 0
		r.days_out = date_diff(today(), r.posting_date) if r.pending else None
		r.late = bool(r.pending and r.expected_return_date and str(r.expected_return_date) < today())
	cols = [{"label": _("Gate Pass"), "fieldname": "name", "fieldtype": "Link", "options": "IB Gate Pass", "width": 140},
		{"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 95},
		{"label": _("In / Out"), "fieldname": "gate_pass_type", "fieldtype": "Data", "width": 75},
		{"label": _("Purpose"), "fieldname": "purpose", "fieldtype": "Data", "width": 110},
		{"label": _("Party"), "fieldname": "party_name", "fieldtype": "Data", "width": 170},
		{"label": _("Vehicle"), "fieldname": "vehicle_no", "fieldtype": "Data", "width": 110},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 150},
		{"label": _("Qty"), "fieldname": "qty", "fieldtype": "Float", "width": 80},
		{"label": _("UOM"), "fieldname": "uom", "fieldtype": "Data", "width": 60},
		{"label": _("Returned"), "fieldname": "returned_qty", "fieldtype": "Float", "width": 80},
		{"label": _("Pending"), "fieldname": "pending", "fieldtype": "Float", "width": 80},
		{"label": _("Days Out"), "fieldname": "days_out", "fieldtype": "Int", "width": 75},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 110},
		{"label": _("Against"), "fieldname": "reference_name", "fieldtype": "Dynamic Link", "options": "reference_doctype", "width": 150},
		{"label": _("Type"), "fieldname": "reference_doctype", "fieldtype": "Data", "hidden": 1}]
	passes = {r.name for r in rows}
	summary = [{"label": _("Gate passes"), "value": len(passes), "datatype": "Int"},
		{"label": _("Vehicles"), "value": len({r.vehicle_no for r in rows}), "datatype": "Int"},
		{"label": _("Returnables still out"), "value": len({r.name for r in rows if r.pending}), "datatype": "Int", "indicator": "orange"},
		{"label": _("Past return date"), "value": len({r.name for r in rows if r.late}), "datatype": "Int", "indicator": "red"}]
	return cols, rows, None, None, summary
