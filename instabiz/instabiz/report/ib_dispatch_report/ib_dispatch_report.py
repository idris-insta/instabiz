"""IB Dispatch Report — daily dispatch summary with item, LR, transporter details."""
import frappe
from frappe import _
from frappe.utils import getdate, today, flt
from instabiz.overrides.naming import LOCATION_CODE_MAP


def _location_from_warehouse(warehouse):
	if not warehouse:
		return ""
	loc = warehouse.split(" - ")[0].strip().lower()
	for key, code in LOCATION_CODE_MAP.items():
		if key in loc or loc in key:
			return code
	return warehouse.split(" - ")[0].strip()


def execute(filters=None):
	filters = filters or {}
	from instabiz.overrides.own_data import locked_user

	if locked_user():
		filters["sales_person_user"] = locked_user()  # a plain Sales User sees only their own
	data = _data(filters)
	columns = _columns()
	return columns, data, None, _chart(data, filters), _summary(data)


def _columns():
	return [
		{"label": _("DN"),             "fieldname": "name",           "fieldtype": "Link",     "options": "Delivery Note", "width": 160},
		{"label": _("Date"),           "fieldname": "posting_date",   "fieldtype": "Date",     "width": 100},
		{"label": _("Customer"),       "fieldname": "customer",       "fieldtype": "Link",     "options": "Customer", "width": 180},
		{"label": _("Location"),       "fieldname": "custom_location","fieldtype": "Data",     "width": 110},
		{"label": _("Transporter"),    "fieldname": "transporter_name","fieldtype": "Data",    "width": 160},
		{"label": _("LR Number"),      "fieldname": "lr_number",      "fieldtype": "Data",     "width": 130},
		{"label": _("Items"),          "fieldname": "items_summary",  "fieldtype": "Data",     "width": 240},
		{"label": _("Total Qty"),      "fieldname": "total_qty",      "fieldtype": "Float",    "width": 100},
		{"label": _("Value"),          "fieldname": "grand_total",    "fieldtype": "Currency", "width": 130},
		{"label": _("Sales Person"),   "fieldname": "sales_person",   "fieldtype": "Data",     "width": 150},
	]


def _data(filters):
	date       = getdate(filters.get("date") or today())
	warehouse  = filters.get("warehouse")
	sp_user    = filters.get("sales_person_user")

	wh_cond = "AND dn.set_warehouse = %(warehouse)s" if warehouse else ""
	sp_cond = "AND dn.custom_sales_person_user = %(sp_user)s" if sp_user else ""

	dns = frappe.db.sql(
		f"""
		SELECT
			dn.name,
			dn.posting_date,
			dn.customer,
			dn.set_warehouse,
			dn.transporter_name,
			COALESCE(NULLIF(dn.custom_lr_number,''), dn.lr_no) AS lr_number,
			dn.total_qty,
			dn.grand_total,
			dn.custom_sales_person_user,
			dn.custom_sales_person
		FROM `tabDelivery Note` dn
		WHERE dn.docstatus = 1
		AND dn.posting_date = %(date)s
		AND dn.is_return = 0
		{wh_cond}
		{sp_cond}
		ORDER BY dn.name
		""",
		{"date": date, "warehouse": warehouse, "sp_user": sp_user},
		as_dict=True,
	)

	if not dns:
		return []

	# Fetch item summaries per DN
	dn_names  = [d.name for d in dns]
	placeholders = ", ".join(["%s"] * len(dn_names))
	items = frappe.db.sql(
		f"""
		SELECT parent, item_code, item_name, qty, uom
		FROM `tabDelivery Note Item`
		WHERE parent IN ({placeholders}) AND docstatus = 1
		ORDER BY parent, idx
		""",
		dn_names,
		as_dict=True,
	)
	item_map = {}
	for it in items:
		item_map.setdefault(it.parent, []).append(f"{it.item_code} × {flt(it.qty,2)} {it.uom}")

	rows = []
	for d in dns:
		rows.append({
			"name":           d.name,
			"posting_date":   d.posting_date,
			"customer":       d.customer,
			"custom_location":_location_from_warehouse(d.set_warehouse),
			"transporter_name": d.transporter_name or "",
			"lr_number":      d.lr_number or "",
			"items_summary":  " | ".join(item_map.get(d.name, [])),
			"total_qty":      flt(d.total_qty),
			"grand_total":    flt(d.grand_total),
			"sales_person":   d.custom_sales_person or d.custom_sales_person_user or "",
		})
	return rows


def _chart(data, filters=None):
	if not data:
		return None
	chart_type = (filters or {}).get("chart_type") or "bar"
	# Group by transporter
	by_transporter = {}
	for r in data:
		t = r["transporter_name"] or "Unknown"
		by_transporter[t] = by_transporter.get(t, 0) + 1
	top = sorted(by_transporter.items(), key=lambda x: -x[1])[:8]
	return {
		"data": {
			"labels":   [t for t, _ in top],
			"datasets": [{"name": _("Dispatches"), "values": [c for _, c in top]}],
		},
		"type": chart_type,
		"colors": ["#d97757"],
	}


def _summary(data):
	if not data:
		return None
	return [
		{"value": len(data),                    "label": _("Total Dispatches"), "datatype": "Int",      "indicator": "blue"},
		{"value": sum(r["total_qty"] for r in data), "label": _("Total Qty"),   "datatype": "Float",    "indicator": "orange"},
		{"value": sum(r["grand_total"] for r in data),"label": _("Total Value"),"datatype": "Currency", "indicator": "green"},
		{"value": len({r["transporter_name"] for r in data if r["transporter_name"]}),
		                                         "label": _("Transporters"),    "datatype": "Int",      "indicator": "purple"},
	]
