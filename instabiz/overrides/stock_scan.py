from __future__ import annotations

import re
from urllib.parse import unquote, urlparse, parse_qs

import frappe
from frappe import _
from frappe.utils import flt


def _require_stock_role() -> None:
	frappe.only_for(["Stock User", "Stock Manager", "System Manager"])


def _extract_code(raw: str) -> str:
	"""A phone camera scanning the label QR returns a full trace URL
	(…/app/ib-trace?id=<code>). A handheld laser scanner returns the bare
	Code128 string. Normalise both to the bare code."""
	raw = (raw or "").strip()
	if not raw:
		return ""
	if "ib-trace" in raw or raw.lower().startswith(("http://", "https://")):
		try:
			q = parse_qs(urlparse(raw).query)
			if q.get("id"):
				return unquote(q["id"][0]).strip()
		except Exception:
			pass
		m = re.search(r"[?&]id=([^&\s]+)", raw)
		if m:
			return unquote(m.group(1)).strip()
	return raw


def _serial_unit_qty(sn: dict) -> float:
	"""Stock qty one finished unit (one box / roll) represents.
	SQMT items: the roll's own area (width/1000 × length). Otherwise: the
	producing WO Output's produced_qty ÷ serial_count, falling back to 1."""
	uom = (frappe.db.get_value("Item", sn["item_code"], "stock_uom") or "").upper()
	if uom == "SQMT" and flt(sn.get("width_mm")) and flt(sn.get("length_mtr")):
		return flt(sn["width_mm"]) / 1000.0 * flt(sn["length_mtr"])
	if sn.get("fg_batch"):
		row = frappe.db.get_value(
			"IB WO Output",
			{"fg_batch": sn["fg_batch"], "item_code": sn["item_code"]},
			["produced_qty", "serial_count"], as_dict=True,
		)
		if row and flt(row.produced_qty) and cint_safe(row.serial_count):
			return flt(row.produced_qty) / cint_safe(row.serial_count)
	return 1.0


def cint_safe(v) -> int:
	try:
		return int(flt(v))
	except Exception:
		return 0


def _fg_warehouse_for(item_code: str) -> str | None:
	"""Best-guess warehouse to deduct a finished unit from: the one that
	currently holds stock of this item, else the company default FG warehouse."""
	wh = frappe.db.get_value(
		"Bin", {"item_code": item_code, "actual_qty": [">", 0]}, "warehouse",
		order_by="actual_qty desc",
	)
	if wh:
		return wh
	return frappe.db.get_single_value("Stock Settings", "default_warehouse")


@frappe.whitelist()
def resolve_barcode(barcode: str) -> dict:
	_require_stock_role()
	barcode = _extract_code(barcode)
	item_code = frappe.db.get_value("Item Barcode", {"barcode": barcode}, "parent")

	if not item_code:
		# An FG serial label scans as the serial string (or its trace-URL id).
		sn = frappe.db.get_value(
			"IB FG Serial",
			barcode,
			["serial_no", "item_code", "item_name", "status", "fg_batch", "source_batch",
			 "work_order", "sales_order", "box_no", "width_mm", "length_mtr", "gsm"],
			as_dict=True,
		)
		if sn:
			unit_qty = _serial_unit_qty(sn)
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
				"unit_qty": flt(unit_qty),
				"suggest_warehouse": _fg_warehouse_for(sn.item_code),
				"can_deduct": sn.status == "In Stock",
			}

		# An IB Batch label scans as the batch id itself.
		batch = frappe.db.get_value(
			"IB Batch",
			barcode,
			["name", "item", "item_name", "qty", "kind", "source_type",
			 "container_import", "purchase_receipt", "supplier_lot"],
			as_dict=True,
		)
		if batch:
			container_no = (
				frappe.db.get_value("IB Container Import", batch.container_import, "container_no")
				if batch.container_import else (batch.purchase_receipt or "")
			)
			return {
				"kind": "batch",
				"batch": batch.name,
				"batch_kind": batch.kind,
				"source_type": batch.source_type,
				"container_no": container_no,
				"supplier_lot": batch.supplier_lot,
				"item_code": batch.item,
				"item_name": batch.item_name or frappe.db.get_value("Item", batch.item, "item_name"),
				"stock_uom": frappe.db.get_value("Item", batch.item, "stock_uom"),
				"batch_qty": flt(batch.qty),
				# RM goes out through production consumption, not a manual scan —
				# only Finished-Good batches are hand-deductable here.
				"can_deduct": batch.kind == "Finished Good" and flt(batch.qty) > 0,
				"suggest_warehouse": _fg_warehouse_for(batch.item),
			}
		frappe.throw(_("No item found for barcode {0}").format(barcode))

	item = frappe.db.get_value("Item", item_code, ["item_name", "stock_uom", "disabled"], as_dict=True)
	if not item:
		frappe.throw(_("Barcode {0} points to a deleted item ({1}).").format(barcode, item_code))
	if item.disabled:
		frappe.throw(_("Item {0} is disabled — cannot scan it in/out of stock.").format(item_code))
	balances = frappe.get_all(
		"Bin",
		filters={"item_code": item_code, "actual_qty": [">", 0]},
		fields=["warehouse", "actual_qty"],
	)
	return {
		"kind": "item",
		"item_code": item_code,
		"item_name": item.item_name,
		"stock_uom": item.stock_uom,
		"balances": balances,
		"suggest_warehouse": balances[0].warehouse if balances else _fg_warehouse_for(item_code),
	}


