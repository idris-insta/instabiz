from __future__ import annotations

import base64
import io

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, cint

# Sane upper bound on a single manual "Print Label" count-prompt run (Draft
# containers, generate_item_labels()) — this only guards the ad-hoc "how many
# labels?" number an operator types by hand, which is the one label-count
# surface prone to a fat-fingered typo (an extra zero) with no cross-check
# against anything real. Deliberately NOT applied to no_of_boxes at submit —
# that's a real recorded quantity from the actual shipment data, and hard-
# blocking a genuinely large stock receipt just because it would print many
# label pages would be a worse outcome than the slow render it prevents.
_MAX_LABEL_COUNT = 2000


def _is_sqmt(uom: str) -> bool:
	return (uom or "").strip().upper() == "SQMT"


class IBContainerImport(Document):
	# ── Lifecycle ─────────────────────────────────────────────────────────────

	def validate(self) -> None:
		for row in self.items:
			if _is_sqmt(row.stock_uom):
				# Area UOM: qty = area of one roll × number of rolls.
				# area_per_unit mirrors the Sales Order Item SQMT rule
				# (width_mm/1000 × length_mtr), then × the roll count.
				row.area_per_unit = flt(row.width_mm) / 1000.0 * flt(row.length_mtr)
				row.total_qty = flt(row.no_of_boxes) * flt(row.area_per_unit)
			else:
				row.total_qty = flt(row.no_of_boxes) * flt(row.qty_per_box)
			row.barcode = _resolve_barcode(row.item_code)
		_apply_landed_cost(self)

	def before_submit(self) -> None:
		for row in self.items:
			if cint(row.no_of_boxes) <= 0:
				frappe.throw(_("Row #{0}: No. of Boxes / Rolls must be greater than 0").format(row.idx))
			if _is_sqmt(row.stock_uom):
				if flt(row.width_mm) <= 0 or flt(row.length_mtr) <= 0:
					frappe.throw(_("Row #{0}: Width (MM) and Length (MTR) are required for SQMT items").format(row.idx))
			elif flt(row.qty_per_box) <= 0:
				frappe.throw(_("Row #{0}: Qty per Box must be greater than 0").format(row.idx))
			if not row.barcode:
				frappe.throw(_("Row #{0}: barcode could not be resolved for {1}").format(row.idx, row.item_code))

	def on_submit(self) -> None:
		stock_entry = _make_stock_entry(self)
		self.db_set("stock_entry", stock_entry.name)
		for row in self.items:
			_make_batch(self, row)

	def on_cancel(self) -> None:
		if self.stock_entry:
			se = frappe.get_doc("Stock Entry", self.stock_entry)
			if se.docstatus == 1:
				se.cancel()
		for b in frappe.get_all("IB Batch", {"container_import": self.name}, pluck="name"):
			# Don't leave Work Orders pointing at a batch that's about to vanish —
			# a dangling source_batch Link blocks the WO from ever starting again.
			for wo in frappe.get_all("IB Work Order", {"source_batch": b}, pluck="name"):
				frappe.db.set_value("IB Work Order", wo, "source_batch", None, update_modified=False)
			frappe.delete_doc("IB Batch", b, ignore_permissions=True, force=True)


# ── Barcode resolution ───────────────────────────────────────────────────────

def _resolve_barcode(item_code: str) -> str:
	if not item_code:
		return ""
	existing = frappe.db.get_value("Item Barcode", {"parent": item_code}, "barcode")
	if existing:
		return existing

	item = frappe.get_doc("Item", item_code)
	item.append("barcodes", {"barcode": item_code, "barcode_type": "Code128"})
	item.save(ignore_permissions=True)
	return item_code


