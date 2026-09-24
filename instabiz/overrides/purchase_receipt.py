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
from instabiz.overrides.purchase_rules import assert_domestic_pr_has_po, auto_inward_gate_pass_for_pr


class CustomPurchaseReceipt(PurchaseReceipt):
	def autoname(self):
		autoname_purchase_receipt(self)

	def validate(self):
		assert_domestic_pr_has_po(self)
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
		_make_grn_batches(self)
		try:
			auto_inward_gate_pass_for_pr(self.name)
		except Exception:
			frappe.log_error("IB Inward Gate Pass", frappe.get_traceback())

	def on_cancel(self):
		super().on_cancel()
		for b in frappe.get_all("IB Batch", {"purchase_receipt": self.name}, pluck="name"):
			for wo in frappe.get_all("IB Work Order", {"source_batch": b}, pluck="name"):
				frappe.db.set_value("IB Work Order", wo, "source_batch", None, update_modified=False)
			frappe.delete_doc("IB Batch", b, ignore_permissions=True, force=True)


def _make_grn_batches(doc):
	"""Domestic RM procurement is the other genealogy root beside IB Container
	Import. Create one IB Batch (annotation only — not a native ERPNext Batch)
	per received line so the trace page has a source-document node for purchased
	material, not just imported."""
	try:
		for row in doc.items:
			batch_id = f"{doc.name}::{row.item_code}::{row.idx}"
			if frappe.db.exists("IB Batch", batch_id):
				continue
			item = frappe.db.get_value(
				"Item", row.item_code, ["gsm", "width_mm", "item_name"], as_dict=True
			) or {}
			b = frappe.new_doc("IB Batch")
			b.batch_id = batch_id
			b.kind = "Raw Material"
			b.item = row.item_code
			b.item_name = item.get("item_name")
			b.qty = frappe.utils.flt(row.get("stock_qty") or row.qty)
			b.status = "Active"
			b.source_type = "Purchase Receipt"
			b.purchase_receipt = doc.name
			b.supplier = doc.supplier
			b.supplier_lot = row.get("custom_supplier_lot") or ""
			b.received_date = doc.posting_date
			b.gsm = frappe.utils.flt(item.get("gsm"))
			b.width_mm = frappe.utils.flt(item.get("width_mm"))
			b.insert(ignore_permissions=True)
	except Exception:
		frappe.log_error("IB GRN batch create", frappe.get_traceback())
