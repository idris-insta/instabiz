"""IB Goods In Transit — branch transfers that have left and not fully arrived:
from / to, items, qty and value still on the road, vehicle, LR and days out."""
import frappe
from frappe import _
from frappe.utils import date_diff, flt, today


def execute(filters=None):
	f = frappe._dict(filters or {})
	cond, args = "", {}
	if f.from_warehouse:
		cond += " AND se.from_warehouse = %(fw)s"
		args["fw"] = f.from_warehouse
	if f.to_warehouse:
		cond += " AND se.custom_final_warehouse = %(tw)s"
		args["tw"] = f.to_warehouse
	rows = frappe.db.sql(
		f"""SELECT se.name, se.posting_date, se.from_warehouse, se.custom_final_warehouse AS to_warehouse,
		       se.vehicle_no, se.lr_no, se.ewaybill, se.per_transferred,
		       GROUP_CONCAT(sed.item_code SEPARATOR ', ') AS items,
		       SUM(sed.transfer_qty - IFNULL(sed.transferred_qty, 0)) AS qty_pending,
		       SUM((sed.transfer_qty - IFNULL(sed.transferred_qty, 0)) * sed.valuation_rate) AS value_pending
		FROM `tabStock Entry` se JOIN `tabStock Entry Detail` sed ON sed.parent = se.name
		WHERE se.docstatus = 1 AND se.add_to_transit = 1 AND IFNULL(se.per_transferred, 0) < 100 {cond}
		GROUP BY se.name ORDER BY se.posting_date""", args, as_dict=True)
	for r in rows:
		r.days = date_diff(today(), r.posting_date)
		r.receive = r.name
	cols = [
		{"label": _("Dispatched"), "fieldname": "posting_date", "fieldtype": "Date", "width": 95},
		{"label": _("Entry"), "fieldname": "name", "fieldtype": "Link", "options": "Stock Entry", "width": 170},
		{"label": _("From"), "fieldname": "from_warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 170},
		{"label": _("To"), "fieldname": "to_warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 170},
		{"label": _("Items"), "fieldname": "items", "fieldtype": "Data", "width": 220},
		{"label": _("Qty Pending"), "fieldname": "qty_pending", "fieldtype": "Float", "width": 100},
		{"label": _("Value Pending"), "fieldname": "value_pending", "fieldtype": "Currency", "width": 120},
		{"label": _("Vehicle"), "fieldname": "vehicle_no", "fieldtype": "Data", "width": 100},
		{"label": _("LR"), "fieldname": "lr_no", "fieldtype": "Data", "width": 90},
		{"label": _("E-Way Bill"), "fieldname": "ewaybill", "fieldtype": "Data", "width": 110},
		{"label": _("Days"), "fieldname": "days", "fieldtype": "Int", "width": 60},
		{"label": _("Receive"), "fieldname": "receive", "fieldtype": "Data", "width": 90},
	]
	summary = [
		{"label": _("Transfers on the road"), "value": len(rows), "datatype": "Int"},
		{"label": _("Value in transit"), "value": sum(flt(r.value_pending) for r in rows), "datatype": "Currency"},
		{"label": _("Older than 7 days"), "value": sum(1 for r in rows if r.days > 7), "datatype": "Int",
			"indicator": "red" if any(r.days > 7 for r in rows) else "green"},
	]
	return cols, rows, None, None, summary