@frappe.whitelist()
def get_barcode_data_uri(value: str, vertical: int = 0) -> str:
	"""High-res Code128 PNG. Rendered big at source so it stays sharp when the
	4x4-per-page sticker scales it down. `vertical=1` rotates the PNG 90° here
	(server-side) so the print format can place a plain tall <img> — wkhtmltopdf
	does not render CSS `transform: rotate` reliably."""
	import barcode as barcode_lib
	from barcode.writer import ImageWriter

	code = barcode_lib.get("code128", value, writer=ImageWriter())
	buf = io.BytesIO()
	# Human-readable digits under the bars, like a normal barcode — but only for
	# the non-rotated orientation. Baking write_text=True into a PNG that then
	# gets rotate(90) below produces garbled overlapping text (tried it, it's
	# unreadable) — the rotated/vertical labels get their HRI text as plain
	# rotated CSS text in the print format instead, not baked into the image.
	options = {
		"quiet_zone": 2,
		"module_width": 0.30,
		"module_height": 14.0,
		"dpi": 300,
	}
	if int(vertical):
		options["write_text"] = False
	else:
		options["write_text"] = True
		options["text_distance"] = 5.0
		options["font_size"] = 9
	code.write(buf, options=options)
	if int(vertical):
		from PIL import Image

		img = Image.open(buf).rotate(90, expand=True)
		buf = io.BytesIO()
		img.save(buf, format="PNG")
	encoded = base64.b64encode(buf.getvalue()).decode()
	return f"data:image/png;base64,{encoded}"


@frappe.whitelist()
def get_qr_data_uri(value: str, scale: int = 10) -> str:
	"""QR PNG at a high source scale (10 px/module) with error-correction M so a
	phone still reads it after the sticker downscales it to ~16-18mm."""
	import pyqrcode

	encoded = pyqrcode.create(str(value), error="M").png_as_base64_str(
		scale=int(scale), quiet_zone=3,
	)
	return f"data:image/png;base64,{encoded}"


# ── Batching ──────────────────────────────────────────────────────────────────

def _make_batch(doc: "IBContainerImport", row) -> str:
	"""Create the RM genealogy record (IB Batch — annotation only, not a native
	ERPNext Batch, so items don't need has_batch_no and the outward stock flow
	is untouched). One per container per item row."""
	batch_id = f"{doc.name}::{row.item_code}::{row.idx}"
	if frappe.db.exists("IB Batch", batch_id):
		return batch_id
	item = frappe.db.get_value("Item", row.item_code, ["gsm", "width_mm", "item_name"], as_dict=True) or {}
	b = frappe.new_doc("IB Batch")
	b.batch_id = batch_id
	b.kind = "Raw Material"
	b.item = row.item_code
	b.item_name = item.get("item_name")
	b.qty = flt(row.total_qty)
	b.status = "Active"
	b.source_type = "Container Import"
	b.container_import = doc.name
	b.supplier = doc.supplier
	b.supplier_lot = row.get("custom_supplier_lot") or ""
	b.received_date = doc.import_date
	# For SQMT rows the operator entered the real imported-roll dimensions —
	# these can differ from the Item master and are what downstream slitting
	# feasibility keys on. Fall back to the Item master otherwise.
	b.gsm = flt(row.gsm) or flt(item.get("gsm"))
	b.width_mm = flt(row.width_mm) or flt(item.get("width_mm"))
	b.length_mtr = flt(row.length_mtr)
	b.insert(ignore_permissions=True)
	return b.name


# ── Landed cost ──────────────────────────────────────────────────────────────

def _apply_landed_cost(doc) -> None:
	"""Stock value = invoice rate × exchange rate + this line's share of duty,
	freight, clearing and other charges (spread by value, or by qty when no
	rates are entered). Without currency / charges the landed rate is the rate."""
	fx = flt(doc.exchange_rate) or 1.0
	charges = flt(doc.customs_duty) + flt(doc.freight) + flt(doc.clearing_charges) + flt(doc.other_charges)
	values = [flt(r.rate) * flt(r.total_qty) for r in doc.items]
	qtys = [flt(r.total_qty) for r in doc.items]
	by_value = (doc.allocate_by or "Value") == "Value" and sum(values) > 0
	base = values if by_value else qtys
	total_base = sum(base) or 1.0
	doc.invoice_value = sum(values)
	doc.invoice_value_inr = doc.invoice_value * fx
	doc.total_charges = charges
	for row, b in zip(doc.items, base):
		share = charges * b / total_base
		row.landed_amount = flt(row.rate) * flt(row.total_qty) * fx + share
		row.landed_rate = row.landed_amount / flt(row.total_qty) if flt(row.total_qty) else 0
	doc.landed_value = sum(flt(r.landed_amount) for r in doc.items)


