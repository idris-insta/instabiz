"""instabiz.overrides.dispatch_scan — mobile-camera scan-to-Delivery-Note.

Scan FG serials / FG batches with a phone camera, build a cart, then create
(and optionally submit) a Delivery Note from it. The Delivery Note itself is
the real stock-deduction document (native SLE/Bin via DN submit) — this module
only turns scans into cart rows and builds the DN.
instabiz.overrides.delivery_note._stamp_scanned_dispatch_units syncs the
IB FG Serial / IB Batch annotation layer once the DN actually submits.
"""
from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint, flt, nowdate

from instabiz.overrides.stock_scan import (
    _fg_warehouse_for,
    _require_stock_role,
    resolve_barcode,
)


@frappe.whitelist()
def scan_into_cart(barcode: str) -> dict:
    """Resolve one scan for the dispatch-cart flow. Only serial/batch scans are
    meaningful here (a bare SKU has no specific unit to ship) — rejects
    anything already spoken for so the phone warns immediately, not at
    DN-build time."""
    _require_stock_role()
    m = resolve_barcode(barcode)
    if m["kind"] == "serial":
        if m["serial_status"] == "Delivered":
            frappe.throw(_("{0} is already dispatched.").format(m["serial"]))
        if m["serial_status"] == "Cancelled":
            frappe.throw(_("{0} is cancelled — cannot dispatch.").format(m["serial"]))
    elif m["kind"] == "batch":
        if m["batch_kind"] != "Finished Good":
            frappe.throw(_("{0} is a raw-material batch — not shippable directly.").format(m["batch"]))
        if flt(m["batch_qty"]) <= 0:
            frappe.throw(_("{0} has no stock left to dispatch.").format(m["batch"]))
    else:
        frappe.throw(_("Scan a finished-unit or batch label, not a bare item barcode."))
    return m


def _fallback_rate(item_code: str) -> float:
    rate = frappe.db.get_value("Item", item_code, "standard_rate")
    if flt(rate):
        return flt(rate)
    last = frappe.db.get_value(
        "Sales Order Item", {"item_code": item_code, "docstatus": 1}, "rate",
        order_by="creation desc",
    )
    return flt(last) if last else 0.0


@frappe.whitelist()
def build_delivery_note(customer: str, lines: str, sales_order: str | None = None, submit: int = 0) -> dict:
    """lines: JSON list of {item_code, kind, unit_qty, serial_no|batch} — one
    entry per scanned unit. Groups by item_code into Delivery Note Item rows;
    every scanned unit is also attached as an IB DN Scan Unit child row for
    the on_submit hook to stamp (IB FG Serial → Delivered / IB Batch.qty--)."""
    _require_stock_role()
    if not customer:
        frappe.throw(_("Pick a customer first."))
    rows = json.loads(lines) if isinstance(lines, str) else (lines or [])
    if not rows:
        frappe.throw(_("Cart is empty — scan at least one unit."))

    by_item: dict[str, dict] = {}
    for r in rows:
        item_code = r["item_code"]
        g = by_item.setdefault(item_code, {"qty": 0.0, "units": []})
        g["qty"] += flt(r.get("unit_qty") or 0)
        g["units"].append(r)

    dn = frappe.new_doc("Delivery Note")
    dn.customer = customer
    dn.posting_date = nowdate()
    if sales_order:
        so = frappe.get_cached_doc("Sales Order", sales_order)
        dn.custom_location = so.custom_location
    else:
        last_loc = frappe.db.get_value(
            "Sales Order", {"customer": customer, "docstatus": 1}, "custom_location",
            order_by="creation desc",
        )
        if last_loc:
            dn.custom_location = last_loc

    for item_code, g in by_item.items():
        row = {
            "item_code": item_code,
            "qty": g["qty"],
            "warehouse": _fg_warehouse_for(item_code),
            "rate": _fallback_rate(item_code),
        }
        if sales_order:
            soi = frappe.db.get_value(
                "Sales Order Item", {"parent": sales_order, "item_code": item_code},
                ["name", "rate"], as_dict=True,
            )
            if soi:
                row["against_sales_order"] = sales_order
                row["so_detail"] = soi.name
                row["rate"] = soi.rate
        dn.append("items", row)

    for item_code, g in by_item.items():
        for u in g["units"]:
            dn.append("custom_scan_units", {
                "item_code": item_code,
                "serial_no": u.get("serial_no") if u.get("kind") == "serial" else None,
                "batch": u.get("batch") if u.get("kind") == "batch" else None,
                "qty": flt(u.get("unit_qty") or 0),
                "uom": frappe.db.get_value("Item", item_code, "stock_uom"),
            })

    dn.insert(ignore_permissions=True)
    if cint(submit):
        dn.submit()
    return {"delivery_note": dn.name, "submitted": bool(cint(submit))}
