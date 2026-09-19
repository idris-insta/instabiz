"""IB Loan Register — every employee loan / advance: amount, monthly deduction,
recovered, balance, next deduction month and status."""
import frappe
from frappe import _
from frappe.utils import flt, getdate, today


def execute(filters=None):
	f = frappe._dict(filters or {})
	flt_ = {"docstatus": 1}
	for k in ("employee", "status", "loan_type"):
		if f.get(k):
			flt_[k] = f.get(k)
	loans = frappe.get_all("IB Employee Loan", filters=flt_, fields=["name", "employee", "employee_name", "loan_type", "posting_date",
		"amount", "instalments", "emi", "recovered_amount", "balance_amount", "status", "payment_entry"], order_by="posting_date desc")
	for l in loans:
		nxt = frappe.get_all("IB Loan Instalment", filters={"parent": l.name, "status": "Pending"}, fields=["payroll_month"],
			order_by="payroll_month asc", limit=1)
		l.next_month = getdate(nxt[0].payroll_month).strftime("%b %Y") if nxt else ""
		l.left = frappe.db.count("IB Loan Instalment", {"parent": l.name, "status": "Pending"})
		l.paid_out = bool(l.payment_entry)
	cols = [{"label": _("Loan"), "fieldname": "name", "fieldtype": "Link", "options": "IB Employee Loan", "width": 140},
		{"label": _("Employee"), "fieldname": "employee_name", "fieldtype": "Data", "width": 180},
		{"label": _("Type"), "fieldname": "loan_type", "fieldtype": "Data", "width": 120},
		{"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 95},
		{"label": _("Amount"), "fieldname": "amount", "fieldtype": "Currency", "width": 110},
		{"label": _("Monthly"), "fieldname": "emi", "fieldtype": "Currency", "width": 100},
		{"label": _("Recovered"), "fieldname": "recovered_amount", "fieldtype": "Currency", "width": 110},
		{"label": _("Balance"), "fieldname": "balance_amount", "fieldtype": "Currency", "width": 110},
		{"label": _("Instalments Left"), "fieldname": "left", "fieldtype": "Int", "width": 110},
		{"label": _("Next Deduction"), "fieldname": "next_month", "fieldtype": "Data", "width": 110},
		{"label": _("Paid Out"), "fieldname": "paid_out", "fieldtype": "Check", "width": 80},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 90}]
	summary = [{"label": _("Loans"), "value": len(loans), "datatype": "Int"},
		{"label": _("Given"), "value": sum(flt(l.amount) for l in loans), "datatype": "Currency"},
		{"label": _("Recovered"), "value": sum(flt(l.recovered_amount) for l in loans), "datatype": "Currency", "indicator": "green"},
		{"label": _("Outstanding"), "value": sum(flt(l.balance_amount) for l in loans), "datatype": "Currency", "indicator": "orange"}]
	return cols, loans, None, None, summary
