# Copyright (c) 2026, Instabiz and contributors
# License: MIT
"""
Todo 38 — Machine plans from IB Work Order lines (slitting / rewinding / cutting).

LOCKED (Idris 2026-09-21):
- 1 SO → 1 Order Sheet → 1 WO header + per-item output lines; track by Sales Order No.
- Set / cut widths ARE usable widths — do NOT subtract fixed trim again when packing.
- Trim/waste = jumbo usable_width_mm − sum(allocated cut widths) via allocation_trim_mm.
- Multi-width packing onto jumbo usable width to minimise leftover (e.g. 72+48 on 1200).
- Cutting undersize suggestion (todo44 seed): soft only, never auto-applied.
- Logs / SQM on WO remain estimates; cutting/packing stages still follow.

Whitelist surface (also re-exported from rewinding_plan / cutting_plan / slitting append):
  create_plan_from_wo(work_order, plan_type=None)
  suggest_multi_width_layout(...)
  suggest_cutting_undersize(...)
  probe_todo38()
  ensure_todo38_setup()
"""
from __future__ import annotations

import json
import math
from typing import Any, Optional

import frappe
from frappe.utils import cint, flt

MARKER = "todo38_mfg_plans"
PLAN_TYPES = ("slitting", "rewinding", "cutting")

PLAN_DOCTYPE = {
	"slitting": "IB Slitting Plan",
	"rewinding": "IB Rewinding Plan",
	"cutting": "IB Cutting Plan",
}

ROUTE_ALIASES = {
	"slitting": {"slitting", "slit", "slitter"},
	"rewinding": {"rewinding", "rewind", "rewinder"},
	"cutting": {"cutting", "cut", "cutter"},
}

DEFAULT_MIN_CUT_WIDTH_MM = 9.0
DEFAULT_UNDERSIZE_STEP_MM = 0.1
DEFAULT_MAX_UNDERSIZE_DELTA_MM = 1.0


# ── manufacturing_rules helpers ───────────────────────────────────────────────

def _mr():
	from instabiz.overrides import manufacturing_rules as mr

	return mr


def _mr_call(name: str, *args, default=None, **kwargs):
	try:
		fn = getattr(_mr(), name, None)
	except Exception:
		fn = None
	if not callable(fn):
		return default
	try:
		return fn(*args, **kwargs)
	except TypeError:
		try:
			return fn(*args)
		except Exception:
			return default
	except Exception:
		return default


def usable_width_mm(item_code: Optional[str] = None, width_mm: Any = None) -> float:
	"""Jumbo usable width. Prefer manufacturing_rules.usable_width_mm."""
	v = _mr_call("usable_width_mm", item_code, width_mm)
	if v is not None and flt(v) > 0:
		return flt(v)
	custom = None
	if item_code:
		try:
			custom = frappe.db.get_value("Item", item_code, "custom_usable_width_mm")
		except Exception:
			custom = None
		if width_mm is None:
			try:
				width_mm = frappe.db.get_value("Item", item_code, "width_mm")
			except Exception:
				width_mm = None
	if custom is not None and flt(custom) > 0:
		return flt(custom)
	return max(0.0, flt(width_mm))


def allocation_trim_mm(jumbo_usable_mm: Any, allocated_widths_mm: Any) -> float:
	"""Waste = jumbo usable − sum(allocated cut widths). Cuts are already usable widths."""
	v = _mr_call("allocation_trim_mm", jumbo_usable_mm, allocated_widths_mm)
	if v is not None:
		return flt(v)
	usable = flt(jumbo_usable_mm)
	total = 0.0
	if isinstance(allocated_widths_mm, (list, tuple)):
		for w in allocated_widths_mm:
			if isinstance(w, dict):
				total += flt(w.get("width_mm") or w.get("width") or 0) * max(
					1, cint(w.get("qty") or w.get("count") or 1)
				)
			else:
				total += flt(w)
	else:
		total = flt(allocated_widths_mm)
	return round(usable - total, 4)


# aliases expected by brief
allocation_trim_mm  # noqa: keep name
calc_sqm_needed = None  # set below
calc_logs_needed = None


def calc_sqm_needed(*args, **kwargs) -> float:
	v = _mr_call("calc_sqm_needed", *args, default=None, **kwargs)
	if v is not None:
		return flt(v)
	v = _mr_call("calculate_sqm_needed", *args, default=None, **kwargs)
	return flt(v) if v is not None else 0.0


def calc_logs_needed(*args, **kwargs) -> int:
	v = _mr_call("calc_logs_needed", *args, default=None, **kwargs)
	if v is not None:
		return cint(v)
	v = _mr_call("calculate_logs_needed", *args, default=None, **kwargs)
	return cint(v) if v is not None else 0


# ── Pure packing ──────────────────────────────────────────────────────────────

def _normalize_demands(cut_widths) -> list:
	out = []
	if cut_widths is None:
		return out
	if isinstance(cut_widths, (int, float, str)):
		cut_widths = [cut_widths]
	for i, row in enumerate(cut_widths):
		if isinstance(row, dict):
			w = flt(row.get("width_mm") or row.get("width") or row.get("cut_width_mm") or 0)
			qty = cint(row.get("qty") or row.get("count") or row.get("pcs") or row.get("pieces") or 1)
			key = row.get("key") or row.get("item_code") or row.get("name") or f"w{i}"
			meta = {
				k: v
				for k, v in row.items()
				if k
				not in (
					"width_mm",
					"width",
					"cut_width_mm",
					"qty",
					"count",
					"pcs",
					"pieces",
				)
			}
		else:
			w = flt(row)
			qty = 1
			key = f"w{i}"
			meta = {}
		if w <= 0 or qty <= 0:
			continue
		out.append({"width_mm": w, "qty": qty, "key": key, "meta": meta})
	return out


