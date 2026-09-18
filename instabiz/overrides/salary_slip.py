from hrms.payroll.doctype.salary_slip.salary_slip import SalarySlip

_MONTHLY_LEAVE_CREDIT = 2.0


def _leave_credit():
	from instabiz.overrides.ib_settings import get_float
	return get_float("monthly_leave_credit", _MONTHLY_LEAVE_CREDIT)


class CustomSalarySlip(SalarySlip):
	def calculate_net_pay(self, skip_tax_breakup_computation: bool = False):
		if self.salary_structure == "IB Payroll":
			deducted = (self.leave_without_pay or 0) + (self.absent_days or 0)
			credit = min(_leave_credit(), deducted)
			if credit > 0:
				self.payment_days = (self.payment_days or 0) + credit
		super().calculate_net_pay(skip_tax_breakup_computation=skip_tax_breakup_computation)
