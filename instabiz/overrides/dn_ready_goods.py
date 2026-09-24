# Copyright (c) 2026, Instabiz and contributors
# License: MIT
"""
Todo 43 — Ready Goods DN path + DN default source warehouse.

LOCKED rules (Idris 2026-09-21):
- Conversion → DN deducts from FG warehouse (fg_warehouse_for_location)
- Ready Goods → DN from allocate_sub_warehouse(location, "Ready Goods")
  (Ground Floor - GUJARAT - IB for Gujarat; MAHARASHTRA for BWD)
- Soft defaults only (blank set_warehouse / item.warehouse)
- Ready Goods fulfillment may skip OS/WO/FG Serial gates even when SGM
  Manufacturing tick is ON
- Mixed SO: conversion lines still need production; ready lines can ship

Prefer helpers already on manufacturing_rules; local fallbacks only if missing
(e.g. after an older mfg_lock replace that dropped names).
"""
from __future__ import annotations

from typing import Any, Optional

import frappe
from frappe.utils import cint, flt

PATH_CONVERSION = "conversion"
PATH_READY_GOODS = "ready_goods"


def _normalize_path(path) -> Optional[str]:
	"""Map live manufacturing_rules labels onto internal path tokens."""
	if path is None:
		return None
	s = str(path).strip().lower().replace("-", " ").replace("_", " ")
	s = " ".join(s.split())
	if s in (PATH_CONVERSION, "conversion", "mfg", "manufacturing", "convert"):
		return PATH_CONVERSION
	if s in (PATH_READY_GOODS, "ready goods", "ready", "trading", "warehouse only", "warehouse"):
		return PATH_READY_GOODS
	return None



def _mr():
	from instabiz.overrides import manufacturing_rules as mr

	return mr


def _mr_call(name: str, *args, default=None, **kwargs):
	mr = _mr()
	fn = getattr(mr, name, None)
	if not callable(fn):
		return default
	try:
		return fn(*args, **kwargs)
	except TypeError:
		# Live helpers often omit company=/warehouse= kwargs — retry positionals only
		try:
			return fn(*args)
		except Exception:
			return default
	except Exception:
		return default


# ── Location / warehouse helpers (prefer manufacturing_rules) ─────────────────

def _is_split_location(location: Any = None) -> bool:
	"""Only Gujarat/SGM and Maharashtra/BWD have an FG vs Ready Goods split.

	Any other location (CHENNAI) must not be handed to the manufacturing_rules
	helpers: they fall back to the Gujarat tree for anything they don't
	recognise, which would source a Chennai delivery from a Gujarat warehouse.
	"""
	blob = f"{location or ''}".lower()
	return any(h in blob for h in ("gujarat", "sgm", "maharashtra", "bwd", "bom"))


def fg_warehouse_for_location(location: Any = None, company: Optional[str] = None) -> Optional[str]:
	if location and not _is_split_location(location):
		return _location_warehouse_fallback(location)
	wh = _mr_call("fg_warehouse_for_location", location, company=company)
	if wh:
		return wh
	# Fallback mirrors manufacturing_rules locked behaviour
	abbr = _mr_call("company_abbr", company, default="IB") or "IB"
	blob = f"{location or ''}".lower()
	if any(h in blob for h in ("gujarat", "sgm")):
		cand = f"FG - GUJARAT - {abbr}"
		return cand if frappe.db.exists("Warehouse", cand) else None
	if any(h in blob for h in ("maharashtra", "bwd", "bom")):
		cand = f"FG - MAHARASHTRA - {abbr}"
		if frappe.db.exists("Warehouse", cand):
			return cand
		parent = f"MAHARASHTRA - {abbr}"
		return parent if frappe.db.exists("Warehouse", parent) else None
	return _location_warehouse_fallback(location)


