"""instabiz.overrides.budget_watch

Expense budgets per head on top of ERPNext's own Budget (cost center × account,
annual amount, optional monthly distribution). budget_rows() gives, for every
budgeted account: the budget and the actual spend for the month and the year
to date. The daily run warns Accounts Managers once per month when a head
crosses 90 % and again at 100 % of its monthly budget. Blocking or warning at
entry time is ERPNext's own Budget setting (Action if budget exceeded).
"""
import frappe
from frappe import _
from frappe.utils import add_months, flt, get_first_day, get_last_day, getdate, today

LEVELS = (90, 100)


def _budget_to(b, on):
	from erpnext.accounts.doctype.budget.budget import get_accumulated_monthly_budget

	return flt(get_accumulated_monthly_budget(b.monthly_distribution, on, b.fiscal_year, flt(b.budget_amount)))


def _actual(company, account, cost_center, start, end):
	lft, rgt = frappe.db.get_value("Cost Center", cost_center, ["lft", "rgt"]) or (0, 0)
	return flt(frappe.db.sql(
		"""SELECT SUM(gle.debit - gle.credit) FROM `tabGL Entry` gle
		JOIN `tabCost Center` cc ON cc.name = gle.cost_center
		WHERE gle.company = %s AND gle.account = %s AND gle.is_cancelled = 0
		  AND cc.lft >= %s AND cc.rgt <= %s AND gle.posting_date BETWEEN %s AND %s""",
		(company, account, lft, rgt, start, end))[0][0])


def budget_rows(on=None, fiscal_year=None, company=None):
	on = getdate(on or today())
	if not fiscal_year:
		from erpnext.accounts.utils import get_fiscal_year
		fiscal_year = get_fiscal_year(on, company=company)[0]
	fy_start = getdate(frappe.db.get_value("Fiscal Year", fiscal_year, "year_start_date"))
	filters = {"docstatus": 1, "fiscal_year": fiscal_year, "budget_against": "Cost Center"}
	if company:
		filters["company"] = company
	out = []
	m_start, m_end = get_first_day(on), get_last_day(on)
	for b in frappe.get_all("Budget", filters=filters, fields=["name", "company", "cost_center", "fiscal_year", "monthly_distribution"]):
		for acc in frappe.get_all("Budget Account", filters={"parent": b.name}, fields=["account", "budget_amount"]):
			row = frappe._dict(b)
			row.update(acc)
			row.ytd_budget = _budget_to(row, m_end)
			row.month_budget = row.ytd_budget - (_budget_to(row, add_months(m_end, -1)) if m_start > fy_start else 0)
			row.month_actual = _actual(b.company, acc.account, b.cost_center, m_start, m_end)
			row.ytd_actual = _actual(b.company, acc.account, b.cost_center, fy_start, m_end)
			row.month_pct = round(row.month_actual / row.month_budget * 100, 1) if row.month_budget else 0
			row.ytd_pct = round(row.ytd_actual / row.ytd_budget * 100, 1) if row.ytd_budget else 0
			out.append(row)
	return out


def run_budget_alerts():
	"""Daily: a head past 90 % / 100 % of this month's budget → Accounts Managers, once per level per month."""
	try:
		rows = budget_rows()
	except Exception:
		return
	users = {u for u in frappe.get_all("Has Role", filters={"role": "Accounts Manager", "parenttype": "User"}, pluck="parent")
		if u != "Administrator" and frappe.db.get_value("User", u, "enabled")}
	month = getdate(today()).strftime("%b %Y")
	for r in rows:
		level = max((lv for lv in LEVELS if r.month_pct >= lv), default=None)
		if not level:
			continue
		marker = f"[ib-budget-{level}-{month}]"
		if frappe.db.exists("Notification Log", {"document_type": "Budget", "document_name": r.name,
				"subject": ["like", f"%{r.account.rsplit(' - ', 1)[0]}%{marker}%"]}):
			continue
		subject = _("{0}: {1}% of {2} budget used ({3} of {4}) {5}").format(
			r.account.rsplit(" - ", 1)[0], r.month_pct, month, frappe.utils.fmt_money(r.month_actual, 0),
			frappe.utils.fmt_money(r.month_budget, 0), marker)
		for u in users:
			frappe.get_doc({"doctype": "Notification Log", "for_user": u, "type": "Alert", "subject": subject[:140],
				"document_type": "Budget", "document_name": r.name}).insert(ignore_permissions=True)
	frappe.db.commit()
