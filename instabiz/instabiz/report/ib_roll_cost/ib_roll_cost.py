"""IB Roll Cost — what each finished roll really cost, from the production run's
stock entry: material (jumbo / film + recipe items, at their stock value, which
for imports is the container's landed cost), plus machine time (hours × running
cost per hour, added as additional cost), divided by the qty made. Compared with
the average selling rate of the last 180 days (billing-mode basis: Sales Orders
while billing runs on orders, else invoices)."""
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import add_days, add_months, flt, today

from instabiz.overrides.billing_mode import is_dev_billing_mode


def execute(filters=None):
	f = frappe._dict(filters or {})
	f.from_date = f.from_date or add_months(today(), -3)
	f.to_date = f.to_date or today()
	cond = ["wo.status = 'Completed'", "se.docstatus = 1", "DATE(wo.completed_at) BETWEEN %(from_date)s AND %(to_date)s",
		"d.is_finished_item = 1"]
	for key, sql in (("location", "wo.location = %(location)s"), ("item_code", "d.item_code = %(item_code)s"),
			("item_group", "i.item_group = %(item_group)s")):
		if f.get(key):
			cond.append(sql)
	rows = frappe.db.sql(f"""SELECT wo.name AS run, wo.completed_at, wo.location, wo.source_item, wo.source_batch,
			d.item_code, d.item_name, d.stock_uom, d.transfer_qty, d.amount, d.additional_cost, i.item_group
		FROM `tabIB Work Order` wo JOIN `tabStock Entry` se ON se.name = wo.stock_entry
		JOIN `tabStock Entry Detail` d ON d.parent = se.name LEFT JOIN `tabItem` i ON i.name = d.item_code
		WHERE {' AND '.join(cond)} ORDER BY wo.completed_at DESC""", f, as_dict=True)

	rates = _selling_rates({r.item_code for r in rows})
	view = f.view or "Run"
	if view == "Item":
		agg = defaultdict(lambda: frappe._dict(runs=0, qty=0.0, amount=0.0, conversion=0.0))
		for r in rows:
			a = agg[r.item_code]
			a.update(item_code=r.item_code, item_name=r.item_name, item_group=r.item_group, stock_uom=r.stock_uom)
			a.runs += 1
			a.qty += flt(r.transfer_qty)
			a.amount += flt(r.amount)
			a.conversion += flt(r.additional_cost)
		data = [_finish(a, rates) for a in agg.values()]
		data.sort(key=lambda d: d["margin_pct"] if d["margin_pct"] is not None else 999)
	else:
		data = [_finish(frappe._dict(run=r.run, completed_on=r.completed_at, location=r.location, source_item=r.source_item,
			source_batch=r.source_batch, item_code=r.item_code, item_name=r.item_name, item_group=r.item_group,
			stock_uom=r.stock_uom, runs=1, qty=flt(r.transfer_qty), amount=flt(r.amount),
			conversion=flt(r.additional_cost)), rates) for r in rows]

	cols = _cols(view)
	loss = [d for d in data if d["margin_pct"] is not None and d["margin_pct"] < 0]
	summary = [
		{"label": _("Finished qty lines"), "value": len(data), "datatype": "Int"},
		{"label": _("Material cost"), "value": sum(d["material_cost"] for d in data), "datatype": "Currency"},
		{"label": _("Machine cost"), "value": sum(d["conversion_cost"] for d in data), "datatype": "Currency"},
		{"label": _("Selling below cost"), "value": len(loss), "datatype": "Int", "indicator": "red" if loss else "green"},
	]
	top = [d for d in data if d["margin_pct"] is not None][:12]
	chart = {"data": {"labels": [d["item_code"] for d in top], "datasets": [
		{"name": _("Margin %"), "values": [d["margin_pct"] for d in top]}]}, "type": "bar",
		"colors": ["#d97757"]} if top else None
	msg = None if rows else _("No completed runs with a submitted stock entry in this period. "
		"Runs post stock when IB Stock Settings → Post production to stock is on.")
	return cols, data, msg, chart, summary


def _finish(a, rates):
	unit = a.amount / a.qty if a.qty else 0
	sell = rates.get(a.item_code)
	return {**a, "material_cost": round(a.amount - a.conversion, 2), "conversion_cost": round(a.conversion, 2),
		"total_cost": round(a.amount, 2), "unit_cost": round(unit, 4), "selling_rate": round(sell, 4) if sell else None,
		"margin_pct": round((sell - unit) / sell * 100, 2) if sell else None}


def _selling_rates(items):
	if not items:
		return {}
	since = add_days(today(), -180)
	if is_dev_billing_mode():
		sql = """SELECT c.item_code, SUM(c.base_net_amount) / NULLIF(SUM(c.stock_qty), 0) AS rate
			FROM `tabSales Order Item` c JOIN `tabSales Order` p ON p.name = c.parent
			WHERE p.docstatus = 1 AND p.transaction_date >= %s AND c.item_code IN %s GROUP BY c.item_code"""
	else:
		sql = """SELECT c.item_code, SUM(c.base_net_amount) / NULLIF(SUM(c.stock_qty), 0) AS rate
			FROM `tabSales Invoice Item` c JOIN `tabSales Invoice` p ON p.name = c.parent
			WHERE p.docstatus = 1 AND p.is_return = 0 AND p.posting_date >= %s AND c.item_code IN %s GROUP BY c.item_code"""
	return {r.item_code: flt(r.rate) for r in frappe.db.sql(sql, (since, tuple(items)), as_dict=True) if r.rate}


def _cols(view):
	cur = lambda label, fn, w=110: {"label": label, "fieldname": fn, "fieldtype": "Currency", "width": w}
	head = []
	if view == "Run":
		head = [{"label": _("Run"), "fieldname": "run", "fieldtype": "Link", "options": "IB Work Order", "width": 140},
			{"label": _("Completed"), "fieldname": "completed_on", "fieldtype": "Datetime", "width": 140},
			{"label": _("Jumbo / Film"), "fieldname": "source_item", "fieldtype": "Link", "options": "Item", "width": 140},
			{"label": _("Batch"), "fieldname": "source_batch", "fieldtype": "Link", "options": "IB Batch", "width": 150}]
	else:
		head = [{"label": _("Runs"), "fieldname": "runs", "fieldtype": "Int", "width": 60}]
	return head + [
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 170},
		{"label": _("Item Group"), "fieldname": "item_group", "fieldtype": "Data", "width": 110},
		{"label": _("Qty Made"), "fieldname": "qty", "fieldtype": "Float", "width": 90},
		{"label": _("UOM"), "fieldname": "stock_uom", "fieldtype": "Data", "width": 60},
		cur(_("Material"), "material_cost"), cur(_("Machine Time"), "conversion_cost"), cur(_("Total Cost"), "total_cost"),
		{"label": _("Cost / Unit"), "fieldname": "unit_cost", "fieldtype": "Currency", "width": 100},
		{"label": _("Avg Selling / Unit"), "fieldname": "selling_rate", "fieldtype": "Currency", "width": 120},
		{"label": _("Margin %"), "fieldname": "margin_pct", "fieldtype": "Percent", "width": 90},
	]
