import frappe
from frappe.utils import nowdate, getdate, flt, cint

from instabiz.overrides.billing_mode import sales_total_expr, is_dev_billing_mode, sales_doctype, sales_outstanding_expr
from instabiz.overrides.utils import build_multi_token_where


def get_context(context):
	context.no_cache = 1


def _is_privileged(user):
	privileged = {"System Manager", "Sales Manager", "Accounts User", "Accounts Manager"}
	return bool(privileged & set(frappe.get_roles(user)))


@frappe.whitelist()
def get_collections_data(search=None, filter_sp=None, overdue_only=False, offset=0, limit=50,
						  min_days_overdue=0, min_outstanding=0):
	# Basis controlled by instabiz.overrides.billing_mode — dev mode reads
	# Sales Order (billing isn't live yet, SI-based collections always reads
	# empty); prod mode reads real Sales Invoice. Sales Order has no is_return
	# and no due_date (falls back to transaction_date, same as ib_ar_aging).
	# Advance/collected-in-90d stay Payment-Entry-based always — real cash
	# movement has no dev/prod distinction.
	user = frappe.session.user
	today = getdate(nowdate())
	privileged = _is_privileged(user)
	overdue_only = cint(overdue_only)
	offset, limit = int(offset), int(limit)
	min_days_overdue = cint(min_days_overdue)
	min_outstanding = flt(min_outstanding)
	dev_mode = is_dev_billing_mode()
	doctype  = sales_doctype()
	date_field = "transaction_date" if dev_mode else "due_date"
	outstanding_expr = sales_outstanding_expr("t")

	conditions = ["t.docstatus=1", f"{outstanding_expr} > 0"]
	if not dev_mode:
		conditions.append("t.is_return=0")
	params = []

	if not privileged:
		conditions.append("t.custom_sales_person_user = %s")
		params.append(user)
	elif filter_sp:
		conditions.append("t.custom_sales_person_user = %s")
		params.append(filter_sp)

	search_cond, search_params = build_multi_token_where(["t.customer_name", "t.name"], search)
	if search_cond:
		conditions.append(search_cond)
		params += search_params

	if overdue_only:
		conditions.append(f"t.{date_field} < %s")
		params.append(str(today))

	where = " AND ".join(conditions)

	# Customer-level filters (days overdue / min outstanding) apply to the
	# GROUPED aggregate, not a raw invoice row — HAVING, not WHERE.
	having_conds = []
	having_params = []
	if min_days_overdue:
		having_conds.append("days_overdue >= %s")
		having_params.append(min_days_overdue)
	if min_outstanding:
		having_conds.append("outstanding >= %s")
		having_params.append(min_outstanding)
	having_sql = ("HAVING " + " AND ".join(having_conds)) if having_conds else ""

	# Real customer count behind this filter, unbounded — used for pagination
	# and so the KPI cards below don't have to be derived from a capped page.
	customer_total = int(frappe.db.sql(f"""
		SELECT COUNT(*) FROM (
			SELECT t.customer,
				   COALESCE(SUM({outstanding_expr}), 0) as outstanding,
				   DATEDIFF(%s, MIN(t.{date_field})) as days_overdue
			FROM `tab{doctype}` t
			WHERE {where}
			GROUP BY t.customer
			{having_sql}
		) sub
	""", [str(today)] + params + having_params)[0][0])

	# Customer-level summary (one page)
	customers = frappe.db.sql(f"""
		SELECT
			t.custom_sales_person_user as sp_user,
			COALESCE(u.full_name, t.custom_sales_person_user) as sp_name,
			t.customer,
			t.customer_name,
			COUNT(t.name) as invoice_count,
			COALESCE(SUM({outstanding_expr}), 0) as outstanding,
			COALESCE(SUM({sales_total_expr('t')}), 0) as billed,
			MIN(t.{date_field}) as earliest_due,
			DATEDIFF(%s, MIN(t.{date_field})) as days_overdue
		FROM `tab{doctype}` t
		LEFT JOIN `tabUser` u ON u.name = t.custom_sales_person_user
		WHERE {where}
		GROUP BY t.customer, t.customer_name, t.custom_sales_person_user, u.full_name
		{having_sql}
		ORDER BY outstanding DESC
		LIMIT %s OFFSET %s
	""", [str(today)] + params + having_params + [limit, offset], as_dict=True)

	customer_names = [c.customer for c in customers]
	invoices = []
	advance_map = {}
	collected_map = {}

	if customer_names:
		placeholders = ",".join(["%s"] * len(customer_names))

		# Outstanding invoices (for drill-down)
		inv_conds = ["t.docstatus=1", f"{outstanding_expr} > 0",
					 f"t.customer IN ({placeholders})"]
		if not dev_mode:
			inv_conds.append("t.is_return=0")
		inv_params = list(customer_names)
		if not privileged and not filter_sp:
			inv_conds.append("t.custom_sales_person_user = %s")
			inv_params.append(user)
		elif filter_sp:
			inv_conds.append("t.custom_sales_person_user = %s")
			inv_params.append(filter_sp)
		inv_where = " AND ".join(inv_conds)
		invoices = frappe.db.sql(f"""
			SELECT t.name, t.customer, t.{date_field} as posting_date, t.{date_field} as due_date,
				   {sales_total_expr('t')} AS grand_total, {outstanding_expr} as outstanding_amount,
				   DATEDIFF(%s, t.{date_field}) as days_overdue
			FROM `tab{doctype}` t
			WHERE {inv_where}
			ORDER BY t.customer, t.{date_field} ASC
			LIMIT 1000
		""", [str(today)] + inv_params, as_dict=True)

		# Advances (unlinked PEs) — batch query, not correlated subquery
		advances = frappe.db.sql(f"""
			SELECT pe.party as customer, SUM(pe.unallocated_amount) as advance
			FROM `tabPayment Entry` pe
			WHERE pe.party_type='Customer' AND pe.payment_type='Receive'
			  AND pe.docstatus=1 AND pe.unallocated_amount > 0
			  AND pe.party IN ({placeholders})
			GROUP BY pe.party
		""", customer_names, as_dict=True)
		advance_map = {a.customer: flt(a.advance) for a in advances}

		# Collections in last 90 days — batch query
		cutoff = frappe.utils.add_days(str(today), -90)
		collected = frappe.db.sql(f"""
			SELECT pe.party as customer, SUM(pe.paid_amount) as collected_90d
			FROM `tabPayment Entry` pe
			WHERE pe.party_type='Customer' AND pe.payment_type='Receive'
			  AND pe.docstatus=1
			  AND pe.posting_date >= %s
			  AND pe.party IN ({placeholders})
			GROUP BY pe.party
		""", [str(cutoff)] + list(customer_names), as_dict=True)
		collected_map = {c.customer: flt(c.collected_90d) for c in collected}

	for c in customers:
		c.advance = advance_map.get(c.customer, 0)
		c.net_outstanding = max(0, flt(c.outstanding) - flt(c.advance))
		c.collected_90d = collected_map.get(c.customer, 0)

	# ── KPI totals — unbounded, independent of the LIMIT/OFFSET page above ────
	# Previously these were summed from just the current (or first-200) page of
	# `customers`, silently understating every KPI once matching customers
	# exceeded the page size (confirmed live: 448 real customers vs a 200 cap,
	# total_outstanding read ~18M short of the real ~43.8Cr).
	total_outstanding = flt(frappe.db.sql(f"""
		SELECT COALESCE(SUM({outstanding_expr}), 0) FROM `tab{doctype}` t WHERE {where}
	""", params)[0][0])

	overdue_count = int(frappe.db.sql(f"""
		SELECT COUNT(*) FROM (
			SELECT t.customer FROM `tab{doctype}` t
			WHERE {where}
			GROUP BY t.customer
			HAVING DATEDIFF(%s, MIN(t.{date_field})) > 0
		) sub
	""", [str(today)] + params)[0][0])

	total_advance = flt(frappe.db.sql(f"""
		SELECT COALESCE(SUM(pe.unallocated_amount), 0)
		FROM `tabPayment Entry` pe
		WHERE pe.party_type='Customer' AND pe.payment_type='Receive'
		  AND pe.docstatus=1 AND pe.unallocated_amount > 0
		  AND pe.party IN (SELECT DISTINCT t.customer FROM `tab{doctype}` t WHERE {where})
	""", params)[0][0])

	collected_90d_total = flt(frappe.db.sql(f"""
		SELECT COALESCE(SUM(pe.paid_amount), 0)
		FROM `tabPayment Entry` pe
		WHERE pe.party_type='Customer' AND pe.payment_type='Receive'
		  AND pe.docstatus=1 AND pe.posting_date >= %s
		  AND pe.party IN (SELECT DISTINCT t.customer FROM `tab{doctype}` t WHERE {where})
	""", [str(frappe.utils.add_days(str(today), -90))] + params)[0][0])

	return {
		"doctype": doctype,
		"dev_mode": dev_mode,
		"customers": customers,
		"customer_total": customer_total,
		"invoices": invoices,
		"kpis": {
			"total_outstanding": total_outstanding,
			"total_advance": total_advance,
			"net_outstanding": total_outstanding - total_advance,
			"customer_count": customer_total,
			"overdue_count": overdue_count,
			"collected_90d": collected_90d_total,
		},
		"privileged": privileged,
	}


@frappe.whitelist()
def get_sales_users():
	if not _is_privileged(frappe.session.user):
		frappe.throw("Not permitted")
	doctype = sales_doctype()
	outstanding_expr = sales_outstanding_expr("t")
	users = frappe.db.sql(f"""
		SELECT DISTINCT t.custom_sales_person_user as user,
			   COALESCE(u.full_name, t.custom_sales_person_user) as full_name
		FROM `tab{doctype}` t
		LEFT JOIN `tabUser` u ON u.name = t.custom_sales_person_user
		WHERE t.docstatus=1 AND {outstanding_expr} > 0
		  AND t.custom_sales_person_user IS NOT NULL AND t.custom_sales_person_user != ''
		ORDER BY full_name
	""", as_dict=True)
	return users
