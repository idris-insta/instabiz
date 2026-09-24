"""instabiz.overrides.source_warehouse

Floors are an internal split of one location, not separate registrations — the
GSTIN is the same whichever floor the goods leave from. So picking a floor on a
Delivery Note is a stock question ("where is it actually lying?"), never a tax
one, and the operator is allowed to move the pick to any floor of that location.

Two things live here:

1. `get_source_options()` — every usable leaf warehouse under a location, with
   how much of THIS document's items each one can actually cover. Backs the
   "Source Floor" picker on the Delivery Note.
2. `best_leaf_for_item()` — the same data reduced to one answer, used as a soft
   default so a line never silently points at a floor holding nothing.
"""
from __future__ import annotations

from typing import Any, Optional

import frappe
from frappe import _
from frappe.utils import flt

# Leaves that hold stock but are never a normal place to ship a customer order
# from. Still selectable by hand in the picker — just never auto-defaulted.
NON_DISPATCH_HINTS = ("scrap", "transit", "rejected", "sample")


def _location_root(location: Any = None) -> Optional[str]:
	"""Top warehouse for a location name, group or leaf."""
	blob = f"{location or ''}".strip().lower()
	if not blob:
		return None
	try:
		from instabiz.overrides.utils import LOCATION_WAREHOUSE
	except Exception:
		LOCATION_WAREHOUSE = {}
	name = LOCATION_WAREHOUSE.get(blob)
	if name and frappe.db.exists("Warehouse", name):
		# The mapping points at a leaf for Gujarat (Ground Floor); walk up to the
		# group so its sibling floors are offered too.
		parent = frappe.db.get_value("Warehouse", name, "parent_warehouse")
		return parent or name
	# location may already be a warehouse name
	if frappe.db.exists("Warehouse", location):
		return location
	for cand in frappe.get_all(
		"Warehouse",
		filters={"disabled": 0},
		fields=["name", "parent_warehouse"],
	):
		if blob in cand.name.lower():
			return cand.parent_warehouse or cand.name
	return None


def location_leaves(location: Any = None, company: Optional[str] = None) -> list[str]:
	"""Enabled, non-group warehouses under a location — the real floors.

	With no location (Stock Entry carries none) every enabled leaf is offered,
	so an inter-floor transfer can still be pointed by hand.
	"""
	root = _location_root(location)
	if not root:
		if location:
			return []
		filters = {"disabled": 0, "is_group": 0}
		if company:
			filters["company"] = company
		return frappe.get_all("Warehouse", filters=filters, pluck="name", order_by="name")
	filters = {"disabled": 0, "is_group": 0}
	if company:
		filters["company"] = company
	if frappe.db.get_value("Warehouse", root, "is_group"):
		lft, rgt = frappe.db.get_value("Warehouse", root, ["lft", "rgt"])
		names = frappe.get_all(
			"Warehouse",
			filters={**filters, "lft": [">=", lft], "rgt": ["<=", rgt]},
			pluck="name",
			order_by="name",
		)
	else:
		names = [root] if frappe.db.get_value("Warehouse", root, "disabled") == 0 else []
	return names


def _is_dispatchable(warehouse: str) -> bool:
	low = (warehouse or "").lower()
	return not any(h in low for h in NON_DISPATCH_HINTS)


def _available(item_code: str, warehouse: str) -> float:
	"""Actual minus reserved — what can really leave today."""
	row = frappe.db.get_value(
		"Bin", {"item_code": item_code, "warehouse": warehouse}, ["actual_qty", "reserved_qty"], as_dict=True
	)
	if not row:
		return 0.0
	return flt(row.actual_qty) - flt(row.reserved_qty)


