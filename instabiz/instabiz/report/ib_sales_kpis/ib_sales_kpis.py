"""IB Sales KPIs — per-rep pipeline conversion and revenue report."""
import frappe
from frappe import _
from frappe.utils import getdate, flt


def execute(filters=None):
	filters = filters or {}
	from instabiz.overrides.own_data import locked_user

	if locked_user():
		filters["sales_person_user"] = locked_user()  # a plain Sales User sees only their own
	_validate(filters)
	data    = _data(filters)
	columns = _columns()
	return columns, data, None, _chart(data, filters), _summary(data)


def _validate(filters):
	if filters.get("from_date") and filters.get("to_date"):
		if getdate(filters["from_date"]) > getdate(filters["to_date"]):
			frappe.throw(_("From Date cannot be after To Date."))


def _columns():
	return [
		{"label": _("Sales Person"),       "fieldname": "sales_person",    "fieldtype": "Data",     "width": 200},
		{"label": _("Leads"),              "fieldname": "leads",           "fieldtype": "Int",      "width": 80},
		{"label": _("Quotations"),         "fieldname": "quotations",      "fieldtype": "Int",      "width": 100},
		{"label": _("Orders"),             "fieldname": "orders",          "fieldtype": "Int",      "width": 80},
		{"label": _("Lead → Q %"),         "fieldname": "lead_to_q_pct",   "fieldtype": "Percent",  "width": 100},
		{"label": _("Q → SO %"),           "fieldname": "q_to_so_pct",     "fieldtype": "Percent",  "width": 100},
		{"label": _("Lead → SO %"),        "fieldname": "lead_to_so_pct",  "fieldtype": "Percent",  "width": 110},
		{"label": _("Revenue"),            "fieldname": "revenue",         "fieldtype": "Currency",  "width": 150},
		{"label": _("Avg Deal Size"),      "fieldname": "avg_deal",        "fieldtype": "Currency",  "width": 150},
		{"label": _("Lost Deals"),         "fieldname": "lost",            "fieldtype": "Int",      "width": 100},
	]