def _location_warehouse_fallback(location: Any = None) -> Optional[str]:
	"""Locations with no FG/Ready split of their own (CHENNAI) keep the plain
	LOCATION_WAREHOUSE default. Without this the helpers return None and the
	Delivery Note lines are left with no warehouse at all."""
	try:
		from instabiz.overrides.utils import LOCATION_WAREHOUSE
	except Exception:
		return None
	key = f"{location or ''}".strip().lower()
	wh = LOCATION_WAREHOUSE.get(key)
	if not wh:
		return None
	# CHENNAI - IB is disabled on this site; handing back a disabled warehouse
	# just moves the failure to save time.
	row = frappe.db.get_value("Warehouse", wh, ["disabled", "is_group"], as_dict=True)
	if not row or row.disabled or row.is_group:
		return None
	return wh


def allocate_sub_warehouse(location: Any = None, kind: str = "Ready Goods", company: Optional[str] = None) -> Optional[str]:
	"""Ready Goods leaf / trading WH. Prefer manufacturing_rules.allocate_sub_warehouse."""
	if location and not _is_split_location(location):
		return _location_warehouse_fallback(location)
	wh = _mr_call("allocate_sub_warehouse", location, kind, company=company)
	if wh:
		return wh
	# Alias some deployments used
	wh = _mr_call("allocate_leaf_sub_warehouse", location, preferred_leaf="Ground Floor", company=company)
	if wh and "Ready" in str(kind):
		# Prefer Ground Floor specifically for Ready Goods
		abbr = _mr_call("company_abbr", company, default="IB") or "IB"
		blob = f"{location or ''}".lower()
		if any(h in blob for h in ("gujarat", "sgm")):
			gf = f"Ground Floor - GUJARAT - {abbr}"
			if frappe.db.exists("Warehouse", gf):
				return gf
			return wh
		if any(h in blob for h in ("maharashtra", "bwd", "bom")):
			parent = f"MAHARASHTRA - {abbr}"
			return parent if frappe.db.exists("Warehouse", parent) else wh
	# Pure fallback
	abbr = _mr_call("company_abbr", company, default="IB") or "IB"
	blob = f"{location or ''}".lower()
	if any(h in blob for h in ("gujarat", "sgm")):
		gf = f"Ground Floor - GUJARAT - {abbr}"
		return gf if frappe.db.exists("Warehouse", gf) else None
	if any(h in blob for h in ("maharashtra", "bwd", "bom")):
		parent = f"MAHARASHTRA - {abbr}"
		return parent if frappe.db.exists("Warehouse", parent) else None
	return _location_warehouse_fallback(location)


def resolve_fulfillment_path(
	item_code: Optional[str] = None,
	location: Any = None,
	warehouse: Any = None,
	so=None,
	so_item=None,
	**kwargs,
) -> str:
	"""Return 'conversion' or 'ready_goods'."""
	# Live manufacturing_rules returns "Ready Goods" / "Conversion" (title case).
	# Also try positional-only call matching live signature (item_code, location).
	path = _mr_call(
		"resolve_fulfillment_path",
		item_code,
		location,
		default=None,
	)
	if path is None:
		path = _mr_call(
			"resolve_fulfillment_path",
			item_code,
			location=location,
			warehouse=warehouse,
			so=so,
			so_item=so_item,
			**kwargs,
		)
	norm = _normalize_path(path)
	if norm:
		return norm
	# Prefer live item_needs_conversion when present
	needs = _mr_call("item_needs_conversion", item_code, location)
	if needs is True:
		return PATH_CONVERSION
	if needs is False:
		return PATH_READY_GOODS

	# Fallback heuristics when helper missing / returned None
	blob_loc = f"{location or ''} {warehouse or ''}".lower()
	# BWD / Maharashtra = warehouse-only Ready Goods
	if any(h in blob_loc for h in ("maharashtra", "bwd", "bom")) and "gujarat" not in blob_loc and "sgm" not in blob_loc:
		return PATH_READY_GOODS

	# Item-level signals
	item_blob = ""
	needs_conv = None
	if item_code and frappe.db.exists("Item", item_code):
		row = frappe.db.get_value(
			"Item",
			item_code,
			[
				"item_name",
				"item_group",
				"include_item_in_manufacturing",
				"custom_needs_conversion",
				"custom_fulfillment_path",
				"custom_conversion_required",
			],
			as_dict=True,
		) or {}
		item_blob = f"{item_code} {row.get('item_name') or ''} {row.get('item_group') or ''}".lower()
		for key in ("custom_fulfillment_path",):
			v = (row.get(key) or "").strip().lower()
			if v in (PATH_CONVERSION, "mfg", "manufacturing"):
				return PATH_CONVERSION
			if v in (PATH_READY_GOODS, "ready", "trading", "ready goods"):
				return PATH_READY_GOODS
		for key in ("custom_needs_conversion", "custom_conversion_required"):
			if row.get(key) is not None:
				needs_conv = bool(cint(row.get(key)))
				break
		# include_item_in_manufacturing alone is too noisy (most items flagged)

	# SO item custom fields
	if so_item is not None:
		for attr in ("fulfillment_path", "custom_fulfillment_path", "conversion_path"):
			v = str(getattr(so_item, attr, None) or "").strip().lower()
			if v in (PATH_CONVERSION, "mfg", "manufacturing"):
				return PATH_CONVERSION
			if v in (PATH_READY_GOODS, "ready", "trading", "ready goods"):
				return PATH_READY_GOODS
		for attr in ("needs_conversion", "custom_needs_conversion"):
			if hasattr(so_item, attr) and getattr(so_item, attr) is not None:
				needs_conv = bool(cint(getattr(so_item, attr)))
				break

	if needs_conv is True:
		return PATH_CONVERSION
	if needs_conv is False:
		return PATH_READY_GOODS

	# Keyword heuristics: finished/trading vs jumbo conversion
	if any(k in item_blob for k in ("ready", "trading", "finished goods", "fg tape")):
		return PATH_READY_GOODS
	if any(k in item_blob for k in ("jumbo", "bopp jumbo", "coating film", "raw film")):
		return PATH_CONVERSION

	# Default: Gujarat/SGM with Manufacturing-capable WH → conversion; else ready
	if warehouse_allows_manufacturing(warehouse or location):
		return PATH_CONVERSION
	return PATH_READY_GOODS


