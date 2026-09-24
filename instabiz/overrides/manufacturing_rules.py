"""instabiz.overrides.manufacturing_rules

Locked Instabiz manufacturing rules (Idris 2026-09-21):

1. 1 Sales Order -> 1 Order Sheet -> 1 Work Order (header) + output lines.
   SO and WO keep SEPARATE number series (track by Sales Order No).
   Same-serial OS<->WO naming is retired (apply_wo_name_from_os is a no-op).
2. Conversion (MFG): jumbo from source/main WH -> convert -> FG WH -> DN from FG.
   Ready goods: DN direct after SO (no production). On Gujarat/SGM WO/run create,
   allocate a leaf sub-warehouse so ready jumbo lines do not enter production.
3. Advance gate before create_run / Start when SO has advance terms.
4. conversion_path: "Slitting Direct" | "Rewind then Cut".
5. Logs/SQM helpers (logs = planner estimate only; cutting/packing still refine).
6. Slitting usable width: Item.custom_usable_width_mm or width - trim setting.
7. FG / carton serials embed OS + WO + date for traceability.
"""
from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate


ADVANCE_TEMPLATE = "IB Advance then Balance Before Despatch"
ADVANCE_TERM_NAMES = ("Advance Before Production",)

# SGM / Gujarat group and known leaf roles
GUJARAT_GROUP = "GUJARAT - IB"
FG_GUJARAT = "FG - GUJARAT - IB"
FG_MAHARASHTRA = "FG - MAHARASHTRA - IB"
READY_WAREHOUSES = {
	# BWD is warehouse-only ready jumbo / trading
	"maharashtra": "MAHARASHTRA - IB",
}
CONVERSION_DEFAULT_SOURCE = {
	# Conversion floor default when not otherwise allocated
	"gujarat": "Second Floor - GUJARAT - IB",
	"maharashtra": "MAHARASHTRA - IB",
	"chennai": "CHENNAI - IB",
}
FG_WAREHOUSE_BY_LOCATION = {
	"gujarat": FG_GUJARAT,
	"maharashtra": FG_MAHARASHTRA,
	"chennai": "CHENNAI - IB",
}


# ── Advance ──────────────────────────────────────────────────────────────────

def so_requires_advance(sales_order: str) -> bool:
	if not sales_order or not frappe.db.exists("Sales Order", sales_order):
		return False
	so = frappe.db.get_value(
		"Sales Order", sales_order, ["payment_terms_template", "name"], as_dict=True
	)
	if so and so.payment_terms_template == ADVANCE_TEMPLATE:
		return True
	rows = frappe.get_all(
		"Payment Schedule",
		filters={"parent": sales_order, "parenttype": "Sales Order"},
		fields=["payment_term"],
	)
	for r in rows:
		term = r.payment_term or ""
		if term in ADVANCE_TERM_NAMES or "advance" in term.lower():
			return True
	return False


def advance_outstanding(sales_order: str) -> float:
	rows = frappe.get_all(
		"Payment Schedule",
		filters={"parent": sales_order, "parenttype": "Sales Order"},
		fields=["payment_term", "payment_amount", "paid_amount"],
	)
	due = 0.0
	for r in rows:
		term = r.payment_term or ""
		if term in ADVANCE_TERM_NAMES or "advance" in term.lower():
			due += max(flt(r.payment_amount) - flt(r.paid_amount), 0.0)
	if due > 0:
		return due
	if so_requires_advance(sales_order):
		so_total = flt(frappe.db.get_value("Sales Order", sales_order, "grand_total"))
		need = so_total * 0.30
		paid = _payments_against_so(sales_order)
		return max(need - paid, 0.0)
	return 0.0


def _payments_against_so(sales_order: str) -> float:
	pe_refs = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(per.allocated_amount), 0)
		FROM `tabPayment Entry Reference` per
		INNER JOIN `tabPayment Entry` pe ON pe.name = per.parent AND pe.docstatus = 1
		WHERE per.reference_doctype = 'Sales Order' AND per.reference_name = %s
		""",
		sales_order,
	)[0][0]
	si_paid = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(per.allocated_amount), 0)
		FROM `tabPayment Entry Reference` per
		INNER JOIN `tabPayment Entry` pe ON pe.name = per.parent AND pe.docstatus = 1
		INNER JOIN `tabSales Invoice Item` sii ON sii.parent = per.reference_name
			AND per.reference_doctype = 'Sales Invoice'
		WHERE sii.sales_order = %s AND pe.docstatus = 1
		""",
		sales_order,
	)[0][0]
	return flt(pe_refs) + flt(si_paid)


