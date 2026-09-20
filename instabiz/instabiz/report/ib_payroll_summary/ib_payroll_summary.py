import frappe
from frappe.utils import flt, add_months, get_first_day, get_last_day

_IB_LEAVE_CREDIT = 2


def execute(filters=None):
    filters = filters or {}
    columns = _columns()
    data = _data(filters)
    return columns, data


def _columns():
    return [
        {"fieldname": "employee", "label": "Employee ID", "fieldtype": "Link", "options": "Employee", "width": 120},
        {"fieldname": "employee_name", "label": "Name", "fieldtype": "Data", "width": 160},
        {"fieldname": "designation", "label": "Designation", "fieldtype": "Data", "width": 140},
        {"fieldname": "department", "label": "Department", "fieldtype": "Data", "width": 120},
        {"fieldname": "salary_structure", "label": "Structure", "fieldtype": "Link", "options": "Salary Structure", "width": 110},
        {"fieldname": "absent_credit", "label": "Absent / Credit", "fieldtype": "Data", "width": 110},
        {"fieldname": "base", "label": "CTC/mo", "fieldtype": "Currency", "width": 100},
        {"fieldname": "basic", "label": "Basic", "fieldtype": "Currency", "width": 90},
        {"fieldname": "hra", "label": "HRA", "fieldtype": "Currency", "width": 80},
        {"fieldname": "ca", "label": "CA", "fieldtype": "Currency", "width": 80},
        {"fieldname": "gross", "label": "Gross", "fieldtype": "Currency", "width": 90},
        {"fieldname": "pf", "label": "PF", "fieldtype": "Currency", "width": 80},
        {"fieldname": "esic", "label": "ESIC", "fieldtype": "Currency", "width": 75},
        {"fieldname": "pt", "label": "PT", "fieldtype": "Currency", "width": 70},
        {"fieldname": "total_deductions", "label": "Deductions", "fieldtype": "Currency", "width": 100},
        {"fieldname": "net_pay", "label": "Net Pay", "fieldtype": "Currency", "width": 100},
    ]


def _calc(base, structure, pf_opt_in=True, esic_opt_in=True):
    ctx = {"base": base}

    if structure == "IB Payroll":
        B = round(base * 2 / 3)
        HRA = round(base * 0.2)
        CA = base - B - HRA
        ctx.update({"B": B, "HRA": HRA, "CA": CA})

        PF = round((min(B + CA, 15000)) * 0.12) if pf_opt_in else 0
        ESIC = round((B + HRA) * 0.0075) if (esic_opt_in and base <= 21000) else 0
        # Real bug, fixed: this claimed to mirror the real "Professional Tax"
        # Salary Component but didn't — the live component (checked directly,
        # `Salary Component.formula`/`.condition`) is a flat 200 whenever
        # `base >= 7500`, with NO gender split and NO 175/200 tiering. The
        # old tiered/gendered version here understated PT for every female
        # employee earning >=7500 (showed 0, real deduction is 200) and for
        # every employee in the 7500-10000 band (showed 175, real is 200).
        PT = 200 if base >= 7500 else 0

    elif structure == "Astro Payroll":
        if base > 21000:
            B = round(base * 2 / 3)
            HRA = round(base / 6)
        elif base > 11000:
            B = round(base * 10 / 13)
            HRA = round(base * 1.5 / 13)
        else:
            B = round(base * 10 / 11)
            HRA = round(B * 0.05)
        CA = base - B - HRA
        ctx.update({"B": B, "HRA": HRA, "CA": CA})

        PF = round((min(B + HRA, 15000)) * 0.12) if pf_opt_in else 0
        ESIC = round((B + HRA) * 0.0075) if (esic_opt_in and base <= 21000) else 0
        # Real bug, fixed — see IB Payroll's own PT comment above for the
        # full story: the live "Professional Tax" component is shared across
        # both structures, flat 200 when base >= 7500, no gender check.
        PT = 200 if base >= 7500 else 0

    else:
        return None

    gross = B + HRA + CA
    total_deductions = PF + ESIC + PT
    net_pay = gross - total_deductions

    return {
        "basic": B, "hra": HRA, "ca": CA,
        "gross": gross,
        "pf": PF, "esic": ESIC, "pt": PT,
        "total_deductions": total_deductions,
        "net_pay": net_pay,
    }


def _slip_absent_map(payroll_month):
    """Returns {employee: total_absent_days} for the given month.
    Prefers existing salary slips (draft or submitted — a draft slip's
    absent_days/leave_without_pay were already computed by HRMS at generation
    time and are the authoritative figure for that month, not a placeholder);
    falls back to a cruder raw-Attendance recount only when no slip exists yet.
    Previously only docstatus=1 (submitted) was accepted — with payroll not
    yet submitted this cycle, that silently fell through to the Attendance
    fallback for every employee, which doesn't replicate HRMS's own
    leave-vs-absence handling and produced a systematically higher gross than
    the real (draft) slips — confirmed live: every one of 52 employees showed
    a higher Payroll Summary gross than their actual Salary Slip, ~₹2.5L
    aggregate gap, matching the reported Payroll Summary vs HR Dashboard
    mismatch."""
    month_start = get_first_day(payroll_month)
    month_end = get_last_day(payroll_month)

    slips = frappe.db.sql(
        """
        SELECT employee,
               COALESCE(absent_days, 0) + COALESCE(leave_without_pay, 0) AS total_absent
        FROM `tabSalary Slip`
        WHERE docstatus < 2
          AND start_date >= %(month_start)s
          AND start_date <= %(month_end)s
        """,
        {"month_start": month_start, "month_end": month_end},
        as_dict=True,
    )
    if slips:
        return {s.employee: flt(s.total_absent) for s in slips}

    # Fall back to Attendance records for the month
    rows = frappe.db.sql(
        """
        SELECT employee,
               SUM(CASE WHEN status = 'Absent' THEN 1
                        WHEN status = 'Half Day' THEN 0.5
                        ELSE 0 END) AS total_absent
        FROM `tabAttendance`
        WHERE docstatus = 1
          AND attendance_date >= %(month_start)s
          AND attendance_date <= %(month_end)s
          AND status IN ('Absent', 'Half Day')
        GROUP BY employee
        """,
        {"month_start": month_start, "month_end": month_end},
        as_dict=True,
    )
    return {r.employee: flt(r.total_absent) for r in rows}


