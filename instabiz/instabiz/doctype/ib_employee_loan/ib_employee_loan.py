"""IB Employee Loan — loan or salary advance recovered from salary.

On submit the schedule becomes one submitted Additional Salary per month
(deduction component "Loan Recovery"), so each month's salary slip picks up its
instalment by itself. The last instalment takes the rounding difference.
"Skip a month" cancels that month's deduction and adds one more month at the
end. A daily run marks instalments Deducted once the month's salary slip is
submitted and closes the loan when nothing is left.
"""
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_months, flt, get_first_day, get_last_day, getdate, today

COMPONENT = "Loan Recovery"


class IBEmployeeLoan(Document):
	ignore_linked_doctypes = ("Additional Salary",)

	def before_insert(self):
		_ensure_component(self.salary_component or COMPONENT)

	def validate(self):
		if flt(self.amount) <= 0 or int(self.instalments or 0) <= 0:
			frappe.throw(_("Amount and No. of Instalments must be more than zero."))
		self.repayment_start = get_first_day(self.repayment_start)
		self.salary_component = self.salary_component or COMPONENT
		self.emi = round(flt(self.amount) / int(self.instalments))
		if self.docstatus == 0:
			self._build_schedule()
		self._totals()

	def _build_schedule(self):
		self.schedule = []
		left = flt(self.amount)
		for i in range(int(self.instalments)):
			amt = left if i == int(self.instalments) - 1 else min(self.emi, left)
			self.append("schedule", {"payroll_month": add_months(self.repayment_start, i), "amount": amt, "status": "Pending"})
			left -= amt

	def _totals(self):
		self.recovered_amount = sum(flt(r.amount) for r in self.schedule if r.status == "Deducted")
		self.balance_amount = flt(self.amount) - self.recovered_amount

	def on_submit(self):
		_ensure_component(self.salary_component)
		for row in self.schedule:
			self._deduction(row)
		self.db_set("status", "Active")
		self.save_schedule()

	def on_cancel(self):
		for row in self.schedule:
			if row.status == "Pending":
				_cancel_addl(row.additional_salary)
		self.db_set("status", "Cancelled")

	def _deduction(self, row):
		if row.additional_salary:
			return
		addl = frappe.get_doc({
			"doctype": "Additional Salary", "employee": self.employee, "company": self.company,
			"salary_component": self.salary_component, "type": "Deduction", "amount": row.amount,
			"payroll_date": getdate(row.payroll_month), "overwrite_salary_structure_amount": 0,
			"ref_doctype": "IB Employee Loan", "ref_docname": self.name,
		})
		addl.insert(ignore_permissions=True)
		addl.submit()
		row.additional_salary = addl.name

	def save_schedule(self):
		for row in self.schedule:
			row.db_update()
		self._totals()
		self.db_set({"recovered_amount": self.recovered_amount, "balance_amount": self.balance_amount})


def _ensure_component(name):
	if not frappe.db.exists("Salary Component", name):
		frappe.get_doc({"doctype": "Salary Component", "salary_component": name, "salary_component_abbr": "LR",
			"type": "Deduction", "depends_on_payment_days": 0, "is_tax_applicable": 0,
			"description": "Employee loan / salary advance recovery (IB Employee Loan)"}).insert(ignore_permissions=True)


def after_migrate():
	_ensure_component(COMPONENT)


def _cancel_addl(name):
	if name and frappe.db.get_value("Additional Salary", name, "docstatus") == 1:
		addl = frappe.get_doc("Additional Salary", name)
		addl.flags.ignore_permissions = True
		addl.flags.ignore_links = True  # the loan's schedule row points at it
		addl.cancel()


@frappe.whitelist()
def skip_month(loan, row_name):
	"""Push one pending instalment to the end of the schedule."""
	doc = frappe.get_doc("IB Employee Loan", loan)
	doc.check_permission("submit")
	row = next((r for r in doc.schedule if r.name == row_name), None)
	if not row or row.status != "Pending":
		frappe.throw(_("Only a pending instalment can be skipped."))
	if frappe.db.exists("Salary Slip", {"employee": doc.employee, "docstatus": 1,
			"start_date": ["<=", row.payroll_month], "end_date": [">=", row.payroll_month]}):
		frappe.throw(_("That month's salary slip is already submitted."))
	_cancel_addl(row.additional_salary)
	row.status, row.additional_salary = "Skipped", None
	last = max(getdate(r.payroll_month) for r in doc.schedule)
	new = doc.append("schedule", {"payroll_month": add_months(last, 1), "amount": row.amount, "status": "Pending"})
	new.parent, new.parenttype, new.parentfield, new.idx = doc.name, doc.doctype, "schedule", len(doc.schedule)
	doc._deduction(new)
	new.db_insert()
	doc.save_schedule()
	doc.add_comment("Info", _("Instalment of {0} moved from {1} to {2}").format(
		frappe.format_value(row.amount, {"fieldtype": "Currency"}), getdate(row.payroll_month).strftime("%b %Y"),
		getdate(new.payroll_month).strftime("%b %Y")))
	return new.payroll_month


def run_loan_recovery():
	"""Daily: an instalment is Deducted once a submitted salary slip covers its month."""
	loans = frappe.get_all("IB Employee Loan", filters={"docstatus": 1, "status": "Active"}, pluck="name")
	for name in loans:
		doc = frappe.get_doc("IB Employee Loan", name)
		changed = False
		for row in doc.schedule:
			if row.status != "Pending" or getdate(row.payroll_month) > getdate(today()):
				continue
			slip = frappe.db.exists("Salary Slip", {"employee": doc.employee, "docstatus": 1,
				"start_date": ["<=", get_last_day(row.payroll_month)], "end_date": [">=", get_first_day(row.payroll_month)]})
			if slip:
				row.status, changed = "Deducted", True
		if changed:
			doc.save_schedule()
			if doc.balance_amount <= 0.5:
				doc.db_set("status", "Repaid")
	frappe.db.commit()
