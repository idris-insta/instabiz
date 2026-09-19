"""IB SKU Report — sales performance per item code."""
import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = filters or {}
	from instabiz.overrides.own_data import locked_user

	if locked_user():
		filters["sales_person_user"] = locked_user()  # a plain Sales User sees only their own
	data    = _data(filters)
	columns = _columns()
	return columns, data, None, _chart(data, filters), _summary(data)


def _columns():
	return [
		{"label": _("Item Code"),    "fieldname": "item_code",   "fieldtype": "Link",     "options": "Item",  "width": 160},
		{"label": _("Item Name"),    "fieldname": "item_name",   "fieldtype": "Data",     "width": 220},
		{"label": _("Item Group"),   "fieldname": "item_group",  "fieldtype": "Link",     "options": "Item Group", "width": 140},
		{"label": _("UOM"),          "fieldname": "uom",         "fieldtype": "Data",     "width": 70},
		{"label": _("Orders"),       "fieldname": "orders",      "fieldtype": "Int",      "width": 90},
		{"label": _("Qty Sold"),     "fieldname": "qty_sold",    "fieldtype": "Float",    "width": 110},
		{"label": _("Revenue"),      "fieldname": "revenue",     "fieldtype": "Currency", "width": 150},
		{"label": _("Avg Rate"),     "fieldname": "avg_rate",    "fieldtype": "Currency", "width": 120},
		{"label": _("Customers"),    "fieldname": "customers",   "fieldtype": "Int",      "width": 100},
	]


def _data(filters):
	from_date    = filters.get("from_date")
	to_date      = filters.get("to_date")
	territory    = filters.get("territory")
	item_group   = filters.get("item_group")
	customer     = filters.get("customer")
	sales_person = filters.get("sales_person_user")

	terr_cond = "AND so.territory = %(territory)s"                        if territory    else ""
	ig_cond   = "AND i.item_group = %(item_group)s"                       if item_group   else ""
	cust_cond = "AND so.customer = %(customer)s"                          if customer     else ""
	sp_cond   = "AND so.custom_sales_person_user = %(sales_person_user)s" if sales_person  else ""

	rows = frappe.db.sql(
		f"""
		SELECT
			soi.item_code,
			soi.item_name,
			i.item_group,
			soi.uom,
			COUNT(DISTINCT so.name)     AS orders,
			SUM(soi.qty)                AS qty_sold,
			SUM(soi.amount)             AS revenue,
			COUNT(DISTINCT so.customer) AS customers
		FROM `tabSales Order Item` soi
		INNER JOIN `tabSales Order` so ON so.name = soi.parent
		INNER JOIN `tabItem` i ON i.name = soi.item_code
		WHERE so.docstatus = 1
		AND so.transaction_date BETWEEN %(from_date)s AND %(to_date)s
		{terr_cond} {ig_cond} {cust_cond} {sp_cond}
		GROUP BY soi.item_code
		ORDER BY revenue DESC
		""",
		{"from_date": from_date, "to_date": to_date,
		 "territory": territory, "item_group": item_group,
		 "customer": customer, "sales_person_user": sales_person},
		as_dict=True,
	)

	for r in rows:
		r["avg_rate"] = flt(r["revenue"] / r["qty_sold"], 2) if r["qty_sold"] else 0

	return rows


def _chart(data, filters=None):
	if not data:
		return None
	chart_type = (filters or {}).get("chart_type") or "bar"
	top = data[:10]
	return {
		"data": {
			"labels":   [r["item_code"] for r in top],
			"datasets": [{"name": _("Revenue"), "values": [r["revenue"] for r in top]}],
		},
		"type": chart_type,
		"colors": ["#d97757"],
	}


def _summary(data):
	if not data:
		return None
	return [
		{"value": len(data),                        "label": _("SKUs Sold"),    "datatype": "Int",      "indicator": "blue"},
		{"value": sum(r["orders"]   for r in data), "label": _("Total Orders"), "datatype": "Int",      "indicator": "orange"},
		{"value": sum(r["qty_sold"] for r in data), "label": _("Total Qty"),    "datatype": "Float",    "indicator": "purple"},
		{"value": sum(r["revenue"]  for r in data), "label": _("Revenue"),      "datatype": "Currency", "indicator": "green"},
	]
