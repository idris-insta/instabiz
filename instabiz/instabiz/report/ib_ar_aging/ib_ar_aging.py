"""IB AR Aging — outstanding Sales Invoices bucketed by age."""
import frappe
from frappe import _
from frappe.utils import today, getdate, date_diff, flt

from instabiz.overrides.billing_mode import is_dev_billing_mode, sales_doctype, sales_outstanding_expr


def execute(filters=None):
	filters = filters or {}
	data    = _data(filters)
	columns = _columns()
	from instabiz.overrides.ageing import rebucket

	columns, data, chart, summary = rebucket(filters, columns, data, "outstanding", "Currency", _chart(data, filters), _summary(data))
	return columns, data, None, chart, summary


def _columns():
	doc_label = _("Order") if is_dev_billing_mode() else _("Invoice")
	doc_options = sales_doctype()
	date_label = _("Order Date") if is_dev_billing_mode() else _("Invoice Date")
	return [
		{"label": _("Customer"),      "fieldname": "customer",     "fieldtype": "Link",     "options": "Customer", "width": 200},
		{"label": doc_label,          "fieldname": "name",         "fieldtype": "Link",     "options": doc_options, "width": 160},
		{"label": date_label,         "fieldname": "posting_date", "fieldtype": "Date",     "width": 110},
		{"label": _("Due Date"),      "fieldname": "due_date",     "fieldtype": "Date",     "width": 100},
		{"label": _("Age (days)"),    "fieldname": "age_days",     "fieldtype": "Int",      "width": 100},
		{"label": _("0-30"),          "fieldname": "b0_30",        "fieldtype": "Currency", "width": 120},
		{"label": _("31-60"),         "fieldname": "b31_60",       "fieldtype": "Currency", "width": 120},
		{"label": _("61-90"),         "fieldname": "b61_90",       "fieldtype": "Currency", "width": 120},
		{"label": _("90+"),           "fieldname": "b90plus",      "fieldtype": "Currency", "width": 120},
		{"label": _("Outstanding"),   "fieldname": "outstanding",  "fieldtype": "Currency", "width": 140},
		{"label": _("Sales Person"),  "fieldname": "sales_person", "fieldtype": "Data",     "width": 150},
	]


def _data(filters):
	# Basis controlled by instabiz.overrides.billing_mode — dev mode reads
	# Sales Order (billing isn't live in ERP yet, so SI-based AR always reads
	# empty); prod mode reads real Sales Invoice outstanding_amount/due_date.
	# In dev mode: "Outstanding" = grand_total minus whatever advance has
	# actually been paid (custom_advance_paid) — not the full order value,
	# since a partially/fully-advance-paid order shouldn't count as fully due.
	# "Due Date" falls back to the order's own transaction_date pre-invoice.
	today_date = getdate(today())
	customer   = filters.get("customer")
	territory  = filters.get("territory")
	sp_user    = filters.get("sales_person_user")
	dev_mode   = is_dev_billing_mode()
	doctype    = sales_doctype()

	if dev_mode:
		date_field  = "transaction_date"
		amount_expr = sales_outstanding_expr("t")
		# Only 'Cancelled' excluded, not 'Closed' — CustomSalesOrder.STATUS_MAP maps
		# DB status 'Closed' to user-facing label 'Confirmed' (a real completed sale).
		status_cond = "AND t.status != 'Cancelled'"
	else:
		date_field  = "posting_date"
		amount_expr = sales_outstanding_expr("t")
		status_cond = "AND t.outstanding_amount > 0"

	cust_cond = "AND t.customer = %(customer)s" if customer else ""
	terr_cond = "AND t.territory = %(territory)s" if territory else ""
	sp_cond   = "AND t.custom_sales_person_user = %(sp_user)s" if sp_user else ""

	rows = frappe.db.sql(
		f"""
		SELECT
			t.name,
			t.customer,
			t.{date_field} AS posting_date,
			t.{date_field} AS due_date,
			{amount_expr}  AS outstanding,
			t.custom_sales_person AS sales_person,
			t.custom_sales_person_user
		FROM `tab{doctype}` t
		WHERE t.docstatus = 1
		AND t.grand_total > 0
		{status_cond}
		{cust_cond} {terr_cond} {sp_cond}
		ORDER BY t.{date_field} ASC
		""",
		{"customer": customer, "territory": territory, "sp_user": sp_user},
		as_dict=True,
	)

	data = []
	for r in rows:
		age = date_diff(today_date, getdate(r.due_date)) if r.due_date else 0
		age = max(age, 0)
		amt = flt(r.outstanding)
		if amt <= 0:
			continue
		data.append({
			"customer":     r.customer,
			"name":         r.name,
			"posting_date": r.posting_date,
			"due_date":     r.due_date,
			"age_days":     age,
			"b0_30":        amt if age <= 30 else 0,
			"b31_60":       amt if 31 <= age <= 60 else 0,
			"b61_90":       amt if 61 <= age <= 90 else 0,
			"b90plus":      amt if age > 90 else 0,
			"outstanding":  amt,
			"sales_person": r.sales_person or r.custom_sales_person_user or "",
		})
	return data


def _chart(data, filters=None):
	if not data:
		return None
	chart_type = (filters or {}).get("chart_type") or "bar"
	buckets = {"0-30": 0, "31-60": 0, "61-90": 0, "90+": 0}
	for r in data:
		buckets["0-30"]  += r["b0_30"]
		buckets["31-60"] += r["b31_60"]
		buckets["61-90"] += r["b61_90"]
		buckets["90+"]   += r["b90plus"]
	return {
		"data": {
			"labels":   list(buckets.keys()),
			"datasets": [{"name": _("Outstanding (INR)"), "values": list(buckets.values())}],
		},
		"type": chart_type,
		"colors": ["#1a7f37", "#d97757", "#ed7d31", "#cf222e"],
	}


def _summary(data):
	if not data:
		return None
	total  = sum(r["outstanding"] for r in data)
	old    = sum(r["b90plus"] for r in data)
	inv_ct = len(data)
	cust_ct = len({r["customer"] for r in data})
	return [
		{"value": inv_ct,  "label": _("Invoices"),          "datatype": "Int",      "indicator": "blue"},
		{"value": cust_ct, "label": _("Customers"),          "datatype": "Int",      "indicator": "orange"},
		{"value": total,   "label": _("Total Outstanding"),  "datatype": "Currency", "indicator": "red"},
		{"value": old,     "label": _("90+ Days"),           "datatype": "Currency", "indicator": "red"},
	]
