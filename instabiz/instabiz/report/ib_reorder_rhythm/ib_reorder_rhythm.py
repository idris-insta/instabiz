"""IB Reorder Rhythm — who is late against their own buying pattern.

Per customer: order days in the look-back window, their usual gap between
orders (median), last order, days since, expected next order and how many
days overdue that is. A call list sorted by value at risk (average order
value of overdue accounts), not a flat "no order in 45 days" rule.
"""
import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, getdate, today

from instabiz.overrides.sales_analytics import distinct_dates_by_customer, median, sales_lines


def execute(filters=None):
	f = frappe._dict(filters or {})
	end = getdate(today())
	start = add_days(end, -cint(f.lookback_days or 365))
	lines = sales_lines(start, end, customer=f.customer)
	dates = distinct_dates_by_customer(lines)
	value, info = {}, {}
	for r in lines:
		value[r.customer] = value.get(r.customer, 0) + flt(r.amount)
		info[r.customer] = r
	data = []
	for cust, ds in dates.items():
		ds = sorted(ds)
		if len(ds) < cint(f.min_orders or 3):
			continue
		gaps = [date_diff(b, a) for a, b in zip(ds, ds[1:]) if date_diff(b, a) > 0]
		if not gaps:
			continue
		usual = median(gaps)
		last = ds[-1]
		since = date_diff(end, last)
		overdue = since - usual
		avg_order = value[cust] / len(ds)
		status = "Overdue" if overdue > usual * 0.25 else ("Due now" if overdue >= -3 else "On rhythm")
		data.append(frappe._dict(customer=cust, customer_name=info[cust].customer_name, sales_person=info[cust].sales_person,
			orders=len(ds), usual_gap=round(usual), last_order=last, days_since=since,
			expected=add_days(last, round(usual)), overdue=round(overdue), status=status,
			value=value[cust], avg_order=avg_order, at_risk=avg_order if status != "On rhythm" else 0))
	if f.status:
		data = [d for d in data if d.status == f.status]
	elif not f.show_all:
		data = [d for d in data if d.status != "On rhythm"]
	data.sort(key=lambda d: (-d.at_risk, -d.overdue))
	cols = [
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 210},
		{"label": _("Sales Person"), "fieldname": "sales_person", "fieldtype": "Data", "width": 120},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 95},
		{"label": _("Order Days"), "fieldname": "orders", "fieldtype": "Int", "width": 85},
		{"label": _("Usual Gap (days)"), "fieldname": "usual_gap", "fieldtype": "Int", "width": 110},
		{"label": _("Last Order"), "fieldname": "last_order", "fieldtype": "Date", "width": 95},
		{"label": _("Days Since"), "fieldname": "days_since", "fieldtype": "Int", "width": 85},
		{"label": _("Expected By"), "fieldname": "expected", "fieldtype": "Date", "width": 95},
		{"label": _("Days Late"), "fieldname": "overdue", "fieldtype": "Int", "width": 80},
		{"label": _("Avg Order"), "fieldname": "avg_order", "fieldtype": "Currency", "width": 115},
		{"label": _("Value (window)"), "fieldname": "value", "fieldtype": "Currency", "width": 125},
	]
	return cols, data, None, None, [
		{"label": _("Overdue accounts"), "value": sum(1 for d in data if d.status == "Overdue"), "datatype": "Int", "indicator": "red"},
		{"label": _("Due now"), "value": sum(1 for d in data if d.status == "Due now"), "datatype": "Int", "indicator": "orange"},
		{"label": _("Next-order value at risk"), "value": sum(d.at_risk for d in data), "datatype": "Currency"},
	]
