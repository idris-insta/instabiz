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

# Real bug, fixed: this listed the OLD per-stage-WO model's field names
# (item_code/item_name/stage/order_sheet_item/produced_serials/target_qty/
# target_uom) — none of which exist on the current WO-per-run schema
# (confirmed via meta: real fields are current_stage, no item_code/
# item_name/target_qty/target_uom at all on the parent — those live per-row
# on the `outputs` child table now, and there's no order_sheet_item either).
# Since frappe.db.get_value bypasses meta validation (raw SQL, unlike
# frappe.client.get_value — same distinction as the Adjust Qty fix), this
# never errored — it silently returned NULL/0 for every one of those
# fields on every real WO under the current model. Confirmed live:
# IB-WO-2026-29505 (real, Completed, 1 real IB FG Serial produced) showed
# a blank Current Stage and "Serials Produced: 0" directly above a
# "FINISHED UNITS: 1 serial(s)" section listing that exact real serial —
# a visible self-contradiction on a page whose whole purpose is being a
# trustworthy recall/audit tool. `stage` is aliased from the real
# current_stage column so ib_trace.js's existing w.stage reads need no
# change; item_code/item_name/target_qty/target_uom/produced_serials are
# resolved separately via _enrich_wo_list (outputs child table + a real
# IB FG Serial count), not selected here.
_WO_FIELDS = [
	"name", "current_stage as stage", "status", "machine",
	"order_sheet", "sales_order", "source_batch", "fg_batch",
	"started_at", "completed_at",
]

_SERIAL_FIELDS = [
	"name", "serial_no", "item_code", "item_name", "status",
	"work_order", "order_sheet", "sales_order", "source_batch", "fg_batch",
	"produced_on", "box_no", "width_mm", "length_mtr", "gsm",
	"delivery_note", "customer",
]


def _enrich_wo_list(wos):
	"""Attach item_code/item_name/target_qty/target_uom (first real output
	row — a run's outputs can be >1 dimension-variant/SKU, matching the
	same first-output approximation _command_center_runs already uses) and
	produced_serials (a real IB FG Serial count, not a parent-doctype field
	that doesn't exist) onto each WO dict in place. Batched — no N+1 for the
	batch/serial trace views that can list several WOs at once."""
	if not wos:
		return wos
	names = [w["name"] for w in wos]
	outs_by_wo = {}
	for o in frappe.get_all(
		"IB WO Output", filters={"parent": ["in", names]},
		fields=["parent", "item_code", "item_name", "planned_qty", "uom"],
		order_by="parent asc, idx asc",
	):
		outs_by_wo.setdefault(o.parent, o)  # first row per parent (idx asc), rest ignored
	serial_counts = {}
	for r in frappe.db.sql(
		"""SELECT work_order, COUNT(*) AS n FROM `tabIB FG Serial`
		   WHERE work_order IN %(names)s GROUP BY work_order""",
		{"names": names}, as_dict=True,
	):
		serial_counts[r.work_order] = r.n
	for w in wos:
		out = outs_by_wo.get(w["name"])
		w["item_code"] = out.item_code if out else ""
		w["item_name"] = out.item_name if out else ""
		w["target_qty"] = out.planned_qty if out else 0
		w["target_uom"] = out.uom if out else ""
		w["produced_serials"] = serial_counts.get(w["name"], 0)
	return wos


def _enrich_wo(wo):
	if not wo:
		return wo
	_enrich_wo_list([wo])
	return wo


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
	return _enrich_wo_list(frappe.get_all(
		"IB Work Order",
		filters={"source_batch": batch_name, "status": ["!=", "Cancelled"]},
		fields=_WO_FIELDS,
		order_by="creation asc",
	))


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
	work_order = _enrich_wo(
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
	wo = _enrich_wo(frappe.db.get_value("IB Work Order", name, _WO_FIELDS, as_dict=True))
	source_batch = (
		frappe.db.get_value("IB Batch", wo.source_batch, _BATCH_FIELDS, as_dict=True)
		if wo.get("source_batch") else None
	)
	source = _source_doc(source_batch)

	# Real bug, fixed: order_sheet_item is not a field on IB Work Order at all
	# under the WO-per-run model (it lives per-row on the `outputs` child
	# table instead) — wo.order_sheet_item was always None, so this always
	# fell through to the single-WO [wo] fallback, silently hiding any real
	# sibling runs (e.g. a length-split creates 2+ real runs against the
	# same output item). Resolved via a real join on IB WO Output.
	# sales_order_item instead — the actual shared key between two runs
	# producing the same Sales Order line.
	sales_order_item = frappe.db.get_value("IB WO Output", {"parent": name}, "sales_order_item")
	if sales_order_item:
		sibling_names = frappe.get_all(
			"IB WO Output",
			filters={"sales_order_item": sales_order_item},
			pluck="parent", distinct=True,
		)
		siblings = _enrich_wo_list(frappe.get_all(
			"IB Work Order",
			filters={"name": ["in", sibling_names], "status": ["!=", "Cancelled"]},
			fields=_WO_FIELDS,
			order_by="creation asc",
		)) if sibling_names else [wo]
	else:
		siblings = [wo]

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
