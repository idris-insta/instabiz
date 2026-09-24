# Copyright (c) 2026, Instabiz and contributors
# License: MIT
"""
Todo 36 — Jumbo + carton serials, multi-jumbo consumption.

Already live (do not break):
- IB FG Serial / IB Batch doctypes
- manufacturing_rules.make_carton_serial / next_carton_serial
- production_run FG serial creation (single source_batch)
- coating jumbo label button on IB Batch

Extensions (optional, backward compatible):
- allocate_jumbo_serials_to_wo
- create_carton_serials_for_output
- list_trace_chain
- make_carton_serial (wrapper)
"""
from __future__ import annotations

import json
from typing import Any, Optional

import frappe
from frappe.utils import add_months, cint, flt, getdate, now_datetime

MARKER = "todo36_mfg_serials"
RETENTION_MONTHS = 6


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


def _parse_list(raw: Any) -> list:
	if raw is None or raw == "":
		return []
	if isinstance(raw, list):
		return raw
	if isinstance(raw, dict):
		return [raw]
	if isinstance(raw, str):
		parsed = _loads(raw)
		if isinstance(parsed, list):
			return parsed
		if isinstance(parsed, dict):
			return [parsed]
		parts = [p.strip() for p in raw.replace("\n", ",").split(",") if p.strip()]
		return [{"batch": p, "qty_taken": 0} for p in parts]
	return []


def _normalize_jumbo_row(row: Any) -> dict:
	if isinstance(row, str):
		return {"batch": row, "serial": row, "qty_taken": 0}
	if not isinstance(row, dict):
		return {"batch": str(row), "qty_taken": 0}
	batch = (
		row.get("batch")
		or row.get("source_batch")
		or row.get("jumbo_serial")
		or row.get("serial")
		or row.get("name")
		or row.get("ib_batch")
	)
	return {
		"batch": batch,
		"serial": row.get("serial") or row.get("jumbo_serial") or batch,
		"qty_taken": flt(row.get("qty_taken") or row.get("qty") or row.get("qty_consumed") or 0),
		"item_code": row.get("item_code") or row.get("item"),
		"warehouse": row.get("warehouse") or row.get("source_warehouse"),
		"notes": row.get("notes"),
	}


def _fg_serial_doctype() -> Optional[str]:
	for dt in ("IB FG Serial", "IB FG Serial No"):
		if frappe.db.exists("DocType", dt):
			return dt
	return None


def _batch_doctype() -> Optional[str]:
	if frappe.db.exists("DocType", "IB Batch"):
		return "IB Batch"
	return None


def _fieldmap_fg(meta) -> dict:
	names = {df.fieldname for df in meta.fields}

	def pick(*cands, default=None):
		for c in cands:
			if c in names:
				return c
		return default

	return {
		"serial_no": pick("serial_no", "name"),
		"item_code": pick("item_code", "item"),
		"item_name": pick("item_name"),
		"status": pick("status"),
		"fg_batch": pick("fg_batch", "fg_batch_id"),
		"source_batch": pick("source_batch", "rm_batch"),
		"produced_on": pick("produced_on", "posting_date", "creation"),
		"box_no": pick("box_no", "carton_no", "box"),
		"work_order": pick("work_order", "ib_work_order"),
		"order_sheet": pick("order_sheet", "ib_order_sheet"),
		"sales_order": pick("sales_order"),
		"width_mm": pick("width_mm", "width"),
		"length_mtr": pick("length_mtr", "length"),
		"delivery_note": pick("delivery_note"),
		"customer": pick("customer"),
		"source_batches_json": pick("custom_source_batches_json", "source_batches_json"),
	}


def _mr_make_carton_serial(*args, **kwargs):
	try:
		from instabiz.overrides import manufacturing_rules as mr
	except Exception:
		mr = None
	if mr:
		for name in ("make_carton_serial", "next_carton_serial"):
			fn = getattr(mr, name, None)
			if callable(fn):
				try:
					return fn(*args, **kwargs)
				except TypeError:
					try:
						return fn()
					except Exception:
						pass
				except Exception:
					pass
	try:
		from instabiz.overrides import carton_serial as cs
		for name in ("make_carton_serial", "next_carton_serial", "get_next"):
			fn = getattr(cs, name, None)
			if callable(fn):
				try:
					return fn(*args, **kwargs)
				except TypeError:
					return fn()
	except Exception:
		pass
	return frappe.model.naming.make_autoname("IB-CTN-.YYYY.-.#####")


