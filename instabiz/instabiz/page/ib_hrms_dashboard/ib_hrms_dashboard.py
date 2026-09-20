import frappe
from frappe.utils import add_months, flt, get_first_day, get_last_day, getdate, nowdate

from instabiz.overrides.utils import build_multi_token_where_named

def get_context(context):
	context.no_cache = 1


@frappe.whitelist()
def get_hrms_data(month=None, att_search=None, att_status=None, leave_search=None,
				   leave_status=None, pay_search=None, pay_status=None,
				   att_offset=0, leave_offset=0, pay_offset=0, page_size=20):
	frappe.only_for(["HR Manager", "HR User", "Factory Management", "System Manager"])
	att_offset, leave_offset, pay_offset, page_size = int(att_offset), int(leave_offset), int(pay_offset), int(page_size)
	today = getdate(nowdate())
	month_date = getdate(month) if month else today
	month_start = get_first_day(month_date)
	month_end = get_last_day(month_date)

	# ── Employees ─────────────────────────────────────────────────────────────
	try:
		total_emp = flt(frappe.db.sql(
			"SELECT COUNT(*) FROM `tabEmployee` WHERE status='Active'"
		)[0][0])
	except Exception:
		total_emp = 0

	try:
		from frappe.utils import today as get_today
		today = get_today()
		# 1. Active Employees Count
		total_emp = frappe.db.count("Employee", filters={"status": "Active"})

		# 2. Present Today (Check-ins + Submitted Attendance)
		checkin_emps = frappe.db.sql_list(
			"SELECT DISTINCT employee FROM `tabEmployee Checkin` WHERE DATE(time) = %s AND log_type = 'IN'",
			(today,)
		)
		attendance_present_emps = frappe.db.sql_list(
			"SELECT DISTINCT employee FROM `tabAttendance` WHERE attendance_date = %s AND status = 'Present' AND docstatus = 1",
			(today,)
		)
		present_set = set(checkin_emps + attendance_present_emps)
		present_today = len(present_set)

		# 3. Employees On Approved Leave Today
		on_leave_emps = frappe.db.sql_list("""
			SELECT DISTINCT employee 
			FROM `tabLeave Application` 
			WHERE %s BETWEEN from_date AND to_date 
			AND status = 'Approved' 
			AND docstatus = 1
		""", (today,))
		on_leave_today = len(set(on_leave_emps))

		# 4. Absent Today (The Default State)
		# Prevents negative counts if data has overlaps
		absent_today = max(0, total_emp - (present_today + on_leave_today))

	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "Attendance Dashboard Error")
		present_today = absent_today = total_emp = 0

	# ── Pending leaves ────────────────────────────────────────────────────────
	try:
		pending_leaves = frappe.db.count("Leave Application", filters={
    	"status": "Open",
    	"docstatus": 0 })
	except Exception:
		pending_leaves = 0

	# ── Payroll MTD ───────────────────────────────────────────────────────────
	try:
		payroll_row = frappe.db.sql("""
			SELECT
				COALESCE(SUM(CASE WHEN docstatus=1 THEN net_pay ELSE 0 END), 0) AS submitted_net,
				COALESCE(SUM(CASE WHEN docstatus=0 THEN net_pay ELSE 0 END), 0) AS draft_net,
				COALESCE(SUM(CASE WHEN docstatus=0 THEN 1 ELSE 0 END), 0)       AS draft_count,
				COALESCE(SUM(CASE WHEN docstatus=1 THEN 1 ELSE 0 END), 0)       AS submitted_count
			FROM `tabSalary Slip`
			WHERE docstatus < 2
			AND start_date BETWEEN %s AND %s
		""", (month_start, month_end))[0]
		payroll_mtd             = flt(payroll_row[0]) or flt(payroll_row[1])
		payroll_draft_count     = int(payroll_row[2])
		payroll_submitted_count = int(payroll_row[3])
		payroll_is_draft        = flt(payroll_row[0]) == 0 and flt(payroll_row[1]) > 0
	except Exception:
		payroll_mtd = payroll_draft_count = payroll_submitted_count = 0
		payroll_is_draft = False

	# ── Attendance for month ──────────────────────────────────────────────────
	# Real `tabAttendance` rows only ever get a submitted "Present" record via
	# HRMS's own end-of-day auto-attendance job — never live, intra-day. So a
	# plain query against it always shows today's real check-ins as missing,
	# even though the "Present Today" KPI above (computed live from Employee
	# Checkin) already knows better. UNION in a synthetic "Present" row per
	# employee who checked in today but has no Attendance doc yet, so the list
	# and the KPI can't disagree. Only applies to today's date — every other
	# day in the range is fully settled and read from `tabAttendance` alone.
	try:
		conditions = ["combined.attendance_date BETWEEN %(month_start)s AND %(month_end)s"]
		params = {"month_start": month_start, "month_end": month_end, "today": today}
		if att_status:
			conditions.append("combined.status = %(att_status)s")
			params["att_status"] = att_status
		att_cond, att_extra = build_multi_token_where_named(["combined.employee_name", "combined.employee"], att_search, "att_tok")
		if att_cond:
			conditions.append(att_cond)
			params.update(att_extra)

		combined_sql = """
			SELECT a.employee AS employee, e.employee_name AS employee_name, e.department AS department,
				   a.attendance_date AS attendance_date, a.status AS status, a.in_time AS in_time, a.out_time AS out_time
			FROM `tabAttendance` a
			LEFT JOIN `tabEmployee` e ON e.name = a.employee
			WHERE a.docstatus = 1

			UNION ALL

			SELECT ec.employee AS employee, e2.employee_name AS employee_name, e2.department AS department,
				   %(today)s AS attendance_date, 'Present' AS status, MIN(ec.time) AS in_time,
				   MAX(CASE WHEN ec.log_type = 'OUT' THEN ec.time END) AS out_time
			FROM `tabEmployee Checkin` ec
			LEFT JOIN `tabEmployee` e2 ON e2.name = ec.employee
			WHERE DATE(ec.time) = %(today)s
			  AND ec.log_type = 'IN'
			  AND NOT EXISTS (
				  SELECT 1 FROM `tabAttendance` a2
				  WHERE a2.employee = ec.employee AND a2.attendance_date = %(today)s AND a2.docstatus = 1
			  )
			GROUP BY ec.employee
		"""

		attendance_total = int(frappe.db.sql(f"""
			SELECT COUNT(*) FROM ({combined_sql}) combined
			WHERE {' AND '.join(conditions)}
		""", params)[0][0])
		attendance_list = frappe.db.sql(f"""
			SELECT * FROM ({combined_sql}) combined
			WHERE {' AND '.join(conditions)}
			ORDER BY combined.attendance_date DESC, combined.employee
			LIMIT %(page_size)s OFFSET %(att_offset)s
		""", {**params, "page_size": page_size, "att_offset": att_offset}, as_dict=True)
	except Exception:
		attendance_list, attendance_total = [], 0

	# ── Leave applications ────────────────────────────────────────────────────
	try:
		# docstatus IN (0, 1), not just 1: a self-service Leave Application
		# stays Draft (docstatus=0) with status="Open" while pending approval
		# (see ib_my_hr.apply_leave / approve_leave/reject_leave below — HRMS's
		# own Leave Application refuses to be submitted while status="Open").
		# Filtering to docstatus=1 only would make every such pending request
		# invisible here, leaving the Approve/Reject buttons with nothing to
		# ever act on. docstatus=2 (Cancelled) stays excluded.
		conditions = ["la.docstatus IN (0, 1)"]
		params = {}
		if leave_status:
			conditions.append("la.status = %(leave_status)s")
			params["leave_status"] = leave_status
		else:
			conditions.append("la.status IN ('Open','Approved','Rejected')")
		leave_cond, leave_extra = build_multi_token_where_named(["e.employee_name", "la.employee"], leave_search, "leave_tok")
		if leave_cond:
			conditions.append(leave_cond)
			params.update(leave_extra)
		leave_total = int(frappe.db.sql(f"""
			SELECT COUNT(*) FROM `tabLeave Application` la
			LEFT JOIN `tabEmployee` e ON e.name=la.employee
			WHERE {' AND '.join(conditions)}
		""", params)[0][0])
		leave_list = frappe.db.sql(f"""
			SELECT la.name, la.employee, e.employee_name,
				   la.leave_type, la.from_date, la.to_date,
				   la.total_leave_days, la.status, la.description as reason
			FROM `tabLeave Application` la
			LEFT JOIN `tabEmployee` e ON e.name=la.employee
			WHERE {' AND '.join(conditions)}
			ORDER BY la.from_date DESC
			LIMIT %(page_size)s OFFSET %(leave_offset)s
		""", {**params, "page_size": page_size, "leave_offset": leave_offset}, as_dict=True)
	except Exception:
		leave_list, leave_total = [], 0

	# ── Salary slips MTD ──────────────────────────────────────────────────────
	try:
		conditions = ["ss.docstatus < 2", "ss.start_date BETWEEN %(month_start)s AND %(month_end)s"]
		params = {"month_start": month_start, "month_end": month_end}
		if pay_status:
			conditions.append("ss.docstatus = %(pay_docstatus)s")
			params["pay_docstatus"] = 1 if pay_status == "Submitted" else 0
		pay_cond, pay_extra = build_multi_token_where_named(["e.employee_name", "ss.employee"], pay_search, "pay_tok")
		if pay_cond:
			conditions.append(pay_cond)
			params.update(pay_extra)
		pay_total = int(frappe.db.sql(f"""
			SELECT COUNT(*) FROM `tabSalary Slip` ss
			LEFT JOIN `tabEmployee` e ON e.name=ss.employee
			WHERE {' AND '.join(conditions)}
		""", params)[0][0])
		# Submitted/draft summary must reflect the full filtered set, not just
		# the current page — otherwise it flickers per-page once real
		# pagination replaces the old "cap at 100, sum in JS" approach.
		pay_summary_row = frappe.db.sql(f"""
			SELECT
				SUM(CASE WHEN ss.docstatus=1 THEN 1 ELSE 0 END) AS submitted_count,
				SUM(CASE WHEN ss.docstatus=0 THEN 1 ELSE 0 END) AS draft_count,
				COALESCE(SUM(CASE WHEN ss.docstatus=1 THEN ss.net_pay ELSE 0 END), 0) AS submitted_net_total
			FROM `tabSalary Slip` ss
			LEFT JOIN `tabEmployee` e ON e.name=ss.employee
			WHERE {' AND '.join(conditions)}
		""", params, as_dict=True)[0]
		pay_submitted_count = int(pay_summary_row.submitted_count or 0)
		pay_draft_count = int(pay_summary_row.draft_count or 0)
		pay_submitted_net_total = flt(pay_summary_row.submitted_net_total)
		salary_slips = frappe.db.sql(f"""
			SELECT ss.name, ss.employee, e.employee_name,
				   ss.gross_pay, ss.total_deduction, ss.net_pay, ss.start_date,
				   CASE ss.docstatus WHEN 1 THEN 'Submitted' ELSE 'Draft' END as slip_status
			FROM `tabSalary Slip` ss
			LEFT JOIN `tabEmployee` e ON e.name=ss.employee
			WHERE {' AND '.join(conditions)}
			ORDER BY ss.net_pay DESC
			LIMIT %(page_size)s OFFSET %(pay_offset)s
		""", {**params, "page_size": page_size, "pay_offset": pay_offset}, as_dict=True)
	except Exception:
		salary_slips, pay_total = [], 0
		pay_submitted_count = pay_draft_count = 0
		pay_submitted_net_total = 0

	return {
		"total_emp": int(total_emp),
		"present_today": int(present_today),
		"absent_today": int(absent_today),
		"pending_leaves": int(pending_leaves),
		"payroll_mtd": payroll_mtd,
		"payroll_draft_count": payroll_draft_count,
		"payroll_submitted_count": payroll_submitted_count,
		"payroll_is_draft": payroll_is_draft,
		"attendance": attendance_list,
		"attendance_total": attendance_total,
		"leaves": leave_list,
		"leave_total": leave_total,
		"salary_slips": salary_slips,
		"pay_total": pay_total,
		"pay_submitted_count": pay_submitted_count,
		"pay_draft_count": pay_draft_count,
		"pay_submitted_net_total": pay_submitted_net_total,
	}