def pack_multi_width(usable_width_mm_val: Any, cut_widths: Any, *, max_bins: int = 5000) -> dict:
	"""First-fit decreasing multi-width packing into bins of size usable_width.

	Cut widths are treated as usable (no fixed trim subtracted).
	"""
	usable = flt(usable_width_mm_val)
	demands = _normalize_demands(cut_widths)
	pieces = []
	for d in demands:
		for _ in range(d["qty"]):
			pieces.append(
				{
					"width_mm": d["width_mm"],
					"key": d["key"],
					**({"meta": d["meta"]} if d.get("meta") else {}),
				}
			)
	pieces.sort(key=lambda p: (-flt(p["width_mm"]), str(p.get("key") or "")))

	bins = []
	unplaced = []
	if usable <= 0:
		return {
			"usable_width_mm": usable,
			"shafts": [],
			"unplaced": pieces,
			"total_allocated_mm": 0.0,
			"total_waste_mm": 0.0,
			"total_recovery_mm": 0.0,
			"pieces_placed": 0,
			"pieces_total": len(pieces),
			"shaft_count": 0,
			"algorithm": "first_fit_decreasing",
			"error": "usable_width_mm must be > 0",
		}

	for p in pieces:
		w = flt(p["width_mm"])
		if w > usable + 1e-9:
			unplaced.append(p)
			continue
		placed = False
		for b in bins:
			if b["remaining_mm"] + 1e-9 >= w:
				b["cuts"].append({"width_mm": w, "key": p.get("key"), "meta": p.get("meta")})
				b["allocated_mm"] = round(b["allocated_mm"] + w, 4)
				b["remaining_mm"] = round(usable - b["allocated_mm"], 4)
				b["allocation_trim_mm"] = b["remaining_mm"]
				placed = True
				break
		if not placed:
			if len(bins) >= max_bins:
				unplaced.append(p)
				continue
			bins.append(
				{
					"shaft_no": len(bins) + 1,
					"usable_width_mm": usable,
					"cuts": [{"width_mm": w, "key": p.get("key"), "meta": p.get("meta")}],
					"allocated_mm": round(w, 4),
					"remaining_mm": round(usable - w, 4),
					"allocation_trim_mm": round(usable - w, 4),
				}
			)

	for b in bins:
		counts = {}
		for c in b["cuts"]:
			k = f"{c.get('key')}|{c['width_mm']}"
			if k not in counts:
				counts[k] = {
					"width_mm": c["width_mm"],
					"key": c.get("key"),
					"qty": 0,
					"meta": c.get("meta"),
				}
			counts[k]["qty"] += 1
		b["cut_summary"] = list(counts.values())
		fit = [d["width_mm"] for d in demands if d["width_mm"] <= b["remaining_mm"] + 1e-9]
		b["recovery_candidate_width_mm"] = max(fit) if fit else None
		b["recovery_mm"] = b["remaining_mm"] if b["recovery_candidate_width_mm"] else 0.0

	return {
		"usable_width_mm": usable,
		"shafts": bins,
		"unplaced": unplaced,
		"total_allocated_mm": round(sum(b["allocated_mm"] for b in bins), 4),
		"total_waste_mm": round(sum(b["allocation_trim_mm"] for b in bins), 4),
		"total_recovery_mm": round(sum(b.get("recovery_mm") or 0 for b in bins), 4),
		"pieces_placed": sum(len(b["cuts"]) for b in bins),
		"pieces_total": len(pieces),
		"shaft_count": len(bins),
		"algorithm": "first_fit_decreasing",
		"note": "Cut widths treated as usable; waste = usable − sum(cuts) per shaft (allocation_trim_mm).",
		"marker": MARKER,
	}


