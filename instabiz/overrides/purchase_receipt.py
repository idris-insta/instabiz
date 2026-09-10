"""instabiz.overrides.purchase_receipt"""
import frappe
from frappe import _
from erpnext.stock.doctype.purchase_receipt.purchase_receipt import PurchaseReceipt  # pyright: ignore[reportMissingImports]

from instabiz.overrides.purchase_order import (
	_auto_correct_purchase_gst_template,
	_apply_purchase_cost_center,
	_apply_purchase_location_gstin,
	_set_location_from_warehouse,
)
from instabiz.overrides.utils import recalculate_purchase_items
from instabiz.overrides.naming import autoname_purchase_receipt


class CustomPurchaseReceipt(PurchaseReceipt):
	def autoname(self):
		autoname_purchase_receipt(self)

	def validate(self):
		_set_location_from_warehouse(self)
		_apply_purchase_location_gstin(self)
		_auto_correct_purchase_gst_template(self)
		_apply_purchase_cost_center(self)
		recalculate_purchase_items(self)
		super().validate()

	def before_cancel(self):
		if not (self.get("custom_cancel_reason") or "").strip():
			frappe.throw(_("Fill in Cancellation Reason before cancelling this Purchase Receipt."))

	def on_submit(self):
		super().on_submit()
		_enrich_grn_batches(self)


def _enrich_grn_batches(doc):
	"""Domestic RM procurement is the other genealogy root beside IB Container
	Import. ERPNext auto-creates a native Batch per received line (items now have
	has_batch_no + create_new_batch); tag those batches as Raw Material and link
	them back to this GRN so the trace page has a source-document node for
	purchased material, not just imported."""
	try:
		for row in doc.items:
			if not row.get("batch_no"):
				continue
			b = frappe.get_doc("Batch", row.batch_no)
			if b.get("custom_batch_kind"):
				continue
			item = frappe.db.get_value("Item", row.item_code, ["gsm", "width_mm"], as_dict=True) or {}
			b.custom_batch_kind = "Raw Material"
			b.custom_purchase_receipt = doc.name
			b.custom_supplier_lot = row.get("custom_supplier_lot") or ""
			b.custom_received_date = doc.posting_date
			b.custom_gsm = frappe.utils.flt(item.get("gsm"))
			b.custom_width_mm = frappe.utils.flt(item.get("width_mm"))
			b.save(ignore_permissions=True)
	except Exception:
		frappe.log_error("IB GRN batch enrich", frappe.get_traceback())
