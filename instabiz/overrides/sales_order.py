"""instabiz.overrides.sales_order"""
import frappe
from frappe import _
from frappe.utils import add_days, nowdate
from frappe.model.mapper import get_mapped_doc  # pyright: ignore[reportMissingImports]
from erpnext.selling.doctype.sales_order.sales_order import SalesOrder  # pyright: ignore[reportMissingImports]

from instabiz.overrides.utils import (
    IbStatusMixin,
    recalculate_items,
    set_sales_person,
    sync_sales_team,
    reopen_sales_doc,
    item_postprocess,
    map_parent_fields,
    map_address_contact_fields,
    apply_location_cost_center,
    COMMON_PARENT_FIELD_MAP,
    COMMON_CHILD_FIELD_MAP,
    LOCATION_WAREHOUSE,
    _check_item_lifecycle,
    _check_customer_item_spec,
    _guard_document_attachments,
)
from instabiz.overrides.advance_approval import check_advance_approval
from instabiz.overrides.naming import autoname_sales_order
from instabiz.overrides.quotation import (
    _set_company_gstin_from_warehouse,
    _auto_correct_gst_template,
)


# ── Hook entry point ──────────────────────────────────────────────────────────

def recalculate_sales_order(doc, method=None):
    recalculate_items(doc)


# ── Document class ────────────────────────────────────────────────────────────

class CustomSalesOrder(IbStatusMixin, SalesOrder):
    STATUS_MAP = {
        "To Deliver and Bill": "Pending",
        "To Deliver":          "Pending",
        "To Bill":             "Dispatched",
        "Completed":           "Confirmed",
        "Closed":              "Confirmed",
    }

    def autoname(self):
        self.flags.name_set = True
        autoname_sales_order(self)

    def before_insert(self):
        set_sales_person(self)
        # Default ETD = order date + 8 days when not explicitly set — covers
        # API/mapper-created SOs; the form itself defaults this client-side too.
        if not self.delivery_date:
            self.delivery_date = add_days(self.transaction_date or nowdate(), 8)

    def validate(self):
        if not self.custom_location or self.custom_location == "Select":
            frappe.throw(_("Please select a Location before saving."))
        _set_company_gstin_from_warehouse(self)
        _auto_correct_gst_template(self)
        set_sales_person(self)
        sync_sales_team(self)
        recalculate_items(self)
        apply_location_cost_center(self)
        _check_item_lifecycle(self)
        _check_customer_item_spec(self)
        _guard_document_attachments(self)
        super().validate()

    def before_cancel(self):
        if not (self.custom_cancel_reason or "").strip():
            frappe.throw(_("Fill in Cancellation Reason before cancelling this Sales Order."))
        _check_no_active_production(self)

    def before_submit(self):
        # _check_credit_limit(self)  # temporarily disabled 2026-09-03 (user request) — re-enable when ready
        # _check_overdue_block(self)  # temporarily disabled 2026-09-03 (user request) — re-enable when ready
        check_advance_approval(self)


# ── Active production guard ───────────────────────────────────────────────────

def _check_no_active_production(doc):
    """Block cancelling a Sales Order that still has real production against
    it. Real gap this closes: before_cancel only ever required a reason
    string — a Sales Order with genuine in-progress (or completed but not
    yet delivered) Work Orders could be cancelled at any time with zero
    warning, leaving the underlying IB Order Sheet / IB Work Order records
    orphaned (referencing a now-cancelled order, with nothing ever
    reconciling that). Blocks on ANY non-cancelled run — Pending/In
    Progress/On Hold/Completed all represent real floor work already
    started or finished, not just "actively running right now" — the
    message tells the user to cancel those runs first (a deliberate,
    auditable action) rather than silently orphaning them.
    """
    order_sheets = frappe.get_all(
        "IB Order Sheet", filters={"sales_order": doc.name, "status": ["!=", "Cancelled"]},
        pluck="name",
    )
    if not order_sheets:
        return
    active = frappe.db.sql(
        """SELECT name, status FROM `tabIB Work Order`
           WHERE order_sheet IN %(sheets)s AND status != 'Cancelled'
           LIMIT 1""",
        {"sheets": order_sheets}, as_dict=True,
    )
    if active:
        frappe.throw(_(
            "Cannot cancel {0} — it has real production against it (Work Order {1}, status {2}). "
            "Cancel that Work Order in the Production module first if it genuinely shouldn't have happened."
        ).format(doc.name, active[0].name, active[0].status))


# ── Credit limit ──────────────────────────────────────────────────────────────

