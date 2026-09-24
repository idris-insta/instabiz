# Copyright (c) 2026, Instabiz Solutions India Pvt Ltd
# License: MIT
"""
Todo 52 — Traceability / Gate locks (Idris 2026-09-23).

Locked decisions:
  (a) Mixed jumbo carton label shows ALL jumbo serials (not primary only).
  (b) 6-month retention = report filter + within_retention in list_trace_chain;
      NO auto-delete job.
  (c) vehicle number compulsory on Delivery Note, IB Gate Pass, Sales Invoice.
      container_no optional (never required).
  (d) Import / Container / Carton labels = editable Print Formats.
  (e) Outbound carton scan checklist = soft warn only — NEVER hard-block
      DN / Gate Pass submit.

Hooks (injected by apply_todo52_patches.py):
  Delivery Note:
    validate       -> validate_delivery_note
    before_submit  -> enforce_vehicle_before_submit
    on_submit      -> copy_vehicle_to_gate_pass_on_submit
  IB Gate Pass:
    validate       -> validate_gate_pass
    before_submit  -> enforce_vehicle_before_submit
  Sales Invoice:
    validate       -> validate_sales_invoice
    before_submit  -> enforce_vehicle_before_submit
  after_migrate    -> after_migrate / ensure_todo52_setup

Whitelist:
  get_carton_label_context
  probe_todo52
  ensure_todo52_setup
"""
from __future__ import annotations

import json
from typing import Any, Optional

import frappe
from frappe import _
from frappe.utils import cint, cstr

MARKER = "todo52_gate_locks"

# Prefer custom_* first so we own the field when India Compliance / transporter
# already exposed a different vehicle column — still resolve live aliases.
VEHICLE_CANDIDATES = (
	"custom_vehicle_no",
	"vehicle_no",
	"custom_vehicle_number",
	"vehicle_number",
	"vehicle",
)

CONTAINER_CANDIDATES = (
	"custom_container_no",
	"container_no",
	"container_number",
	"container",
)

SCAN_CANDIDATES = (
	"custom_scan_units",
	"custom_scanned_serials",
	"custom_carton_serials",
	"scanned_serials",
	"scan_units",
)

# The three shop-floor stickers plus the container sheet. All four are shipped as
# real print formats under instabiz/instabiz/print_format/ — they used to be
# placeholder text created here ("editable — replace with final layout"), which
# meant a fresh site had the Print buttons and nothing worth printing, and the
# container sheet's git copy was never what actually printed (see
# ensure_todo52_print_formats for how that happened).
#
# Kept as a table so the smoke report can still say whether each one is installed.
PRINT_FORMATS = {
	"import": {"name": "IB Import Label", "doc_types": ("IB Batch", "IB Container Import")},
	"container": {"name": "IB Container Label", "doc_types": ("IB Container Import",)},
	"carton": {"name": "IB Carton Label", "doc_types": ("IB FG Serial", "IB FG Serial No")},
	"coating_jumbo": {"name": "IB Coating Jumbo Label", "doc_types": ("IB Batch",)},
}


# ── Meta / field resolution ───────────────────────────────────────────────────


def _has_field(doctype: str, fieldname: str) -> bool:
	try:
		return bool(frappe.get_meta(doctype).has_field(fieldname))
	except Exception:
		return False


def _meta_fieldnames(doctype: str) -> set:
	try:
		return {df.fieldname for df in frappe.get_meta(doctype).fields}
	except Exception:
		return set()


def resolve_vehicle_field(doctype: str) -> Optional[str]:
	"""Return first existing vehicle fieldname on doctype (live alias audit)."""
	names = _meta_fieldnames(doctype)
	for c in VEHICLE_CANDIDATES:
		if c in names:
			return c
	return None


def resolve_container_field(doctype: str) -> Optional[str]:
	names = _meta_fieldnames(doctype)
	for c in CONTAINER_CANDIDATES:
		if c in names:
			return c
	return None


def resolve_scan_field(doctype: str) -> Optional[str]:
	names = _meta_fieldnames(doctype)
	for c in SCAN_CANDIDATES:
		if c in names:
			return c
	return None


def get_vehicle_value(doc) -> str:
	fname = resolve_vehicle_field(doc.doctype)
	if not fname:
		return ""
	return cstr(doc.get(fname) or "").strip()


