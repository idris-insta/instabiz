"""instabiz.overrides.delivery_note"""
import frappe
from frappe.utils import flt
from erpnext.stock.doctype.delivery_note.delivery_note import (
    DeliveryNote,  # pyright: ignore[reportMissingImports]
)
from frappe.model.mapper import get_mapped_doc  # pyright: ignore[reportMissingImports]

from instabiz.overrides.naming import autoname_delivery_note
from instabiz.overrides.quotation import _auto_correct_gst_template, drop_gst
from instabiz.overrides.utils import (
    COMMON_CHILD_FIELD_MAP,
    COMMON_PARENT_FIELD_MAP,
    LOCATION_COMPANY_ADDRESS,
    LOCATION_COMPANY_GSTIN,
    IbStatusMixin,
    apply_location_cost_center,
    item_postprocess,
    map_address_contact_fields,
    map_parent_fields,
    recalculate_items,
    set_sales_person,
    sync_sales_team,
    _guard_document_attachments,
)

# ── Document class ────────────────────────────────────────────────────────────

class CustomDeliveryNote(IbStatusMixin, DeliveryNote):
    STATUS_MAP = {
        "To Bill":   "Pending",
        "Completed": "Confirmed",
        "Closed":    "Confirmed",
    }

    def autoname(self):
        self.flags.name_set = True
        autoname_delivery_note(self)

    def before_insert(self):
        set_sales_person(self)

    def validate(self):
        if not self.custom_location or self.custom_location == "Select":
            frappe.throw(frappe._("Please select a Location before saving."))
        loc = (self.custom_location or "").lower()
        addr = LOCATION_COMPANY_ADDRESS.get(loc)
        if addr:
            self.company_address = addr
            self.dispatch_address_name = None
        gstin = LOCATION_COMPANY_GSTIN.get(loc)
        if gstin:
            self.company_gstin = gstin
        drop_gst(self)  # GST goes on the Sales Invoice only
        set_sales_person(self)
        sync_sales_team(self)
        recalculate_items(self)
        apply_location_cost_center(self)
        _guard_document_attachments(self)
        _set_item_weights(self)
        super().validate()

    def on_update_after_submit(self):
        recalculate_items(self)
        try:
            super().on_update_after_submit()
        except AttributeError:
            pass

    def before_cancel(self):
        if not (self.custom_cancel_reason or "").strip():
            frappe.throw(frappe._("Fill in Cancellation Reason before cancelling this Delivery Note."))

    def before_submit(self):
        _auto_create_sr_if_needed(self)

    def on_submit(self):
        super().on_submit()
        link_dn_source_batches(self)
        _stamp_scanned_dispatch_units(self)
        _auto_create_gate_pass(self)  # IB_DN_AUTO_GATE_PASS_V1

    def on_cancel(self):
        super().on_cancel()
        for row in self.items:
            if row.get("custom_source_batch"):
                frappe.db.set_value("Delivery Note Item", row.name, "custom_source_batch", None,
                                    update_modified=False)
        _reverse_scanned_dispatch_units(self)


# ── Direct-B2B traceability: link the RM batch a non-produced line shipped from ─

def link_dn_source_batches(doc, method=None):
    """For any Delivery Note line that did NOT come from production (no IB FG
    Serial for this Sales Order + item), stamp it with the raw-material IB Batch
    it shipped from — FIFO, oldest Active batch of that item first. Lets a
    directly-sold (imported-and-resold) unit still trace back to its container
    and supplier lot. Informational only; does not change the shipped qty."""
    try:
        for row in doc.items:
            if row.get("custom_source_batch"):
                continue
            so = row.get("against_sales_order")
            # Came from production? then the serial/FG-batch chain already covers it.
            if so and frappe.db.exists(
                "IB FG Serial", {"sales_order": so, "item_code": row.item_code}
            ):
                continue
            rm = frappe.db.get_all(
                "IB Batch",
                filters={"item": row.item_code, "kind": "Raw Material", "status": "Active"},
                fields=["name"],
                order_by="received_date asc, creation asc",
                limit=1,
            )
            if rm:
                frappe.db.set_value(
                    "Delivery Note Item", row.name, "custom_source_batch", rm[0].name,
                    update_modified=False,
                )
    except Exception:
        frappe.log_error("IB DN batch link", frappe.get_traceback())


# ── Mobile scan-to-dispatch: stamp units scanned by ib-dispatch-scan on submit ──

