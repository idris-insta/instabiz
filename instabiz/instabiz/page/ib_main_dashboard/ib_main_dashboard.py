import frappe
from frappe.utils import add_days, date_diff, flt, getdate, nowdate

from instabiz.overrides.billing_mode import (
	is_dev_billing_mode,
	sales_doctype,
	sales_outstanding_expr,
	sales_total_expr,
)

ROLES = [
	"System Manager",
	"Sales Manager",
	"Sales User",
	"Accounts Manager",
	"Accounts User",
	"Factory Management",
]

LOCATIONS = ("MAHARASHTRA", "GUJARAT", "CHENNAI")


def get_context(context):
	context.no_cache = 1


def _period(from_date, to_date):
	"""Return (from, to, prev_from, prev_to) — previous window is the same length
	immediately before, so a 7-day view compares against the 7 days before it
	instead of always against last calendar month."""
	to_date = getdate(to_date or nowdate())
	from_date = getdate(from_date or to_date.replace(day=1))
	if from_date > to_date:
		from_date, to_date = to_date, from_date
	span = date_diff(to_date, from_date) + 1
	prev_to = add_days(from_date, -1)
	prev_from = add_days(prev_to, -(span - 1))
	return from_date, to_date, prev_from, prev_to


def _bucket(from_date, to_date):
	"""Chart granularity — a year of daily points is unreadable, a week of
	monthly points is a single bar."""
	span = date_diff(to_date, from_date) + 1
	if span <= 31:
		return "day"
	if span <= 120:
		return "week"
	return "month"


def _bucket_sql(field, bucket):
	if bucket == "day":
		return f"DATE_FORMAT({field}, '%%d %%b')", f"DATE({field})"
	if bucket == "week":
		return f"CONCAT('W', WEEK({field}, 3))", f"YEARWEEK({field}, 3)"
	return f"DATE_FORMAT({field}, '%%b %%y')", f"DATE_FORMAT({field}, '%%Y-%%m')"


