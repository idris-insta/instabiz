"""instabiz.overrides.quick_actions

Small time-savers on the sales forms:
  - repeat an order: a new draft Sales Order copied from a customer's last
    (or a chosen) order, dated today;
  - price hint: what this customer last paid for an item, and the rate card
    price, shown when the item is picked on a Quotation / Sales Order.
"""
import frappe
from frappe import _
from frappe.utils import add_days, flt, nowdate

from instabiz.overrides.ib_settings import get_int


@frappe.whitelist()
def repeat_order(sales_order=None, customer=None):
	"""Unsaved copy of a Sales Order (or the customer's latest one) for the form to open."""
	if not sales_order:
		if not customer:
			frappe.throw(_("Pick a customer or an order to repeat."))
		sales_order = frappe.db.get_value(
			"Sales Order", {"customer": customer, "docstatus": 1},
			"name", order_by="transaction_date desc, creation desc",
		)
		if not sales_order:
			frappe.throw(_("{0} has no confirmed order to repeat yet.").format(customer))
	source = frappe.get_doc("Sales Order", sales_order)
	source.check_permission("read")

	new = frappe.copy_doc(source)
	new.transaction_date = nowdate()
	new.delivery_date = add_days(nowdate(), get_int("default_delivery_days", 8))
	for field in ("po_no", "po_date", "custom_reference_po", "custom_cancel_reason",
			"custom_credit_override_reason", "custom_advance_approval_status",
			"custom_advance_approval_remarks", "custom_remarks"):
		if new.meta.has_field(field):
			new.set(field, None)
	for field in ("custom_advance_paid", "advance_paid"):
		if new.meta.has_field(field):
			new.set(field, 0)
	for row in new.items:
		row.delivery_date = new.delivery_date
		for field in ("prevdoc_docname", "quotation_item", "custom_attachment"):
			if row.meta.has_field(field):
				row.set(field, None)
	if new.meta.has_field("custom_document_attachments"):
		new.set("custom_document_attachments", [])
	out = new.as_dict()
	# an unsaved doc for frappe.model.sync: it names it and opens it as new
	out.update({"name": None, "__islocal": 1, "__unsaved": 1, "docstatus": 0})
	for table in ("items", "taxes", "payment_schedule", "sales_team", "packed_items"):
		for row in out.get(table) or []:
			row.update({"name": None, "parent": None, "__islocal": 1, "docstatus": 0})
	return out


@frappe.whitelist()
def price_hint(item_code, customer=None):
	"""Last price this customer paid for the item, plus the rate-card price."""
	if not item_code:
		return {}
	out = {}
	if customer:
		last = frappe.db.sql(
			"""
			SELECT soi.rate, soi.uom, so.transaction_date, so.name
			FROM `tabSales Order Item` soi
			INNER JOIN `tabSales Order` so ON so.name = soi.parent
			WHERE so.docstatus = 1 AND so.customer = %s AND soi.item_code = %s
			ORDER BY so.transaction_date DESC, so.creation DESC LIMIT 1
			""",
			(customer, item_code), as_dict=True,
		)
		if last and frappe.has_permission("Sales Order", "read", last[0].name):
			out["last"] = {"rate": flt(last[0].rate), "uom": last[0].uom,
				"date": str(last[0].transaction_date), "order": last[0].name}
	try:
		from instabiz.instabiz.page.ib_price_list.ib_price_list import get_current_rate_for_item

		card = get_current_rate_for_item(item_code)
		if card:
			out["card"] = {"face": flt(card.get("face_price")), "last": flt(card.get("last_price")),
				"unit": card.get("unit")}
	except frappe.PermissionError:
		pass
	return out