def suggest_cutting_undersize_pure(
	usable_width_mm_val: Any,
	width_mm: Any,
	*,
	pcs: Any = None,
	min_width_mm: Any = DEFAULT_MIN_CUT_WIDTH_MM,
	step_mm: Any = DEFAULT_UNDERSIZE_STEP_MM,
	max_delta_mm: Any = DEFAULT_MAX_UNDERSIZE_DELTA_MM,
) -> dict:
	"""Soft suggestion only — never auto-applies (todo44 seed)."""
	usable = flt(usable_width_mm_val)
	w = flt(width_mm)
	min_w = flt(min_width_mm) if min_width_mm is not None else DEFAULT_MIN_CUT_WIDTH_MM
	step = flt(step_mm) if step_mm else DEFAULT_UNDERSIZE_STEP_MM
	max_delta = flt(max_delta_mm) if max_delta_mm is not None else DEFAULT_MAX_UNDERSIZE_DELTA_MM

	out = {
		"usable_width_mm": usable,
		"ordered_width_mm": w,
		"suggestion": None,
		"applied": False,
		"soft": True,
		"todo": 44,
		"message": None,
		"marker": MARKER,
	}
	if usable <= 0 or w <= 0:
		out["message"] = "usable_width_mm and width_mm must be > 0"
		return out

	n = cint(pcs) if pcs is not None else int(math.floor(usable / w))
	if n <= 0:
		out["message"] = "Cannot fit even 1 piece at ordered width"
		if w > usable and usable >= min_w:
			out["suggestion"] = {
				"suggested_width_mm": round(usable, 4),
				"pcs_at_ordered": 0,
				"pcs_at_suggested": 1,
				"waste_at_ordered_mm": usable,
				"waste_at_suggested_mm": 0.0,
				"delta_mm": round(w - usable, 4),
			}
			out["message"] = "Ordered width exceeds usable; soft suggest width = usable"
		return out

	waste = round(usable - n * w, 4)
	out["pcs_at_ordered"] = n
	out["waste_at_ordered_mm"] = waste

	target_pcs = n + 1
	ideal = usable / target_pcs
	suggested = math.floor(ideal / step) * step if step > 0 else ideal
	suggested = round(suggested, 4)

	if suggested < min_w:
		out["message"] = f"No undersize within min_width_mm={min_w}"
		return out
	if suggested >= w - 1e-9:
		out["message"] = "Already optimal or no beneficial undersize"
		return out
	if (w - suggested) > max_delta + 1e-9:
		clamped = round(w - max_delta, 4)
		if clamped >= min_w and int(math.floor(usable / clamped + 1e-9)) >= target_pcs:
			suggested = clamped
		else:
			out["message"] = (
				f"Beneficial undersize to fit {target_pcs} would require delta > "
				f"max_delta_mm={max_delta}; not suggesting"
			)
			return out

	pcs_s = int(math.floor(usable / suggested + 1e-9))
	if pcs_s <= n:
		out["message"] = "Undersize would not fit an extra piece"
		return out

	out["suggestion"] = {
		"suggested_width_mm": suggested,
		"pcs_at_ordered": n,
		"pcs_at_suggested": pcs_s,
		"waste_at_ordered_mm": waste,
		"waste_at_suggested_mm": round(usable - pcs_s * suggested, 4),
		"delta_mm": round(w - suggested, 4),
		"example": "e.g. 10 → 9.9 to fit one more piece when waste would otherwise be lost",
	}
	out["message"] = (
		f"Soft suggest {suggested} mm ({pcs_s} pcs) instead of {w} mm ({n} pcs); "
		"operator must confirm — not auto-applied"
	)
	return out


# ── WO extraction ─────────────────────────────────────────────────────────────

def _row_get(row, *names, default=None):
	for n in names:
		if isinstance(row, dict):
			if n in row and row[n] is not None:
				return row[n]
		elif hasattr(row, n):
			v = getattr(row, n)
			if v is not None:
				return v
	return default


def _stage_blob(row) -> str:
	parts = []
	for f in ("stage", "stage_name", "process", "operation", "route_stage", "name"):
		parts.append(str(_row_get(row, f, default="") or ""))
	return " ".join(parts).lower()


def detect_plan_types_from_wo(wo) -> list:
	found = set()
	for row in getattr(wo, "route", None) or []:
		blob = _stage_blob(row)
		for pt, aliases in ROUTE_ALIASES.items():
			if any(a in blob for a in aliases):
				found.add(pt)
	cur = str(getattr(wo, "current_stage", "") or getattr(wo, "stage", "") or "").lower()
	for pt, aliases in ROUTE_ALIASES.items():
		if any(a in cur for a in aliases):
			found.add(pt)
	machine = getattr(wo, "machine", None)
	if machine:
		try:
			mtype = (
				frappe.db.get_value("IB Machine", machine, "machine_type")
				or frappe.db.get_value("IB Machine", machine, "machine_name")
				or ""
			).lower()
			for pt, aliases in ROUTE_ALIASES.items():
				if any(a in mtype for a in aliases):
					found.add(pt)
		except Exception:
			pass
	if not found and (getattr(wo, "outputs", None) or []):
		found.add("slitting")
	return [p for p in PLAN_TYPES if p in found]


def extract_wo_cut_demands(wo) -> list:
	demands = []
	outputs = getattr(wo, "outputs", None) or []
	for idx, row in enumerate(outputs):
		item = _row_get(row, "item_code", "item", "fg_item")
		w = flt(_row_get(row, "width_mm", "cut_width_mm", "finished_width_mm", default=0))
		if w <= 0 and item:
			try:
				w = flt(frappe.db.get_value("Item", item, "width_mm"))
			except Exception:
				w = 0
		qty = flt(_row_get(row, "qty", "output_qty", "ordered_qty", "pcs", default=0))
		stock_uom = _row_get(row, "stock_uom", "uom")
		length_mtr = _row_get(row, "length_mtr", "length")
		pcs = cint(_row_get(row, "pcs", "pieces", "no_of_rolls", default=0))
		if pcs <= 0:
			uom = str(stock_uom or "").strip().upper()
			if uom in ("SQM", "SQMT", "M2", "M²") and w > 0:
				area = 0.0
				if length_mtr:
					area = (flt(w) / 1000.0) * flt(length_mtr)
				pcs = cint(math.ceil(qty / area)) if area > 0 else (cint(math.ceil(qty)) if qty else 1)
			else:
				pcs = cint(math.ceil(qty)) if qty else 1
		if pcs <= 0:
			pcs = 1
		if w <= 0:
			continue
		sqm = _row_get(row, "sqm_needed", "sqm_needed")
		logs = _row_get(row, "logs_needed", "logs_needed")
		if sqm is None:
			sqm = calc_sqm_needed(qty or pcs, w, length_mtr, item_code=item, stock_uom=stock_uom)
		if logs is None:
			logs = calc_logs_needed(qty or pcs, w, length_mtr, item_code=item, stock_uom=stock_uom)
		demands.append(
			{
				"width_mm": w,
				"qty": pcs,
				"key": item or f"line{idx}",
				"item_code": item,
				"qty_raw": qty,
				"length_mtr": length_mtr,
				"sqm_needed": flt(sqm) if sqm is not None else None,
				"logs_needed": cint(logs) if logs is not None else None,
				"row_idx": idx,
			}
		)
	# Fallback: WO header often has empty outputs until stage start — pull OS / SO lines
	if not demands:
		demands = _demands_from_order_sheet(wo)
	return demands


