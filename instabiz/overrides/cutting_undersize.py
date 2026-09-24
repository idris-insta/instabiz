# Copyright (c) 2026, Instabiz and contributors
# License: MIT
"""
Todo 44 — Cutting undersize accept/apply.

LOCKED (Idris): Soft until operator confirms; then write suggested width into
plan/demands. Set widths are usable. Never change Item master width without
explicit update_item_master=1.
"""
from __future__ import annotations

import json
from typing import Any, Optional

import frappe
from frappe.utils import cint, flt, now_datetime

MARKER = "todo44_cutting_undersize"


def _mp():
	try:
		from instabiz.overrides import mfg_plans as mp
		return mp
	except Exception:
		from instabiz.overrides import mfg_plans as mp  # noqa: F401
		return mp


def _loads(raw: Any) -> Any:
	if raw is None or raw == "":
		return None
	if isinstance(raw, (dict, list)):
		return raw
	try:
		return json.loads(raw)
	except Exception:
		return None


def _dumps(obj: Any) -> str:
	return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


def _parse_payload(suggestion_payload: Any) -> dict:
	if suggestion_payload is None or suggestion_payload == "":
		return {}
	if isinstance(suggestion_payload, dict):
		return suggestion_payload
	if isinstance(suggestion_payload, str):
		parsed = _loads(suggestion_payload)
		return parsed if isinstance(parsed, dict) else {}
	return {}


def _resolve_suggested_width(payload: dict, suggested_width_mm: Any = None) -> float:
	if suggested_width_mm is not None and flt(suggested_width_mm) > 0:
		return flt(suggested_width_mm)
	sug = payload.get("suggestion") if isinstance(payload.get("suggestion"), dict) else None
	if sug is None and isinstance(payload.get("suggestions"), list) and payload["suggestions"]:
		first = payload["suggestions"][0]
		sug = first.get("suggestion") if isinstance(first, dict) and isinstance(first.get("suggestion"), dict) else first
	if sug is None:
		sug = payload
	if isinstance(sug, dict):
		for k in ("suggested_width_mm", "width_mm", "applied_width_mm"):
			if sug.get(k) is not None and flt(sug.get(k)) > 0:
				return flt(sug.get(k))
	return 0.0


def _match_demand(demands: list, item_code: Optional[str], key: Optional[str], ordered_width: float):
	if not demands:
		return None
	if key:
		for d in demands:
			if str(d.get("key") or "") == str(key):
				return d
	if item_code:
		for d in demands:
			if str(d.get("item_code") or d.get("item") or "") == str(item_code):
				return d
	if ordered_width > 0:
		for d in demands:
			if abs(flt(d.get("width_mm")) - ordered_width) < 1e-6:
				return d
	return demands[0]