@frappe.whitelist()
def make_carton_serial(work_order: str = None, item_code: str = None, box_no: Any = None, **kwargs) -> dict:
	serial = _mr_make_carton_serial(
		work_order=work_order, item_code=item_code, box_no=box_no, **kwargs
	)
	if isinstance(serial, dict):
		return {"marker": MARKER, **serial}
	return {
		"marker": MARKER,
		"carton_serial": serial,
		"work_order": work_order,
		"item_code": item_code,
		"box_no": box_no,
	}


@frappe.whitelist()
def allocate_jumbo_serials_to_wo(
	work_order: str,
	source_batches: Any = None,
	replace: Any = 0,
) -> dict:
	"""Register one or many jumbo (RM) serials/batches on a WO."""
	if not work_order or not frappe.db.exists("IB Work Order", work_order):
		frappe.throw(f"IB Work Order not found: {work_order}")
	frappe.has_permission("IB Work Order", "write", throw=True)

	rows = [_normalize_jumbo_row(r) for r in _parse_list(source_batches)]
	rows = [r for r in rows if r.get("batch")]
	if not rows:
		frappe.throw("source_batches required (list of batch/serial + qty_taken)")

	wo = frappe.get_doc("IB Work Order", work_order)
	meta_fields = {df.fieldname for df in frappe.get_meta("IB Work Order").fields}

	existing = []
	if not cint(replace):
		existing = _parse_list(getattr(wo, "custom_jumbo_serials_json", None))
		existing = [_normalize_jumbo_row(r) for r in existing if r]
		# also accept nested payload.jumbos
		if len(existing) == 1 and isinstance(existing[0], dict) and existing[0].get("jumbos"):
			existing = [_normalize_jumbo_row(r) for r in existing[0]["jumbos"]]
		prev = _loads(getattr(wo, "custom_jumbo_serials_json", None))
		if isinstance(prev, dict) and prev.get("jumbos"):
			existing = [_normalize_jumbo_row(r) for r in prev["jumbos"]]

	by_key = {str(r.get("batch")): r for r in existing if r.get("batch")}
	for r in rows:
		k = str(r["batch"])
		if k in by_key and not cint(replace):
			by_key[k]["qty_taken"] = flt(by_key[k].get("qty_taken")) + flt(r.get("qty_taken"))
			by_key[k].update({kk: vv for kk, vv in r.items() if vv and kk != "qty_taken"})
		else:
			by_key[k] = r
	merged = list(by_key.values())

	payload = {
		"marker": MARKER,
		"work_order": wo.name,
		"sales_order": getattr(wo, "sales_order", None),
		"order_sheet": getattr(wo, "order_sheet", None),
		"jumbos": merged,
		"updated_at": str(now_datetime()),
		"updated_by": getattr(getattr(frappe, "session", None), "user", None),
		"mixed_jumbos_allowed": True,
	}

	if "custom_jumbo_serials_json" in meta_fields or hasattr(wo, "custom_jumbo_serials_json"):
		wo.custom_jumbo_serials_json = _dumps(payload)
	else:
		frappe.db.set_value(
			"IB Work Order",
			wo.name,
			"custom_jumbo_serials_json",
			_dumps(payload),
			update_modified=False,
		)

	first = merged[0]
	if "source_batch" in meta_fields:
		wo.source_batch = first.get("batch")
	if first.get("item_code") and "source_item" in meta_fields:
		wo.source_item = first["item_code"]
	total_qty = sum(flt(r.get("qty_taken")) for r in merged)
	if total_qty and "source_qty" in meta_fields:
		wo.source_qty = total_qty
	if first.get("warehouse") and "source_warehouse" in meta_fields:
		wo.source_warehouse = first["warehouse"]

	wo.flags.ignore_permissions = True
	wo.save()
	frappe.db.commit()

	return {
		"marker": MARKER,
		"todo": 36,
		"work_order": wo.name,
		"jumbos": merged,
		"count": len(merged),
		"primary_source_batch": first.get("batch"),
		"message": f"Allocated {len(merged)} jumbo serial(s) to {wo.name}",
	}