# ── Stock posting ────────────────────────────────────────────────────────────

def _make_stock_entry(doc: "IBContainerImport"):
	se = frappe.new_doc("Stock Entry")
	se.stock_entry_type = "Material Receipt"
	se.company = frappe.defaults.get_user_default("Company") or frappe.get_cached_value("Global Defaults", None, "default_company")
	se.posting_date = doc.import_date
	se.remarks = _("Container Import {0} ({1})").format(doc.container_no, doc.name)
	for row in doc.items:
		se_row = {
			"item_code": row.item_code,
			"qty": row.total_qty,
			"t_warehouse": doc.warehouse,
			"uom": row.stock_uom,
		}
		if flt(row.landed_rate or row.rate) > 0:
			se_row["basic_rate"] = flt(row.landed_rate) or flt(row.rate)
		elif not flt(frappe.get_cached_value("Item", row.item_code, "valuation_rate")):
			# No rate on the row and none on the item master — let the receipt
			# post at zero value rather than hard-blocking the whole container.
			# A real cost can be set on the item master and reposted later.
			se_row["allow_zero_valuation_rate"] = 1
		se.append("items", se_row)
	se.insert(ignore_permissions=True)
	se.submit()
	return se


# ── Label printing ───────────────────────────────────────────────────────────

@frappe.whitelist()
def get_container_items(container_import: str) -> list:
	"""Item rows for the list-view "Generate Label" picker — just enough to
	let the user pick which item when a container has more than one."""
	frappe.has_permission("IB Container Import", "read", container_import, throw=True)
	return frappe.db.get_all(
		"IB Container Import Item",
		filters={"parent": container_import},
		fields=["item_code", "item_name"],
		order_by="idx asc",
	)


@frappe.whitelist()
def generate_item_labels(container_import: str, item_code: str, count) -> None:
	"""List-view "Generate Label" action — print an arbitrary N labels for
	one item, independent of that row's actual recorded no_of_boxes (the
	operator just needs however many labels are physically needed right
	now). Reuses the exact same "IB Container Label" print format/template
	reprint_item_labels() already uses below — only the in-memory row's
	no_of_boxes is overridden (never saved) so "ROLL NO: i / N" reflects
	the requested count, not what's on record."""
	from frappe.utils.print_utils import get_print

	frappe.has_permission("IB Container Import", "read", container_import, throw=True)
	count = cint(count)
	if count <= 0:
		frappe.throw(_("Enter a number of labels greater than 0."))
	if count > _MAX_LABEL_COUNT:
		frappe.throw(_("{0} labels in one print run looks like a typo — max is {1}. Print in smaller batches.").format(count, _MAX_LABEL_COUNT))

	doc = frappe.get_doc("IB Container Import", container_import)
	row = next((r for r in doc.items if r.item_code == item_code), None)
	if not row:
		frappe.throw(_("Item {0} not found on {1}").format(item_code, container_import))

	row.no_of_boxes = count
	doc.items = [row]
	pdf = get_print(
		doctype="IB Container Import",
		name=doc.name,
		print_format="IB Container Label",
		doc=doc,
		as_pdf=True,
	)
	frappe.local.response.filename = f"{doc.name}-{item_code}-labels.pdf"
	frappe.local.response.filecontent = pdf
	frappe.local.response.type = "download"


@frappe.whitelist()
def reprint_item_labels(container_import: str, item_code: str) -> None:
	from frappe.utils.print_utils import get_print

	frappe.has_permission("IB Container Import", "read", container_import, throw=True)
	doc = frappe.get_doc("IB Container Import", container_import)
	row = next((r for r in doc.items if r.item_code == item_code), None)
	if not row:
		frappe.throw(_("Item {0} not found on {1}").format(item_code, container_import))

	doc.items = [row]
	pdf = get_print(
		doctype="IB Container Import",
		name=doc.name,
		print_format="IB Container Label",
		doc=doc,
		as_pdf=True,
	)
	frappe.local.response.filename = f"{doc.name}-{item_code}-labels.pdf"
	frappe.local.response.filecontent = pdf
	frappe.local.response.type = "download"
