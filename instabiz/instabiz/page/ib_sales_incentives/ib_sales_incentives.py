import frappe
from frappe.utils import nowdate, getdate, get_first_day, get_last_day, add_months, flt

from instabiz.overrides.billing_mode import is_dev_billing_mode, sales_doctype, sales_outstanding_expr


def get_context(context):
	context.no_cache = 1


def _load_slabs():
	"""Return {designation: [sorted slabs]} from IB Incentive Slab."""
	rows = frappe.db.get_all(
		"IB Incentive Slab",
		filters={"is_active": 1},
		fields=["designation", "slab_label", "from_pct", "to_pct", "commission_pct"],
		order_by="designation, from_pct asc",
	)
	out = {}
	for r in rows:
		out.setdefault(r.designation, []).append(r)
	return out


def _is_manager():
	roles = set(frappe.get_roles())
	return "Sales Manager" in roles or "System Manager" in roles


def _get_slab_designation(user):
	"""Map a user to 'Sales Manager' or 'Sales User' based on their Frappe roles."""
	roles = set(frappe.get_roles(user))
	return "Sales Manager" if "Sales Manager" in roles else "Sales User"


def _apply_slab(amount, pct, designation, slabs_by_desig):
	"""Return (commission_amount, slab_label) for the given achievement %.

	`amount` is the commission base — order value (grand_total), not cash
	collected. Sales Manager/PE access is gated separately (see billing_mode
	and payment_entry.py), so custom_advance_paid — and therefore "collected"
	— stays at 0 for most reps regardless of real sales activity; keying
	commission off it made the payout always compute to zero.
	"""
	if pct is None or pct < 0:
		return 0.0, None
	candidates = slabs_by_desig.get(designation) or slabs_by_desig.get("Sales User") or []
	for slab in candidates:
		lo = flt(slab.from_pct)
		hi = flt(slab.to_pct)
		if pct >= lo and (hi == 0 or pct < hi):
			commission = flt(amount) * flt(slab.commission_pct) / 100
			return round(commission, 2), slab.slab_label
	return 0.0, None


def _load_team_map():
	"""Return {user: {team_name, team_leader}} from Lead Sales Team."""
	rows = frappe.db.sql(
		"""
		SELECT lstm.user, lst.name AS team_name, lst.team_leader
		FROM `tabLead Sales Team Member` lstm
		INNER JOIN `tabLead Sales Team` lst ON lst.name = lstm.parent
		""",
		as_dict=True,
	)
	return {r.user: {"team_name": r.team_name, "team_leader": r.team_leader} for r in rows}


@frappe.whitelist()
def get_sales_reps_for_targets(month=None):
	"""All active Sales Users with team, current month target, last month target, MTD collected."""
	if not _is_manager():
		frappe.throw(frappe._("Not permitted"), frappe.PermissionError)
	from frappe.utils import get_first_day, get_last_day, getdate, nowdate as _now, add_months

	month_first = get_first_day(getdate(month) if month else getdate(_now()))
	month_last  = get_last_day(month_first)
	prev_first  = get_first_day(add_months(month_first, -1))

	team_map = _load_team_map()

	users = frappe.db.sql(
		"""
		SELECT DISTINCT u.name AS user, u.full_name
		FROM `tabUser` u
		INNER JOIN `tabHas Role` hr ON hr.parent = u.name
		WHERE hr.role = 'Sales User' AND u.enabled = 1 AND u.name != 'Administrator'
		ORDER BY u.full_name
		""",
		as_dict=True,
	)

	def _target_map(mf):
		return {
			t.sales_user: flt(t.target_amount)
			for t in frappe.db.get_all(
				"IB Sales Target",
				filters={"month": mf},
				fields=["sales_user", "target_amount"],
			)
		}

	targets      = _target_map(month_first)
	prev_targets = _target_map(prev_first)

	# Basis controlled by instabiz.overrides.billing_mode — dev mode reads
	# Sales Order (billing isn't live yet, SI-based collected always reads
	# empty); prod mode reads real Sales Invoice. Sales Order has no
	# is_return and no posting_date (falls back to transaction_date).
	dev_mode = is_dev_billing_mode()
	doctype  = sales_doctype()
	date_field = "transaction_date" if dev_mode else "posting_date"
	outstanding_expr = sales_outstanding_expr("t")
	return_cond = "" if dev_mode else "AND is_return = 0"

	# MTD collected for each rep this month
	collected_rows = frappe.db.sql(
		f"""
		SELECT custom_sales_person_user AS sp_user,
			   COALESCE(SUM(grand_total) - SUM({outstanding_expr}), 0) AS collected,
			   COALESCE(SUM(grand_total), 0) AS revenue
		FROM `tab{doctype}` t
		WHERE docstatus = 1 {return_cond}
		  AND {date_field} BETWEEN %s AND %s
		  AND custom_sales_person_user IS NOT NULL AND custom_sales_person_user != ''
		GROUP BY custom_sales_person_user
		""",
		(month_first, month_last),
		as_dict=True,
	)
	collected_map = {r.sp_user: {"collected": flt(r.collected), "revenue": flt(r.revenue)} for r in collected_rows}

	result = []
	for u in users:
		team_info = team_map.get(u.user, {})
		perf = collected_map.get(u.user, {"collected": 0, "revenue": 0})
		cur_target  = targets.get(u.user, 0)
		prev_target = prev_targets.get(u.user, 0)
		collected   = perf["collected"]
		pct = round(collected / cur_target * 100) if cur_target else None
		result.append({
			"sp_user":     u.user,
			"sp_name":     u.full_name or u.user,
			"team_name":   team_info.get("team_name") or "",
			"target":      cur_target,
			"prev_target": prev_target,
			"collected":   collected,
			"revenue":     perf["revenue"],
			"pct":         pct,
		})

	result.sort(key=lambda r: (r["team_name"] or "\xff", r["sp_name"]))
	return result


