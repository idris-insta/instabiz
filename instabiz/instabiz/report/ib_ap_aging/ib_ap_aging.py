"""IB AP Aging — outstanding Purchase Invoices bucketed by age."""
import frappe
from frappe import _
from frappe.utils import today, getdate, date_diff, flt

from instabiz.overrides.billing_mode import is_dev_billing_mode, purchase_doctype, purchase_outstanding_expr


def execute(filters=None):
	filters = filters or {}
	data    = _data(filters)
	columns = _columns()
	from instabiz.overrides.ageing import rebucket

	columns, data, chart, summary = rebucket(filters, columns, data, "outstanding", "Currency", _chart(data, filters), _summary(data))
	return columns, data, None, chart, summary


def _columns():
	doc_label = _("Order") if is_dev_billing_mode() else _("Invoice")
	doc_options = purchase_doctype()
	date_label = _("Order Date") if is_dev_billing_mode() else _("Invoice Date")
	return [
		{"label": _("Supplier"),      "fieldname": "supplier",     "fieldtype": "Link",     "options": "Supplier", "width": 200},
		{"label": doc_label,          "fieldname": "name",         "fieldtype": "Link",     "options": doc_options, "width": 160},
		{"label": date_label,         "fieldname": "posting_date", "fieldtype": "Date",     "width": 110},
		{"label": _("Due Date"),      "fieldname": "due_date",     "fieldtype": "Date",     "width": 100},
		{"label": _("Age (days)"),    "fieldname": "age_days",     "fieldtype": "Int",      "width": 100},
		{"label": _("0-30"),          "fieldname": "b0_30",        "fieldtype": "Currency", "width": 120},
		{"label": _("31-60"),         "fieldname": "b31_60",       "fieldtype": "Currency", "width": 120},
		{"label": _("61-90"),         "fieldname": "b61_90",       "fieldtype": "Currency", "width": 120},
		{"label": _("90+"),           "fieldname": "b90plus",      "fieldtype": "Currency", "width": 120},
		{"label": _("Outstanding"),   "fieldname": "outstanding",  "fieldtype": "Currency", "width": 140},
	]


def _data(filters):
	# Basis controlled by instabiz.overrides.billing_mode — dev mode reads
	# Purchase Order (billing isn't live in ERP yet, so PI-based AP always
	# reads empty); prod mode reads real Purchase Invoice outstanding_amount/
	# due_date. No advance-paid tracking exists against Purchase Order (no
	# purchase-side equivalent of custom_advance_paid), so dev-mode
	# "Outstanding" stays the full order value pre-invoice.
	today_date = getdate(today())
	supplier   = filters.get("supplier")
	dev_mode   = is_dev_billing_mode()
	doctype    = purchase_doctype()

	if dev_mode:
		date_field  = "transaction_date"
		status_cond = "AND t.status NOT IN ('Closed', 'Cancelled')"
	else:
		date_field  = "posting_date"
		status_cond = "AND t.outstanding_amount > 0"
	amount_expr = purchase_outstanding_expr("t")

	supp_cond = "AND t.supplier = %(supplier)s" if supplier else ""

	rows = frappe.db.sql(
		f"""
		SELECT
			t.name,
			t.supplier,
			t.{date_field} AS posting_date,
			t.{date_field} AS due_date,
			{amount_expr}   AS outstanding
		FROM `tab{doctype}` t
		WHERE t.docstatus = 1
		AND t.grand_total > 0
		{status_cond}
		{supp_cond}
		ORDER BY t.{date_field} ASC
		""",
		{"supplier": supplier},
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
			"supplier":     r.supplier,
			"name":         r.name,
			"posting_date": r.posting_date,
			"due_date":     r.due_date,
			"age_days":     age,
			"b0_30":        amt if age <= 30 else 0,
			"b31_60":       amt if 31 <= age <= 60 else 0,
			"b61_90":       amt if 61 <= age <= 90 else 0,
			"b90plus":      amt if age > 90 else 0,
			"outstanding":  amt,
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
	total    = sum(r["outstanding"] for r in data)
	old      = sum(r["b90plus"] for r in data)
	inv_ct   = len(data)
	supp_ct  = len({r["supplier"] for r in data})
	return [
		{"value": inv_ct,  "label": _("Invoices"),         "datatype": "Int",      "indicator": "blue"},
		{"value": supp_ct, "label": _("Suppliers"),         "datatype": "Int",      "indicator": "orange"},
		{"value": total,   "label": _("Total Payable"),     "datatype": "Currency", "indicator": "red"},
		{"value": old,     "label": _("90+ Days"),          "datatype": "Currency", "indicator": "red"},
	]
