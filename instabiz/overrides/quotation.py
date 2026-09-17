"""instabiz.overrides.quotation"""
import frappe
from frappe import _
from frappe.model.mapper import get_mapped_doc  # pyright: ignore[reportMissingImports]
from frappe.utils import add_months, getdate
from erpnext.selling.doctype.quotation.quotation import Quotation  # pyright: ignore[reportMissingImports]

from instabiz.overrides.utils import (
    IbStatusMixin,
    recalculate_items,
    recalc_item_margins,
    set_sales_person,
    sync_sales_team,
    reopen_sales_doc,
    item_postprocess,
    map_parent_fields,
    map_address_contact_fields,
    COMMON_PARENT_FIELD_MAP,
    COMMON_CHILD_FIELD_MAP,
    LOCATION_WAREHOUSE,
    _check_item_lifecycle,
    _check_customer_item_spec,
    _guard_document_attachments,
)
from instabiz.overrides.naming import autoname_quotation

DEFAULT_TERMS = "Quotation Terms"

# Address records may store gst_category in uppercase (legacy data).
# india_compliance's GSTIN_FORMATS uses title-case keys — normalize before validation fires.
_GST_CATEGORY_NORMALIZE = {v.upper(): v for v in [
	"Registered Regular", "Registered Composition", "Unregistered",
	"SEZ", "Overseas", "Deemed Export", "UIN Holders",
	"Tax Deductor", "Tax Collector", "Input Service Distributor",
]}

def _set_company_gstin_from_warehouse(doc):
	warehouse_name = LOCATION_WAREHOUSE.get((doc.custom_location or "").lower())
	if not warehouse_name:
		return
	gstin = frappe.get_cached_value("Warehouse", warehouse_name, "custom_gstin")
	if gstin:
		doc.company_gstin = gstin


_GST_INSTATE_TEMPLATE  = "Output GST In-state - IB"
_GST_OUTSTATE_TEMPLATE = "Output GST Out-state - IB"

# All templates that are valid for each direction — Transport variants are kept as-is
_GST_INSTATE_TEMPLATES  = {_GST_INSTATE_TEMPLATE,  "Output GST In-state + Transport - IB"}
_GST_OUTSTATE_TEMPLATES = {_GST_OUTSTATE_TEMPLATE, "Output GST Out-state + Transport - IB"}


def _auto_correct_gst_template(doc):
	"""Swap to correct in/out-state template based on GSTIN state codes."""
	if doc.get("custom_sale_type") == "Export":
		return
	if doc.currency and doc.currency != "INR":
		return
	company_gstin  = (doc.company_gstin or "")[:2]
	customer_gstin = (doc.billing_address_gstin or "")[:2]
	if not customer_gstin and doc.get("customer_address"):
		customer_gstin = (frappe.db.get_value("Address", doc.customer_address, "gstin") or "")[:2]
	if not customer_gstin:
		# billing_address_gstin/customer_address are usually filled by client-side
		# get_party_details JS on customer selection — on a freshly-saved doc that
		# can still be blank server-side. Customer.gstin is the same value's real
		# source and doesn't depend on that timing, so fall back to it directly
		# rather than silently skipping the in/out-state correction (which leaves
		# whatever template was already on the doc — wrong, if it's stale/default —
		# and lets india_compliance's own later, stricter check throw instead).
		customer_name = doc.get("customer") or (
			doc.get("party_name") if doc.get("quotation_to") == "Customer" else None
		)
		if customer_name:
			customer_gstin = (frappe.db.get_value("Customer", customer_name, "gstin") or "")[:2]
	if not company_gstin or not customer_gstin:
		return
	is_instate = company_gstin == customer_gstin
	correct_set = _GST_INSTATE_TEMPLATES if is_instate else _GST_OUTSTATE_TEMPLATES
	correct = _GST_INSTATE_TEMPLATE if is_instate else _GST_OUTSTATE_TEMPLATE
	if doc.taxes_and_charges in correct_set:
		return
	doc.taxes_and_charges = correct
	template_doc = frappe.get_cached_doc("Sales Taxes and Charges Template", correct)
	doc.set("taxes", [])
	for row in template_doc.taxes:
		doc.append("taxes", {
			"charge_type":            row.charge_type,
			"account_head":           row.account_head,
			"description":            row.description,
			"rate":                   row.rate,
			"included_in_print_rate": row.included_in_print_rate,
		})


