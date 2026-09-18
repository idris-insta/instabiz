import frappe
from frappe.utils import nowdate, getdate, get_first_day, add_months, flt

from instabiz.overrides.billing_mode import (
	is_dev_billing_mode, sales_doctype, sales_outstanding_expr,
	purchase_doctype, purchase_outstanding_expr,
)


def get_context(context):
	context.no_cache = 1


_PRIVILEGED_ANALYTICS_ROLES = {"System Manager", "Sales Manager", "Accounts Manager", "Factory Management"}
# Per-tab additions on top of the base set above — HR Manager/HR User run
# company HR ops, Stock Manager runs company stock, and Purchase Manager
# owns AP (the Finance tab's AP figures are their domain even though they
# have nothing to do with sales/AR), so each needs the privileged
# (company-wide) view on their own tab specifically — same as Factory
# Management does for Production and Accounts Manager does for Finance.
# They stay non-privileged (scoped to their own work) on every other tab,
# same as any other non-privileged role.
# Accounts User added to "finance" 2026-08-06 — was falling through to
# _my_finance_data() (filtered by custom_sales_person_user = user), which is
# always empty for an Accounts User since they aren't a sales rep and own no
# Sales Orders. Their whole job is processing AR/AP company-wide, same
# reasoning as Purchase Manager owning AP — bug, not intentional scoping.
_TAB_EXTRA_PRIVILEGED_ROLES = {
	"hr": {"HR Manager", "HR User"},
	"inventory": {"Stock Manager"},
	"finance": {"Purchase Manager", "Accounts User"},
	"procurement": {"Purchase Manager", "Purchase User"},
	"docs": {"Accounts User"},
}


@frappe.whitelist()
def get_analytics_data(tab="sales", period="monthly"):
	# Every tab is open to any authenticated user — "me" was always self-scoped;
	# the other tabs used to hard-block anyone without a privileged role. Now
	# privileged roles still get the full company-wide view, everyone else gets
	# a content-aware view scoped to their own work (own orders/customers, a
	# stock in/out signal with no real numbers, their own SOs' production
	# status, their own HR self-service snapshot) instead of either "everything"
	# or "nothing".
	user = frappe.session.user
	user_roles = set(frappe.get_roles(user))
	base_privileged = bool(_PRIVILEGED_ANALYTICS_ROLES & user_roles)

	def is_tab_privileged(tab_name):
		if base_privileged:
			return True
		return bool(_TAB_EXTRA_PRIVILEGED_ROLES.get(tab_name, set()) & user_roles)

	today = getdate(nowdate())

	# `since`/date_fmt/group_fmt drive the trend chart's window+bucketing.
	# `period_start`/`prev_start`/`prev_end`/`period_label` drive the headline
	# KPI cards — previously those were hardcoded to calendar-month-to-date
	# regardless of which period tab was selected, so clicking Daily/Weekly
	# only ever changed the trend chart underneath while every number on the
	# page stayed exactly the same (confirmed: "Revenue MTD" was still MTD
	# after clicking Daily). Both now derive from the same period selector.
	if period == "daily":
		since = frappe.utils.add_days(today, -30)
		date_fmt = "%%d %%b"
		group_fmt = "%%Y-%%m-%%d"
		period_start = today
		prev_start = prev_end = frappe.utils.add_days(today, -1)
		period_label = "Today"
	elif period == "weekly":
		since = frappe.utils.add_days(today, -84)
		date_fmt = "Week %%U"
		group_fmt = "%%Y-%%U"
		period_start = frappe.utils.add_days(today, -today.weekday())  # Monday this week
		prev_start = frappe.utils.add_days(period_start, -7)
		prev_end = frappe.utils.add_days(period_start, -1)
		period_label = "WTD"
	else:
		since = get_first_day(add_months(today, -11))
		date_fmt = "%%b %%Y"
		group_fmt = "%%Y-%%m"
		period_start = get_first_day(today)
		prev_start = get_first_day(add_months(today, -1))
		prev_end = frappe.utils.get_last_day(add_months(today, -1))
		period_label = "MTD"

	pw = {
		"period_start": period_start, "period_end": today,
		"prev_start": prev_start, "prev_end": prev_end,
		"period_label": period_label,
	}

	month_start = get_first_day(today)

	if tab == "sales":
		if is_tab_privileged("sales"):
			return _sales_data(today, since, date_fmt, group_fmt, pw)
		return _my_work_sales(user, today, since, date_fmt, group_fmt, month_start, pw)
	elif tab == "inventory":
		if is_tab_privileged("inventory"):
			return _inventory_data(today, since, date_fmt, group_fmt)
		return _my_inventory_data()
	elif tab == "production":
		if is_tab_privileged("production"):
			return _production_data(today, since, date_fmt, group_fmt, pw)
		return _my_production_status_data(user, pw)
	elif tab == "hr":
		if is_tab_privileged("hr"):
			return _hr_data(today, since, date_fmt, group_fmt, pw)
		return _my_personal_hr_data(user, today, since, date_fmt, group_fmt, month_start, pw)
	elif tab == "finance":
		if is_tab_privileged("finance"):
			return _finance_data(today, since, date_fmt, group_fmt, pw)
		return _my_finance_data(user, today, since, date_fmt, group_fmt, month_start, pw)
	elif tab == "procurement":
		if is_tab_privileged("procurement"):
			return _procurement_data(today, since, date_fmt, group_fmt, pw)
		return _my_procurement_data()
	elif tab == "docs":
		# HR doc-chain (Leave/Overtime/F&F/Salary Slip) is a completely
		# different shape from the order-chain (Q/SO/DN/SI/Payment/Production/
		# AR) — checked first and always company-wide, matching the existing
		# hr-tab privilege (both HR Manager and HR User are privileged there).
		if user_roles & {"HR Manager", "HR User"}:
			return _docs_hr_data()
		return _docs_order_data(user, is_tab_privileged("docs"))
	elif tab == "me":
		return _my_work_data(user, today, since, date_fmt, group_fmt, pw)
	return {}


def _sales_data(today, since, date_fmt, group_fmt, pw):
	# Basis controlled by instabiz.overrides.billing_mode — was 100%
	# hardcoded to Sales Invoice, so this whole tab read zero (billing isn't
	# live in ERP yet).
	period_start, period_end = pw["period_start"], pw["period_end"]
	prev_start, prev_end = pw["prev_start"], pw["prev_end"]
	period_label = pw["period_label"]

	dev_mode = is_dev_billing_mode()
	sales_dt = sales_doctype()
	sales_date = "transaction_date" if dev_mode else "posting_date"
	# Only 'Cancelled' excluded, not 'Closed' — CustomSalesOrder.STATUS_MAP maps
	# DB status 'Closed' to user-facing label 'Confirmed' (a real completed sale).
	sales_cond = "AND t.status != 'Cancelled'" if dev_mode else "AND t.is_return=0"
	outstanding_expr = sales_outstanding_expr("t")
	item_dt = f"{sales_dt} Item"

	rev_period = flt(frappe.db.sql(f"""
		SELECT COALESCE(SUM(grand_total),0) FROM `tab{sales_dt}` t
		WHERE docstatus=1 {sales_cond} AND {sales_date} BETWEEN %s AND %s
	""", (period_start, period_end))[0][0])

	rev_prev = flt(frappe.db.sql(f"""
		SELECT COALESCE(SUM(grand_total),0) FROM `tab{sales_dt}` t
		WHERE docstatus=1 {sales_cond} AND {sales_date} BETWEEN %s AND %s
	""", (prev_start, prev_end))[0][0])

	invoice_count = flt(frappe.db.sql(f"""
		SELECT COUNT(*) FROM `tab{sales_dt}` t
		WHERE docstatus=1 {sales_cond} AND {sales_date} BETWEEN %s AND %s
	""", (period_start, period_end))[0][0])

	avg_order = round(rev_period / invoice_count, 2) if invoice_count else 0

	ar = flt(frappe.db.sql(f"""
		SELECT COALESCE(SUM({outstanding_expr}),0)
		FROM `tab{sales_dt}` t WHERE docstatus=1 {sales_cond}
	""")[0][0])

	trend = frappe.db.sql(f"""
		SELECT DATE_FORMAT({sales_date}, '{date_fmt}') as label,
			   DATE_FORMAT({sales_date}, '{group_fmt}') as grp,
			   COALESCE(SUM(grand_total),0) as amount,
			   COUNT(*) as count
		FROM `tab{sales_dt}` t
		WHERE docstatus=1 {sales_cond} AND {sales_date} >= %s
		GROUP BY grp, label ORDER BY grp
	""", (since,), as_dict=True)

	by_customer = frappe.db.sql(f"""
		SELECT customer_name as label, COALESCE(SUM(grand_total),0) as amount
		FROM `tab{sales_dt}` t
		WHERE docstatus=1 {sales_cond} AND {sales_date} BETWEEN %s AND %s
		GROUP BY customer_name ORDER BY amount DESC LIMIT 10
	""", (period_start, period_end), as_dict=True)

	try:
		by_item = frappe.db.sql(f"""
			SELECT i.item_group as label, COALESCE(SUM(i.amount),0) as amount
			FROM `tab{item_dt}` i
			JOIN `tab{sales_dt}` t ON t.name=i.parent
			WHERE t.docstatus=1 {sales_cond} AND t.{sales_date} BETWEEN %s AND %s
			GROUP BY i.item_group ORDER BY amount DESC LIMIT 8
		""", (period_start, period_end), as_dict=True)
	except Exception:
		by_item = []

	return {
		"kpis": [
			{"label": f"Revenue {period_label}", "value": rev_period, "type": "currency",
			 "delta": round((rev_period - rev_prev) / rev_prev * 100, 1) if rev_prev else 0},
			{"label": f"Invoices {period_label}", "value": int(invoice_count), "type": "count", "delta": 0},
			{"label": "Avg Invoice", "value": avg_order, "type": "currency", "delta": 0},
			{"label": "Outstanding AR", "value": ar, "type": "currency", "delta": 0},
		],
		"trend": trend,
		"breakdown": by_customer,
		"secondary": by_item,
	}