def warehouse_allows_manufacturing(warehouse: Any = None) -> bool:
	"""Manufacturing tick — prefer manufacturing_site.is_factory (custom_manufacturing_enabled)."""
	name = warehouse
	if hasattr(warehouse, "name"):
		name = warehouse.name
	name = str(name or "").strip()
	if not name:
		return False
	try:
		from instabiz.overrides.manufacturing_site import is_factory, location_has_factory
		# Location string (gujarat / maharashtra) vs warehouse name
		low = name.lower()
		if low in ("gujarat", "maharashtra", "chennai", "bwd", "sgm", "bom"):
			# sgm maps to gujarat factory tree
			loc = "gujarat" if low in ("sgm", "gujarat") else ("maharashtra" if low in ("bwd", "bom", "maharashtra") else low)
			return bool(location_has_factory(loc))
		return bool(is_factory(name))
	except Exception:
		pass
	val = _mr_call("warehouse_allows_manufacturing", name)
	if isinstance(val, bool):
		return val
	if isinstance(val, (int, float)):
		return bool(cint(val))
	for field in (
		"custom_manufacturing_enabled",
		"custom_manufacturing",
		"custom_allow_manufacturing",
		"manufacturing",
		"custom_is_manufacturing",
		"custom_mfg",
	):
		try:
			if not frappe.db.has_column("Warehouse", field):
				continue
			v = frappe.db.get_value("Warehouse", name, field)
			if v is not None:
				return bool(cint(v))
		except Exception:
			continue
	return False


def so_location(so) -> Optional[str]:
	if not so:
		return None
	if isinstance(so, str):
		so = frappe.get_cached_doc("Sales Order", so)
	for attr in ("custom_location", "location", "branch", "custom_branch", "set_warehouse", "source_warehouse"):
		v = getattr(so, attr, None)
		if v:
			return v
	# Item warehouse as last resort
	for row in getattr(so, "items", None) or []:
		if getattr(row, "warehouse", None):
			return row.warehouse
	return None


def so_line_needs_production(so, so_item) -> bool:
	"""Per-line: conversion path needs OS/WO; ready goods does not."""
	item_code = getattr(so_item, "item_code", None) if so_item is not None else None
	loc = so_location(so)
	wh = getattr(so_item, "warehouse", None) if so_item is not None else None
	path = resolve_fulfillment_path(item_code=item_code, location=loc, warehouse=wh or loc, so=so, so_item=so_item)
	return path == PATH_CONVERSION


