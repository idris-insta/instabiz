"""instabiz.overrides.dpr_auto

The daily production report fills itself from production data. Every stage a
run completes (IB Work Order stage_log) becomes one IB DPR Entry, with the run's
machine, operator, jumbo, item, size, brand, times and output already in.
The few DPR-only numbers (shafts, logs, cartons, film / adhesive microns,
drum...) are asked in the same "Complete Stage" dialog, pre-filled from the
run, and handed over through a short-lived cache until the entry is made.
"""
import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, getdate, time_diff_in_seconds

CACHE = "ib_dpr_extra:{0}:{1}"
SUBSTRATE_BY_GROUP = {"PLASTIC": "BOPP", "PVC": "PVC", "FOIL": "Aluminium Foil", "FOAM": "Foam",
	"FOAM - PE": "Foam", "PAPER": "Kraft Paper", "REFLECTIVE": "BOPP"}
HM_SUBSTRATES = {"Aluminium Foil", "Foam", "Kraft Paper", "HDPE", "DS Polyester"}
# which DPR inputs each stage asks for in the Complete Stage dialog
ASK = {
	"Coating WB": ["film_mic", "adh_mic", "no_of_rolls", "color_used", "film_waste", "adh_waste"],
	"Coating PVC": ["film_mic", "adh_mic", "no_of_rolls", "color_used", "film_waste", "adh_waste"],
	"Coating HM": ["film_mic", "adh_mic", "liner_mic", "adhesive_sides", "no_of_rolls", "film_waste", "adh_waste"],
	"Slitting": ["shafts", "jumbo_width_mm", "qty_per_ctn", "total_ctns"],
	"Rewinding": ["no_of_logs", "jumbo_mtr", "wastage_mtr"],
	"Cutting": ["no_of_logs", "log_width_mm", "qty_per_ctn", "total_ctns"],
	"Silicon": ["drum_no", "weight_per_pc", "weight_per_drum", "total_ctns", "pcs_per_ctn"],
	"Packing": ["total_ctns", "pcs_per_ctn"],
}


def _first_output(wo):
	return (wo.get("outputs") or [frappe._dict()])[0]


def _item_info(item_code):
	if not item_code:
		return frappe._dict()
	return frappe.db.get_value("Item", item_code, ["item_group", "item_name", "color", "custom_thickness"], as_dict=True) or frappe._dict()


def _substrate(item):
	name = (item.item_name or "").upper()
	if "HDPE" in name:
		return "HDPE"
	if "DS" in name and "POLY" in name:
		return "DS Polyester"
	if "KRAFT" in name:
		return "Kraft Paper"
	return SUBSTRATE_BY_GROUP.get(item.item_group or "", "BOPP")


def dpr_stage(wo, stage):
	if stage != "Coating":
		return stage
	sub = _substrate(_item_info(wo.get("source_item") or _first_output(wo).item_code))
	if sub == "PVC":
		return "Coating PVC"
	return "Coating HM" if sub in HM_SUBSTRATES else "Coating WB"


def _defaults(wo, stage, output_qty=None, input_qty=None):
	out = _first_output(wo)
	item = _item_info(out.item_code)
	src = _item_info(wo.get("source_item"))
	batch = frappe.db.get_value("IB Batch", wo.source_batch, ["width_mm", "length_mtr"], as_dict=True) if wo.get("source_batch") else None
	batch = batch or frappe._dict()
	label = dpr_stage(wo, stage)
	qty = flt(output_qty if output_qty is not None else (out.produced_qty or out.planned_qty))
	per_ctn = cint(out.pack_count) or 0
	d = frappe._dict(stage=label, width_mm=out.width_mm, length_mtr=out.length_mtr, brand=out.brand,
		color=item.color, microns=flt((item.custom_thickness or "").split()[0]) if (item.custom_thickness or "").split() else 0,
		jumbo_width_mm=batch.width_mm, jumbo_mtr=batch.length_mtr, log_width_mm=batch.width_mm)
	if label.startswith("Coating"):
		d.coating_substrate = _substrate(src if src else item)
		d.no_of_rolls = qty
		d.width_mm = batch.width_mm or out.width_mm
		d.length_mtr = batch.length_mtr or out.length_mtr
	elif label in ("Slitting", "Cutting"):
		d.qty_per_ctn = per_ctn
		d.total_ctns = round(qty / per_ctn, 2) if per_ctn else qty
		if label == "Cutting":
			d.no_of_logs = flt(input_qty) or None
	elif label == "Rewinding":
		d.no_of_logs = qty
	elif label == "Packing":
		d.pcs_per_ctn = per_ctn or 1
		d.total_ctns = round(qty / (per_ctn or 1), 2)
	elif label == "Silicon":
		d.pcs_per_ctn = 24
		d.total_ctns = round(qty / 24, 2)
	return d


