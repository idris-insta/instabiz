"""IB Idle Stock — money standing still.

Every item with stock, ranked by rupees: stock value, last sale, days since,
qty sold in the period, months of cover, and the state — Dead (no sale in the
period), Overstock (cover above the limit), Slow, or Moving.
"""
import frappe
from frappe import _
from frappe.utils import date_diff, flt, getdate, today

from instabiz.overrides.sales_analytics import period, sales_lines


def execute(filters=None):
	f = frappe._dict(filters or {})
	start, end, months = period(f)
	limit = flt(f.cover_limit or 4)
	cond, args = "b.actual_qty > 0 AND i.disabled = 0", {}
	if f.item_group:
		cond += " AND i.item_group = %(g)s"
		args["g"] = f.item_group
	if f.warehouse:
		cond += " AND b.warehouse = %(wh)s"
		args["wh"] = f.warehouse
	stock = frappe.db.sql(f"""SELECT b.item_code, i.item_name, i.item_group, i.stock_uom,
		SUM(b.actual_qty) qty, SUM(b.stock_value) value, GROUP_CONCAT(DISTINCT b.warehouse SEPARATOR ', ') warehouses
		FROM `tabBin` b JOIN `tabItem` i ON i.name = b.item_code WHERE {cond} GROUP BY b.item_code""", args, as_dict=True)
	sold = {}
	for r in sales_lines(start, end, item_group=f.item_group):
		sold[r.item_code] = sold.get(r.item_code, 0) + flt(r.qty)
	last = dict(frappe.db.sql("""SELECT item_code, MAX(posting_date) FROM `tabStock Ledger Entry`
		WHERE is_cancelled = 0 AND actual_qty < 0 AND voucher_type IN ('Delivery Note', 'Sales Invoice')
		GROUP BY item_code"""))
	data = []
	for s in stock:
		monthly = flt(sold.get(s.item_code)) / months
		cover = flt(s.qty) / monthly if monthly else 999
		last_sale = last.get(s.item_code)
		days = date_diff(getdate(today()), last_sale) if last_sale else None
		if not sold.get(s.item_code):
			state = "Dead"
		elif cover > limit * 2:
			state = "Overstock"
		elif cover > limit:
			state = "Slow"
		else:
			state = "Moving"
		excess = max(flt(s.qty) - monthly * limit, 0) if state != "Dead" else flt(s.qty)
		data.append(frappe._dict(item_code=s.item_code, item_name=s.item_name, family=s.item_group, uom=s.stock_uom,
			warehouses=s.warehouses, qty=s.qty, value=s.value, sold=flt(sold.get(s.item_code)),
			monthly=monthly, cover=round(min(cover, 999), 1), last_sale=last_sale, days=days, state=state,
			excess_value=flt(s.value) * excess / flt(s.qty) if flt(s.qty) else 0))
	if not f.show_moving:
		data = [d for d in data if d.state != "Moving"]
	data.sort(key=lambda d: -d.excess_value)
	by_state = {}
	for d in data:
		by_state[d.state] = by_state.get(d.state, 0) + d.excess_value
	cols = [
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 170},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 200},
		{"label": _("Family"), "fieldname": "family", "fieldtype": "Data", "width": 110},
		{"label": _("State"), "fieldname": "state", "fieldtype": "Data", "width": 95},
		{"label": _("Stock Qty"), "fieldname": "qty", "fieldtype": "Float", "width": 95},
		{"label": _("UOM"), "fieldname": "uom", "fieldtype": "Data", "width": 60},
		{"label": _("Stock Value"), "fieldname": "value", "fieldtype": "Currency", "width": 120},
		{"label": _("Excess Value"), "fieldname": "excess_value", "fieldtype": "Currency", "width": 120,
			"description": "Value above the cover limit (all of it when dead)"},
		{"label": _("Sold in Period"), "fieldname": "sold", "fieldtype": "Float", "width": 100},
		{"label": _("Months Cover"), "fieldname": "cover", "fieldtype": "Float", "precision": 1, "width": 95},
		{"label": _("Last Sale"), "fieldname": "last_sale", "fieldtype": "Date", "width": 95},
		{"label": _("Days Since"), "fieldname": "days", "fieldtype": "Int", "width": 80},
		{"label": _("Warehouses"), "fieldname": "warehouses", "fieldtype": "Data", "width": 200},
	]
	chart = {"data": {"labels": list(by_state), "datasets": [{"name": _("Excess value"), "values": [round(v) for v in by_state.values()]}]},
		"type": "donut", "fieldtype": "Currency"} if by_state else None
	return cols, data, None, chart, [
		{"label": _("Idle money (excess value)"), "value": sum(d.excess_value for d in data), "datatype": "Currency", "indicator": "red"},
		{"label": _("Dead lines"), "value": sum(1 for d in data if d.state == "Dead"), "datatype": "Int"},
		{"label": _("Dead stock value"), "value": by_state.get("Dead", 0), "datatype": "Currency"},
		{"label": _("Cover limit (months)"), "value": limit, "datatype": "Float"},
	]
