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


class IBContainerImport(Document):
	# ── Lifecycle ─────────────────────────────────────────────────────────────

	def validate(self) -> None:
		for row in self.items:
			row.total_qty = flt(row.no_of_boxes) * flt(row.qty_per_box)
			row.barcode = _resolve_barcode(row.item_code)

	def before_submit(self) -> None:
		for row in self.items:
			if cint(row.no_of_boxes) <= 0 or flt(row.qty_per_box) <= 0:
				frappe.throw(_("Row #{0}: No. of Boxes and Qty per Box must both be greater than 0").format(row.idx))
			if not row.barcode:
				frappe.throw(_("Row #{0}: barcode could not be resolved for {1}").format(row.idx, row.item_code))
			if not row.batch_no and frappe.get_cached_value("Item", row.item_code, "has_batch_no"):
				row.batch_no = _make_batch(self, row)

	def on_submit(self) -> None:
		stock_entry = _make_stock_entry(self)
		self.db_set("stock_entry", stock_entry.name)

	def on_cancel(self) -> None:
		if self.stock_entry:
			se = frappe.get_doc("Stock Entry", self.stock_entry)
			if se.docstatus == 1:
				se.cancel()


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
def get_barcode_data_uri(value: str) -> str:
	import barcode as barcode_lib
	from barcode.writer import ImageWriter

	code = barcode_lib.get("code128", value, writer=ImageWriter())
	buf = io.BytesIO()
	code.write(buf, options={"write_text": False, "quiet_zone": 1})
	encoded = base64.b64encode(buf.getvalue()).decode()
	return f"data:image/png;base64,{encoded}"


@frappe.whitelist()
def get_qr_data_uri(value: str) -> str:
	import pyqrcode

	encoded = pyqrcode.create(value).png_as_base64_str(scale=4, quiet_zone=1)
	return f"data:image/png;base64,{encoded}"


# ── Batching ──────────────────────────────────────────────────────────────────

def _make_batch(doc: "IBContainerImport", row) -> str:
	item = frappe.db.get_value("Item", row.item_code, ["gsm", "width_mm"], as_dict=True) or {}
	batch = frappe.new_doc("Batch")
	# Deterministic, readable RM batch id — one per container per item row.
	batch.batch_id = f"{doc.container_no}::{row.item_code}::{row.idx}"
	batch.item = row.item_code
	batch.supplier = doc.supplier
	batch.reference_doctype = doc.doctype
	batch.reference_name = doc.name
	batch.description = _("Container {0}").format(doc.container_no)
	batch.custom_batch_kind = "Raw Material"
	batch.custom_container_import = doc.name
	batch.custom_container_no = doc.container_no
	batch.custom_supplier_lot = row.get("custom_supplier_lot") or ""
	batch.custom_received_date = doc.import_date
	batch.custom_gsm = flt(item.get("gsm"))
	batch.custom_width_mm = flt(item.get("width_mm"))
	batch.insert(ignore_permissions=True)
	return batch.name


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
		if row.batch_no:
			se_row["batch_no"] = row.batch_no
			se_row["use_serial_batch_fields"] = 1
		if flt(row.rate) > 0:
			se_row["basic_rate"] = row.rate
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