def _inventory_data(today, since, date_fmt, group_fmt):
	try:
		total_items = flt(frappe.db.sql(
			"SELECT COUNT(DISTINCT item_code) FROM `tabBin`"
		)[0][0])
		in_stock = flt(frappe.db.sql(
			"SELECT COUNT(DISTINCT item_code) FROM `tabBin` WHERE actual_qty > 0"
		)[0][0])
		negative = flt(frappe.db.sql(
			"SELECT COUNT(DISTINCT item_code) FROM `tabBin` WHERE actual_qty < 0"
		)[0][0])
		stock_val = flt(frappe.db.sql("""
			SELECT COALESCE(SUM(stock_value), 0)
			FROM `tabBin` WHERE actual_qty > 0
		""")[0][0])
	except Exception:
		stock_val = 0
		total_items = in_stock = negative = 0

	by_warehouse = frappe.db.sql("""
		SELECT warehouse as label, COALESCE(SUM(actual_qty), 0) as amount
		FROM `tabBin`
		WHERE actual_qty > 0
		GROUP BY warehouse ORDER BY amount DESC LIMIT 10
	""", as_dict=True)

	by_item_group = []
	try:
		by_item_group = frappe.db.sql("""
			SELECT i.item_group as label, COUNT(DISTINCT b.item_code) as amount
			FROM `tabBin` b JOIN `tabItem` i ON i.name=b.item_code
			WHERE b.actual_qty > 0
			GROUP BY i.item_group ORDER BY amount DESC LIMIT 8
		""", as_dict=True)
	except Exception:
		pass

	recent_movements = frappe.db.sql("""
		SELECT item_code, warehouse, qty_after_transaction as qty,
			   voucher_type, voucher_no, posting_date
		FROM `tabStock Ledger Entry`
		WHERE is_cancelled=0
		ORDER BY posting_date DESC, creation DESC
		LIMIT 10
	""", as_dict=True)

	# Goods received (inbound SLE) trend
	try:
		inbound_trend = frappe.db.sql(f"""
			SELECT DATE_FORMAT(posting_date, '{date_fmt}') as label,
				   DATE_FORMAT(posting_date, '{group_fmt}') as grp,
				   COALESCE(SUM(actual_qty), 0) as amount
			FROM `tabStock Ledger Entry`
			WHERE is_cancelled=0 AND actual_qty > 0 AND posting_date >= %s
			GROUP BY grp, label ORDER BY grp
		""", (since,), as_dict=True)
	except Exception:
		inbound_trend = []

	return {
		"kpis": [
			{"label": "Total SKUs", "value": int(total_items), "type": "count", "delta": 0},
			{"label": "In Stock", "value": int(in_stock), "type": "count", "delta": 0},
			{"label": "Negative Stock", "value": int(negative), "type": "count", "delta": 0},
			{"label": "Stock Value", "value": stock_val, "type": "currency", "delta": 0},
		],
		"trend": inbound_trend,
		"breakdown": by_warehouse,
		"secondary": by_item_group,
		"recent": recent_movements,
	}


def _production_data(today, since, date_fmt, group_fmt, pw):
	period_start = pw["period_start"]
	period_label = pw["period_label"]

	try:
		wo_active = flt(frappe.db.sql("""
			SELECT COUNT(*) FROM `tabIB Work Order`
			WHERE status NOT IN ('Completed','Cancelled')
		""")[0][0])
		wo_completed = flt(frappe.db.sql("""
			SELECT COUNT(*) FROM `tabIB Work Order`
			WHERE status='Completed' AND COALESCE(completed_at, modified) >= %s
		""", (period_start,))[0][0])
		wo_total = flt(frappe.db.sql(
			"SELECT COUNT(*) FROM `tabIB Work Order`"
		)[0][0])
		machines_active = flt(frappe.db.sql(
			"SELECT COUNT(*) FROM `tabIB Machine` WHERE status='Active'"
		)[0][0])

		by_status = frappe.db.sql("""
			SELECT status as label, COUNT(*) as amount
			FROM `tabIB Work Order`
			GROUP BY status ORDER BY amount DESC
		""", as_dict=True)

		# Counts each item's true CURRENT stage only, not every stage it has a
		# WO for. auto_create_all_stage_wos() pre-creates one WO per stage in
		# an item's whole route up front, all Pending — a plain GROUP BY stage
		# on "not Completed/Cancelled" WOs (the original shape of this query)
		# counted every future stage's placeholder as if real work were
		# sitting there, same root cause as the Production page's Stage-wise/
		# Job Bundles/pipeline-card bugs fixed 2026-08-06 in production.py.
		# Fixed the same way: resolve each item's current stage (first
		# non-Completed in route order), then only count it if that stage is
		# genuinely Pending/In Progress right now.
		stage_wo_rows = frappe.db.sql("""
			SELECT stage, status, order_sheet, order_sheet_item, item_code
			FROM `tabIB Work Order`
			WHERE status != 'Cancelled' AND stage IS NOT NULL AND stage != ''
		""", as_dict=True)
		_stage_order = ["Coating", "Slitting", "Rewinding", "Cutting", "Packing"]  # RTD/Delivered collapsed out 2026-08-13
		_stage_rank = {s: i for i, s in enumerate(_stage_order)}
		_item_groups = {}
		for row in stage_wo_rows:
			key = row.order_sheet_item or f"{row.order_sheet}::{row.item_code}"
			_item_groups.setdefault(key, []).append(row)
		_stage_counts = {}
		for wos in _item_groups.values():
			wos.sort(key=lambda r: _stage_rank.get(r.stage, 999))
			current = next((r for r in wos if r.status != "Completed"), None)
			if current:
				_stage_counts[current.stage] = _stage_counts.get(current.stage, 0) + 1
		by_stage = sorted(
			[{"label": s, "amount": c} for s, c in _stage_counts.items()],
			key=lambda r: -r["amount"],
		)[:10]
	except Exception:
		wo_active = wo_completed = wo_total = machines_active = 0
		by_status = []
		by_stage = []

	# WO completion trend from IB Work Order
	try:
		wo_trend = frappe.db.sql(f"""
			SELECT DATE_FORMAT(COALESCE(completed_at, modified), '{date_fmt}') as label,
				   DATE_FORMAT(COALESCE(completed_at, modified), '{group_fmt}') as grp,
				   COUNT(*) as amount
			FROM `tabIB Work Order`
			WHERE status='Completed' AND COALESCE(completed_at, modified) >= %s
			GROUP BY grp, label ORDER BY grp
		""", (since,), as_dict=True)
	except Exception:
		wo_trend = []

	# Avg wastage from completed WOs (wastage_qty / target_qty)
	try:
		avg_wastage = flt(frappe.db.sql("""
			SELECT COALESCE(AVG(wastage_qty / NULLIF(target_qty, 0)) * 100, 0)
			FROM `tabIB Work Order`
			WHERE status='Completed' AND COALESCE(completed_at, modified) >= %s
		""", (period_start,))[0][0])
	except Exception:
		avg_wastage = 0

	return {
		"kpis": [
			{"label": "Active WOs", "value": int(wo_active), "type": "count", "delta": 0},
			{"label": f"Completed {period_label}", "value": int(wo_completed), "type": "count", "delta": 0},
			{"label": "Machines Active", "value": int(machines_active), "type": "count", "delta": 0},
			{"label": "Avg Wastage %", "value": round(avg_wastage, 2), "type": "pct", "delta": 0},
		],
		"trend": wo_trend,
		"breakdown": by_stage if by_stage else by_status,
		"secondary": by_status,
	}


def _hr_data(today, since, date_fmt, group_fmt, pw):
	# HR's headline KPIs (Active Employees, Present Today, Pending Leaves) are
	# point-in-time snapshots and Payroll MTD is inherently monthly — none of
	# them have a meaningful daily/weekly equivalent, so `pw` is intentionally
	# unused here; the period selector still drives this tab's trend chart.
	try:
		total_emp = flt(frappe.db.sql(
			"SELECT COUNT(*) FROM `tabEmployee` WHERE status='Active'"
		)[0][0])
	except Exception:
		total_emp = 0

	try:
		# Count employees who checked in via terminal (Employee Checkin) OR have a
		# submitted Present attendance record. UNION deduplicates employees processed both ways.
		present_today = flt(frappe.db.sql("""
			SELECT COUNT(DISTINCT employee) FROM (
				SELECT employee FROM `tabEmployee Checkin`
				WHERE DATE(time) = %s AND log_type = 'IN'
				UNION
				SELECT employee FROM `tabAttendance`
				WHERE attendance_date = %s AND status = 'Present' AND docstatus = 1
			) _combined
		""", (today, today))[0][0])
		absent_today = flt(frappe.db.sql(
			"SELECT COUNT(*) FROM `tabAttendance` WHERE attendance_date=%s AND status='Absent' AND docstatus=1",
			(today,)
		)[0][0])
	except Exception:
		present_today = absent_today = 0

	try:
		pending_leaves = flt(frappe.db.sql(
			"SELECT COUNT(*) FROM `tabLeave Application` WHERE status='Open' AND docstatus=1"
		)[0][0])
	except Exception:
		pending_leaves = 0

	try:
		attendance_trend = frappe.db.sql(f"""
			SELECT DATE_FORMAT(attendance_date, '{date_fmt}') as label,
				   DATE_FORMAT(attendance_date, '{group_fmt}') as grp,
				   SUM(CASE WHEN status='Present' THEN 1 ELSE 0 END) as amount
			FROM `tabAttendance`
			WHERE attendance_date >= %s AND docstatus=1
			GROUP BY grp, label ORDER BY grp
		""", (since,), as_dict=True)
	except Exception:
		attendance_trend = []

	try:
		by_dept = frappe.db.sql("""
			SELECT department as label, COUNT(*) as amount
			FROM `tabEmployee` WHERE status='Active' AND department IS NOT NULL
			GROUP BY department ORDER BY amount DESC LIMIT 10
		""", as_dict=True)
	except Exception:
		by_dept = []

	try:
		# Payroll is inherently monthly (slips are generated once/month) — always
		# calendar-MTD regardless of the daily/weekly/monthly period selector,
		# since a daily/weekly window would just read 0 for most of the month.
		_pr = frappe.db.sql("""
			SELECT
				COALESCE(SUM(CASE WHEN docstatus=1 THEN net_pay ELSE 0 END), 0) AS sub_pay,
				COALESCE(SUM(CASE WHEN docstatus=0 THEN net_pay ELSE 0 END), 0) AS draft_pay
			FROM `tabSalary Slip`
			WHERE docstatus < 2 AND start_date >= %s
		""", (get_first_day(today),))[0]
		payroll_mtd = flt(_pr[0]) or flt(_pr[1])
	except Exception:
		payroll_mtd = 0

	return {
		"kpis": [
			{"label": "Active Employees", "value": int(total_emp), "type": "count", "delta": 0},
			{"label": "Present Today", "value": int(present_today), "type": "count", "delta": 0},
			{"label": "Pending Leaves", "value": int(pending_leaves), "type": "count", "delta": 0},
			{"label": "Payroll MTD", "value": payroll_mtd, "type": "currency", "delta": 0},
		],
		"trend": attendance_trend,
		"breakdown": by_dept,
		"secondary": [],
	}


