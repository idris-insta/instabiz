"""IB DPR Sheet — the daily production report in the DPR workbook layout.

View "Summary" is the MAIN sheet (each stage and variant with its day's
quantity); the stage views are the DPR COATING / SLITTING / REWINDING /
CUTTING / SILICON / PACKING sheets with a total line. Source: IB DPR Entry.
"""
import frappe
from frappe import _
from frappe.utils import flt, getdate, today

BASE = [("machine", "Machine", "Link", "IB Machine", 90), ("jumbo_no", "Jumbo No", "Data", None, 80),
	("item_code", "Item", "Link", "Item", 150), ("width_mm", "Width (MM)", "Float", None, 80),
	("length_mtr", "Length (MTR)", "Float", None, 85), ("microns", "Microns", "Float", None, 70),
	("color", "Color", "Data", None, 70), ("brand", "Brand", "Data", None, 80)]

VIEWS = {
	"Coating": BASE[:1] + [("coating_substrate", "Film", "Data", None, 100), ("stage", "Line", "Data", None, 95)] + BASE[1:7] + [
		("film_mic", "Film Mic", "Float"), ("adh_mic", "Adh Mic", "Float"), ("liner_mic", "Liner Mic", "Float"),
		("film_per_sqm", "Film / SQM", "Float"), ("adh_per_sqm", "Adh / SQM", "Float"), ("no_of_rolls", "No of Rolls", "Float"),
		("film_used", "Film Used", "Float"), ("adh_used", "Adh Used", "Float"), ("adh_solid", "Adh Solid", "Float"),
		("color_used", "Color Used", "Float"), ("roll_weight", "Roll Wt", "Float"), ("time_per_roll", "Time / Roll", "Float"),
		("film_waste", "Film Waste", "Float"), ("adh_waste", "Adh Waste", "Float"),
		("film_total", "Film Stock Used", "Float"), ("adh_total", "Adh Stock Used", "Float"), ("liner_total", "Liner Used", "Float")],
	"Slitting": BASE + [("shafts", "Shafts", "Float"), ("qty_per_ctn", "QTY / CTN", "Float"), ("total_ctns", "Total CTNs", "Float"),
		("sqm_per_ctn", "SQM / CTN", "Float"), ("total_sqm", "Total SQM", "Float"), ("os_no", "OS No", "Data"),
		("shafts_used_per_ctn", "SFT Used / CTN", "Float"), ("shafts_req_per_ctn", "SFT Req / CTN", "Float"),
		("jumbo_width_mm", "Jumbo Width", "Float"), ("pcs_per_shaft", "PCS / Shaft", "Float"), ("total_pcs", "Total PCS", "Float"),
		("pcs_used", "PCS Used", "Float"), ("balance_pcs", "Balance PCS", "Float"), ("time_taken", "Time Taken", "Float"),
		("time_per_shaft", "Time / Shaft", "Float")],
	"Rewinding": BASE + [("no_of_logs", "No of Logs", "Float"), ("total_mtrs", "Total MTRs", "Float"),
		("jumbo_mtr", "MTR of Jumbo", "Float"), ("sqm_per_roll", "SQM / Roll", "Float"), ("total_sqm", "Total SQM", "Float"),
		("wastage_mtr", "Wastage", "Float"), ("balance_mtrs", "Bal MTRs", "Float"), ("os_no", "OS No", "Data"),
		("time_taken", "Time Taken", "Float"), ("time_per_log", "Time / Log", "Float")],
	"Cutting": BASE + [("no_of_logs", "No of Logs", "Float"), ("log_width_mm", "MM of Jumbo", "Float"),
		("pcs_per_log", "PCS / Log", "Float"), ("total_pcs", "Total PCS", "Float"), ("balance_pcs", "Bal PCS", "Float"),
		("os_no", "OS No", "Data"), ("qty_per_ctn", "QTY / CTN", "Float"), ("total_ctns", "No of CTN", "Float"),
		("pcs_used", "PCS Used", "Float"), ("time_taken", "Time Taken", "Float"), ("time_per_log", "Time / Log", "Float")],
	"Silicon": [("machine", "Machine", "Link", "IB Machine", 90), ("drum_no", "Drum No", "Data"),
		("item_code", "Item", "Link", "Item", 150), ("weight_per_pc", "Weight / PC (g)", "Float"),
		("weight_per_drum", "Weight / Drum (kg)", "Float"), ("color", "Color", "Data"), ("total_ctns", "No of CTNs", "Float"),
		("total_pcs", "Total PCS", "Float"), ("party", "Party", "Link", "Customer", 150), ("pcs_per_drum", "PC / Drum", "Float"),
		("ctns_per_drum", "CTN / Drum", "Float")],
	"Packing": [("machine", "Machine", "Link", "IB Machine", 90), ("item_code", "Item", "Link", "Item", 180),
		("total_ctns", "No of CTNs", "Float"), ("pcs_per_ctn", "PCS / CTN", "Float"), ("brand", "Brand", "Data"),
		("total_pcs", "Total PCS", "Float"), ("os_no", "OS No", "Data")],
}
# columns that get a sum on the total line (the sheet's SUM rows)
SUMS = {"no_of_rolls", "film_total", "adh_total", "liner_total", "film_waste", "adh_waste", "color_used", "shafts",
	"total_ctns", "total_sqm", "total_pcs", "pcs_used", "no_of_logs", "total_mtrs", "wastage_mtr", "time_taken",
	"weight_per_drum"}


def execute(filters=None):
	f = frappe._dict(filters or {})
	f.from_date = getdate(f.from_date or today())
	f.to_date = getdate(f.to_date or f.from_date)
	view = f.view or "Summary"
	if view == "Summary":
		return _summary_columns(), _summary(f), None, None, _cards(f)
	return _columns(VIEWS[view]), _stage_rows(f, view), None, None, _cards(f)


