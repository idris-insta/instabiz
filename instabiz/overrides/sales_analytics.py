"""instabiz.overrides.sales_analytics

Shared data for the range / pricing / stock / rhythm / cross-sell reports.
Sales lines follow the billing mode (Sales Order items while billing runs on
orders, Sales Invoice items after), leave branch transfers out, and are
limited to a Sales User's own customers.
"""
from collections import defaultdict

import frappe
from frappe.utils import add_months, date_diff, flt, getdate, today

from instabiz.overrides.billing_mode import is_dev_billing_mode

MANAGER_ROLES = {"System Manager", "Sales Manager", "Accounts Manager", "Accounts User", "Stock Manager",
	"Purchase Manager", "Factory Management"}


def own_scope():
	"""Session user when they may only see their own customers, else None."""
	return None if set(frappe.get_roles()) & MANAGER_ROLES else frappe.session.user


def period(f, months=6):
	end = getdate(f.get("to_date") or today())
	start = getdate(f.get("from_date") or add_months(end, -months))
	return start, end, max(date_diff(end, start) / 30.44, 1)


def sales_lines(start, end, item_group=None, item_code=None, customer=None):
	if is_dev_billing_mode():
		parent, child, date_field = "Sales Order", "Sales Order Item", "p.transaction_date"
	else:
		parent, child, date_field = "Sales Invoice", "Sales Invoice Item", "p.posting_date"
	cond = ["p.docstatus = 1", f"{date_field} BETWEEN %(from)s AND %(to)s",
		"IFNULL(c.is_internal_customer, 0) = 0", "IFNULL(c.customer_name, '') NOT LIKE 'INSTABIZ%%'"]
	args = {"from": start, "to": end}
	if parent == "Sales Invoice":
		cond.append("p.is_return = 0")
	if item_group:
		cond.append("i.item_group = %(item_group)s")
		args["item_group"] = item_group
	if item_code:
		cond.append("ci.item_code = %(item_code)s")
		args["item_code"] = item_code
	if customer:
		cond.append("p.customer = %(customer)s")
		args["customer"] = customer
	mine = own_scope()
	if mine:
		cond.append("(c.custom_sales_person_user = %(me)s OR p.custom_sales_person_user = %(me)s)")
		args["me"] = mine
	return frappe.db.sql(
		f"""SELECT p.name AS doc, {date_field} AS date, p.customer, c.customer_name,
		           IFNULL(c.custom_sales_person, '') AS sales_person,
		           ci.item_code, i.item_name, i.item_group, IFNULL(i.color, '') AS color, i.stock_uom,
		           ci.stock_qty AS qty, ci.base_net_amount AS amount,
		           ci.base_net_amount / NULLIF(ci.stock_qty, 0) AS rate
		FROM `tab{child}` ci
		JOIN `tab{parent}` p ON p.name = ci.parent
		JOIN `tabItem` i ON i.name = ci.item_code
		LEFT JOIN `tabCustomer` c ON c.name = p.customer
		WHERE {' AND '.join(cond)}""",
		args, as_dict=True,
	)


def stock_by_item(item_codes=None, warehouse=None):
	"""{item: frappe._dict(qty, value)} from Bin."""
	cond, args = "1=1", {}
	if item_codes is not None:
		if not item_codes:
			return {}
		cond += " AND item_code IN %(items)s"
		args["items"] = tuple(item_codes)
	if warehouse:
		cond += " AND warehouse = %(wh)s"
		args["wh"] = warehouse
	out = {}
	for r in frappe.db.sql(f"""SELECT item_code, SUM(actual_qty) qty, SUM(stock_value) value
			FROM `tabBin` WHERE {cond} GROUP BY item_code""", args, as_dict=True):
		out[r.item_code] = r
	return out


def median(values):
	v = sorted(values)
	if not v:
		return 0
	mid = len(v) // 2
	return v[mid] if len(v) % 2 else (v[mid - 1] + v[mid]) / 2


def weighted_median(pairs):
	"""Median rate weighted by quantity: [(rate, qty)]."""
	pairs = sorted((flt(r), flt(q)) for r, q in pairs if flt(q) > 0)
	total = sum(q for _, q in pairs)
	run = 0
	for rate, q in pairs:
		run += q
		if run >= total / 2:
			return rate
	return 0


def group_key(row, by):
	return {"Family": row.item_group or "—", "Colour": row.color or "—"}.get(by, row.item_code)


def distinct_dates_by_customer(lines):
	out = defaultdict(set)
	for r in lines:
		out[r.customer].add(getdate(r.date))
	return out
