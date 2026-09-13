import frappe
from frappe.utils import nowdate, getdate, get_first_day, get_last_day, add_months, flt

from instabiz.overrides.billing_mode import (
	is_dev_billing_mode, sales_doctype, purchase_doctype,
	sales_outstanding_expr, purchase_outstanding_expr,
)


def get_context(context):
	context.no_cache = 1


def _get_fy_start(today):
	try:
		from erpnext.accounts.utils import get_fiscal_year
		return getdate(get_fiscal_year(today)[1])
	except Exception:
		# Fallback: April 1 of current or previous year
		d = getdate(today)
		return getdate(f"{d.year if d.month >= 4 else d.year - 1}-04-01")


@frappe.whitelist()
def get_finance_data():
	# Page nav restricts to these roles but the RPC had no internal check —
	# any authenticated user could pull company-wide cash/bank/AR/AP/GST data.
	frappe.only_for(["System Manager", "Accounts Manager", "Accounts User", "Sales Manager"])
	today = getdate(nowdate())
	month_start = get_first_day(today)
	last_start = get_first_day(add_months(today, -1))
	last_end = get_last_day(add_months(today, -1))
	fy_start = _get_fy_start(today)

	# Basis controlled by instabiz.overrides.billing_mode — this whole
	# dashboard was previously 100% hardcoded to Sales/Purchase Invoice and
	# read zero everywhere, since real invoicing isn't live yet (unlike
	# sales_target.py/AR-AP Aging/Business Pulse, which had each been
	# separately, inconsistently patched to Sales/Purchase Order already).
	dev_mode    = is_dev_billing_mode()
	sales_dt    = sales_doctype()
	purch_dt    = purchase_doctype()
	sales_date  = "transaction_date" if dev_mode else "posting_date"
	purch_date  = "transaction_date" if dev_mode else "posting_date"
	# Sales side: only 'Cancelled' excluded, not 'Closed' — CustomSalesOrder.STATUS_MAP
	# maps DB status 'Closed' to user-facing label 'Confirmed' (a real completed sale).
	sales_cond  = "AND t.status != 'Cancelled'" if dev_mode else "AND t.is_return=0"
	purch_cond  = "AND t.status NOT IN ('Closed', 'Cancelled')" if dev_mode else "AND t.is_return=0"
	ar_expr     = sales_outstanding_expr("t")
	ap_expr     = purchase_outstanding_expr("t")

	# ── Revenue ──────────────────────────────────────────────────────────────
	rev_mtd = flt(frappe.db.sql(f"""
		SELECT COALESCE(SUM(grand_total),0) FROM `tab{sales_dt}` t
		WHERE docstatus=1 {sales_cond} AND {sales_date} BETWEEN %s AND %s
	""", (month_start, today))[0][0])

	rev_last = flt(frappe.db.sql(f"""
		SELECT COALESCE(SUM(grand_total),0) FROM `tab{sales_dt}` t
		WHERE docstatus=1 {sales_cond} AND {sales_date} BETWEEN %s AND %s
	""", (last_start, last_end))[0][0])

	rev_ytd = flt(frappe.db.sql(f"""
		SELECT COALESCE(SUM(grand_total),0) FROM `tab{sales_dt}` t
		WHERE docstatus=1 {sales_cond} AND {sales_date} BETWEEN %s AND %s
	""", (fy_start, today))[0][0])

	# ── Expenses (Purchase Invoices / Purchase Orders + IB Expense) ──────────
	# IB Expense (company/operational spend — rent, utilities, etc., see
	# instabiz/instabiz/doctype/ib_expense/) posts its own real GL entries but
	# is a separate doctype from Purchase Order/Invoice, so it was silently
	# excluded here — "Expenses MTD"/"Gross Profit" understated real spend
	# the moment anyone used it. Always included regardless of billing mode
	# (IB Expense has no dev/prod distinction — it's real either way).
	def _ib_expense_sum(start, end):
		return flt(frappe.db.sql("""
			SELECT COALESCE(SUM(amount),0) FROM `tabIB Expense`
			WHERE docstatus=1 AND posting_date BETWEEN %s AND %s
		""", (start, end))[0][0])

	exp_mtd = flt(frappe.db.sql(f"""
		SELECT COALESCE(SUM(grand_total),0) FROM `tab{purch_dt}` t
		WHERE docstatus=1 {purch_cond} AND {purch_date} BETWEEN %s AND %s
	""", (month_start, today))[0][0]) + _ib_expense_sum(month_start, today)

	exp_last = flt(frappe.db.sql(f"""
		SELECT COALESCE(SUM(grand_total),0) FROM `tab{purch_dt}` t
		WHERE docstatus=1 {purch_cond} AND {purch_date} BETWEEN %s AND %s
	""", (last_start, last_end))[0][0]) + _ib_expense_sum(last_start, last_end)

	# ── Outstanding AR / AP ───────────────────────────────────────────────────
	ar = flt(frappe.db.sql(f"""
		SELECT COALESCE(SUM({ar_expr}),0) FROM `tab{sales_dt}` t
		WHERE docstatus=1 {sales_cond}
	""")[0][0])

	ap = flt(frappe.db.sql(f"""
		SELECT COALESCE(SUM({ap_expr}),0) FROM `tab{purch_dt}` t
		WHERE docstatus=1 {purch_cond}
	""")[0][0])

	# ── Cash & Bank balances (real GL entries — unaffected by billing mode) ──
	company = frappe.db.get_default("company") or frappe.db.sql(
		"SELECT name FROM `tabCompany` LIMIT 1"
	)[0][0]

	cash_bank = frappe.db.sql("""
		SELECT a.name, a.account_type,
			COALESCE(SUM(gl.debit - gl.credit), 0) as balance
		FROM `tabAccount` a
		LEFT JOIN `tabGL Entry` gl ON gl.account = a.name AND gl.is_cancelled = 0
		WHERE a.account_type IN ('Cash','Bank') AND a.company = %s
		GROUP BY a.name, a.account_type
		ORDER BY balance DESC
	""", (company,), as_dict=True)

	total_cash_bank = sum(flt(r.balance) for r in cash_bank)

	# ── GST summary ───────────────────────────────────────────────────────────
	# Sales/Purchase Taxes and Charges are shared child tables already present
	# on Quotation/SO/DN/SI and PO/PR/PI alike, so the same join works in
	# either billing mode — only the parent doctype/date field changes.
	gst_collected = flt(frappe.db.sql(f"""
		SELECT COALESCE(SUM(tx.tax_amount),0)
		FROM `tabSales Taxes and Charges` tx
		JOIN `tab{sales_dt}` t ON t.name = tx.parent AND tx.parenttype = %s
		WHERE t.docstatus=1 AND t.{sales_date} BETWEEN %s AND %s
		AND (tx.account_head LIKE '%%GST%%' OR tx.account_head LIKE '%%gst%%'
			OR tx.account_head LIKE '%%CGST%%' OR tx.account_head LIKE '%%IGST%%'
			OR tx.account_head LIKE '%%SGST%%')
	""", (sales_dt, month_start, today))[0][0])

	gst_paid = flt(frappe.db.sql(f"""
		SELECT COALESCE(SUM(tx.tax_amount),0)
		FROM `tabPurchase Taxes and Charges` tx
		JOIN `tab{purch_dt}` t ON t.name = tx.parent AND tx.parenttype = %s
		WHERE t.docstatus=1 AND t.{purch_date} BETWEEN %s AND %s
		AND (tx.account_head LIKE '%%GST%%' OR tx.account_head LIKE '%%gst%%'
			OR tx.account_head LIKE '%%CGST%%' OR tx.account_head LIKE '%%IGST%%'
			OR tx.account_head LIKE '%%SGST%%')
	""", (purch_dt, month_start, today))[0][0])

	gst_net = gst_collected - gst_paid

	# ── Monthly P&L trend (6 months) ─────────────────────────────────────────
	pl_trend = frappe.db.sql(f"""
		SELECT DATE_FORMAT({sales_date},'%%b %%Y') as label,
			   DATE_FORMAT({sales_date},'%%Y-%%m') as ym,
			   COALESCE(SUM(grand_total),0) as revenue
		FROM `tab{sales_dt}` t
		WHERE docstatus=1 {sales_cond}
		AND {sales_date} >= DATE_SUB(%s, INTERVAL 6 MONTH)
		GROUP BY ym, label ORDER BY ym
	""", (today,), as_dict=True)

	exp_trend = frappe.db.sql(f"""
		SELECT DATE_FORMAT({purch_date},'%%Y-%%m') as ym,
			   COALESCE(SUM(grand_total),0) as expenses
		FROM `tab{purch_dt}` t
		WHERE docstatus=1 {purch_cond}
		AND {purch_date} >= DATE_SUB(%s, INTERVAL 6 MONTH)
		GROUP BY ym ORDER BY ym
	""", (today,), as_dict=True)

	ib_expense_trend = frappe.db.sql("""
		SELECT DATE_FORMAT(posting_date,'%%Y-%%m') as ym,
			   COALESCE(SUM(amount),0) as expenses
		FROM `tabIB Expense`
		WHERE docstatus=1
		AND posting_date >= DATE_SUB(%s, INTERVAL 6 MONTH)
		GROUP BY ym ORDER BY ym
	""", (today,), as_dict=True)

	exp_map = {r.ym: flt(r.expenses) for r in exp_trend}
	for r in ib_expense_trend:
		exp_map[r.ym] = exp_map.get(r.ym, 0) + flt(r.expenses)
	for r in pl_trend:
		r.expenses = exp_map.get(r.ym, 0)
		r.profit = flt(r.revenue) - r.expenses

	# ── Overdue AR ────────────────────────────────────────────────────────────
	# Dev mode has no real due_date pre-invoice — falls back to the order's
	# own date, same as AR Aging report.
	overdue = frappe.db.sql(f"""
		SELECT name, customer_name, {sales_date} as posting_date,
			   {sales_date} as due_date, {ar_expr} as outstanding_amount, grand_total,
			   DATEDIFF(%s, {sales_date}) as days_overdue
		FROM `tab{sales_dt}` t
		WHERE docstatus=1 {sales_cond}
		AND {sales_date} < %s
		HAVING outstanding_amount > 0
		ORDER BY outstanding_amount DESC
		LIMIT 15
	""", (today, today), as_dict=True)

	# ── Top expense vendors ───────────────────────────────────────────────────
	top_vendors = frappe.db.sql(f"""
		SELECT supplier_name as label, COALESCE(SUM(grand_total),0) as amount
		FROM `tab{purch_dt}` t
		WHERE docstatus=1 {purch_cond} AND {purch_date} BETWEEN %s AND %s
		GROUP BY supplier_name ORDER BY amount DESC LIMIT 8
	""", (month_start, today), as_dict=True)

	# ── Pending payments (real, unaffected by billing mode) ──────────────────
	pending_pe = frappe.db.sql("""
		SELECT COUNT(*) as cnt, COALESCE(SUM(paid_amount),0) as total
		FROM `tabPayment Entry`
		WHERE docstatus=0
	""", as_dict=True)[0]

	return {
		"sales_dt": sales_dt,
		"purch_dt": purch_dt,
		# Frontend needs this to know Sales Order (dev mode) has no
		# outstanding_amount column — a route_options filter built for Sales
		# Invoice's own field would silently 500/return nothing on that
		# doctype's list view.
		"dev_mode": dev_mode,
		"sales_date_field": sales_date,
		"purch_date_field": purch_date,
		"rev_mtd": rev_mtd,
		"rev_last": rev_last,
		"rev_delta": round((rev_mtd - rev_last) / rev_last * 100, 1) if rev_last else 0,
		"rev_ytd": rev_ytd,
		"exp_mtd": exp_mtd,
		"exp_last": exp_last,
		"exp_delta": round((exp_mtd - exp_last) / exp_last * 100, 1) if exp_last else 0,
		"ar": ar,
		"ap": ap,
		"total_cash_bank": total_cash_bank,
		"cash_bank_accounts": cash_bank,
		"gst_collected": gst_collected,
		"gst_paid": gst_paid,
		"gst_net": gst_net,
		"pl_trend": pl_trend,
		"overdue": overdue,
		"top_vendors": top_vendors,
		"pending_pe_count": int(pending_pe.cnt or 0),
		"pending_pe_total": flt(pending_pe.total),
		"gross_profit": rev_mtd - exp_mtd,
		"gross_margin": round((rev_mtd - exp_mtd) / rev_mtd * 100, 1) if rev_mtd else 0,
	}