def _data(filters):
	from_date = filters.get("from_date")
	to_date   = filters.get("to_date")
	territory = filters.get("territory")
	sp_user   = filters.get("sales_person_user")
	source    = filters.get("source")

	# ── Leads per rep ────────────────────────────────────────────────────────
	lead_cond = "WHERE DATE(l.creation) BETWEEN %(from_date)s AND %(to_date)s"
	if territory:
		lead_cond += " AND l.territory = %(territory)s"
	if sp_user:
		lead_cond += " AND l.lead_owner = %(sp_user)s"
	if source:
		lead_cond += " AND l.source = %(source)s"

	leads = frappe.db.sql(
		f"""
		SELECT
			COALESCE(NULLIF(l.lead_owner,''), l.owner)          AS user,
			COALESCE(u.full_name, l.lead_owner)                  AS sales_person,
			COUNT(l.name)                                         AS leads,
			SUM(l.custom_status = 'Lost')                        AS lost
		FROM `tabLead` l
		LEFT JOIN `tabUser` u ON u.name = l.lead_owner
		{lead_cond}
		GROUP BY COALESCE(NULLIF(l.lead_owner,''), l.owner)
		""",
		{"from_date": from_date, "to_date": to_date,
		 "territory": territory, "sp_user": sp_user, "source": source},
		as_dict=True,
	)
	lead_map = {r.user: r for r in leads}

	# ── Quotations per rep ───────────────────────────────────────────────────
	q_cond = "WHERE q.transaction_date BETWEEN %(from_date)s AND %(to_date)s AND q.docstatus = 1 AND q.custom_sales_person_user != ''"
	if territory:
		q_cond += " AND q.territory = %(territory)s"
	if sp_user:
		q_cond += " AND q.custom_sales_person_user = %(sp_user)s"

	quotes = frappe.db.sql(
		f"""
		SELECT custom_sales_person_user AS user, COUNT(name) AS quotations
		FROM `tabQuotation` q
		{q_cond}
		GROUP BY custom_sales_person_user
		""",
		{"from_date": from_date, "to_date": to_date,
		 "territory": territory, "sp_user": sp_user},
		as_dict=True,
	)
	quote_map = {r.user: r.quotations for r in quotes}

	# ── Sales Orders per rep ─────────────────────────────────────────────────
	so_cond = "WHERE so.transaction_date BETWEEN %(from_date)s AND %(to_date)s AND so.docstatus = 1 AND so.custom_sales_person_user != ''"
	if territory:
		so_cond += " AND so.territory = %(territory)s"
	if sp_user:
		so_cond += " AND so.custom_sales_person_user = %(sp_user)s"

	orders = frappe.db.sql(
		f"""
		SELECT
			custom_sales_person_user          AS user,
			COUNT(name)                        AS orders,
			SUM(rounded_total)                 AS revenue
		FROM `tabSales Order` so
		{so_cond}
		GROUP BY custom_sales_person_user
		""",
		{"from_date": from_date, "to_date": to_date,
		 "territory": territory, "sp_user": sp_user},
		as_dict=True,
	)
	order_map = {r.user: r for r in orders}

	# ── Merge ────────────────────────────────────────────────────────────────
	all_users = set(lead_map) | set(quote_map) | set(order_map)
	rows = []
	for user in all_users:
		lrow  = lead_map.get(user, {})
		l_cnt = lrow.get("leads", 0) or 0
		q_cnt = quote_map.get(user, 0) or 0
		orow  = order_map.get(user, {})
		o_cnt = orow.get("orders", 0) or 0
		rev   = flt(orow.get("revenue", 0))

		rows.append({
			"sales_person":   lrow.get("sales_person") or user,
			"leads":          l_cnt,
			"quotations":     q_cnt,
			"orders":         o_cnt,
			"lead_to_q_pct":  flt(q_cnt / l_cnt * 100, 1) if l_cnt else 0,
			"q_to_so_pct":    flt(o_cnt / q_cnt * 100, 1) if q_cnt else 0,
			"lead_to_so_pct": flt(o_cnt / l_cnt * 100, 1) if l_cnt else 0,
			"revenue":        rev,
			"avg_deal":       flt(rev / o_cnt, 2) if o_cnt else 0,
			"lost":           lrow.get("lost", 0) or 0,
		})

	rows.sort(key=lambda r: r["revenue"], reverse=True)
	return rows


def _chart(data, filters=None):
	if not data:
		return None
	chart_type = (filters or {}).get("chart_type") or "bar"
	top = data[:10]
	return {
		"data": {
			"labels":   [r["sales_person"] for r in top],
			"datasets": [
				{"name": _("Revenue"),    "values": [r["revenue"] for r in top]},
				{"name": _("Quotations"), "values": [r["quotations"] for r in top]},
				{"name": _("Orders"),     "values": [r["orders"] for r in top]},
			],
		},
		"type": chart_type,
		"colors": ["#d97757", "#2e74b5", "#70ad47"],
	}


def _summary(data):
	if not data:
		return None
	total_leads  = sum(r["leads"]       for r in data)
	total_orders = sum(r["orders"]      for r in data)
	total_rev    = sum(r["revenue"]     for r in data)
	total_q      = sum(r["quotations"]  for r in data)
	overall_conv = flt(total_orders / total_leads * 100, 1) if total_leads else 0
	return [
		{"value": total_leads,   "label": _("Total Leads"),      "datatype": "Int",      "indicator": "blue"},
		{"value": total_q,       "label": _("Quotations"),        "datatype": "Int",      "indicator": "orange"},
		{"value": total_orders,  "label": _("Orders"),            "datatype": "Int",      "indicator": "green"},
		{"value": overall_conv,  "label": _("Lead→SO Conv %"),    "datatype": "Percent",  "indicator": "purple"},
		{"value": total_rev,     "label": _("Total Revenue"),     "datatype": "Currency", "indicator": "green"},
	]