@frappe.whitelist()
def get_dashboard_data(from_date=None, to_date=None, location=None, sales_person=None):
	# The page nav restricts by role but the RPC is callable directly — same
	# gap already closed on the finance/procurement dashboards.
	frappe.only_for(ROLES)
	from instabiz.overrides.own_data import locked_user

	from_date, to_date, prev_from, prev_to = _period(from_date, to_date)
	dev_mode = is_dev_billing_mode()
	sales_dt = sales_doctype()
	date_field = "transaction_date" if dev_mode else "posting_date"
	total_expr = sales_total_expr("t")
	ar_expr = sales_outstanding_expr("t")

	# Only 'Cancelled' excluded in dev mode — 'Closed' maps to the user-facing
	# label 'Confirmed' (a real completed sale), see CustomSalesOrder.STATUS_MAP.
	cond = "AND t.status != 'Cancelled'" if dev_mode else "AND t.is_return = 0"
	params = {}
	location = (location or "").strip().upper()
	if location in LOCATIONS:
		cond += " AND t.custom_location = %(location)s"
		params["location"] = location
	else:
		location = ""

	locked = locked_user()
	if locked:  # a plain Sales User always sees their own figures, never the company's
		sales_person = locked
	if sales_person:
		cond += " AND t.custom_sales_person_user = %(sales_person)s"
		params["sales_person"] = sales_person

	def total(start, end):
		return flt(
			frappe.db.sql(
				f"""SELECT COALESCE(SUM({total_expr}), 0) FROM `tab{sales_dt}` t
				WHERE t.docstatus = 1 {cond} AND t.{date_field} BETWEEN %(start)s AND %(end)s""",
				{**params, "start": start, "end": end},
			)[0][0]
		)

	revenue = total(from_date, to_date)
	revenue_prev = total(prev_from, prev_to)
	rev_delta = round((revenue - revenue_prev) / revenue_prev * 100, 1) if revenue_prev else None

	orders = frappe.db.sql(
		f"""SELECT COUNT(*) c, COALESCE(SUM({total_expr}), 0) v FROM `tab{sales_dt}` t
		WHERE t.docstatus = 1 {cond} AND t.{date_field} BETWEEN %(start)s AND %(end)s""",
		{**params, "start": from_date, "end": to_date},
		as_dict=True,
	)[0]
	orders_prev = flt(
		frappe.db.sql(
			f"""SELECT COUNT(*) FROM `tab{sales_dt}` t
			WHERE t.docstatus = 1 {cond} AND t.{date_field} BETWEEN %(start)s AND %(end)s""",
			{**params, "start": prev_from, "end": prev_to},
		)[0][0]
	)
	ord_delta = round((orders.c - orders_prev) / orders_prev * 100, 1) if orders_prev else None

	# ── Outstanding (open, whole book — not period-scoped) ───────────────────
	ar = flt(
		frappe.db.sql(
			f"SELECT COALESCE(SUM({ar_expr}), 0) FROM `tab{sales_dt}` t WHERE t.docstatus = 1 {cond}",
			params,
		)[0][0]
	)
	overdue = flt(
		frappe.db.sql(
			f"""SELECT COALESCE(SUM({ar_expr}), 0) FROM `tab{sales_dt}` t
			WHERE t.docstatus = 1 {cond} AND t.{date_field} < %(cut)s""",
			{**params, "cut": add_days(getdate(nowdate()), -30)},
		)[0][0]
	)

	# ── Open orders / quotations (live pipeline) ─────────────────────────────
	so_cond, so_params = _doc_cond(location, sales_person)
	open_so = frappe.db.sql(
		f"""SELECT COUNT(*) c, COALESCE(SUM({total_expr}), 0) v FROM `tabSales Order` t
		WHERE t.docstatus = 1 AND t.status NOT IN ('Completed','Cancelled','Closed','Confirmed') {so_cond}""",
		so_params,
		as_dict=True,
	)[0]
	q_cond, q_params = _doc_cond(location, sales_person)
	quotes = frappe.db.sql(
		f"""SELECT COUNT(*) c, COALESCE(SUM(t.grand_total), 0) v FROM `tabQuotation` t
		WHERE t.docstatus = 1
		AND t.status NOT IN ('Ordered','Lost','Cancelled','Expired','Confirmed') {q_cond}""",
		q_params,
		as_dict=True,
	)[0]

	# ── Dispatches in period ────────────────────────────────────────────────
	dn_cond, dn_params = _doc_cond(location, sales_person)
	dispatch = frappe.db.sql(
		f"""SELECT COUNT(*) c, COALESCE(SUM(t.grand_total), 0) v FROM `tabDelivery Note` t
		WHERE t.docstatus = 1 AND t.is_return = 0 AND t.posting_date BETWEEN %(start)s AND %(end)s {dn_cond}""",
		{**dn_params, "start": from_date, "end": to_date},
		as_dict=True,
	)[0]
	pending_dn = flt(frappe.db.sql("SELECT COUNT(*) FROM `tabDelivery Note` WHERE docstatus = 0")[0][0])

	# ── Collections in period (real cash, Payment Entry) ─────────────────────
	pe_cond, pe_params = "", {"start": from_date, "end": to_date}
	if sales_person:
		pe_cond = " AND c.custom_sales_person_user = %(sales_person)s"
		pe_params["sales_person"] = sales_person
	collections = flt(
		frappe.db.sql(
			f"""SELECT COALESCE(SUM(pe.paid_amount), 0) FROM `tabPayment Entry` pe
			LEFT JOIN `tabCustomer` c ON c.name = pe.party
			WHERE pe.docstatus = 1 AND pe.payment_type = 'Receive' AND pe.party_type = 'Customer'
			AND pe.posting_date BETWEEN %(start)s AND %(end)s {pe_cond}""",
			pe_params,
		)[0][0]
	)

	# ── Low / zero stock (reorder level, same rule as reorder_alert.py) ──────
	low_stock = 0
	try:
		wh_cond, wh_params = "", {}
		if location:
			wh_cond = " AND b.warehouse LIKE %(wh)s"
			wh_params["wh"] = f"%{location} - IB"
		low_stock = flt(
			frappe.db.sql(
				f"""SELECT COUNT(DISTINCT b.item_code) FROM `tabBin` b
				INNER JOIN `tabItem Reorder` r ON r.parent = b.item_code AND r.warehouse = b.warehouse
				WHERE r.warehouse_reorder_level > 0 AND b.actual_qty <= r.warehouse_reorder_level {wh_cond}""",
				wh_params,
			)[0][0]
		)
	except Exception:
		low_stock = 0

	# ── Trend ───────────────────────────────────────────────────────────────
	bucket = _bucket(from_date, to_date)
	label_expr, group_expr = _bucket_sql(f"t.{date_field}", bucket)
	trend = frappe.db.sql(
		f"""SELECT {label_expr} label, {group_expr} bk,
			COALESCE(SUM({total_expr}), 0) amount, COUNT(*) cnt
		FROM `tab{sales_dt}` t
		WHERE t.docstatus = 1 {cond} AND t.{date_field} BETWEEN %(start)s AND %(end)s
		GROUP BY bk, label ORDER BY bk""",
		{**params, "start": from_date, "end": to_date},
		as_dict=True,
	)

	# 6-month sparkline for the revenue KPI — independent of the picked period
	spark = frappe.db.sql(
		f"""SELECT COALESCE(SUM({total_expr}), 0) amount
		FROM `tab{sales_dt}` t
		WHERE t.docstatus = 1 {cond}
		AND t.{date_field} >= DATE_SUB(%(today)s, INTERVAL 6 MONTH)
		GROUP BY DATE_FORMAT(t.{date_field}, '%%Y-%%m')
		ORDER BY DATE_FORMAT(t.{date_field}, '%%Y-%%m')""",
		{**params, "today": getdate(nowdate())},
		as_dict=True,
	)

	top_customers = frappe.db.sql(
		f"""SELECT t.customer, t.customer_name, COALESCE(SUM({total_expr}), 0) total, COUNT(*) cnt
		FROM `tab{sales_dt}` t
		WHERE t.docstatus = 1 {cond} AND t.{date_field} BETWEEN %(start)s AND %(end)s
		GROUP BY t.customer, t.customer_name ORDER BY total DESC LIMIT 8""",
		{**params, "start": from_date, "end": to_date},
		as_dict=True,
	)

	by_location = frappe.db.sql(
		f"""SELECT COALESCE(NULLIF(t.custom_location, ''), 'Not set') label,
			COALESCE(SUM({total_expr}), 0) total
		FROM `tab{sales_dt}` t
		WHERE t.docstatus = 1 {cond} AND t.{date_field} BETWEEN %(start)s AND %(end)s
		GROUP BY label ORDER BY total DESC""",
		{**params, "start": from_date, "end": to_date},
		as_dict=True,
	)

	by_person = []
	if not locked:
		by_person = frappe.db.sql(
			f"""SELECT COALESCE(NULLIF(t.custom_sales_person, ''), t.custom_sales_person_user) label,
				t.custom_sales_person_user user, COALESCE(SUM({total_expr}), 0) total, COUNT(*) cnt
			FROM `tab{sales_dt}` t
			WHERE t.docstatus = 1 {cond} AND t.{date_field} BETWEEN %(start)s AND %(end)s
			AND COALESCE(t.custom_sales_person_user, '') != ''
			GROUP BY label, user ORDER BY total DESC LIMIT 10""",
			{**params, "start": from_date, "end": to_date},
			as_dict=True,
		)

	recent = frappe.db.sql(
		f"""SELECT t.name, t.customer_name, t.{date_field} posting_date,
			{total_expr} grand_total, {ar_expr} outstanding_amount, t.status, t.custom_location
		FROM `tab{sales_dt}` t
		WHERE t.docstatus = 1 {cond}
		ORDER BY t.{date_field} DESC, t.creation DESC LIMIT 10""",
		params,
		as_dict=True,
	)

	return {
		"meta": {
			"sales_dt": sales_dt,
			"date_field": date_field,
			"dev_mode": dev_mode,
			"from_date": str(from_date),
			"to_date": str(to_date),
			"prev_from": str(prev_from),
			"prev_to": str(prev_to),
			"bucket": bucket,
			"location": location,
			"sales_person": sales_person or "",
			"locked": bool(locked),
			"collections_all_locations": bool(location),
		},
		"revenue": revenue,
		"revenue_prev": revenue_prev,
		"rev_delta": rev_delta,
		"orders": int(orders.c or 0),
		"order_value": flt(orders.v),
		"ord_delta": ord_delta,
		"ar": ar,
		"ar_overdue": overdue,
		"open_so": int(open_so.c or 0),
		"open_so_value": flt(open_so.v),
		"quotes": int(quotes.c or 0),
		"quote_value": flt(quotes.v),
		"dispatch_count": int(dispatch.c or 0),
		"dispatch_value": flt(dispatch.v),
		"pending_dn": int(pending_dn),
		"collections": collections,
		"low_stock": int(low_stock),
		"trend": trend,
		"spark": [flt(r.amount) for r in spark],
		"top_customers": top_customers,
		"by_location": by_location,
		"by_person": by_person,
		"recent": recent,
	}


def _doc_cond(location, sales_person):
	"""Location / sales-person filter for a doctype that always carries both
	custom fields (Quotation, Sales Order, Delivery Note)."""
	cond, params = "", {}
	if location:
		cond += " AND t.custom_location = %(location)s"
		params["location"] = location
	if sales_person:
		cond += " AND t.custom_sales_person_user = %(sales_person)s"
		params["sales_person"] = sales_person
	return cond, params