@frappe.whitelist()
def create_carton_serials_for_output(
	work_order: str,
	qty: Any = None,
	boxes: Any = None,
	item_code: str = None,
	source_batch: str = None,
	length_mtr: Any = None,
	width_mm: Any = None,
) -> dict:
	"""Create multiple IB FG Serial (carton) rows for WO output."""
	if not work_order or not frappe.db.exists("IB Work Order", work_order):
		frappe.throw(f"IB Work Order not found: {work_order}")
	frappe.has_permission("IB Work Order", "write", throw=True)

	fg_dt = _fg_serial_doctype()
	if not fg_dt:
		frappe.throw("IB FG Serial DocType not found")

	n = cint(boxes) if boxes is not None else cint(qty)
	if n <= 0:
		frappe.throw("boxes or qty must be > 0")
	if n > 500:
		frappe.throw("Refusing to create >500 carton serials in one call")

	wo = frappe.get_doc("IB Work Order", work_order)
	meta = frappe.get_meta(fg_dt)
	fmap = _fieldmap_fg(meta)
	fieldnames = {df.fieldname for df in meta.fields}

	if not item_code:
		outputs = getattr(wo, "outputs", None) or []
		if outputs:
			item_code = (
				getattr(outputs[0], "item_code", None)
				or getattr(outputs[0], "item", None)
				or getattr(outputs[0], "fg_item", None)
			)
			if width_mm is None:
				width_mm = getattr(outputs[0], "width_mm", None)
			if length_mtr is None:
				length_mtr = getattr(outputs[0], "length_mtr", None)

	jumbo_payload = _loads(getattr(wo, "custom_jumbo_serials_json", None)) or {}
	jumbos = jumbo_payload.get("jumbos") if isinstance(jumbo_payload, dict) else None
	primary_source = source_batch or getattr(wo, "source_batch", None)
	if not primary_source and jumbos:
		primary_source = (jumbos[0] or {}).get("batch")

	fg_batch = getattr(wo, "fg_batch", None)

	def setf(doc, logical, value):
		fname = fmap.get(logical)
		if not fname or value is None:
			return
		if fname in fieldnames or hasattr(doc, fname):
			try:
				setattr(doc, fname, value)
			except Exception:
				pass

	created = []
	errors = []
	for i in range(1, n + 1):
		try:
			serial = _mr_make_carton_serial(work_order=wo.name, item_code=item_code, box_no=i)
			if isinstance(serial, dict):
				serial_no = serial.get("carton_serial") or serial.get("serial") or serial.get("name")
			else:
				serial_no = serial
			if not serial_no:
				serial_no = frappe.model.naming.make_autoname("IB-CTN-.YYYY.-.#####")

			doc = frappe.new_doc(fg_dt)
			if fmap.get("serial_no") and fmap["serial_no"] != "name":
				setf(doc, "serial_no", serial_no)
			else:
				doc.name = serial_no
				if "serial_no" in fieldnames:
					doc.serial_no = serial_no

			setf(doc, "item_code", item_code)
			if item_code and fmap.get("item_name"):
				try:
					setf(doc, "item_name", frappe.db.get_value("Item", item_code, "item_name"))
				except Exception:
					pass

			if fmap.get("status"):
				opts = ""
				for df in meta.fields:
					if df.fieldname == fmap["status"]:
						opts = df.options or ""
						break
				status_val = "In Stock"
				for candidate in ("In Stock", "In Stock", "Active"):
					if candidate in opts:
						status_val = candidate
						break
				setf(doc, "status", status_val)

			setf(doc, "fg_batch", fg_batch)
			setf(doc, "source_batch", primary_source)
			setf(doc, "produced_on", now_datetime())
			setf(doc, "box_no", i)
			setf(doc, "work_order", wo.name)
			setf(doc, "order_sheet", getattr(wo, "order_sheet", None))
			setf(doc, "sales_order", getattr(wo, "sales_order", None))
			setf(doc, "width_mm", flt(width_mm) if width_mm is not None else None)
			setf(doc, "length_mtr", flt(length_mtr) if length_mtr is not None else None)
			if fmap.get("source_batches_json") and jumbos:
				setattr(doc, fmap["source_batches_json"], _dumps(jumbos))

			doc.insert(ignore_permissions=True)
			created.append({"name": doc.name, "serial_no": serial_no, "box_no": i})
		except Exception as e:
			errors.append({"box_no": i, "error": str(e)})

	meta_fields = {df.fieldname for df in frappe.get_meta("IB Work Order").fields}
	carton_payload = {
		"marker": MARKER,
		"work_order": wo.name,
		"sales_order": getattr(wo, "sales_order", None),
		"order_sheet": getattr(wo, "order_sheet", None),
		"cartons": created,
		"count": len(created),
		"updated_at": str(now_datetime()),
	}
	if "custom_carton_serials_json" in meta_fields or hasattr(wo, "custom_carton_serials_json"):
		prev = _loads(getattr(wo, "custom_carton_serials_json", None)) or {}
		prev_cartons = prev.get("cartons") if isinstance(prev, dict) else []
		if not isinstance(prev_cartons, list):
			prev_cartons = []
		carton_payload["cartons"] = prev_cartons + created
		carton_payload["count"] = len(carton_payload["cartons"])
		wo.custom_carton_serials_json = _dumps(carton_payload)
		wo.flags.ignore_permissions = True
		wo.save()

	frappe.db.commit()
	return {
		"marker": MARKER,
		"todo": 36,
		"work_order": wo.name,
		"created": created,
		"errors": errors,
		"count": len(created),
		"fg_doctype": fg_dt,
		"message": f"Created {len(created)} carton serial(s) for {wo.name}",
	}