def set_vehicle_value(doc, value: str) -> Optional[str]:
	fname = resolve_vehicle_field(doc.doctype)
	if not fname or value is None:
		return None
	if not cstr(doc.get(fname) or "").strip():
		doc.set(fname, value)
	return fname


def _ensure_custom_field(dt: str, fieldname: str, spec: dict) -> Optional[str]:
	if frappe.db.exists("Custom Field", {"dt": dt, "fieldname": fieldname}):
		return f"exists:{dt}.{fieldname}"
	if _has_field(dt, fieldname):
		return f"native:{dt}.{fieldname}"
	payload = {"doctype": "Custom Field", "dt": dt, "fieldname": fieldname, **spec}
	frappe.get_doc(payload).insert(ignore_permissions=True)
	return f"created:{dt}.{fieldname}"


def _insert_after_guess(dt: str, preferred: tuple) -> str:
	names = _meta_fieldnames(dt)
	for p in preferred:
		if p in names:
			return p
	# fallbacks that usually exist
	for p in ("transporter", "lr_no", "total_net_weight", "remarks", "amended_from"):
		if p in names:
			return p
	return "naming_series" if "naming_series" in names else "title"


def ensure_todo52_fields() -> dict:
	"""Idempotent: vehicle compulsory field + optional container + scan units."""
	out = {"marker": MARKER, "created": [], "resolved": {}, "notes": []}
	targets = []
	for dt in ("Delivery Note", "IB Gate Pass", "Sales Invoice"):
		if not frappe.db.exists("DocType", dt):
			out["notes"].append(f"missing DocType: {dt}")
			continue
		targets.append(dt)

	for dt in targets:
		existing = resolve_vehicle_field(dt)
		if existing:
			out["resolved"][f"{dt}.vehicle"] = existing
		else:
			after = _insert_after_guess(dt, ("transporter", "lr_no", "custom_total_cbm", "total_net_weight"))
			r = _ensure_custom_field(
				dt,
				"custom_vehicle_no",
				{
					"label": "Vehicle No",
					"fieldtype": "Data",
					"insert_after": after,
					"reqd": 0,  # enforced in before_submit, not DB reqd (drafts soft)
					"description": f"Todo52 compulsory on submit. Marker={MARKER}",
				},
			)
			out["created"].append(r)
			out["resolved"][f"{dt}.vehicle"] = "custom_vehicle_no"

		# container — ensure useful field, NEVER mark required
		cex = resolve_container_field(dt)
		if cex:
			out["resolved"][f"{dt}.container"] = cex
		else:
			after = _insert_after_guess(
				dt, ("custom_vehicle_no", "vehicle_no", "transporter", "lr_no")
			)
			r = _ensure_custom_field(
				dt,
				"custom_container_no",
				{
					"label": "Container No",
					"fieldtype": "Data",
					"insert_after": after,
					"reqd": 0,
					"description": f"Todo52 optional — never required. Marker={MARKER}",
				},
			)
			out["created"].append(r)
			out["resolved"][f"{dt}.container"] = "custom_container_no"

	# Outbound scan checklist field on DN + Gate Pass (soft warn only)
	for dt in ("Delivery Note", "IB Gate Pass"):
		if not frappe.db.exists("DocType", dt):
			continue
		sex = resolve_scan_field(dt)
		if sex:
			out["resolved"][f"{dt}.scan"] = sex
		else:
			after = _insert_after_guess(
				dt, ("custom_ib_gate_pass", "custom_container_no", "custom_vehicle_no", "remarks")
			)
			r = _ensure_custom_field(
				dt,
				"custom_scan_units",
				{
					"label": "Scanned Carton Serials",
					"fieldtype": "Long Text",
					"insert_after": after,
					"reqd": 0,
					"description": (
						f"Todo52 outbound scan checklist (soft warn only). "
						f"Comma/newline serials. Marker={MARKER}"
					),
				},
			)
			out["created"].append(r)
			out["resolved"][f"{dt}.scan"] = "custom_scan_units"

	if out["created"]:
		frappe.clear_cache()
	return out