def _demands_from_order_sheet(wo) -> list:
	"""Build cut demands from linked IB Order Sheet items (and Item.width_mm)."""
	out = []
	os_name = getattr(wo, "order_sheet", None) if wo else None
	so_name = getattr(wo, "sales_order", None) if wo else None
	rows = []
	if os_name and frappe.db.exists("IB Order Sheet", os_name):
		try:
			os_doc = frappe.get_doc("IB Order Sheet", os_name)
			rows = list(os_doc.get("items") or [])
		except Exception:
			rows = []
	if not rows and so_name and frappe.db.exists("Sales Order", so_name):
		try:
			so = frappe.get_doc("Sales Order", so_name)
			rows = list(so.get("items") or [])
		except Exception:
			rows = []
	for idx, row in enumerate(rows):
		item = _row_get(row, "item_code", "item")
		if not item:
			continue
		w = flt(_row_get(row, "width_mm", "custom_width_mm", "cut_width_mm", default=0))
		if w <= 0:
			try:
				w = flt(frappe.db.get_value("Item", item, "width_mm"))
			except Exception:
				w = 0
		if w <= 0:
			continue
		qty = flt(_row_get(row, "qty", "ordered_qty", default=0)) or 1
		uom = str(_row_get(row, "uom", "stock_uom") or "").upper()
		length_mtr = _row_get(row, "length_mtr", "length")
		if not length_mtr:
			try:
				length_mtr = frappe.db.get_value("Item", item, "length_mtr")
			except Exception:
				length_mtr = None
		pcs = cint(math.ceil(qty)) if uom not in ("SQM", "SQMT", "M2", "M²") else 0
		if pcs <= 0 and uom in ("SQM", "SQMT", "M2", "M²") and w > 0 and length_mtr:
			area = (flt(w) / 1000.0) * flt(length_mtr)
			pcs = cint(math.ceil(qty / area)) if area > 0 else cint(math.ceil(qty))
		if pcs <= 0:
			pcs = cint(math.ceil(qty)) if qty else 1
		out.append({
			"width_mm": w,
			"qty": pcs,
			"key": item or f"os{idx}",
			"item_code": item,
			"qty_raw": qty,
			"length_mtr": length_mtr,
			"sqm_needed": None,
			"logs_needed": None,
			"row_idx": idx,
			"source": "order_sheet_or_so",
		})
	return out


def resolve_jumbo_usable(wo=None, jumbo_item: Optional[str] = None, jumbo_width_mm: Any = None) -> dict:
	item = jumbo_item or (getattr(wo, "source_item", None) if wo else None)
	raw_w = jumbo_width_mm
	if raw_w is None and wo:
		for f in ("jumbo_width_mm", "source_width_mm", "log_width_mm"):
			if getattr(wo, f, None):
				raw_w = getattr(wo, f)
				break
	# source_batch → IB Batch.item
	if not item and wo and getattr(wo, "source_batch", None):
		try:
			item = frappe.db.get_value("IB Batch", wo.source_batch, "item")
		except Exception:
			item = item
	# Fall back to widest ordered cut * packs is wrong for jumbo — use Item of first demand's... no.
	# Use IB Stock Settings default jumbo width if still blank, else max common tape jumbo 1200/1315 from location.
	if raw_w is None and item:
		try:
			raw_w = frappe.db.get_value("Item", item, "width_mm")
		except Exception:
			raw_w = None
	if (raw_w is None or flt(raw_w) <= 0) and wo:
		# Prefer custom_usable on any linked FG? For planning UI, default 1200 mm jumbo when unknown.
		try:
			from instabiz.overrides import ib_settings
			raw_w = ib_settings.get_float("default_jumbo_width_mm", 0) or None
		except Exception:
			raw_w = None
		if not raw_w:
			raw_w = 1200.0  # planner default; operator can override on plan
	usable = usable_width_mm(item, raw_w)
	meta = _mr_call("usable_width_plan_note", item, raw_w, default=None) or {
		"item_code": item,
		"width_mm": flt(raw_w),
		"usable_width_mm": usable,
		"source": "todo38_resolve_jumbo_usable",
	}
	return {
		"jumbo_item": item,
		"jumbo_width_mm": flt(raw_w) if raw_w is not None else None,
		"usable_width_mm": usable,
		"meta": meta,
	}


def _normalize_plan_type(plan_type: Optional[str]) -> Optional[str]:
	if not plan_type:
		return None
	s = str(plan_type).strip().lower()
	for pt, aliases in ROUTE_ALIASES.items():
		if s == pt or s in aliases:
			return pt
	return s if s in PLAN_TYPES else None


def _plan_fieldname(plan_type: str) -> str:
	return f"custom_{plan_type}_plan_json"


def _plan_link_fieldname(plan_type: str) -> str:
	return f"custom_{plan_type}_plan"


# ── Persist ───────────────────────────────────────────────────────────────────

