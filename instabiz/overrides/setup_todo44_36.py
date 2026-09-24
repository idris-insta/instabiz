# Copyright (c) 2026, Instabiz
# License: MIT
"""Ensure custom fields + Client Scripts for todo44/36."""
from __future__ import annotations

import frappe

MARKER = "todo44_36_setup"


def ensure_todo44_36_setup() -> dict:
	out = {"marker": MARKER, "fields": {}, "client_scripts": [], "notes": []}
	try:
		from instabiz.overrides.cutting_undersize import ensure_todo44_fields
		out["fields"]["todo44"] = ensure_todo44_fields()
	except Exception as e:
		out["notes"].append(f"todo44 fields: {e}")
	try:
		from instabiz.overrides.mfg_serials import ensure_todo36_fields
		out["fields"]["todo36"] = ensure_todo36_fields()
	except Exception as e:
		out["notes"].append(f"todo36 fields: {e}")

	# Ensure cutting plan JSON field exists (todo38 may already have it)
	try:
		from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
		if frappe.db.exists("DocType", "IB Work Order"):
			create_custom_fields(
				{
					"IB Work Order": [
						{
							"fieldname": "custom_cutting_plan_json",
							"label": "Cutting Plan JSON",
							"fieldtype": "Long Text",
							"read_only": 1,
							"insert_after": "notes",
						}
					]
				},
				update=True,
			)
			out["fields"]["cutting_plan"] = ["IB Work Order.custom_cutting_plan_json"]
	except Exception as e:
		out["notes"].append(f"cutting plan field: {e}")

	out["client_scripts"].append(_ensure_client_script_wo())
	out["client_scripts"].append(_ensure_client_script_batch())
	frappe.db.commit()
	return out


def _read_js(name: str) -> str:
	import os
	candidates = [
		os.path.join(frappe.get_app_path("instabiz"), "public", "js", name),
		os.path.join(frappe.get_app_path("instabiz"), "overrides", name),
	]
	for p in candidates:
		if os.path.exists(p):
			with open(p, "r", encoding="utf-8") as f:
				return f.read()
	# fallback embedded minimal
	return ""


def _ensure_client_script_wo() -> str:
	cs_name = "IB Work Order — Todo44/36 Undersize + Serials"
	js = _read_js("ib_work_order_mfg_plans.js")
	if not js:
		js = "/* missing ib_work_order_mfg_plans.js */\n"
	if frappe.db.exists("Client Script", cs_name):
		doc = frappe.get_doc("Client Script", cs_name)
		doc.script = js
		doc.enabled = 1
		doc.save(ignore_permissions=True)
		return f"updated:{cs_name}"
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
	return f"created:{cs_name}"


def _ensure_client_script_batch() -> str:
	cs_name = "IB Batch — Todo36 Jumbo/Carton Serials"
	js = _read_js("ib_batch_mfg_serials.js")
	if not js:
		return "skipped:no js"
	if not frappe.db.exists("DocType", "IB Batch"):
		return "skipped:no IB Batch"
	if frappe.db.exists("Client Script", cs_name):
		doc = frappe.get_doc("Client Script", cs_name)
		doc.script = js
		doc.enabled = 1
		doc.save(ignore_permissions=True)
		return f"updated:{cs_name}"
	doc = frappe.get_doc(
		{
			"doctype": "Client Script",
			"name": cs_name,
			"dt": "IB Batch",
			"view": "Form",
			"enabled": 1,
			"script": js,
		}
	)
	doc.insert(ignore_permissions=True)
	return f"created:{cs_name}"


def after_migrate():
	try:
		ensure_todo44_36_setup()
	except Exception:
		frappe.log_error(title="todo44_36 ensure failed")