def _set_ib_outbound_scan_soft_flag() -> dict:
	"""Prefer IB Stock Settings custom field; else site_config."""
	info = {"flag": "ib_outbound_scan_soft", "value": 1, "where": None}
	try:
		if frappe.db.exists("DocType", "IB Stock Settings"):
			# ensure field
			if not _has_field("IB Stock Settings", "ib_outbound_scan_soft"):
				_spec = {
					"label": "Outbound Scan Soft Warn",
					"fieldtype": "Check",
					"default": "1",
					"description": "Todo52: 1 = soft warn only (never hard-block DN/GP)",
				}
				if _has_field("IB Stock Settings", "naming_series"):
					_spec["insert_after"] = "naming_series"
				_ensure_custom_field("IB Stock Settings", "ib_outbound_scan_soft", _spec)
			try:
				frappe.db.set_single_value("IB Stock Settings", "ib_outbound_scan_soft", 1)
				info["where"] = "IB Stock Settings"
				return info
			except Exception:
				pass
	except Exception as e:
		info["settings_error"] = str(e)

	try:
		conf = frappe.get_site_config() or {}
		if cint(conf.get("ib_outbound_scan_soft", 0)) != 1:
			from frappe.installer import update_site_config

			update_site_config("ib_outbound_scan_soft", 1)
		info["where"] = "site_config"
	except Exception as e:
		info["conf_error"] = str(e)
		# last resort: in-memory for this process
		frappe.conf.ib_outbound_scan_soft = 1
		info["where"] = "frappe.conf_memory"
	return info


def is_outbound_scan_soft() -> bool:
	"""Always soft by locked decision (e); flag documents intent."""
	try:
		if frappe.db.exists("DocType", "IB Stock Settings") and _has_field(
			"IB Stock Settings", "ib_outbound_scan_soft"
		):
			v = frappe.db.get_single_value("IB Stock Settings", "ib_outbound_scan_soft")
			if v is not None:
				return cint(v) == 1
	except Exception:
		pass
	try:
		return cint(frappe.conf.get("ib_outbound_scan_soft", 1)) == 1
	except Exception:
		return True


# ── Vehicle enforce / copy ────────────────────────────────────────────────────


def _soft_vehicle_msg(doc) -> None:
	if get_vehicle_value(doc):
		return
	fname = resolve_vehicle_field(doc.doctype) or "custom_vehicle_no"
	frappe.msgprint(
		_("Vehicle No ({0}) is compulsory before submit.").format(fname),
		indicator="orange",
		alert=True,
	)


def enforce_vehicle_before_submit(doc, method=None):
	"""Hard throw if vehicle blank on submit. container_no never checked."""
	ensure_todo52_fields()
	val = get_vehicle_value(doc)
	if val:
		return
	fname = resolve_vehicle_field(doc.doctype) or "custom_vehicle_no"
	frappe.throw(
		_("Vehicle No is compulsory on {0}. Please set {1} before submit.").format(
			_(doc.doctype), fname
		),
		title=_("Vehicle No Required"),
	)


def validate_delivery_note(doc, method=None):
	ensure_todo52_fields()
	_soft_vehicle_msg(doc)
	_soft_outbound_scan_warn(doc)


def validate_gate_pass(doc, method=None):
	ensure_todo52_fields()
	_soft_vehicle_msg(doc)
	# Pull vehicle from linked DN if blank (auto-create path / make_from)
	_pull_vehicle_from_dn_ref(doc)
	_soft_outbound_scan_warn(doc)


def validate_sales_invoice(doc, method=None):
	ensure_todo52_fields()
	_copy_vehicle_from_dn_to_si(doc)
	_soft_vehicle_msg(doc)


def _dn_names_from_si(doc) -> list:
	names = []
	if getattr(doc, "delivery_note", None):
		names.append(doc.delivery_note)
	for row in doc.get("items") or []:
		for attr in ("delivery_note", "against_delivery_note", "dn_detail"):
			# dn_detail is child row name — skip
			if attr == "dn_detail":
				continue
			v = getattr(row, attr, None)
			if v and v not in names:
				names.append(v)
	return names


def _copy_vehicle_from_dn_to_si(doc) -> None:
	if get_vehicle_value(doc):
		return
	for dn_name in _dn_names_from_si(doc):
		if not frappe.db.exists("Delivery Note", dn_name):
			continue
		dn = frappe.get_doc("Delivery Note", dn_name)
		src = get_vehicle_value(dn)
		if src:
			set_vehicle_value(doc, src)
			return