def _detect_user_type(user):
	"""Resolve which 'My Work' view to show based on user's highest-priority role."""
	roles = set(frappe.get_roles(user))
	if "HR Manager" in roles or "HR User" in roles:
		return "hr"
	if "Factory Management" in roles:
		return "production"
	if "Accounts Manager" in roles or "Accounts User" in roles:
		return "finance"
	# Sales User, Sales Manager, Purchase Manager, System Manager → sales view
	return "sales"


def _my_work_data(user, today, since, date_fmt, group_fmt, pw):
	month_start = get_first_day(today)
	user_type = _detect_user_type(user)

	if user_type == "hr":
		return _my_work_hr(user, today, since, date_fmt, group_fmt, month_start, pw)
	if user_type == "production":
		return _my_work_production(user, today, since, date_fmt, group_fmt, month_start, pw)
	if user_type == "finance":
		return _my_work_finance(user, today, since, date_fmt, group_fmt, month_start, pw)
	return _my_work_sales(user, today, since, date_fmt, group_fmt, month_start, pw)


# ── Sales user view ────────────────────────────────────────────────────────────

def _my_work_sales(user, today, since, date_fmt, group_fmt, month_start, pw):
	period_start, period_end = pw["period_start"], pw["period_end"]
	period_label = pw["period_label"]
	# ── Core billing metrics ───────────────────────────────────────────────────
	# Basis controlled by instabiz.overrides.billing_mode — dev mode reads
	# Sales Order (billing isn't live in ERP yet, so SI-based revenue always
	# read 0/wrong); prod mode reads Sales Invoice for real revenue-realization
	# accounting. "collected" always stays Sales Invoice/Payment Entry — it's a
	# real money-received concept with no Sales Order equivalent.
	dev_mode = is_dev_billing_mode()
	sales_dt = sales_doctype()
	sales_date = "transaction_date" if dev_mode else "posting_date"
	# Only 'Cancelled' excluded, not 'Closed' — CustomSalesOrder.STATUS_MAP maps
	# DB status 'Closed' to user-facing label 'Confirmed' (a real completed sale).
	sales_cond = "AND t.status != 'Cancelled'" if dev_mode else "AND t.is_return=0"
	outstanding_expr = sales_outstanding_expr("t")

	# Period-scoped (drives the headline KPI cards — daily/weekly/monthly).
	billing_row = frappe.db.sql(f"""
		SELECT
			COALESCE(SUM(grand_total), 0)               as rev,
			COUNT(*)                                     as invoice_count
		FROM `tab{sales_dt}` t
		WHERE docstatus=1 {sales_cond}
		AND {sales_date} BETWEEN %s AND %s
		AND custom_sales_person_user = %s
	""", (period_start, period_end, user), as_dict=True)[0]

	rev_period    = flt(billing_row.rev)
	invoice_count  = int(billing_row.invoice_count or 0)
	avg_invoice    = round(rev_period / invoice_count, 2) if invoice_count else 0

	# Always-calendar-month (target attainment + incentive slabs are a strictly
	# monthly concept — see ib_sales_incentives.py — so these stay MTD
	# regardless of the daily/weekly/monthly period selector above).
	rev_mtd = flt(frappe.db.sql(f"""
		SELECT COALESCE(SUM(grand_total), 0) FROM `tab{sales_dt}` t
		WHERE docstatus=1 {sales_cond}
		AND {sales_date} BETWEEN %s AND %s
		AND custom_sales_person_user = %s
	""", (month_start, today, user))[0][0])

	collected = flt(frappe.db.sql("""
		SELECT COALESCE(SUM(grand_total - outstanding_amount), 0)
		FROM `tabSales Invoice`
		WHERE docstatus=1 AND is_return=0
		AND posting_date BETWEEN %s AND %s
		AND custom_sales_person_user = %s
	""", (month_start, today, user))[0][0])

	# ── Orders (period-scoped) ─────────────────────────────────────────────────
	orders_mtd = int(flt(frappe.db.sql("""
		SELECT COUNT(*) FROM `tabSales Order`
		WHERE docstatus=1 AND transaction_date BETWEEN %s AND %s
		AND custom_sales_person_user = %s
	""", (period_start, period_end, user))[0][0]))

	# ── Advance collections (period-scoped; PEs linked to this user's SOs) ────
	# Sum per-reference-row allocated_amount, not the PE parent's paid_amount —
	# a PE split across multiple SOs would otherwise count its full paid_amount
	# once per joined reference row (same fan-out fix already applied in
	# payment_entry.py's _update_so_advance()).
	advance_collected = flt(frappe.db.sql("""
		SELECT COALESCE(SUM(per.allocated_amount), 0)
		FROM `tabPayment Entry` pe
		JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
		JOIN `tabSales Order` so ON so.name = per.reference_name
		WHERE pe.docstatus=1 AND pe.payment_type = 'Receive'
		AND per.reference_doctype = 'Sales Order'
		AND pe.posting_date BETWEEN %s AND %s
		AND so.custom_sales_person_user = %s
	""", (period_start, period_end, user))[0][0])

	# ── Target & commission (always monthly — see rev_mtd note above) ─────────
	target_row = frappe.db.sql("""
		SELECT target_amount FROM `tabIB Sales Target`
		WHERE sales_user = %s AND month = %s
	""", (user, str(month_start)), as_dict=True)
	target = flt(target_row[0]["target_amount"]) if target_row else 0
	# Attainment vs rev_mtd (dev-mode Sales Order basis), not collected —
	# matches the billing-mode basis used for rev_mtd above.
	tgt_pct = round(rev_mtd / target * 100, 1) if target else None

	commission, slab_label = 0.0, None
	try:
		from instabiz.instabiz.page.ib_sales_incentives.ib_sales_incentives import (
			_load_slabs, _get_slab_designation, _apply_slab,
		)
		# rev_mtd (dev-mode Sales Order basis), not collected — the real IB
		# Sales Incentives page (_individual_incentive) computes commission
		# on revenue for exactly this reason (billing isn't live, so
		# Sales-Invoice-based "collected" always reads 0 in dev mode). This
		# was passing `collected` here, so Analytics Hub's Me/Sales tabs
		# always showed zero commission regardless of real performance.
		commission, slab_label = _apply_slab(
			rev_mtd, tgt_pct, _get_slab_designation(user), _load_slabs()
		)
	except Exception:
		pass

	commission_per_invoice = round(commission / invoice_count, 2) if invoice_count else 0

	# ── Trend: my revenue by period ────────────────────────────────────────────
	trend = frappe.db.sql(f"""
		SELECT DATE_FORMAT({sales_date}, '{date_fmt}') as label,
			   DATE_FORMAT({sales_date}, '{group_fmt}') as grp,
			   COALESCE(SUM(grand_total), 0) as amount,
			   COUNT(*) as count
		FROM `tab{sales_dt}` t
		WHERE docstatus=1 {sales_cond} AND {sales_date} >= %s
		AND custom_sales_person_user = %s
		GROUP BY grp, label ORDER BY grp
	""", (since, user), as_dict=True)

	# ── Breakdown: my top customers MTD ────────────────────────────────────────
	by_customer = frappe.db.sql(f"""
		SELECT customer_name as label, COALESCE(SUM(grand_total), 0) as amount
		FROM `tab{sales_dt}` t
		WHERE docstatus=1 {sales_cond} AND {sales_date} BETWEEN %s AND %s
		AND custom_sales_person_user = %s
		GROUP BY customer_name ORDER BY amount DESC LIMIT 8
	""", (month_start, today, user), as_dict=True)

	# ── Customer outstanding list (all-time, for this user's customers) ────────
	cust_outstanding = frappe.db.sql(f"""
		SELECT
			customer_name as customer,
			COUNT(*)                                as invoice_count,
			COALESCE(SUM(grand_total), 0)            as total_invoiced,
			COALESCE(SUM(grand_total) - SUM({outstanding_expr}), 0) as total_collected,
			COALESCE(SUM({outstanding_expr}), 0)     as outstanding
		FROM `tab{sales_dt}` t
		WHERE docstatus=1 {sales_cond}
		AND custom_sales_person_user = %s
		GROUP BY customer_name
		HAVING outstanding > 0
		ORDER BY outstanding DESC
		LIMIT 20
	""", (user,), as_dict=True)

	# collection_pct per customer
	for r in cust_outstanding:
		ti = flt(r.total_invoiced)
		r.collection_pct = round(flt(r.total_collected) / ti * 100, 1) if ti else 0

	# ── Pending: open leads ────────────────────────────────────────────────────
	open_leads = frappe.db.sql("""
		SELECT name, lead_name, custom_status as status,
			   custom_next_follow_up_date as next_date, DATE(creation) as created
		FROM `tabLead`
		WHERE (lead_owner = %s OR owner = %s)
		AND (custom_status IS NULL OR custom_status NOT IN ('Lost', 'Converted'))
		ORDER BY custom_next_follow_up_date ASC, creation DESC LIMIT 15
	""", (user, user), as_dict=True)

	# ── Pending: open quotations ───────────────────────────────────────────────
	open_quotes = frappe.db.sql("""
		SELECT name, customer_name as customer, grand_total, status, valid_till, transaction_date
		FROM `tabQuotation`
		WHERE docstatus=1 AND status IN ('Pending', 'Open', 'Replied')
		AND custom_sales_person_user = %s
		ORDER BY valid_till ASC LIMIT 15
	""", (user,), as_dict=True)

	# ── Pending: open orders ───────────────────────────────────────────────────
	open_orders = frappe.db.sql("""
		SELECT name, customer_name as customer, grand_total, status,
			   transaction_date, custom_advance_paid as advance_paid
		FROM `tabSales Order`
		WHERE docstatus=1 AND status NOT IN ('Completed', 'Cancelled', 'Confirmed')
		AND custom_sales_person_user = %s
		ORDER BY transaction_date ASC LIMIT 15
	""", (user,), as_dict=True)

	# ── Pending: overdue invoices ──────────────────────────────────────────────
	# Dev mode has no real due_date pre-invoice — falls back to the order's
	# own date, same pattern as the Finance Dashboard/AR Aging report.
	overdue_si = frappe.db.sql(f"""
		SELECT name, customer_name as customer, {outstanding_expr} as outstanding_amount,
			   {sales_date} as due_date, DATEDIFF(%s, {sales_date}) as days_overdue
		FROM `tab{sales_dt}` t
		WHERE docstatus=1 {sales_cond} AND {sales_date} < %s
		AND custom_sales_person_user = %s
		HAVING outstanding_amount > 0
		ORDER BY due_date ASC LIMIT 15
	""", (today, today, user), as_dict=True)

	return {
		"kpis": [
			{"label": f"Revenue {period_label}", "value": rev_period,     "type": "currency",
			 "delta": round(tgt_pct - 100, 1) if tgt_pct else 0, "delta_label": "vs month target"},
			{"label": f"Invoices {period_label}", "value": invoice_count,  "type": "count",    "delta": 0},
			{"label": f"Advance {period_label}",  "value": advance_collected, "type": "currency", "delta": 0},
			{"label": "Commission (MTD)",         "value": commission,        "type": "currency", "delta": 0},
		],
		"trend": trend,
		"breakdown": by_customer,
		"pending": {
			"outstanding": cust_outstanding,
			"leads":       open_leads,
			"quotes":      open_quotes,
			"orders":      open_orders,
			"overdue":     overdue_si,
		},
		"meta": {
			"user_type": "sales",
			"target":             target,
			"collected":          collected,
			"tgt_pct":            tgt_pct,
			"slab":               slab_label,
			"invoice_count":      invoice_count,
			"orders_mtd":         orders_mtd,
			"avg_invoice":        avg_invoice,
			"commission_per_inv": commission_per_invoice,
		},
	}