def smoke_todo44_36(wo='IB-WO-2026-29510'):
	import json, frappe
	from instabiz.overrides.cutting_undersize import apply_cutting_undersize
	from instabiz.overrides.mfg_plans import suggest_cutting_undersize, create_plan_from_wo
	from instabiz.overrides.mfg_serials import (
		allocate_jumbo_serials_to_wo, create_carton_serials_for_output, list_trace_chain, make_carton_serial
	)
	out = {'wo': wo}
	# Ensure cutting plan exists
	try:
		create_plan_from_wo(wo, 'cutting')
	except Exception as e:
		out['plan_err'] = str(e)[:200]
	sug = suggest_cutting_undersize(work_order=wo)
	out['suggest'] = {
		'soft': (sug or {}).get('soft'),
		'message': (sug or {}).get('message'),
		'suggestion': (sug or {}).get('suggestion') or (sug or {}).get('suggestions'),
	}
	# Build apply payload from first suggestion if any
	payload = sug
	applied = apply_cutting_undersize(work_order=wo, suggestion_payload=json.dumps(payload) if not isinstance(payload, str) else payload, confirm=1)
	out['apply'] = {
		'applied': (applied or {}).get('applied'),
		'message': (applied or {}).get('message'),
		'before_after': (applied or {}).get('before_after') or (applied or {}).get('pcs'),
		'suggested_width_mm': (applied or {}).get('suggested_width_mm'),
	}
	# Carton serial helper
	out['carton'] = make_carton_serial(work_order=wo, item_code='TEST-ITEM', box_no=1)
	# Trace missing serial should be soft
	try:
		out['trace_missing'] = list_trace_chain('NO-SUCH-SERIAL')
	except Exception as e:
		out['trace_missing'] = {'error': str(e)[:160]}
	# Multi-jumbo allocate with empty / noop if no batches ? find one Active RM batch
	batches = frappe.get_all('IB Batch', filters={'status': 'Active'}, fields=['name','item'], limit=2)
	out['batches_found'] = batches
	if batches:
		rows = [{'batch': b.name, 'qty_taken': 1} for b in batches]
		out['allocate'] = allocate_jumbo_serials_to_wo(work_order=wo, jumbo_rows=json.dumps(rows))
	return out

def smoke_todo44_36_v2(wo="IB-WO-2026-29510"):
	import json, frappe
	from instabiz.overrides.cutting_undersize import apply_cutting_undersize
	from instabiz.overrides.mfg_plans import create_plan_from_wo, suggest_cutting_undersize_pure
	from instabiz.overrides.mfg_serials import (
		allocate_jumbo_serials_to_wo, create_carton_serials_for_output, list_trace_chain, make_carton_serial
	)
	out = {"wo": wo}
	try:
		create_plan_from_wo(wo, "cutting")
	except Exception as e:
		out["plan_err"] = str(e)[:160]
	pure = suggest_cutting_undersize_pure(99, 10)
	out["pure"] = pure
	applied = apply_cutting_undersize(
		work_order=wo,
		suggested_width_mm=9.9,
		item_code="IS-55224V-160GYHBNL",
		confirm=1,
		update_item_master=0,
	)
	out["apply"] = {
		"applied": applied.get("applied") if isinstance(applied, dict) else None,
		"message": (applied or {}).get("message"),
		"before_after": (applied or {}).get("before_after") or (applied or {}).get("pcs"),
		"suggested_width_mm": (applied or {}).get("suggested_width_mm"),
	}
	# refuse without confirm
	soft = apply_cutting_undersize(work_order=wo, suggested_width_mm=9.8, confirm=0)
	out["soft_block"] = {"applied": soft.get("applied"), "soft": soft.get("soft")}
	out["carton"] = make_carton_serial(work_order=wo, item_code="IS-55224V-160GYHBNL", box_no=1)
	batches = frappe.get_all("IB Batch", filters={"status": "Active"}, fields=["name", "item"], limit=2)
	out["batches"] = batches
	if batches:
		rows = [{"batch": b.name, "qty_taken": 1} for b in batches]
		out["allocate"] = allocate_jumbo_serials_to_wo(work_order=wo, jumbo_rows=json.dumps(rows))
		# generate 2 carton serials
		try:
			out["cartons"] = create_carton_serials_for_output(
				work_order=wo, item_code="IS-55224V-160GYHBNL", qty_or_boxes=2
			)
		except Exception as e:
			out["cartons_err"] = str(e)[:200]
		# trace first carton if created
		sns = []
		if isinstance(out.get("cartons"), dict):
			sns = out["cartons"].get("serials") or out["cartons"].get("names") or []
		if sns:
			first = sns[0] if isinstance(sns[0], str) else (sns[0].get("name") if isinstance(sns[0], dict) else None)
			if first:
				out["trace"] = list_trace_chain(first)
	return out

