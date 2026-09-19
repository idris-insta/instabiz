"""IB Collections Report — per-rep invoice, collected, outstanding, collection %."""
import frappe
from frappe import _
from frappe.utils import flt

from instabiz.overrides.billing_mode import sales_total_expr, is_dev_billing_mode, sales_doctype, sales_outstanding_expr


def execute(filters=None):
	filters = filters or {}
	from instabiz.overrides.own_data import locked_user

	if locked_user():
		filters["sales_person_user"] = locked_user()  # a plain Sales User sees only their own
	columns = _columns()
	data    = _data(filters)
	chart   = _chart(data, filters)
	summary = _summary(data)
	return columns, data, None, chart, summary


def _columns():
	return [
		{"fieldname": "sales_person",     "label": _("Sales Person"),       "fieldtype": "Data",     "width": 180},
		{"fieldname": "invoice_count",    "label": _("Invoices"),            "fieldtype": "Int",      "width": 90},
		{"fieldname": "invoiced_amount",  "label": _("Invoiced (₹)"),        "fieldtype": "Currency", "width": 140},
		{"fieldname": "collected_amount", "label": _("Collected (₹)"),       "fieldtype": "Currency", "width": 140},
		{"fieldname": "outstanding",      "label": _("Outstanding (₹)"),     "fieldtype": "Currency", "width": 140},
		{"fieldname": "collection_pct",   "label": _("Collection %"),        "fieldtype": "Percent",  "width": 110},
	]


def _data(filters):
	# Basis controlled by instabiz.overrides.billing_mode — dev mode reads
	# Sales Order (billing isn't live yet, SI-based collections always reads
	# empty); prod mode reads real Sales Invoice. Sales Order has no is_return
	# and no posting_date (uses transaction_date instead).
	dev_mode = is_dev_billing_mode()
	doctype  = sales_doctype()
	date_field  = "transaction_date" if dev_mode else "posting_date"
	outstanding_expr = sales_outstanding_expr("t")

	conds = ["t.docstatus = 1", "t.custom_sales_person_user IS NOT NULL"]
	if not dev_mode:
		conds.append("t.is_return = 0")
	params = {}

	if filters.get("from_date"):
		conds.append(f"t.{date_field} >= %(from_date)s")
		params["from_date"] = filters["from_date"]
	if filters.get("to_date"):
		conds.append(f"t.{date_field} <= %(to_date)s")
		params["to_date"] = filters["to_date"]
	if filters.get("territory"):
		conds.append("t.territory = %(territory)s")
		params["territory"] = filters["territory"]
	if filters.get("sales_person_user"):
		conds.append("t.custom_sales_person_user = %(sales_person_user)s")
		params["sales_person_user"] = filters["sales_person_user"]

	where = " AND ".join(conds)

	rows = frappe.db.sql(
		f"""
		SELECT
			t.custom_sales_person_user                                       AS sales_person,
			COUNT(DISTINCT t.name)                                           AS invoice_count,
			ROUND(SUM({sales_total_expr('t')}), 2)                                     AS invoiced_amount,
			ROUND(SUM({sales_total_expr('t')}) - SUM({outstanding_expr}), 2)           AS collected_amount,
			ROUND(SUM({outstanding_expr}), 2)                                AS outstanding,
			CASE WHEN SUM({sales_total_expr('t')}) > 0
			     THEN ROUND((SUM({sales_total_expr('t')}) - SUM({outstanding_expr}))
			                / SUM({sales_total_expr('t')}) * 100, 1)
			     ELSE 0
			END                                                               AS collection_pct
		FROM `tab{doctype}` t
		WHERE {where}
		GROUP BY t.custom_sales_person_user
		ORDER BY collected_amount DESC
		""",
		params,
		as_dict=True,
	)
	return rows


def _chart(data, filters=None):
	chart_type = (filters or {}).get("chart_type", "bar")
	labels     = [r.sales_person for r in data]
	return {
		"type":    chart_type,
		"data": {
			"labels":   labels,
			"datasets": [
				{"name": _("Invoiced"),    "values": [flt(r.invoiced_amount)  for r in data]},
				{"name": _("Collected"),   "values": [flt(r.collected_amount) for r in data]},
				{"name": _("Outstanding"), "values": [flt(r.outstanding)      for r in data]},
			],
		},
		"colors": ["#5e64ff", "#28a745", "#e74c3c"],
	}


def _summary(data):
	total_inv   = sum(flt(r.invoiced_amount)  for r in data)
	total_col   = sum(flt(r.collected_amount) for r in data)
	total_out   = sum(flt(r.outstanding)      for r in data)
	overall_pct = round(total_col / total_inv * 100, 1) if total_inv else 0

	return [
		{"label": _("Total Invoiced"),    "value": total_inv,   "datatype": "Currency", "currency": "INR"},
		{"label": _("Total Collected"),   "value": total_col,   "datatype": "Currency", "currency": "INR"},
		{"label": _("Total Outstanding"), "value": total_out,   "datatype": "Currency", "currency": "INR"},
		{"label": _("Overall Collection %"), "value": overall_pct, "datatype": "Percent"},
	]