def so_needs_production(so) -> bool:
	"""Whole-SO: True if ANY line needs conversion production.

	Fine grain on top of manufacturing_site.so_needs_production:
	- Site Manufacturing tick OFF → False (DN direct; existing rule)
	- Tick ON + all Ready Goods lines → False (skip useless WO on SGM)
	- Tick ON + any Conversion line → True
	"""
	if isinstance(so, str):
		so = frappe.get_cached_doc("Sales Order", so)

	# Coarse site gate — MUST use so_needs_production_site (not wrapped so_needs_production)
	site_needs = None
	try:
		from instabiz.overrides import manufacturing_site as _ms
		_site_fn = getattr(_ms, "so_needs_production_site", None) or getattr(_ms, "_ib_site_so_needs_production", None)
		if _site_fn:
			site_needs = bool(_site_fn(so))
	except Exception:
		site_needs = None

	if site_needs is False:
		return False

	items = getattr(so, "items", None) or []
	if not items:
		return bool(site_needs) if site_needs is not None else False

	any_conversion = False
	for row in items:
		if cint(getattr(row, "delivered_by_supplier", 0)):
			continue
		if so_line_needs_production(so, row):
			any_conversion = True
			break

	if not any_conversion:
		# Pure Ready Goods even on SGM Manufacturing ON → skip OS/WO
		return False

	return True


def so_is_pure_ready_goods(so) -> bool:
	if isinstance(so, str):
		so = frappe.get_cached_doc("Sales Order", so)
	items = getattr(so, "items", None) or []
	if not items:
		return False
	for row in items:
		if cint(getattr(row, "delivered_by_supplier", 0)):
			continue
		if so_line_needs_production(so, row):
			return False
	return True


def so_allows_direct_dn(so) -> bool:
	"""DN from SO allowed without OS/WO/FG Serial when no conversion lines need production."""
	return not so_needs_production(so)


def default_source_warehouse_for_line(so, so_item=None, item_code: Optional[str] = None) -> Optional[str]:
	loc = so_location(so)
	item_code = item_code or (getattr(so_item, "item_code", None) if so_item is not None else None)
	wh = getattr(so_item, "warehouse", None) if so_item is not None else None
	path = resolve_fulfillment_path(item_code=item_code, location=loc, warehouse=wh or loc, so=so, so_item=so_item)
	company = getattr(so, "company", None) if so is not None else None
	if path == PATH_CONVERSION:
		rule_wh = fg_warehouse_for_location(loc, company=company)
	else:
		rule_wh = allocate_sub_warehouse(loc, "Ready Goods", company=company)

	# The floors of one location share a GSTIN — moving the pick between them is
	# internal, so a rule-chosen floor holding nothing is never worth keeping.
	# Fall back to a floor that can actually supply the line; the operator can
	# still override either way from the Source Floor picker.
	try:
		from instabiz.overrides.source_warehouse import best_leaf_for_item

		qty = flt(getattr(so_item, "stock_qty", None) or getattr(so_item, "qty", 0)) if so_item else 0
		stocked = best_leaf_for_item(item_code, loc, company=company, qty=qty)
	except Exception:
		stocked = None
	if not stocked:
		return rule_wh
	if not rule_wh:
		return stocked
	try:
		from instabiz.overrides.source_warehouse import _available

		if _available(item_code, rule_wh) > 0:
			return rule_wh
	except Exception:
		return rule_wh
	return stocked


