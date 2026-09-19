"""IB Vendor Price History — what we bought, from whom, at what rate, when.

Every submitted Purchase Order (or Purchase Invoice) line, newest first. Pick an
item to compare suppliers: the table flags the highest and lowest rate, and the
per-supplier view gives last / lowest / highest / average rate per supplier.
"""
import frappe
from frappe import _
from frappe.utils import flt

from instabiz.overrides.billing_mode import purchase_doctype


def execute(filters=None):
	f = frappe._dict(filters or {})
	doctype = f.source or purchase_doctype()
	rows = _rows(f, doctype)
	if (f.view or "Lines") == "By Supplier":
		return _by_supplier(rows)
	return _columns(doctype), rows, None, _chart(rows), _summary(rows)


def _rows(f, doctype):
	date = "transaction_date" if doctype == "Purchase Order" else "posting_date"
	cond, args = "", {}
	for key, sql in (("item_code", "i.item_code = %(item_code)s"), ("supplier", "p.supplier = %(supplier)s"),
			("item_group", "i.item_group = %(item_group)s"), ("from_date", f"p.{date} >= %(from_date)s"),
			("to_date", f"p.{date} <= %(to_date)s")):
		if f.get(key):
			cond += " AND " + sql
			args[key] = f.get(key)
	rows = frappe.db.sql(
		f"""SELECT p.{date} AS date, i.parent, p.supplier, p.supplier_name, i.item_code, i.item_name,
		       i.qty, i.uom, i.rate, i.amount, i.base_net_rate AS net_rate
		FROM `tab{doctype} Item` i JOIN `tab{doctype}` p ON p.name = i.parent
		WHERE p.docstatus = 1 {cond}
		ORDER BY p.{date} DESC, i.parent DESC LIMIT 2000""", args, as_dict=True)
	rates = [flt(r.net_rate) for r in rows if flt(r.net_rate) > 0]
	if rates and len({r.item_code for r in rows}) == 1:
		hi, lo = max(rates), min(rates)
		for r in rows:
			r._flag = "high" if flt(r.net_rate) == hi else ("low" if flt(r.net_rate) == lo else None)
	return rows


def _columns(doctype):
	return [
		{"label": _("Date"), "fieldname": "date", "fieldtype": "Date", "width": 95},
		{"label": _("Document"), "fieldname": "parent", "fieldtype": "Link", "options": doctype, "width": 160},
		{"label": _("Supplier"), "fieldname": "supplier_name", "fieldtype": "Data", "width": 200},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 170},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 180},
		{"label": _("Qty"), "fieldname": "qty", "fieldtype": "Float", "width": 80},
		{"label": _("UOM"), "fieldname": "uom", "fieldtype": "Data", "width": 65},
		{"label": _("Rate (net)"), "fieldname": "net_rate", "fieldtype": "Currency", "width": 110},
		{"label": _("Amount"), "fieldname": "amount", "fieldtype": "Currency", "width": 120},
	]


def _by_supplier(rows):
	agg = {}
	for r in rows:
		a = agg.setdefault((r.supplier, r.item_code), frappe._dict(supplier_name=r.supplier_name, item_code=r.item_code,
			item_name=r.item_name, uom=r.uom, last_date=r.date, last_rate=flt(r.net_rate), rates=[], qty=0))
		a.rates.append(flt(r.net_rate))
		a.qty += flt(r.qty)
	data = []
	for a in agg.values():
		rates = [x for x in a.rates if x > 0] or [0]
		a.update(low=min(rates), high=max(rates), avg=sum(rates) / len(rates), buys=len(a.rates))
		data.append(a)
	data.sort(key=lambda a: (a.item_code, a.avg))
	cols = [
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 170},
		{"label": _("Supplier"), "fieldname": "supplier_name", "fieldtype": "Data", "width": 200},
		{"label": _("Buys"), "fieldname": "buys", "fieldtype": "Int", "width": 60},
		{"label": _("Qty"), "fieldname": "qty", "fieldtype": "Float", "width": 90},
		{"label": _("Last Bought"), "fieldname": "last_date", "fieldtype": "Date", "width": 95},
		{"label": _("Last Rate"), "fieldname": "last_rate", "fieldtype": "Currency", "width": 105},
		{"label": _("Lowest"), "fieldname": "low", "fieldtype": "Currency", "width": 100},
		{"label": _("Highest"), "fieldname": "high", "fieldtype": "Currency", "width": 100},
		{"label": _("Average"), "fieldname": "avg", "fieldtype": "Currency", "width": 100},
	]
	return cols, data, None, None, None


def _chart(rows):
	pts = list(reversed([r for r in rows if flt(r.net_rate) > 0][:30]))
	if not pts or len({r.item_code for r in rows}) != 1:
		return None
	return {"data": {"labels": [str(r.date) for r in pts], "datasets": [{"name": _("Rate"), "values": [flt(r.net_rate) for r in pts]}]},
		"type": "line", "colors": ["#d97757"]}


def _summary(rows):
	rates = [flt(r.net_rate) for r in rows if flt(r.net_rate) > 0]
	if not rates:
		return None
	one_item = len({r.item_code for r in rows}) == 1
	out = [{"value": len(rows), "label": _("Purchase lines"), "datatype": "Int"},
		{"value": len({r.supplier for r in rows}), "label": _("Suppliers"), "datatype": "Int"}]
	if one_item:
		out += [{"value": rates[0], "label": _("Last Rate"), "datatype": "Currency"},
			{"value": min(rates), "label": _("Lowest"), "datatype": "Currency", "indicator": "green"},
			{"value": max(rates), "label": _("Highest"), "datatype": "Currency", "indicator": "red"}]
	return out
