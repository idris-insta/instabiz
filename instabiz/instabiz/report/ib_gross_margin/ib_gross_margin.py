"""IB Gross Margin — margin per SKU using SO Item rate vs valuation_rate."""
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
		{"label": _("Item Code"),    "fieldname": "item_code",   "fieldtype": "Link",     "options": "Item",       "width": 160},
		{"label": _("Item Name"),    "fieldname": "item_name",   "fieldtype": "Data",     "width": 220},
		{"label": _("Item Group"),   "fieldname": "item_group",  "fieldtype": "Link",     "options": "Item Group", "width": 140},
		{"label": _("Qty Sold"),     "fieldname": "qty_sold",    "fieldtype": "Float",    "width": 110},
		{"label": _("Revenue"),      "fieldname": "revenue",     "fieldtype": "Currency", "width": 150},
		{"label": _("COGS"),         "fieldname": "cogs",        "fieldtype": "Currency", "width": 150},
		{"label": _("Gross Profit"), "fieldname": "gross_profit","fieldtype": "Currency", "width": 150},
		{"label": _("Margin %"),     "fieldname": "margin_pct",  "fieldtype": "Percent",  "width": 110},
	]


def _data(filters):
	from_date      = filters.get("from_date")
	to_date        = filters.get("to_date")
	territory      = filters.get("territory")
	item_group     = filters.get("item_group")
	sales_person   = filters.get("sales_person_user")

	terr_cond = "AND so.territory = %(territory)s"       if territory    else ""
	ig_cond   = "AND i.item_group = %(item_group)s"      if item_group   else ""
	sp_cond   = "AND so.custom_sales_person_user = %(sales_person_user)s" if sales_person else ""

	rows = frappe.db.sql(
		f"""
		SELECT
			soi.item_code,
			soi.item_name,
			i.item_group,
			SUM(soi.qty)                              AS qty_sold,
			SUM(soi.amount)                           AS revenue,
			SUM(soi.qty * i.valuation_rate)           AS cogs
		FROM `tabSales Order Item` soi
		INNER JOIN `tabSales Order` so ON so.name = soi.parent
		INNER JOIN `tabItem` i ON i.name = soi.item_code
		WHERE so.docstatus = 1
		AND so.transaction_date BETWEEN %(from_date)s AND %(to_date)s
		{terr_cond} {ig_cond} {sp_cond}
		GROUP BY soi.item_code
		ORDER BY revenue DESC
		""",
		{"from_date": from_date, "to_date": to_date,
		 "territory": territory, "item_group": item_group,
		 "sales_person_user": sales_person},
		as_dict=True,
	)

	for r in rows:
		r["revenue"]      = round(flt(r["revenue"]), 2)
		r["cogs"]         = round(flt(r["cogs"]), 2)
		r["gross_profit"] = round(r["revenue"] - r["cogs"], 2)
		r["margin_pct"]   = flt(r["gross_profit"] / r["revenue"] * 100, 2) if r["revenue"] else 0

	return rows


def _chart(data, filters=None):
	if not data:
		return None
	chart_type = (filters or {}).get("chart_type") or "bar"
	top = data[:10]
	return {
		"data": {
			"labels":   [r["item_code"] for r in top],
			"datasets": [
				{"name": _("Revenue"),      "values": [round(r["revenue"])      for r in top]},
				{"name": _("Gross Profit"), "values": [round(r["gross_profit"]) for r in top]},
			],
		},
		"type": chart_type,
		"colors": ["#2e74b5", "#1a7f37"],
	}


def _summary(data):
	if not data:
		return None
	total_rev  = sum(r["revenue"]      for r in data)
	total_cogs = sum(r["cogs"]         for r in data)
	total_gp   = sum(r["gross_profit"] for r in data)
	avg_margin = flt(total_gp / total_rev * 100, 2) if total_rev else 0
	return [
		{"value": len(data),   "label": _("SKUs"),          "datatype": "Int",      "indicator": "blue"},
		{"value": total_rev,   "label": _("Revenue"),        "datatype": "Currency", "indicator": "orange"},
		{"value": total_gp,    "label": _("Gross Profit"),   "datatype": "Currency", "indicator": "green"},
		{"value": avg_margin,  "label": _("Avg Margin %"),   "datatype": "Percent",  "indicator": "purple"},
	]