def smoke_todo44_36_v3(wo="IB-WO-2026-29510"):
	import json, frappe
	from instabiz.overrides.cutting_undersize import apply_cutting_undersize
	from instabiz.overrides.mfg_plans import create_plan_from_wo, suggest_cutting_undersize_pure
	from instabiz.overrides.mfg_serials import (
		allocate_jumbo_serials_to_wo, create_carton_serials_for_output, list_trace_chain, make_carton_serial
	)
	out = {"wo": wo}
	try:
		create_plan_from_wo(wo, "cutting")
	except Exception as e:
		out["plan_err"] = str(e)[:160]
	out["pure"] = suggest_cutting_undersize_pure(99, 10)
	applied = apply_cutting_undersize(
		work_order=wo, suggested_width_mm=9.9, item_code="IS-55224V-160GYHBNL", confirm=1, update_item_master=0
	)
	out["apply"] = {
		"applied": (applied or {}).get("applied"),
		"message": (applied or {}).get("message"),
		"before_after": (applied or {}).get("before_after") or (applied or {}).get("pcs"),
		"suggested_width_mm": (applied or {}).get("suggested_width_mm"),
	}
	soft = apply_cutting_undersize(work_order=wo, suggested_width_mm=9.8, confirm=0)
	out["soft_block"] = {"applied": soft.get("applied"), "soft": soft.get("soft")}
	out["carton_helper"] = make_carton_serial(work_order=wo, item_code="IS-55224V-160GYHBNL", box_no=1)
	batches = frappe.get_all("IB Batch", filters={"status": "Active"}, fields=["name", "item"], limit=2)
	out["batches"] = batches
	if batches:
		rows = [{"batch": b.name, "qty_taken": 1} for b in batches]
		out["allocate"] = allocate_jumbo_serials_to_wo(work_order=wo, source_batches=json.dumps(rows), replace=1)
		try:
			out["cartons"] = create_carton_serials_for_output(
				work_order=wo, item_code="IS-55224V-160GYHBNL", qty_or_boxes=2
			)
		except Exception as e:
			out["cartons_err"] = str(e)[:240]
		sns = []
		if isinstance(out.get("cartons"), dict):
			sns = out["cartons"].get("serials") or out["cartons"].get("names") or out["cartons"].get("created") or []
		if sns:
			first = sns[0] if isinstance(sns[0], str) else (sns[0].get("name") if isinstance(sns[0], dict) else None)
			if first:
				out["trace"] = list_trace_chain(first)
	# Read back WO fields
	wo_doc = frappe.get_doc("IB Work Order", wo)
	out["wo_fields"] = {
		"undersize_json_set": bool(wo_doc.get("custom_cutting_undersize_applied_json")),
		"last_undersize": wo_doc.get("custom_last_undersize_applied_mm"),
		"jumbo_json_set": bool(wo_doc.get("custom_jumbo_serials_json")),
		"carton_json_set": bool(wo_doc.get("custom_carton_serials_json")),
		"source_batch": wo_doc.get("source_batch"),
	}
	return out

def smoke_carton_and_reset(wo="IB-WO-2026-29510"):
	import frappe
	from instabiz.overrides.mfg_plans import create_plan_from_wo
	from instabiz.overrides.mfg_serials import create_carton_serials_for_output, list_trace_chain
	# Rebuild cutting plan so demands go back to OS widths (clears bad 9.9 smoke write in plan demands)
	plan = create_plan_from_wo(wo, "cutting")
	cartons = create_carton_serials_for_output(work_order=wo, item_code="IS-55224V-160GYHBNL", boxes=2)
	trace = None
	created = []
	if isinstance(cartons, dict):
		created = cartons.get("serials") or cartons.get("created") or cartons.get("names") or []
	if created:
		first = created[0] if isinstance(created[0], str) else created[0].get("name")
		if first:
			trace = list_trace_chain(first)
	wo_doc = frappe.get_doc("IB Work Order", wo)
	return {
		"plan_summary": (plan.get("summary") if isinstance(plan, dict) else None) or str(plan)[:200],
		"demands": ((plan.get("plans") or [plan])[0].get("demands") if isinstance(plan, dict) else None),
		"cartons": cartons,
		"trace": trace,
		"carton_json_set": bool(wo_doc.get("custom_carton_serials_json")),
		"jumbo_count": len((frappe.parse_json(wo_doc.custom_jumbo_serials_json) or {}).get("jumbos") or []) if wo_doc.get("custom_jumbo_serials_json") else 0,
	}