# ── Hook entry point ──────────────────────────────────────────────────────────

def recalculate_quotation(doc, method=None):
    recalculate_items(doc)


# ── New-document defaults ─────────────────────────────────────────────────────

def _set_default_terms(doc):
    """Auto-populate tc_name and terms on new documents only."""
    if not doc.is_new():
        return
    if not doc.get("tc_name"):
        doc.tc_name = DEFAULT_TERMS
    if not doc.get("terms"):
        terms_text = frappe.db.get_value("Terms and Conditions", doc.tc_name, "terms")
        if terms_text:
            doc.terms = terms_text


# ── Document class ────────────────────────────────────────────────────────────

class CustomQuotation(IbStatusMixin, Quotation):
    STATUS_MAP = {
        "Open":              "Pending",
        "Replied":           "Pending",
        "Expired":           "Pending",
        "Ordered":           "Confirmed",
        "Partially Ordered": "Confirmed",
        "Lost":              "Cancelled",
    }

    def autoname(self):
        self.flags.name_set = True
        autoname_quotation(self)

    def before_insert(self):
        _set_default_terms(self)
        set_sales_person(self)

    def validate(self):
        if not self.custom_location or self.custom_location == "Select":
            frappe.throw(_("Please select a Location before saving."))
        if self.get("custom_sale_type") == "Export" or (self.currency and self.currency != "INR"):
            self.taxes_and_charges = None
            self.set("taxes", [])
        _set_company_gstin_from_warehouse(self)
        _auto_correct_gst_template(self)
        if self.gst_category:
            self.gst_category = _GST_CATEGORY_NORMALIZE.get(
                self.gst_category.upper(), self.gst_category
            )
        set_sales_person(self)
        sync_sales_team(self)
        recalculate_items(self)
        recalc_item_margins(self)
        _check_item_lifecycle(self)
        _check_customer_item_spec(self)
        _guard_document_attachments(self)
        # Ensure valid_till is never before transaction_date.
        # valid_till is hidden from users; on reopened/amended docs the old value
        # can be stale, causing ERPNext's validate_valid_till() to throw.
        if not self.valid_till or getdate(self.valid_till) < getdate(self.transaction_date):
            self.valid_till = add_months(self.transaction_date, 1)
        super().validate()


# ── Reopen ────────────────────────────────────────────────────────────────────

@frappe.whitelist()
def reopen_quotation(name):
    """Reopen a cancelled Quotation, resetting it back to Draft (docstatus=0)."""
    reopen_sales_doc("Quotation", name, "Quotation Item")


# ── Mapper: Quotation → Sales Order ──────────────────────────────────────────

@frappe.whitelist()
def custom_make_sales_order(source_name, target_doc=None):
    def postprocess_parent(source_doc, target_doc, source_parent):
        if source_doc.get("quotation_to") == "Customer":
            target_doc.customer = source_doc.party_name
            target_doc.customer_name = source_doc.customer_name
            customer_doc = frappe.get_cached_doc("Customer", source_doc.party_name)
            if not target_doc.get("customer_group") and customer_doc.customer_group:
                target_doc.customer_group = customer_doc.customer_group
            if not target_doc.get("territory") and customer_doc.territory:
                target_doc.territory = customer_doc.territory
        map_parent_fields(source_doc, target_doc)
        map_address_contact_fields(source_doc, target_doc)

    return get_mapped_doc(
        "Quotation",
        source_name,
        {
            "Quotation": {
                "doctype": "Sales Order",
                "validation": {"docstatus": ["=", 1]},
                "postprocess": postprocess_parent,
                "field_map": {
                    **COMMON_PARENT_FIELD_MAP,
                    "name":             "quotation",
                    "party_name":       "customer",
                    "transaction_date": "transaction_date",
                },
            },
            "Quotation Item": {
                "doctype": "Sales Order Item",
                "postprocess": item_postprocess,
                "condition": lambda row: row.qty != 0,
                "field_map": {
                    **COMMON_CHILD_FIELD_MAP,
                    "parent":           "prevdoc_docname",
                    "name":             "quotation_item",
                },
            },
            "Sales Taxes and Charges": {
                "doctype": "Sales Taxes and Charges",
                "add_if_empty": True,
            },
        },
        target_doc,
    )