@frappe.whitelist()
def get_payroll_audit(month=None):
	"""Per-employee payroll verification: slip vs actual attendance."""
	frappe.only_for(["HR Manager", "System Manager", "HR User"])
	today = getdate(nowdate())
	month_date = getdate(month) if month else today
	month_start = get_first_day(month_date)
	month_end = get_last_day(month_date)

	rows = frappe.db.sql("""
		SELECT
			ss.name        AS slip_name,
			ss.employee,
			e.employee_name,
			e.department,
			ss.salary_structure,
			ss.total_working_days,
			ss.payment_days,
			ss.absent_days   AS slip_absent,
			ss.leave_without_pay AS slip_lwp,
			ss.gross_pay,
			ss.net_pay,
			ss.docstatus,
			COALESCE(att.att_count, 0)    AS att_records,
			COALESCE(att.actual_present, 0) AS actual_present,
			COALESCE(att.actual_absent, 0)  AS actual_absent,
			COALESCE(att.actual_half, 0)    AS actual_half
		FROM `tabSalary Slip` ss
		JOIN `tabEmployee` e ON e.name = ss.employee
		LEFT JOIN (
			SELECT employee,
				COUNT(*)                                                   AS att_count,
				SUM(CASE WHEN status='Present' THEN 1 ELSE 0 END)         AS actual_present,
				SUM(CASE WHEN status='Absent'  THEN 1 ELSE 0 END)         AS actual_absent,
				SUM(CASE WHEN status='Half Day' THEN 0.5 ELSE 0 END)      AS actual_half
			FROM `tabAttendance`
			WHERE attendance_date BETWEEN %s AND %s AND docstatus = 1
			GROUP BY employee
		) att ON att.employee = ss.employee
		WHERE ss.docstatus < 2
		  AND ss.start_date = %s AND ss.end_date = %s
		ORDER BY e.department, e.employee_name
	""", (month_start, month_end, month_start, month_end), as_dict=True)

	result = []
	for r in rows:
		abs_slip = flt(r.slip_absent)
		abs_att  = flt(r.actual_absent) + flt(r.actual_half)
		net_pay  = flt(r.net_pay)
		is_factory = "Factory" in (r.department or "")
		att_count  = int(r.att_records or 0)

		if att_count == 0:
			status = "NO ATT DATA"
		elif net_pay <= 0 and flt(r.gross_pay) > 0:
			status = "ZERO NET PAY"
		elif abs(abs_slip - abs_att) > 1:
			status = "MISMATCH"
		else:
			status = "OK"

		result.append({
			"slip_name":       r.slip_name,
			"employee":        r.employee,
			"employee_name":   r.employee_name or "",
			"department":      r.department or "",
			"salary_structure":r.salary_structure or "",
			"emp_type":        "Factory" if is_factory else "Office",
			"working_days":    int(r.total_working_days or 0),
			"payment_days":    flt(r.payment_days),
			"slip_absent":     abs_slip,
			"att_records":     att_count,
			"actual_absent":   abs_att,
			"gross_pay":       flt(r.gross_pay),
			"net_pay":         net_pay,
			"slip_status":     "Submitted" if r.docstatus == 1 else "Draft",
			"status":          status,
		})

	ok   = sum(1 for r in result if r["status"] == "OK")
	issues = len(result) - ok
	return {"rows": result, "ok": ok, "issues": issues, "period": month_start.strftime("%B %Y")}