def _pull_vehicle_from_dn_ref(gp) -> None:
	if get_vehicle_value(gp):
		return
	dn_name = None
	meta = gp.meta
	for pair in (
		("reference_doctype", "reference_name"),
		("ref_doctype", "ref_name"),
		("document_type", "document_name"),
	):
		if meta.has_field(pair[0]) and meta.has_field(pair[1]):
			if cstr(gp.get(pair[0])) == "Delivery Note" and gp.get(pair[1]):
				dn_name = gp.get(pair[1])
				break
	if not dn_name and meta.has_field("delivery_note"):
		dn_name = gp.get("delivery_note")
	if not dn_name:
		return
	if not frappe.db.exists("Delivery Note", dn_name):
		return
	dn = frappe.get_doc("Delivery Note", dn_name)
	src = get_vehicle_value(dn)
	if src:
		set_vehicle_value(gp, src)


def copy_vehicle_to_gate_pass_on_submit(doc, method=None):
	"""After DN submit / auto Gate Pass: copy vehicle_no DN → GP if GP blank."""
	if doc.doctype != "Delivery Note":
		return
	src = get_vehicle_value(doc)
	if not src:
		return
	gp_name = None
	if _has_field("Delivery Note", "custom_ib_gate_pass"):
		gp_name = doc.get("custom_ib_gate_pass")
	if not gp_name:
		# best-effort lookup like dn_packing_gate_pass
		try:
			from instabiz.overrides.dn_packing_gate_pass import _existing_gate_pass

			gp_name = _existing_gate_pass(doc.name)
		except Exception:
			gp_name = None
	if not gp_name or not frappe.db.exists("IB Gate Pass", gp_name):
		return
	gp = frappe.get_doc("IB Gate Pass", gp_name)
	if get_vehicle_value(gp):
		return
	fname = set_vehicle_value(gp, src)
	if not fname:
		return
	# Persist without re-entering full validate when already submitted
	try:
		if int(gp.docstatus or 0) == 0:
			gp.save(ignore_permissions=True)
		else:
			frappe.db.set_value("IB Gate Pass", gp.name, fname, src, update_modified=False)
	except Exception as e:
		frappe.log_error(f"todo52 copy vehicle DN→GP failed: {e}", MARKER)


def copy_vehicle_dn_to_target(dn, target_doc) -> Optional[str]:
	"""Helper for dn_packing_gate_pass / custom_make_sales_invoice patches."""
	src = get_vehicle_value(dn) if hasattr(dn, "doctype") else ""
	if not src and isinstance(dn, str) and frappe.db.exists("Delivery Note", dn):
		src = get_vehicle_value(frappe.get_doc("Delivery Note", dn))
	if not src:
		return None
	return set_vehicle_value(target_doc, src)


# ── Soft outbound scan ────────────────────────────────────────────────────────


def _scan_payload(doc) -> str:
	fname = resolve_scan_field(doc.doctype)
	if not fname:
		return ""
	return cstr(doc.get(fname) or "").strip()


def _has_linked_carton_serials(doc) -> bool:
	"""True if scan field non-empty OR items carry serial/batch looking like cartons."""
	raw = _scan_payload(doc)
	if raw:
		parts = [p.strip() for p in raw.replace("\n", ",").split(",") if p.strip()]
		if parts:
			return True
	# child serial_no / custom_carton_serial
	for row in doc.get("items") or []:
		for attr in ("serial_no", "custom_carton_serial", "carton_serial", "custom_serial_no"):
			if cstr(getattr(row, attr, None) or "").strip():
				return True
	return False


def _soft_outbound_scan_warn(doc) -> None:
	"""Orange warning only — NEVER throw (locked decision e)."""
	if not is_outbound_scan_soft():
		# Even if flag flipped off, locked decision forbids hard-block.
		pass
	if _has_linked_carton_serials(doc):
		return
	fname = resolve_scan_field(doc.doctype) or "custom_scan_units"
	frappe.msgprint(
		_(
			"Outbound carton scan checklist is empty ({0}). "
			"You may still submit — this is a soft warning only."
		).format(fname),
		indicator="orange",
		alert=True,
		title=_("Outbound Scan Soft Warn"),
	)


# ── Mixed jumbo carton label context ──────────────────────────────────────────