@frappe.whitelist()
def list_trace_chain(serial_or_carton: str) -> dict:
	"""Trace carton/FG serial -> WO -> OS/SO -> jumbo source batch(es)."""
	out = {
		"marker": MARKER,
		"todo": 36,
		"query": serial_or_carton,
		"fg_serial": None,
		"work_order": None,
		"order_sheet": None,
		"sales_order": None,
		"jumbos": [],
		"cartons_on_wo": [],
		"retention_months": RETENTION_MONTHS,
		"notes": [],
	}
	if not serial_or_carton:
		out["notes"].append("empty query")
		return out

	fg_dt = _fg_serial_doctype()
	fg = None
	if fg_dt and frappe.db.exists(fg_dt, serial_or_carton):
		fg = frappe.get_doc(fg_dt, serial_or_carton)
	elif fg_dt:
		name = frappe.db.get_value(fg_dt, {"serial_no": serial_or_carton}, "name")
		if name:
			fg = frappe.get_doc(fg_dt, name)

	if fg:
		fmap = _fieldmap_fg(frappe.get_meta(fg_dt))

		def g(logical):
			fname = fmap.get(logical)
			return getattr(fg, fname, None) if fname else None

		out["fg_serial"] = {
			"doctype": fg_dt,
			"name": fg.name,
			"serial_no": g("serial_no") or fg.name,
			"item_code": g("item_code"),
			"status": g("status"),
			"box_no": g("box_no"),
			"source_batch": g("source_batch"),
			"fg_batch": g("fg_batch"),
			"work_order": g("work_order"),
			"order_sheet": g("order_sheet"),
			"sales_order": g("sales_order"),
			"delivery_note": g("delivery_note"),
			"produced_on": str(g("produced_on") or ""),
		}
		produced = g("produced_on")
		if produced:
			try:
				cutoff = add_months(getdate(), -RETENTION_MONTHS)
				out["within_retention"] = getdate(produced) >= cutoff
			except Exception:
				out["within_retention"] = None

		wo_name = g("work_order")
		if wo_name and frappe.db.exists("IB Work Order", wo_name):
			wo = frappe.get_doc("IB Work Order", wo_name)
			out["work_order"] = {
				"name": wo.name,
				"sales_order": getattr(wo, "sales_order", None),
				"order_sheet": getattr(wo, "order_sheet", None),
				"source_batch": getattr(wo, "source_batch", None),
				"fg_batch": getattr(wo, "fg_batch", None),
				"status": getattr(wo, "status", None),
			}
			out["order_sheet"] = getattr(wo, "order_sheet", None)
			out["sales_order"] = getattr(wo, "sales_order", None)
			jp = _loads(getattr(wo, "custom_jumbo_serials_json", None)) or {}
			out["jumbos"] = jp.get("jumbos") if isinstance(jp, dict) else []
			if not out["jumbos"] and getattr(wo, "source_batch", None):
				out["jumbos"] = [{"batch": wo.source_batch, "qty_taken": getattr(wo, "source_qty", None)}]
			cp = _loads(getattr(wo, "custom_carton_serials_json", None)) or {}
			out["cartons_on_wo"] = cp.get("cartons") if isinstance(cp, dict) else []
		else:
			out["order_sheet"] = g("order_sheet")
			out["sales_order"] = g("sales_order")
			if g("source_batch"):
				out["jumbos"] = [{"batch": g("source_batch")}]
	else:
		if frappe.db.exists("IB Work Order", serial_or_carton):
			wo = frappe.get_doc("IB Work Order", serial_or_carton)
			out["work_order"] = {
				"name": wo.name,
				"sales_order": wo.get("sales_order"),
				"order_sheet": wo.get("order_sheet"),
			}
			jp = _loads(getattr(wo, "custom_jumbo_serials_json", None)) or {}
			out["jumbos"] = jp.get("jumbos") if isinstance(jp, dict) else []
			cp = _loads(getattr(wo, "custom_carton_serials_json", None)) or {}
			out["cartons_on_wo"] = cp.get("cartons") if isinstance(cp, dict) else []
			out["notes"].append("resolved as IB Work Order")
		elif _batch_doctype() and frappe.db.exists("IB Batch", serial_or_carton):
			out["jumbos"] = [{"batch": serial_or_carton}]
			fg_dt2 = _fg_serial_doctype()
			if fg_dt2:
				rows = frappe.get_all(
					fg_dt2,
					filters={"source_batch": serial_or_carton},
					fields=["name", "serial_no", "work_order", "sales_order", "box_no"],
					limit=50,
				)
				out["cartons_on_wo"] = rows
			out["notes"].append("resolved as IB Batch (jumbo)")
		else:
			out["notes"].append("not found as FG Serial / WO / IB Batch")

	out["locked_rules"] = {
		"mixed_jumbos_per_carton_allowed": True,
		"trace_links": ["carton_serial", "jumbo_serial", "OS/WO", "container"],
		"coating_jumbos_need_labels_serials": True,
		"retain_months": RETENTION_MONTHS,
		"labels_editable": True,
	}
	return out