@frappe.whitelist()
def generate_single_slip(employee, month=None, notify=1):
	"""Create (or fetch) one employee's Salary Slip for the given month and
	bell-notify them. Used by the HR Dashboard's per-person payroll action."""
	frappe.only_for(["HR Manager", "HR User", "System Manager"])
	today = getdate(nowdate())
	month_date = getdate(month) if month else today
	month_start = get_first_day(month_date)
	month_end = get_last_day(month_date)

	if not frappe.db.exists("Salary Structure Assignment", {"employee": employee, "docstatus": 1}):
		frappe.throw(f"{employee} has no active Salary Structure Assignment — set a base salary first.")

	existing = frappe.db.get_value("Salary Slip", {"employee": employee, "start_date": month_start})
	if existing:
		return {"status": "exists", "slip": existing}

	doc = frappe.get_doc({
		"doctype": "Salary Slip",
		"employee": employee,
		"posting_date": today,
		"start_date": month_start,
		"end_date": month_end,
	})
	doc.insert(ignore_permissions=True)
	frappe.db.commit()

	if frappe.utils.cint(notify):
		user_id = frappe.db.get_value("Employee", employee, "user_id")
		if user_id:
			frappe.get_doc({
				"doctype": "Notification Log",
				"subject": f"Your salary slip for {month_start.strftime('%B %Y')} is ready",
				"email_content": f"Salary Slip {doc.name} has been generated — net pay {frappe.utils.fmt_money(doc.net_pay, precision=2)}.",
				"for_user": user_id,
				"from_user": frappe.session.user,
				"type": "Alert",
				"document_type": "Salary Slip",
				"document_name": doc.name,
			}).insert(ignore_permissions=True)
			frappe.db.commit()

	return {"status": "created", "slip": doc.name, "net_pay": doc.net_pay}


