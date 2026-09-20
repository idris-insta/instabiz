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
	if frappe.db.exists("Delivery Note", trace_id):
		return _trace_from_dn(trace_id)

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


def _deliveries_for_batch(batch_name):
	"""Delivery Notes that shipped directly from this RM batch (no production —
	Path B). Grouped by DN, with the customer."""
	rows = frappe.get_all(
		"Delivery Note Item",
		filters={"custom_source_batch": batch_name, "docstatus": 1},
		fields=["parent", "item_code", "qty"],
	)
	out = {}
	for r in rows:
		d = out.setdefault(r.parent, {"delivery_note": r.parent, "qty": 0, "items": set()})
		d["qty"] += r.qty
		d["items"].add(r.item_code)
	for d in out.values():
		d["items"] = sorted(d["items"])
		d["customer"] = frappe.db.get_value("Delivery Note", d["delivery_note"], "customer_name")
	return list(out.values())


def _trace_from_batch(name):
	batch = frappe.db.get_value("IB Batch", name, _BATCH_FIELDS, as_dict=True)
	source = _source_doc(batch)
	work_orders = _wos_for_batch(name)
	fg_batches = _fg_batches_for_parent(name)
	sales_orders = sorted({wo.sales_order for wo in work_orders if wo.sales_order})
	deliveries = _deliveries_for_batch(name)

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
		"deliveries": deliveries,
		"serials": serials,
	}


def _trace_from_dn(name):
	dn = frappe.db.get_value(
		"Delivery Note", name,
		["name", "customer_name", "posting_date", "status", "set_warehouse"],
		as_dict=True,
	)
	rows = frappe.get_all(
		"Delivery Note Item", filters={"parent": name},
		fields=["item_code", "qty", "custom_source_batch", "against_sales_order"],
	)
	lines = []
	for r in rows:
		src_batch = (
			frappe.db.get_value("IB Batch", r.custom_source_batch, _BATCH_FIELDS, as_dict=True)
			if r.custom_source_batch else None
		)
		lines.append({
			"item_code": r.item_code, "qty": r.qty, "sales_order": r.against_sales_order,
			"source_batch": src_batch,
			"source": _source_doc(src_batch),
			"serials": _serials_for({"sales_order": r.against_sales_order, "item_code": r.item_code})
				if r.against_sales_order else [],
		})
	return {"kind": "delivery_note", "delivery_note": dn, "lines": lines}


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


# ---------------------------------------------------------------------------
# Delete guard (2026-09-20)
# ---------------------------------------------------------------------------
# Real incident this closes: IB-CTN-2026-00540::IS-51210V-029TRNANL::1 (a
# real Raw Material batch, real Container Import) was hard-deleted via
# frappe.delete_doc() on 2026-09-19 while 9+ real Work Orders — spanning
# multiple Sales Orders, some already Completed, one still In Progress —
# still carried it as their `source_batch`. Nothing broke immediately; the
# dangling Link only surfaced a day later as an opaque core Frappe error
# ("Could not find Source (RM) Batch: ...") the moment someone tried to
# Complete/advance one of the affected runs, with zero indication of why or
# what to do about it. IB Batch has no doc_events wired at all today (no
# hooks.py entry) — nothing has ever stopped this. Restoring the deleted
# record (from its own Deleted Document trace) fixed that one incident;
# this stops the next one at the source instead of after the fact.
def prevent_delete_if_traced(doc, method=None):
	"""before_delete hook for IB Batch — refuses to delete a batch that's
	still real genealogy: the source of a real Work Order, or a parent of a
	real Finished Good batch. A batch with nothing pointing at it (disposable
	test data, a genuine data-entry mistake caught immediately) still
	deletes freely — this only blocks the specific shape of mistake that
	silently orphans an in-use traceability chain.
	"""
	wo_count = frappe.db.count("IB Work Order", {"source_batch": doc.name})
	if wo_count:
		sample = frappe.get_all("IB Work Order", filters={"source_batch": doc.name},
			pluck="name", limit=5, order_by="creation asc")
		names = ", ".join(sample) + (f", +{wo_count - len(sample)} more" if wo_count > len(sample) else "")
		frappe.throw(_(
			"Cannot delete batch {0} — it's still the source batch on {1} Work Order(s) ({2}). "
			"Deleting it would silently break their traceability the next time one of them "
			"advances or completes."
		).format(doc.name, wo_count, names))
	fg_count = frappe.db.count("IB Batch", {"parent_batches": ["like", f"%{doc.name}%"]})
	if fg_count:
		sample = frappe.get_all("IB Batch", filters={"parent_batches": ["like", f"%{doc.name}%"]},
			pluck="name", limit=5)
		names = ", ".join(sample) + (f", +{fg_count - len(sample)} more" if fg_count > len(sample) else "")
		frappe.throw(_(
			"Cannot delete batch {0} — it's a parent of {1} finished-goods batch(es) ({2})."
		).format(doc.name, fg_count, names))