# ── HR user view ───────────────────────────────────────────────────────────────

def _my_work_hr(user, today, since, date_fmt, group_fmt, month_start, pw):
	# Same as the main HR tab: Active Employees/Present Today/Pending Leaves
	# are point-in-time and Payroll MTD is inherently monthly — `pw` unused.
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
		) _c
	""", (today, today))[0][0])

	pending_leaves = flt(frappe.db.sql(
		"SELECT COUNT(*) FROM `tabLeave Application` WHERE status='Open' AND docstatus=1"
	)[0][0])

	payroll_mtd = flt(frappe.db.sql("""
		SELECT COALESCE(SUM(net_pay), 0) FROM `tabSalary Slip`
		WHERE docstatus < 2 AND start_date BETWEEN %s AND %s
	""", (month_start, today))[0][0])

	attendance_trend = frappe.db.sql(f"""
		SELECT DATE_FORMAT(attendance_date, '{date_fmt}') as label,
			   DATE_FORMAT(attendance_date, '{group_fmt}') as grp,
			   SUM(CASE WHEN status='Present' THEN 1 ELSE 0 END) as amount
		FROM `tabAttendance`
		WHERE attendance_date >= %s AND docstatus=1
		GROUP BY grp, label ORDER BY grp
	""", (since,), as_dict=True)

	by_dept = frappe.db.sql("""
		SELECT department as label, COUNT(*) as amount
		FROM `tabEmployee` WHERE status='Active' AND department IS NOT NULL
		GROUP BY department ORDER BY amount DESC LIMIT 10
	""", as_dict=True)

	pending_leave_list = frappe.db.sql("""
		SELECT la.name, e.employee_name, la.leave_type, la.from_date, la.to_date,
			   la.total_leave_days, la.status
		FROM `tabLeave Application` la
		LEFT JOIN `tabEmployee` e ON e.name = la.employee
		WHERE la.docstatus=1 AND la.status = 'Open'
		ORDER BY la.from_date ASC LIMIT 15
	""", as_dict=True)

	new_joiners = frappe.db.sql("""
		SELECT name, employee_name, designation, department, date_of_joining
		FROM `tabEmployee`
		WHERE status='Active' AND date_of_joining >= %s
		ORDER BY date_of_joining DESC LIMIT 10
	""", (month_start,), as_dict=True)

	exiting = frappe.db.sql("""
		SELECT name, employee_name, designation, department, relieving_date
		FROM `tabEmployee`
		WHERE relieving_date >= %s AND relieving_date <= %s
		ORDER BY relieving_date ASC LIMIT 10
	""", (today, frappe.utils.add_days(today, 30)), as_dict=True)

	absent_today_list = frappe.db.sql("""
		SELECT a.employee, e.employee_name, e.department
		FROM `tabAttendance` a
		LEFT JOIN `tabEmployee` e ON e.name = a.employee
		WHERE a.attendance_date = %s AND a.status = 'Absent' AND a.docstatus = 1
		ORDER BY e.department, e.employee_name LIMIT 15
	""", (today,), as_dict=True)

	return {
		"kpis": [
			{"label": "Active Employees", "value": int(total_emp), "type": "count", "delta": 0},
			{"label": "Present Today",    "value": int(present_today), "type": "count", "delta": 0},
			{"label": "Pending Leaves",   "value": int(pending_leaves), "type": "count", "delta": 0},
			{"label": "Payroll MTD",      "value": payroll_mtd, "type": "currency", "delta": 0},
		],
		"trend": attendance_trend,
		"breakdown": by_dept,
		"pending": {
			"leaves": pending_leave_list,
			"joiners": new_joiners,
			"exiting": exiting,
			"absent": absent_today_list,
		},
		"meta": {"user_type": "hr"},
	}


# ── Production user view ───────────────────────────────────────────────────────

def _my_work_production(user, today, since, date_fmt, group_fmt, month_start, pw):
	period_start = pw["period_start"]
	period_label = pw["period_label"]
	wo_active = flt(frappe.db.sql(
		"SELECT COUNT(*) FROM `tabIB Work Order` WHERE status NOT IN ('Completed','Cancelled')"
	)[0][0])
	wo_pending = flt(frappe.db.sql(
		"SELECT COUNT(*) FROM `tabIB Work Order` WHERE status = 'Pending'"
	)[0][0])
	wo_today = flt(frappe.db.sql(
		"SELECT COUNT(*) FROM `tabIB Work Order` WHERE status='Completed' AND COALESCE(completed_at, modified) >= %s",
		(period_start,)
	)[0][0])
	machines_active = flt(frappe.db.sql(
		"SELECT COUNT(*) FROM `tabIB Machine` WHERE status='Active'"
	)[0][0])

	wo_trend = frappe.db.sql(f"""
		SELECT DATE_FORMAT(COALESCE(completed_at, modified), '{date_fmt}') as label,
			   DATE_FORMAT(COALESCE(completed_at, modified), '{group_fmt}') as grp,
			   COUNT(*) as amount
		FROM `tabIB Work Order`
		WHERE status='Completed' AND COALESCE(completed_at, modified) >= %s
		GROUP BY grp, label ORDER BY grp
	""", (since,), as_dict=True)

	# Both queries below count/list each item's true CURRENT stage only, not
	# every stage it happens to have a non-Completed WO for.
	# auto_create_all_stage_wos() pre-creates one WO per stage in an item's
	# whole route up front, all Pending — the original "status NOT IN
	# (Completed, Cancelled)" filter counted/listed every future stage's
	# placeholder as if it were real, current work, same root cause as the
	# Production page's Stage-wise/Job Bundles/pipeline-card bugs fixed
	# 2026-08-06 in production.py (and the privileged _production_data()
	# view's by_stage above). Fixed by resolving each item's current stage
	# (first non-Completed in route order) and only counting/listing that one.
	_stage_wo_rows = frappe.db.sql("""
		SELECT name, item_code, stage, priority, status, machine, operator,
			   target_qty, completed_qty, started_at, order_sheet, order_sheet_item
		FROM `tabIB Work Order`
		WHERE status != 'Cancelled'
	""", as_dict=True)
	_stage_order = ["Coating", "Slitting", "Rewinding", "Cutting", "Packing"]  # RTD/Delivered collapsed out 2026-08-13
	_stage_rank = {s: i for i, s in enumerate(_stage_order)}
	_item_groups = {}
	for row in _stage_wo_rows:
		key = row.order_sheet_item or f"{row.order_sheet}::{row.item_code}"
		_item_groups.setdefault(key, []).append(row)
	_current_rows = []
	for wos in _item_groups.values():
		wos.sort(key=lambda r: _stage_rank.get(r.stage, 999))
		current = next((r for r in wos if r.status != "Completed"), None)
		if current:
			_current_rows.append(current)

	_stage_counts = {}
	for r in _current_rows:
		label = r.stage or "No Stage"
		_stage_counts[label] = _stage_counts.get(label, 0) + 1
	by_stage = sorted(
		[{"label": s, "amount": c} for s, c in _stage_counts.items()],
		key=lambda r: -r["amount"],
	)[:10]

	# Priority order fixed alongside this rewrite — the original SQL sorted by
	# FIELD(priority,'High','Medium','Low'), but IB Work Order's real Select
	# options are Urgent/High/Normal/Low (no "Medium"); every real WO's
	# priority fell through to FIELD's unmatched-value rank (0, sorts first),
	# so the ORDER BY was effectively a no-op. Now matches the real options.
	_priority_rank = {"Urgent": 0, "High": 1, "Normal": 2, "Low": 3}
	active_wos = sorted(
		[r for r in _current_rows if r.status in ("Pending", "In Progress")],
		key=lambda r: (_priority_rank.get(r.priority, 4), r.started_at or ""),
	)[:15]

	on_hold = frappe.db.sql("""
		SELECT name, item_code, stage, priority, machine
		FROM `tabIB Work Order` WHERE status='On Hold' LIMIT 10
	""", as_dict=True)

	return {
		"kpis": [
			{"label": "Active WOs",       "value": int(wo_active), "type": "count", "delta": 0},
			{"label": "Pending",          "value": int(wo_pending), "type": "count", "delta": 0},
			{"label": f"Completed {period_label}",  "value": int(wo_today), "type": "count", "delta": 0},
			{"label": "Machines Active",  "value": int(machines_active), "type": "count", "delta": 0},
		],
		"trend": wo_trend,
		"breakdown": by_stage,
		"pending": {"active": active_wos, "on_hold": on_hold},
		"meta": {"user_type": "production"},
	}


# ── Finance/Accounts user view ─────────────────────────────────────────────────

def _my_work_finance(user, today, since, date_fmt, group_fmt, month_start, pw):
	# Basis controlled by instabiz.overrides.billing_mode — was 100%
	# hardcoded to Sales/Purchase Invoice, so every figure here except the
	# real Payment Entry ones (collections_mtd/payments_mtd/recent_payments)
	# read zero (billing isn't live in ERP yet).
	period_start, period_end = pw["period_start"], pw["period_end"]
	period_label = pw["period_label"]
	dev_mode = is_dev_billing_mode()
	sales_dt = sales_doctype()
	purch_dt = purchase_doctype()
	sales_date = "transaction_date" if dev_mode else "posting_date"
	purch_date = "transaction_date" if dev_mode else "posting_date"
	# Only 'Cancelled' excluded, not 'Closed' — CustomSalesOrder.STATUS_MAP maps
	# DB status 'Closed' to user-facing label 'Confirmed' (a real completed sale).
	sales_cond = "AND t.status != 'Cancelled'" if dev_mode else "AND t.is_return=0"
	purch_cond = "AND t.status NOT IN ('Closed', 'Cancelled')" if dev_mode else "AND t.is_return=0"
	ar_expr = sales_outstanding_expr("t")
	ap_expr = purchase_outstanding_expr("t")

	ar_total = flt(frappe.db.sql(
		f"SELECT COALESCE(SUM({ar_expr}),0) FROM `tab{sales_dt}` t WHERE docstatus=1 {sales_cond}"
	)[0][0])
	ap_total = flt(frappe.db.sql(
		f"SELECT COALESCE(SUM({ap_expr}),0) FROM `tab{purch_dt}` t WHERE docstatus=1 {purch_cond}"
	)[0][0])
	collections_mtd = flt(frappe.db.sql("""
		SELECT COALESCE(SUM(paid_amount), 0) FROM `tabPayment Entry`
		WHERE docstatus=1 AND payment_type='Receive' AND posting_date BETWEEN %s AND %s
	""", (period_start, period_end))[0][0])
	payments_mtd = flt(frappe.db.sql("""
		SELECT COALESCE(SUM(paid_amount), 0) FROM `tabPayment Entry`
		WHERE docstatus=1 AND payment_type='Pay' AND posting_date BETWEEN %s AND %s
	""", (period_start, period_end))[0][0])

	rev_trend = frappe.db.sql(f"""
		SELECT DATE_FORMAT({sales_date}, '{date_fmt}') as label,
			   DATE_FORMAT({sales_date}, '{group_fmt}') as grp,
			   COALESCE(SUM(grand_total), 0) as amount
		FROM `tab{sales_dt}` t
		WHERE docstatus=1 {sales_cond} AND {sales_date} >= %s
		GROUP BY grp, label ORDER BY grp
	""", (since,), as_dict=True)

	overdue_by_cust = frappe.db.sql(f"""
		SELECT customer_name as label, COALESCE(SUM({ar_expr}), 0) as amount
		FROM `tab{sales_dt}` t
		WHERE docstatus=1 {sales_cond} AND {sales_date} < %s
		GROUP BY customer_name
		HAVING amount > 0
		ORDER BY amount DESC LIMIT 10
	""", (today,), as_dict=True)

	overdue_si = frappe.db.sql(f"""
		SELECT name, customer_name as customer, {ar_expr} as outstanding_amount,
			   {sales_date} as due_date, DATEDIFF(%s, {sales_date}) as days_overdue
		FROM `tab{sales_dt}` t
		WHERE docstatus=1 {sales_cond} AND {sales_date} < %s
		HAVING outstanding_amount > 0
		ORDER BY due_date ASC LIMIT 15
	""", (today, today), as_dict=True)

	overdue_pi = frappe.db.sql(f"""
		SELECT name, supplier_name as supplier, {ap_expr} as outstanding_amount,
			   {purch_date} as due_date, DATEDIFF(%s, {purch_date}) as days_overdue
		FROM `tab{purch_dt}` t
		WHERE docstatus=1 {purch_cond} AND {purch_date} < %s
		HAVING outstanding_amount > 0
		ORDER BY due_date ASC LIMIT 15
	""", (today, today), as_dict=True)

	recent_payments = frappe.db.sql("""
		SELECT name, payment_type, party_name as party, paid_amount,
			   reference_no, posting_date
		FROM `tabPayment Entry`
		WHERE docstatus=1 AND posting_date BETWEEN %s AND %s
		ORDER BY posting_date DESC, creation DESC LIMIT 15
	""", (period_start, period_end), as_dict=True)

	return {
		"kpis": [
			{"label": "Outstanding AR",            "value": ar_total,       "type": "currency", "delta": 0},
			{"label": "Outstanding AP",            "value": ap_total,       "type": "currency", "delta": 0},
			{"label": f"Collections {period_label}", "value": collections_mtd,"type": "currency", "delta": 0},
			{"label": f"Payments {period_label}",    "value": payments_mtd,   "type": "currency", "delta": 0},
		],
		"trend": rev_trend,
		"breakdown": overdue_by_cust,
		"pending": {
			"overdue_si": overdue_si,
			"overdue_pi": overdue_pi,
			"payments": recent_payments,
		},
		"meta": {"user_type": "finance"},
	}


def _finance_data(today, since, date_fmt, group_fmt, pw):
	# Basis controlled by instabiz.overrides.billing_mode — was 100%
	# hardcoded to Sales/Purchase Invoice, so this whole tab read zero
	# (billing isn't live in ERP yet).
	period_start, period_end = pw["period_start"], pw["period_end"]
	prev_start, prev_end = pw["prev_start"], pw["prev_end"]
	period_label = pw["period_label"]

	dev_mode = is_dev_billing_mode()
	sales_dt = sales_doctype()
	purch_dt = purchase_doctype()
	sales_date = "transaction_date" if dev_mode else "posting_date"
	# Only 'Cancelled' excluded, not 'Closed' — CustomSalesOrder.STATUS_MAP maps
	# DB status 'Closed' to user-facing label 'Confirmed' (a real completed sale).
	sales_cond = "AND t.status != 'Cancelled'" if dev_mode else "AND t.is_return=0"
	purch_cond = "AND t.status NOT IN ('Closed', 'Cancelled')" if dev_mode else ""
	ar_expr = sales_outstanding_expr("t")
	ap_expr = purchase_outstanding_expr("t")

	ar = flt(frappe.db.sql(
		f"SELECT COALESCE(SUM({ar_expr}),0) FROM `tab{sales_dt}` t WHERE docstatus=1 {sales_cond}"
	)[0][0])

	ap = flt(frappe.db.sql(
		f"SELECT COALESCE(SUM({ap_expr}),0) FROM `tab{purch_dt}` t WHERE docstatus=1 {purch_cond}"
	)[0][0])

	rev_period = flt(frappe.db.sql(f"""
		SELECT COALESCE(SUM(grand_total),0) FROM `tab{sales_dt}` t
		WHERE docstatus=1 {sales_cond} AND {sales_date} BETWEEN %s AND %s
	""", (period_start, period_end))[0][0])

	rev_prev = flt(frappe.db.sql(f"""
		SELECT COALESCE(SUM(grand_total),0) FROM `tab{sales_dt}` t
		WHERE docstatus=1 {sales_cond} AND {sales_date} BETWEEN %s AND %s
	""", (prev_start, prev_end))[0][0])

	rev_delta = round((rev_period - rev_prev) / rev_prev * 100, 1) if rev_prev else 0

	gst_period = flt(frappe.db.sql(f"""
		SELECT COALESCE(SUM(tx.tax_amount),0)
		FROM `tabSales Taxes and Charges` tx
		JOIN `tab{sales_dt}` t ON t.name=tx.parent AND tx.parenttype=%s
		WHERE t.docstatus=1 AND t.{sales_date} BETWEEN %s AND %s
		AND (tx.account_head LIKE '%%GST%%' OR tx.account_head LIKE '%%CGST%%'
			OR tx.account_head LIKE '%%IGST%%' OR tx.account_head LIKE '%%SGST%%')
	""", (sales_dt, period_start, period_end))[0][0])

	pl_trend = frappe.db.sql(f"""
		SELECT DATE_FORMAT({sales_date},'{date_fmt}') as label,
			   DATE_FORMAT({sales_date},'{group_fmt}') as grp,
			   COALESCE(SUM(grand_total),0) as amount
		FROM `tab{sales_dt}` t
		WHERE docstatus=1 {sales_cond} AND {sales_date} >= %s
		GROUP BY grp, label ORDER BY grp
	""", (since,), as_dict=True)

	overdue = frappe.db.sql(f"""
		SELECT customer_name as label, COALESCE(SUM({ar_expr}),0) as amount
		FROM `tab{sales_dt}` t
		WHERE docstatus=1 {sales_cond} AND {sales_date} < %s
		GROUP BY customer_name
		HAVING amount > 0
		ORDER BY amount DESC LIMIT 10
	""", (today,), as_dict=True)

	return {
		"kpis": [
			{"label": f"Revenue {period_label}", "value": rev_period, "type": "currency", "delta": rev_delta},
			{"label": "Outstanding AR", "value": ar, "type": "currency", "delta": 0},
			{"label": "Outstanding AP", "value": ap, "type": "currency", "delta": 0},
			{"label": f"GST Collected {period_label}", "value": gst_period, "type": "currency", "delta": 0},
		],
		"trend": pl_trend,
		"breakdown": overdue,
		"secondary": [],
	}


def _procurement_data(today, since, date_fmt, group_fmt, pw):
	# Basis controlled by instabiz.overrides.billing_mode, same as Finance tab —
	# dev mode reads Purchase Order (billing isn't live in ERP yet, PI-based
	# spend would read empty); prod mode reads real Purchase Invoice.
	period_start, period_end = pw["period_start"], pw["period_end"]
	prev_start, prev_end = pw["prev_start"], pw["prev_end"]
	period_label = pw["period_label"]

	dev_mode = is_dev_billing_mode()
	purch_dt = purchase_doctype()
	purch_date = "transaction_date" if dev_mode else "posting_date"
	purch_cond = "AND t.status NOT IN ('Closed', 'Cancelled')" if dev_mode else "AND t.is_return=0"
	ap_expr = purchase_outstanding_expr("t")

	spend_period = flt(frappe.db.sql(f"""
		SELECT COALESCE(SUM(grand_total),0) FROM `tab{purch_dt}` t
		WHERE docstatus=1 {purch_cond} AND {purch_date} BETWEEN %s AND %s
	""", (period_start, period_end))[0][0])

	spend_prev = flt(frappe.db.sql(f"""
		SELECT COALESCE(SUM(grand_total),0) FROM `tab{purch_dt}` t
		WHERE docstatus=1 {purch_cond} AND {purch_date} BETWEEN %s AND %s
	""", (prev_start, prev_end))[0][0])

	open_po = flt(frappe.db.sql("""
		SELECT COUNT(*) FROM `tabPurchase Order`
		WHERE docstatus=1 AND status NOT IN ('Completed','Cancelled','Closed')
	""")[0][0])

	pending_grn = flt(frappe.db.sql("""
		SELECT COUNT(*) FROM `tabPurchase Order`
		WHERE docstatus=1 AND status IN ('To Receive and Bill','To Receive')
	""")[0][0])

	ap = flt(frappe.db.sql(
		f"SELECT COALESCE(SUM({ap_expr}),0) FROM `tab{purch_dt}` t WHERE docstatus=1 {purch_cond}"
	)[0][0])

	trend = frappe.db.sql(f"""
		SELECT DATE_FORMAT({purch_date}, '{date_fmt}') as label,
			   DATE_FORMAT({purch_date}, '{group_fmt}') as grp,
			   COALESCE(SUM(grand_total),0) as amount,
			   COUNT(*) as count
		FROM `tab{purch_dt}` t
		WHERE docstatus=1 {purch_cond} AND {purch_date} >= %s
		GROUP BY grp, label ORDER BY grp
	""", (since,), as_dict=True)

	by_vendor = frappe.db.sql(f"""
		SELECT supplier_name as label, COALESCE(SUM(grand_total),0) as amount
		FROM `tab{purch_dt}` t
		WHERE docstatus=1 {purch_cond} AND {purch_date} BETWEEN %s AND %s
		GROUP BY supplier_name ORDER BY amount DESC LIMIT 10
	""", (period_start, period_end), as_dict=True)

	open_po_list = frappe.db.sql("""
		SELECT name, supplier_name, transaction_date, schedule_date, grand_total, status,
			   DATEDIFF(%s, schedule_date) as days_overdue
		FROM `tabPurchase Order`
		WHERE docstatus=1 AND status NOT IN ('Completed','Cancelled','Closed')
		ORDER BY schedule_date ASC LIMIT 15
	""", (today,), as_dict=True)

	overdue_pi = frappe.db.sql(f"""
		SELECT name, supplier_name as supplier, {ap_expr} as outstanding_amount,
			   {purch_date} as due_date, DATEDIFF(%s, {purch_date}) as days_overdue
		FROM `tab{purch_dt}` t
		WHERE docstatus=1 {purch_cond} AND {purch_date} < %s
		HAVING outstanding_amount > 0
		ORDER BY due_date ASC LIMIT 15
	""", (today, today), as_dict=True)

	return {
		"kpis": [
			{"label": f"Spend {period_label}", "value": spend_period, "type": "currency",
			 "delta": round((spend_period - spend_prev) / spend_prev * 100, 1) if spend_prev else 0},
			{"label": "Open POs", "value": int(open_po), "type": "count", "delta": 0},
			{"label": "Pending GRNs", "value": int(pending_grn), "type": "count", "delta": 0},
			{"label": "Outstanding AP", "value": ap, "type": "currency", "delta": 0},
		],
		"trend": trend,
		"breakdown": by_vendor,
		"pending": {
			"open_po": open_po_list,
			"overdue_pi": overdue_pi,
		},
	}


def _docs_order_data(user, privileged):
	"""Per-Sales-Order cross-module chain: Quotation → SO → DN → SI →
	Payment → Production stage → AR, one row per order. Sales User sees only
	their own orders; Sales Manager/Accounts Manager/Accounts User/System
	Manager see company-wide (most-recent-first, capped at 50 — this is a
	work-queue view, not a report). Chain always reads the real Sales
	Order/Delivery Note/Sales Invoice doctypes regardless of billing_mode —
	unlike the KPI tabs, a lifecycle tracker needs both SO and SI to exist as
	distinct stages, not whichever one billing_mode currently treats as
	"revenue"."""
	from instabiz.overrides.production import get_my_production_orders

	params = {}
	so_filter = ""
	if not privileged:
		so_filter = "AND so.custom_sales_person_user = %(user)s"
		params["user"] = user

	orders = frappe.db.sql(f"""
		SELECT so.name, so.customer_name, so.transaction_date, so.status,
			   so.grand_total, so.custom_advance_paid as advance_paid,
			   so.custom_sales_person_user, so.custom_sales_person
		FROM `tabSales Order` so
		WHERE so.docstatus=1 {so_filter}
		ORDER BY so.transaction_date DESC LIMIT 50
	""", params, as_dict=True)

	empty = {
		"kpis": [
			{"label": "Orders", "value": 0, "type": "count", "delta": 0},
			{"label": "Awaiting Dispatch", "value": 0, "type": "count", "delta": 0},
			{"label": "Awaiting Payment", "value": 0, "type": "count", "delta": 0},
			{"label": "Fully Paid", "value": 0, "type": "count", "delta": 0},
		],
		"trend": [], "breakdown": [],
		"pending": {"chain": []},
		"meta": {"chain_type": "order", "scoped": not privileged},
	}
	if not orders:
		return empty

	names = [o.name for o in orders]

	# Quotation → SO link lives on the child row (prevdoc_docname), set by the
	# Q→SO mapper — same field instabiz/overrides/sales_order.py already reads.
	q_rows = frappe.db.sql("""
		SELECT parent as so_name, prevdoc_docname as quotation
		FROM `tabSales Order Item`
		WHERE parent IN %(names)s AND prevdoc_docname IS NOT NULL AND prevdoc_docname != ''
		GROUP BY parent, prevdoc_docname
	""", {"names": names}, as_dict=True)
	q_map = {r.so_name: r.quotation for r in q_rows}

	# latest_name: picked per-SO in Python below (MySQL has no clean "value from
	# the max-date row" aggregate) — used to give the Docs tab's Dispatched/
	# Invoiced badges a real document to deep-link to instead of just a status
	# word. Multiple DNs/SIs can exist per SO; "most recent by posting date" is
	# the same most-recent-wins tie-break this app already uses elsewhere.
	dn_rows = frappe.db.sql("""
		SELECT dni.against_sales_order as so_name, dn.name as dn_name,
		       dn.docstatus, dn.posting_date
		FROM `tabDelivery Note Item` dni
		JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		WHERE dni.against_sales_order IN %(names)s AND dn.docstatus != 2
		GROUP BY dni.against_sales_order, dn.name
	""", {"names": names}, as_dict=True)
	dn_map = {}
	for r in dn_rows:
		existing = dn_map.get(r.so_name)
		dn_map[r.so_name] = {
			"any_submitted": max(r.docstatus, (existing or {}).get("any_submitted", 0)),
			"latest_name": r.dn_name if not existing or (r.posting_date or "") >= existing.get("_pd", "") else existing["latest_name"],
			"_pd": max(str(r.posting_date or ""), (existing or {}).get("_pd", "")),
		}

	si_rows = frappe.db.sql("""
		SELECT sii.sales_order as so_name, si.name as si_name,
		       si.docstatus, si.posting_date, si.outstanding_amount, si.grand_total
		FROM `tabSales Invoice Item` sii
		JOIN `tabSales Invoice` si ON si.name = sii.parent
		WHERE sii.sales_order IN %(names)s AND si.docstatus != 2
		GROUP BY sii.sales_order, si.name
	""", {"names": names}, as_dict=True)
	si_map = {}
	si_agg = {}
	for r in si_rows:
		existing = si_map.get(r.so_name)
		si_map[r.so_name] = {
			"any_submitted": max(r.docstatus, (existing or {}).get("any_submitted", 0)),
			"latest_name": r.si_name if not existing or (r.posting_date or "") >= existing.get("_pd", "") else existing["latest_name"],
			"_pd": max(str(r.posting_date or ""), (existing or {}).get("_pd", "")),
		}
		agg = si_agg.setdefault(r.so_name, {"outstanding": 0, "invoiced": 0})
		if r.docstatus == 1:
			agg["outstanding"] += flt(r.outstanding_amount)
			agg["invoiced"] += flt(r.grand_total)

	# sales_person_user=None (privileged) reuses the exact function/shape that
	# powers the sales-facing Production Tracker page — one source of truth
	# for pct/current_stage, can't drift from that page's numbers.
	prod_rows = get_my_production_orders(sales_person_user=(None if privileged else user), show_completed=1)
	prod_map = {r["sales_order"]: r for r in prod_rows}

	chain = []
	c_ordered = c_dispatched = c_invoiced = c_paid = 0
	for o in orders:
		dn = dn_map.get(o.name)
		si = si_map.get(o.name)
		si_totals = si_agg.get(o.name) or {}
		prod = prod_map.get(o.name)

		dn_submitted = bool(dn and dn.get("any_submitted") == 1)
		si_submitted = bool(si and si.get("any_submitted") == 1)
		invoiced = flt(si_totals.get("invoiced"))
		advance = flt(o.advance_paid)

		if si_submitted:
			# Real invoice AR.
			outstanding = flt(si_totals.get("outstanding"))
			payment_status = "Paid" if outstanding <= 0 else "Partial" if outstanding < invoiced else "Unpaid"
		else:
			# No SI yet (the normal case right now — billing isn't live,
			# everything's evaluated off Sales Order per instabiz.overrides.
			# billing_mode). Same formula as sales_outstanding_expr()'s
			# dev-mode branch: grand_total minus whatever advance has
			# actually been paid — was previously hardcoded to 0 here, so
			# every not-yet-invoiced order showed no outstanding at all.
			outstanding = max(flt(o.grand_total) - advance, 0)
			payment_status = "Paid" if outstanding <= 0 else "Partial" if advance > 0 else "Unpaid"

		chain.append({
			"sales_order": o.name,
			"customer": o.customer_name,
			"date": str(o.transaction_date) if o.transaction_date else None,
			"grand_total": flt(o.grand_total),
			"quotation": q_map.get(o.name),
			"dn_status": "Dispatched" if dn_submitted else ("Pending" if dn else "Not Created"),
			"dn_name": (dn or {}).get("latest_name"),
			"si_status": "Invoiced" if si_submitted else ("Pending" if si else "Not Created"),
			"si_name": (si or {}).get("latest_name"),
			"payment_status": payment_status,
			"outstanding": outstanding,
			"production_stage": (prod or {}).get("current_stage"),
			"production_pct": (prod or {}).get("pct"),
			"risk": (prod or {}).get("risk"),
			"sales_person": o.custom_sales_person or o.custom_sales_person_user,
		})

		if not dn_submitted:
			c_ordered += 1
		elif not si_submitted:
			c_dispatched += 1
		elif outstanding > 0:
			c_invoiced += 1
		else:
			c_paid += 1

	return {
		"kpis": [
			{"label": "Orders", "value": len(orders), "type": "count", "delta": 0},
			{"label": "Awaiting Dispatch", "value": c_ordered, "type": "count", "delta": 0},
			{"label": "Awaiting Payment", "value": c_invoiced, "type": "count", "delta": 0},
			{"label": "Fully Paid", "value": c_paid, "type": "count", "delta": 0},
		],
		"trend": [],
		"breakdown": [],
		"pending": {"chain": chain},
		"meta": {
			"chain_type": "order",
			"scoped": not privileged,
			# Company-wide view has no way to narrow to one rep otherwise —
			# only populated when privileged, since a scoped Sales User's
			# chain is already just their own orders.
			"sales_persons": sorted({c["sales_person"] for c in chain if privileged and c["sales_person"]}),
		},
	}


def _docs_hr_data():
	"""Company-wide HR request pipeline — Leave Application, IB Overtime
	Request, IB Full Final Settlement, Salary Slip — merged into one list so
	HR can see everything mid-flight in one place instead of checking 4
	separate list views. Each doctype keeps its own status vocabulary as-is
	(not normalized into a shared enum — HR already knows what "In Review"
	vs "Pending Approval" means per doctype)."""
	month_start = get_first_day(getdate(nowdate()))

	leave_rows = frappe.db.sql("""
		SELECT la.name, e.employee_name, 'Leave Application' as doctype,
			   la.leave_type as detail, la.status, la.modified
		FROM `tabLeave Application` la
		LEFT JOIN `tabEmployee` e ON e.name = la.employee
		WHERE la.docstatus IN (0,1) AND la.status = 'Open'
		ORDER BY la.modified DESC LIMIT 20
	""", as_dict=True)

	ot_rows = frappe.db.sql("""
		SELECT ot.name, e.employee_name, 'Overtime Request' as doctype,
			   CONCAT(ot.overtime_hours, ' hrs') as detail, ot.status, ot.modified
		FROM `tabIB Overtime Request` ot
		LEFT JOIN `tabEmployee` e ON e.name = ot.employee
		WHERE ot.status IN ('Draft','Pending Approval')
		ORDER BY ot.modified DESC LIMIT 20
	""", as_dict=True)

	ffs_rows = frappe.db.sql("""
		SELECT f.name, e.employee_name, 'Full & Final Settlement' as doctype,
			   CONCAT('₹', FORMAT(f.total_payable,0)) as detail, f.status, f.modified
		FROM `tabIB Full Final Settlement` f
		LEFT JOIN `tabEmployee` e ON e.name = f.employee
		WHERE f.status IN ('Draft','In Review','Approved')
		ORDER BY f.modified DESC LIMIT 20
	""", as_dict=True)

	slip_rows = frappe.db.sql("""
		SELECT s.name, e.employee_name, 'Salary Slip' as doctype,
			   CONCAT('₹', FORMAT(s.net_pay,0)) as detail,
			   CASE WHEN s.docstatus=1 THEN 'Submitted' ELSE 'Draft' END as status,
			   s.modified
		FROM `tabSalary Slip` s
		LEFT JOIN `tabEmployee` e ON e.name = s.employee
		WHERE s.docstatus IN (0,1) AND s.start_date >= %s
		ORDER BY s.modified DESC LIMIT 20
	""", (month_start,), as_dict=True)

	all_rows = list(leave_rows) + list(ot_rows) + list(ffs_rows) + list(slip_rows)
	all_rows.sort(key=lambda r: str(r.modified or ""), reverse=True)

	by_type = {}
	for r in all_rows:
		by_type[r.doctype] = by_type.get(r.doctype, 0) + 1

	return {
		"kpis": [
			{"label": "Pending Leave", "value": len(leave_rows), "type": "count", "delta": 0},
			{"label": "Pending Overtime", "value": len(ot_rows), "type": "count", "delta": 0},
			{"label": "F&F In Progress", "value": len(ffs_rows), "type": "count", "delta": 0},
			{"label": "Salary Slips (Open)", "value": len(slip_rows), "type": "count", "delta": 0},
		],
		"trend": [],
		"breakdown": [{"label": k, "amount": v} for k, v in sorted(by_type.items(), key=lambda x: -x[1])],
		"pending": {"chain": all_rows[:40]},
		"meta": {"chain_type": "hr"},
	}


# ── Non-privileged, content-aware tab views ──────────────────────────────────
# Shown instead of _inventory_data/_production_data/_hr_data/_finance_data
# when the caller doesn't hold any of _PRIVILEGED_ANALYTICS_ROLES. Never raw
# company-wide numbers — either scoped to the calling user's own work, or (for
# inventory) reduced to a plain in-stock/out-of-stock signal.

def _my_inventory_data():
	"""No real quantities or stock value — a Sales User needs to know whether
	they can promise an item right now, not the company's exact stock
	position. In/out status only."""
	total_items = int(flt(frappe.db.sql(
		"SELECT COUNT(DISTINCT item_code) FROM `tabBin`"
	)[0][0]))
	in_stock = int(flt(frappe.db.sql("""
		SELECT COUNT(*) FROM (
			SELECT item_code FROM `tabBin` GROUP BY item_code HAVING SUM(actual_qty) > 0
		) x
	""")[0][0]))
	out_of_stock = total_items - in_stock

	# Out-of-stock items first (most actionable before quoting), capped —
	# this is a quick signal list, not a full stock report (that's the Stock
	# Ledger / Live Stock Balance pages, which have real numbers by design
	# for the roles that need them).
	rows = frappe.db.sql("""
		SELECT b.item_code, i.item_name, SUM(b.actual_qty) as qty
		FROM `tabBin` b JOIN `tabItem` i ON i.name = b.item_code
		WHERE i.disabled = 0
		GROUP BY b.item_code, i.item_name
		ORDER BY qty ASC
		LIMIT 30
	""", as_dict=True)
	breakdown = [
		{"label": r.item_name or r.item_code, "status": "green" if flt(r.qty) > 0 else "red"}
		for r in rows
	]

	return {
		"kpis": [
			{"label": "Total SKUs", "value": total_items, "type": "count", "delta": 0},
			{"label": "In Stock", "value": in_stock, "type": "count", "delta": 0},
			{"label": "Out of Stock", "value": out_of_stock, "type": "count", "delta": 0},
		],
		"trend": [],
		"breakdown": breakdown,
		"meta": {"scoped": True, "user_type": "inventory_status"},
	}


def _my_production_status_data(user, pw):
	"""Production status of just this user's own Sales Orders — which stage
	each is in, or whether it's shipped. Reuses the same scoped query that
	powers the sales-facing Production Tracker page (item 110), so the two
	views can never drift apart."""
	from instabiz.overrides.production import get_my_production_orders

	orders = get_my_production_orders(sales_person_user=user, show_completed=1)

	in_flight = [o for o in orders if o["pct"] < 100]
	completed = [o for o in orders if o["pct"] >= 100]
	overdue = [o for o in orders if o.get("risk") == "overdue"]
	at_risk = [o for o in orders if o.get("risk") == "at-risk"]

	breakdown = [
		{"label": f"{o['sales_order']} — {o['customer']}", "amount": o["pct"]}
		for o in sorted(orders, key=lambda o: o["pct"])[:15]
	]

	return {
		"kpis": [
			{"label": "In Production", "value": len(in_flight), "type": "count", "delta": 0},
			{"label": "At Risk", "value": len(at_risk), "type": "count", "delta": 0},
			{"label": "Overdue", "value": len(overdue), "type": "count", "delta": 0},
			{"label": "Completed", "value": len(completed), "type": "count", "delta": 0},
		],
		"trend": [],
		"breakdown": breakdown,
		"meta": {"scoped": True, "user_type": "production_status"},
	}


def _my_personal_hr_data(user, today, since, date_fmt, group_fmt, month_start, pw):
	"""The employee's own HR self-service snapshot — leave balance, this
	period's attendance, their own pending leave requests, last payslip —
	never company-wide headcount/payroll (that's _hr_data, privileged-only)."""
	employee = frappe.db.get_value("Employee", {"user_id": user, "status": "Active"}, "name")
	if not employee:
		return {
			"kpis": [{"label": "No Employee Record", "value": 0, "type": "count", "delta": 0}],
			"trend": [], "breakdown": [],
			"meta": {"scoped": True, "user_type": "personal_hr"},
		}

	leave_rows = frappe.db.sql("""
		SELECT la.leave_type, la.total_leaves_allocated as allocated,
			   COALESCE(SUM(CASE WHEN app.status='Approved' AND app.docstatus=1
			   					  THEN app.total_leave_days ELSE 0 END), 0) as used
		FROM `tabLeave Allocation` la
		LEFT JOIN `tabLeave Application` app
			   ON app.employee = la.employee AND app.leave_type = la.leave_type
		WHERE la.employee = %(emp)s
		GROUP BY la.leave_type, la.total_leaves_allocated
	""", {"emp": employee}, as_dict=True)
	leave_balance = sum(flt(r.allocated) - flt(r.used) for r in leave_rows)
	leave_breakdown = [
		{"label": r.leave_type, "amount": round(flt(r.allocated) - flt(r.used), 1)}
		for r in leave_rows
	]

	present_days = int(flt(frappe.db.sql("""
		SELECT COUNT(*) FROM `tabAttendance`
		WHERE employee=%(emp)s AND status='Present' AND docstatus=1
		AND attendance_date BETWEEN %(start)s AND %(end)s
	""", {"emp": employee, "start": pw["period_start"], "end": pw["period_end"]})[0][0]))

	pending_leaves = int(flt(frappe.db.sql("""
		SELECT COUNT(*) FROM `tabLeave Application`
		WHERE employee=%(emp)s AND status='Open' AND docstatus IN (0,1)
	""", {"emp": employee})[0][0]))

	latest_slip = frappe.db.sql("""
		SELECT net_pay FROM `tabSalary Slip`
		WHERE employee=%(emp)s AND docstatus=1
		ORDER BY start_date DESC LIMIT 1
	""", {"emp": employee}, as_dict=True)
	last_net_pay = flt(latest_slip[0].net_pay) if latest_slip else 0

	trend = frappe.db.sql(f"""
		SELECT DATE_FORMAT(attendance_date, '{date_fmt}') as label,
			   DATE_FORMAT(attendance_date, '{group_fmt}') as grp,
			   COUNT(*) as amount
		FROM `tabAttendance`
		WHERE employee=%(emp)s AND status='Present' AND docstatus=1
		AND attendance_date >= %(since)s
		GROUP BY grp, label ORDER BY grp
	""", {"emp": employee, "since": since}, as_dict=True)

	return {
		"kpis": [
			{"label": "Leave Balance", "value": round(leave_balance, 1), "type": "count", "delta": 0},
			{"label": f"Present Days ({pw['period_label']})", "value": present_days, "type": "count", "delta": 0},
			{"label": "Pending Leave Requests", "value": pending_leaves, "type": "count", "delta": 0},
			{"label": "Last Net Pay", "value": last_net_pay, "type": "currency", "delta": 0},
		],
		"trend": trend,
		"breakdown": leave_breakdown,
		"meta": {"scoped": True, "user_type": "personal_hr"},
	}


def _my_finance_data(user, today, since, date_fmt, group_fmt, month_start, pw):
	"""This sales rep's own customers' outstanding and collections only — no
	AP (a Sales User has no business reason to see company payables) and no
	other reps' customers."""
	period_start, period_end = pw["period_start"], pw["period_end"]
	period_label = pw["period_label"]
	dev_mode = is_dev_billing_mode()
	sales_dt = sales_doctype()
	sales_date = "transaction_date" if dev_mode else "posting_date"
	sales_cond = "AND t.status != 'Cancelled'" if dev_mode else "AND t.is_return=0"
	ar_expr = sales_outstanding_expr("t")

	ar_total = flt(frappe.db.sql(f"""
		SELECT COALESCE(SUM({ar_expr}),0) FROM `tab{sales_dt}` t
		WHERE docstatus=1 {sales_cond} AND t.custom_sales_person_user = %s
	""", (user,))[0][0])

	collections_mtd = flt(frappe.db.sql(f"""
		SELECT COALESCE(SUM(per.allocated_amount), 0)
		FROM `tabPayment Entry` pe
		JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
		JOIN `tab{sales_dt}` t ON t.name = per.reference_name
		WHERE pe.docstatus=1 AND pe.payment_type='Receive'
		AND per.reference_doctype = %s
		AND pe.posting_date BETWEEN %s AND %s
		AND t.custom_sales_person_user = %s
	""", (sales_dt, period_start, period_end, user))[0][0])

	trend = frappe.db.sql(f"""
		SELECT DATE_FORMAT({sales_date}, '{date_fmt}') as label,
			   DATE_FORMAT({sales_date}, '{group_fmt}') as grp,
			   COALESCE(SUM(grand_total), 0) as amount
		FROM `tab{sales_dt}` t
		WHERE docstatus=1 {sales_cond} AND {sales_date} >= %s AND t.custom_sales_person_user = %s
		GROUP BY grp, label ORDER BY grp
	""", (since, user), as_dict=True)

	overdue_by_cust = frappe.db.sql(f"""
		SELECT customer_name as label, COALESCE(SUM({ar_expr}), 0) as amount
		FROM `tab{sales_dt}` t
		WHERE docstatus=1 {sales_cond} AND {sales_date} < %s AND t.custom_sales_person_user = %s
		GROUP BY customer_name
		HAVING amount > 0
		ORDER BY amount DESC LIMIT 10
	""", (today, user), as_dict=True)

	return {
		"kpis": [
			{"label": "My Outstanding AR", "value": ar_total, "type": "currency", "delta": 0},
			{"label": f"My Collections {period_label}", "value": collections_mtd, "type": "currency", "delta": 0},
		],
		"trend": trend,
		"breakdown": overdue_by_cust,
		"meta": {"scoped": True, "user_type": "my_finance"},
	}


def _my_procurement_data():
	"""No spend/AP figures — a non-procurement role (e.g. Sales User, HR) has
	no business reason to see vendor spend or payables. Status-only signal,
	same spirit as _my_inventory_data's in-stock/out-of-stock reduction."""
	open_po = int(flt(frappe.db.sql("""
		SELECT COUNT(*) FROM `tabPurchase Order`
		WHERE docstatus=1 AND status NOT IN ('Completed','Cancelled','Closed')
	""")[0][0]))
	pending_grn = int(flt(frappe.db.sql("""
		SELECT COUNT(*) FROM `tabPurchase Order`
		WHERE docstatus=1 AND status IN ('To Receive and Bill','To Receive')
	""")[0][0]))

	by_status = frappe.db.sql("""
		SELECT status as label, COUNT(*) as amount
		FROM `tabPurchase Order`
		WHERE docstatus=1 AND status NOT IN ('Completed','Cancelled','Closed')
		GROUP BY status ORDER BY amount DESC
	""", as_dict=True)

	return {
		"kpis": [
			{"label": "Open POs", "value": open_po, "type": "count", "delta": 0},
			{"label": "Pending GRNs", "value": pending_grn, "type": "count", "delta": 0},
		],
		"trend": [],
		"breakdown": by_status,
		"meta": {"scoped": True, "user_type": "procurement_status"},
	}
