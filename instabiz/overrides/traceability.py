"""instabiz.overrides.traceability

Forward + backward genealogy for an IB Batch, Work Order or IB FG Serial.
IB Batch / IB FG Serial are lightweight annotation doctypes — they do NOT touch
the native ERPNext stock ledger (that's Phase 3), so enabling traceability never
changes how stock moves in/out.
"""
from __future__ import annotations

import frappe
from frappe import _

_BATCH_FIELDS = [
	"name", "batch_id", "kind", "item", "item_name", "qty", "status",
	"source_type", "container_import", "purchase_receipt", "supplier",
	"supplier_lot", "received_date", "gsm", "width_mm", "work_order", "parent_batches",
]

_WO_FIELDS = [
	"name", "item_code", "item_name", "stage", "status", "machine",
	"order_sheet", "order_sheet_item", "sales_order", "source_batch", "fg_batch",
	"produced_serials", "target_qty", "target_uom", "started_at", "completed_at",
]

_SERIAL_FIELDS = [
	"name", "serial_no", "item_code", "item_name", "status",
	"work_order", "order_sheet", "sales_order", "source_batch", "fg_batch",
	"produced_on", "box_no", "width_mm", "length_mtr", "gsm",
	"delivery_note", "customer",
]


@frappe.whitelist()
def get_trace(trace_id):
	frappe.has_permission("IB Batch", "read", throw=True)
	trace_id = (trace_id or "").strip()
	if not trace_id:
		frappe.throw(_("Enter an IB Batch, Work Order or Serial id"))

	if frappe.db.exists("IB FG Serial", trace_id):
		return _trace_from_serial(trace_id)
	if frappe.db.exists("IB Work Order", trace_id):
		return _trace_from_wo(trace_id)
	if frappe.db.exists("IB Batch", trace_id):
		return _trace_from_batch(trace_id)

	item = frappe.db.get_value("Item Barcode", {"barcode": trace_id}, "parent")
	if item:
		return {
			"kind": "item",
			"item": item,
			"message": _("That is a SKU barcode — no batch or work-order context. Scan a batch label or open a work order to trace."),
		}
	frappe.throw(_("Nothing found for '{0}'").format(trace_id))


def _source_doc(batch):
	"""RM genealogy root — an import (IB Container Import) or a domestic purchase
	(Purchase Receipt)."""
	if not batch:
		return None
	if batch.get("container_import"):
		d = frappe.db.get_value(
			"IB Container Import", batch.container_import,
			["name", "container_no", "supplier", "import_date", "warehouse", "docstatus"],
			as_dict=True,
		)
		if d:
			d["source_type"] = "Container Import"
			d["dt"] = "IB Container Import"
		return d
	if batch.get("purchase_receipt"):
		d = frappe.db.get_value(
			"Purchase Receipt", batch.purchase_receipt,
			["name", "supplier", "supplier_name", "posting_date", "set_warehouse", "docstatus"],
			as_dict=True,
		)
		if d:
			d.update({
				"source_type": "Purchase Receipt", "dt": "Purchase Receipt",
				"container_no": "", "import_date": d.get("posting_date"),
				"warehouse": d.get("set_warehouse"),
				"supplier": d.get("supplier_name") or d.get("supplier"),
			})
		return d
	return None


def _wos_for_batch(batch_name):
	return frappe.get_all(
		"IB Work Order",
		filters={"source_batch": batch_name, "status": ["!=", "Cancelled"]},
		fields=_WO_FIELDS,
		order_by="creation asc",
	)


def _fg_batches_for_parent(batch_name):
	return frappe.get_all(
		"IB Batch",
		filters={"kind": "Finished Good", "parent_batches": ["like", f"%{batch_name}%"]},
		fields=_BATCH_FIELDS,
	)


def _serials_for(filters):
	return frappe.get_all("IB FG Serial", filters=filters, fields=_SERIAL_FIELDS, order_by="box_no asc")


def _trace_from_batch(name):
	batch = frappe.db.get_value("IB Batch", name, _BATCH_FIELDS, as_dict=True)
	source = _source_doc(batch)
	work_orders = _wos_for_batch(name)
	fg_batches = _fg_batches_for_parent(name)
	sales_orders = sorted({wo.sales_order for wo in work_orders if wo.sales_order})

	if batch.get("kind") == "Finished Good":
		serials = _serials_for({"fg_batch": name})
	else:
		fg_names = [f.name for f in fg_batches]
		serials = _serials_for({"fg_batch": ["in", fg_names]}) if fg_names else []

	return {
		"kind": "batch",
		"batch": batch,
		"source": source,
		"work_orders": work_orders,
		"fg_batches": fg_batches,
		"sales_orders": sales_orders,
		"serials": serials,
	}


def _trace_from_serial(name):
	sn = frappe.db.get_value("IB FG Serial", name, _SERIAL_FIELDS, as_dict=True)
	source_batch = (
		frappe.db.get_value("IB Batch", sn.source_batch, _BATCH_FIELDS, as_dict=True)
		if sn.get("source_batch") else None
	)
	fg_batch = (
		frappe.db.get_value("IB Batch", sn.fg_batch, _BATCH_FIELDS, as_dict=True)
		if sn.get("fg_batch") else None
	)
	source = _source_doc(source_batch)
	work_order = (
		frappe.db.get_value("IB Work Order", sn.work_order, _WO_FIELDS, as_dict=True)
		if sn.get("work_order") else None
	)
	siblings = _serials_for({"work_order": sn.work_order}) if sn.get("work_order") else [sn]

	return {
		"kind": "serial",
		"serial": sn,
		"source_batch": source_batch,
		"fg_batch": fg_batch,
		"source": source,
		"work_order": work_order,
		"siblings": siblings,
	}


def _trace_from_wo(name):
	wo = frappe.db.get_value("IB Work Order", name, _WO_FIELDS, as_dict=True)
	source_batch = (
		frappe.db.get_value("IB Batch", wo.source_batch, _BATCH_FIELDS, as_dict=True)
		if wo.get("source_batch") else None
	)
	source = _source_doc(source_batch)

	siblings = frappe.get_all(
		"IB Work Order",
		filters={"order_sheet_item": wo.order_sheet_item, "status": ["!=", "Cancelled"]},
		fields=["name", "stage", "status", "machine", "started_at", "completed_at"],
		order_by="creation asc",
	) if wo.get("order_sheet_item") else [wo]

	return {
		"kind": "work_order",
		"work_order": wo,
		"source_batch": source_batch,
		"source": source,
		"stages": siblings,
		"serials": _serials_for({"work_order": name}),
	}
