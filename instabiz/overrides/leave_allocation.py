"""instabiz.overrides.leave_allocation

Daily scheduler: make sure every active employee has this financial year's
Casual / Sick / Privilege leave. FY 2026-27 was allocated once by a script;
without this, balances drop to zero every 1 April. Also covers new joiners
the day after they are added (allocation starts on their joining date,
prorated by remaining whole months).

Days per year come from IB HR Settings. A leave type set to 0 is
skipped. Existing allocations are never touched, so re-running is safe.
"""
import math

import frappe
from frappe.utils import date_diff, getdate, today

from instabiz.overrides.ib_settings import get_check, get_float

_LEAVE_SETTINGS = (
	("Casual Leave", "annual_casual_leave", 12),
	("Sick Leave", "annual_sick_leave", 12),
	("Privilege Leave", "annual_privilege_leave", 15),
)


def _fiscal_year(on_date):
	from erpnext.accounts.utils import get_fiscal_year

	fy = get_fiscal_year(on_date, as_dict=True)
	return getdate(fy.year_start_date), getdate(fy.year_end_date)


def _prorated(annual, start, fy_start, fy_end):
	if start <= fy_start:
		return annual
	total_months = 12
	remaining = math.ceil(date_diff(fy_end, start) / 30.4)
	days = annual * min(remaining, total_months) / total_months
	return math.floor(days * 2) / 2  # nearest half day, rounded down


def run_yearly_leave_allocation(on_date=None):
	if not get_check("auto_allocate_leave", True):
		return
	on_date = getdate(on_date or today())
	try:
		fy_start, fy_end = _fiscal_year(on_date)
	except Exception:
		frappe.log_error("IB leave allocation: no fiscal year", frappe.get_traceback())
		return

	leave_types = [
		(lt, get_float(field, default)) for lt, field, default in _LEAVE_SETTINGS
		if frappe.db.exists("Leave Type", lt)
	]
	employees = frappe.get_all(
		"Employee",
		filters={"status": "Active"},
		fields=["name", "date_of_joining", "company"],
	)
	created = 0
	for emp in employees:
		start = max(fy_start, getdate(emp.date_of_joining or fy_start))
		if start > fy_end:
			continue
		for leave_type, annual in leave_types:
			if annual <= 0:
				continue
			exists = frappe.db.exists("Leave Allocation", {
				"employee": emp.name, "leave_type": leave_type, "docstatus": 1,
				"from_date": ["<=", fy_end], "to_date": [">=", fy_start],
			})
			if exists:
				continue
			days = _prorated(annual, start, fy_start, fy_end)
			if days <= 0:
				continue
			sp = f"ib_leave_{created}"
			frappe.db.savepoint(sp)
			try:
				alloc = frappe.get_doc({
					"doctype": "Leave Allocation",
					"employee": emp.name,
					"leave_type": leave_type,
					"from_date": start,
					"to_date": fy_end,
					"new_leaves_allocated": days,
					"description": "Auto-allocated from IB HR Settings",
				})
				alloc.insert(ignore_permissions=True)
				alloc.submit()
				created += 1
			except Exception:
				frappe.db.rollback(save_point=sp)
				frappe.log_error(f"IB leave allocation {emp.name} {leave_type}"[:140], frappe.get_traceback())
	frappe.db.commit()
	return created