def _persist_plan_on_wo(wo, plan_type: str, plan: dict) -> dict:
	result = {"stored_on_wo": False, "doctype_created": None, "doctype_name": None, "notes": []}
	field = _plan_fieldname(plan_type)
	link_field = _plan_link_fieldname(plan_type)
	dt = PLAN_DOCTYPE.get(plan_type)

	if dt and frappe.db.exists("DocType", dt):
		try:
			meta = frappe.get_meta(dt)
			existing = None
			if meta.has_field("work_order"):
				rows = frappe.get_all(
					dt,
					filters={"work_order": wo.name},
					fields=["name", "docstatus"],
					order_by="modified desc",
					limit=5,
				)
				for r in rows:
					if cint(r.get("docstatus")) == 0:
						existing = r.name
						break
			if existing:
				doc = frappe.get_doc(dt, existing)
				result["notes"].append(f"reopened draft {dt} {existing}")
			else:
				doc = frappe.new_doc(dt)
				if meta.has_field("work_order"):
					doc.work_order = wo.name
				if meta.has_field("sales_order") and getattr(wo, "sales_order", None):
					doc.sales_order = wo.sales_order
				if meta.has_field("order_sheet") and getattr(wo, "order_sheet", None):
					doc.order_sheet = wo.order_sheet
				if meta.has_field("plan_type"):
					doc.plan_type = plan_type
				result["notes"].append(f"created new {dt}")

			payload = json.dumps(plan, default=str)
			for fname, val in (
				("usable_width_mm", (plan.get("layout") or {}).get("usable_width_mm")),
				("total_waste_mm", (plan.get("layout") or {}).get("total_waste_mm")),
				("allocation_trim_mm", (plan.get("layout") or {}).get("total_waste_mm")),
				("jumbo_item", (plan.get("jumbo") or {}).get("jumbo_item")),
				("jumbo_width_mm", (plan.get("jumbo") or {}).get("jumbo_width_mm")),
				("plan_json", payload),
				("layout_json", payload),
				("notes", plan.get("summary")),
			):
				if meta.has_field(fname):
					try:
						setattr(doc, fname, val)
					except Exception:
						pass
			doc.save(ignore_permissions=True)
			frappe.db.commit()
			result["doctype_created"] = dt
			result["doctype_name"] = doc.name
			plan["plan_doc"] = {"doctype": dt, "name": doc.name}
		except Exception as e:
			result["notes"].append(f"doctype persist failed: {e}")

	try:
		meta_wo = frappe.get_meta("IB Work Order")
		if meta_wo.has_field(field):
			setattr(wo, field, json.dumps(plan, default=str))
			if result.get("doctype_name") and meta_wo.has_field(link_field):
				setattr(wo, link_field, result["doctype_name"])
			wo.flags.ignore_validate_update_after_submit = True
			wo.save(ignore_permissions=True)
			frappe.db.commit()
			result["stored_on_wo"] = True
		else:
			result["notes"].append(f"WO missing field {field} — run ensure_todo38_setup")
	except Exception as e:
		result["notes"].append(f"WO store failed: {e}")
	return result


def _try_slitting_create_pass(wo, plan: dict) -> dict:
	out = {"called": False, "result": None, "error": None}
	try:
		from instabiz.overrides import slitting_plan as sp

		fn = getattr(sp, "create_pass", None)
		if not callable(fn):
			out["error"] = "create_pass not found"
			return out
		import inspect

		sig = inspect.signature(fn)
		kwargs = {}
		for name in ("work_order", "wo", "sales_order", "plan", "layout"):
			if name in sig.parameters:
				if name in ("work_order", "wo"):
					kwargs[name] = wo.name
				elif name == "sales_order":
					kwargs[name] = getattr(wo, "sales_order", None)
				elif name in ("plan", "layout"):
					kwargs[name] = plan.get("layout")
		if kwargs:
			out["result"] = fn(**kwargs)
			out["called"] = True
		else:
			out["error"] = "create_pass has no WO/plan kwargs — skipped"
	except Exception as e:
		out["error"] = str(e)
	return out


# ── Whitelist API ─────────────────────────────────────────────────────────────

@frappe.whitelist()
def suggest_multi_width_layout(
	usable_width_mm: Any = None,
	cut_widths: Any = None,
	jumbo_item: Optional[str] = None,
	jumbo_width_mm: Any = None,
	work_order: Optional[str] = None,
) -> dict:
	"""Pack ordered cut widths onto jumbo usable width (multi-width, min leftover)."""
	if isinstance(cut_widths, str):
		try:
			cut_widths = json.loads(cut_widths)
		except Exception:
			cut_widths = [x.strip() for x in cut_widths.split(",") if x.strip()]

	wo = None
	if work_order and frappe.db.exists("IB Work Order", work_order):
		wo = frappe.get_doc("IB Work Order", work_order)

	jumbo_meta = None
	if usable_width_mm is None or flt(usable_width_mm) <= 0:
		jumbo_meta = resolve_jumbo_usable(wo, jumbo_item=jumbo_item, jumbo_width_mm=jumbo_width_mm)
		usable_width_mm = jumbo_meta.get("usable_width_mm")
	else:
		jumbo_meta = {
			"usable_width_mm": flt(usable_width_mm),
			"jumbo_item": jumbo_item,
			"jumbo_width_mm": flt(jumbo_width_mm) if jumbo_width_mm is not None else None,
		}

	if cut_widths is None and wo:
		cut_widths = extract_wo_cut_demands(wo)

	layout = pack_multi_width(usable_width_mm, cut_widths)
	layout["jumbo"] = jumbo_meta
	layout["work_order"] = work_order or (wo.name if wo else None)
	layout["sales_order"] = getattr(wo, "sales_order", None) if wo else None
	for shaft in layout.get("shafts") or []:
		shaft["allocation_trim_mm"] = allocation_trim_mm(
			shaft["usable_width_mm"],
			[c["width_mm"] for c in shaft.get("cuts") or []],
		)
	return layout


