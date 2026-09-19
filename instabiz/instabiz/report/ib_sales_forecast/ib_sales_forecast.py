"""IB Sales Forecast — next months' sales from your own history.

For each group (total, family, item, customer or sales person): the average
of the last three full months, lifted or lowered by that month's usual
seasonal pattern (same month last year against last year's monthly average,
kept between 0.5× and 2×). Needs at least three months of history; with a year
or more the seasonal part kicks in. Value or quantity; Sales Users see their
own customers only.
"""
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import add_days, add_months, flt, get_first_day, today

from instabiz.overrides.sales_analytics import sales_lines

KEYS = {"Total": None, "Family": "item_group", "Item": "item_code", "Customer": "customer_name", "Sales Person": "sales_person"}


def execute(filters=None):
	f = frappe._dict(filters or {})
	ahead = max(1, min(int(f.months or 3), 12))
	by = f.group_by or "Total"
	measure = "qty" if f.measure == "Quantity" else "amount"
	this_month = get_first_day(today())
	hist_start = add_months(this_month, -24)
	lines = sales_lines(hist_start, add_days(this_month, -1),
		item_group=f.item_group, item_code=f.item_code, customer=f.customer)
	series = defaultdict(lambda: defaultdict(float))
	for r in lines:
		key = "Total" if by == "Total" else (r.get(KEYS[by]) or "—")
		series[key][get_first_day(r.date)] += flt(r.get(measure))
	past = [add_months(this_month, -i) for i in range(12, 0, -1)]
	future = [add_months(this_month, i) for i in range(ahead)]
	rows = []
	for key, s in series.items():
		last3 = [s.get(add_months(this_month, -i), 0) for i in (1, 2, 3)]
		base = sum(last3) / 3
		ly = [s.get(add_months(this_month, -i), 0) for i in range(24, 12, -1)]
		ly_avg = sum(ly) / 12 if any(ly) else 0
		row = frappe._dict(group=key, last_12=sum(s.get(m, 0) for m in past), last_3_avg=base)
		total = 0
		for m in future:
			same_ly = s.get(add_months(m, -12), 0)
			factor = min(max(same_ly / ly_avg, 0.5), 2.0) if ly_avg and same_ly else 1.0
			val = base * factor
			row[m.strftime("f_%Y_%m")] = val
			total += val
		row.forecast_total = total
		prev = sum(s.get(add_months(this_month, -12 + i), 0) for i in range(ahead))
		row.vs_last_year = round((total - prev) / prev * 100, 1) if prev else None
		rows.append(row)
	rows.sort(key=lambda r: -r.forecast_total)
	if f.top_n:
		rows = rows[: int(f.top_n)]
	ft = "Float" if measure == "qty" else "Currency"
	cols = [{"label": _(by), "fieldname": "group", "fieldtype": "Data", "width": 220},
		{"label": _("Last 12 months"), "fieldname": "last_12", "fieldtype": ft, "width": 130},
		{"label": _("Avg last 3 months"), "fieldname": "last_3_avg", "fieldtype": ft, "width": 130}]
	cols += [{"label": m.strftime("%b %Y") + " " + _("(forecast)"), "fieldname": m.strftime("f_%Y_%m"), "fieldtype": ft, "width": 140} for m in future]
	cols += [{"label": _("Forecast total"), "fieldname": "forecast_total", "fieldtype": ft, "width": 130},
		{"label": _("vs same months last year %"), "fieldname": "vs_last_year", "fieldtype": "Percent", "width": 120}]
	total_series = defaultdict(float)
	for s in series.values():
		for m, v in s.items():
			total_series[m] += v
	labels = [m.strftime("%b %y") for m in past] + [m.strftime("%b %y") for m in future]
	fut_total = [sum(r.get(m.strftime("f_%Y_%m"), 0) for r in rows) for m in future]
	chart = {"data": {"labels": labels, "datasets": [
		{"name": _("Actual"), "values": [round(total_series.get(m, 0)) for m in past] + [0] * len(future)},
		{"name": _("Forecast"), "values": [0] * len(past) + [round(v) for v in fut_total]}]},
		"type": "bar", "colors": ["#94a3b8", "#d97757"], "fieldtype": ft} if series else None
	msg = None if len({get_first_day(r.date) for r in lines}) >= 3 else _("Needs at least three months of sales history.")
	summary = [{"label": _("Forecast next {0} months").format(ahead), "value": sum(r.forecast_total for r in rows), "datatype": ft},
		{"label": _("Last 12 months"), "value": sum(r.last_12 for r in rows), "datatype": ft}]
	return cols, rows, msg, chart, summary
