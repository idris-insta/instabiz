"""IB Statutory Returns — PF ECR and ESIC monthly contribution from submitted salary slips.

PF: EPF wages are worked back from the PF deducted (12 %); EPS wages are
capped at ₹15,000; EPS = 8.33 % of EPS wages, EPF–EPS difference = 12 % of EPF
wages − EPS; NCP days = working days − payment days. UAN is the employee's
Provident Fund account field. ESIC: wages worked back from the ESIC deducted
(0.75 %); employer share 3.25 %; IP number is the health insurance no.
"Download" writes the ECR text file (#~# separated) or the ESIC upload sheet.
"""
import frappe
from frappe import _
from frappe.utils import flt, get_first_day, get_last_day, getdate


def _component(kind):
	comps = frappe.get_all("Salary Component", filters={"type": "Deduction"}, fields=["name", "salary_component_abbr"])
	for c in comps:
		n, a = c.name.lower(), (c.salary_component_abbr or "").upper()
		if kind == "PF" and (a == "PF" or "provident" in n):
			return c.name
		if kind == "ESIC" and (a in ("ESI", "ESIC") or "esi" in n or "state insurance" in n):
			return c.name
	return None


def _slips(month):
	start, end = get_first_day(getdate(month)), get_last_day(getdate(month))
	return frappe.db.sql("""SELECT ss.name, ss.employee, ss.employee_name, ss.gross_pay, ss.payment_days,
		ss.total_working_days, e.provident_fund_account AS uan, e.health_insurance_no AS ip
		FROM `tabSalary Slip` ss JOIN `tabEmployee` e ON e.name = ss.employee
		WHERE ss.docstatus = 1 AND ss.start_date >= %s AND ss.end_date <= %s ORDER BY ss.employee_name""", (start, end), as_dict=True)


def _deduction(slip, component):
	if not component:
		return 0
	return flt(frappe.db.get_value("Salary Detail", {"parent": slip, "parentfield": "deductions", "salary_component": component}, "amount"))


def execute(filters=None):
	f = frappe._dict(filters or {})
	month = f.month or frappe.utils.today()
	kind = f.return_type or "PF ECR"
	rows = []
	if kind == "PF ECR":
		comp = _component("PF")
		for s in _slips(month):
			pf = _deduction(s.name, comp)
			if pf <= 0:
				continue
			epf_wages = round(pf / 0.12)
			eps_wages = min(epf_wages, 15000)
			eps = round(eps_wages * 0.0833)
			rows.append(frappe._dict(employee=s.employee, name=s.employee_name, uan=s.uan, gross=round(flt(s.gross_pay)),
				epf_wages=epf_wages, eps_wages=eps_wages, edli_wages=eps_wages, epf_ee=round(pf), eps=eps,
				diff=round(epf_wages * 0.12) - eps, ncp=max(round(flt(s.total_working_days) - flt(s.payment_days)), 0),
				missing=_("UAN missing") if not s.uan else ""))
		cols = [
			{"label": _("Employee"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 120},
			{"label": _("Name"), "fieldname": "name", "fieldtype": "Data", "width": 180},
			{"label": _("UAN"), "fieldname": "uan", "fieldtype": "Data", "width": 120},
			{"label": _("Gross Wages"), "fieldname": "gross", "fieldtype": "Currency", "width": 110},
			{"label": _("EPF Wages"), "fieldname": "epf_wages", "fieldtype": "Currency", "width": 110},
			{"label": _("EPS Wages"), "fieldname": "eps_wages", "fieldtype": "Currency", "width": 110},
			{"label": _("EDLI Wages"), "fieldname": "edli_wages", "fieldtype": "Currency", "width": 110},
			{"label": _("EPF (Employee 12%)"), "fieldname": "epf_ee", "fieldtype": "Currency", "width": 120},
			{"label": _("EPS (8.33%)"), "fieldname": "eps", "fieldtype": "Currency", "width": 110},
			{"label": _("EPF-EPS (3.67%)"), "fieldname": "diff", "fieldtype": "Currency", "width": 120},
			{"label": _("NCP Days"), "fieldname": "ncp", "fieldtype": "Int", "width": 80},
			{"label": _("Check"), "fieldname": "missing", "fieldtype": "Data", "width": 110},
		]
		summary = [{"label": _("Members"), "value": len(rows), "datatype": "Int"},
			{"label": _("Employee share"), "value": sum(r.epf_ee for r in rows), "datatype": "Currency"},
			{"label": _("Employer share (EPS + diff)"), "value": sum(r.eps + r.diff for r in rows), "datatype": "Currency"},
			{"label": _("Admin + EDLI (≈1%)"), "value": round(sum(r.epf_wages for r in rows) * 0.005) + round(sum(r.edli_wages for r in rows) * 0.005),
				"datatype": "Currency"}]
		msg = None if comp else _("No Provident Fund deduction component found.")
	else:
		comp = _component("ESIC")
		for s in _slips(month):
			esi = _deduction(s.name, comp)
			if esi <= 0:
				continue
			wages = round(esi / 0.0075)
			rows.append(frappe._dict(employee=s.employee, name=s.employee_name, ip=s.ip, days=round(flt(s.payment_days)),
				wages=wages, ee=round(esi), er=round(wages * 0.0325), missing=_("IP number missing") if not s.ip else ""))
		cols = [
			{"label": _("Employee"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 120},
			{"label": _("Name"), "fieldname": "name", "fieldtype": "Data", "width": 180},
			{"label": _("IP Number"), "fieldname": "ip", "fieldtype": "Data", "width": 130},
			{"label": _("Days Paid"), "fieldname": "days", "fieldtype": "Int", "width": 80},
			{"label": _("ESIC Wages"), "fieldname": "wages", "fieldtype": "Currency", "width": 120},
			{"label": _("Employee 0.75%"), "fieldname": "ee", "fieldtype": "Currency", "width": 120},
			{"label": _("Employer 3.25%"), "fieldname": "er", "fieldtype": "Currency", "width": 120},
			{"label": _("Check"), "fieldname": "missing", "fieldtype": "Data", "width": 130},
		]
		summary = [{"label": _("Insured persons"), "value": len(rows), "datatype": "Int"},
			{"label": _("Employee share"), "value": sum(r.ee for r in rows), "datatype": "Currency"},
			{"label": _("Employer share"), "value": sum(r.er for r in rows), "datatype": "Currency"}]
		msg = None if comp else _("No ESIC deduction component found.")
	return cols, rows, msg, None, summary