def apply_dn_source_warehouses(dn, so=None) -> dict:
	"""Soft-set DN set_warehouse + item.warehouse from fulfillment path.

	Only fills blanks — never overwrites user-chosen warehouses.
	"""
	stats = {"set_warehouse": None, "items_set": 0, "items_skipped": 0, "paths": []}

	if isinstance(dn, str):
		dn = frappe.get_doc("Delivery Note", dn)

	so_name = None
	if so is None:
		so_name = getattr(dn, "against_sales_order", None)
		if not so_name:
			for row in getattr(dn, "items", None) or []:
				so_name = getattr(row, "against_sales_order", None)
				if so_name:
					break
		if so_name and frappe.db.exists("Sales Order", so_name):
			so = frappe.get_doc("Sales Order", so_name)
	elif isinstance(so, str):
		so = frappe.get_doc("Sales Order", so)

	# Header set_warehouse
	if not getattr(dn, "set_warehouse", None) and so is not None:
		# Prefer majority / first line path
		first_item = (getattr(dn, "items", None) or [None])[0]
		item_code = getattr(first_item, "item_code", None) if first_item else None
		# Map SO item if possible
		so_item = None
		if so is not None and first_item is not None:
			so_detail = getattr(first_item, "so_detail", None)
			if so_detail:
				so_item = next((r for r in (so.items or []) if r.name == so_detail), None)
		wh = default_source_warehouse_for_line(so, so_item=so_item, item_code=item_code)
		if wh:
			dn.set_warehouse = wh
			stats["set_warehouse"] = wh

	for row in getattr(dn, "items", None) or []:
		if getattr(row, "warehouse", None):
			stats["items_skipped"] += 1
			continue
		so_item = None
		if so is not None:
			so_detail = getattr(row, "so_detail", None)
			if so_detail:
				so_item = next((r for r in (so.items or []) if r.name == so_detail), None)
		wh = default_source_warehouse_for_line(so, so_item=so_item, item_code=getattr(row, "item_code", None))
		path = resolve_fulfillment_path(
			item_code=getattr(row, "item_code", None),
			location=so_location(so) if so is not None else None,
			so=so,
			so_item=so_item,
		)
		stats["paths"].append({"item": row.item_code, "path": path, "warehouse": wh})
		if wh:
			row.warehouse = wh
			stats["items_set"] += 1
		else:
			stats["items_skipped"] += 1

	return stats


def delivery_note_before_insert(doc, method=None):
	"""Hook: soft-default warehouses on new DN."""
	try:
		apply_dn_source_warehouses(doc)
	except Exception:
		frappe.log_error(title="dn_ready_goods.before_insert", message=frappe.get_traceback())


def delivery_note_validate(doc, method=None):
	"""Hook: soft-default blank warehouses during validate."""
	try:
		apply_dn_source_warehouses(doc)
	except Exception:
		frappe.log_error(title="dn_ready_goods.validate", message=frappe.get_traceback())


def wrap_custom_make_delivery_note(original_fn):
	"""Decorator/wrapper: after ERPNext make_delivery_note, apply WH defaults."""

	def _wrapped(*args, **kwargs):
		dn = original_fn(*args, **kwargs)
		try:
			# dn may be a dict (mapped doc) or Document
			so = None
			if args:
				so = args[0]
			apply_target = dn
			if isinstance(dn, dict):
				# mapped doc dict — mutate in place
				class _Tmp:
					pass

				tmp = _Tmp()
				tmp.set_warehouse = dn.get("set_warehouse")
				tmp.against_sales_order = dn.get("against_sales_order")
				tmp.company = dn.get("company")
				items = []
				for it in dn.get("items") or []:
					o = _Tmp()
					for k, v in it.items():
						setattr(o, k, v)
					items.append(o)
				tmp.items = items
				stats = apply_dn_source_warehouses(tmp, so=so if not isinstance(so, str) else so)
				if tmp.set_warehouse and not dn.get("set_warehouse"):
					dn["set_warehouse"] = tmp.set_warehouse
				for src, dst in zip(tmp.items, dn.get("items") or []):
					if getattr(src, "warehouse", None) and not dst.get("warehouse"):
						dst["warehouse"] = src.warehouse
				dn.setdefault("_ib_dn_wh_stats", stats)
			else:
				apply_dn_source_warehouses(dn, so=so)
		except Exception:
			frappe.log_error(title="dn_ready_goods.make_delivery_note", message=frappe.get_traceback())
		return dn

	_wrapped.__name__ = getattr(original_fn, "__name__", "custom_make_delivery_note")
	_wrapped.__doc__ = getattr(original_fn, "__doc__", None)
	return _wrapped


# ── Production / DN readiness gates ───────────────────────────────────────────

