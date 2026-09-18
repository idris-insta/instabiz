"""IB Daily Sales Report — per-rep operational snapshot for a single day."""
import frappe
from frappe import _
from frappe.utils import flt, getdate, get_first_day

from instabiz.overrides.ib_status import stored_statuses


def execute(filters=None):
	filters = filters or {}
	date = getdate(filters.get("date") or frappe.utils.today())
	territory = filters.get("territory")
	month_start = get_first_day(date)

	reps = _get_reps(date, territory)
	data = _build_rows(date, month_start, territory, reps)
	columns = _columns()
	return columns, data, None, _chart(data, filters), _summary(data, date, month_start)


# ── Columns ───────────────────────────────────────────────────────────────────

def _columns():
	return [
		{"label": _("Sales Person"),      "fieldname": "sales_person",   "fieldtype": "Data",     "width": 180},
		{"label": _("New Leads"),         "fieldname": "leads",          "fieldtype": "Int",      "width": 100},
		{"label": _("Quotations"),        "fieldname": "quotations",     "fieldtype": "Int",      "width": 110},
		{"label": _("Quot. Value"),       "fieldname": "quot_value",     "fieldtype": "Currency", "width": 140},
		{"label": _("Orders"),            "fieldname": "orders",         "fieldtype": "Int",      "width": 90},
		{"label": _("Order Value"),       "fieldname": "order_value",    "fieldtype": "Currency", "width": 140},
		{"label": _("Dispatches"),        "fieldname": "dispatches",     "fieldtype": "Int",      "width": 110},
		{"label": _("Dispatch Value"),    "fieldname": "dispatch_value", "fieldtype": "Currency", "width": 140},
		{"label": _("MTD Revenue"),       "fieldname": "mtd_revenue",    "fieldtype": "Currency", "width": 140},
		{"label": _("MTD Target"),        "fieldname": "mtd_target",     "fieldtype": "Currency", "width": 140},
		{"label": _("MTD %"),             "fieldname": "mtd_pct",        "fieldtype": "Percent",  "width": 100},
	]


# ── Data helpers ──────────────────────────────────────────────────────────────

_ADMIN_EXCEPTIONS = {"idris@instabizsolutions.com"}


def _admin_users():
	"""Return set of user emails that have the System Manager role — excluded from report.
	Users in _ADMIN_EXCEPTIONS are kept even if they have System Manager role."""
	rows = frappe.db.sql(
		"SELECT parent FROM `tabHas Role` WHERE role = 'System Manager' AND parenttype = 'User'",
		as_dict=True,
	)
	return {r.parent for r in rows} - _ADMIN_EXCEPTIONS


def _get_reps(date, territory):
	"""Return set of all sales person users active on this date."""
	cond = "WHERE transaction_date = %(date)s AND docstatus = 1 AND custom_sales_person_user != ''"
	if territory:
		cond += " AND territory = %(territory)s"

	so_reps = frappe.db.sql(
		f"SELECT DISTINCT custom_sales_person_user AS user, custom_sales_person AS name FROM `tabSales Order` {cond}",
		{"date": date, "territory": territory}, as_dict=True,
	)

	lead_cond = "WHERE DATE(l.creation) = %(date)s AND l.lead_owner != ''"
	if territory:
		lead_cond += " AND l.territory = %(territory)s"

	lead_reps = frappe.db.sql(
		f"""SELECT DISTINCT l.lead_owner AS user, u.full_name AS name
			FROM `tabLead` l LEFT JOIN `tabUser` u ON u.name = l.lead_owner {lead_cond}""",
		{"date": date, "territory": territory}, as_dict=True,
	)

	rep_map = {}
	for r in list(so_reps) + list(lead_reps):
		if r.user and r.user not in rep_map:
			rep_map[r.user] = r.name or r.user
	return rep_map


