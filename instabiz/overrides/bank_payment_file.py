"""instabiz.overrides.bank_payment_file

Bulk payment upload file for the bank (HDFC ENet "bulk upload" layout): one
line per salary slip or vendor payment, so salaries and supplier payments go
out in one upload instead of one transfer at a time.

  salary  — submitted Salary Slips for a month (net pay → employee bank a/c)
  vendor  — submitted Pay Payment Entries to Suppliers in a date range
            (paid amount → the supplier's Bank Account on the entry)

Rows without an account number or IFSC are listed with a reason and left out
of the file. Transfer mode: I = HDFC to HDFC, R = RTGS (₹2 lakh and above),
N = NEFT otherwise.
"""
import csv
import io
import re

import frappe
from frappe import _
from frappe.utils import flt, get_first_day, get_last_day, getdate

ROLES = ("System Manager", "Accounts Manager", "Accounts User", "HR Manager")
RTGS_FROM = 200000
HEADER = [
	"Transaction Type", "Beneficiary Code", "Beneficiary Account Number", "Instrument Amount",
	"Beneficiary Name", "Drawee Location", "Print Location", "Bene Address 1", "Bene Address 2",
	"Bene Address 3", "Bene Address 4", "Bene Address 5", "Instruction Reference Number",
	"Customer Reference Number", "Payment details 1", "Payment details 2", "Payment details 3",
	"Payment details 4", "Payment details 5", "Payment details 6", "Payment details 7",
	"Cheque Number", "Chq / Trn Date", "MICR Number", "IFC Code", "Beneficiary Bank Name",
	"Beneficiary Bank Branch Name", "Beneficiary email id",
]
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")


def _mode(ifsc, amount):
	if (ifsc or "").startswith("HDFC"):
		return "I"
	return "R" if flt(amount) >= RTGS_FROM else "N"


def _ifsc(raw):
	m = re.search(r"[A-Z]{4}0[A-Z0-9]{6}", (raw or "").upper())
	return m.group(0) if m else ""


def salary_rows(month):
	start, end = get_first_day(getdate(month)), get_last_day(getdate(month))
	slips = frappe.db.sql(
		"""SELECT ss.name, ss.employee, ss.employee_name, ss.net_pay, ss.end_date,
		       e.bank_ac_no, e.ifsc_code, e.bank_name, e.personal_email, e.company_email
		FROM `tabSalary Slip` ss JOIN `tabEmployee` e ON e.name = ss.employee
		WHERE ss.docstatus = 1 AND ss.start_date >= %s AND ss.end_date <= %s AND ss.net_pay > 0
		ORDER BY ss.employee_name""", (start, end), as_dict=True)
	label = start.strftime("%b %Y")
	return [frappe._dict(
		source="Salary Slip", voucher=s.name, code=s.employee, name=s.employee_name, amount=flt(s.net_pay, 2),
		account=(s.bank_ac_no or "").replace(" ", ""), ifsc=_ifsc(s.ifsc_code), bank=s.bank_name,
		email=s.company_email or s.personal_email, narration=f"SALARY {label}".upper(),
	) for s in slips]


def vendor_rows(from_date, to_date):
	pes = frappe.db.sql(
		"""SELECT pe.name, pe.party, pe.party_name, pe.paid_amount, pe.reference_no,
		       ba.bank_account_no, ba.branch_code, ba.bank
		FROM `tabPayment Entry` pe LEFT JOIN `tabBank Account` ba ON ba.name = pe.party_bank_account
		WHERE pe.docstatus = 1 AND pe.payment_type = 'Pay' AND pe.party_type = 'Supplier'
		  AND pe.posting_date BETWEEN %s AND %s
		ORDER BY pe.posting_date, pe.name""", (from_date, to_date), as_dict=True)
	return [frappe._dict(
		source="Payment Entry", voucher=p.name, code=p.party, name=p.party_name, amount=flt(p.paid_amount, 2),
		account=(p.bank_account_no or "").replace(" ", ""), ifsc=_ifsc(p.branch_code), bank=p.bank,
		email=None, narration=(p.reference_no or p.name)[:30],
	) for p in pes]


def rows_for(source, month=None, from_date=None, to_date=None):
	rows = salary_rows(month) if source == "Salary" else vendor_rows(from_date, to_date)
	for r in rows:
		problems = []
		if not r.account:
			problems.append(_("no account number"))
		if not IFSC_RE.match(r.ifsc or ""):
			problems.append(_("no valid IFSC"))
		r.problem = ", ".join(problems)
		r.mode = "" if r.problem else _mode(r.ifsc, r.amount)
	return rows


@frappe.whitelist()
def download(source, month=None, from_date=None, to_date=None):
	frappe.only_for(ROLES)
	rows = [r for r in rows_for(source, month, from_date, to_date) if not r.problem]
	if not rows:
		frappe.throw(_("Nothing to pay — no rows with a bank account and IFSC."))
	out = io.StringIO()
	w = csv.writer(out)
	w.writerow(HEADER)
	today = getdate().strftime("%d/%m/%Y")
	for r in rows:
		line = [""] * len(HEADER)
		line[0], line[1], line[2], line[3], line[4] = r.mode, (r.code or "")[:13], r.account, f"{r.amount:.2f}", (r.name or "")[:40]
		line[12], line[13], line[14] = r.voucher[:20], r.voucher[:20], r.narration
		line[22], line[24], line[25], line[27] = today, r.ifsc, (r.bank or "")[:40], r.email or ""
		w.writerow(line)
	name = f"{source.lower()}_payments_{month or from_date}.csv"
	return {"filename": name, "content": out.getvalue(), "count": len(rows), "total": sum(r.amount for r in rows)}