def _loads(raw: Any) -> Any:
	if raw is None or raw == "":
		return None
	if isinstance(raw, (dict, list)):
		return raw
	try:
		return json.loads(raw)
	except Exception:
		return None


def _fg_serial_doctype() -> Optional[str]:
	for dt in ("IB FG Serial", "IB FG Serial No"):
		if frappe.db.exists("DocType", dt):
			return dt
	return None


def _jumbo_list_from_payload(payload: Any) -> list:
	"""Normalize jumbos → list of serial/batch strings (ALL, not primary only)."""
	out = []
	seen = set()

	def add(v):
		s = cstr(v or "").strip()
		if s and s not in seen:
			seen.add(s)
			out.append(s)

	if payload is None:
		return out
	if isinstance(payload, dict):
		rows = payload.get("jumbos") or payload.get("serials") or payload.get("batches") or []
		if not rows and (payload.get("batch") or payload.get("serial")):
			rows = [payload]
		payload = rows
	if isinstance(payload, list):
		for row in payload:
			if isinstance(row, str):
				add(row)
			elif isinstance(row, dict):
				add(
					row.get("serial")
					or row.get("jumbo_serial")
					or row.get("batch")
					or row.get("source_batch")
					or row.get("name")
				)
	elif isinstance(payload, str):
		for p in payload.replace("\n", ",").split(","):
			add(p)
	return out


@frappe.whitelist()
def get_carton_label_context(serial: str) -> dict:
	"""Whitelist helper for Print Format / API — returns ALL jumbo serials.

	Sources (in order):
	  1. FG serial custom_source_batches_json / source_batches_json
	  2. IB Work Order.custom_jumbo_serials_json
	  3. FG source_batch (single) as last resort
	"""
	out = {
		"marker": MARKER,
		"serial": serial,
		"fg_serial": None,
		"work_order": None,
		"jumbo_serials": [],
		"jumbos": [],
		"source": None,
		"locked": {"mixed_jumbo_label_shows_all": True},
	}
	if not serial:
		return out

	fg_dt = _fg_serial_doctype()
	fg = None
	if fg_dt and frappe.db.exists(fg_dt, serial):
		fg = frappe.get_doc(fg_dt, serial)
	elif fg_dt:
		name = frappe.db.get_value(fg_dt, {"serial_no": serial}, "name")
		if name:
			fg = frappe.get_doc(fg_dt, name)

	wo_name = None
	if fg:
		out["fg_serial"] = fg.name
		meta_names = {df.fieldname for df in fg.meta.fields}
		json_field = None
		for c in ("custom_source_batches_json", "source_batches_json"):
			if c in meta_names:
				json_field = c
				break
		if json_field:
			payload = _loads(fg.get(json_field))
			jumbos = _jumbo_list_from_payload(payload)
			if jumbos:
				out["jumbo_serials"] = jumbos
				out["jumbos"] = payload if isinstance(payload, list) else (payload or {}).get("jumbos")
				out["source"] = f"{fg_dt}.{json_field}"
		wo_name = getattr(fg, "work_order", None) or getattr(fg, "ib_work_order", None)
		if not out["jumbo_serials"] and getattr(fg, "source_batch", None):
			# keep as fallback after WO check
			out["_fg_source_batch"] = fg.source_batch

	if (not out["jumbo_serials"]) and wo_name and frappe.db.exists("IB Work Order", wo_name):
		wo = frappe.get_doc("IB Work Order", wo_name)
		out["work_order"] = wo.name
		jp = _loads(getattr(wo, "custom_jumbo_serials_json", None))
		jumbos = _jumbo_list_from_payload(jp)
		if jumbos:
			out["jumbo_serials"] = jumbos
			out["jumbos"] = (jp or {}).get("jumbos") if isinstance(jp, dict) else jp
			out["source"] = "IB Work Order.custom_jumbo_serials_json"
		elif getattr(wo, "source_batch", None) and not out["jumbo_serials"]:
			out["jumbo_serials"] = [wo.source_batch]
			out["source"] = "IB Work Order.source_batch"

	if not out["jumbo_serials"] and out.get("_fg_source_batch"):
		out["jumbo_serials"] = [out["_fg_source_batch"]]
		out["source"] = "FG.source_batch"
	out.pop("_fg_source_batch", None)

	# Also allow resolving WO name directly
	if not fg and frappe.db.exists("IB Work Order", serial):
		wo = frappe.get_doc("IB Work Order", serial)
		out["work_order"] = wo.name
		jp = _loads(getattr(wo, "custom_jumbo_serials_json", None))
		out["jumbo_serials"] = _jumbo_list_from_payload(jp)
		out["source"] = "IB Work Order.custom_jumbo_serials_json"
		out["jumbos"] = (jp or {}).get("jumbos") if isinstance(jp, dict) else jp

	return out