def _slip_ratio_map(payroll_month):
    """Returns {employee: payment_days/total_working_days} straight from an
    existing (draft or submitted) Salary Slip for the month — this is HRMS's
    own already-computed proration ratio, which accounts for holiday lists,
    weekly offs, and leave-balance handling that this report's manual
    absent-days-minus-leave-credit approximation (below) doesn't fully
    replicate. Preferred over the manual estimate whenever a real slip
    already exists; the manual estimate remains the fallback for employees
    with no slip yet (a forward-looking preview)."""
    month_start = get_first_day(payroll_month)
    month_end = get_last_day(payroll_month)
    rows = frappe.db.sql(
        """
        SELECT employee, payment_days, total_working_days
        FROM `tabSalary Slip`
        WHERE docstatus < 2
          AND start_date >= %(month_start)s
          AND start_date <= %(month_end)s
          AND total_working_days > 0
        """,
        {"month_start": month_start, "month_end": month_end},
        as_dict=True,
    )
    return {r.employee: flt(r.payment_days) / flt(r.total_working_days) for r in rows}


def _absent_credit_label(total_absent, salary_structure):
    if total_absent == 0:
        return "-"
    if salary_structure == "IB Payroll":
        return f"{int(total_absent)} / {_IB_LEAVE_CREDIT}"
    return str(int(total_absent))


def _data(filters):
    # include both draft (0) and submitted (1) Salary Structure Assignments
    conditions = "AND ssa.docstatus IN (0, 1)"
    emp_cat = filters.get("emp_category") or "All"
    if emp_cat == "Factory":
        conditions += " AND e.department LIKE '%%Factory%%'"
    elif emp_cat == "Office":
        conditions += " AND e.department NOT LIKE '%%Factory%%'"
    # Apply salary_structure filter only when Employee Type is All
    if emp_cat == "All" and filters.get("salary_structure"):
        conditions += " AND ssa.salary_structure = %(salary_structure)s"

    rows = frappe.db.sql(f"""
        SELECT
            ssa.employee, ssa.employee_name, ssa.salary_structure, ssa.base,
            e.designation, e.department,
            e.provident_fund_account, e.health_insurance_no,
            ROW_NUMBER() OVER (PARTITION BY ssa.employee ORDER BY ssa.from_date DESC) AS rn
        FROM `tabSalary Structure Assignment` ssa
        JOIN `tabEmployee` e ON e.name = ssa.employee
        WHERE e.status = 'Active'
        {conditions}
    """, filters, as_dict=True)

    slip_map = _slip_absent_map(filters["payroll_month"]) if filters.get("payroll_month") else {}
    ratio_map = _slip_ratio_map(filters["payroll_month"]) if filters.get("payroll_month") else {}

    # Keep only latest assignment per employee
    seen = set()
    data = []
    for r in rows:
        if r.rn != 1 or r.employee in seen:
            continue
        seen.add(r.employee)

        calc = _calc(
            flt(r.base), r.salary_structure,
            pf_opt_in=bool(r.provident_fund_account),
            esic_opt_in=bool(r.health_insurance_no),
        )
        if not calc:
            continue

        total_absent = slip_map.get(r.employee, 0)

        # Prorate amounts based on present days when payroll_month provided
        if filters.get("payroll_month"):
            if r.employee in ratio_map:
                # Real slip already exists — use HRMS's own computed ratio
                # rather than re-deriving one, so this report always agrees
                # with the actual slip once one has been generated.
                ratio = ratio_map[r.employee]
            else:
                month_start = get_first_day(filters["payroll_month"])
                month_end = get_last_day(filters["payroll_month"])
                days_in_month = (month_end - month_start).days + 1
                # Apply IB leave credit where applicable
                effective_absent = total_absent
                if r.salary_structure == "IB Payroll":
                    effective_absent = max(0, total_absent - _IB_LEAVE_CREDIT)
                present_days = max(0, days_in_month - effective_absent)
                ratio = (present_days / days_in_month) if days_in_month else 1

            # prorate base + calculated components
            base_pr = flt(round(flt(r.base) * ratio, 2))
            prorated = {k: flt(round(v * ratio, 2)) for k, v in calc.items()}
        else:
            base_pr = flt(r.base)
            prorated = {k: flt(v) for k, v in calc.items()}

        data.append({
            "employee": r.employee,
            "employee_name": r.employee_name,
            "designation": r.designation,
            "department": r.department,
            "salary_structure": r.salary_structure,
            "absent_credit": _absent_credit_label(total_absent, r.salary_structure),
            "base": base_pr,
            **prorated,
        })

    data.sort(key=lambda x: (x.get("department") or "", x["employee_name"]))
    return data
