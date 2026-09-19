"""instabiz.overrides.sales_invoice"""
import frappe
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice  # pyright: ignore[reportMissingImports]

from instabiz.overrides.utils import LOCATION_COMPANY_ADDRESS, LOCATION_COMPANY_GSTIN, IbStatusMixin, apply_location_cost_center, recalculate_items, set_sales_person, sync_sales_team, _guard_document_attachments
from instabiz.overrides.naming import autoname_sales_invoice
from instabiz.overrides.quotation import _auto_correct_gst_template


# ── Document class ────────────────────────────────────────────────────────────

class CustomSalesInvoice(IbStatusMixin, SalesInvoice):
    # All target values ("Unpaid", "Overdue", "Paid") are already valid ERPNext
    # SI status options so no _validate_selects override is needed — the mixin's
    # default swap-to-Draft guard still runs harmlessly.
    STATUS_MAP = {
        "Partly Paid":                "Unpaid",
        "Unpaid and Discounted":      "Unpaid",
        "Partly Paid and Discounted": "Unpaid",
        "Submitted":                  "Unpaid",
        "Overdue and Discounted":     "Overdue",
        "Credit Note Issued":         "Paid",
    }

    def autoname(self):
        self.flags.name_set = True
        autoname_sales_invoice(self)

    def before_cancel(self):
        if not (self.custom_cancel_reason or "").strip():
            frappe.throw(frappe._("Fill in Cancellation Reason before cancelling this Sales Invoice."))

    def on_cancel(self):
        super().on_cancel()
        # Ensure outstanding_amount is zeroed — ERPNext should handle this but
        # occasionally leaves a stale value when payment linkages are unusual.
        if self.outstanding_amount != 0:
            frappe.db.set_value("Sales Invoice", self.name, "outstanding_amount", 0, update_modified=False)

    def before_insert(self):
        set_sales_person(self)

    def validate(self):
        # Credit notes go through IB Credit Note only, as of 2026-08-12 — it's a
        # full independent GL/AR/stock posting, same as native is_return; running
        # both live risked double-crediting Accounts Receivable for the same
        # return. Only blocks NEW return invoices — existing historical is_return
        # SIs are untouched and still cancel/report normally.
        if self.is_return and self.is_new():
            frappe.throw(frappe._(
                "Don't create a return here — use <b>IB Credit Note</b> instead "
                "(Workspace → IB Credit Note → New)."
            ))
        if not self.custom_location or self.custom_location == "Select":
            frappe.throw(frappe._("Please select a Location before saving."))
        set_sales_person(self)
        sync_sales_team(self)
        recalculate_items(self)
        _guard_document_attachments(self)
        self._pre_transport_charges()   # set freight Actual row before ERPNext calc
        super().validate()
        self._apply_transport_gst()     # add extra GST on transport after ERPNext calc
        # Must run AFTER super().validate() — ERPNext's set_missing_values() resets
        # company_gstin and cost_center to company defaults; re-apply location values last.
        self._apply_location_gstin()
        apply_location_cost_center(self)
        before = (self.taxes_and_charges, len(self.taxes or []))
        if (self.taxes_and_charges or "").startswith("Output GST") and not any(
                row.charge_type != "Actual" for row in (self.taxes or [])):
            self.taxes_and_charges = None  # template named but its GST rows missing — re-apply
        _auto_correct_gst_template(self)
        if not self.is_return and (self.taxes_and_charges, len(self.taxes or [])) != before:
            # the template was set after ERPNext totalled the invoice — total again or the
            # GST rows stay at 0 (177 dev invoices had a template but no tax)
            self.calculate_taxes_and_totals()

    # ── Transport charges helpers ──────────────────────────────────────────────

    def _pre_transport_charges(self):
        """Set Actual freight row amount from custom_transport_charges BEFORE
        super().validate() so ERPNext includes it in total_taxes_and_charges."""
        from frappe.utils import flt
        transport = flt(self.get("custom_transport_charges") or 0)
        for tax in self.taxes:
            if tax.charge_type == "Actual" and "freight" in (tax.account_head or "").lower():
                tax.tax_amount = transport
                break

    def _apply_transport_gst(self):
        """After ERPNext calculates taxes On Net Total (items only), add the
        proportional GST on transport charges to each GST row and update totals.

        Formula: GST row extra = transport × row_rate / 100
        Grand total = items + transport + GST on (items + transport)
        """
        from frappe.utils import flt
        transport = flt(self.get("custom_transport_charges") or 0)
        if not transport:
            return

        has_freight_row = any(
            t.charge_type == "Actual" and "freight" in (t.account_head or "").lower()
            for t in self.taxes
        )

        # Add transport × rate to every On Net Total GST row
        total_extra = 0.0
        for tax in self.taxes:
            if tax.charge_type == "On Net Total" and flt(tax.rate) > 0:
                extra = flt(transport * flt(tax.rate) / 100, 2)
                tax.tax_amount = flt(tax.tax_amount) + extra
                tax.base_tax_amount = flt(tax.base_tax_amount) + extra
                total_extra += extra

        # If no freight Actual row exists, transport itself isn't in totals yet —
        # add it now and append a display row so it shows on the invoice.
        if not has_freight_row:
            total_extra += transport
            self.append("taxes", {
                "charge_type": "Actual",
                "account_head": "Freight and Forwarding Charges - IB",
                "description": "Transport Charges",
                "tax_amount": transport,
                "base_tax_amount": transport,
            })

        if total_extra:
            self.total_taxes_and_charges = flt(self.total_taxes_and_charges) + total_extra
            self.grand_total            = flt(self.grand_total) + total_extra
            self.base_grand_total       = flt(self.base_grand_total) + total_extra
            self.outstanding_amount     = flt(self.outstanding_amount) + total_extra
            if self.rounded_total is not None:
                self.rounded_total = flt(self.grand_total, 2)
                self.base_rounded_total = flt(self.rounded_total * flt(self.conversion_rate or 1), 2)
            # super().validate() already computed in_words/base_in_words off the
            # pre-transport grand_total/rounded_total (ERPNext's
            # AccountsController.validate() calls set_total_in_words() before this
            # method runs) — recompute now so the printed "Amount in Words" on the
            # Tax Invoice matches the actual (post-transport) Grand Total instead
            # of silently showing a stale, smaller figure.
            self.set_total_in_words()

    def _apply_location_gstin(self):
        loc = (self.custom_location or "").lower()
        addr = LOCATION_COMPANY_ADDRESS.get(loc)
        if addr:
            self.company_address = addr
        gstin = LOCATION_COMPANY_GSTIN.get(loc)
        if gstin:
            self.company_gstin = gstin
