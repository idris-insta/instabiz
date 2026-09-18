"""Status values as they are actually stored.

IbStatusMixin rewrites Quotation / Sales Order / Delivery Note / Sales Invoice
status through each override class's STATUS_MAP before it reaches the DB
(a submitted Quotation is stored as "Pending", never "Open"). Any SQL or
filter written against raw ERPNext status names silently matches nothing.

Build status lists with stored_statuses() instead of hard-coding them:

	stored_statuses("Sales Order", "Completed", "Closed", "Cancelled")
	# -> ("Completed", "Confirmed", "Closed", "Cancelled")

Raw names are kept alongside their stored label so legacy rows written before
the remap still match. scripts/check_status_literals.py enforces this in CI.
"""
import frappe

_CLASS_PATHS = {
	"Quotation": "instabiz.overrides.quotation.CustomQuotation",
	"Sales Order": "instabiz.overrides.sales_order.CustomSalesOrder",
	"Delivery Note": "instabiz.overrides.delivery_note.CustomDeliveryNote",
	"Sales Invoice": "instabiz.overrides.sales_invoice.CustomSalesInvoice",
}


def status_map(doctype):
	path = _CLASS_PATHS.get(doctype)
	if not path:
		return {}
	return getattr(frappe.get_attr(path), "STATUS_MAP", {}) or {}


def stored_statuses(doctype, *erpnext_statuses):
	"""Every value a row in one of the given ERPNext statuses can be stored as."""
	smap = status_map(doctype)
	out = []
	for status in erpnext_statuses:
		for value in (status, smap.get(status)):
			if value and value not in out:
				out.append(value)
	return tuple(out)
