import frappe
from frappe.utils import nowdate, getdate, get_first_day, get_last_day, add_months, flt

from instabiz.overrides.billing_mode import sales_total_expr, is_dev_billing_mode, sales_doctype, sales_outstanding_expr


def get_context(context):
	context.no_cache = 1


@frappe.whitelist()
def get_dashboard_data():
	# Page nav restricts to these roles but the RPC had no internal check —
	# any authenticated user could pull company-wide revenue/AR/top-customer
	# data. Same bug class already fixed in ib_finance_dashboard.py /
	# ib_procurement_dashboard.py — backported here.
	frappe.only_for(["System Manager", "Sales Manager", "Sales User", "Accounts Manager", "Accounts User", "Factory Management"])
	today = getdate(nowdate())
	month_start = get_first_day(today)
	last_month_start = get_first_day(add_months(today, -1))
	last_month_end = get_last_day(add_months(today, -1))

	# Basis controlled by instabiz.overrides.billing_mode — dev mode reads
	# Sales Order (billing isn't live in ERP yet, so SI-based figures always
	# read 0/wrong); prod mode reads Sales Invoice for real revenue-
	# realization accounting. AR/trend/top-customers/recent-docs were
	# previously left hardcoded to Sales Invoice even after revenue was
	# switched, so they silently read zero/empty regardless of order activity.
	dev_mode = is_dev_billing_mode()
	sales_dt = sales_doctype()
	date_field = "transaction_date" if dev_mode else "posting_date"
	# Only 'Cancelled' excluded, not 'Closed' — CustomSalesOrder.STATUS_MAP maps
	# DB status 'Closed' to user-facing label 'Confirmed' (a real completed sale).
	status_cond = "AND t.status != 'Cancelled'" if dev_mode else "AND t.is_return=0"
	from instabiz.overrides.own_data import locked_user

	if locked_user():  # a plain Sales User sees their own figures, not the company's
		status_cond += f" AND t.custom_sales_person_user = {frappe.db.escape(locked_user())}"
	ar_expr = sales_outstanding_expr("t")

	# ── Revenue MTD ──────────────────────────────────────────────────────────
	rev_mtd = flt(frappe.db.sql(f"""
		SELECT COALESCE(SUM({sales_total_expr('t')}), 0)
		FROM `tab{sales_dt}` t
		WHERE docstatus=1 {status_cond}
		AND {date_field} BETWEEN %s AND %s
	""", (month_start, today))[0][0])

	rev_last = flt(frappe.db.sql(f"""
		SELECT COALESCE(SUM({sales_total_expr('t')}), 0)
		FROM `tab{sales_dt}` t
		WHERE docstatus=1 {status_cond}
		AND {date_field} BETWEEN %s AND %s
	""", (last_month_start, last_month_end))[0][0])

	rev_delta = round(((rev_mtd - rev_last) / rev_last * 100), 1) if rev_last else 0

	# ── Outstanding AR ───────────────────────────────────────────────────────
	ar = flt(frappe.db.sql(f"""
		SELECT COALESCE(SUM({ar_expr}), 0)
		FROM `tab{sales_dt}` t
		WHERE docstatus=1 {status_cond}
	""")[0][0])

	# ── Open Quotations ──────────────────────────────────────────────────────
	quotes = flt(frappe.db.sql("""
		SELECT COUNT(*) FROM `tabQuotation`
		WHERE docstatus=1 AND status NOT IN ('Ordered','Lost','Cancelled','Expired','Confirmed')
	""")[0][0])

	# ── Open Sales Orders ────────────────────────────────────────────────────
	open_so = flt(frappe.db.sql("""
		SELECT COUNT(*) FROM `tabSales Order`
		WHERE docstatus=1 AND status NOT IN ('Completed','Cancelled','Closed','Confirmed')
	""")[0][0])

	# ── Pending Delivery Notes ───────────────────────────────────────────────
	pending_dn = flt(frappe.db.sql("""
		SELECT COUNT(*) FROM `tabDelivery Note`
		WHERE docstatus=0
	""")[0][0])

	# ── Low / zero stock (actual_qty at or below the item's reorder level) ──
	# Same definition as reorder_alert.py — was previously narrowed to
	# actual_qty<=0 AND reserved_qty>0, which excluded plain zero-stock
	# items with no open reservation and any genuinely-low (but positive)
	# stock, contradicting the "Low / Zero Stock" label.
	try:
		low_stock = flt(frappe.db.sql("""
			SELECT COUNT(DISTINCT b.item_code) FROM `tabBin` b
			INNER JOIN `tabItem Reorder` r
				ON r.parent = b.item_code AND r.warehouse = b.warehouse
			WHERE r.warehouse_reorder_level > 0
			  AND b.actual_qty <= r.warehouse_reorder_level
		""")[0][0])
	except Exception:
		low_stock = 0

	# ── 6-month revenue trend ────────────────────────────────────────────────
	trend = frappe.db.sql(f"""
		SELECT
			DATE_FORMAT({date_field}, '%%b %%Y') as label,
			DATE_FORMAT({date_field}, '%%Y-%%m') as ym,
			COALESCE(SUM({sales_total_expr('t')}), 0) as amount,
			COALESCE(SUM(base_grand_total), 0) as base_amount
		FROM `tab{sales_dt}` t
		WHERE docstatus=1 {status_cond}
		AND {date_field} >= DATE_SUB(%s, INTERVAL 6 MONTH)
		GROUP BY ym, label
		ORDER BY ym
	""", (today,), as_dict=True)

	# ── Top 5 customers this month ───────────────────────────────────────────
	top_customers = frappe.db.sql(f"""
		SELECT customer_name, COALESCE(SUM({sales_total_expr('t')}), 0) as total
		FROM `tab{sales_dt}` t
		WHERE docstatus=1 {status_cond}
		AND {date_field} BETWEEN %s AND %s
		GROUP BY customer_name
		ORDER BY total DESC
		LIMIT 5
	""", (month_start, today), as_dict=True)

	# ── Recent docs — scoped to user unless privileged ───────────────────────
	roles = frappe.get_roles(frappe.session.user)
	privileged = any(r in roles for r in ("System Manager", "Sales Manager", "Accounts Manager", "Accounts User"))
	si_cond = "" if privileged else f"AND custom_sales_person_user = {frappe.db.escape(frappe.session.user)}"
	recent_si = frappe.db.sql(f"""
		SELECT name, customer_name, {date_field} as posting_date, {date_field} as due_date,
		       {sales_total_expr('t')} as grand_total, {ar_expr} as outstanding_amount, status
		FROM `tab{sales_dt}` t
		WHERE docstatus=1 {si_cond}
		ORDER BY {date_field} DESC, creation DESC
		LIMIT 8
	""", as_dict=True)

	return {
		"sales_dt": sales_dt,
		"sales_date_field": date_field,
		"rev_mtd": rev_mtd,
		"rev_last": rev_last,
		"rev_delta": rev_delta,
		"ar": ar,
		"quotes": int(quotes),
		"open_so": int(open_so),
		"pending_dn": int(pending_dn),
		"low_stock": int(low_stock),
		"trend": trend,
		"top_customers": top_customers,
		"recent_si": recent_si,
	}