@frappe.whitelist()
def approve_leave(leave_id):
	frappe.only_for(["HR Manager", "System Manager"])
	doc = frappe.get_doc("Leave Application", leave_id)
	# HRMS's Leave Application only creates its Leave Ledger Entry (the actual
	# balance deduction) inside on_submit() — a raw frappe.db.set_value() on
	# `status` bypasses Document events entirely (see CLAUDE.md "Frappe /
	# ERPNext Gotchas"), so the previous version here could mark a leave
	# "Approved" while never touching the employee's real leave balance.
	# Confirmed live: this whole self-service apply→approve pipeline had never
	# processed a single leave end-to-end (see ib_my_hr.apply_leave fix,
	# same session) — every existing real Leave Application was created via
	# the native HRMS form instead, which sets status before submit.
	if doc.docstatus == 0:
		if doc.status != "Open":
			frappe.throw(f"Cannot approve leave in status '{doc.status}'")
		doc.status = "Approved"
		doc.submit()  # HRMS on_submit(): validates, creates Leave Ledger Entry, notifies employee
	elif doc.docstatus == 1:
		# Already submitted — HRMS's own doctype has no post-submit transition
		# for `status` (permlevel=1, no allow_on_submit), so there is nothing
		# safe to do here via the framework; a doc reaching this branch is
		# already in whatever state it was submitted with.
		if doc.status != "Approved":
			frappe.throw(
				f"Leave {leave_id} is already submitted with status '{doc.status}' — "
				"it cannot be re-approved. Cancel and re-create it if this is wrong."
			)
	else:
		frappe.throw(f"Cannot approve a cancelled leave application ({leave_id}).")
	frappe.db.commit()
	return {"status": "ok"}