def _post_stock_entry(item_code: str, qty: float, warehouse: str, direction: str, remark: str):
	se = frappe.new_doc("Stock Entry")
	row = {"item_code": item_code, "qty": flt(qty)}
	if direction == "Add":
		se.stock_entry_type = "Material Receipt"
		row["t_warehouse"] = warehouse
	else:
		se.stock_entry_type = "Material Issue"
		row["s_warehouse"] = warehouse
	se.remarks = remark
	se.append("items", row)
	se.insert(ignore_permissions=True)
	se.submit()
	return se


@frappe.whitelist()
def adjust_stock(barcode: str, warehouse: str, qty: float, direction: str) -> dict:
	"""SKU-barcode stock move. Deduct is the everyday action (stock enters via
	production/import); Add stays available for corrections."""
	_require_stock_role()
	if direction not in ("Add", "Deduct"):
		frappe.throw(_("Direction must be Add or Deduct"))
	qty = flt(qty)
	if qty <= 0:
		frappe.throw(_("Qty must be greater than 0"))

	item_code = frappe.db.get_value("Item Barcode", {"barcode": _extract_code(barcode)}, "parent")
	if not item_code:
		frappe.throw(_("No item found for barcode {0}").format(barcode))

	se = _post_stock_entry(
		item_code, qty, warehouse, direction,
		_("Scanned {0} via Scan Stock ({1})").format(item_code, direction),
	)
	new_qty = frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": warehouse}, "actual_qty") or 0
	return {"stock_entry": se.name, "item_code": item_code, "new_qty": flt(new_qty)}


@frappe.whitelist()
def ship_serial(serial_no: str, warehouse: str | None = None) -> dict:
	"""Scan a finished-unit label to take that one box/roll OUT of stock.
	Posts a Material Issue for the unit's qty and marks the serial Delivered."""
	_require_stock_role()
	serial_no = _extract_code(serial_no)
	sn = frappe.db.get_value(
		"IB FG Serial", serial_no,
		["name", "serial_no", "item_code", "status", "fg_batch", "width_mm", "length_mtr"],
		as_dict=True,
	)
	if not sn:
		frappe.throw(_("Serial {0} not found").format(serial_no))
	if sn.status != "In Stock":
		return {"already": True, "message": _("{0} is already {1}").format(sn.serial_no, sn.status)}

	qty = _serial_unit_qty(dict(sn))
	wh = warehouse or _fg_warehouse_for(sn.item_code)
	if not wh:
		frappe.throw(_("No warehouse to deduct from — pick one and retry."))

	se = _post_stock_entry(
		sn.item_code, qty, wh, "Deduct",
		_("Scan-out finished unit {0}").format(sn.serial_no),
	)
	frappe.db.set_value("IB FG Serial", sn.name, "status", "Delivered", update_modified=True)
	new_qty = frappe.db.get_value("Bin", {"item_code": sn.item_code, "warehouse": wh}, "actual_qty") or 0
	return {
		"stock_entry": se.name, "serial": sn.serial_no, "item_code": sn.item_code,
		"qty": flt(qty), "warehouse": wh, "new_qty": flt(new_qty),
	}


@frappe.whitelist()
def adjust_batch_stock(batch: str, warehouse: str, qty: float, direction: str = "Deduct") -> dict:
	"""Hand stock move against a Finished-Good IB Batch (e.g. shipping loose
	rolls from a produced lot that were not individually serialised)."""
	_require_stock_role()
	batch = _extract_code(batch)
	b = frappe.db.get_value("IB Batch", batch, ["name", "item", "qty", "kind"], as_dict=True)
	if not b:
		frappe.throw(_("Batch {0} not found").format(batch))
	if b.kind != "Finished Good":
		frappe.throw(_("Only Finished-Good batches can be scanned out here. Raw material leaves through production."))
	if direction not in ("Add", "Deduct"):
		frappe.throw(_("Direction must be Add or Deduct"))
	qty = flt(qty)
	if qty <= 0:
		frappe.throw(_("Qty must be greater than 0"))
	if direction == "Deduct" and qty > flt(b.qty):
		frappe.throw(_("Batch {0} only has {1} left").format(b.name, flt(b.qty)))

	se = _post_stock_entry(
		b.item, qty, warehouse, direction,
		_("Scan {0} FG batch {1}").format(direction, b.name),
	)
	frappe.db.set_value(
		"IB Batch", b.name, "qty",
		flt(b.qty) + (qty if direction == "Add" else -qty), update_modified=True,
	)
	new_qty = frappe.db.get_value("Bin", {"item_code": b.item, "warehouse": warehouse}, "actual_qty") or 0
	return {"stock_entry": se.name, "batch": b.name, "item_code": b.item, "new_qty": flt(new_qty)}
