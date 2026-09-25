import frappe
from frappe import _
from frappe.utils import now_datetime, today

_PRIVILEGED_ROLES = {"System Manager", "HR Manager", "HR User"}
_SALES_USER_ROLE  = "Sales User"


def _is_sales_user(user=None):
	return _SALES_USER_ROLE in frappe.get_roles(user or frappe.session.user)


def employee_checkin_has_permission(doc, ptype, user=None):
	if _is_sales_user(user or frappe.session.user):
		return False
	return None


def employee_checkin_query_conditions(user=None):
	if _is_sales_user(user or frappe.session.user):
		return "1=0"
	return ""


def _is_privileged():
	return bool(_PRIVILEGED_ROLES & set(frappe.get_roles(frappe.session.user)))


@frappe.whitelist()
def get_my_status():
	"""Return today's checkin status for the logged-in employee."""
	employee = _get_employee_for_user()

	rows = frappe.db.sql(
		"""
		SELECT log_type, time
		FROM `tabEmployee Checkin`
		WHERE employee = %(employee)s
		  AND DATE(time) = %(today)s
		ORDER BY time ASC
		""",
		{"employee": employee.name, "today": today()},
		as_dict=True,
	)

	if not rows:
		log_type  = None
		last_time = None
	elif any(r.log_type == "IN" for r in rows) and any(r.log_type == "OUT" for r in rows):
		log_type  = "DONE"
		last_time = str(rows[-1].time)
	else:
		log_type  = rows[-1].log_type
		last_time = str(rows[-1].time)

	duration = None
	if log_type == "IN" and last_time:
		from frappe.utils import time_diff_in_seconds
		secs = time_diff_in_seconds(now_datetime(), rows[-1].time)
		h, m = divmod(int(secs) // 60, 60)
		duration = f"{h}h {m}m" if h else f"{m}m"

	return {
		"employee":          employee.name,
		"employee_name":     employee.employee_name,
		"log_type":          log_type,
		"last_checkin_time": last_time,
		"duration":          duration,
	}


@frappe.whitelist()
def self_checkin(log_type, latitude=None, longitude=None):
	"""Check in or out for the logged-in employee."""
	if log_type not in ("IN", "OUT"):
		frappe.throw(_("Invalid log_type"))

	employee = _get_employee_for_user()

	# Prevent consecutive duplicate log types (IN→IN or OUT→OUT)
	last = frappe.db.sql(
		"SELECT log_type FROM `tabEmployee Checkin`"
		" WHERE employee = %s AND DATE(time) = %s"
		" ORDER BY time DESC LIMIT 1",
		(employee.name, today()),
		as_dict=True,
	)
	if last and last[0].log_type == log_type:
		label = _("in") if log_type == "IN" else _("out")
		frappe.throw(_("You are already checked {0}.").format(label))

	shift    = frappe.db.get_value("Employee", employee.name, "default_shift")

	doc = frappe.get_doc({
		"doctype":   "Employee Checkin",
		"employee":  employee.name,
		"log_type":  log_type,
		"time":      now_datetime(),
		"device_id": "Self Service",
		"shift":     shift,
	})

	if latitude and longitude:
		doc.latitude  = float(latitude)
		doc.longitude = float(longitude)

	doc.insert(ignore_permissions=True)
	return {"log_type": log_type}


@frappe.whitelist()
def get_daily_attendance(date=None, department=None, search=None, limit=20, offset=0):
	"""
	Return one row per employee with IN time, OUT time and work hours
	for the given date. Used by the Employee Checkin list view.
	"""
	# This queries via raw SQL (bypasses ORM permission query conditions), so it
	# must replicate employee_checkin_query_conditions/has_permission's own
	# exclusion of Sales User explicitly — previously this RPC had no gate at
	# all, letting a Sales User pull company-wide attendance data that the
	# doctype's own permission hooks are specifically designed to hide from them.
	# `and not _is_privileged()` matters because frappe.get_roles() returns every
	# role for Administrator (including "Sales User") — a bare _is_sales_user()
	# check here permanently broke this RPC for Administrator (and would for any
	# real HR Manager/HR User who also happens to hold the Sales User role),
	# unlike undo_attendance() below which already gates on _is_privileged().
	if _is_sales_user() and not _is_privileged():
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	limit  = int(limit)
	offset = int(offset)
	if not date:
		date = today()

	filters = {"status": "Active"}
	if department and department.strip():
		filters["department"] = ["like", f"%{department.strip()}%"]

	all_employees = frappe.get_all(
		"Employee",
		filters=filters,
		fields=["name", "employee_name", "department", "designation"],
		order_by="employee_name asc",
	)

	if not all_employees:
		return {"data": [], "total": 0}

	if search:
		s = search.lower()
		all_employees = [
			e for e in all_employees
			if s in (e.employee_name or "").lower() or s in (e.name or "").lower()
		]

	if not all_employees:
		return {"data": [], "total": 0}

	emp_names = [e.name for e in all_employees]

	# Employee Checkin logs (used for today / recent dates with device data)
	checkin_rows = frappe.db.sql(
		"""
		SELECT employee, log_type, time
		FROM `tabEmployee Checkin`
		WHERE employee IN %(employees)s
		  AND DATE(time) = %(date)s
		ORDER BY time ASC
		""",
		{"employees": emp_names, "date": date},
		as_dict=True,
	)

	logs_by_emp = {}
	for r in checkin_rows:
		logs_by_emp.setdefault(r.employee, []).append(r)

	# Submitted Attendance records (covers backfilled / processed months)
	att_rows = frappe.db.sql(
		"""
		SELECT employee, status, in_time, out_time, working_hours
		FROM `tabAttendance`
		WHERE employee IN %(employees)s
		  AND attendance_date = %(date)s
		  AND docstatus = 1
		""",
		{"employees": emp_names, "date": date},
		as_dict=True,
	)
	att_by_emp = {r.employee: r for r in att_rows}

	total = len(all_employees)
	paged = all_employees[offset: offset + limit]

	data = []
	for emp in paged:
		logs     = logs_by_emp.get(emp.name, [])
		in_time  = None
		out_time = None
		last_in  = None

		for log in logs:
			if log.log_type == "IN":
				if not in_time:
					in_time = log.time
				last_in = log.time
			elif log.log_type == "OUT":
				out_time = log.time

		if in_time and out_time:
			status = "OUT"
			delta  = (out_time - in_time).total_seconds()
			h, rem = divmod(int(delta), 3600)
			m      = rem // 60
			work_hours = f"{h}h {m}m" if h else f"{m}m"
		elif in_time:
			status     = "IN"
			work_hours = None
		else:
			# No checkin logs — fall back to submitted Attendance record
			att = att_by_emp.get(emp.name)
			if att:
				if att.status == "Present":
					status     = "Present"
					in_time    = att.in_time
					out_time   = att.out_time
					if att.working_hours:
						h, rem = divmod(int(float(att.working_hours) * 3600), 3600)
						m      = rem // 60
						work_hours = f"{h}h {m}m" if h else f"{m}m"
					else:
						work_hours = None
				elif att.status == "Half Day":
					status     = "Half Day"
					in_time    = att.in_time
					out_time   = att.out_time
					work_hours = None
				else:
					status     = "Absent"
					work_hours = None
			else:
				status     = "Absent"
				work_hours = None

		data.append({
			"employee":      emp.name,
			"employee_name": emp.employee_name,
			"department":    emp.department or "—",
			"designation":   emp.designation or "—",
			"status":        status,
			"in_time":       str(in_time)  if in_time  else None,
			"out_time":      str(out_time) if out_time else None,
			"work_hours":    work_hours,
			"last_in":       str(last_in)  if last_in  else None,
			"can_undo":      bool(logs) or bool(att_by_emp.get(emp.name)),
		})

	# Summary counts across ALL employees (not just the current page)
	# An employee is "present" if they have checkin logs OR a non-Absent submitted attendance
	def _is_present(e):
		if logs_by_emp.get(e.name):
			return True
		att = att_by_emp.get(e.name)
		return att and att.status in ("Present", "Half Day")

	present  = sum(1 for e in all_employees if _is_present(e))
	absent   = sum(1 for e in all_employees if not _is_present(e))
	still_in = 0
	for e in all_employees:
		logs = logs_by_emp.get(e.name, [])
		has_in  = any(l.log_type == "IN"  for l in logs)
		has_out = any(l.log_type == "OUT" for l in logs)
		if has_in and not has_out:
			still_in += 1

	return {
		"data":       data,
		"total":      total,
		"privileged": _is_privileged(),
		"summary": {
			"present":  present,
			"absent":   absent,
			"still_in": still_in,
		},
	}


@frappe.whitelist()
def undo_attendance(employee, date):
	"""Admin only: delete checkin logs and cancel submitted attendance for employee on date."""
	if not _is_privileged():
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	checkin_names = [r[0] for r in frappe.db.sql(
		"SELECT name FROM `tabEmployee Checkin` WHERE employee = %s AND DATE(time) = %s",
		(employee, date),
	)]
	for name in checkin_names:
		frappe.delete_doc("Employee Checkin", name, ignore_permissions=True, force=True)

	att_names = [r[0] for r in frappe.db.sql(
		"SELECT name FROM `tabAttendance` WHERE employee = %s AND attendance_date = %s AND docstatus = 1",
		(employee, date),
	)]
	for name in att_names:
		frappe.get_doc("Attendance", name).cancel()

	return {"checkins": len(checkin_names), "attendance": len(att_names)}


def _get_employee_for_user():
	"""Resolve the active Employee linked to the current session user."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	employee = frappe.db.get_value(
		"Employee",
		{"user_id": frappe.session.user, "status": "Active"},
		["name", "employee_name"],
		as_dict=True,
	)
	if not employee:
		frappe.throw(_("No active Employee record linked to your account."))
	return employee
