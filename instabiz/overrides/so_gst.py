"""GST the invoice will carry, kept on the Sales Order.

Sales Orders carry no GST rows (internal document, quotation.drop_gst) but the
customer owes the GST-inclusive amount: receivables, statements, the portal and
the order PDF use custom_total_with_gst. It is worked out on a throw-away copy
of the order with the in / out-state template applied — the same rows the Sales
Invoice will get."""
import frappe
from frappe.utils import flt

FIELDS = [
	{"fieldname": "custom_gst_amount", "label": "GST (on invoice)", "fieldtype": "Currency",
		"options": "currency", "insert_after": "grand_total", "read_only": 1, "no_copy": 1,
		"description": "GST the Sales Invoice will add. Not charged on this order."},
	{"fieldname": "custom_total_with_gst", "label": "Total incl. GST", "fieldtype": "Currency",
		"options": "currency", "insert_after": "custom_gst_amount", "read_only": 1, "no_copy": 1, "bold": 1,
		"description": "What the customer owes for this order — used for outstanding, statements and the order PDF."},
]


def after_migrate():
	for f in FIELDS:
		if not frappe.db.exists("Custom Field", {"dt": "Sales Order", "fieldname": f["fieldname"]}):
			frappe.get_doc({"doctype": "Custom Field", "dt": "Sales Order", **f}).insert(ignore_permissions=True)


def gst_on_invoice(doc):
	"""GST amount for the order's lines (freight rows are left out)."""
	from instabiz.overrides.quotation import _auto_correct_gst_template

	gst_rows = [t for t in doc.get("taxes") or [] if t.charge_type != "Actual"]
	if gst_rows:
		return flt(sum(flt(t.base_tax_amount or t.tax_amount) for t in gst_rows), 2)
	shadow = frappe.copy_doc(doc)
	shadow.taxes_and_charges = None
	shadow.set("taxes", [])
	_auto_correct_gst_template(shadow)
	if not shadow.taxes:
		return 0.0
	shadow.flags.ignore_permissions = True
	shadow.calculate_taxes_and_totals()
	return flt(sum(flt(t.tax_amount) for t in shadow.taxes if t.charge_type != "Actual"), 2)


def set_gst_totals(doc, method=None):
	try:
		gst = gst_on_invoice(doc)
	except Exception:
		frappe.log_error(title="IB SO GST total", message=frappe.get_traceback())
		gst = 0.0
	has_rows = any(t.charge_type != "Actual" for t in doc.get("taxes") or [])
	base = flt(doc.rounded_total or doc.grand_total)
	total = base if has_rows else base + gst
	doc.custom_gst_amount = gst
	doc.custom_total_with_gst = flt(round(total)) if doc.rounded_total else flt(total, 2)


def backfill(since="2026-09-20"):
	"""Orders saved without GST rows since the change get their GST-inclusive total."""
	names = frappe.get_all("Sales Order", filters={"docstatus": ["<", 2], "creation": [">=", since]}, pluck="name")
	for name in names:
		doc = frappe.get_doc("Sales Order", name)
		set_gst_totals(doc)
		frappe.db.set_value("Sales Order", name, {"custom_gst_amount": doc.custom_gst_amount,
			"custom_total_with_gst": doc.custom_total_with_gst}, update_modified=False)
	return len(names)