# ── Editable Print Formats ────────────────────────────────────────────────────


def _pick_doc_type(candidates: tuple) -> Optional[str]:
	for dt in candidates:
		if frappe.db.exists("DocType", dt):
			return dt
	return None


def ensure_todo52_print_formats() -> dict:
	"""Adopt the four label Print Formats the app ships, and report on them.

	This used to insert placeholder text ("Todo52 stub", "editable — replace with
	final layout") for three of them and then force standard="No" on all four on
	every run, so the shop could redesign them in the UI. The placeholders are what
	printed for as long as nobody redesigned them, which was the whole time: a
	fresh site got the Print buttons and nothing worth printing.

	All four are real shipped files now (print_format/ib_*_label/), so the flag goes
	back to standard="Yes" — not because it changes what renders (for a DocType
	format printview.get_print_format checks the module path first and the file
	wins whatever the flag says) but because a shipped format should not be
	presented as somebody's local edit, and because the placeholder html sitting in
	the column is the thing that gets found when someone goes looking for why a
	label looks wrong.

	Redesigning is still possible: "Duplicate" in the Print Format UI makes an
	editable copy, and that copy is the one to point a Print button at.
	"""
	out = {"marker": MARKER, "formats": [], "notes": []}
	for key, spec in PRINT_FORMATS.items():
		name = spec["name"]
		dt = _pick_doc_type(spec["doc_types"])
		if not dt:
			out["notes"].append(f"{key}: no DocType among {spec['doc_types']}")
			continue
		if not frappe.db.exists("Print Format", name):
			# Shipped as a file, so migrate imports it. Missing here means the
			# module folder did not import — worth saying, not worth faking.
			out["notes"].append(f"{name}: not installed (expected from print_format/)")
			continue
		try:
			pf = frappe.db.get_value(
				"Print Format", name, ["standard", "custom_format", "html"], as_dict=True
			)
			changes = {}
			if pf.standard != "Yes":
				changes["standard"] = "Yes"
			if not cint(pf.custom_format):
				changes["custom_format"] = 1
			if (pf.html or "").strip():
				# The stub text. Harmless now that a file exists — but it is what
				# turns up first when someone debugs the label, so clear it.
				changes["html"] = ""
			if changes:
				# db.set_value, not doc.save(): Print Format.validate refuses to
				# save a standard="Yes" format outside developer_mode / migrate,
				# and this is not an edit — it is asserting what the app ships.
				frappe.db.set_value("Print Format", name, changes, update_modified=False)
				out["formats"].append(f"adopted_shipped:{name}:{','.join(sorted(changes))}")
			else:
				out["formats"].append(f"exists:{name}")
		except Exception as e:
			out["notes"].append(f"{name}: {e}")
	return out


# ── Setup / probe ─────────────────────────────────────────────────────────────


@frappe.whitelist()
def ensure_todo52_setup() -> dict:
	out = {
		"marker": MARKER,
		"todo": 52,
		"fields": {},
		"print_formats": {},
		"soft_flag": {},
		"notes": [
			"retention: filter + within_retention only — NO auto-delete job",
			"container_no: optional forever",
			"outbound scan: soft warn only",
			"mixed jumbo label: ALL serials",
		],
	}
	out["fields"] = ensure_todo52_fields()
	out["print_formats"] = ensure_todo52_print_formats()
	out["soft_flag"] = _set_ib_outbound_scan_soft_flag()
	out["client_scripts"] = _ensure_client_scripts()
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
	return ""


def _ensure_one_client_script(cs_name: str, dt: str, js: str) -> str:
	if not js:
		return f"skipped:no js:{dt}"
	if not frappe.db.exists("DocType", dt):
		return f"skipped:no doctype:{dt}"
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
			"dt": dt,
			"view": "Form",
			"enabled": 1,
			"script": js,
		}
	)
	doc.insert(ignore_permissions=True)
	return f"created:{cs_name}"