@frappe.whitelist()
def get_prompt(work_order):
	"""What the Complete Stage dialog should ask for this run's current stage, pre-filled."""
	wo = frappe.get_doc("IB Work Order", work_order)
	stage = wo.current_stage
	if not stage or stage == "Done":
		return {}
	d = _defaults(wo, stage)
	label = d.stage
	meta = frappe.get_meta("IB DPR Entry")
	fields = []
	for fn in ASK.get(label, []):
		df = meta.get_field(fn)
		if df:
			fields.append({"fieldname": fn, "label": df.label, "fieldtype": df.fieldtype,
				"default": d.get(fn) if d.get(fn) not in (None, "") else df.default})
	return {"dpr_stage": label, "fields": fields}


@frappe.whitelist()
def stash(work_order, stage, data):
	"""Hold the dialog's DPR numbers until the stage completion saves the run."""
	data = frappe.parse_json(data) if isinstance(data, str) else (data or {})
	frappe.cache.set_value(CACHE.format(work_order, stage), data, expires_in_sec=900)
	return True


def sync_from_work_order(doc, method=None):
	"""IB Work Order on_update: one DPR line per newly completed stage event."""
	for ev in doc.get("stage_log") or []:
		if ev.skipped or not ev.completed_at:
			continue
		# only fresh completions; history is filled by backfill()
		if time_diff_in_seconds(frappe.utils.now_datetime(), get_datetime(ev.completed_at)) > 2 * 86400:
			continue
		try:
			make_entry(doc, ev)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"IB DPR auto entry {doc.name}")


def make_entry(wo, ev, extra=None):
	if frappe.db.exists("IB DPR Entry", {"stage_event": ev.name}):
		return None
	extra = extra if extra is not None else (frappe.cache.get_value(CACHE.format(wo.name, ev.stage)) or {})
	d = _defaults(wo, ev.stage, output_qty=ev.output_qty, input_qty=ev.input_qty)
	d.update({k: v for k, v in (extra or {}).items() if v not in (None, "")})
	out = _first_output(wo)
	secs = time_diff_in_seconds(get_datetime(ev.completed_at), get_datetime(ev.started_at)) if ev.started_at else 0
	entry = frappe.get_doc({
		"doctype": "IB DPR Entry", "source": "Production", "stage_event": ev.name,
		"posting_date": getdate(ev.completed_at), "shift": "Night" if get_datetime(ev.completed_at).hour >= 20 else "Day",
		"location": (wo.get("location") or "gujarat").lower(), "machine": ev.machine, "operator": _employee(ev.operator),
		"work_order": wo.name, "sales_order": wo.get("sales_order"), "os_no": wo.get("order_sheet"),
		"jumbo_no": wo.get("source_batch"), "item_code": out.item_code, "output_qty": ev.output_qty,
		"input_qty": ev.input_qty, "wastage_qty": ev.wastage_qty,
		"time_taken": round(max(secs, 0) / 60, 1) if secs and secs < 86400 else 0,
		**{k: v for k, v in d.items() if v not in (None, "")},
	})
	entry.flags.ignore_permissions = True
	entry.insert()
	frappe.cache.delete_value(CACHE.format(wo.name, ev.stage))
	return entry.name


def _employee(user):
	if not user:
		return None
	return frappe.db.get_value("Employee", {"user_id": user}, "name")


@frappe.whitelist()
def backfill(from_date=None):
	"""Create DPR lines for past stage completions (managers; safe to re-run)."""
	frappe.only_for(["System Manager", "Factory Management"])
	cond, args = "e.skipped = 0 AND e.completed_at IS NOT NULL", {}
	if from_date:
		cond += " AND DATE(e.completed_at) >= %(f)s"
		args["f"] = from_date
	rows = frappe.db.sql(f"""SELECT e.parent, e.name FROM `tabIB WO Stage Event` e
		WHERE {cond} ORDER BY e.completed_at""", args, as_dict=True)
	made, cache = 0, {}
	for r in rows:
		wo = cache.get(r.parent) or frappe.get_doc("IB Work Order", r.parent)
		cache[r.parent] = wo
		ev = next((e for e in wo.stage_log if e.name == r.name), None)
		if ev and make_entry(wo, ev, extra={}):
			made += 1
	frappe.db.commit()
	return _("{0} DPR lines created from production records.").format(made)