@frappe.whitelist()
def suggest_cutting_undersize(
	usable_width_mm: Any = None,
	width_mm: Any = None,
	pcs: Any = None,
	min_width_mm: Any = None,
	step_mm: Any = None,
	max_delta_mm: Any = None,
	work_order: Optional[str] = None,
	jumbo_item: Optional[str] = None,
) -> dict:
	"""Soft cutting undersize suggestion (todo44 seed). Never auto-applies."""
	wo = None
	if work_order and frappe.db.exists("IB Work Order", work_order):
		wo = frappe.get_doc("IB Work Order", work_order)
	if (usable_width_mm is None or flt(usable_width_mm) <= 0) and (wo or jumbo_item):
		usable_width_mm = resolve_jumbo_usable(wo, jumbo_item=jumbo_item)["usable_width_mm"]
	if width_mm is None and wo:
		demands = extract_wo_cut_demands(wo)
		if demands:
			width_mm = demands[0]["width_mm"]
	return suggest_cutting_undersize_pure(
		usable_width_mm,
		width_mm,
		pcs=pcs,
		min_width_mm=min_width_mm if min_width_mm is not None else DEFAULT_MIN_CUT_WIDTH_MM,
		step_mm=step_mm if step_mm is not None else DEFAULT_UNDERSIZE_STEP_MM,
		max_delta_mm=max_delta_mm if max_delta_mm is not None else DEFAULT_MAX_UNDERSIZE_DELTA_MM,
	)


@frappe.whitelist()
def create_plan_from_wo(work_order: str, plan_type: Optional[str] = None) -> dict:
	"""Generate (and persist when possible) Slitting/Rewinding/Cutting plan from a WO."""
	if not work_order or not frappe.db.exists("IB Work Order", work_order):
		frappe.throw(f"IB Work Order not found: {work_order}")

	wo = frappe.get_doc("IB Work Order", work_order)
	pt = _normalize_plan_type(plan_type)
	types = [pt] if pt else detect_plan_types_from_wo(wo)
	if not types:
		types = ["slitting"]

	demands = extract_wo_cut_demands(wo)
	jumbo = resolve_jumbo_usable(wo)
	layout = pack_multi_width(jumbo["usable_width_mm"], demands)

	plans = []
	for t in types:
		plan = {
			"plan_type": t,
			"work_order": wo.name,
			"sales_order": getattr(wo, "sales_order", None),
			"order_sheet": getattr(wo, "order_sheet", None),
			"jumbo": jumbo,
			"demands": demands,
			"layout": layout,
			"summary": (
				f"{t.title()} plan for {wo.name} (SO {getattr(wo, 'sales_order', '') or '—'}): "
				f"{layout.get('shaft_count', 0)} shaft(s), "
				f"waste {layout.get('total_waste_mm', 0)} mm total, "
				f"usable {layout.get('usable_width_mm', 0)} mm"
			),
			"estimates_note": (
				"sqm_needed / logs_needed on WO are estimates only; packing/cutting stages still follow."
			),
			"locked_rule": "Set widths are usable widths; allocation_trim_mm = usable − sum(cuts).",
			"marker": MARKER,
		}
		if t == "cutting":
			suggestions = []
			seen = set()
			for d in demands:
				w = d["width_mm"]
				if w in seen:
					continue
				seen.add(w)
				suggestions.append(suggest_cutting_undersize_pure(jumbo["usable_width_mm"], w))
			plan["undersize_suggestions"] = suggestions
		persist = _persist_plan_on_wo(wo, t, plan)
		plan["persist"] = persist
		if t == "slitting":
			plan["legacy_handoff"] = _try_slitting_create_pass(wo, plan)
		plans.append(plan)

	if plan_type and len(plans) == 1:
		return plans[0]
	return {
		"work_order": wo.name,
		"sales_order": getattr(wo, "sales_order", None),
		"plans": plans,
		"detected_types": types,
		"marker": MARKER,
	}


@frappe.whitelist()
def list_plan_types_for_wo(work_order: str) -> dict:
	if not work_order or not frappe.db.exists("IB Work Order", work_order):
		return {"work_order": work_order, "types": []}
	wo = frappe.get_doc("IB Work Order", work_order)
	return {"work_order": work_order, "types": detect_plan_types_from_wo(wo)}


# ── Ensure setup ──────────────────────────────────────────────────────────────