def assert_advance_cleared(sales_order: str):
	if not sales_order:
		return
	if not so_requires_advance(sales_order):
		return
	left = advance_outstanding(sales_order)
	if left > 0.5:
		frappe.throw(
			_(
				"Advance of {0} is still unpaid on Sales Order {1}. "
				"Receive the advance before starting production."
			).format(frappe.format_value(left, {"fieldtype": "Currency"}), sales_order)
		)


# ── Naming (separate series — no-op) ──────────────────────────────────────────

def os_to_wo_name(order_sheet: str) -> str:
	"""Deprecated: kept for smoke/compat. Do not force WO name from OS."""
	if not order_sheet:
		return ""
	if order_sheet.startswith("IB-OS-"):
		return "IB-WO-" + order_sheet[len("IB-OS-") :]
	return "IB-WO-" + order_sheet


def next_wo_name_for_os(order_sheet: str) -> str:
	"""Deprecated: WO uses DocType autoname IB-WO-.YYYY.-.#####."""
	return ""


def apply_wo_name_from_os(doc):
	"""No-op. SO/OS/WO keep independent series; track by sales_order link."""
	return


# ── Conversion path ───────────────────────────────────────────────────────────

def infer_conversion_path(route_stages) -> str:
	stages = [s for s in (route_stages or []) if s]
	if "Rewinding" in stages and "Cutting" in stages:
		return "Rewind then Cut"
	if "Slitting" in stages:
		return "Slitting Direct"
	return ""


def stamp_conversion_path(doc):
	if frappe.get_meta("IB Work Order").has_field("conversion_path"):
		route = [r.stage for r in (doc.route or [])]
		path = infer_conversion_path(route)
		if path:
			doc.conversion_path = path


# ── Logs / SQM estimates ──────────────────────────────────────────────────────

def roll_sqm(width_mm, length_mtr) -> float:
	"""One roll/log area in SQM, 2 decimal places."""
	w = flt(width_mm)
	l = flt(length_mtr)
	if w <= 0 or l <= 0:
		return 0.0
	return round((w / 1000.0) * l, 2)


def calc_sqm_needed(qty, uom, width_mm=None, length_mtr=None, item_code=None) -> float:
	"""Order demand in SQM (2 dp). PCS/rolls -> qty * roll area; SQMT -> qty."""
	u = (uom or "").upper()
	q = flt(qty)
	if item_code and (not width_mm or not length_mtr):
		im = frappe.db.get_value("Item", item_code, ["width_mm", "length_mtr", "stock_uom"], as_dict=True) or {}
		width_mm = width_mm or im.get("width_mm")
		length_mtr = length_mtr or im.get("length_mtr")
		u = u or (im.get("stock_uom") or "")
		u = u.upper()
	if u in ("SQMT", "SQM", "M2", "M²"):
		return round(q, 2)
	area = roll_sqm(width_mm, length_mtr)
	if area > 0:
		return round(q * area, 2)
	return round(q, 2)


def calc_logs_needed(sqm_needed, jumbo_width_mm, jumbo_length_mtr, usable_width_mm=None) -> int:
	"""Planner estimate of jumbo logs. Ceiling. Not the final cut list."""
	sqm = flt(sqm_needed)
	jw = flt(usable_width_mm) if usable_width_mm else flt(jumbo_width_mm)
	jl = flt(jumbo_length_mtr)
	if sqm <= 0 or jw <= 0 or jl <= 0:
		return 0
	per_log = roll_sqm(jw, jl)
	if per_log <= 0:
		return 0
	import math
	return int(math.ceil(sqm / per_log))


def usable_width_mm(item_code, jumbo_width_mm=None) -> float:
	"""Usable width = the width set on the item/line (Idris 2026-09-21).

	Do NOT subtract a fixed trim here. Side trim / waste is calculated later from
	cut-size allocation and recovery on the slitting plan (jumbo - sum(cuts)).
	Optional Item.custom_usable_width_mm overrides only when staff set it explicitly.
	"""
	jw = flt(jumbo_width_mm)
	if item_code and frappe.db.has_column("Item", "custom_usable_width_mm"):
		uw = flt(frappe.db.get_value("Item", item_code, "custom_usable_width_mm"))
		if uw > 0:
			return uw
	if not jw and item_code:
		jw = flt(frappe.db.get_value("Item", item_code, "width_mm"))
	return jw


