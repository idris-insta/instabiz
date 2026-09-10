from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt


def _require_stock_role() -> None:
	frappe.only_for(["Stock User", "Stock Manager", "System Manager"])


@frappe.whitelist()
def resolve_barcode(barcode: str) -> dict:
	_require_stock_role()
	item_code = frappe.db.get_value("Item Barcode", {"barcode": barcode}, "parent")

	if not item_code:
		# Not a SKU barcode — an FG serial label scans as the serial string.
		sn = frappe.db.get_value(
			"IB FG Serial",
			barcode,
			["serial_no", "item_code", "item_name", "status", "fg_batch", "source_batch",
			 "work_order", "sales_order", "box_no"],
			as_dict=True,
		)
		if sn:
			return {
				"kind": "serial",
				"serial": sn.serial_no,
				"serial_status": sn.status,
				"fg_batch": sn.fg_batch,
				"source_batch": sn.source_batch,
				"work_order": sn.work_order,
				"sales_order": sn.sales_order,
				"box_no": sn.box_no,
				"item_code": sn.item_code,
				"item_name": sn.item_name,
				"stock_uom": frappe.db.get_value("Item", sn.item_code, "stock_uom"),
			}

		# A batch label scans as the batch name itself.
		batch = frappe.db.get_value(
			"Batch",
			barcode,
			["name", "item", "batch_qty", "custom_batch_kind", "custom_container_no", "custom_supplier_lot"],
			as_dict=True,
		)
		if batch:
			bal = frappe.get_all(
				"Bin",
				filters={"item_code": batch.item, "actual_qty": [">", 0]},
				fields=["warehouse", "actual_qty"],
			)
			return {
				"kind": "batch",
				"batch": batch.name,
				"batch_kind": batch.custom_batch_kind,
				"container_no": batch.custom_container_no,
				"supplier_lot": batch.custom_supplier_lot,
				"item_code": batch.item,
				"item_name": frappe.db.get_value("Item", batch.item, "item_name"),
				"stock_uom": frappe.db.get_value("Item", batch.item, "stock_uom"),
				"batch_qty": flt(batch.batch_qty),
				"balances": bal,
			}
		frappe.throw(_("No item found for barcode {0}").format(barcode))

	item = frappe.db.get_value("Item", item_code, ["item_name", "stock_uom", "disabled"], as_dict=True)
	if not item:
		# Item Barcode row survived an Item that no longer exists (e.g. a raw
		# delete that skipped the usual on_trash cascade) — surface a clear
		# error instead of an AttributeError on a None item.
		frappe.throw(_("Barcode {0} points to a deleted item ({1}).").format(barcode, item_code))
	if item.disabled:
		frappe.throw(_("Item {0} is disabled — cannot scan it in/out of stock.").format(item_code))
	balances = frappe.get_all(
		"Bin",
		filters={"item_code": item_code, "actual_qty": [">", 0]},
		fields=["warehouse", "actual_qty"],
	)
	return {
		"item_code": item_code,
		"item_name": item.item_name,
		"stock_uom": item.stock_uom,
		"balances": balances,
	}


@frappe.whitelist()
def adjust_stock(barcode: str, warehouse: str, qty: float, direction: str) -> dict:
	_require_stock_role()
	if direction not in ("Add", "Deduct"):
		frappe.throw(_("Direction must be Add or Deduct"))
	qty = flt(qty)
	if qty <= 0:
		frappe.throw(_("Qty must be greater than 0"))

	item_code = frappe.db.get_value("Item Barcode", {"barcode": barcode}, "parent")
	if not item_code:
		frappe.throw(_("No item found for barcode {0}").format(barcode))

	se = frappe.new_doc("Stock Entry")
	row = {"item_code": item_code, "qty": qty}
	if direction == "Add":
		se.stock_entry_type = "Material Receipt"
		row["t_warehouse"] = warehouse
	else:
		se.stock_entry_type = "Material Issue"
		row["s_warehouse"] = warehouse
	se.remarks = _("Scanned {0} via Scan Stock ({1})").format(barcode, direction)
	se.append("items", row)
	se.insert(ignore_permissions=True)
	se.submit()

	new_qty = frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty") or 0
	return {
		"stock_entry": se.name,
		"item_code": item_code,
		"new_qty": flt(new_qty),
	}