def _stamp_scanned_dispatch_units(doc):
    """Every IB FG Serial / IB Batch row scanned into this DN via ib-dispatch-scan
    is recorded on doc.custom_scan_units at draft-build time (see
    instabiz.overrides.dispatch_scan.build_delivery_note). Real stock deduction
    already happened above via the normal DN submit (SLE/Bin) — this only syncs
    the annotation layer (IB FG Serial.status / IB Batch.qty) so traceability
    and the scan page's dupe/over-scan guards stay accurate. Idempotent and
    non-blocking — a failure here must never block a real DN submit."""
    try:
        for row in (doc.get("custom_scan_units") or []):
            if row.get("serial_no"):
                sn = frappe.db.get_value("IB FG Serial", row.serial_no, "status")
                if sn == "Delivered":
                    continue
                frappe.db.set_value(
                    "IB FG Serial", row.serial_no,
                    {"status": "Delivered", "delivery_note": doc.name, "customer": doc.customer},
                    update_modified=False,
                )
            elif row.get("batch"):
                frappe.db.set_value(
                    "IB Batch", row.batch, "qty",
                    flt(frappe.db.get_value("IB Batch", row.batch, "qty")) - flt(row.qty),
                    update_modified=False,
                )
    except Exception:
        frappe.log_error("IB DN scan-unit stamp", frappe.get_traceback())


def _reverse_scanned_dispatch_units(doc):
    """Mirror of _stamp_scanned_dispatch_units for DN cancel — puts scanned
    serials back In Stock and restores batch qty. Non-blocking, same reasoning
    as above."""
    try:
        for row in (doc.get("custom_scan_units") or []):
            if row.get("serial_no"):
                if frappe.db.get_value("IB FG Serial", row.serial_no, "delivery_note") != doc.name:
                    continue
                frappe.db.set_value(
                    "IB FG Serial", row.serial_no,
                    {"status": "In Stock", "delivery_note": None, "customer": None},
                    update_modified=False,
                )
            elif row.get("batch"):
                frappe.db.set_value(
                    "IB Batch", row.batch, "qty",
                    flt(frappe.db.get_value("IB Batch", row.batch, "qty")) + flt(row.qty),
                    update_modified=False,
                )
    except Exception:
        frappe.log_error("IB DN scan-unit reverse", frappe.get_traceback())


# ── Per-row weight (same carton-weight math as IB Packing List) ───────────────

def _set_item_weights(dn):
    for row in dn.items:
        item = frappe.get_cached_doc("Item", row.item_code)
        rolls_per_box = item.custom_rolls_per_box or 1
        carton_wt = item.custom_carton_weight_kg or 0
        carton_cbm = flt(item.get("custom_carton_cbm") or 0)
        boxes = flt(row.qty) / rolls_per_box if rolls_per_box else flt(row.qty)
        row.custom_total_weight_kg = round(boxes * carton_wt, 2)
        if hasattr(row, "custom_cbm"):
            row.custom_cbm = round(boxes * carton_cbm, 4)
    dn.total_net_weight = sum(flt(row.custom_total_weight_kg) for row in dn.items)
    if hasattr(dn, "custom_total_cbm"):
        dn.custom_total_cbm = sum(flt(getattr(row, "custom_cbm", 0) or 0) for row in dn.items)

def _auto_create_sr_if_needed(dn):
    """Check actual stock per item/warehouse. If any row is short, create a
    draft Stock Reconciliation covering the shortfall and throw with a link."""
    from frappe.utils import today

    company = frappe.defaults.get_global_default("company") or dn.company

    # Aggregate required qty per (item_code, warehouse)
    required: dict[tuple, float] = {}
    for row in dn.items:
        if not row.item_code or not row.warehouse:
            continue
        item_has_batch = frappe.db.get_value("Item", row.item_code, "has_batch_no")
        if item_has_batch:
            continue  # batch items need bundles — skip
        key = (row.item_code, row.warehouse)
        required[key] = required.get(key, 0.0) + (row.qty or 0.0)

    if not required:
        return

    # Fetch actual stock in one query
    keys_list = list(required.keys())
    item_codes = list({k[0] for k in keys_list})
    warehouses  = list({k[1] for k in keys_list})

    bins = frappe.db.sql(
        """SELECT item_code, warehouse, actual_qty
           FROM `tabBin`
           WHERE item_code IN %(items)s AND warehouse IN %(wh)s""",
        {"items": item_codes, "wh": warehouses},
        as_dict=True,
    )
    actual: dict[tuple, float] = {(b.item_code, b.warehouse): b.actual_qty for b in bins}

    shortfall = [
        {"item_code": ic, "warehouse": wh, "needed": qty, "have": actual.get((ic, wh), 0.0)}
        for (ic, wh), qty in required.items()
        if actual.get((ic, wh), 0.0) < qty
    ]

    if not shortfall:
        return

    # Fetch expense account for stock adjustment
    expense_account = frappe.db.get_value("Company", company, "stock_adjustment_account") \
        or "Stock Adjustment - IB"

    sr = frappe.get_doc({
        "doctype": "Stock Reconciliation",
        "purpose": "Stock Reconciliation",
        "posting_date": today(),
        "company": company,
        "expense_account": expense_account,
        "items": [
            {
                "item_code": row["item_code"],
                "warehouse": row["warehouse"],
                # Set qty to exactly what this DN needs
                "qty": row["needed"],
                "valuation_rate": frappe.db.get_value("Item", row["item_code"], "valuation_rate") or 1.0,
            }
            for row in shortfall
        ],
    })
    sr.insert(ignore_permissions=True)
    # Commit now — the frappe.throw() below aborts this request, and without
    # an explicit commit here, frappe's own exception handler rolls back the
    # whole transaction (including this SR), leaving the error message
    # pointing at a Stock Reconciliation that was never actually persisted.
    frappe.db.commit()

    lines = "".join(
        f"<li>{r['item_code']} — need {r['needed']}, have {r['have']} in {r['warehouse']}</li>"
        for r in shortfall
    )
    sr_link = f'<a href="/app/stock-reconciliation/{sr.name}">{sr.name}</a>'
    frappe.throw(
        frappe._(
            "Insufficient stock for {0} item(s). A draft Stock Reconciliation {1} has been "
            "created. Submit it to add stock, then re-submit this Delivery Note.<ul>{2}</ul>"
        ).format(len(shortfall), sr_link, lines),
        title=frappe._("Stock Reconciliation Required"),
    )