def allocation_trim_mm(jumbo_usable_mm, allocated_widths_mm) -> float:
	"""Waste/trim mm left after packing cut widths onto usable jumbo width."""
	used = sum(flt(w) for w in (allocated_widths_mm or []) if flt(w) > 0)
	left = flt(jumbo_usable_mm) - used
	return round(left, 2) if left > 0 else 0.0


def stamp_output_logs_sqm(doc):
	"""Fill logs_needed / sqm_needed on WO outputs when fields exist."""
	meta = frappe.get_meta("IB WO Output")
	has_sqm = meta.has_field("sqm_needed")
	has_logs = meta.has_field("logs_needed")
	if not (has_sqm or has_logs):
		return
	src_w = flt(getattr(doc, "source_width_mm", None) or 0)
	src_l = flt(getattr(doc, "source_length_mtr", None) or 0)
	src_item = doc.get("source_item")
	if src_item and (not src_w or not src_l):
		im = frappe.db.get_value("Item", src_item, ["width_mm", "length_mtr"], as_dict=True) or {}
		src_w = src_w or flt(im.get("width_mm"))
		src_l = src_l or flt(im.get("length_mtr"))
	uw = usable_width_mm(src_item, src_w) if src_item or src_w else src_w
	for o in doc.get("outputs") or []:
		sqm = calc_sqm_needed(o.planned_qty, o.uom, o.width_mm, o.length_mtr, o.item_code)
		if has_sqm and not flt(o.get("sqm_needed")):
			o.sqm_needed = sqm
		if has_logs and not cint(o.get("logs_needed")):
			# estimate vs source jumbo
			jw = src_w or flt(o.width_mm)
			jl = src_l or flt(o.length_mtr)
			o.logs_needed = calc_logs_needed(sqm, jw, jl, uw if jw == src_w else None)


# ── Path classification + sub-warehouse ───────────────────────────────────────

def item_needs_conversion(item_code, location=None) -> bool:
	"""True if item has a production stage route at this location."""
	if not item_code:
		return False
	try:
		from instabiz.overrides.production import _get_stage_route
		route = _get_stage_route(item_code, location) or []
		return bool(route)
	except Exception:
		return False


def allocate_sub_warehouse(location, fulfillment_path, preferred=None) -> str:
	"""Pick leaf WH for Gujarat group. Ready goods stay on Ground; conversion on floor."""
	loc = (location or "").lower()
	if preferred and frappe.db.exists("Warehouse", preferred):
		if not frappe.db.get_value("Warehouse", preferred, "is_group"):
			return preferred
	if loc in ("maharashtra", "bwd"):
		return READY_WAREHOUSES.get("maharashtra", "MAHARASHTRA - IB")
	if fulfillment_path == "Ready Goods":
		# Trading / ready jumbo at SGM sits on Ground Floor leaf
		return "Ground Floor - GUJARAT - IB"
	if fulfillment_path == "Conversion":
		return CONVERSION_DEFAULT_SOURCE.get("gujarat", "Second Floor - GUJARAT - IB")
	return CONVERSION_DEFAULT_SOURCE.get(loc) or "Ground Floor - GUJARAT - IB"


def resolve_fulfillment_path(item_code, location=None) -> str:
	loc = (location or "").lower()
	# BWD / Maharashtra: warehouse-only — ready path
	if loc in ("maharashtra", "bwd"):
		return "Ready Goods"
	if item_needs_conversion(item_code, location):
		return "Conversion"
	return "Ready Goods"


def stamp_source_warehouse(doc):
	"""On WO create: set source_warehouse leaf so ready jumbo never hits conversion floor."""
	if not frappe.get_meta("IB Work Order").has_field("source_warehouse"):
		return
	if doc.get("source_warehouse"):
		# still resolve group -> leaf
		wh = doc.source_warehouse
		if frappe.db.get_value("Warehouse", wh, "is_group"):
			path = doc.get("fulfillment_path") or resolve_fulfillment_path(
				doc.get("source_item") or (doc.outputs[0].item_code if doc.get("outputs") else None),
				doc.get("location"),
			)
			doc.source_warehouse = allocate_sub_warehouse(doc.get("location"), path)
		return
	item = doc.get("source_item")
	if not item and doc.get("outputs"):
		item = doc.outputs[0].item_code
	path = resolve_fulfillment_path(item, doc.get("location"))
	if frappe.get_meta("IB Work Order").has_field("fulfillment_path"):
		doc.fulfillment_path = path
	doc.source_warehouse = allocate_sub_warehouse(doc.get("location"), path)