@frappe.whitelist()
def get_sales_person_options():
	"""Active Sales Users for the incentives-page filter dropdown (name + team only, no calc)."""
	if not _is_manager():
		frappe.throw(frappe._("Not permitted"), frappe.PermissionError)
	team_map = _load_team_map()
	users = frappe.db.sql(
		"""
		SELECT DISTINCT u.name AS user, u.full_name
		FROM `tabUser` u
		INNER JOIN `tabHas Role` hr ON hr.parent = u.name
		WHERE hr.role = 'Sales User' AND u.enabled = 1 AND u.name != 'Administrator'
		ORDER BY u.full_name
		""",
		as_dict=True,
	)
	out = []
	for u in users:
		team_info = team_map.get(u.user, {})
		out.append({"user": u.user, "name": u.full_name or u.user, "team_name": team_info.get("team_name") or ""})
	out.sort(key=lambda r: (r["team_name"] or "\xff", r["name"]))
	return out


ALL_REPS = "__all__"


@frappe.whitelist()
def get_incentives_data(month=None, sales_person=None):
	"""Incentive calc only runs once a selection is made — page starts blank
	otherwise. Sales User is locked to their own number always. Sales Manager+
	picks either one rep (separately) or ALL_REPS (collectively, team table)."""
	today = getdate(nowdate())
	month_date = getdate(month) if month else today
	month_start = get_first_day(month_date)
	month_end = get_last_day(month_date)

	# Non-managers can only ever calculate their own incentive, regardless of
	# what sales_person the client sends — page now grants Sales User access,
	# so this guards against one rep pulling another rep's commission via the API.
	if not _is_manager():
		sales_person = frappe.session.user

	if not sales_person:
		return {"month": str(month_start), "selected": False}

	if sales_person == ALL_REPS:
		if not _is_manager():
			frappe.throw(frappe._("Not permitted"), frappe.PermissionError)
		data = _team_incentives(month_start, month_end)
	else:
		data = _individual_incentive(sales_person, month_start, month_end)

	data["month"] = str(month_start)
	data["selected"] = True
	return data


