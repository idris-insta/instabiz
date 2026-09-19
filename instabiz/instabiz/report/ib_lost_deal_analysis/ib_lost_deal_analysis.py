"""IB Lost Deal Analysis — loss reasons from Leads and Quotations."""
import frappe
from frappe import _
from frappe.utils import getdate, flt

from instabiz.overrides.ib_status import stored_statuses


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
		{"label": _("Source"),        "fieldname": "source",       "fieldtype": "Data",     "width": 100},
		{"label": _("Loss Reason"),   "fieldname": "loss_reason",  "fieldtype": "Data",     "width": 180},
		{"label": _("Sales Person"),  "fieldname": "sales_person", "fieldtype": "Data",     "width": 180},
		{"label": _("State"),     "fieldname": "territory",    "fieldtype": "Data",     "width": 140},
		{"label": _("Month"),         "fieldname": "month",        "fieldtype": "Data",     "width": 100},
		{"label": _("Count"),         "fieldname": "count",        "fieldtype": "Int",      "width": 80},
		{"label": _("Value Lost"),    "fieldname": "value_lost",   "fieldtype": "Currency", "width": 140},
		{"label": _("Document"),      "fieldname": "docname",      "fieldtype": "Dynamic Link", "options": "source_dt", "width": 160},
		{"label": _(""),              "fieldname": "source_dt",    "fieldtype": "Data",     "hidden": 1},
	]


def _data(filters):
	rows = []
	source_filter = filters.get("source") or "Both"

	if source_filter in ("Lead", "Both"):
		rows += _lost_leads(filters)
	if source_filter in ("Quotation", "Both"):
		rows += _lost_quotations(filters)

	rows.sort(key=lambda r: (r["loss_reason"] or "", r["month"] or ""))
	return rows


def _lost_leads(filters):
	cond  = "WHERE l.custom_status = 'Lost' AND DATE(l.modified) BETWEEN %(from_date)s AND %(to_date)s"
	vals  = {"from_date": filters.get("from_date"), "to_date": filters.get("to_date")}

	if filters.get("territory"):
		cond += " AND l.territory = %(territory)s"
		vals["territory"] = filters["territory"]
	if filters.get("sales_person_user"):
		cond += " AND l.lead_owner = %(sp_user)s"
		vals["sp_user"] = filters["sales_person_user"]
	if filters.get("loss_reason"):
		cond += " AND l.custom_loss_reason = %(loss_reason)s"
		vals["loss_reason"] = filters["loss_reason"]

	return frappe.db.sql(
		f"""
		SELECT
			'Lead'                                              AS source,
			'Lead'                                              AS source_dt,
			l.name                                              AS docname,
			COALESCE(NULLIF(l.custom_loss_reason,''), 'Not Set') AS loss_reason,
			COALESCE(u.full_name, l.lead_owner, l.owner)       AS sales_person,
			l.territory,
			DATE_FORMAT(l.modified, '%%Y-%%m')                  AS month,
			1                                                   AS count,
			0                                                   AS value_lost
		FROM `tabLead` l
		LEFT JOIN `tabUser` u ON u.name = l.lead_owner
		{cond}
		ORDER BY l.modified DESC
		""",
		vals,
		as_dict=True,
	)


def _lost_quotations(filters):
	# CustomQuotation.STATUS_MAP stores "Lost" as "Cancelled" (docstatus stays 1)
	cond = "WHERE q.status IN %(lost)s AND DATE(q.modified) BETWEEN %(from_date)s AND %(to_date)s AND q.docstatus = 1"
	vals = {
		"from_date": filters.get("from_date"),
		"to_date": filters.get("to_date"),
		"lost": stored_statuses("Quotation", "Lost"),
	}

	if filters.get("territory"):
		cond += " AND q.territory = %(territory)s"
		vals["territory"] = filters["territory"]
	if filters.get("sales_person_user"):
		cond += " AND q.custom_sales_person_user = %(sp_user)s"
		vals["sp_user"] = filters["sales_person_user"]
	if filters.get("loss_reason"):
		cond += " AND q.custom_loss_reason = %(loss_reason)s"
		vals["loss_reason"] = filters["loss_reason"]

	return frappe.db.sql(
		f"""
		SELECT
			'Quotation'                                              AS source,
			'Quotation'                                              AS source_dt,
			q.name                                                   AS docname,
			COALESCE(NULLIF(q.custom_loss_reason,''), 'Not Set')     AS loss_reason,
			COALESCE(NULLIF(q.custom_sales_person,''), u.full_name,
			         q.custom_sales_person_user)                     AS sales_person,
			q.territory,
			DATE_FORMAT(q.modified, '%%Y-%%m')                       AS month,
			1                                                        AS count,
			COALESCE(q.rounded_total, q.grand_total, 0)              AS value_lost
		FROM `tabQuotation` q
		LEFT JOIN `tabUser` u ON u.name = q.custom_sales_person_user
		{cond}
		ORDER BY q.modified DESC
		""",
		vals,
		as_dict=True,
	)


def _chart(data, filters=None):
	if not data:
		return None
	reason_map = {}
	for row in data:
		r = row["loss_reason"] or "Not Set"
		reason_map[r] = reason_map.get(r, 0) + 1

	reasons = sorted(reason_map, key=lambda k: reason_map[k], reverse=True)
	chart_type = (filters or {}).get("chart_type") or "bar"
	return {
		"data": {
			"labels":   reasons,
			"datasets": [{"name": _("Lost Deals"), "values": [reason_map[r] for r in reasons]}],
		},
		"type": chart_type,
		"colors": ["#d97757", "#2e74b5", "#cf222e", "#70ad47", "#9467bd", "#8c564b"],
		"height": 280,
	}


def _summary(data):
	if not data:
		return None
	total        = len(data)
	total_value  = sum(flt(r.get("value_lost", 0)) for r in data)
	from_leads   = sum(1 for r in data if r["source"] == "Lead")
	from_quotes  = sum(1 for r in data if r["source"] == "Quotation")
	top_reason   = ""
	if data:
		reason_map = {}
		for row in data:
			r = row["loss_reason"] or "Not Set"
			reason_map[r] = reason_map.get(r, 0) + 1
		top_reason = max(reason_map, key=reason_map.get)

	return [
		{"value": total,       "label": _("Total Lost"),       "datatype": "Int",      "indicator": "red"},
		{"value": from_leads,  "label": _("From Leads"),       "datatype": "Int",      "indicator": "orange"},
		{"value": from_quotes, "label": _("From Quotations"),  "datatype": "Int",      "indicator": "orange"},
		{"value": total_value, "label": _("Value Lost"),       "datatype": "Currency", "indicator": "red"},
		{"value": top_reason,  "label": _("Top Loss Reason"),  "datatype": "Data",     "indicator": "blue"},
	]