@frappe.whitelist()
def reject_leave(leave_id):
	frappe.only_for(["HR Manager", "System Manager"])
	doc = frappe.get_doc("Leave Application", leave_id)
	if doc.docstatus == 0:
		if doc.status != "Open":
			frappe.throw(f"Cannot reject leave in status '{doc.status}'")
		doc.status = "Rejected"
		doc.submit()  # on_submit() allows Rejected; no ledger entry created for a rejection
	elif doc.docstatus == 1:
		if doc.status != "Rejected":
			frappe.throw(
				f"Leave {leave_id} is already submitted with status '{doc.status}' — "
				"it cannot be re-rejected."
			)
	else:
		frappe.throw(f"Cannot reject a cancelled leave application ({leave_id}).")
	frappe.db.commit()
	return {"status": "ok"}


# ─────────────────────────────────────────────────────────────────────────────
# Overview — the analytics half of the page. get_hrms_data() above stays the
# operational half (the attendance / leave / payroll lists with their own
# search + pagination); this adds the numbers a manager actually reads first.

HR_ROLES = ["HR Manager", "HR User", "Factory Management", "System Manager"]


def _scope(alias="e"):
	"""Department / branch filter shared by every query below."""

	def build(department=None, branch=None):
		cond, params = "", {}
		if department:
			cond += f" AND {alias}.department = %(department)s"
			params["department"] = department
		if branch:
			cond += f" AND {alias}.branch = %(branch)s"
			params["branch"] = branch
		return cond, params

	return build