READY_GOODS_OS_MSG = (
	"This Sales Order is Ready Goods only — make Delivery Note directly from the "
	"Sales Order (no IB Order Sheet / IB Work Order / FG Serial required)."
)


def assert_so_needs_production_or_throw(so, *, action: str = "create Order Sheet"):
	"""Call from create_order_sheet / create_run — refuse pure Ready Goods SOs."""
	if isinstance(so, str):
		so_name = so
		so_doc = frappe.get_doc("Sales Order", so)
	else:
		so_doc = so
		so_name = so.name

	if so_is_pure_ready_goods(so_doc):
		frappe.throw(
			f"Cannot {action} for {so_name}. {READY_GOODS_OS_MSG}",
			title="Ready Goods — DN Direct",
		)
	return True


def dn_readiness_override(so_name: str, base_result: Optional[dict] = None) -> dict:
	"""Relax get_order_dn_readiness for Ready Goods / mixed SOs.

	base_result is the existing readiness dict (mutated/extended).
	"""
	result = dict(base_result or {})
	so = frappe.get_doc("Sales Order", so_name)
	pure_ready = so_is_pure_ready_goods(so)
	needs_prod = so_needs_production(so)
	result["ib_fulfillment"] = {
		"pure_ready_goods": pure_ready,
		"needs_production": needs_prod,
		"allows_direct_dn": so_allows_direct_dn(so),
		"lines": [],
	}
	for row in so.items or []:
		path = resolve_fulfillment_path(
			item_code=row.item_code,
			location=so_location(so),
			warehouse=getattr(row, "warehouse", None),
			so=so,
			so_item=row,
		)
		result["ib_fulfillment"]["lines"].append(
			{
				"item_code": row.item_code,
				"path": path,
				"needs_production": path == PATH_CONVERSION,
				"default_warehouse": default_source_warehouse_for_line(so, so_item=row),
			}
		)

	if pure_ready or so_allows_direct_dn(so):
		# Common gate keys used by UI — mark ready / skip WO requirements
		for key in ("ready", "dn_ready", "can_create_dn", "allow_dn"):
			if key in result:
				result[key] = True
		for key in ("requires_wo", "requires_order_sheet", "requires_fg_serial", "blocked", "block_dn"):
			if key in result:
				result[key] = False
		result["ib_ready_goods_direct_dn"] = True
		result["message"] = READY_GOODS_OS_MSG
		# Clear blocking reasons that cite missing WO/OS/FG Serial
		reasons = result.get("reasons") or result.get("blocking_reasons") or result.get("errors")
		if isinstance(reasons, list):
			filtered = []
			for r in reasons:
				blob = str(r).lower()
				if any(x in blob for x in ("work order", "order sheet", "fg serial", "ib-wo", "ib-os", "production")):
					continue
				filtered.append(r)
			if "reasons" in result:
				result["reasons"] = filtered
			if "blocking_reasons" in result:
				result["blocking_reasons"] = filtered
			if "errors" in result:
				result["errors"] = filtered
	elif needs_prod:
		# Mixed: annotate which lines still block
		result["ib_ready_goods_direct_dn"] = False
		result["ib_mixed_fulfillment"] = True
		result.setdefault(
			"message",
			"Mixed SO: conversion lines still need OS/WO; Ready Goods lines may ship without WO.",
		)

	return result