def ensure_todo38_setup() -> dict:
	"""Idempotent custom fields on IB Work Order + Client Script buttons."""
	result = {"fields": [], "client_script": None, "notes": []}
	if not frappe.db.exists("DocType", "IB Work Order"):
		result["notes"].append("IB Work Order DocType missing — skip")
		return result

	try:
		from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
	except Exception as e:
		result["notes"].append(f"create_custom_fields unavailable: {e}")
		return result

	fields = []
	for pt in PLAN_TYPES:
		fields.append(
			{
				"fieldname": _plan_fieldname(pt),
				"label": f"{pt.title()} Plan JSON",
				"fieldtype": "Long Text",
				"read_only": 1,
				"description": f"Todo38 {pt} plan payload. Marker={MARKER}",
				"insert_after": "notes",
			}
		)
		fields.append(
			{
				"fieldname": _plan_link_fieldname(pt),
				"label": f"{pt.title()} Plan",
				"fieldtype": "Data",
				"read_only": 1,
				"description": f"Link/name of {PLAN_DOCTYPE.get(pt)} when that DocType exists.",
				"insert_after": _plan_fieldname(pt),
			}
		)
	create_custom_fields({"IB Work Order": fields}, update=True)
	for f in fields:
		result["fields"].append(f"IB Work Order.{f['fieldname']}")

	cs_name = "IB Work Order — MFG Plans (todo38)"
	js = _client_script_js()
	if frappe.db.exists("Client Script", cs_name):
		doc = frappe.get_doc("Client Script", cs_name)
		doc.script = js
		doc.enabled = 1
		doc.save(ignore_permissions=True)
		result["client_script"] = f"updated:{cs_name}"
	else:
		doc = frappe.get_doc(
			{
				"doctype": "Client Script",
				"name": cs_name,
				"dt": "IB Work Order",
				"view": "Form",
				"enabled": 1,
				"script": js,
			}
		)
		doc.insert(ignore_permissions=True)
		result["client_script"] = f"created:{cs_name}"
	frappe.db.commit()
	return result


def _client_script_js() -> str:
	return r"""
// Todo38 — Create Slitting / Rewinding / Cutting Plan from IB Work Order
frappe.ui.form.on('IB Work Order', {
	refresh(frm) {
		if (frm.is_new()) return;
		const add = (label, plan_type) => {
			frm.add_custom_button(__(label), () => {
				frappe.call({
					method: 'instabiz.overrides.mfg_plans.create_plan_from_wo',
					args: { work_order: frm.doc.name, plan_type },
					freeze: true,
					freeze_message: __('Building {0} plan…', [label]),
					callback(r) {
						const p = r.message || {};
						frappe.msgprint({
							title: __('Plan ready'),
							indicator: 'green',
							message: p.summary || JSON.stringify(p).slice(0, 500),
						});
						frm.reload_doc();
						const pd = p.plan_doc;
						if (pd && pd.doctype && pd.name) {
							frappe.set_route('Form', pd.doctype, pd.name);
						}
					},
				});
			}, __('Create Plan'));
		};
		add('Slitting Plan', 'slitting');
		add('Rewinding Plan', 'rewinding');
		add('Cutting Plan', 'cutting');
		frm.add_custom_button(__('Auto (from route)'), () => {
			frappe.call({
				method: 'instabiz.overrides.mfg_plans.create_plan_from_wo',
				args: { work_order: frm.doc.name },
				freeze: true,
				callback(r) {
					const msg = r.message || {};
					const plans = msg.plans || [msg];
					const lines = plans.map(p => p.summary || p.plan_type).join('<br>');
					frappe.msgprint({ title: __('Plans'), indicator: 'green', message: lines || __('Done') });
					frm.reload_doc();
				},
			});
		}, __('Create Plan'));
		frm.add_custom_button(__('Suggest multi-width layout'), () => {
			frappe.call({
				method: 'instabiz.overrides.mfg_plans.suggest_multi_width_layout',
				args: { work_order: frm.doc.name },
				callback(r) {
					const L = r.message || {};
					frappe.msgprint({
						title: __('Multi-width layout'),
						message: `Shafts: ${L.shaft_count || 0}<br>Waste: ${L.total_waste_mm || 0} mm<br>Usable: ${L.usable_width_mm || 0} mm`,
					});
				},
			});
		}, __('Create Plan'));
		frm.add_custom_button(__('Suggest cutting undersize'), () => {
			frappe.call({
				method: 'instabiz.overrides.mfg_plans.suggest_cutting_undersize',
				args: { work_order: frm.doc.name },
				callback(r) {
					const s = r.message || {};
					frappe.msgprint({
						title: __('Undersize suggestion (soft)'),
						message: s.message || JSON.stringify(s.suggestion || s),
					});
				},
			});
		}, __('Create Plan'));
	},
});
""".strip()


def after_migrate():
	try:
		ensure_todo38_setup()
	except Exception:
		frappe.log_error(title="todo38 ensure_todo38_setup failed")