def _individual_incentive(sales_person, month_start, month_end):
	slabs_by_desig = _load_slabs()
	team_map = _load_team_map()

	# Basis controlled by instabiz.overrides.billing_mode — see
	# get_sales_reps_for_targets above for rationale.
	dev_mode = is_dev_billing_mode()
	doctype  = sales_doctype()
	date_field = "transaction_date" if dev_mode else "posting_date"
	outstanding_expr = sales_outstanding_expr("t")
	return_cond = "" if dev_mode else "AND t.is_return=0"

	# ── Selected rep's billing for the month ──────────────────────────────────
	rows = frappe.db.sql(f"""
		SELECT
			t.custom_sales_person_user as sp_user,
			COALESCE(u.full_name, t.custom_sales_person_user) as sp_name,
			COUNT(t.name) as invoice_count,
			COALESCE(SUM(t.grand_total), 0) as revenue,
			COALESCE(SUM({outstanding_expr}), 0) as outstanding,
			COALESCE(SUM(t.grand_total) - SUM({outstanding_expr}), 0) as collected
		FROM `tab{doctype}` t
		LEFT JOIN `tabUser` u ON u.name = t.custom_sales_person_user
		WHERE t.docstatus=1 {return_cond}
		AND t.{date_field} BETWEEN %s AND %s
		AND t.custom_sales_person_user = %s
		GROUP BY t.custom_sales_person_user, u.full_name
	""", (month_start, month_end, sales_person), as_dict=True)

	if rows:
		row = rows[0]
	else:
		full_name = frappe.db.get_value("User", sales_person, "full_name") or sales_person
		row = frappe._dict(
			sp_user=sales_person, sp_name=full_name,
			invoice_count=0, revenue=0, outstanding=0, collected=0,
		)

	target = flt(frappe.db.get_value(
		"IB Sales Target", {"sales_user": sales_person, "month": month_start}, "target_amount"
	) or 0)
	row.target = target
	# Achievement % and commission are computed on order value (revenue), not
	# cash collected — see _apply_slab docstring for why.
	row.pct = round(flt(row.revenue) / target * 100, 1) if target else None
	row.gap = max(0, target - flt(row.revenue)) if target else None
	row.collection_pct = round(flt(row.collected) / flt(row.revenue) * 100, 1) if row.revenue else 0

	desig = _get_slab_designation(row.sp_user)
	row.slab_designation = desig
	commission, slab_label = _commission(row, desig, slabs_by_desig, month_start, month_end)
	row.commission = commission
	row.slab_earned = slab_label

	team_info = team_map.get(row.sp_user, {})
	row.team_name = team_info.get("team_name") or ""
	row.team_leader = team_info.get("team_leader") or ""

	# ── This rep's own 6-month trend ──────────────────────────────────────────
	trend = frappe.db.sql(f"""
		SELECT
			DATE_FORMAT(t.{date_field},'%%b %%Y') as label,
			DATE_FORMAT(t.{date_field},'%%Y-%%m') as ym,
			COALESCE(SUM(t.grand_total) - SUM({outstanding_expr}),0) as collected
		FROM `tab{doctype}` t
		WHERE t.docstatus=1 {return_cond}
		AND t.custom_sales_person_user = %s
		AND t.{date_field} >= DATE_SUB(%s, INTERVAL 5 MONTH)
		GROUP BY ym, label
		ORDER BY ym
	""", (sales_person, month_start), as_dict=True)

	# ── This rep's top 10 customers for the month ─────────────────────────────
	top_customers = frappe.db.sql(f"""
		SELECT t.customer_name,
			   COALESCE(SUM(t.grand_total) - SUM({outstanding_expr}), 0) as collected
		FROM `tab{doctype}` t
		WHERE t.docstatus=1 {return_cond}
		AND t.{date_field} BETWEEN %s AND %s
		AND t.custom_sales_person_user = %s
		GROUP BY t.customer_name
		ORDER BY collected DESC LIMIT 10
	""", (month_start, month_end, sales_person), as_dict=True)

	return {"mode": "individual", "rep": row, "trend": trend, "top_customers": top_customers}