def _check_credit_limit(doc):
    """Block submit if customer exceeds credit limit AND oldest unpaid invoice
    is older than the configured credit days. Both conditions must be met."""
    row = frappe.db.get_value(
        "Customer Credit Limit",
        {"parent": doc.customer, "company": doc.company},
        ["credit_limit", "bypass_credit_limit_check", "custom_days"],
        as_dict=True,
    )
    if not row:
        return
    if row.bypass_credit_limit_check:
        return
    if row.credit_limit is None or row.custom_days is None:
        return

    result = frappe.db.sql(
        """
        SELECT
            SUM(outstanding_amount) AS total_outstanding,
            MIN(posting_date)       AS oldest_date
        FROM `tabSales Invoice`
        WHERE customer    = %(customer)s
          AND company     = %(company)s
          AND docstatus   = 1
          AND outstanding_amount > 0
        """,
        {"customer": doc.customer, "company": doc.company},
        as_dict=True,
    )
    if not result or not result[0].oldest_date:
        return

    from frappe.utils import date_diff, fmt_money, today
    total_outstanding = result[0].total_outstanding or 0
    overdue_days = date_diff(today(), result[0].oldest_date)

    if total_outstanding > row.credit_limit and overdue_days > row.custom_days:
        name = doc.customer_name or doc.customer
        outstanding_fmt = fmt_money(total_outstanding, currency="INR")
        limit_fmt = fmt_money(row.credit_limit, currency="INR")
        frappe.throw(
            f"Cannot submit: {name} has outstanding {outstanding_fmt} "
            f"(limit {limit_fmt}) with an invoice unpaid for {overdue_days} days "
            f"(allowed {row.custom_days} days). Clear dues or contact your manager."
        )


def _check_overdue_block(doc):
    """Block SO submit when customer has a 30d+ overdue flag set by overdue_alert scheduler.
    Sales Manager / System Manager get a warning instead of a hard block.
    """
    if not frappe.db.get_value("Customer", doc.customer, "custom_overdue_block"):
        return
    from instabiz.overrides.permissions import _is_privileged
    msg = (
        f"{doc.customer_name or doc.customer} has invoices overdue 30+ days. "
        "Clear outstanding dues before submitting new orders."
    )
    if _is_privileged(frappe.session.user):
        frappe.msgprint(msg, title="Overdue Warning", indicator="orange")
    else:
        frappe.throw(f"Cannot submit: {msg} Contact Sales Manager to override.")


# ── Reopen ────────────────────────────────────────────────────────────────────

def _so_pre_checks(name):
    """Block reopen if submitted DN or SI is still linked."""
    linked_dn = frappe.db.get_all(
        "Delivery Note Item",
        filters={"against_sales_order": name, "docstatus": 1},
        fields=["parent"],
        limit=1,
    )
    if linked_dn:
        frappe.throw(
            _("Cannot reopen: submitted Delivery Note {0} is linked to this order.").format(
                linked_dn[0].parent
            )
        )
    linked_si = frappe.db.get_all(
        "Sales Invoice Item",
        filters={"sales_order": name, "docstatus": 1},
        fields=["parent"],
        limit=1,
    )
    if linked_si:
        frappe.throw(
            _("Cannot reopen: submitted Sales Invoice {0} is linked to this order.").format(
                linked_si[0].parent
            )
        )


def _so_extra_steps(doc):
    """Revert linked Quotation statuses after the SO is reset to Draft."""
    for q_name in set(d.prevdoc_docname for d in doc.get("items") if d.prevdoc_docname):
        if frappe.db.get_value("Quotation", q_name, "docstatus") != 2:
            frappe.get_doc("Quotation", q_name).set_status(update=True)


@frappe.whitelist()
def reopen_sales_order(name):
    """Reopen a cancelled Sales Order, resetting it back to Draft (docstatus=0)."""
    reopen_sales_doc(
        "Sales Order", name, "Sales Order Item",
        pre_checks=_so_pre_checks,
        extra_steps=_so_extra_steps,
    )


# ── Mapper: Sales Order → Delivery Note ──────────────────────────────────────