def _ensure_client_scripts() -> list:
	"""Install per-DocType Client Scripts (Frappe scopes each script to one dt)."""
	js = _read_js("dn_gate_locks.js")
	out = []
	for dt, label in (
		("Delivery Note", "DN"),
		("IB Gate Pass", "Gate Pass"),
		("Sales Invoice", "SI"),
	):
		out.append(
			_ensure_one_client_script(f"Todo52 Gate Locks — {label}", dt, js)
		)
	return out


def after_migrate():
	try:
		ensure_todo52_setup()
	except Exception:
		frappe.log_error(title="todo52 ensure failed")


@frappe.whitelist()
def probe_todo52() -> dict:
	"""Audit-only probe. Does not claim live Windows success from the Linux box."""
	out = {
		"marker": MARKER,
		"todo": 52,
		"status": "ok",
		"vehicle_fields": {},
		"container_fields": {},
		"scan_fields": {},
		"print_formats": {},
		"helpers": {},
		"flags": {},
		"locked_decisions": {
			"mixed_jumbo_label_all": True,
			"retention_no_auto_delete": True,
			"vehicle_compulsory": True,
			"container_optional": True,
			"labels_editable": True,
			"outbound_scan_soft_only": True,
		},
	}
	for dt in ("Delivery Note", "IB Gate Pass", "Sales Invoice"):
		exists = bool(frappe.db.exists("DocType", dt))
		out["vehicle_fields"][dt] = {
			"doctype_exists": exists,
			"resolved": resolve_vehicle_field(dt) if exists else None,
			"candidates_checked": list(VEHICLE_CANDIDATES),
		}
		out["container_fields"][dt] = {
			"resolved": resolve_container_field(dt) if exists else None,
			"required_enforced": False,
		}
		if dt in ("Delivery Note", "IB Gate Pass"):
			out["scan_fields"][dt] = {
				"resolved": resolve_scan_field(dt) if exists else None,
				"hard_block": False,
			}

	for key, spec in PRINT_FORMATS.items():
		name = spec["name"]
		out["print_formats"][key] = {
			"name": name,
			"exists": bool(frappe.db.exists("Print Format", name)),
			"doc_type_pick": _pick_doc_type(spec["doc_types"]),
		}
	out["print_formats"]["coating_jumbo"] = {
		"name": "IB Coating Jumbo Label",
		"exists": bool(frappe.db.exists("Print Format", "IB Coating Jumbo Label")),
	}

	out["helpers"]["get_carton_label_context"] = True
	out["helpers"]["ensure_todo52_setup"] = True
	out["helpers"]["list_trace_chain_retention"] = "mfg_serials.list_trace_chain (within_retention)"
	out["flags"]["ib_outbound_scan_soft"] = is_outbound_scan_soft()
	out["flags"]["no_auto_delete_job"] = True
	return out


@frappe.whitelist()
def smoke_todo52():
	"""Live check: empty vehicle must throw; validate soft-scan must not."""
	import json
	out = {}
	name = frappe.db.get_value("Delivery Note", {"docstatus": 0}, "name")
	out["draft_dn"] = name
	if not name:
		out["status"] = "no_draft_dn"
		return out
	doc = frappe.get_doc("Delivery Note", name)
	old = doc.get("vehicle_no")
	doc.vehicle_no = ""
	if hasattr(doc, "custom_vehicle_no"):
		try:
			doc.custom_vehicle_no = ""
		except Exception:
			pass
	threw = False
	msg = ""
	try:
		enforce_vehicle_before_submit(doc)
	except Exception as e:
		threw = True
		msg = str(e)[:200]
	out["empty_vehicle_throws"] = threw
	out["empty_vehicle_msg"] = msg
	soft_ok = True
	try:
		validate_delivery_note(doc)
	except Exception as e:
		soft_ok = False
		out["validate_err"] = str(e)[:200]
	out["validate_soft_ok"] = soft_ok
	out["ctx"] = get_carton_label_context(serial="")
	doc.vehicle_no = old
	frappe.db.rollback()
	out["status"] = "ok" if threw and soft_ok else "check"
	return out
