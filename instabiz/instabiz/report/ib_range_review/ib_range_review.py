"""IB Range Review — what to reorder, order less or drop.

Per item, family or colour: sales, qty, buyers, share, stock on hand, months of
cover (stock ÷ average monthly qty sold) and a call — Reorder now, Healthy,
Order less, Tail (tiny, one-off buyers) or Dead (stock but no sales). The
buyer mix shows whether volume accounts or one-off counters carry each line.
"""
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt

from instabiz.overrides.sales_analytics import group_key, period, sales_lines, stock_by_item


def execute(filters=None):
	f = frappe._dict(filters or {})
	by = f.group_by or "Item"
	start, end, months = period(f)
	lines = sales_lines(start, end, item_group=f.item_group)
	total = sum(flt(r.amount) for r in lines) or 1

	cust_value = defaultdict(float)
	for r in lines:
		cust_value[r.customer] += flt(r.amount)
	volume = {c for c, _v in sorted(cust_value.items(), key=lambda kv: -kv[1])[:max(1, len(cust_value) // 10)]}

	g = {}
	for r in lines:
		k = group_key(r, by)
		d = g.setdefault(k, frappe._dict(key=k, item_name=r.item_name if by == "Item" else "", family=r.item_group,
			colour=r.color, item_set=set(), value=0, qty=0, buyers=defaultdict(float), orders=set(), vol_value=0))
		d.item_set.add(r.item_code)
		d.value += flt(r.amount)
		d.qty += flt(r.qty)
		d.buyers[r.customer] += flt(r.amount)
		d.orders.add(r.doc)
		if r.customer in volume:
			d.vol_value += flt(r.amount)

	# stock for everything sold, plus dead lines (stock, no sale) when grouping by item
	stock_items = {i for d in g.values() for i in d.item_set}
	if by == "Item" and f.include_dead:
		dead = frappe.db.sql("""SELECT b.item_code FROM `tabBin` b JOIN `tabItem` i ON i.name = b.item_code
			WHERE b.actual_qty > 0 AND i.disabled = 0 {0} GROUP BY b.item_code""".format(
			"AND i.item_group = %(g)s" if f.item_group else ""), {"g": f.item_group}, pluck=True)
		for it in dead:
			if it not in g:
				info = frappe.db.get_value("Item", it, ["item_name", "item_group", "color"], as_dict=True) or {}
				g[it] = frappe._dict(key=it, item_name=info.get("item_name"), family=info.get("item_group"),
					colour=info.get("color"), item_set={it}, value=0, qty=0, buyers={}, orders=set(), vol_value=0)
				stock_items.add(it)
	stock = stock_by_item(list(stock_items), f.warehouse)

	data = []
	for d in g.values():
		st_qty = sum(flt((stock.get(i) or {}).get("qty")) for i in d.item_set)
		st_val = sum(flt((stock.get(i) or {}).get("value")) for i in d.item_set)
		monthly = d.qty / months
		cover = st_qty / monthly if monthly else (99 if st_qty > 0 else 0)
		buyers = len(d.buyers)
		share = d.value * 100 / total
		if d.value <= 0 and st_qty > 0:
			call = "Dead"
		elif cover < 1 and d.value > 0:
			call = "Reorder now"
		elif share < 0.2 and buyers <= 2:
			call = "Tail"
		elif cover > 4:
			call = "Order less"
		else:
			call = "Healthy"
		top = max(d.buyers.items(), key=lambda kv: kv[1]) if d.buyers else ("", 0)
		data.append(frappe._dict(key=d.key, item_name=d.item_name, family=d.family, colour=d.colour,
			value=d.value, share=round(share, 2), qty=d.qty, buyers=buyers, orders=len(d.orders),
			top_buyer=top[0], top_buyer_share=round(top[1] * 100 / d.value, 1) if d.value else 0,
			volume_share=round(d.vol_value * 100 / d.value, 1) if d.value else 0,
			stock_qty=st_qty, stock_value=st_val, monthly_qty=monthly, cover=round(min(cover, 99), 1), call=call))
	if f.call:
		data = [d for d in data if d.call == f.call]
	data.sort(key=lambda d: -d.value)

	calls = defaultdict(float)
	for d in data:
		calls[d.call] += d.stock_value
	label = {"Item": _("Item"), "Family": _("Family"), "Colour": _("Colour")}[by]
	cols = [{"label": label, "fieldname": "key", "fieldtype": "Link" if by == "Item" else "Data",
		"options": "Item" if by == "Item" else None, "width": 180}]
	if by == "Item":
		cols += [{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 200},
			{"label": _("Family"), "fieldname": "family", "fieldtype": "Data", "width": 110},
			{"label": _("Colour"), "fieldname": "colour", "fieldtype": "Data", "width": 80}]
	cols += [
		{"label": _("Call"), "fieldname": "call", "fieldtype": "Data", "width": 110},
		{"label": _("Sales"), "fieldname": "value", "fieldtype": "Currency", "width": 120},
		{"label": _("Share %"), "fieldname": "share", "fieldtype": "Float", "precision": 2, "width": 75},
		{"label": _("Qty Sold"), "fieldname": "qty", "fieldtype": "Float", "width": 95},
		{"label": _("Qty / Month"), "fieldname": "monthly_qty", "fieldtype": "Float", "precision": 1, "width": 95},
		{"label": _("Stock Qty"), "fieldname": "stock_qty", "fieldtype": "Float", "width": 95},
		{"label": _("Stock Value"), "fieldname": "stock_value", "fieldtype": "Currency", "width": 115},
		{"label": _("Months Cover"), "fieldname": "cover", "fieldtype": "Float", "precision": 1, "width": 95},
		{"label": _("Buyers"), "fieldname": "buyers", "fieldtype": "Int", "width": 70},
		{"label": _("Orders"), "fieldname": "orders", "fieldtype": "Int", "width": 70},
		{"label": _("Volume Accounts %"), "fieldname": "volume_share", "fieldtype": "Float", "precision": 1, "width": 115},
		{"label": _("Top Buyer"), "fieldname": "top_buyer", "fieldtype": "Link", "options": "Customer", "width": 170},
		{"label": _("Top Buyer %"), "fieldname": "top_buyer_share", "fieldtype": "Float", "precision": 1, "width": 90},
	]
	chart = {"data": {"labels": list(calls), "datasets": [{"name": _("Stock value"), "values": [round(v) for v in calls.values()]}]},
		"type": "donut", "fieldtype": "Currency"} if any(calls.values()) else None
	summary = [
		{"label": _("Sales in period"), "value": sum(d.value for d in data), "datatype": "Currency"},
		{"label": _("Reorder now"), "value": sum(1 for d in data if d.call == "Reorder now"), "datatype": "Int", "indicator": "red"},
		{"label": _("Order less (stock value)"), "value": calls.get("Order less", 0), "datatype": "Currency", "indicator": "orange"},
		{"label": _("Dead / Tail (stock value)"), "value": calls.get("Dead", 0) + calls.get("Tail", 0), "datatype": "Currency"},
		{"label": _("Months in period"), "value": round(months, 1), "datatype": "Float"},
	]
	return cols, data, None, chart, summary