def fg_warehouse_for_location(location: str) -> str:
	loc = (location or "").lower()
	name = FG_WAREHOUSE_BY_LOCATION.get(loc)
	if name and frappe.db.exists("Warehouse", name):
		return name
	from instabiz.overrides import ib_settings
	field = {
		"gujarat": "fg_warehouse_gujarat",
		"maharashtra": "fg_warehouse_maharashtra",
		"chennai": "fg_warehouse_chennai",
	}.get(loc)
	if field:
		configured = ib_settings.get(field, None)
		if configured:
			return configured
	return allocate_sub_warehouse(loc, "Ready Goods")


# ── Serials ───────────────────────────────────────────────────────────────────

def make_carton_serial(item_code: str, order_sheet: str, work_order: str, box_no: int, produced_on=None) -> str:
	d = getdate(produced_on or nowdate()).strftime("%Y%m%d")
	os_bit = (order_sheet or "NOOS").replace("IB-OS-", "OS")
	wo_bit = (work_order or "NOWO").replace("IB-WO-", "WO")
	return f"{item_code}::{os_bit}::{wo_bit}::{d}::{box_no:04d}"


def ensure_scrap_warehouse(company: str) -> str:
	name = "Scrap - IB"
	if frappe.db.exists("Warehouse", name):
		return name
	existing = frappe.db.get_value(
		"Warehouse", {"warehouse_name": ["like", "%Scrap%"], "company": company}, "name"
	)
	if existing:
		return existing
	wh = frappe.get_doc(
		{
			"doctype": "Warehouse",
			"warehouse_name": "Scrap",
			"company": company,
			"parent_warehouse": GUJARAT_GROUP if frappe.db.exists("Warehouse", GUJARAT_GROUP) else None,
			"is_group": 0,
		}
	)
	wh.insert(ignore_permissions=True)
	return wh.name


# ── Migrate / ensure ──────────────────────────────────────────────────────────

def ensure_mfg_lock_setup():
	"""Idempotent: FG warehouses, settings, custom fields, print format stub."""
	company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
		"Company", {}, "name"
	)
	_ensure_fg_warehouses(company)
	_ensure_stock_settings()
	_ensure_custom_fields()
	_ensure_coating_label_print_format()
	frappe.clear_cache()
	return {
		"fg_gujarat": frappe.db.exists("Warehouse", FG_GUJARAT) and FG_GUJARAT,
		"fg_maharashtra": frappe.db.exists("Warehouse", FG_MAHARASHTRA) and FG_MAHARASHTRA,
		"settings": {
			"fg_warehouse_gujarat": frappe.db.get_single_value("IB Stock Settings", "fg_warehouse_gujarat"),
			"slitting_trim_mm": frappe.db.get_single_value("IB Stock Settings", "slitting_trim_mm"),
		},
	}


def _ensure_fg_warehouses(company):
	specs = [
		(FG_GUJARAT, "FG", GUJARAT_GROUP),
		(FG_MAHARASHTRA, "FG Maharashtra", None),
	]
	for name, wh_name, parent in specs:
		if frappe.db.exists("Warehouse", name):
			continue
		# name may differ if warehouse_name-based naming
		existing = frappe.db.get_value("Warehouse", {"warehouse_name": wh_name, "company": company}, "name")
		if existing:
			continue
		doc = frappe.get_doc(
			{
				"doctype": "Warehouse",
				"warehouse_name": wh_name if name == FG_GUJARAT else "FG",
				"company": company,
				"parent_warehouse": parent if parent and frappe.db.exists("Warehouse", parent) else None,
				"is_group": 0,
			}
		)
		# Force known name via flags when possible
		doc.insert(ignore_permissions=True)
		if doc.name != name and not frappe.db.exists("Warehouse", name):
			try:
				frappe.rename_doc("Warehouse", doc.name, name, force=True, merge=False)
			except Exception:
				frappe.log_error("IB MFG FG warehouse rename", frappe.get_traceback())


