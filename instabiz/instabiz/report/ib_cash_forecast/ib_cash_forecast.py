"""IB Cash Forecast — week by week, what comes in and goes out.

Opening = today's bank and cash balance. In: customer dues on their due date
(invoice due date; while billing runs on orders, delivery date + credit days),
optionally pushed by how late each customer usually pays, and post-dated
cheques on their cheque date. Out: supplier dues on their due date, salaries at
each month end (last payroll's net pay) and running expenses (average of the
last three months). Overdue items fall in the first week.
"""
import frappe
from frappe import _
from frappe.utils import add_days, add_months, flt, get_first_day, get_last_day, getdate, today

from instabiz.overrides.billing_mode import is_dev_billing_mode


def execute(filters=None):
	f = frappe._dict(filters or {})
	weeks = max(1, min(int(f.weeks or 12), 26))
	start = getdate(today())
	start = add_days(start, -start.weekday())
	buckets = [add_days(start, 7 * i) for i in range(weeks)]
	end = add_days(buckets[-1], 6)
	credit_days = int(f.credit_days or 30)

	def week_of(d):
		d = getdate(d)
		if d < buckets[0]:
			return 0
		i = (d - buckets[0]).days // 7
		return i if i < weeks else None

	lines = {k: [0.0] * weeks for k in ("receivables", "pdc", "payables", "salary", "expenses")}
	detail = []

	delay = _customer_delay() if f.adjust_for_delay else {}
	for r in _receivables(credit_days):
		due = add_days(r.due, delay.get(r.party, 0))
		w = week_of(due)
		if w is not None:
			lines["receivables"][w] += r.amount
			detail.append(("In", r.doctype, r.name, r.party, due, r.amount))
	for p in frappe.get_all("IB PDC", filters={"status": "Pending", "cheque_date": ["<=", end]},
			fields=["name", "customer_name", "cheque_date", "amount", "sales_invoice"]):
		if p.sales_invoice and not is_dev_billing_mode():
			continue  # its invoice is already counted as a receivable
		w = week_of(p.cheque_date)
		if w is not None:
			lines["pdc"][w] += flt(p.amount)
			detail.append(("In", "IB PDC", p.name, p.customer_name, p.cheque_date, flt(p.amount)))
	for r in _payables(credit_days):
		w = week_of(r.due)
		if w is not None:
			lines["payables"][w] += r.amount
			detail.append(("Out", r.doctype, r.name, r.party, r.due, r.amount))
	salary = _monthly_salary()
	month_end = get_last_day(start)
	while getdate(month_end) <= end:
		w = week_of(month_end)
		if w is not None and salary:
			lines["salary"][w] += salary
		month_end = get_last_day(add_months(month_end, 1))
	weekly_exp = _monthly_expenses() * 12 / 52
	for i in range(weeks):
		lines["expenses"][i] += weekly_exp

	balance = _cash_balance()
	data = []
	for i, wk in enumerate(buckets):
		inflow = lines["receivables"][i] + lines["pdc"][i]
		outflow = lines["payables"][i] + lines["salary"][i] + lines["expenses"][i]
		row = frappe._dict(week=f"{getdate(wk).strftime('%d %b')} – {getdate(add_days(wk, 6)).strftime('%d %b')}", opening=balance,
			receivables=lines["receivables"][i], pdc=lines["pdc"][i], payables=lines["payables"][i], salary=lines["salary"][i],
			expenses=lines["expenses"][i], net=inflow - outflow)
		balance += row.net
		row.closing = balance
		data.append(row)

	if f.show == "Documents":
		cols = [{"label": _("In / Out"), "fieldname": "dir", "fieldtype": "Data", "width": 70},
			{"label": _("Type"), "fieldname": "doctype", "fieldtype": "Data", "width": 120},
			{"label": _("Document"), "fieldname": "name", "fieldtype": "Dynamic Link", "options": "doctype", "width": 170},
			{"label": _("Party"), "fieldname": "party", "fieldtype": "Data", "width": 220},
			{"label": _("Expected"), "fieldname": "due", "fieldtype": "Date", "width": 100},
			{"label": _("Amount"), "fieldname": "amount", "fieldtype": "Currency", "width": 130}]
		rows = [dict(zip(("dir", "doctype", "name", "party", "due", "amount"), d)) for d in sorted(detail, key=lambda d: getdate(d[4]))]
		return cols, rows, None, None, None

	c = lambda label, fn, w=120: {"label": label, "fieldname": fn, "fieldtype": "Currency", "width": w}
	cols = [{"label": _("Week"), "fieldname": "week", "fieldtype": "Data", "width": 130}, c(_("Opening"), "opening", 130),
		c(_("Customer Dues"), "receivables"), c(_("Cheques (PDC)"), "pdc"), c(_("Supplier Dues"), "payables"),
		c(_("Salaries"), "salary"), c(_("Running Expenses"), "expenses"), c(_("Net"), "net"), c(_("Closing"), "closing", 130)]
	chart = {"data": {"labels": [d.week for d in data], "datasets": [{"name": _("Closing balance"), "values": [round(d.closing) for d in data]}]},
		"type": "line", "fieldtype": "Currency", "colors": ["#d97757"]}
	low = min(data, key=lambda d: d.closing)
	summary = [
		{"label": _("Cash today"), "value": _cash_balance(), "datatype": "Currency"},
		{"label": _("Expected in"), "value": sum(d.receivables + d.pdc for d in data), "datatype": "Currency", "indicator": "green"},
		{"label": _("Expected out"), "value": sum(d.payables + d.salary + d.expenses for d in data), "datatype": "Currency", "indicator": "orange"},
		{"label": _("Lowest point ({0})").format(low.week), "value": low.closing, "datatype": "Currency",
			"indicator": "red" if low.closing < 0 else "blue"},
	]
	return cols, data, None, chart, summary