def _build_rows(date, month_start, territory, reps):
	leads       = _leads_today(date, territory)
	quotations  = _quotations_today(date, territory)
	orders      = _orders_today(date, territory)
	dispatches  = _dispatches_today(date, territory)
	mtd_revenue = _mtd_revenue(month_start, date, territory)
	mtd_targets = _mtd_targets(month_start)

	admins = _admin_users()
	all_users = (set(reps) | set(leads) | set(quotations) | set(orders) | set(dispatches) | set(mtd_revenue)) - admins
	rows = []
	for user in all_users:
		target    = flt(mtd_targets.get(user, 0))
		mtd_rev   = flt(mtd_revenue.get(user, {}).get("revenue", 0))
		mtd_pct   = flt(mtd_rev / target * 100, 1) if target else 0
		rows.append({
			"sales_person":   reps.get(user) or user,
			"leads":          leads.get(user, 0),
			"quotations":     quotations.get(user, {}).get("count", 0),
			"quot_value":     flt(quotations.get(user, {}).get("value", 0)),
			"orders":         orders.get(user, {}).get("count", 0),
			"order_value":    flt(orders.get(user, {}).get("value", 0)),
			"dispatches":     dispatches.get(user, {}).get("count", 0),
			"dispatch_value": flt(dispatches.get(user, {}).get("value", 0)),
			"mtd_revenue":    mtd_rev,
			"mtd_target":     target,
			"mtd_pct":        mtd_pct,
		})

	rows.sort(key=lambda r: r["order_value"], reverse=True)
	return rows


# ── SQL queries ───────────────────────────────────────────────────────────────

def _leads_today(date, territory):
	cond = "WHERE DATE(creation) = %(date)s AND lead_owner != ''"
	if territory:
		cond += " AND territory = %(territory)s"
	rows = frappe.db.sql(
		f"SELECT lead_owner AS user, COUNT(name) AS cnt FROM `tabLead` {cond} GROUP BY lead_owner",
		{"date": date, "territory": territory}, as_dict=True,
	)
	return {r.user: r.cnt for r in rows}


def _quotations_today(date, territory):
	cond = "WHERE transaction_date = %(date)s AND docstatus = 1 AND custom_sales_person_user != ''"
	if territory:
		cond += " AND territory = %(territory)s"
	rows = frappe.db.sql(
		f"""SELECT custom_sales_person_user AS user, COUNT(name) AS cnt, SUM(rounded_total) AS val
			FROM `tabQuotation` {cond} GROUP BY custom_sales_person_user""",
		{"date": date, "territory": territory}, as_dict=True,
	)
	return {r.user: {"count": r.cnt, "value": r.val or 0} for r in rows}


def _orders_today(date, territory):
	cond = "WHERE transaction_date = %(date)s AND docstatus = 1 AND custom_sales_person_user != ''"
	if territory:
		cond += " AND territory = %(territory)s"
	rows = frappe.db.sql(
		f"""SELECT custom_sales_person_user AS user, COUNT(name) AS cnt, SUM(rounded_total) AS val
			FROM `tabSales Order` {cond} GROUP BY custom_sales_person_user""",
		{"date": date, "territory": territory}, as_dict=True,
	)
	return {r.user: {"count": r.cnt, "value": r.val or 0} for r in rows}


def _dispatches_today(date, territory):
	cond = "WHERE posting_date = %(date)s AND docstatus = 1 AND is_return = 0 AND custom_sales_person_user != ''"
	if territory:
		cond += " AND territory = %(territory)s"
	rows = frappe.db.sql(
		f"""SELECT custom_sales_person_user AS user, COUNT(name) AS cnt, SUM(rounded_total) AS val
			FROM `tabDelivery Note` {cond} GROUP BY custom_sales_person_user""",
		{"date": date, "territory": territory}, as_dict=True,
	)
	return {r.user: {"count": r.cnt, "value": r.val or 0} for r in rows}


