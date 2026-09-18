import frappe
from frappe.utils import nowdate, getdate, get_first_day, add_months, flt
from erpnext.accounts.utils import get_fiscal_year

from instabiz.overrides.billing_mode import is_dev_billing_mode, sales_doctype, sales_outstanding_expr
from instabiz.overrides.utils import build_multi_token_where


def get_context(context):
	context.no_cache = 1


def _ch_privileged(user):
	roles = frappe.get_roles(user)
	return "System Manager" in roles or "Sales Manager" in roles or "Accounts Manager" in roles


@frappe.whitelist()
def get_customer_health(search=None, territory=None, limit=50, offset=0):
	today = getdate(nowdate())
	month_start = get_first_day(today)
	three_months = get_first_day(add_months(today, -3))
	year_start = getdate(get_fiscal_year(today, as_dict=True).year_start_date)

	limit = int(limit)
	offset = int(offset)
	user = frappe.session.user
	privileged = _ch_privileged(user)

	# Basis controlled by instabiz.overrides.billing_mode — dev mode reads
	# Sales Order (billing isn't live yet, SI-based health always reads
	# empty); prod mode reads real Sales Invoice. Sales Order has no
	# is_return and no posting_date (falls back to transaction_date).
	dev_mode = is_dev_billing_mode()
	doctype  = sales_doctype()
	date_field = "transaction_date" if dev_mode else "posting_date"
	outstanding_expr = sales_outstanding_expr("t")
	return_cond = "" if dev_mode else "AND t.is_return=0"

	conditions = ["c.disabled = 0"]
	params = []

	if not privileged:
		conditions.append("c.custom_sales_person_user = %s")
		params.append(user)

	search_cond, search_params = build_multi_token_where(["c.customer_name", "c.name"], search)
	if search_cond:
		conditions.append(search_cond)
		params += search_params

	if territory:
		conditions.append("c.territory = %s")
		params.append(territory)

	where = " AND ".join(conditions)

	rows = frappe.db.sql(f"""
		SELECT
			c.name as customer,
			c.customer_name,
			c.territory,
			c.customer_group,
			COALESCE(c.custom_sales_person, c.custom_sales_person_user) as sales_person,
			COALESCE(ar.outstanding, 0) as outstanding,
			COALESCE(mtd.revenue, 0) as mtd_revenue,
			COALESCE(ytd.revenue, 0) as ytd_revenue,
			COALESCE(q3.revenue, 0) as q3_revenue,
			last_si.last_order as last_order_date,
			COALESCE(oq.open_quotes, 0) as open_quotes,
			COALESCE(oq.quote_value, 0) as quote_value
		FROM `tabCustomer` c
		LEFT JOIN (
			SELECT customer, SUM({outstanding_expr}) as outstanding
			FROM `tab{doctype}` t
			WHERE t.docstatus=1 AND {outstanding_expr} > 0
			GROUP BY customer
		) ar ON ar.customer = c.name
		LEFT JOIN (
			SELECT customer, SUM(grand_total) as revenue
			FROM `tab{doctype}` t
			WHERE t.docstatus=1 {return_cond}
			AND t.{date_field} BETWEEN %s AND %s
			GROUP BY customer
		) mtd ON mtd.customer = c.name
		LEFT JOIN (
			SELECT customer, SUM(grand_total) as revenue
			FROM `tab{doctype}` t
			WHERE t.docstatus=1 {return_cond}
			AND t.{date_field} BETWEEN %s AND %s
			GROUP BY customer
		) ytd ON ytd.customer = c.name
		LEFT JOIN (
			SELECT customer, SUM(grand_total) as revenue
			FROM `tab{doctype}` t
			WHERE t.docstatus=1 {return_cond}
			AND t.{date_field} BETWEEN %s AND %s
			GROUP BY customer
		) q3 ON q3.customer = c.name
		LEFT JOIN (
			SELECT customer, MAX(t.{date_field}) as last_order
			FROM `tab{doctype}` t
			WHERE t.docstatus=1 {return_cond}
			GROUP BY customer
		) last_si ON last_si.customer = c.name
		LEFT JOIN (
			SELECT party_name as customer, COUNT(*) as open_quotes, COALESCE(SUM(grand_total),0) as quote_value
			FROM `tabQuotation`
			WHERE docstatus=1 AND quotation_to='Customer'
			AND status NOT IN ('Ordered','Lost','Cancelled','Expired','Confirmed')
			GROUP BY party_name
		) oq ON oq.customer = c.name
		WHERE {where}
		ORDER BY ar.outstanding DESC, mtd.revenue DESC
		LIMIT %s OFFSET %s
	""", [month_start, today, year_start, today, three_months, today] + params + [limit, offset], as_dict=True)

	# Health score per customer (current page)
	for r in rows:
		score = 100
		days_since = (today - getdate(r.last_order_date)).days if r.last_order_date else 999
		if days_since > 90:
			score -= 30
		elif days_since > 30:
			score -= 10
		if flt(r.outstanding) > flt(r.q3_revenue) * 0.5:
			score -= 25
		if flt(r.mtd_revenue) == 0:
			score -= 20
		r.health_score = max(0, min(100, score))
		r.days_since_order = days_since if r.last_order_date else None

	total_count = flt(frappe.db.sql(f"""
		SELECT COUNT(*) FROM `tabCustomer` c WHERE {where}
	""", params)[0][0])

	# Aggregate KPIs across ALL matching customers (not just this page)
	agg = frappe.db.sql(f"""
		SELECT
			COALESCE(SUM(ar.outstanding), 0) as total_outstanding,
			COALESCE(SUM(mtd.revenue), 0) as total_mtd,
			COALESCE(SUM(ytd.revenue), 0) as total_ytd
		FROM `tabCustomer` c
		LEFT JOIN (
			SELECT customer, SUM({outstanding_expr}) as outstanding
			FROM `tab{doctype}` t
			WHERE t.docstatus=1 AND {outstanding_expr} > 0
			GROUP BY customer
		) ar ON ar.customer = c.name
		LEFT JOIN (
			SELECT customer, SUM(grand_total) as revenue
			FROM `tab{doctype}` t
			WHERE t.docstatus=1 {return_cond}
			AND t.{date_field} BETWEEN %s AND %s
			GROUP BY customer
		) mtd ON mtd.customer = c.name
		LEFT JOIN (
			SELECT customer, SUM(grand_total) as revenue
			FROM `tab{doctype}` t
			WHERE t.docstatus=1 {return_cond}
			AND t.{date_field} BETWEEN %s AND %s
			GROUP BY customer
		) ytd ON ytd.customer = c.name
		WHERE {where}
	""", [month_start, today, year_start, today] + params, as_dict=True)

	agg_outstanding = flt(agg[0].total_outstanding) if agg else 0
	agg_mtd = flt(agg[0].total_mtd) if agg else 0
	agg_ytd = flt(agg[0].total_ytd) if agg else 0

	# Health counts from score distribution on the current page
	# (Full scan would be expensive; we approximate from the page)
	agg_healthy = sum(1 for r in rows if r.health_score >= 80)
	agg_at_risk = sum(1 for r in rows if r.health_score < 50)

	territories = frappe.db.sql("""
		SELECT DISTINCT territory FROM `tabCustomer`
		WHERE territory IS NOT NULL AND territory != ''
		ORDER BY territory
	""", as_list=True)

	return {
		"customers": rows,
		"total": int(total_count),
		"territories": [t[0] for t in territories],
		"agg_outstanding": agg_outstanding,
		"agg_mtd": agg_mtd,
		"agg_ytd": agg_ytd,
		"agg_healthy": agg_healthy,
		"agg_at_risk": agg_at_risk,
	}
