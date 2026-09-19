"""IB Budget vs Actual — each budgeted expense head: this month and year to date,
budget against actual spend and % used (ERPNext Budget, cost-center based)."""
import frappe
from frappe import _

from instabiz.overrides.budget_watch import budget_rows


def execute(filters=None):
	f = frappe._dict(filters or {})
	rows = budget_rows(f.date, f.fiscal_year, f.company)
	for r in rows:
		r.head = r.account.rsplit(" - ", 1)[0]
		r.month_left = r.month_budget - r.month_actual
		r.ytd_left = r.ytd_budget - r.ytd_actual
	rows.sort(key=lambda r: -r.month_pct)

	def cur(label, fieldname, width=120):
		return {"label": label, "fieldname": fieldname, "fieldtype": "Currency", "width": width}

	cols = [
		{"label": _("Expense Head"), "fieldname": "account", "fieldtype": "Link", "options": "Account", "width": 220},
		{"label": _("Cost Center"), "fieldname": "cost_center", "fieldtype": "Link", "options": "Cost Center", "width": 150},
		cur(_("Month Budget"), "month_budget"), cur(_("Month Actual"), "month_actual"), cur(_("Month Left"), "month_left"),
		{"label": _("Month %"), "fieldname": "month_pct", "fieldtype": "Percent", "width": 85},
		cur(_("YTD Budget"), "ytd_budget"), cur(_("YTD Actual"), "ytd_actual"), cur(_("YTD Left"), "ytd_left"),
		{"label": _("YTD %"), "fieldname": "ytd_pct", "fieldtype": "Percent", "width": 80},
		cur(_("Annual Budget"), "budget_amount", 130),
	]
	over = [r for r in rows if r.month_pct >= 100]
	summary = [
		{"label": _("Heads budgeted"), "value": len(rows), "datatype": "Int"},
		{"label": _("Spent this month"), "value": sum(r.month_actual for r in rows), "datatype": "Currency"},
		{"label": _("Month budget"), "value": sum(r.month_budget for r in rows), "datatype": "Currency"},
		{"label": _("Over budget"), "value": len(over), "datatype": "Int", "indicator": "red" if over else "green"},
	]
	chart = {"data": {"labels": [r.head for r in rows[:12]], "datasets": [
		{"name": _("Budget"), "values": [round(r.month_budget) for r in rows[:12]]},
		{"name": _("Actual"), "values": [round(r.month_actual) for r in rows[:12]]}]},
		"type": "bar", "fieldtype": "Currency", "colors": ["#c9ccd1", "#d97757"]} if rows else None
	msg = None if rows else _(
		"No budgets yet. Press New Budget: Budget Against = Cost Center, pick the expense accounts and the yearly amount.")
	return cols, rows, msg, chart, summary