@frappe.whitelist()
def probe_todo43(sales_order: str = None, item_conversion: str = None, item_ready: str = None, location: str = "gujarat"):
	"""bench execute / API probe for todo 43."""
	out = {
		"fg_warehouse_gujarat": fg_warehouse_for_location("gujarat"),
		"fg_warehouse_maharashtra": fg_warehouse_for_location("maharashtra"),
		"ready_wh_gujarat": allocate_sub_warehouse("gujarat", "Ready Goods"),
		"ready_wh_bwd": allocate_sub_warehouse("bwd", "Ready Goods"),
		"resolve": {},
		"so": None,
		"dn_helper": None,
	}
	if item_conversion:
		out["resolve"]["conversion_item"] = {
			"item": item_conversion,
			"path": resolve_fulfillment_path(item_conversion, location=location),
		}
	if item_ready:
		out["resolve"]["ready_item"] = {
			"item": item_ready,
			"path": resolve_fulfillment_path(item_ready, location=location),
		}
	if sales_order and frappe.db.exists("Sales Order", sales_order):
		so = frappe.get_doc("Sales Order", sales_order)
		out["so"] = {
			"name": so.name,
			"needs_production": so_needs_production(so),
			"pure_ready_goods": so_is_pure_ready_goods(so),
			"allows_direct_dn": so_allows_direct_dn(so),
			"location": so_location(so),
		}
		# Simulate blank DN
		class _DN:
			pass

		dn = _DN()
		dn.set_warehouse = None
		dn.against_sales_order = so.name
		dn.company = so.company
		dn.items = []
		for row in so.items[:3]:
			it = _DN()
			it.item_code = row.item_code
			it.warehouse = None
			it.so_detail = row.name
			it.against_sales_order = so.name
			dn.items.append(it)
		out["dn_helper"] = apply_dn_source_warehouses(dn, so=so)
	return out

def reprobe_todo43():
	"""Live sanity check for todo43 — call via bench execute."""
	import json
	from instabiz.overrides.dn_ready_goods import (
		so_needs_production, so_is_pure_ready_goods, resolve_fulfillment_path,
		apply_dn_source_warehouses, allocate_sub_warehouse, fg_warehouse_for_location,
	)
	from instabiz.overrides import manufacturing_site as ms

	out = {
		"fg": fg_warehouse_for_location("gujarat"),
		"ready_g": allocate_sub_warehouse("gujarat", "Ready Goods"),
		"ready_b": allocate_sub_warehouse("bwd", "Ready Goods"),
		"has_site_fn": hasattr(ms, "so_needs_production_site"),
		"sos": [],
	}
	sos = frappe.get_all(
		"Sales Order",
		filters={"docstatus": 1, "name": ("like", "IB-SGM-SO-%")},
		fields=["name"],
		order_by="modified desc",
		limit=3,
	)
	for s in sos:
		doc = frappe.get_doc("Sales Order", s.name)
		paths = [resolve_fulfillment_path(r.item_code, location=doc.custom_location) for r in (doc.items or [])[:3]]
		class T:
			pass
		dn = T()
		dn.set_warehouse = None
		dn.against_sales_order = doc.name
		dn.company = doc.company
		dn.items = []
		for row in (doc.items or [])[:2]:
			it = T()
			it.item_code = row.item_code
			it.warehouse = None
			it.so_detail = row.name
			dn.items.append(it)
		stats = apply_dn_source_warehouses(dn, so=doc)
		out["sos"].append({
			"so": doc.name,
			"site_only": bool(ms.so_needs_production_site(doc)),
			"fine": so_needs_production(doc),
			"wrapped": ms.so_needs_production(doc),
			"pure_ready": so_is_pure_ready_goods(doc),
			"paths": paths,
			"dn_wh": getattr(dn, "set_warehouse", None),
			"item_wh": [getattr(i, "warehouse", None) for i in dn.items],
		})
	bwd = frappe.get_all(
		"Sales Order",
		filters={"docstatus": 1, "custom_location": ("in", ["Maharashtra", "maharashtra", "MAHARASHTRA"])},
		fields=["name"],
		limit=2,
	)
	for s in bwd:
		doc = frappe.get_doc("Sales Order", s.name)
		out["sos"].append({
			"so": doc.name,
			"loc": doc.custom_location,
			"site_only": bool(ms.so_needs_production_site(doc)),
			"fine": so_needs_production(doc),
			"wrapped": ms.so_needs_production(doc),
			"pure_ready": so_is_pure_ready_goods(doc),
		})
	return out

def smoke_make_dn(so_name=None):
	"""Map a DN from SO and report warehouses (no save)."""
	so_name = so_name or "IB-BWD-SO-00759"
	from instabiz.overrides.sales_order import custom_make_delivery_note
	dn = custom_make_delivery_note(so_name)
	return {
		"so": so_name,
		"set_warehouse": getattr(dn, "set_warehouse", None),
		"item_warehouses": [getattr(r, "warehouse", None) for r in (dn.items or [])[:5]],
		"item_count": len(dn.items or []),
	}
