import frappe
from frappe.utils import nowdate, getdate, get_first_day, get_last_day, add_months, flt

from instabiz.overrides.billing_mode import sales_total_expr, is_dev_billing_mode, sales_doctype, sales_outstanding_expr


def get_context(context):
	context.no_cache = 1


@frappe.whitelist()
def get_pulse_data():
	# Page nav restricts to these roles but the RPC had no internal check —
	# any authenticated user could pull company-wide revenue/AR/HR/production
	# data. Same bug class already fixed in ib_finance_dashboard.py /
	# ib_procurement_dashboard.py — backported here.
	frappe.only_for(["System Manager", "Sales Manager", "Accounts Manager", "Factory Management"])
	today = getdate(nowdate())
	month_start = get_first_day(today)
	last_month_start = get_first_day(add_months(today, -1))
	last_month_end = get_last_day(add_months(today, -1))

	# ── Revenue ──────────────────────────────────────────────────────────────
	# Basis controlled by instabiz.overrides.billing_mode — dev mode reads
	# Sales Order (billing isn't live in ERP yet, so SI-based revenue/AR always
	# read 0). AR and collection rate previously stayed hardcoded to Sales
	# Invoice even after revenue was switched, so both silently read 0/100%
	# regardless of real order activity — fixed to follow the same toggle.
	dev_mode = is_dev_billing_mode()
	doctype = sales_doctype()
	date_field = "transaction_date" if dev_mode else "posting_date"
	outstanding_expr = sales_outstanding_expr("t")
	# Only 'Cancelled' excluded, not 'Closed' — CustomSalesOrder.STATUS_MAP maps
	# DB status 'Closed' to user-facing label 'Confirmed' (a real completed sale).
	status_cond = "AND t.status != 'Cancelled'" if dev_mode else "AND t.is_return=0"

	rev_mtd = flt(frappe.db.sql(f"""
		SELECT COALESCE(SUM({sales_total_expr(None)}), 0)
		FROM `tab{doctype}`
		WHERE docstatus=1
		AND {date_field} BETWEEN %s AND %s
	""", (month_start, today))[0][0])

	rev_last = flt(frappe.db.sql(f"""
		SELECT COALESCE(SUM({sales_total_expr(None)}), 0)
		FROM `tab{doctype}`
		WHERE docstatus=1
		AND {date_field} BETWEEN %s AND %s
	""", (last_month_start, last_month_end))[0][0])

	ar = flt(frappe.db.sql(f"""
		SELECT COALESCE(SUM({outstanding_expr}), 0)
		FROM `tab{doctype}` t
		WHERE docstatus=1 {status_cond}
	""")[0][0])

	# Collection rate = collected / billed for the same 3-month window. In dev
	# mode "collected" means advance paid against orders (custom_advance_paid)
	# — the only real payment signal that exists pre-invoice.
	three_months_start = get_first_day(add_months(today, -3))
	total_billed = flt(frappe.db.sql(f"""
		SELECT COALESCE(SUM({sales_total_expr('t')}), 0)
		FROM `tab{doctype}` t
		WHERE docstatus=1 {status_cond}
		AND {date_field} BETWEEN %s AND %s
	""", (three_months_start, today))[0][0])
	ar_3m = flt(frappe.db.sql(f"""
		SELECT COALESCE(SUM({outstanding_expr}), 0)
		FROM `tab{doctype}` t
		WHERE docstatus=1 {status_cond}
		AND {date_field} BETWEEN %s AND %s
	""", (three_months_start, today))[0][0])
	collected_3m = max(0.0, total_billed - ar_3m)
	collection_rate = max(0.0, min(100.0, round(collected_3m / total_billed * 100, 1))) if total_billed else 100.0
	rev_change_pct = round(((rev_mtd - rev_last) / rev_last * 100), 1) if rev_last else None

	# ── Sales Pipeline ───────────────────────────────────────────────────────
	open_leads = flt(frappe.db.sql("""
		SELECT COUNT(*) FROM `tabLead`
		WHERE status NOT IN ('Converted','Do Not Contact')
	""")[0][0])

	open_quotes = flt(frappe.db.sql("""
		SELECT COUNT(*) FROM `tabQuotation`
		WHERE docstatus=1 AND status NOT IN ('Ordered','Lost','Cancelled','Expired','Confirmed')
	""")[0][0])

	# ── Inventory ────────────────────────────────────────────────────────────
	try:
		total_items = flt(frappe.db.sql(
			"SELECT COUNT(DISTINCT item_code) FROM `tabBin` WHERE actual_qty > 0"
		)[0][0])
		# Same definition as reorder_alert.py / ib_stock_dashboard.py — actual_qty at
		# or below the item's reorder level, not just zero-stock-with-reservation.
		low_stock = flt(frappe.db.sql("""
			SELECT COUNT(DISTINCT b.item_code) FROM `tabBin` b
			INNER JOIN `tabItem Reorder` r
				ON r.parent = b.item_code AND r.warehouse = b.warehouse
			WHERE r.warehouse_reorder_level > 0
			  AND b.actual_qty <= r.warehouse_reorder_level
		""")[0][0])
	except Exception:
		total_items, low_stock = 0, 0

	# ── Procurement / Payables ───────────────────────────────────────────────
	try:
		open_po = flt(frappe.db.sql("""
			SELECT COUNT(*) FROM `tabPurchase Order`
			WHERE docstatus=1 AND status NOT IN ('Completed','Cancelled','Closed')
		""")[0][0])
	except Exception:
		open_po = 0

	# ── HR ────────────────────────────────────────────────────────────────────
	try:
		total_emp = flt(frappe.db.sql(
			"SELECT COUNT(*) FROM `tabEmployee` WHERE status='Active'"
		)[0][0])
		present_today = flt(frappe.db.sql("""
			SELECT COUNT(DISTINCT employee) FROM (
				SELECT employee FROM `tabEmployee Checkin`
				WHERE DATE(time) = %s AND log_type = 'IN'
				UNION
				SELECT employee FROM `tabAttendance`
				WHERE attendance_date = %s AND status = 'Present' AND docstatus = 1
			) _combined
		""", (today, today))[0][0])
	except Exception:
		total_emp, present_today = 0, 0

	# ── Production ───────────────────────────────────────────────────────────
	try:
		wo_active = flt(frappe.db.sql("""
			SELECT COUNT(*) FROM `tabIB Work Order`
			WHERE status NOT IN ('Completed','Cancelled')
		""")[0][0])
		wo_completed = flt(frappe.db.sql("""
			SELECT COUNT(*) FROM `tabIB Work Order`
			WHERE status='Completed'
			AND COALESCE(completed_at, modified) >= %s
		""", (month_start,))[0][0])
	except Exception:
		wo_active, wo_completed = 0, 0

	# ── 14-day revenue trend ──────────────────────────────────────────────────
	trend_14 = frappe.db.sql(f"""
		SELECT
			DATE_FORMAT({date_field}, '%%d %%b') as label,
			{date_field} as dt,
			COALESCE(SUM({sales_total_expr('t')}), 0) as amount
		FROM `tab{doctype}` t
		WHERE docstatus=1 {status_cond}
		AND {date_field} >= DATE_SUB(%s, INTERVAL 13 DAY)
		GROUP BY dt, label
		ORDER BY dt
	""", (today,), as_dict=True)

	return {
		"dev_mode": dev_mode,
		"sales_doctype": doctype,
		"date_field": date_field,
		"month_start": str(month_start),
		"last_month_start": str(last_month_start),
		"last_month_end": str(last_month_end),
		"today": str(today),
		"rev_mtd": rev_mtd,
		"rev_last": rev_last,
		"rev_change_pct": rev_change_pct,
		"collection_rate": collection_rate,
		"ar": ar,
		"open_leads": int(open_leads),
		"open_quotes": int(open_quotes),
		"total_items": int(total_items),
		"low_stock": int(low_stock),
		"open_po": int(open_po),
		"total_emp": int(total_emp),
		"present_today": int(present_today),
		"wo_active": int(wo_active),
		"wo_completed": int(wo_completed),
		"trend_14": trend_14,
	}