def _mtd_revenue(month_start, date, territory):
	cond = "WHERE transaction_date BETWEEN %(month_start)s AND %(date)s AND docstatus = 1 AND custom_sales_person_user != ''"
	if territory:
		cond += " AND territory = %(territory)s"
	rows = frappe.db.sql(
		f"""SELECT custom_sales_person_user AS user, SUM(rounded_total) AS revenue
			FROM `tabSales Order` {cond} GROUP BY custom_sales_person_user""",
		{"month_start": month_start, "date": date, "territory": territory}, as_dict=True,
	)
	return {r.user: {"revenue": r.revenue or 0} for r in rows}


def _mtd_targets(month_start):
	rows = frappe.db.sql(
		"SELECT sales_user, target_amount FROM `tabIB Sales Target` WHERE month = %(month)s",
		{"month": month_start}, as_dict=True,
	)
	return {r.sales_user: r.target_amount for r in rows}


# ── Chart ─────────────────────────────────────────────────────────────────────

def _chart(data, filters=None):
	if not data:
		return None
	chart_type = (filters or {}).get("chart_type") or "bar"
	top = [r for r in data if r["order_value"] > 0][:10]
	if not top:
		top = data[:10]
	return {
		"data": {
			"labels": [r["sales_person"] for r in top],
			"datasets": [
				{"name": _("Order Value"),    "values": [r["order_value"]    for r in top]},
				{"name": _("Dispatch Value"), "values": [r["dispatch_value"] for r in top]},
				{"name": _("MTD Revenue"),    "values": [r["mtd_revenue"]    for r in top]},
			],
		},
		"type": chart_type,
		"colors": ["#d97757", "#2e74b5", "#70ad47"],
	}


# ── Summary cards ─────────────────────────────────────────────────────────────

def _summary(data, date, month_start):
	if not data:
		return None

	total_leads    = sum(r["leads"]          for r in data)
	total_orders   = sum(r["orders"]         for r in data)
	total_o_val    = sum(r["order_value"]    for r in data)
	total_dispatch = sum(r["dispatch_value"] for r in data)
	total_mtd      = sum(r["mtd_revenue"]    for r in data)
	total_target   = sum(r["mtd_target"]     for r in data)

	# Collections (not per-rep — Payment Entry has no sales person link)
	collections = flt(frappe.db.sql(
		"""SELECT COALESCE(SUM(paid_amount), 0) FROM `tabPayment Entry`
		   WHERE payment_type = 'Receive' AND party_type = 'Customer'
		   AND posting_date = %(date)s AND docstatus = 1""",
		{"date": date},
	)[0][0])

	# Outstanding backlog — submitted SOs not fully delivered
	backlog = flt(frappe.db.sql(
		"""SELECT COALESCE(SUM(rounded_total - COALESCE(per_delivered, 0) * rounded_total / 100), 0)
		   FROM `tabSales Order`
		   WHERE docstatus = 1 AND status NOT IN %(done)s""",
		{"done": stored_statuses("Sales Order", "Completed", "Cancelled", "Closed")},
	)[0][0])

	mtd_pct = flt(total_mtd / total_target * 100, 1) if total_target else 0

	return [
		{"value": total_orders,   "label": _("Orders Today"),      "datatype": "Int",      "indicator": "blue"},
		{"value": total_o_val,    "label": _("Order Value Today"),  "datatype": "Currency", "indicator": "blue"},
		{"value": total_dispatch, "label": _("Dispatched Today"),   "datatype": "Currency", "indicator": "orange"},
		{"value": collections,    "label": _("Collections Today"),  "datatype": "Currency", "indicator": "green"},
		{"value": total_leads,    "label": _("New Leads Today"),    "datatype": "Int",      "indicator": "purple"},
		{"value": backlog,        "label": _("Order Backlog"),      "datatype": "Currency", "indicator": "red"},
		{"value": total_mtd,      "label": _("MTD Revenue"),        "datatype": "Currency", "indicator": "green"},
		{"value": mtd_pct,        "label": _("MTD vs Target %"),    "datatype": "Percent",  "indicator": "green" if mtd_pct >= 75 else "orange" if mtd_pct >= 50 else "red"},
	]
