"""IB Replenishment Suggestions — which stock items to reorder, and how much.

Demand is read from submitted Sales Orders (what customers have ordered),
weighting the last 30 days against the longer look-back so a rising or falling
SKU is caught early. An item is flagged when projected stock (on hand + on
order - reserved, all warehouses) falls below its reorder point:

	reorder point = daily demand x lead time + safety stock
	suggested qty = daily demand x (lead time + review days) + safety stock - projected

Suggestions only: nothing is ordered. The report's "Create Material Request"
button drafts one for the ticked rows, for a buyer to review.
"""
import math

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, nowdate

_EXCLUDED_GROUPS = ("PACKAGING",)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	data = _data(filters)
	return _columns(), data, None, None, _summary(data)


def _columns():
	return [
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 190},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 200},
		{"label": _("UOM"), "fieldname": "uom", "fieldtype": "Data", "width": 70},
		{"label": _("Daily Demand"), "fieldname": "daily", "fieldtype": "Float", "precision": 2, "width": 110},
		{"label": _("Trend"), "fieldname": "trend", "fieldtype": "Data", "width": 85},
		{"label": _("Projected Stock"), "fieldname": "projected", "fieldtype": "Float", "precision": 1, "width": 120},
		{"label": _("Days of Cover"), "fieldname": "cover_days", "fieldtype": "Float", "precision": 1, "width": 110},
		{"label": _("Lead Time (d)"), "fieldname": "lead_time", "fieldtype": "Int", "width": 100},
		{"label": _("Reorder Point"), "fieldname": "reorder_point", "fieldtype": "Float", "precision": 1, "width": 110},
		{"label": _("Suggested Qty"), "fieldname": "suggested", "fieldtype": "Float", "precision": 0, "width": 115},
	]


def _data(filters):
	lookback = cint(filters.lookback_days) or 90
	from instabiz.overrides.ib_settings import get_int

	default_lead = cint(filters.default_lead_days) or get_int("replenishment_lead_days", 14)
	review = cint(filters.review_days) or get_int("replenishment_review_days", 7)
	today = nowdate()

	cond = ""
	vals = {"since": add_days(today, -lookback), "recent": add_days(today, -30), "ex": _EXCLUDED_GROUPS}
	if filters.item_group:
		cond += " AND i.item_group = %(item_group)s"
		vals["item_group"] = filters.item_group

	demand = frappe.db.sql(
		f"""
		SELECT soi.item_code,
			SUM(soi.stock_qty) AS qty_all,
			SUM(CASE WHEN so.transaction_date >= %(recent)s THEN soi.stock_qty ELSE 0 END) AS qty_30
		FROM `tabSales Order Item` soi
		INNER JOIN `tabSales Order` so ON so.name = soi.parent
		INNER JOIN `tabItem` i ON i.name = soi.item_code
		WHERE so.docstatus = 1 AND so.transaction_date >= %(since)s
		  AND i.is_stock_item = 1 AND i.disabled = 0 AND i.item_group NOT IN %(ex)s {cond}
		GROUP BY soi.item_code
		""",
		vals,
		as_dict=True,
	)
	if not demand:
		return []

	codes = [d.item_code for d in demand]
	items = {
		r.name: r
		for r in frappe.get_all(
			"Item",
			filters={"name": ["in", codes]},
			fields=["name", "item_name", "stock_uom", "lead_time_days", "safety_stock"],
		)
	}
	projected = {
		r.item_code: flt(r.projected)
		for r in frappe.db.sql(
			"SELECT item_code, SUM(projected_qty) AS projected FROM `tabBin`"
			" WHERE item_code IN %(c)s GROUP BY item_code",
			{"c": codes},
			as_dict=True,
		)
	}

	rows = []
	for d in demand:
		it = items.get(d.item_code)
		if not it:
			continue
		avg_all = flt(d.qty_all) / lookback
		avg_30 = flt(d.qty_30) / 30
		daily = 0.5 * avg_all + 0.5 * avg_30  # lean toward the recent month
		if daily <= 0:
			continue
		lead = cint(it.lead_time_days) or default_lead
		safety = flt(it.safety_stock)
		proj = projected.get(d.item_code, 0.0)
		reorder_point = daily * lead + safety
		if not filters.show_all and proj >= reorder_point:
			continue
		suggested = max(0.0, daily * (lead + review) + safety - proj)
		ratio = avg_30 / avg_all if avg_all else 0
		rows.append({
			"item_code": d.item_code,
			"item_name": it.item_name,
			"uom": it.stock_uom,
			"daily": daily,
			"trend": "Rising" if ratio > 1.2 else "Falling" if ratio < 0.8 else "Steady",
			"projected": proj,
			"cover_days": round(proj / daily, 1) if proj > 0 else 0,
			"lead_time": lead,
			"reorder_point": reorder_point,
			"suggested": math.ceil(suggested),
		})

	# most urgent first: least cover relative to how long a reorder takes
	rows.sort(key=lambda r: (r["cover_days"] - r["lead_time"], -r["suggested"]))
	return rows


def _summary(data):
	return [
		{"label": _("Items to reorder"), "value": len([r for r in data if r["suggested"] > 0]),
			"datatype": "Int", "indicator": "orange"},
		{"label": _("Run out before stock arrives"), "value": len([r for r in data if r["cover_days"] < r["lead_time"]]),
			"datatype": "Int", "indicator": "red"},
		{"label": _("Rising demand"), "value": len([r for r in data if r["trend"] == "Rising"]),
			"datatype": "Int", "indicator": "blue"},
	]