def _dn_qty_adjustment_note(sales_order_item):
    """If production's Adjust Qty reconciliation (pcs_to_make/logs_to_make,
    see production.py's update_production_qty) set a value different from
    what was originally planned for this SO Item's Work Orders, return a
    human note describing it ("Packing: 100 → 95 PCS") so it isn't invisible
    on the Delivery Note — same "from → to" language the Production
    Dashboard's own adj badge already uses (_render_plan in
    ib_production_dashboard.js), just surfaced here too. Does not change the
    DN's own delivered qty — informational only. Returns None if this SO
    Item has no linked production, or nothing was ever adjusted."""
    osi = frappe.db.get_value(
        "IB Order Sheet Item", {"sales_order_item": sales_order_item}, "name"
    )
    if not osi:
        # Fallback for Order Sheet Items created before sales_order_item was
        # populated (2026-08-05) — match by the SO Item's own item_code on an
        # Order Sheet linked to this Sales Order.
        soi = frappe.db.get_value(
            "Sales Order Item", sales_order_item, ["parent", "item_code"], as_dict=True
        )
        if soi:
            osi = frappe.db.sql(
                """SELECT osi.name FROM `tabIB Order Sheet Item` osi
                   JOIN `tabIB Order Sheet` os ON os.name = osi.parent
                   WHERE os.sales_order = %s AND osi.item_code = %s LIMIT 1""",
                (soi.parent, soi.item_code),
            )
            osi = osi[0][0] if osi else None
    if not osi:
        return None

    wos = frappe.db.get_all(
        "IB Work Order",
        filters={"order_sheet_item": osi, "status": ["!=", "Cancelled"]},
        fields=["stage", "target_qty", "target_uom", "pcs_to_make", "logs_to_make"],
    )
    lines = []
    for wo in wos:
        # UOM-agnostic — the Adjust Qty dialog writes pcs_to_make OR logs_to_make
        # per the item's UOM; either one being set and different from target is
        # an adjustment worth surfacing (KG / ROLL / any UOM, not just PCS/SQMT).
        adjusted = wo.pcs_to_make or wo.logs_to_make or None
        if adjusted and adjusted != wo.target_qty:
            lines.append(f"{wo.stage}: {wo.target_qty} → {adjusted} {wo.target_uom or ''}".strip())
    if not lines:
        return None
    return "Qty adjusted in production — " + " | ".join(lines)


@frappe.whitelist()
def custom_make_delivery_note(source_name, target_doc=None, item_code=None, order_sheet_item=None):
    """Map a Sales Order to a Delivery Note.

    order_sheet_item: preferred scoping — the IB Order Sheet Item row (from
    IB Work Order.order_sheet_item) whose own sales_order_item field points
    at the *exact* Sales Order Item child row this WO is for. Resolved to a
    row-name match below, not an item_code match — a Sales Order can carry
    the same item_code on multiple separate lines with different quantities
    (a real, valid scenario — see item 119's identical Work Order grouping
    fix), so matching by item_code alone would pull every line sharing that
    code into the Delivery Note, including ones other stages haven't
    finished producing yet. item_code is kept as a fallback only for legacy
    WOs that predate the sales_order_item field being populated (2026-08-05).
    Blank (both) keeps the existing whole-order behavior used by the SO
    form's own "Create > Delivery Note" button.
    """
    sales_order_item_row = None
    if order_sheet_item:
        sales_order_item_row = frappe.db.get_value(
            "IB Order Sheet Item", order_sheet_item, "sales_order_item"
        )
    def postprocess_parent(source_doc, target_doc, source_parent):
        if source_doc.get("customer"):
            target_doc.customer = source_doc.customer
            target_doc.customer_name = source_doc.customer_name
            customer_doc = frappe.get_cached_doc("Customer", source_doc.customer)
            if not target_doc.get("customer_group") and customer_doc.customer_group:
                target_doc.customer_group = customer_doc.customer_group
            if not target_doc.get("territory") and customer_doc.territory:
                target_doc.territory = customer_doc.territory
        location = (source_doc.get("custom_location") or "").strip().lower()
        warehouse = LOCATION_WAREHOUSE.get(location)
        if warehouse and not target_doc.set_warehouse:
            target_doc.set_warehouse = warehouse
        map_parent_fields(source_doc, target_doc)
        map_address_contact_fields(source_doc, target_doc)

    location = (frappe.db.get_value("Sales Order", source_name, "custom_location") or "").strip().lower()
    _dn_warehouse = LOCATION_WAREHOUSE.get(location)

    def dn_item_postprocess(source_item, target_item, source_doc):
        item_postprocess(source_item, target_item, source_doc)
        if _dn_warehouse:
            target_item.warehouse = _dn_warehouse
        note = _dn_qty_adjustment_note(source_item.name)
        if note:
            target_item.custom_qty_adjustment_note = note

    return get_mapped_doc(
        "Sales Order",
        source_name,
        {
            "Sales Order": {
                "doctype": "Delivery Note",
                "validation": {"docstatus": ["=", 1]},
                "postprocess": postprocess_parent,
                "field_map": {
                    **COMMON_PARENT_FIELD_MAP,
                    "name": "against_sales_order",
                },
            },
            "Sales Order Item": {
                "doctype": "Delivery Note Item",
                "postprocess": dn_item_postprocess,
                "condition": (
                    (lambda row: row.qty != 0 and row.name == sales_order_item_row) if sales_order_item_row
                    else (lambda row: row.qty != 0 and row.item_code == item_code) if item_code
                    else (lambda row: row.qty != 0)
                ),
                "field_map": {
                    **COMMON_CHILD_FIELD_MAP,
                    "name":   "so_detail",
                    "parent": "against_sales_order",
                },
            },
            "Sales Taxes and Charges": {
                "doctype": "Sales Taxes and Charges",
                "add_if_empty": True,
            },
        },
        target_doc,
    )