@frappe.whitelist()
def probe_todo36(work_order: str = None) -> dict:
	"""Audit + dry helpers. Does not claim live Windows success."""
	out = {
		"marker": MARKER,
		"todo": 36,
		"status": "ok",
		"doctypes": {},
		"helpers": {},
		"audit": {},
		"work_order": work_order,
	}
	out["doctypes"]["IB FG Serial"] = bool(_fg_serial_doctype())
	out["doctypes"]["IB Batch"] = bool(_batch_doctype())
	out["doctypes"]["IB Work Order"] = bool(frappe.db.exists("DocType", "IB Work Order"))

	try:
		from instabiz.overrides import manufacturing_rules as mr
		out["helpers"]["make_carton_serial"] = callable(getattr(mr, "make_carton_serial", None))
		out["helpers"]["next_carton_serial"] = callable(getattr(mr, "next_carton_serial", None))
		out["helpers"]["print_coating_jumbo_label"] = callable(
			getattr(mr, "print_coating_jumbo_label", None)
		)
	except Exception as e:
		out["helpers"]["manufacturing_rules_error"] = str(e)

	out["helpers"]["allocate_jumbo_serials_to_wo"] = True
	out["helpers"]["create_carton_serials_for_output"] = True
	out["helpers"]["list_trace_chain"] = True
	out["helpers"]["make_carton_serial_wrapper"] = True

	try:
		sample = _mr_make_carton_serial(work_order=work_order or "PROBE", item_code=None, box_no=1)
		out["audit"]["sample_carton_serial"] = sample
	except Exception as e:
		out["audit"]["sample_carton_serial_error"] = str(e)

	if work_order and frappe.db.exists("IB Work Order", work_order):
		wo = frappe.get_doc("IB Work Order", work_order)
		out["audit"]["wo_source_batch"] = getattr(wo, "source_batch", None)
		out["audit"]["wo_has_jumbo_json"] = bool(getattr(wo, "custom_jumbo_serials_json", None))
		out["audit"]["wo_has_carton_json"] = bool(getattr(wo, "custom_carton_serials_json", None))
		jp = _loads(getattr(wo, "custom_jumbo_serials_json", None))
		out["audit"]["jumbo_count"] = len((jp or {}).get("jumbos") or []) if isinstance(jp, dict) else 0

	out["gaps"] = {
		"single_batch_create_run": "kept — allocate_jumbo_serials_to_wo is optional extension",
		"container_link": "trace includes OS/WO/SO; container/DN via FG serial.delivery_note when set",
		"label_edit": "coating jumbo Print Format exists; label content edit is Print Format / Client Script",
	}
	return out


def ensure_todo36_fields() -> dict:
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
			"fieldname": "custom_jumbo_serials_json",
			"label": "Jumbo Serials JSON",
			"fieldtype": "Long Text",
			"description": f"Todo36 multi-jumbo allocation. Marker={MARKER}",
			"insert_after": "source_batch",
		},
		{
			"fieldname": "custom_carton_serials_json",
			"label": "Carton Serials JSON",
			"fieldtype": "Long Text",
			"description": f"Todo36 carton/FG serials produced. Marker={MARKER}",
			"insert_after": "custom_jumbo_serials_json",
		},
	]
	targets = {"IB Work Order": wo_fields}
	fg_dt = _fg_serial_doctype()
	if fg_dt:
		targets[fg_dt] = [
			{
				"fieldname": "custom_source_batches_json",
				"label": "Source Batches JSON (multi-jumbo)",
				"fieldtype": "Long Text",
				"description": "Mixed jumbos per carton allowed (todo36).",
			}
		]
	create_custom_fields(targets, update=True)
	for dt, fields in targets.items():
		for f in fields:
			result["fields"].append(f"{dt}.{f['fieldname']}")
	return result