# ── Mapper: Delivery Note → Sales Invoice ─────────────────────────────────────

@frappe.whitelist()
def custom_make_sales_invoice(source_name, target_doc=None):
    def postprocess_parent(source_doc, target_doc, source_parent):
        if source_doc.get("customer"):
            target_doc.customer = source_doc.customer
            target_doc.customer_name = source_doc.customer_name
        map_parent_fields(source_doc, target_doc)
        map_address_contact_fields(source_doc, target_doc)
        # --- BEGIN todo52_copy_vehicle_si ---
        try:
            from instabiz.overrides.gate_locks import copy_vehicle_dn_to_target
            copy_vehicle_dn_to_target(source_doc, target_doc)
        except Exception:
            pass
        # --- END todo52_copy_vehicle_si ---


    def _finalize(source_doc, target_doc):
        # Real bug, fixed here: core ERPNext's own make_sales_invoice mapper
        # (erpnext/stock/doctype/delivery_note/delivery_note.py) passes
        # set_missing_values as get_mapped_doc's top-level `postprocess` arg,
        # which frappe's mapper runs only AFTER every child table (Delivery
        # Note Item → Sales Invoice Item) has been mapped onto target_doc.
        # This custom mapper instead called target.run_method("set_missing_values")
        # from inside the per-table "postprocess" key on the "Delivery Note"
        # block — frappe.model.mapper.map_doc() invokes that BEFORE the
        # caller ever maps child tables (get_mapped_doc's own loop over
        # source_doc.meta.get_table_fields() runs after map_doc() returns),
        # so target_doc.items was still empty every time it ran and
        # set_missing_item_details() had nothing to iterate. Delivery Note
        # Item has no income_account field at all (DN doesn't post GL), so
        # income_account can only ever be resolved via Sales Invoice's own
        # set_missing_values() (Item Default per company) once items exist —
        # confirmed live, blocked submit with "Mandatory fields required...
        # Income Account" despite the Item's own Item Default having it set
        # correctly. Moving the call to the top-level postprocess arg (this
        # function) fixes the ordering.
        target_doc.run_method("set_missing_values")

    return get_mapped_doc(
        "Delivery Note",
        source_name,
        {
            "Delivery Note": {
                "doctype": "Sales Invoice",
                "validation": {"docstatus": ["=", 1]},
                "postprocess": postprocess_parent,
                "field_map": {
                    **COMMON_PARENT_FIELD_MAP,
                    "name": "delivery_note",
                },
            },
            "Delivery Note Item": {
                "doctype": "Sales Invoice Item",
                "postprocess": item_postprocess,
                "condition": lambda row: row.qty != 0,
                "field_map": {
                    **COMMON_CHILD_FIELD_MAP,
                    "name":   "dn_detail",
                    "parent": "delivery_note",
                },
            },
            "Sales Taxes and Charges": {
                "doctype": "Sales Taxes and Charges",
                "add_if_empty": True,
            },
        },
        target_doc,
        _finalize,
    )

def _auto_create_gate_pass(dn):
    """Create Outward IB Gate Pass on DN submit (idempotent). IB_DN_AUTO_GATE_PASS_V1"""
    try:
        from instabiz.instabiz.doctype.ib_gate_pass.ib_gate_pass import auto_create_for_delivery_note
        name = auto_create_for_delivery_note(dn.name)
        if name:
            frappe.msgprint(
                frappe._("Gate Pass {0} created").format(
                    frappe.utils.get_link_to_form("IB Gate Pass", name)
                ),
                indicator="green",
                alert=True,
            )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Auto Gate Pass from Delivery Note")