def _ensure_stock_settings():
	if not frappe.db.exists("DocType", "IB Stock Settings"):
		return
	# resolve actual FG names after create
	fg_g = FG_GUJARAT if frappe.db.exists("Warehouse", FG_GUJARAT) else frappe.db.get_value(
		"Warehouse", {"warehouse_name": "FG", "parent_warehouse": GUJARAT_GROUP}, "name"
	)
	fg_m = FG_MAHARASHTRA if frappe.db.exists("Warehouse", FG_MAHARASHTRA) else frappe.db.get_value(
		"Warehouse", {"warehouse_name": ["in", ["FG", "FG Maharashtra"]], "parent_warehouse": ["in", ["", None]]}, "name"
	)
	ss = frappe.get_single("IB Stock Settings")
	changed = False
	if fg_g and not ss.fg_warehouse_gujarat:
		ss.fg_warehouse_gujarat = fg_g
		changed = True
	if fg_m and not ss.fg_warehouse_maharashtra:
		ss.fg_warehouse_maharashtra = fg_m
		changed = True
	if not cint(ss.production_posts_stock):
		ss.production_posts_stock = 1
		changed = True
	if changed:
		ss.save(ignore_permissions=True)


def _ensure_custom_fields():
	fields = [
		{
			"dt": "IB WO Output",
			"fieldname": "sqm_needed",
			"label": "SQM Needed",
			"fieldtype": "Float",
			"precision": "2",
			"insert_after": "planned_qty",
		},
		{
			"dt": "IB WO Output",
			"fieldname": "logs_needed",
			"label": "Logs Needed (est.)",
			"fieldtype": "Int",
			"insert_after": "sqm_needed",
		},
		{
			"dt": "IB Work Order",
			"fieldname": "fulfillment_path",
			"label": "Fulfillment Path",
			"fieldtype": "Select",
			"options": "\nConversion\nReady Goods",
			"insert_after": "location",
		},
		{
			"dt": "Item",
			"fieldname": "custom_usable_width_mm",
			"label": "Usable Width (mm)",
			"fieldtype": "Float",
			"insert_after": "width_mm",
			"description": "Slitting usable width after side trim (e.g. 1296 when jumbo is 1315).",
		},
	]
	for f in fields:
		name = f"{f['dt']}-{f['fieldname']}"
		if frappe.db.exists("Custom Field", name) or frappe.db.exists(
			"Custom Field", {"dt": f["dt"], "fieldname": f["fieldname"]}
		):
			continue
		# skip if already on DocType
		try:
			if frappe.get_meta(f["dt"]).has_field(f["fieldname"]):
				continue
		except Exception:
			pass
		doc = frappe.get_doc({"doctype": "Custom Field", **f})
		doc.insert(ignore_permissions=True)


def _ensure_coating_label_print_format():
	"""The coating jumbo sticker is a shipped Print Format — adopt it, don't fake it.

	This used to insert a monospace placeholder ("editable — replace with final
	layout") as standard="No". A standard="No" format renders the html column in
	the database rather than the file on disk, so the placeholder outlived every
	attempt to design a real label. The real one is
	print_format/ib_coating_jumbo_label/, and gate_locks.ensure_todo52_print_formats
	is what puts the flag back where it belongs.
	"""
	from instabiz.overrides.gate_locks import ensure_todo52_print_formats

	ensure_todo52_print_formats()


@frappe.whitelist()
def print_coating_jumbo_label(batch: str):
	"""Return PDF of IB Coating Jumbo Label for an IB Batch."""
	from frappe.utils.print_utils import get_print

	if not batch or not frappe.db.exists("IB Batch", batch):
		frappe.throw(_("IB Batch {0} not found").format(batch))
	ensure_mfg_lock_setup()
	pdf = get_print("IB Batch", batch, print_format="IB Coating Jumbo Label", as_pdf=True)
	frappe.local.response.filename = f"{batch}-coating-jumbo-label.pdf"
	frappe.local.response.filecontent = pdf
	frappe.local.response.type = "pdf"


def smoke_check():
	ensure_mfg_lock_setup()
	sqm = calc_sqm_needed(10, "PCS", 48, 50)
	logs = calc_logs_needed(sqm, 1296, 4000)
	return {
		"apply_wo_name_noop": apply_wo_name_from_os(frappe._dict()) is None,
		"sample_sqm_10pcs_48x50": sqm,
		"sample_logs": logs,
		"usable_default_trim": usable_width_mm(None, 1315),
		"setup": ensure_mfg_lock_setup(),
	}