def _receivables(credit_days):
	if is_dev_billing_mode():
		from instabiz.overrides.ib_status import stored_statuses

		rows = frappe.db.sql("""SELECT 'Sales Order' AS doctype, name, customer AS party, delivery_date AS due_base,
			GREATEST(COALESCE(NULLIF(custom_total_with_gst, 0), grand_total) - IFNULL(custom_advance_paid, 0), 0) AS amount FROM `tabSales Order`
			WHERE docstatus = 1 AND per_billed < 100 AND status NOT IN %s""",
			(stored_statuses("Sales Order", "Closed", "Completed"),), as_dict=True)
		for r in rows:
			r.due = add_days(r.due_base or today(), credit_days)
	else:
		rows = frappe.db.sql("""SELECT 'Sales Invoice' AS doctype, name, customer AS party, IFNULL(due_date, posting_date) AS due,
			outstanding_amount AS amount FROM `tabSales Invoice` WHERE docstatus = 1 AND outstanding_amount > 0""", as_dict=True)
	return [r for r in rows if flt(r.amount) > 0]


def _payables(credit_days):
	if is_dev_billing_mode():
		rows = frappe.db.sql("""SELECT 'Purchase Order' AS doctype, name, supplier AS party, schedule_date AS due_base,
			grand_total * (100 - IFNULL(per_billed, 0)) / 100 AS amount FROM `tabPurchase Order`
			WHERE docstatus = 1 AND status NOT IN ('Closed', 'Cancelled', 'Completed')""", as_dict=True)
		for r in rows:
			r.due = add_days(r.due_base or today(), credit_days)
	else:
		rows = frappe.db.sql("""SELECT 'Purchase Invoice' AS doctype, name, supplier AS party, IFNULL(due_date, posting_date) AS due,
			outstanding_amount AS amount FROM `tabPurchase Invoice` WHERE docstatus = 1 AND outstanding_amount > 0""", as_dict=True)
	return [r for r in rows if flt(r.amount) > 0]


def _customer_delay():
	"""Average days each customer paid after the due date over the last year (0 if early)."""
	rows = frappe.db.sql("""SELECT si.customer, AVG(GREATEST(DATEDIFF(pe.posting_date, IFNULL(si.due_date, si.posting_date)), 0)) AS d
		FROM `tabPayment Entry Reference` per JOIN `tabPayment Entry` pe ON pe.name = per.parent
		JOIN `tabSales Invoice` si ON si.name = per.reference_name
		WHERE per.reference_doctype = 'Sales Invoice' AND pe.docstatus = 1 AND pe.posting_date >= %s
		GROUP BY si.customer""", add_months(today(), -12), as_dict=True)
	return {r.customer: int(flt(r.d)) for r in rows}


def _monthly_salary():
	row = frappe.db.sql("""SELECT end_date, SUM(net_pay) FROM `tabSalary Slip` WHERE docstatus = 1
		GROUP BY end_date ORDER BY end_date DESC LIMIT 1""")
	return flt(row[0][1]) if row else 0.0


def _monthly_expenses():
	since = get_first_day(add_months(today(), -3))
	total = frappe.db.sql("SELECT IFNULL(SUM(amount), 0) FROM `tabIB Expense` WHERE docstatus = 1 AND posting_date >= %s", since)[0][0]
	return flt(total) / 3


def _cash_balance():
	return flt(frappe.db.sql("""SELECT SUM(gle.debit - gle.credit) FROM `tabGL Entry` gle
		JOIN `tabAccount` a ON a.name = gle.account WHERE a.account_type IN ('Bank', 'Cash') AND gle.is_cancelled = 0""")[0][0])