@frappe.whitelist()
def get_source_options(location=None, items=None, company=None, delivery_note=None, mode="source"):
	"""Floors under `location` and how much of `items` each can cover.

	items: JSON list of {item_code, qty}. When `delivery_note` is given the rows
	are read from that document instead. mode="target" skips the coverage maths —
	nothing has to be in stock to receive goods — and just lists the floors.
	"""
	if delivery_note:
		frappe.get_doc("Delivery Note", delivery_note).check_permission("read")
		dn = frappe.get_doc("Delivery Note", delivery_note)
		location = location or dn.get("custom_location")
		company = company or dn.company
		rows = [{"item_code": r.item_code, "qty": flt(r.stock_qty or r.qty)} for r in dn.items or []]
	else:
		rows = frappe.parse_json(items) if isinstance(items, str) else (items or [])
		rows = [{"item_code": r.get("item_code"), "qty": flt(r.get("qty"))} for r in rows if r.get("item_code")]

	leaves = location_leaves(location, company)
	if not leaves:
		return {"location": location, "warehouses": [], "items": rows, "mode": mode}

	if mode == "target":
		out = [
			{
				"warehouse": wh,
				"label": _floor_label(wh, with_location=not location),
				"dispatchable": _is_dispatchable(wh),
				"covered": 0,
				"total": 0,
				"shortfall": 0.0,
				"on_hand": round(sum(_available(r["item_code"], wh) for r in rows), 2) if rows else 0.0,
				"lines": [],
			}
			for wh in leaves
		]
		out.sort(key=lambda w: (not w["dispatchable"], w["warehouse"]))
		return {"location": location, "warehouses": out, "items": rows, "mode": mode}

	out = []
	for wh in leaves:
		lines, covered, shortfall = [], 0, 0.0
		for r in rows:
			avail = _available(r["item_code"], wh)
			need = flt(r["qty"])
			full = avail + 0.0001 >= need
			if full:
				covered += 1
			else:
				shortfall += max(need - avail, 0)
			lines.append({"item_code": r["item_code"], "need": need, "available": avail, "full": full})
		out.append(
			{
				"warehouse": wh,
				"label": _floor_label(wh, with_location=not location),
				"dispatchable": _is_dispatchable(wh),
				"covered": covered,
				"total": len(rows),
				"shortfall": round(shortfall, 3),
				"lines": lines,
			}
		)

	# Best coverage first, then least shortfall; non-dispatch leaves last.
	out.sort(key=lambda w: (not w["dispatchable"], -w["covered"], w["shortfall"], w["warehouse"]))
	return {"location": location, "warehouses": out, "items": rows, "mode": mode}


def _floor_label(warehouse: str, with_location: bool = False) -> str:
	"""'Ground Floor - GUJARAT - IB' -> 'Ground Floor'.

	with_location keeps the location segment ('FG - GUJARAT'), needed when the
	list spans every location — otherwise both FG warehouses read just 'FG'.
	"""
	parts = [p.strip() for p in (warehouse or "").split(" - ") if p.strip()]
	if not parts:
		return warehouse
	if with_location and len(parts) > 2:
		return " - ".join(parts[:-1])
	return parts[0]


def best_leaf_for_item(
	item_code: str, location: Any = None, company: Optional[str] = None, qty: float = 0
) -> Optional[str]:
	"""Floor under `location` that can actually supply this item.

	Prefers one holding enough, else the one holding the most. Returns None when
	the whole location is empty, so callers can keep their own default.
	"""
	if not item_code:
		return None
	enough, enough_avail = None, 0.0
	best, best_avail = None, 0.0
	for wh in location_leaves(location, company):
		if not _is_dispatchable(wh):
			continue
		avail = _available(item_code, wh)
		if avail > best_avail:
			best, best_avail = wh, avail
		if qty and avail + 0.0001 >= flt(qty) and avail > enough_avail:
			enough, enough_avail = wh, avail
	# Deepest stock first, so one pick can usually cover the rest of the order too.
	return enough or (best if best_avail > 0 else None)


@frappe.whitelist()
def apply_source_warehouse(delivery_note: str, warehouse: str, only_blank: int = 0):
	"""Point a draft Delivery Note's lines at one floor.

	Same location only — this is an internal floor move, not a change of
	registration, so crossing to another location's tree is refused.
	"""
	dn = frappe.get_doc("Delivery Note", delivery_note)
	dn.check_permission("write")
	if dn.docstatus != 0:
		frappe.throw(_("Only a draft Delivery Note can be repointed."))
	if not frappe.db.exists("Warehouse", warehouse):
		frappe.throw(_("Warehouse {0} not found.").format(warehouse))
	if frappe.db.get_value("Warehouse", warehouse, "is_group"):
		frappe.throw(_("{0} is a group warehouse — pick a floor under it.").format(warehouse))

	allowed = location_leaves(dn.get("custom_location"), dn.company)
	if allowed and warehouse not in allowed:
		frappe.throw(
			_("{0} is not a floor of {1}. Change the document's Location first.").format(
				warehouse, dn.get("custom_location") or _("this location")
			)
		)

	changed = 0
	for row in dn.items or []:
		if int(only_blank or 0) and row.warehouse:
			continue
		if row.warehouse != warehouse:
			row.warehouse = warehouse
			changed += 1
	dn.set_warehouse = warehouse
	dn.save()
	return {"warehouse": warehouse, "rows_changed": changed}