def _before_after_pcs(usable: float, ordered_w: float, suggested_w: float) -> dict:
	pcs_before = int(usable // ordered_w) if ordered_w > 0 and usable > 0 else 0
	pcs_after = int(usable // suggested_w) if suggested_w > 0 and usable > 0 else 0
	return {
		"pcs_before": pcs_before,
		"pcs_after": pcs_after,
		"waste_before_mm": round(usable - pcs_before * ordered_w, 4) if ordered_w > 0 else usable,
		"waste_after_mm": round(usable - pcs_after * suggested_w, 4) if suggested_w > 0 else usable,
		"delta_mm": round(ordered_w - suggested_w, 4) if ordered_w and suggested_w else None,
	}


def _update_plan_demands(plan: dict, item_code, key, ordered_w: float, suggested_w: float) -> dict:
	demands = plan.get("demands")
	if not isinstance(demands, list):
		demands = []
		plan["demands"] = demands
	target = _match_demand(demands, item_code, key, ordered_w)
	if target is None:
		target = {
			"width_mm": suggested_w,
			"qty": 1,
			"key": key or item_code or "applied",
			"item_code": item_code,
			"ordered_width_mm": ordered_w,
			"applied_undersize": True,
			"applied_width_mm": suggested_w,
		}
		demands.append(target)
	else:
		target["ordered_width_mm"] = flt(target.get("width_mm") or ordered_w)
		target["width_mm"] = suggested_w
		target["applied_undersize"] = True
		target["applied_width_mm"] = suggested_w
		if item_code:
			target["item_code"] = item_code
	plan["undersize_applied"] = {
		"marker": MARKER,
		"item_code": item_code,
		"key": key,
		"ordered_width_mm": ordered_w,
		"applied_width_mm": suggested_w,
		"at": str(now_datetime()),
		"by": getattr(getattr(frappe, "session", None), "user", None),
	}
	layout = plan.get("layout")
	if isinstance(layout, dict):
		layout["undersize_note"] = (
			f"Operator applied undersize {ordered_w}->{suggested_w} mm; "
			"re-run Create Plan to refresh shafts."
		)
	return target


def _stamp_wo_output_rows(wo, item_code, suggested_w: float, notes: list) -> None:
	outputs = getattr(wo, "outputs", None) or []
	meta_fields = set()
	try:
		meta_fields = {df.fieldname for df in frappe.get_meta("IB WO Output").fields}
	except Exception:
		meta_fields = set()
	touched = 0
	for row in outputs:
		row_item = (
			getattr(row, "item_code", None)
			or getattr(row, "item", None)
			or getattr(row, "fg_item", None)
		)
		if item_code and row_item and str(row_item) != str(item_code):
			continue
		for fname in ("custom_applied_width_mm", "applied_width_mm", "custom_suggested_width_mm"):
			if fname in meta_fields or hasattr(row, fname):
				try:
					setattr(row, fname, suggested_w)
					touched += 1
				except Exception:
					pass
		if item_code or touched:
			break
	notes.append(
		f"stamped {touched} WO output width field(s)"
		if touched
		else "WO output custom width fields absent — plan JSON only"
	)


def _stamp_item_optional(item_code: str, suggested_w: float, update_item_master: int, notes: list) -> None:
	if not cint(update_item_master):
		notes.append("Item master width unchanged (update_item_master=0)")
		return
	if not item_code or not frappe.db.exists("Item", item_code):
		notes.append("update_item_master requested but item missing")
		return
	item = frappe.get_doc("Item", item_code)
	if hasattr(item, "custom_applied_width_mm"):
		item.custom_applied_width_mm = suggested_w
		item.save(ignore_permissions=True)
		notes.append(f"Item.custom_applied_width_mm={suggested_w}")
	elif hasattr(item, "custom_suggested_width_mm"):
		item.custom_suggested_width_mm = suggested_w
		item.save(ignore_permissions=True)
		notes.append(f"Item.custom_suggested_width_mm={suggested_w}")
	else:
		notes.append(
			"Item has no custom_*_width_mm field; refusing to overwrite Item.width_mm."
		)


@frappe.whitelist()
def apply_cutting_undersize(
	work_order: str,
	suggestion_payload: Any = None,
	suggested_width_mm: Any = None,
	item_code: Optional[str] = None,
	key: Optional[str] = None,
	confirm: Any = 0,
	update_item_master: Any = 0,
	usable_width_mm: Any = None,
	ordered_width_mm: Any = None,
) -> dict:
	"""Apply undersize only when confirm=1. Soft path unchanged when confirm missing."""
	out = {
		"marker": MARKER,
		"todo": 44,
		"work_order": work_order,
		"applied": False,
		"soft": True,
		"confirm": cint(confirm),
		"before_after": None,
		"notes": [],
		"plan_field": None,
	}

	payload = _parse_payload(suggestion_payload)
	if not item_code:
		item_code = payload.get("item_code") or (payload.get("suggestion") or {}).get("item_code")
	if not key:
		key = payload.get("key") or (payload.get("suggestion") or {}).get("key")

	suggested_w = _resolve_suggested_width(payload, suggested_width_mm)
	ordered_w = flt(
		ordered_width_mm
		or payload.get("ordered_width_mm")
		or (payload.get("suggestion") or {}).get("ordered_width_mm")
		or 0
	)

	if not cint(confirm):
		out["message"] = (
			"Soft only — pass confirm=1 after operator accepts. "
			"No plan/demands were written."
		)
		if suggested_w > 0:
			out["pending_suggested_width_mm"] = suggested_w
		return out

	if not work_order or not frappe.db.exists("IB Work Order", work_order):
		frappe.throw(f"IB Work Order not found: {work_order}")
	if suggested_w <= 0:
		frappe.throw("suggested_width_mm / suggestion_payload.suggestion.suggested_width_mm required")

	frappe.has_permission("IB Work Order", "write", throw=True)
	wo = frappe.get_doc("IB Work Order", work_order)

	usable = flt(usable_width_mm or payload.get("usable_width_mm") or 0)
	mp = None
	try:
		mp = _mp()
	except Exception:
		mp = None

	if usable <= 0 and mp:
		for fn_name in (
			"resolve_jumbo_usable",
			"usable_width_for_wo",
			"get_jumbo_usable_width",
			"resolve_usable_width",
		):
			fn = getattr(mp, fn_name, None)
			if callable(fn):
				try:
					res = fn(wo)
					if isinstance(res, dict):
						usable = flt(res.get("usable_width_mm") or 0)
					else:
						usable = flt(res or 0)
					if usable > 0:
						break
				except Exception:
					pass

	if ordered_w <= 0 and mp:
		for fn_name in ("extract_wo_cut_demands", "get_wo_cut_demands", "wo_cut_demands"):
			fn = getattr(mp, fn_name, None)
			if callable(fn):
				try:
					demands = fn(wo)
					target = _match_demand(demands or [], item_code, key, 0)
					if target:
						ordered_w = flt(target.get("width_mm"))
						if not item_code:
							item_code = target.get("item_code")
						if not key:
							key = target.get("key")
					break
				except Exception:
					pass

	if ordered_w <= 0:
		ordered_w = suggested_w

	if usable > 0:
		ba = _before_after_pcs(usable, ordered_w, suggested_w)
	else:
		ba = {
			"pcs_before": None,
			"pcs_after": None,
			"waste_before_mm": None,
			"waste_after_mm": None,
			"delta_mm": round(ordered_w - suggested_w, 4),
			"note": "usable_width_mm unknown — pcs/waste not computed",
		}
	out["before_after"] = ba

	plan_field = "custom_cutting_plan_json"
	plan = _loads(getattr(wo, plan_field, None))
	if not isinstance(plan, dict):
		for f in ("custom_slitting_plan_json", "custom_rewinding_plan_json"):
			cand = _loads(getattr(wo, f, None))
			if isinstance(cand, dict) and cand.get("demands"):
				plan = cand
				plan_field = f
				break
		if not isinstance(plan, dict):
			plan = {
				"plan_type": "cutting",
				"work_order": wo.name,
				"demands": [],
				"marker": MARKER,
				"created_by_apply": True,
			}

	_update_plan_demands(plan, item_code, key, ordered_w, suggested_w)
	plan["before_after"] = ba

	wo_meta_fields = {df.fieldname for df in frappe.get_meta("IB Work Order").fields}
	if plan_field in wo_meta_fields or hasattr(wo, plan_field):
		setattr(wo, plan_field, _dumps(plan))
		out["plan_field"] = plan_field
		out["notes"].append(f"updated {plan_field}")
	else:
		audit_field = "custom_cutting_undersize_applied_json"
		if audit_field in wo_meta_fields or hasattr(wo, audit_field):
			setattr(wo, audit_field, _dumps(plan))
			out["plan_field"] = audit_field
			out["notes"].append(f"plan fields missing — wrote {audit_field}")
		else:
			out["notes"].append("WO plan JSON field missing — ensure should create it")
			try:
				frappe.db.set_value(
					"IB Work Order", wo.name, plan_field, _dumps(plan), update_modified=False
				)
				out["plan_field"] = plan_field
			except Exception as e:
				out["notes"].append(f"set_value {plan_field} failed: {e}")

	if "custom_cutting_undersize_applied_json" in wo_meta_fields:
		setattr(wo, "custom_cutting_undersize_applied_json", _dumps(plan.get("undersize_applied")))

	_stamp_wo_output_rows(wo, item_code, suggested_w, out["notes"])
	if item_code:
		_stamp_item_optional(item_code, suggested_w, update_item_master, out["notes"])

	for fname, val in (
		("custom_applied_cut_width_mm", suggested_w),
		("custom_last_undersize_applied_mm", suggested_w),
	):
		if fname in wo_meta_fields:
			setattr(wo, fname, val)

	try:
		wo.flags.ignore_permissions = True
		wo.save()
		frappe.db.commit()
	except Exception as e:
		frappe.db.rollback()
		frappe.throw(f"Failed to save WO after undersize apply: {e}")

	out["applied"] = True
	out["soft"] = False
	out["suggested_width_mm"] = suggested_w
	out["ordered_width_mm"] = ordered_w
	out["item_code"] = item_code
	out["key"] = key
	out["usable_width_mm"] = usable
	out["message"] = (
		f"Applied undersize on {wo.name}: {ordered_w} -> {suggested_w} mm"
		+ (
			f" (pcs {ba.get('pcs_before')}->{ba.get('pcs_after')}, "
			f"waste {ba.get('waste_before_mm')}->{ba.get('waste_after_mm')} mm)"
			if ba.get("pcs_before") is not None
			else ""
		)
	)
	return out


@frappe.whitelist()
def probe_todo44(work_order: str = None) -> dict:
	"""Probe soft vs apply gate. Does not auto-confirm on a live WO."""
	out = {
		"marker": MARKER,
		"todo": 44,
		"status": "ok",
		"soft_path": {},
		"apply_without_confirm": {},
		"helpers": {},
		"work_order": work_order,
	}
	try:
		mp = _mp()
		pure_fn = getattr(mp, "suggest_cutting_undersize_pure", None) or getattr(
			mp, "suggest_cutting_undersize", None
		)
		pure = pure_fn(99, 10) if pure_fn else {"suggestion": None, "applied": False, "soft": True}
		# normalize if whitelist signature differs
		if not isinstance(pure, dict):
			pure = {"raw": pure}
		out["soft_path"] = {
			"usable": 99,
			"ordered": 10,
			"has_suggestion": bool(pure.get("suggestion")),
			"applied_flag": pure.get("applied"),
			"soft": pure.get("soft", True),
			"suggested_width_mm": (pure.get("suggestion") or {}).get("suggested_width_mm")
			if isinstance(pure.get("suggestion"), dict)
			else None,
		}
		soft_call = apply_cutting_undersize(
			work_order=work_order or "__missing__",
			suggested_width_mm=9.9,
			confirm=0,
		)
		out["apply_without_confirm"] = {
			"applied": soft_call.get("applied"),
			"soft": soft_call.get("soft"),
			"message": soft_call.get("message"),
		}
		out["helpers"]["apply_cutting_undersize"] = True
		out["helpers"]["suggest_cutting_undersize"] = True
	except Exception as e:
		out["status"] = "error"
		out["error"] = str(e)

	if work_order and frappe.db.exists("IB Work Order", work_order):
		try:
			sug_fn = getattr(_mp(), "suggest_cutting_undersize", None)
			if sug_fn:
				sug = sug_fn(work_order=work_order)
				out["wo_suggestion"] = {
					"message": sug.get("message") if isinstance(sug, dict) else None,
					"suggestion": sug.get("suggestion") if isinstance(sug, dict) else sug,
					"applied": sug.get("applied") if isinstance(sug, dict) else False,
				}
		except Exception as e:
			out["wo_suggestion_error"] = str(e)

	return out


def ensure_todo44_fields() -> dict:
	result = {"fields": [], "notes": []}
	if not frappe.db.exists("DocType", "IB Work Order"):
		result["notes"].append("IB Work Order missing")
		return result
	try:
		from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
	except Exception as e:
		result["notes"].append(str(e))
		return result

	wo_fields = [
		{
			"fieldname": "custom_cutting_undersize_applied_json",
			"label": "Cutting Undersize Applied JSON",
			"fieldtype": "Long Text",
			"read_only": 1,
			"description": f"Todo44 audit payload. Marker={MARKER}",
			"insert_after": "notes",
		},
		{
			"fieldname": "custom_last_undersize_applied_mm",
			"label": "Last Undersize Applied (mm)",
			"fieldtype": "Float",
			"read_only": 1,
			"insert_after": "custom_cutting_undersize_applied_json",
		},
	]
	targets = {"IB Work Order": wo_fields}
	if frappe.db.exists("DocType", "IB WO Output"):
		targets["IB WO Output"] = [
			{
				"fieldname": "custom_applied_width_mm",
				"label": "Applied Cut Width (mm)",
				"fieldtype": "Float",
				"description": "Set when operator confirms cutting undersize (todo44).",
			},
			{
				"fieldname": "custom_suggested_width_mm",
				"label": "Suggested Cut Width (mm)",
				"fieldtype": "Float",
				"read_only": 1,
			},
		]
	create_custom_fields(targets, update=True)
	for dt, fields in targets.items():
		for f in fields:
			result["fields"].append(f"{dt}.{f['fieldname']}")
	return result


# Package brief alias