@frappe.whitelist()
def get_hr_overview(month=None, department=None, branch=None):
	frappe.only_for(HR_ROLES)
	today = getdate(nowdate())
	month_date = getdate(month) if month else today
	month_start = get_first_day(month_date)
	month_end = get_last_day(month_date)
	# A month in the future has no history to report on; a past month is read
	# in full, the running month only up to today.
	period_end = min(month_end, today) if month_end > today else month_end
	prev_start = get_first_day(add_months(month_start, -1))
	prev_end = get_last_day(prev_start)

	emp_cond, emp_params = _scope("e")(department, branch)
	base = {"start": month_start, "end": month_end, "pend": period_end, "today": today}
	p = {**emp_params, **base}

	# ── Headcount ────────────────────────────────────────────────────────────
	headcount = int(
		frappe.db.sql(
			f"SELECT COUNT(*) FROM `tabEmployee` e WHERE e.status = 'Active' {emp_cond}", emp_params
		)[0][0]
	)
	joiners = int(
		frappe.db.sql(
			f"""SELECT COUNT(*) FROM `tabEmployee` e
			WHERE e.date_of_joining BETWEEN %(start)s AND %(end)s {emp_cond}""",
			p,
		)[0][0]
	)
	exits = int(
		frappe.db.sql(
			f"""SELECT COUNT(*) FROM `tabEmployee` e
			WHERE e.relieving_date BETWEEN %(start)s AND %(end)s {emp_cond}""",
			p,
		)[0][0]
	)
	exits_year = int(
		frappe.db.sql(
			f"""SELECT COUNT(*) FROM `tabEmployee` e
			WHERE e.relieving_date >= DATE_SUB(%(today)s, INTERVAL 12 MONTH) {emp_cond}""",
			p,
		)[0][0]
	)
	attrition = round(exits_year / headcount * 100, 1) if headcount else 0

	# ── Today ────────────────────────────────────────────────────────────────
	checkin_today = frappe.db.sql(
		f"""SELECT DISTINCT ec.employee FROM `tabEmployee Checkin` ec
		INNER JOIN `tabEmployee` e ON e.name = ec.employee
		WHERE DATE(ec.time) = %(today)s AND ec.log_type = 'IN' {emp_cond}""",
		p,
	)
	att_today = frappe.db.sql(
		f"""SELECT DISTINCT a.employee FROM `tabAttendance` a
		INNER JOIN `tabEmployee` e ON e.name = a.employee
		WHERE a.attendance_date = %(today)s AND a.status IN ('Present','Work From Home','Half Day')
		AND a.docstatus = 1 {emp_cond}""",
		p,
	)
	present_today = len({r[0] for r in checkin_today} | {r[0] for r in att_today})
	on_leave_today = int(
		frappe.db.sql(
			f"""SELECT COUNT(DISTINCT la.employee) FROM `tabLeave Application` la
			INNER JOIN `tabEmployee` e ON e.name = la.employee
			WHERE %(today)s BETWEEN la.from_date AND la.to_date
			AND la.status = 'Approved' AND la.docstatus = 1 {emp_cond}""",
			p,
		)[0][0]
	)
	absent_today = max(0, headcount - present_today - on_leave_today)

	# ── Attendance for the month ─────────────────────────────────────────────
	mix = frappe.db.sql(
		f"""SELECT a.status, COUNT(*) c FROM `tabAttendance` a
		INNER JOIN `tabEmployee` e ON e.name = a.employee
		WHERE a.docstatus = 1 AND a.attendance_date BETWEEN %(start)s AND %(pend)s {emp_cond}
		GROUP BY a.status""",
		p,
		as_dict=True,
	)
	marked = sum(r.c for r in mix) or 0
	present_days = sum(r.c for r in mix if r.status in ("Present", "Work From Home"))
	half_days = sum(r.c for r in mix if r.status == "Half Day")
	att_rate = round((present_days + half_days * 0.5) / marked * 100, 1) if marked else 0

	prev_mix = frappe.db.sql(
		f"""SELECT a.status, COUNT(*) c FROM `tabAttendance` a
		INNER JOIN `tabEmployee` e ON e.name = a.employee
		WHERE a.docstatus = 1 AND a.attendance_date BETWEEN %(ps)s AND %(pe)s {emp_cond}
		GROUP BY a.status""",
		{**p, "ps": prev_start, "pe": prev_end},
		as_dict=True,
	)
	prev_marked = sum(r.c for r in prev_mix) or 0
	prev_present = sum(r.c for r in prev_mix if r.status in ("Present", "Work From Home"))
	prev_half = sum(r.c for r in prev_mix if r.status == "Half Day")
	prev_rate = round((prev_present + prev_half * 0.5) / prev_marked * 100, 1) if prev_marked else 0
	att_delta = round(att_rate - prev_rate, 1) if prev_marked else None

	late_count = int(
		frappe.db.sql(
			f"""SELECT COUNT(*) FROM `tabAttendance` a
			INNER JOIN `tabEmployee` e ON e.name = a.employee
			WHERE a.docstatus = 1 AND a.late_entry = 1
			AND a.attendance_date BETWEEN %(start)s AND %(pend)s {emp_cond}""",
			p,
		)[0][0]
	)

	att_trend = frappe.db.sql(
		f"""SELECT DATE_FORMAT(a.attendance_date, '%%d %%b') label, a.attendance_date d,
			SUM(a.status IN ('Present','Work From Home')) present,
			SUM(a.status = 'Absent') absent,
			SUM(a.status = 'On Leave') leave_
		FROM `tabAttendance` a
		INNER JOIN `tabEmployee` e ON e.name = a.employee
		WHERE a.docstatus = 1 AND a.attendance_date BETWEEN %(start)s AND %(pend)s {emp_cond}
		GROUP BY a.attendance_date, label ORDER BY a.attendance_date""",
		p,
		as_dict=True,
	)

	absentees = frappe.db.sql(
		f"""SELECT a.employee, e.employee_name, e.department, COUNT(*) days
		FROM `tabAttendance` a
		INNER JOIN `tabEmployee` e ON e.name = a.employee
		WHERE a.docstatus = 1 AND a.status = 'Absent'
		AND a.attendance_date BETWEEN %(start)s AND %(pend)s {emp_cond}
		GROUP BY a.employee, e.employee_name, e.department
		ORDER BY days DESC LIMIT 8""",
		p,
		as_dict=True,
	)

	# ── People mix ───────────────────────────────────────────────────────────
	by_department = frappe.db.sql(
		f"""SELECT COALESCE(NULLIF(e.department, ''), 'Unassigned') label, COUNT(*) c
		FROM `tabEmployee` e WHERE e.status = 'Active' {emp_cond}
		GROUP BY label ORDER BY c DESC""",
		emp_params,
		as_dict=True,
	)
	by_designation = frappe.db.sql(
		f"""SELECT COALESCE(NULLIF(e.designation, ''), 'Unassigned') label, COUNT(*) c
		FROM `tabEmployee` e WHERE e.status = 'Active' {emp_cond}
		GROUP BY label ORDER BY c DESC LIMIT 10""",
		emp_params,
		as_dict=True,
	)
	tenure = frappe.db.sql(
		f"""SELECT CASE
				WHEN e.date_of_joining IS NULL THEN 'Unknown'
				WHEN e.date_of_joining > DATE_SUB(%(today)s, INTERVAL 1 YEAR) THEN 'Under 1 yr'
				WHEN e.date_of_joining > DATE_SUB(%(today)s, INTERVAL 3 YEAR) THEN '1 - 3 yrs'
				WHEN e.date_of_joining > DATE_SUB(%(today)s, INTERVAL 5 YEAR) THEN '3 - 5 yrs'
				ELSE 'Over 5 yrs' END label, COUNT(*) c
		FROM `tabEmployee` e WHERE e.status = 'Active' {emp_cond}
		GROUP BY label""",
		p,
		as_dict=True,
	)

	# ── Leave ────────────────────────────────────────────────────────────────
	leave_by_type = frappe.db.sql(
		f"""SELECT la.leave_type label, COALESCE(SUM(la.total_leave_days), 0) days
		FROM `tabLeave Application` la
		INNER JOIN `tabEmployee` e ON e.name = la.employee
		WHERE la.docstatus = 1 AND la.status = 'Approved'
		AND la.from_date <= %(end)s AND la.to_date >= %(start)s {emp_cond}
		GROUP BY la.leave_type ORDER BY days DESC""",
		p,
		as_dict=True,
	)
	pending_leaves = int(
		frappe.db.sql(
			f"""SELECT COUNT(*) FROM `tabLeave Application` la
			INNER JOIN `tabEmployee` e ON e.name = la.employee
			WHERE la.status = 'Open' AND la.docstatus = 0 {emp_cond}""",
			emp_params,
		)[0][0]
	)
	upcoming_leave = frappe.db.sql(
		f"""SELECT la.name, la.employee, e.employee_name, la.leave_type, la.from_date, la.to_date,
			la.total_leave_days
		FROM `tabLeave Application` la
		INNER JOIN `tabEmployee` e ON e.name = la.employee
		WHERE la.docstatus = 1 AND la.status = 'Approved'
		AND la.to_date >= %(today)s AND la.from_date <= DATE_ADD(%(today)s, INTERVAL 14 DAY) {emp_cond}
		ORDER BY la.from_date LIMIT 8""",
		p,
		as_dict=True,
	)

	# ── Overtime (the doctype may hold nothing yet — 0 is a real answer) ──────
	ot = frappe.db.sql(
		f"""SELECT COALESCE(SUM(o.overtime_hours), 0) hrs,
			SUM(o.status = 'Pending Approval') pending
		FROM `tabIB Overtime Request` o
		INNER JOIN `tabEmployee` e ON e.name = o.employee
		WHERE o.date BETWEEN %(start)s AND %(end)s {emp_cond}""",
		p,
		as_dict=True,
	)[0]

	# ── Payroll ──────────────────────────────────────────────────────────────
	pay = frappe.db.sql(
		f"""SELECT
			COALESCE(SUM(CASE WHEN ss.docstatus = 1 THEN ss.net_pay ELSE 0 END), 0) net,
			COALESCE(SUM(CASE WHEN ss.docstatus = 0 THEN ss.net_pay ELSE 0 END), 0) draft_net,
			SUM(ss.docstatus = 0) draft_count, SUM(ss.docstatus = 1) submitted_count
		FROM `tabSalary Slip` ss
		INNER JOIN `tabEmployee` e ON e.name = ss.employee
		WHERE ss.docstatus < 2 AND ss.start_date BETWEEN %(start)s AND %(end)s {emp_cond}""",
		p,
		as_dict=True,
	)[0]
	pay_trend = frappe.db.sql(
		f"""SELECT DATE_FORMAT(ss.start_date, '%%b %%y') label, DATE_FORMAT(ss.start_date, '%%Y-%%m') bk,
			COALESCE(SUM(ss.net_pay), 0) net, COALESCE(SUM(ss.gross_pay), 0) gross
		FROM `tabSalary Slip` ss
		INNER JOIN `tabEmployee` e ON e.name = ss.employee
		WHERE ss.docstatus < 2 AND ss.start_date >= DATE_SUB(%(start)s, INTERVAL 6 MONTH)
		AND ss.start_date <= %(end)s {emp_cond}
		GROUP BY bk, label ORDER BY bk""",
		p,
		as_dict=True,
	)
	pay_by_dept = frappe.db.sql(
		f"""SELECT COALESCE(NULLIF(e.department, ''), 'Unassigned') label,
			COALESCE(SUM(ss.net_pay), 0) net
		FROM `tabSalary Slip` ss
		INNER JOIN `tabEmployee` e ON e.name = ss.employee
		WHERE ss.docstatus < 2 AND ss.start_date BETWEEN %(start)s AND %(end)s {emp_cond}
		GROUP BY label ORDER BY net DESC LIMIT 10""",
		p,
		as_dict=True,
	)

	# ── People moments — birthdays and work anniversaries, next 30 days ──────
	moments = frappe.db.sql(
		f"""SELECT e.name, e.employee_name, e.department, e.image, 'Birthday' kind,
			e.date_of_birth d,
			(DAYOFYEAR(e.date_of_birth) - DAYOFYEAR(%(today)s) + 366) %% 366 in_days
		FROM `tabEmployee` e
		WHERE e.status = 'Active' AND e.date_of_birth IS NOT NULL {emp_cond}
		HAVING in_days <= 30
		UNION ALL
		SELECT e.name, e.employee_name, e.department, e.image, 'Work anniversary' kind,
			e.date_of_joining d,
			(DAYOFYEAR(e.date_of_joining) - DAYOFYEAR(%(today)s) + 366) %% 366 in_days
		FROM `tabEmployee` e
		WHERE e.status = 'Active' AND e.date_of_joining IS NOT NULL
		AND e.date_of_joining < DATE_SUB(%(today)s, INTERVAL 1 YEAR) {emp_cond}
		HAVING in_days <= 30
		ORDER BY in_days LIMIT 10""",
		p,
		as_dict=True,
	)

	pending_ffs = int(
		frappe.db.sql(
			"""SELECT COUNT(*) FROM `tabIB Full Final Settlement`
			WHERE docstatus < 2 AND status IN ('Draft','In Review','Approved')"""
		)[0][0]
	)

	return {
		"meta": {
			"month": str(month_start),
			"month_label": month_start.strftime("%B %Y"),
			"period_end": str(period_end),
			"department": department or "",
			"branch": branch or "",
		},
		"headcount": headcount,
		"joiners": joiners,
		"exits": exits,
		"attrition": attrition,
		"present_today": present_today,
		"on_leave_today": on_leave_today,
		"absent_today": absent_today,
		"att_rate": att_rate,
		"att_delta": att_delta,
		"att_marked": marked,
		"late_count": late_count,
		"att_trend": att_trend,
		"att_mix": mix,
		"absentees": absentees,
		"by_department": by_department,
		"by_designation": by_designation,
		"tenure": tenure,
		"leave_by_type": leave_by_type,
		"pending_leaves": pending_leaves,
		"upcoming_leave": upcoming_leave,
		"ot_hours": flt(ot.hrs),
		"ot_pending": int(ot.pending or 0),
		"payroll_net": flt(pay.net) or flt(pay.draft_net),
		"payroll_is_draft": not flt(pay.net) and flt(pay.draft_net) > 0,
		"payroll_draft_count": int(pay.draft_count or 0),
		"payroll_submitted_count": int(pay.submitted_count or 0),
		"pay_trend": pay_trend,
		"pay_by_dept": pay_by_dept,
		"moments": moments,
		"pending_ffs": pending_ffs,
	}


@frappe.whitelist()
def get_hr_months(count=12):
	"""Month options for the dashboard picker — newest first."""
	frappe.only_for(HR_ROLES)
	first = get_first_day(getdate(nowdate()))
	out = []
	for i in range(int(count)):
		d = get_first_day(add_months(first, -i))
		out.append({"value": str(d), "label": d.strftime("%b %Y")})
	return out
