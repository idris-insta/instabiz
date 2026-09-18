"""instabiz.overrides.overtime

Overtime is paid at the regular salary rate (user decision 2026-09-18):

	per-day rate  = monthly base (Salary Structure Assignment.base) / day basis
	per-hour rate = per-day rate / working hours per day
	overtime pay  = hours x per-hour rate x multiplier (1 = regular rate)

Day basis, hours per day and the multiplier live in Instabiz Settings (HR tab).
An approved IB Overtime Request becomes a submitted Additional Salary on the
overtime date, so the next salary slip for that month pays it. Rejecting (or
un-approving) the request cancels that Additional Salary.
"""
import calendar

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from instabiz.overrides.ib_settings import get, get_check, get_float

_DEFAULT_COMPONENT = "Overtime"


def _day_basis(on_date=None):
	basis = get("ot_day_basis", "26 days")
	if basis == "30 days":
		return 30
	if basis == "Days in the month":
		d = getdate(on_date or today())
		return calendar.monthrange(d.year, d.month)[1]
	return 26


def rates_for(monthly, on_date=None):
	"""(per_day, per_hour) for a monthly salary."""
	per_day = flt(monthly) / _day_basis(on_date)
	per_hour = per_day / get_float("ot_hours_per_day", 8.0)
	return flt(per_day, 2), flt(per_hour, 2)


def _assignment(employee, on_date):
	rows = frappe.get_all(
		"Salary Structure Assignment",
		filters={"employee": employee, "docstatus": 1, "from_date": ["<=", on_date]},
		fields=["name", "base", "company"],
		order_by="from_date desc",
		limit=1,
	)
	return rows[0] if rows else None


@frappe.whitelist()
def get_employee_rates(employee, on_date=None):
	on_date = on_date or today()
	if not frappe.has_permission("Employee", "read", employee):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	ssa = _assignment(employee, on_date)
	if not ssa:
		return {"monthly": 0, "per_day": 0, "per_hour": 0}
	per_day, per_hour = rates_for(ssa.base, on_date)
	return {"monthly": flt(ssa.base), "per_day": per_day, "per_hour": per_hour}


@frappe.whitelist()
def preview_rates(monthly, on_date=None):
	per_day, per_hour = rates_for(monthly, on_date)
	return {"per_day": per_day, "per_hour": per_hour}


# ── Salary Structure Assignment (doc_events.validate) ───────────────────────────

def set_assignment_rates(doc, method=None):
	per_day, per_hour = rates_for(doc.base, doc.from_date)
	doc.custom_per_day_rate = per_day
	doc.custom_per_hour_rate = per_hour


# ── IB Overtime Request ─────────────────────────────────────────────────────────

def compute_request_pay(doc):
	ssa = _assignment(doc.employee, doc.date or today()) if doc.employee else None
	if not ssa:
		doc.hourly_rate = 0
		doc.ot_amount = 0
		return
	_, per_hour = rates_for(ssa.base, doc.date)
	doc.hourly_rate = per_hour
	doc.ot_amount = flt(flt(doc.overtime_hours) * per_hour * get_float("ot_rate_multiplier", 1.0), 2)


def sync_additional_salary(doc):
	"""Create / cancel the Additional Salary that carries this overtime into payroll."""
	if doc.status == "Approved":
		if doc.additional_salary or not get_check("ot_pay_on_approval", True):
			return
		if flt(doc.ot_amount) <= 0:
			frappe.msgprint(
				_("Overtime approved but not added to payroll: {0} has no salary structure assignment "
				  "on {1}, so no hourly rate could be worked out.").format(doc.employee_name or doc.employee, doc.date),
				indicator="orange",
			)
			return
		ssa = _assignment(doc.employee, doc.date)
		addl = frappe.get_doc({
			"doctype": "Additional Salary",
			"employee": doc.employee,
			"company": ssa.company,
			"salary_component": _ensure_component(),
			"type": "Earning",
			"amount": doc.ot_amount,
			"payroll_date": doc.date,
			"overwrite_salary_structure_amount": 0,
			"ref_doctype": "IB Overtime Request",
			"ref_docname": doc.name,
		})
		addl.insert(ignore_permissions=True)
		addl.submit()
		doc.db_set("additional_salary", addl.name, update_modified=False)
		frappe.msgprint(
			_("Overtime of {0} added to payroll ({1}).").format(
				frappe.format_value(doc.ot_amount, {"fieldtype": "Currency"}), addl.name
			),
			indicator="green", alert=True,
		)
	elif doc.additional_salary:
		addl = frappe.get_doc("Additional Salary", doc.additional_salary)
		if addl.docstatus == 1:
			addl.flags.ignore_permissions = True
			addl.cancel()
		doc.db_set("additional_salary", None, update_modified=False)


def _ensure_component():
	name = get("ot_salary_component") or _DEFAULT_COMPONENT
	if not frappe.db.exists("Salary Component", name):
		frappe.get_doc({
			"doctype": "Salary Component",
			"salary_component": name,
			"salary_component_abbr": "OT",
			"type": "Earning",
			"depends_on_payment_days": 0,
			"is_tax_applicable": 1,
			"description": "Approved overtime (IB Overtime Request)",
		}).insert(ignore_permissions=True)
	return name


def refresh_assignment_rates(only_missing=False):
	"""Write per-day / per-hour rates onto Salary Structure Assignments.
	Runs after migrate (fills older records) and when the day basis changes."""
	if not frappe.db.has_column("Salary Structure Assignment", "custom_per_day_rate"):
		return
	rows = frappe.get_all(
		"Salary Structure Assignment",
		filters={"docstatus": ["!=", 2]},
		fields=["name", "base", "from_date", "custom_per_day_rate"],
	)
	for row in rows:
		if only_missing and row.custom_per_day_rate:
			continue
		per_day, per_hour = rates_for(row.base, row.from_date)
		frappe.db.set_value(
			"Salary Structure Assignment", row.name,
			{"custom_per_day_rate": per_day, "custom_per_hour_rate": per_hour},
			update_modified=False,
		)


def after_migrate():
	refresh_assignment_rates(only_missing=True)
