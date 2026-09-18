"""IB Price Realisation — how far selling rates drift for the same item.

Item view: per SKU the low / median / high / average rate, spread, and the
"below median" gap = Σ (median − rate) × qty over sales billed under the
median. Customer view: per customer (or per customer for one item) the
average rate against the item median and the same gap. Rates are net of GST,
per stock unit.
"""
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt

from instabiz.overrides.sales_analytics import period, sales_lines, weighted_median


def execute(filters=None):
	f = frappe._dict(filters or {})
	start, end, _m = period(f)
	lines = [r for r in sales_lines(start, end, item_group=f.item_group, item_code=f.item_code, customer=f.customer)
		if flt(r.qty) > 0 and flt(r.amount) > 0]
	by_item = defaultdict(list)
	for r in lines:
		by_item[r.item_code].append(r)
	medians = {it: weighted_median([(r.rate, r.qty) for r in rows]) for it, rows in by_item.items()}
	if (f.view or "Item") == "Customer":
		return _customers(f, lines, medians)
	return _items(f, by_item, medians)


def _gap(rows, med):
	return sum((med - flt(r.rate)) * flt(r.qty) for r in rows if flt(r.rate) < med)


def _items(f, by_item, medians):
	data = []
	for it, rows in by_item.items():
		med = medians[it]
		qty = sum(flt(r.qty) for r in rows)
		value = sum(flt(r.amount) for r in rows)
		rates = [flt(r.rate) for r in rows]
		lo, hi = min(rates), max(rates)
		gap = _gap(rows, med)
		data.append(frappe._dict(item_code=it, item_name=rows[0].item_name, family=rows[0].item_group, uom=rows[0].stock_uom,
			lines=len(rows), customers=len({r.customer for r in rows}), qty=qty, value=value,
			low=lo, median=med, high=hi, avg=value / qty if qty else 0,
			spread=round((hi - lo) * 100 / med, 1) if med else 0, gap=gap,
			gap_pct=round(gap * 100 / value, 2) if value else 0))
	min_lines = frappe.utils.cint(f.min_lines or 3)
	data = [d for d in data if d.lines >= min_lines]
	data.sort(key=lambda d: -d.gap)
	cols = [
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 170},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 200},
		{"label": _("Family"), "fieldname": "family", "fieldtype": "Data", "width": 110},
		{"label": _("UOM"), "fieldname": "uom", "fieldtype": "Data", "width": 60},
		{"label": _("Lines"), "fieldname": "lines", "fieldtype": "Int", "width": 60},
		{"label": _("Customers"), "fieldname": "customers", "fieldtype": "Int", "width": 80},
		{"label": _("Qty"), "fieldname": "qty", "fieldtype": "Float", "width": 90},
		_c(_("Sales"), "value", 120), _c(_("Low Rate"), "low"), _c(_("Median Rate"), "median"),
		_c(_("High Rate"), "high"), _c(_("Avg Rate"), "avg"),
		{"label": _("Spread %"), "fieldname": "spread", "fieldtype": "Float", "precision": 1, "width": 80},
		_c(_("Below-Median Gap"), "gap", 130),
		{"label": _("Gap % of Sales"), "fieldname": "gap_pct", "fieldtype": "Float", "precision": 2, "width": 105},
	]
	return cols, data, None, _chart(data, "item_name"), _summary(data)


def _customers(f, lines, medians):
	g = {}
	for r in lines:
		d = g.setdefault(r.customer, frappe._dict(customer=r.customer, customer_name=r.customer_name,
			sales_person=r.sales_person, rows=[], value=0, at_median=0))
		d.rows.append(r)
		d.value += flt(r.amount)
		d.at_median += medians[r.item_code] * flt(r.qty)
	data = []
	for d in g.values():
		gap = sum(_gap([r], medians[r.item_code]) for r in d.rows)
		data.append(frappe._dict(customer=d.customer, customer_name=d.customer_name, sales_person=d.sales_person,
			lines=len(d.rows), items=len({r.item_code for r in d.rows}), value=d.value, at_median=d.at_median,
			index=round(d.value * 100 / d.at_median, 1) if d.at_median else 0, gap=gap,
			gap_pct=round(gap * 100 / d.value, 2) if d.value else 0))
	data.sort(key=lambda d: -d.gap)
	cols = [
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 200},
		{"label": _("Sales Person"), "fieldname": "sales_person", "fieldtype": "Data", "width": 120},
		{"label": _("Lines"), "fieldname": "lines", "fieldtype": "Int", "width": 60},
		{"label": _("Items"), "fieldname": "items", "fieldtype": "Int", "width": 60},
		_c(_("Sales"), "value", 120), _c(_("Sales at Median Rate"), "at_median", 140),
		{"label": _("Price Index"), "fieldname": "index", "fieldtype": "Float", "precision": 1, "width": 90,
			"description": "100 = pays the median rate"},
		_c(_("Below-Median Gap"), "gap", 130),
		{"label": _("Gap % of Sales"), "fieldname": "gap_pct", "fieldtype": "Float", "precision": 2, "width": 105},
	]
	return cols, data, None, _chart(data, "customer_name"), _summary(data)


def _c(label, fieldname, width=100):
	return {"label": label, "fieldname": fieldname, "fieldtype": "Currency", "width": width}


def _chart(data, label):
	top = [d for d in data if d.gap > 0][:10]
	if not top:
		return None
	return {"data": {"labels": [str(d.get(label) or "")[:24] for d in top],
		"datasets": [{"name": _("Below-median gap"), "values": [round(d.gap) for d in top]}]},
		"type": "bar", "fieldtype": "Currency", "colors": ["#d97757"]}


def _summary(data):
	value = sum(d.value for d in data)
	gap = sum(d.gap for d in data)
	return [
		{"label": _("Sales analysed"), "value": value, "datatype": "Currency"},
		{"label": _("Below-median gap"), "value": gap, "datatype": "Currency", "indicator": "red"},
		{"label": _("Gap % of sales"), "value": round(gap * 100 / value, 2) if value else 0, "datatype": "Percent"},
		{"label": _("1% better realisation"), "value": value * 0.01, "datatype": "Currency", "indicator": "green"},
	]
