"""IB Bank Payment File — salaries or vendor payments as one bank bulk-upload file.
The table shows every payee and why a line is left out (no account / IFSC);
the Download button writes the HDFC upload CSV (instabiz.overrides.bank_payment_file)."""
import frappe
from frappe import _

from instabiz.overrides.bank_payment_file import ROLES, rows_for


def execute(filters=None):
	f = frappe._dict(filters or {})
	frappe.only_for(ROLES)
	rows = rows_for(f.source or "Salary", f.month, f.from_date, f.to_date)
	cols = [
		{"label": _("Voucher"), "fieldname": "voucher", "fieldtype": "Dynamic Link", "options": "source", "width": 170},
		{"label": _("Source"), "fieldname": "source", "fieldtype": "Data", "hidden": 1},
		{"label": _("Payee"), "fieldname": "name", "fieldtype": "Data", "width": 200},
		{"label": _("Amount"), "fieldname": "amount", "fieldtype": "Currency", "width": 120},
		{"label": _("Account No"), "fieldname": "account", "fieldtype": "Data", "width": 150},
		{"label": _("IFSC"), "fieldname": "ifsc", "fieldtype": "Data", "width": 110},
		{"label": _("Mode"), "fieldname": "mode", "fieldtype": "Data", "width": 60},
		{"label": _("Left out because"), "fieldname": "problem", "fieldtype": "Data", "width": 200},
	]
	ok = [r for r in rows if not r.problem]
	summary = [
		{"label": _("In file"), "value": len(ok), "datatype": "Int", "indicator": "green"},
		{"label": _("Amount in file"), "value": sum(r.amount for r in ok), "datatype": "Currency"},
		{"label": _("Left out"), "value": len(rows) - len(ok), "datatype": "Int", "indicator": "red" if len(rows) > len(ok) else "gray"},
	]
	return cols, rows, None, None, summary