def _team_incentives(month_start, month_end):
	"""Collective view — every rep with billing or a target this month, grouped
	by team, plus team totals and a top-3-reps 6-month trend. Manager only."""
	slabs_by_desig = _load_slabs()
	team_map = _load_team_map()

	dev_mode = is_dev_billing_mode()
	doctype  = sales_doctype()
	date_field = "transaction_date" if dev_mode else "posting_date"
	outstanding_expr = sales_outstanding_expr("t")
	return_cond = "" if dev_mode else "AND t.is_return=0"

	by_sp = frappe.db.sql(f"""
		SELECT
			t.custom_sales_person_user as sp_user,
			COALESCE(u.full_name, t.custom_sales_person_user) as sp_name,
			COUNT(t.name) as invoice_count,
			COALESCE(SUM(t.grand_total), 0) as revenue,
			COALESCE(SUM({outstanding_expr}), 0) as outstanding,
			COALESCE(SUM(t.grand_total) - SUM({outstanding_expr}), 0) as collected
		FROM `tab{doctype}` t
		LEFT JOIN `tabUser` u ON u.name = t.custom_sales_person_user
		WHERE t.docstatus=1 {return_cond}
		AND t.{date_field} BETWEEN %s AND %s
		AND t.custom_sales_person_user IS NOT NULL
		AND t.custom_sales_person_user != ''
		GROUP BY t.custom_sales_person_user, u.full_name
		ORDER BY revenue DESC
	""", (month_start, month_end), as_dict=True)

	targets = frappe.db.sql("""
		SELECT sales_user, target_amount, month
		FROM `tabIB Sales Target`
		WHERE month BETWEEN %s AND %s
	""", (month_start, month_end), as_dict=True)
	target_map = {t.sales_user: flt(t.target_amount) for t in targets}

	# Include reps with a target but no invoices this month (visible as zero-billing)
	billed_users = {r.sp_user for r in by_sp}
	for user, amt in target_map.items():
		if user not in billed_users:
			full_name = frappe.db.get_value("User", user, "full_name") or user
			by_sp.append(frappe._dict(
				sp_user=user, sp_name=full_name,
				invoice_count=0, revenue=0, outstanding=0, collected=0,
			))

	for row in by_sp:
		target = target_map.get(row.sp_user, 0)
		row.target = target
		# Achievement % and commission are computed on order value (revenue),
		# not cash collected — see _apply_slab docstring for why.
		row.pct = round(flt(row.revenue) / target * 100, 1) if target else None
		row.gap = max(0, target - flt(row.revenue)) if target else None
		row.collection_pct = round(flt(row.collected) / flt(row.revenue) * 100, 1) if row.revenue else 0

		desig = _get_slab_designation(row.sp_user)
		row.slab_designation = desig
		commission, slab_label = _commission(row, desig, slabs_by_desig, month_start, month_end)
		row.commission = commission
		row.slab_earned = slab_label

		team_info = team_map.get(row.sp_user, {})
		row.team_name = team_info.get("team_name") or ""
		row.team_leader = team_info.get("team_leader") or ""

	by_sp.sort(key=lambda r: (r.team_name or "\xff", -flt(r.collected)))

	total_revenue = sum(flt(r.revenue) for r in by_sp)
	total_target = sum(r.target for r in by_sp)
	total_collected = sum(flt(r.collected) for r in by_sp)
	total_commission = sum(flt(r.commission) for r in by_sp)

	# Fetch top 3 SP users first — MariaDB doesn't support LIMIT in IN-subquery
	top3_rows = frappe.db.sql(f"""
		SELECT custom_sales_person_user FROM `tab{doctype}` t
		WHERE t.docstatus=1 {return_cond} AND t.{date_field} BETWEEN %s AND %s
		AND custom_sales_person_user IS NOT NULL AND custom_sales_person_user != ''
		GROUP BY custom_sales_person_user ORDER BY SUM(grand_total) DESC LIMIT 3
	""", (month_start, month_end), as_list=True)
	top3 = [r[0] for r in top3_rows]

	if top3:
		placeholders = ",".join(["%s"] * len(top3))
		trend = frappe.db.sql(f"""
			SELECT
				t.custom_sales_person_user as sp_user,
				COALESCE(u.full_name, t.custom_sales_person_user) as sp_name,
				DATE_FORMAT(t.{date_field},'%%b %%Y') as label,
				DATE_FORMAT(t.{date_field},'%%Y-%%m') as ym,
				COALESCE(SUM(t.grand_total) - SUM({outstanding_expr}),0) as collected
			FROM `tab{doctype}` t
			LEFT JOIN `tabUser` u ON u.name = t.custom_sales_person_user
			WHERE t.docstatus=1 {return_cond}
			AND t.custom_sales_person_user IN ({placeholders})
			AND t.{date_field} >= DATE_SUB(%s, INTERVAL 5 MONTH)
			GROUP BY sp_user, sp_name, ym, label
			ORDER BY ym, collected DESC
		""", top3 + [month_start], as_dict=True)
	else:
		trend = []

	top_customers = frappe.db.sql(f"""
		SELECT t.custom_sales_person_user as sp_user,
			   t.customer_name,
			   COALESCE(SUM(t.grand_total) - SUM({outstanding_expr}), 0) as collected
		FROM `tab{doctype}` t
		WHERE t.docstatus=1 {return_cond}
		AND t.{date_field} BETWEEN %s AND %s
		AND t.custom_sales_person_user IS NOT NULL
		GROUP BY t.custom_sales_person_user, t.customer_name
		ORDER BY collected DESC LIMIT 20
	""", (month_start, month_end), as_dict=True)

	return {
		"mode": "team",
		"by_sp": by_sp,
		"total_revenue": total_revenue,
		"total_target": total_target,
		"total_collected": total_collected,
		"total_commission": total_commission,
		"team_pct": round(total_revenue / total_target * 100, 1) if total_target else None,
		"trend": trend,
		"top_customers": top_customers,
	}


def _commission(row, desig, slabs_by_desig, month_start, month_end):
	"""Incentive from the person's own net sales on their IB Incentive Scale
	(COMM ACC slabs); falls back to the older target-% slabs when no scale applies."""
	from instabiz.overrides.incentive_scale import scale_incentive
	incentive, scale, net = scale_incentive(row.sp_user, month_start, month_end)
	if scale:
		row.net_sale = net
		return round(incentive, 2), f"{scale} · net ₹{frappe.utils.fmt_money(net, 0)}"
	return _apply_slab(row.revenue, row.pct, desig, slabs_by_desig)