@frappe.whitelist()
def probe_todo38(work_order: str = None) -> dict:
	"""bench execute / API probe — pure layout + optional WO plan (no stock posts)."""
	out = {
		"marker": MARKER,
		"todo": 38,
		"helpers": {},
		"examples": {},
		"wo": None,
		"ensure": None,
		"status": "ok",
	}
	try:
		mr = _mr()
		out["helpers"] = {
			"usable_width_mm": callable(getattr(mr, "usable_width_mm", None)),
			"allocation_trim_mm": callable(getattr(mr, "allocation_trim_mm", None)),
			"calculate_sqm_needed": callable(getattr(mr, "calculate_sqm_needed", None)),
			"calculate_logs_needed": callable(getattr(mr, "calculate_logs_needed", None)),
			"calc_sqm_needed": callable(getattr(mr, "calc_sqm_needed", None)),
			"calc_logs_needed": callable(getattr(mr, "calc_logs_needed", None)),
		}
	except Exception as e:
		out["helpers"]["error"] = str(e)

	ex = pack_multi_width(1200, [{"width_mm": 72, "qty": 10}, {"width_mm": 48, "qty": 10}])
	out["examples"]["pack_72_48_on_1200"] = {
		"shaft_count": ex["shaft_count"],
		"total_waste_mm": ex["total_waste_mm"],
		"pieces_placed": ex["pieces_placed"],
		"first_shaft_summary": (ex["shafts"][0]["cut_summary"] if ex["shafts"] else None),
		"first_shaft_trim": (ex["shafts"][0]["allocation_trim_mm"] if ex["shafts"] else None),
	}
	out["examples"]["allocation_trim_72_48"] = allocation_trim_mm(1200, [72, 48])
	out["examples"]["undersize_10_on_99"] = suggest_cutting_undersize_pure(99, 10)
	out["examples"]["undersize_10_5_on_100"] = suggest_cutting_undersize_pure(100, 10.5)
	out["examples"]["set_width_no_double_trim"] = {
		"rule": "set widths are usable; packing uses 72 as 72 not 72-trim",
		"allocation_trim_mm(1200,[72,48])": allocation_trim_mm(1200, [72, 48]),
	}

	if work_order and frappe.db.exists("IB Work Order", work_order):
		try:
			out["wo"] = create_plan_from_wo(work_order)
		except Exception as e:
			out["wo_error"] = str(e)

	try:
		out["ensure"] = ensure_todo38_setup()
	except Exception as e:
		out["ensure_error"] = str(e)

	return out


# Back-compat aliases used in brief / client wording
suggest_multi_width_layout  # noqa
create_plan_from_wo  # noqa
suggest_cutting_undersize  # noqa
# brief named suggest_cutting_undersize / suggest_multi_width_layout / create_plan_from_wo

def smoke_plan_wo():
	import frappe
	from instabiz.overrides.mfg_plans import create_plan_from_wo, suggest_multi_width_layout, list_plan_types_for_wo
	wos = frappe.get_all('IB Work Order', filters={'docstatus': ['<', 2]}, fields=['name'], order_by='modified desc', limit=5)
	out = {'wos_tried': [], 'ok': None}
	for w in wos:
		try:
			types = list_plan_types_for_wo(w.name)
			layout = suggest_multi_width_layout(work_order=w.name)
			plan = create_plan_from_wo(w.name)
			out['ok'] = {
				'so_wo': w.name,
				'types': types,
				'layout_shafts': (layout or {}).get('shaft_count'),
				'layout_waste': (layout or {}).get('total_waste_mm'),
				'plan_summary': (plan.get('summary') if isinstance(plan, dict) else None) or (plan.get('plans') if isinstance(plan, dict) else str(plan)[:300]),
			}
			out['wos_tried'].append(w.name)
			break
		except Exception as e:
			out['wos_tried'].append({'name': w.name, 'err': str(e)[:200]})
	return out

def dump_wo_shape(name='IB-WO-2026-29510'):
	import frappe
	wo = frappe.get_doc('IB Work Order', name)
	meta = frappe.get_meta('IB Work Order')
	child_tables = [df.fieldname for df in meta.fields if df.fieldtype=='Table']
	out = {
		'name': wo.name,
		'parent_keys': sorted([k for k in wo.as_dict().keys() if not k.startswith('_')])[:80],
		'child_tables': child_tables,
		'source_item': wo.get('source_item'),
		'source_width': wo.get('source_width_mm') or wo.get('jumbo_width_mm') or wo.get('width_mm'),
		'location': wo.get('location'),
		'stage': wo.get('stage'),
	}
	for ct in child_tables:
		rows = wo.get(ct) or []
		out[ct] = {
			'count': len(rows),
			'sample': rows[0].as_dict() if rows else None,
			'keys': list(rows[0].as_dict().keys()) if rows else [],
		}
	return out

def find_wo_rich():
	import frappe
	meta = frappe.get_meta("IB Work Order")
	out_df = meta.get_field("outputs")
	child = out_df.options if out_df else None
	rows = []
	if child and frappe.db.table_exists(child):
		rows = frappe.db.sql(
			"SELECT parent, COUNT(*) AS c FROM `tab{0}` GROUP BY parent ORDER BY c DESC LIMIT 10".format(child),
			as_dict=True,
		)
	sample = None
	if rows:
		wo = frappe.get_doc("IB Work Order", rows[0].parent)
		sample = {
			"name": wo.name,
			"source_item": wo.get("source_item"),
			"sales_order": wo.get("sales_order"),
			"order_sheet": wo.get("order_sheet"),
			"first_output": (wo.outputs[0].as_dict() if wo.outputs else None),
			"output_keys": list(wo.outputs[0].as_dict().keys()) if wo.outputs else [],
		}
	# Also WOs with source_item
	with_src = frappe.get_all(
		"IB Work Order",
		filters={"source_item": ["!=", ""]},
		fields=["name", "source_item", "sales_order", "order_sheet", "status"],
		order_by="modified desc",
		limit=5,
	)
	# Order sheet items for a linked OS
	os_sample = None
	if sample and sample.get("order_sheet"):
		osi = frappe.get_all(
			"IB Order Sheet Item",
			filters={"parent": sample["order_sheet"]},
			fields=["name", "item_code", "qty", "uom", "width_mm", "custom_width_mm"],
			limit=5,
		)
		os_sample = osi
	return {
		"outputs_child_doctype": child,
		"top_wos": rows,
		"sample": sample,
		"with_source_item": with_src,
		"os_items": os_sample,
	}