def _where(f):
	cond, args = "posting_date BETWEEN %(from)s AND %(to)s", {"from": f.from_date, "to": f.to_date}
	if f.location:
		cond += " AND location = %(location)s"
		args["location"] = f.location
	if f.machine:
		cond += " AND machine = %(machine)s"
		args["machine"] = f.machine
	if f.shift:
		cond += " AND shift = %(shift)s"
		args["shift"] = f.shift
	return cond, args


def _columns(spec):
	cols = [{"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 90}]
	for c in spec:
		fieldname, label, fieldtype = c[0], c[1], c[2]
		col = {"label": _(label), "fieldname": fieldname, "fieldtype": fieldtype, "width": c[4] if len(c) > 4 else 95}
		if len(c) > 3 and c[3]:
			col["options"] = c[3]
		if fieldtype == "Float":
			col["precision"] = 2
		cols.append(col)
	cols.append({"label": _("Entry"), "fieldname": "name", "fieldtype": "Link", "options": "IB DPR Entry", "width": 130})
	return cols


def _stage_rows(f, view):
	cond, args = _where(f)
	if view == "Coating":
		cond += " AND stage LIKE 'Coating%%'"
	else:
		cond += " AND stage = %(stage)s"
		args["stage"] = view
	rows = frappe.db.sql(f"SELECT * FROM `tabIB DPR Entry` WHERE {cond} ORDER BY posting_date, machine, creation",
		args, as_dict=True)
	if rows:
		total = frappe._dict(machine="", item_code="<b>" + _("Total") + "</b>", bold=1)
		for c in VIEWS[view]:
			if c[0] in SUMS:
				total[c[0]] = sum(flt(r.get(c[0])) for r in rows)
		rows.append(total)
	return rows


def _summary_columns():
	return [
		{"label": _("Stage"), "fieldname": "stage", "fieldtype": "Data", "width": 130},
		{"label": _("Variant"), "fieldname": "variant", "fieldtype": "Data", "width": 170},
		{"label": _("Measure"), "fieldname": "measure", "fieldtype": "Data", "width": 90},
		{"label": _("Qty"), "fieldname": "qty", "fieldtype": "Float", "precision": 2, "width": 120},
		{"label": _("Runs"), "fieldname": "runs", "fieldtype": "Int", "width": 70},
	]


def _summary(f):
	cond, args = _where(f)
	rows = frappe.db.sql(f"SELECT * FROM `tabIB DPR Entry` WHERE {cond}", args, as_dict=True)
	out, acc = [], {}

	def add(stage, variant, measure, qty):
		key = (stage, variant, measure)
		if key not in acc:
			acc[key] = frappe._dict(stage=stage, variant=variant, measure=measure, qty=0, runs=0)
			out.append(acc[key])
		acc[key].qty += flt(qty)
		acc[key].runs += 1

	order = ["Coating WB", "Coating HM", "Coating PVC", "Slitting", "Rewinding", "Cutting", "Silicon", "Packing"]
	for r in sorted(rows, key=lambda r: (order.index(r.stage) if r.stage in order else 99, r.coating_substrate or "", flt(r.film_mic))):
		if r.stage == "Coating WB":
			add(r.stage, f"{flt(r.film_mic):g} MIC {r.coating_substrate or ''}".strip(), "ROLLS", r.no_of_rolls)
		elif r.stage in ("Coating HM", "Coating PVC"):
			add(r.stage, r.coating_substrate or r.item_code or "", "ROLLS", r.no_of_rolls)
		elif r.stage == "Slitting":
			add(r.stage, "SHAFT", "SHAFTS", r.shafts)
			add(r.stage, "CTNS", "CTNS", r.total_ctns)
		elif r.stage == "Rewinding":
			add(r.stage, "LOG", "LOGS", r.no_of_logs)
			add(r.stage, "MTR", "MTR", r.total_mtrs)
			add(r.stage, "SQM", "SQM", r.total_sqm)
		elif r.stage == "Cutting":
			add(r.stage, "LOGS", "LOGS", r.no_of_logs)
			add(r.stage, "CTNS", "CTNS", r.total_ctns)
		elif r.stage == "Silicon":
			add(r.stage, "KGS", "KGS", r.weight_per_drum)
			add(r.stage, "CTNS", "CTNS", r.total_ctns)
		elif r.stage == "Packing":
			add(r.stage, "CTNS", "CTNS", r.total_ctns)
			add(r.stage, "ROLLS", "PCS", r.total_pcs)
	return out


def _cards(f):
	cond, args = _where(f)
	r = frappe.db.sql(f"""SELECT COUNT(*) runs, SUM(IF(stage LIKE 'Coating%%', no_of_rolls, 0)) rolls,
		SUM(IF(stage IN ('Slitting','Rewinding') OR stage LIKE 'Coating%%', total_sqm, 0)) sqm,
		SUM(IF(stage = 'Packing', total_ctns, 0)) packed, SUM(time_taken) mins
		FROM `tabIB DPR Entry` WHERE {cond}""", args, as_dict=True)[0]
	return [
		{"label": _("Runs"), "value": r.runs or 0, "datatype": "Int"},
		{"label": _("Coated Rolls"), "value": flt(r.rolls), "datatype": "Float"},
		{"label": _("SQM (coat / slit / rewind)"), "value": flt(r.sqm), "datatype": "Float"},
		{"label": _("CTNs Packed"), "value": flt(r.packed), "datatype": "Float"},
		{"label": _("Machine Hours"), "value": round(flt(r.mins) / 60, 1), "datatype": "Float"},
	]
