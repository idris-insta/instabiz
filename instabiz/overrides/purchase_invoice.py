"""instabiz.overrides.purchase_invoice"""
import frappe
from frappe import _
from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import PurchaseInvoice  # pyright: ignore[reportMissingImports]

from instabiz.overrides.purchase_order import (
	_auto_correct_purchase_gst_template,
	_apply_purchase_cost_center,
	_apply_purchase_location_gstin,
	_set_location_from_warehouse,
	_first_warehouse,
)
from instabiz.overrides.utils import recalculate_purchase_items
from instabiz.overrides.naming import autoname_purchase_invoice
from instabiz.overrides.purchase_rules import assert_domestic_pi_has_po_pr


# ── Document class ────────────────────────────────────────────────────────────

class CustomPurchaseInvoice(PurchaseInvoice):
	def autoname(self):
		autoname_purchase_invoice(self)

	def validate(self):
		# Debit notes go through IB Debit Note only, as of 2026-08-12 — same
		# reasoning as the Sales Invoice side: native is_return posts its own
		# full GL/AR impact, same as IB Debit Note, running both risked
		# double-crediting. Only blocks NEW return invoices — existing
		# historical is_return PIs are untouched.
		if self.is_return and self.is_new():
			frappe.throw(_(
				"Don't create a return here — use <b>IB Debit Note</b> instead "
				"(Workspace → IB Debit Note → New)."
			))
		assert_domestic_pi_has_po_pr(self)
		_set_location_from_warehouse(self)
		_apply_purchase_location_gstin(self)
		_auto_correct_purchase_gst_template(self)
		_apply_purchase_cost_center(self)
		recalculate_purchase_items(self)
		super().validate()
		# Re-apply after super() resets cost centers to company default
		_apply_purchase_cost_center(self)

	def before_cancel(self):
		if not (self.get("custom_cancel_reason") or "").strip():
			frappe.throw(_("Fill in Cancellation Reason before cancelling this Purchase Invoice."))
