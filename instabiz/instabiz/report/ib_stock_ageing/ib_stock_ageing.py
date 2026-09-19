"""IB Stock Ageing — stock age per item/warehouse bucketed into 0-30, 31-60, 61-90, 90+ days."""
import frappe
from frappe import _
from frappe.utils import getdate, today, date_diff, flt


def execute(filters=None):
	filters = filters or {}
	data = _data(filters)
	columns = _columns()
	from instabiz.overrides.ageing import rebucket

	columns, data, chart, summary = rebucket(filters, columns, data, "qty", "Float", _chart(data, filters), _summary(data))
	return columns, data, None, chart, summary


def _columns():
	return [
		{"label": _("Item Code"),      "fieldname": "item_code",    "fieldtype": "Link",     "options": "Item", "width": 160},
		{"label": _("Item Name"),      "fieldname": "item_name",    "fieldtype": "Data",     "width": 200},
		{"label": _("Warehouse"),      "fieldname": "warehouse",    "fieldtype": "Link",     "options": "Warehouse", "width": 180},
		{"label": _("Qty"),            "fieldname": "qty",          "fieldtype": "Float",    "width": 90},
		{"label": _("UOM"),            "fieldname": "uom",          "fieldtype": "Data",     "width": 70},
		{"label": _("First Receipt"),  "fieldname": "first_receipt","fieldtype": "Date",     "width": 110},
		{"label": _("Age (days)"),     "fieldname": "age_days",     "fieldtype": "Int",      "width": 100},
		{"label": _("0-30 days"),      "fieldname": "b0_30",        "fieldtype": "Float",    "width": 90},
		{"label": _("31-60 days"),     "fieldname": "b31_60",       "fieldtype": "Float",    "width": 90},
		{"label": _("61-90 days"),     "fieldname": "b61_90",       "fieldtype": "Float",    "width": 90},
		{"label": _("90+ days"),       "fieldname": "b90plus",      "fieldtype": "Float",    "width": 90},
		{"label": _("Valuation Rate"), "fieldname": "valuation_rate","fieldtype": "Currency", "width": 130},
		{"label": _("Stock Value"),    "fieldname": "stock_value",  "fieldtype": "Currency", "width": 130},
	]


def _data(filters):
	warehouse  = filters.get("warehouse")
	item_group = filters.get("item_group")
	today_date = getdate(today())

	wh_cond = "AND b.warehouse = %(warehouse)s" if warehouse else ""
	ig_cond  = "AND i.item_group = %(item_group)s" if item_group else ""

	# Current stock from Bin
	bins = frappe.db.sql(
		f"""
		SELECT
			b.item_code,
			b.warehouse,
			b.actual_qty        AS qty,
			b.valuation_rate,
			b.stock_value,
			i.item_name,
			i.stock_uom         AS uom
		FROM `tabBin` b
		INNER JOIN `tabItem` i ON i.name = b.item_code
		WHERE b.actual_qty > 0
		{wh_cond}
		{ig_cond}
		ORDER BY b.item_code, b.warehouse
		""",
		{"warehouse": warehouse, "item_group": item_group},
		as_dict=True,
	)

	# Earliest SLE (FIFO approximation) per item+warehouse
	earliest = frappe.db.sql(
		"""
		SELECT item_code, warehouse, MIN(posting_date) AS first_receipt
		FROM `tabStock Ledger Entry`
		WHERE actual_qty > 0 AND is_cancelled = 0
		GROUP BY item_code, warehouse
		""",
		as_dict=True,
	)
	receipt_map = {(r.item_code, r.warehouse): r.first_receipt for r in earliest}

	rows = []
	for b in bins:
		first = receipt_map.get((b.item_code, b.warehouse))
		age   = date_diff(today_date, first) if first else 0
		qty   = flt(b.qty)

		row = {
			"item_code":      b.item_code,
			"item_name":      b.item_name,
			"warehouse":      b.warehouse,
			"qty":            qty,
			"uom":            b.uom,
			"first_receipt":  first,
			"age_days":       age,
			"b0_30":          qty if age <= 30 else 0,
			"b31_60":         qty if 31 <= age <= 60 else 0,
			"b61_90":         qty if 61 <= age <= 90 else 0,
			"b90plus":        qty if age > 90 else 0,
			"valuation_rate": flt(b.valuation_rate),
			"stock_value":    flt(b.stock_value),
		}
		rows.append(row)

	rows.sort(key=lambda r: r["age_days"], reverse=True)
	return rows


def _chart(data, filters=None):
	if not data:
		return None
	chart_type = (filters or {}).get("chart_type") or "bar"
	buckets = {"0-30": 0, "31-60": 0, "61-90": 0, "90+": 0}
	for r in data:
		buckets["0-30"]  += r["b0_30"]
		buckets["31-60"] += r["b31_60"]
		buckets["61-90"] += r["b61_90"]
		buckets["90+"]   += r["b90plus"]
	return {
		"data": {
			"labels":   list(buckets.keys()),
			"datasets": [{"name": _("Stock Qty"), "values": list(buckets.values())}],
		},
		"type": chart_type,
		"colors": ["#70ad47", "#d97757", "#ed7d31", "#cf222e"],
	}


def _summary(data):
	if not data:
		return None
	total_items  = len(data)
	old_items    = sum(1 for r in data if r["age_days"] > 90)
	total_value  = sum(r["stock_value"] for r in data)
	old_value    = sum(r["stock_value"] for r in data if r["age_days"] > 90)
	return [
		{"value": total_items, "label": _("Items in Stock"),   "datatype": "Int",      "indicator": "blue"},
		{"value": old_items,   "label": _("Items > 90 days"),  "datatype": "Int",      "indicator": "red"},
		{"value": total_value, "label": _("Total Stock Value"), "datatype": "Currency", "indicator": "green"},
		{"value": old_value,   "label": _("Old Stock Value"),   "datatype": "Currency", "indicator": "orange"},
	]
