"""instabiz.overrides.production"""
import json

import frappe
from frappe import _
from frappe.model.workflow import apply_workflow
from frappe.utils import today, now, flt, cint, add_days, getdate, nowdate, date_diff, get_fullname

_PRODUCTION_ROLES = {"Factory Management", "Factory Production", "System Manager"}


def _require_production_role():
    if not (_PRODUCTION_ROLES & set(frappe.get_roles())):
        frappe.throw(_("Not permitted — Factory Management role required"), frappe.PermissionError)


def _check_so_production_access(sales_order):
	"""Restrict production visibility to: production-role users, Sales Manager/
	System Manager, or the Sales Order's own sales person/owner. Was previously
	unguarded — any logged-in user could pull any other rep's order detail."""
	if _PRODUCTION_ROLES & set(frappe.get_roles()):
		return
	from instabiz.overrides.permissions import _is_privileged
	if _is_privileged(frappe.session.user):
		return
	row = frappe.db.get_value("Sales Order", sales_order, ["custom_sales_person_user", "owner"], as_dict=True)
	if not row:
		frappe.throw(_("Sales Order {0} not found").format(sales_order))
	if frappe.session.user in (row.custom_sales_person_user, row.owner):
		return
	frappe.throw(_("Not permitted to view production status for this Sales Order"), frappe.PermissionError)

# Ready to Deliver / Delivered collapsed out of the stage model entirely
# (2026-08-13, user's explicit decision). Packing (or an item's real last
# production stage) is now the true last Work Order — nothing is
# manufactured at RTD, it was a manual click with no physical work behind
# it. "Ready to Deliver" is now just what a Completed-through-Packing item
# IS (Create Delivery Note becomes available); "Delivered" is derived from
# the Delivery Note being submitted (see mark_wos_delivered / _get_dispatch_info)
# rather than a Work Order anyone starts/completes. Despatch-type IB Machines
# (DS-01/DS-02) lose their only purpose in the stage-routing model as a
# result — left as real master data, just unreferenced by production flow.
STAGES = [
	"Coating",
	"Slitting",
	"Rewinding",
	"Cutting",
	"Packing",
]

_STAGE_MACHINE_TYPE = {
	"Coating":   "Coating",
	"Slitting":  "Slitting",
	"Rewinding": "Rewinding",
	"Cutting":   "Cutting",
	"Packing":   "Packing",
}

# Stage route per item group — determines which stages apply in order.
# Items skip stages not in their route (e.g. PVC tapes don't need Coating).
_ITEM_GROUP_STAGE_ROUTES = {
	"PLASTIC":           ["Coating", "Slitting", "Rewinding", "Cutting", "Packing"],
	"PAPER":             ["Coating", "Slitting", "Cutting", "Packing"],
	"REFLECTIVE":        ["Coating", "Slitting", "Cutting", "Packing"],
	"PVC":               ["Slitting", "Cutting", "Packing"],
	"CLOTH":             ["Slitting", "Cutting", "Packing"],
	"FOAM":              ["Slitting", "Cutting", "Packing"],
	"FOAM - PE":         ["Slitting", "Cutting", "Packing"],
	"FOIL":              ["Slitting", "Cutting", "Packing"],
	"AEROSOL-PAINT":     ["Packing"],
	"AEROSOL-CLEANER":   ["Packing"],
	"AEROSOL-LUBRICANT": ["Packing"],
	"AEROSOL-MULTI":     ["Packing"],
	"AEROSOL-PU FOAM":   ["Packing"],
	"SEALANT-ACRYLIC":   ["Packing"],
	"SEALANT-SILICONE":  ["Packing"],
	"ADHESIVE-HOTMELT":  ["Packing"],
}
_DEFAULT_STAGE_ROUTE = ["Cutting", "Packing"]

# Gujarat is the only factory location (Coating/Slitting/Rewinding/Cutting
# machines all live there). Maharashtra and Chennai are warehouse-only — an
# order routed to either always gets just Packing regardless of item group,
# since there's no factory capability physically there.
_WAREHOUSE_ONLY_LOCATIONS = {"maharashtra", "chennai"}
_WAREHOUSE_STAGE_ROUTE = ["Packing"]


def _get_stage_route(item_code, location=None):
	"""Return ordered list of production stages for an item.

	`location` is the Sales Order's `custom_location` (maharashtra/gujarat/chennai,
	lowercase). Warehouse-only locations short-circuit to Packing->RTD; Gujarat
	(factory) uses the existing item-group-based route.
	"""
	if (location or "").lower() in _WAREHOUSE_ONLY_LOCATIONS:
		return _WAREHOUSE_STAGE_ROUTE
	item_group = frappe.db.get_value("Item", item_code, "item_group") or ""
	return _ITEM_GROUP_STAGE_ROUTES.get(item_group, _DEFAULT_STAGE_ROUTE)


def _assign_machine_load_balanced(stage, location=None):
	"""Return least-loaded active machine for stage (prefer same location).

	Load = number of active (Pending + In Progress) Work Orders currently on the machine.
	If capacity is set on the machine, machines at/over capacity are skipped first.
	"""
	machine_type = _STAGE_MACHINE_TYPE.get(stage)
	if not machine_type:
		return None

	machines = frappe.db.get_all(
		"IB Machine",
		filters={"machine_type": machine_type, "status": "Active"},
		fields=["name", "location", "capacity", "floor"],
		order_by="name asc",
	)
	if not machines:
		return None

	# Floor-aware filter: a machine with a floor set may only run stages that
	# floor is actually equipped for (IB Production Floor.allow_*). Machines
	# with no floor set are untouched by this — location-only behavior as before.
	from instabiz.instabiz.doctype.ib_production_floor.ib_production_floor import get_allowed_stages
	machines = [
		m for m in machines
		if not m.floor or stage in get_allowed_stages(m.floor)
	]
	if not machines:
		return None

	# Prefer same-location machines; fall back to any — EXCEPT for a
	# warehouse-only location (Maharashtra/Chennai), which physically has no
	# machines at all (confirmed live: zero IB Machine rows for either).
	# Falling back there silently cross-assigned a real Gujarat machine to a
	# warehouse order (confirmed live: a Maharashtra Packing run got assigned
	# "PK-02", a Gujarat-location machine) — nonsensical for a floor
	# supervisor (Gujarat's Machine-wise view shows a Maharashtra order queued
	# on a machine two states away; Maharashtra's own Machine-wise view can
	# never show it, since it filters strictly by IB Machine.location). A
	# warehouse packing job just doesn't run on a machine in the traditional
	# sense — leave it unassigned rather than pick a wrong one.
	preferred = [m for m in machines if not location or m.location == location]
	if not preferred and location in _WAREHOUSE_ONLY_LOCATIONS:
		return None
	pool = preferred if preferred else machines

	if len(pool) == 1:
		return pool[0].name

	# Count active WOs per machine
	machine_names = [m.name for m in pool]
	placeholders = ", ".join(["%s"] * len(machine_names))
	load_rows = frappe.db.sql(
		f"""
		SELECT machine, COUNT(*) AS load_count
		FROM `tabIB Work Order`
		WHERE machine IN ({placeholders}) AND status IN ('Pending', 'In Progress')
		GROUP BY machine
		""",
		tuple(machine_names),
		as_dict=True,
	)
	load_map = {r.machine: r.load_count for r in load_rows}

	# Sort by load ascending — ties broken by name (stable order)
	pool.sort(key=lambda m: load_map.get(m.name, 0))

	# Skip machines at/over capacity (if capacity > 0)
	for m in pool:
		cap = flt(m.capacity)
		if cap > 0 and load_map.get(m.name, 0) >= cap:
			continue
		return m.name

	# All machines over capacity — assign to least-loaded anyway
	return pool[0].name


# Keep original name as alias for any callers that still reference it


# ---------------------------------------------------------------------------
# Dimension-aware machine assignment (run model)
#   feasible  ->  least changeover  ->  least load        (lexicographic)
# spec = {input_width_mm, output_widths_mm[], output_length_m,
#         output_diameter_mm, gsm, core_id, box_type}
# A machine field left blank = no constraint. spec empty = pure load balance.
# ---------------------------------------------------------------------------

_ASSUMED_TRIM_MM = 20.0            # slitter edge trim per jumbo (assumed; TODO shop-floor number)
_CHANGEOVER_PENALTY_MIN = 30.0    # used when IB Machine.changeover_min is unset
_SIG_STAGES = ("Coating", "Slitting", "Rewinding", "Cutting", "Packing")

_MACHINE_CAP_COLS = [
	"name", "location", "capacity", "floor",
	"max_input_width_mm", "max_output_width_mm", "min_slit_width_mm", "knife_positions",
	"max_roll_diameter_mm", "min_core_diameter_mm", "max_core_diameter_mm",
	"min_length_m", "max_length_m", "gsm_min", "gsm_max",
	"speed_m_per_min", "changeover_min", "current_setup_sig",
]


def _setup_sig(stage, spec):
	"""Short string identifying the machine setup a job needs at `stage`.
	Two jobs with the same signature share a setup -> zero changeover."""
	spec = spec or {}
	ow = sorted(int(round(flt(w))) for w in (spec.get("output_widths_mm") or []) if flt(w) > 0)
	core = spec.get("core_id") or ""
	if stage == "Coating":
		return "C|{0}|{1}|{2}".format(
			int(round(flt(spec.get("input_width_mm")))), int(round(flt(spec.get("gsm")))),
			spec.get("adhesive_type") or "",
		)
	if stage == "Slitting":
		return "S|{0}|{1}".format("-".join(map(str, ow)), core)
	if stage == "Rewinding":
		return "R|{0}|{1}".format(ow[-1] if ow else 0, core)
	if stage == "Cutting":
		return "X|{0}|{1}|{2}".format(ow[-1] if ow else 0, int(round(flt(spec.get("output_length_m")))), core)
	return "P|{0}".format(spec.get("box_type") or "")


def _machine_feasible(m, stage, spec):
	"""m: dict of IB Machine capability fields. Unset field => that check passes."""
	spec = spec or {}

	def le(val, cap):
		return not flt(cap) or flt(val) <= flt(cap)

	def ge(val, floor):
		return not flt(floor) or flt(val) >= flt(floor)

	iw = flt(spec.get("input_width_mm"))
	ows = [flt(w) for w in (spec.get("output_widths_mm") or []) if flt(w) > 0]
	dia = flt(spec.get("output_diameter_mm"))
	core_dia = flt(spec.get("core_diameter_mm"))
	length = flt(spec.get("output_length_m"))
	gsm = flt(spec.get("gsm"))
	n_out = len(ows)

	if stage == "Coating":
		if not le(iw, m.get("max_input_width_mm")):
			return False
		if flt(m.get("gsm_min")) and gsm and gsm < flt(m["gsm_min"]):
			return False
		if flt(m.get("gsm_max")) and gsm and gsm > flt(m["gsm_max"]):
			return False
		return True
	if stage == "Slitting":
		if not le(iw, m.get("max_input_width_mm")):
			return False
		if cint(m.get("knife_positions")) and n_out > cint(m["knife_positions"]):
			return False
		if ows and not ge(min(ows), m.get("min_slit_width_mm")):
			return False
		# Trim only actually gets lost when the pass genuinely narrows the web
		# (real cuts made -> real edge waste). A single output at (near) the
		# full input width is a pass-through, not a slit -- nothing is being
		# trimmed off, so the -_ASSUMED_TRIM_MM penalty shouldn't apply. Found
		# live: a real 380kg run with output width == source batch width
		# (1315mm both) was wrongly rejected here ("no machine can run this
		# job") purely because 1315 > 1315-20, despite SM-01 being physically
		# fine with it.
		is_passthrough = n_out == 1 and iw and abs(ows[0] - iw) < 0.01
		if not is_passthrough and iw and ows and sum(ows) > iw - _ASSUMED_TRIM_MM:
			return False
		if not le(dia, m.get("max_roll_diameter_mm")):
			return False
		if not le(core_dia, m.get("max_core_diameter_mm")):
			return False
		if not ge(core_dia, m.get("min_core_diameter_mm")):
			return False
		return True
	if stage == "Rewinding":
		if ows and not le(max(ows), m.get("max_input_width_mm")):
			return False
		if not le(dia, m.get("max_roll_diameter_mm")):
			return False
		if not le(core_dia, m.get("max_core_diameter_mm")):
			return False
		if not ge(core_dia, m.get("min_core_diameter_mm")):
			return False
		return True
	if stage == "Cutting":
		if ows and not le(max(ows), m.get("max_output_width_mm")):
			return False
		if flt(m.get("min_length_m")) and length and length < flt(m["min_length_m"]):
			return False
		if flt(m.get("max_length_m")) and length and length > flt(m["max_length_m"]):
			return False
		if cint(m.get("knife_positions")) and n_out > cint(m["knife_positions"]):
			return False
		return True
	return True  # Packing / Quality Control / Despatch


def _machine_infeasible_reason(m, stage, spec):
	"""Same checks as _machine_feasible, but returns a human reason for the
	FIRST one that fails (or None if the machine is feasible) — used only to
	build the "no machine can run this" error message, never on the hot
	assignment path. Kept as a parallel function rather than having
	_machine_feasible itself return a reason, so its own simple bool
	contract (and every existing caller) is untouched."""
	spec = spec or {}

	def le(val, cap):
		return not flt(cap) or flt(val) <= flt(cap)

	def ge(val, floor):
		return not flt(floor) or flt(val) >= flt(floor)

	iw = flt(spec.get("input_width_mm"))
	ows = [flt(w) for w in (spec.get("output_widths_mm") or []) if flt(w) > 0]
	dia = flt(spec.get("output_diameter_mm"))
	core_dia = flt(spec.get("core_diameter_mm"))
	length = flt(spec.get("output_length_m"))
	gsm = flt(spec.get("gsm"))
	n_out = len(ows)

	if stage == "Coating":
		if not le(iw, m.get("max_input_width_mm")):
			return _("input width {0}mm exceeds its max input width {1}mm").format(int(iw), int(flt(m["max_input_width_mm"])))
		if flt(m.get("gsm_min")) and gsm and gsm < flt(m["gsm_min"]):
			return _("GSM {0} is below its minimum {1}").format(gsm, flt(m["gsm_min"]))
		if flt(m.get("gsm_max")) and gsm and gsm > flt(m["gsm_max"]):
			return _("GSM {0} exceeds its maximum {1}").format(gsm, flt(m["gsm_max"]))
		return None
	if stage == "Slitting":
		if not le(iw, m.get("max_input_width_mm")):
			return _("input width {0}mm exceeds its max input width {1}mm").format(int(iw), int(flt(m["max_input_width_mm"])))
		if cint(m.get("knife_positions")) and n_out > cint(m["knife_positions"]):
			return _("needs {0} knives, it only has {1}").format(n_out, cint(m["knife_positions"]))
		if ows and not ge(min(ows), m.get("min_slit_width_mm")):
			return _("output width {0}mm is below its minimum slit width {1}mm").format(int(min(ows)), int(flt(m["min_slit_width_mm"])))
		is_passthrough = n_out == 1 and iw and abs(ows[0] - iw) < 0.01
		if not is_passthrough and iw and ows and sum(ows) > iw - _ASSUMED_TRIM_MM:
			return _("outputs sum to {0}mm, more than its {1}mm input allows after trim").format(int(sum(ows)), int(iw))
		if not le(dia, m.get("max_roll_diameter_mm")):
			return _("roll diameter {0}mm exceeds its max {1}mm").format(int(dia), int(flt(m["max_roll_diameter_mm"])))
		if not le(core_dia, m.get("max_core_diameter_mm")):
			return _("core diameter {0}mm exceeds its max {1}mm").format(int(core_dia), int(flt(m["max_core_diameter_mm"])))
		if not ge(core_dia, m.get("min_core_diameter_mm")):
			return _("core diameter {0}mm is below its min {1}mm").format(int(core_dia), int(flt(m["min_core_diameter_mm"])))
		return None
	if stage == "Rewinding":
		if ows and not le(max(ows), m.get("max_input_width_mm")):
			return _("output width {0}mm exceeds its max input width {1}mm").format(int(max(ows)), int(flt(m["max_input_width_mm"])))
		if not le(dia, m.get("max_roll_diameter_mm")):
			return _("roll diameter {0}mm exceeds its max {1}mm").format(int(dia), int(flt(m["max_roll_diameter_mm"])))
		if not le(core_dia, m.get("max_core_diameter_mm")):
			return _("core diameter {0}mm exceeds its max {1}mm").format(int(core_dia), int(flt(m["max_core_diameter_mm"])))
		if not ge(core_dia, m.get("min_core_diameter_mm")):
			return _("core diameter {0}mm is below its min {1}mm").format(int(core_dia), int(flt(m["min_core_diameter_mm"])))
		return None
	if stage == "Cutting":
		if ows and not le(max(ows), m.get("max_output_width_mm")):
			return _("output width {0}mm exceeds its max output width {1}mm").format(int(max(ows)), int(flt(m["max_output_width_mm"])))
		if flt(m.get("min_length_m")) and length and length < flt(m["min_length_m"]):
			return _("length {0}m is below its minimum {1}m").format(length, flt(m["min_length_m"]))
		if flt(m.get("max_length_m")) and length and length > flt(m["max_length_m"]):
			return _("length {0}m exceeds its maximum {1}m").format(length, flt(m["max_length_m"]))
		if cint(m.get("knife_positions")) and n_out > cint(m["knife_positions"]):
			return _("needs {0} knives, it only has {1}").format(n_out, cint(m["knife_positions"]))
		return None
	return None


def _machine_queued_minutes(machine_name, speed):
	"""Rough load: planned output over the machine's active/held runs / speed.
	Falls back to (run count x 60) when speed is unset — today's behaviour scaled."""
	rows = frappe.db.sql(
		"""SELECT COALESCE(SUM(o.planned_qty), 0) AS qty, COUNT(DISTINCT w.name) AS n
		   FROM `tabIB Work Order` w
		   LEFT JOIN `tabIB WO Output` o ON o.parent = w.name
		   WHERE w.machine = %s AND w.status IN ('In Progress', 'On Hold')""",
		machine_name, as_dict=True,
	)
	qty = flt(rows[0].qty) if rows else 0.0
	n = cint(rows[0].n) if rows else 0
	if flt(speed) > 0 and qty > 0:
		return qty / flt(speed)
	return n * 60.0


def _assign_machine(stage, location=None, spec=None):
	"""Dimension-aware pick for the run model. feasible -> least changeover -> least load.
	spec falsy -> feasibility all-pass -> pure load balance (matches the old fn)."""
	spec = spec or {}
	machine_type = _STAGE_MACHINE_TYPE.get(stage)
	if not machine_type:
		return None

	machines = frappe.db.get_all(
		"IB Machine",
		filters={"machine_type": machine_type, "status": "Active"},
		fields=_MACHINE_CAP_COLS,
		order_by="name asc",
	)
	if not machines:
		return None

	from instabiz.instabiz.doctype.ib_production_floor.ib_production_floor import get_allowed_stages
	machines = [m for m in machines if not m.get("floor") or stage in get_allowed_stages(m["floor"])]
	if not machines:
		return None

	# See _assign_machine_load_balanced's matching comment — a warehouse-only
	# location (Maharashtra/Chennai) has zero real machines; falling back to a
	# different location's machine here is the exact same bug (this is the
	# function create_run() actually calls) and produced the same real
	# cross-location mis-assignment confirmed live (a Maharashtra Packing run
	# assigned Gujarat's "PK-02").
	preferred = [m for m in machines if not location or m.get("location") == location]
	if not preferred and location in _WAREHOUSE_ONLY_LOCATIONS:
		return None
	pool = preferred if preferred else machines

	feasible = [m for m in pool if _machine_feasible(m, stage, spec)]

	# Real gap, fixed: this auto-picker never checked IB Machine.capacity at
	# all — only the MANUAL assign_machine RPC enforced it. Auto-assignment
	# (used here by create_run/resume_run/every stage-advance) could pile
	# unlimited concurrent runs onto one machine automatically; it only
	# ever load-balanced by queued minutes, never capped. Same "blank/0 =
	# no limit" convention as assign_machine's own check. Filtered here
	# (dropped from the candidate pool), not thrown per-machine — this
	# function picks among several candidates, it doesn't validate one.
	under_capacity = []
	for m in feasible:
		cap = flt(m.get("capacity"))
		if cap <= 0:
			under_capacity.append(m)
			continue
		load = frappe.db.count(
			"IB Work Order", filters={"machine": m["name"], "status": ["in", ("Pending", "In Progress")]}
		)
		if load < cap:
			under_capacity.append(m)
	feasible = under_capacity

	if not feasible:
		bits = []
		if flt(spec.get("input_width_mm")):
			bits.append(_("input width {0}mm").format(int(flt(spec["input_width_mm"]))))
		ows = [flt(w) for w in (spec.get("output_widths_mm") or []) if flt(w) > 0]
		if ows:
			bits.append(_("{0} output(s): {1}mm").format(len(ows), "/".join(str(int(w)) for w in ows)))
		# Real gap, found investigating a live report (IB-SGM-SO-01838): this
		# message used to just dump the job's own dimensions and say "check
		# the machine masters" — it never said WHICH machine failed WHICH
		# check, so a genuine "SM-01's min slit width is narrower than 2 of
		# your outputs" reason read identically to a real bug (a fabricated
		# input width, since fixed above). Per-machine breakdown so the real
		# reason is visible without having to go compare masters by hand.
		reasons = []
		for m in pool:
			why = _machine_infeasible_reason(m, stage, spec)
			if why is None:
				cap = flt(m.get("capacity"))
				if cap > 0:
					load = frappe.db.count(
						"IB Work Order", filters={"machine": m["name"], "status": ["in", ("Pending", "In Progress")]}
					)
					why = _("at capacity ({0}/{1} runs)").format(load, int(cap))
			if why:
				reasons.append(_("{0} — {1}").format(m["name"], why))
		detail = ("<br>" + "<br>".join(reasons)) if reasons else ""
		frappe.throw(_(
			"No active {0} machine at {1} can run this job ({2}).{3}"
		).format(machine_type, location or _("any location"), ", ".join(bits) or _("given dimensions"), detail))

	if len(feasible) == 1:
		return feasible[0]["name"]

	want_sig = _setup_sig(stage, spec)

	def _score(m):
		change = 0.0 if (m.get("current_setup_sig") or "") == want_sig \
			else (flt(m.get("changeover_min")) or _CHANGEOVER_PENALTY_MIN)
		return (change, _machine_queued_minutes(m["name"], m.get("speed_m_per_min")), m["name"])

	feasible.sort(key=_score)
	return feasible[0]["name"]


def _spec_from_run(doc):
	"""Build the assignment spec from an IB Work Order's outputs + source batch."""
	outs = list(doc.get("outputs") or [])
	widths = [flt(o.width_mm) for o in outs if flt(o.width_mm) > 0]
	lengths = [flt(o.length_mtr) for o in outs if flt(o.length_mtr) > 0]
	src_w = 0.0
	if doc.get("source_batch"):
		src_w = flt(frappe.db.get_value("IB Batch", doc.source_batch, "width_mm"))
	core = (outs[0].core if outs else "") or ""
	core_dia = flt(frappe.get_cached_value("Item", core, "custom_core_diameter_mm")) if core else 0.0
	adhesive_item = doc.get("source_item") or (outs[0].item_code if outs else "")
	adhesive = (frappe.get_cached_value("Item", adhesive_item, "custom_adhesive_type") or "") if adhesive_item else ""
	# Real bug, confirmed live (IB-SGM-SO-01838, 6 outputs 9/11/16/9/11/16mm):
	# this used to fall back to max(widths) — the LARGEST single OUTPUT
	# width — whenever the real source batch had no width_mm recorded.
	# Fabricating "input width 16mm" from an unrelated output, then feeding
	# it straight into _machine_feasible's sum(ows) > iw - trim check,
	# guarantees failure for any multi-output slitting job (6 outputs
	# summing 72mm can never fit inside a fabricated 16mm "input") —
	# every real Slitting machine got rejected, with a message ("every
	# machine either doesn't fit it or is already at capacity") that reads
	# like a real capacity shortage when the actual problem is a batch
	# missing its own width_mm. Unset/unknown input width should mean "no
	# constraint known" (0), matching _machine_feasible's own "unset field
	# => that check passes" rule everywhere else — never guessed from
	# output data that has no real relationship to the input roll's width.
	return {
		"input_width_mm": src_w,
		"output_widths_mm": widths,
		"output_length_m": max(lengths) if lengths else 0.0,
		"output_diameter_mm": flt(doc.get("roll_diameter_mm")),
		"core_diameter_mm": core_dia,
		"gsm": flt(outs[0].gsm) if outs else 0.0,
		"core_id": core,
		"box_type": (outs[0].packing_type if outs else "") or "",
		"adhesive_type": adhesive,
	}


def _stamp_machine_setup(machine_name, stage, spec):
	"""Record that `machine_name` is now set up for this stage's signature —
	the next matching run then incurs zero changeover in _assign_machine's ranking."""
	if machine_name and stage in _SIG_STAGES:
		frappe.db.set_value(
			"IB Machine", machine_name, "current_setup_sig",
			_setup_sig(stage, spec), update_modified=False,
		)


def _get_os_location(order_sheet):
	"""Return location string for machine matching by following Order Sheet → SO → custom_location."""
	so_name = frappe.db.get_value("IB Order Sheet", order_sheet, "sales_order")
	if not so_name:
		return None
	loc = frappe.db.get_value("Sales Order", so_name, "custom_location")
	return (loc or "").lower() or None


# ---------------------------------------------------------------------------
# 1. Dashboard
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_production_dashboard(location=None):
	"""Compat shim -> run model (production_run.get_production_kpis, same
	{summary, pipeline} shape). The old per-stage impl is incompatible with the
	WO=one-run schema on this branch."""
	from instabiz.overrides.production_run import get_production_kpis
	return get_production_kpis(location)


@frappe.whitelist()
def get_machines(machine_type=None, location=None):
	"""Return all machines, optionally filtered.

	Guard added 2026-08-10: uses frappe.get_all (ignore_permissions=True), so
	before this it was reachable directly via frappe.call by any authenticated
	user regardless of IB Machine's own doctype permissions -- harmless while
	IB Machine granted role "All" read=1 (items 120/134 correctly reasoned
	"leaks nothing beyond desk access"), but that reasoning broke the moment
	item 135 removed the "All" row: a plain Sales User (confirmed live,
	has_permission("IB Machine","read")==False) could still call this RPC and
	get every machine's capacity/wastage_norm_pct. The only real frontend
	caller (ib_production_dashboard.js) already only renders on a page gated
	to the same three roles below, so this closes the gap with zero UI impact.
	"""
	_require_production_role()
	filters = {}
	if machine_type:
		filters["machine_type"] = machine_type
	if location:
		filters["location"] = location

	machines = frappe.get_all(
		"IB Machine",
		filters=filters,
		fields=[
			"name",
			"machine_code",
			"machine_name",
			"machine_type",
			"location",
			"floor",
			"capacity",
			"capacity_uom",
			"wastage_norm_pct",
			"status",
			"notes",
		],
		order_by="machine_code asc",
	)

	return machines


@frappe.whitelist()
def save_machine(
	machine_code,
	machine_name,
	machine_type,
	location,
	capacity,
	wastage_norm_pct,
	status,
	capacity_uom="",
	notes=None,
	floor=None,
	name=None,  # ignored — machine_code IS the name (autoname = field:machine_code)
):
	"""Create or update IB Machine. Requires Factory Management or System Manager."""
	_require_production_role()
	exists = frappe.db.exists("IB Machine", machine_code)
	if exists:
		doc = frappe.get_doc("IB Machine", machine_code)
	else:
		doc = frappe.new_doc("IB Machine")
		doc.machine_code = machine_code

	doc.machine_name = machine_name
	doc.machine_type = machine_type
	doc.location = location
	doc.floor = floor or ""
	doc.capacity = flt(capacity)
	doc.capacity_uom = capacity_uom or ""
	doc.wastage_norm_pct = flt(wastage_norm_pct)
	doc.status = status
	doc.notes = notes or ""
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return doc.name


# ---------------------------------------------------------------------------
# 3. Order Sheets
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_order_sheets(status=None, priority=None, location=None, search=None):
	"""Return order sheets with progress %."""
	_require_production_role()
	filters = {}
	if status:
		filters["status"] = status
	if priority:
		filters["priority"] = priority
	if location:
		loc_sos = frappe.get_all("Sales Order", filters={"custom_location": location}, pluck="name")
		filters["sales_order"] = ["in", loc_sos or [""]]

	or_filters = None
	if search:
		like = f"%{search}%"
		or_filters = [["sales_order", "like", like], ["customer_name", "like", like]]

	sheets = frappe.get_all(
		"IB Order Sheet",
		filters=filters,
		or_filters=or_filters,
		fields=[
			"name",
			"sales_order",
			"customer",
			"order_date",
			"delivery_date",
			"priority",
			"status",
		],
		order_by="creation desc",
		# Safety ceiling — this was previously unbounded (full-table fetch every
		# call) while the Order-wise tab's own UI already paginates client-side
		# at 20/page; 467 Order Sheets already exist live, so this was a real,
		# already-active scale risk, not a hypothetical one.
		limit_page_length=500,
	)

	if not sheets:
		return []

	sheet_names = [s.name for s in sheets]
	placeholders = ", ".join(["%s"] * len(sheet_names))

	# Item counts (for the Items column — a real "how many line items" count,
	# unrelated to the progress fix below).
	item_counts = frappe.db.sql(
		f"""
		SELECT parent,
			COUNT(*) AS total_items,
			SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) AS completed_items
		FROM `tabIB Order Sheet Item`
		WHERE parent IN ({placeholders})
		GROUP BY parent
		""",
		tuple(sheet_names),
		as_dict=True,
	)
	count_map = {row.parent: row for row in item_counts}

	# Real bug, confirmed live: progress_pct used to be "how many whole
	# items are fully Completed" (0 of 1 = 0%) instead of "how far along is
	# the actual production" — a real order with one item 8/10 stages done
	# (one run finished, a second run 3/5 through) showed 0% on this list,
	# reading as if nothing had happened, while its own detail view (built
	# off the exact same run data, see get_order_sheet_detail/
	# _all_runs_for_osi) correctly showed 80%. Recomputed here on the same
	# basis as the detail view — stages done / stages total across every
	# non-cancelled run's route, for every item on the sheet — via one join
	# instead of walking runs per item per sheet (467 real Order Sheets
	# exist; an N+1 per-item route walk here would not scale).
	stage_counts = frappe.db.sql(
		f"""
		SELECT w.order_sheet AS parent,
			COUNT(rt.name) AS total_stages,
			SUM(CASE WHEN rt.done = 1 THEN 1 ELSE 0 END) AS done_stages
		FROM `tabIB Work Order` w
		JOIN `tabIB WO Route Stage` rt ON rt.parent = w.name
		WHERE w.order_sheet IN ({placeholders}) AND w.status != 'Cancelled'
		GROUP BY w.order_sheet
		""",
		tuple(sheet_names),
		as_dict=True,
	)
	stage_map = {row.parent: row for row in stage_counts}

	# Customer name from Customer master. Uses its OWN placeholder count — the
	# previous version reused `placeholders` (sized to len(sheet_names)) for a
	# tuple built from `[s.customer for s in sheets if s.customer]`, which is a
	# different length whenever any sheet has a blank customer, causing a SQL
	# parameter-count mismatch.
	customers = [s.customer for s in sheets if s.customer]
	if customers:
		customer_placeholders = ", ".join(["%s"] * len(customers))
		customer_names = frappe.db.sql(
			f"""
			SELECT name, customer_name FROM `tabCustomer`
			WHERE name IN ({customer_placeholders})
			""",
			tuple(customers),
			as_dict=True,
		)
	else:
		customer_names = []
	cname_map = {r.name: r.customer_name for r in customer_names}

	result = []
	for s in sheets:
		counts = count_map.get(s.name)
		total = counts.total_items if counts else 0
		stages = stage_map.get(s.name)
		stage_total = stages.total_stages if stages else 0
		stage_done = stages.done_stages if stages else 0
		progress_pct = round((flt(stage_done) / flt(stage_total) * 100), 1) if stage_total else 0.0
		result.append({
			"name": s.name,
			"sales_order": s.sales_order,
			"customer": s.customer,
			"customer_name": cname_map.get(s.customer, s.customer),
			"order_date": s.order_date,
			"delivery_date": s.delivery_date,
			"priority": s.priority,
			"status": s.status,
			"item_count": total,
			"progress_pct": progress_pct,
		})

	return result


@frappe.whitelist()
def create_order_sheet(sales_order, priority="Normal", notes=None):
	"""Create IB Order Sheet from Sales Order. Pulls items automatically."""
	_require_production_role()

	# Advisory lock prevents two concurrent requests from creating duplicate Order Sheets
	lock_name = f"IB-OS-{sales_order}"
	locked = frappe.db.sql("SELECT GET_LOCK(%s, 5)", lock_name)[0][0]
	if not locked:
		frappe.throw(_("Could not acquire lock for Order Sheet creation. Please try again."))

	# Everything below holds the advisory lock — release it on ANY exit path
	# (validation error, SO fetch failure, insert failure, WO auto-create failure),
	# not just the duplicate-check branch. Otherwise the lock leaks for the life
	# of the DB connection and blocks all future Order Sheet creation for this SO.
	try:
		# for_update=True: the GET_LOCK advisory lock above only serializes *when*
		# two callers' critical sections run — it does nothing about each caller's
		# own already-open REPEATABLE-READ transaction (MariaDB default here,
		# autocommit=0) still seeing a pre-lock snapshot that predates the other
		# caller's commit. A plain read here can return "no existing Order Sheet"
		# for both callers even though they're strictly serialized by the lock,
		# because InnoDB/MariaDB consistent reads under REPEATABLE READ ignore
		# what committed after the transaction's own snapshot was taken. FOR UPDATE
		# forces a locking read of the latest committed row instead of the stale
		# snapshot, closing that gap. Confirmed live: this exact race produced two
		# independent Order Sheets (each with its own full Work Order chain) for
		# one Sales Order when the on-submit background auto-create job
		# (_create_order_sheet_for_so) and an explicit create_order_sheet() call
		# landed close together — same failure class as the historical
		# IB-OS-2026-02038 duplicate-WO incident, one layer up (whole Order Sheet,
		# not just a stage WO).
		existing = frappe.db.get_value(
			"IB Order Sheet",
			{"sales_order": sales_order, "status": ["!=", "Cancelled"]},
			"name",
			for_update=True,
		)
		if existing:
			frappe.throw(
				_("An active Order Sheet ({0}) already exists for Sales Order {1}").format(existing, sales_order)
			)

		so = frappe.get_doc("Sales Order", sales_order)

		# custom_location is not a mandatory field on Sales Order — a blank value
		# used to silently fall through _get_stage_route() into the full Gujarat
		# factory route (Coating/Slitting/...) for any item whose item_group
		# matched a factory route, even though there's no way to know the order
		# is actually meant for Gujarat vs a warehouse-only location. Hard-block
		# instead of guessing (2026-08-10, user's explicit decision after this
		# was flagged across 3 earlier audits — see CLAUDE.md item 96/119/120).
		if not so.custom_location:
			frappe.throw(_(
				"Sales Order {0} has no Location set. Set Location on the Sales "
				"Order before creating its Order Sheet — Production stage routing "
				"depends on it."
			).format(sales_order))

		customer_name = frappe.db.get_value("Customer", so.customer, "customer_name") or so.customer

		doc = frappe.new_doc("IB Order Sheet")
		doc.sales_order = sales_order
		doc.customer = so.customer
		doc.customer_name = customer_name
		doc.order_date = so.transaction_date
		doc.delivery_date = so.delivery_date
		doc.priority = priority
		doc.status = "Draft"
		if notes:
			doc.notes = notes

		# Pull items from SO. sales_order_item captures the exact source Sales
		# Order Item row (item.name) — a Sales Order can carry the same
		# item_code on multiple separate lines with different quantities, so
		# custom_make_delivery_note() needs this to map back to precisely the
		# one row that's actually ready, not every row sharing that item_code.
		for item in so.items:
			doc.append("items", {
				"item_code": item.item_code,
				"item_name": item.item_name,
				"qty": item.qty,
				"uom": item.uom,
				"completed_qty": 0.0,
				"status": "Pending",
				"sales_order_item": item.name,
			})

		doc.insert(ignore_permissions=True)
		frappe.db.commit()

		# JIT stage model (2026-08-13, user's explicit decision): no Work Orders
		# are pre-created here anymore. auto_create_all_stage_wos() used to build
		# the whole route's WO chain upfront the moment an Order Sheet existed —
		# left in place, unused, same "dormant not deleted" precedent as the
		# Seat Map/Live Floor/Link Jumbo Roll removals (see production.py
		# history). Every item now starts with zero Work Orders; the first one
		# is created on demand by start_item_stage() when a production user
		# actually begins work on it and picks a stage. Order Sheet stays
		# "Draft" until then — start_item_stage() flips it to "In Progress".
		return doc.name
	finally:
		frappe.db.sql("SELECT RELEASE_LOCK(%s)", lock_name)


# ---------------------------------------------------------------------------
# 4. Stage Pipeline
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_stage_pipeline(location=None):
	"""Compat shim -> run model. Old Stage-wise tab expects
	{ <lower_stage>: [ run_row, ... ] }.

	`_stage_order` is an added reserved key (never a real stage name) giving
	the frontend the location-aware ordered stage-key list get_stage_board()
	now computes — without it, Stage-wise's pill row was hardcoded to always
	render all 5 canonical stages client-side even when the backend was
	already only returning warehouse-only locations' real single stage,
	leaving 4 permanently-dead pills defaulting to "Coating" (impossible at
	a warehouse) as the initially-active one.
	"""
	from instabiz.overrides.production_run import get_stage_board
	b = get_stage_board(location)
	out = {(k or "").lower().replace(" ", "_"): v for k, v in (b.get("board") or {}).items()}
	out["_stage_order"] = [(s or "").lower().replace(" ", "_") for s in (b.get("stages") or [])]
	return out


@frappe.whitelist()
def get_order_sheet_detail(order_sheet):
	"""Compat shim -> run model (production_run.get_order_sheet_detail)."""
	from instabiz.overrides.production_run import get_order_sheet_detail as _rd
	return _rd(order_sheet)


@frappe.whitelist()
def get_order_sheet_wo_names(order_sheet):
	"""Names of the ONE currently-actionable Work Order per item under an
	Order Sheet — for the Order-wise list's bulk "Print Job Order" action.

	Rewritten for the WO-per-run model (was still written against the old
	per-stage-WO JIT model: filtered IB Work Order by "order_sheet_item" and
	"stage" fields that no longer exist on this doctype — both confirmed
	orphaned pre-WO-per-run legacy DB columns, always NULL on every real
	modern Work Order, same bug class as get_dpr()/IB Production Report/
	get_machine_day_stats (all fixed 2026-09-13). Every real order's Print
	Job Order button has been silently printing nothing (this always
	returned an empty list) since the WO-per-run migration.

	Under this model an item has at most ONE current real run at a time
	(_latest_run_for_osi, same resolver get_order_sheet_detail() uses) — an
	item with no run yet (not started) or whose run already Completed has
	nothing to print; otherwise that one run's Work Order is the answer,
	no route-walking needed.
	"""
	_require_production_role()
	from instabiz.overrides.production_run import _latest_run_for_osi

	items = frappe.db.get_all(
		"IB Order Sheet Item",
		filters={"parent": order_sheet},
		fields=["name", "item_code", "sales_order_item"],
	)
	if not items:
		return []

	names = []
	for item in items:
		run = _latest_run_for_osi(item.sales_order_item, item.item_code, order_sheet)
		if run and run.status != "Completed":
			names.append(run.name)

	return names


_SUMMARY_STAGES = STAGES


@frappe.whitelist()
def get_order_sheet_stage_workflow(order_sheet):
	"""Per-item full stage routing for the "IB Job Order Summary" print format's
	stage x machine grid — one row per Order Sheet Item, one column per stage in
	_SUMMARY_STAGES, showing the real machine allotment (or lack of one) at every
	stage of that item's actual route (via _get_stage_route — route-aware, same
	helper get_order_sheet_wo_names()/auto_create_all_stage_wos() already use).

	Unlike get_order_sheet_wo_names() (which returns only the ONE currently-
	actionable WO per item), this returns the FULL route so the printed sheet
	can show completed / current / not-yet-reached / not-in-route honestly.
	JIT stage model (2026-08-13): a stage with no Work Order yet (never
	started) renders here with status=None/machine=None, same as any other
	not-yet-reached stage — real, expected data, not a gap to hide.

	Keyed by order_sheet_item (child row name), not bare item_code, so an item
	appearing on multiple rows of the same order sheet doesn't collide.

	Also carries each item's real dimension fields (color/width_mm/length_mtr/
	qty_pkg/total_pkg, from the underlying Sales Order Item) plus sheet-wide
	any_* flags — the print format uses these to show only the dimension
	columns that actually have data anywhere on the sheet (a SQMT roll item
	and a PCS packed item can sit on the same order sheet; each only fills in
	its own columns, the other's stay blank rather than adding a column no
	row on the sheet ever uses).
	"""
	_require_production_role()
	from instabiz.overrides.production_run import _latest_run_for_osi, _stage_map_for_run

	location = _get_os_location(order_sheet)
	sales_order = frappe.db.get_value("IB Order Sheet", order_sheet, "sales_order")
	items = frappe.db.get_all(
		"IB Order Sheet Item",
		filters={"parent": order_sheet},
		fields=["name", "item_code", "item_name", "qty", "uom", "sales_order_item",
		        "custom_brand", "custom_core", "custom_ctn", "custom_shrink_film",
		        "custom_no_of_logs", "custom_packing_type", "custom_size"],
	)

	any_color = any_width_mm = any_length_mtr = any_qty_pkg = any_total_pkg = False

	result = []
	for item in items:
		dims = frappe.db.get_value(
			"Sales Order Item",
			{"parent": sales_order, "item_code": item.item_code},
			["color", "width_mm", "length_mtr", "qty_pkg", "total_pkg"],
			as_dict=True,
		) if sales_order else None
		dims = dims or frappe._dict()
		any_color = any_color or bool(dims.color)
		any_width_mm = any_width_mm or bool(dims.width_mm)
		any_length_mtr = any_length_mtr or bool(dims.length_mtr)
		any_qty_pkg = any_qty_pkg or bool(dims.qty_pkg)
		any_total_pkg = any_total_pkg or bool(dims.total_pkg)

		# Rewritten for the WO-per-run model — was still filtering IB Work
		# Order by "order_sheet_item"/"stage", both orphaned pre-WO-per-run
		# legacy DB columns (always NULL on every real modern Work Order,
		# same bug class as get_dpr()/get_order_sheet_wo_names(), fixed
		# 2026-09-13) — every printed Job Order Summary has shown every
		# stage as "not yet reached", blank machine/operator, for every real
		# order, since the WO-per-run migration. An item has at most ONE
		# current real run (_latest_run_for_osi, same resolver
		# get_order_sheet_detail() already uses); its route + per-stage
		# status come from _stage_map_for_run (same helper), and per-stage
		# machine/operator come from the run's real IB WO Stage Event log
		# (the current, not-yet-completed stage has no event yet — falls
		# back to the run's live machine field, no operator recorded until
		# that stage actually completes).
		run = _latest_run_for_osi(item.sales_order_item, item.item_code, order_sheet)
		if run:
			smap, route = _stage_map_for_run(run)
			stage_route = [r.stage for r in route]
			events_by_stage = {
				e.stage: e for e in frappe.get_all(
					"IB WO Stage Event", filters={"parent": run.name, "skipped": 0},
					fields=["stage", "machine", "operator"],
				)
			}
			current_stage = run.current_stage
		else:
			stage_route = _get_stage_route(item.item_code, location)
			smap, events_by_stage, current_stage = {}, {}, None

		stages_out = []
		for stage in _SUMMARY_STAGES:
			if stage not in stage_route:
				stages_out.append({
					"stage": stage, "in_route": False, "machine": None,
					"status": None, "is_current": False,
				})
				continue
			info = smap.get(stage) or {}
			ev = events_by_stage.get(stage)
			is_current = stage == current_stage
			stages_out.append({
				"stage": stage,
				"in_route": True,
				"machine": (ev.machine if ev else None) or (run.machine if (run and is_current) else None),
				# get_fullname caches per-request (frappe.local.fullnames) so
				# resolving this per-stage/per-item doesn't turn into N+1 —
				# printed sheets should show a real name, not a raw user email.
				"operator": get_fullname(ev.operator) if (ev and ev.operator) else None,
				"status": info.get("status"),
				"is_current": is_current,
			})

		# pcs_to_make/logs_to_make (the old per-stage-WO manager-reconciliation
		# fields) are no longer written anywhere under the WO-per-run model
		# (confirmed: production_run.py hardcodes both to 0 at every call
		# site) — kept as 0 here too, consistent with the rest of the app
		# rather than reading a column that was never a real thing on this
		# doctype to begin with.
		pcs_to_make = 0
		logs_to_make = 0
		target_uom = (run.uom if run else None) or item.uom

		result.append({
			"item_code": item.item_code,
			"item_name": item.item_name,
			"qty": item.qty,
			"uom": item.uom,
			"target_uom": target_uom,
			"pcs_to_make": pcs_to_make,
			"logs_to_make": logs_to_make,
			"color": dims.color,
			"width_mm": dims.width_mm,
			"length_mtr": dims.length_mtr,
			"qty_pkg": dims.qty_pkg,
			"total_pkg": dims.total_pkg,
			"brand": item.custom_brand,
			"core": item.custom_core,
			"ctn": item.custom_ctn,
			"shrink_film": item.custom_shrink_film,
			"no_of_logs": item.custom_no_of_logs,
			"packing_type": item.custom_packing_type,
			"size": item.custom_size,
			"stages": stages_out,
		})

	return {
		"rows": result,
		"any_color": any_color,
		"any_width_mm": any_width_mm,
		"any_length_mtr": any_length_mtr,
		"any_qty_pkg": any_qty_pkg,
		"any_total_pkg": any_total_pkg,
	}


# ---------------------------------------------------------------------------
# 6. Work Order operations
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_order_dn_readiness(order_sheet):
	"""Whether every item in this Order Sheet has reached Completed at every
	stage — i.e. the whole Sales Order is actually ready to ship, not just
	the one item/WO the caller happens to be looking at.

	Reuses IB Order Sheet.status as the single source of truth: it's only
	ever set to "Completed" once every real Work Order for every item on
	the sheet is itself Completed (see _update_order_sheet_progress, fixed
	2026-08-05 to be symmetric/reliable). Powers the WO side panel's
	"Create Delivery Note" gate — previously that button appeared as soon
	as ONE item's own WO reached Completed at Ready to Deliver, letting a
	rep create a Delivery Note for a single item while the rest of the
	order was still mid-production.
	"""
	_require_production_role()
	if not order_sheet:
		return {"ready": False}
	status = frappe.db.get_value("IB Order Sheet", order_sheet, "status")
	return {"ready": status == "Completed"}


@frappe.whitelist()
def assign_machine(work_order, machine):
	"""Assign machine to work order (only if Pending)."""
	_require_production_role()
	# Advisory lock — same pattern as start_work_order/complete_work_order/etc.
	# Without it, two concurrent assign_machine calls on the same WO can both
	# pass the "is Pending" check before either write lands.
	lock_name = f"IB-WO-{work_order}"
	locked = frappe.db.sql("SELECT GET_LOCK(%s, 5)", lock_name)[0][0]
	if not locked:
		frappe.throw(_("Could not acquire lock for Work Order {0}. Please try again.").format(work_order))
	try:
		doc = frappe.get_doc("IB Work Order", work_order)
		if doc.status != "Pending":
			frappe.throw(_("Machine can only be assigned to a Pending work order. Current status: {0}").format(doc.status))
		machine_row = frappe.db.get_value("IB Machine", machine, ["machine_type", "capacity"], as_dict=True)
		if machine_row is None:
			frappe.throw(_("Machine {0} does not exist").format(machine))
		required_type = _STAGE_MACHINE_TYPE.get(doc.stage)
		if required_type and machine_row.machine_type != required_type:
			frappe.throw(
				_("Machine {0} is a {1} machine; Work Order stage {2} requires a {3} machine.").format(
					machine, machine_row.machine_type, doc.stage, required_type
				)
			)
		# Manual assignment previously had no capacity check at all — unlike
		# _assign_machine_load_balanced() (which only treats capacity as a soft
		# preference anyway), this is a hard block: a user explicitly picking a
		# machine should not be able to push it over its own configured capacity.
		cap = flt(machine_row.capacity)
		if cap > 0:
			current_load = frappe.db.count(
				"IB Work Order",
				filters={"machine": machine, "status": ["in", ("Pending", "In Progress")], "name": ["!=", work_order]},
			)
			if current_load >= cap:
				frappe.throw(
					_("Machine {0} is already at capacity ({1}/{2} active Work Orders).").format(
						machine, current_load, int(cap)
					)
				)
		doc.machine = machine
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		_notify_floor_update()
		return {"status": "ok", "machine": machine}
	finally:
		frappe.db.sql("SELECT RELEASE_LOCK(%s)", lock_name)


@frappe.whitelist()
def start_work_order(work_order):
	"""Transition status Pending/On Hold -> In Progress via the IB Work Order
	Workflow (action "Start"/"Resume"), record started_at."""
	_require_production_role()
	# Advisory lock prevents two concurrent calls (e.g. double-click, two tabs)
	# from both passing the status check before either write lands — same
	# pattern already used for Order Sheet creation.
	lock_name = f"IB-WO-{work_order}"
	locked = frappe.db.sql("SELECT GET_LOCK(%s, 5)", lock_name)[0][0]
	if not locked:
		frappe.throw(_("Could not acquire lock for Work Order {0}. Please try again.").format(work_order))
	try:
		doc = frappe.get_doc("IB Work Order", work_order)
		if doc.status == "In Progress":
			return {"status": "ok", "started_at": doc.started_at}
		if doc.status not in ("Pending", "On Hold"):
			frappe.throw(
				_("Work Order {0} cannot be started from status '{1}'. Expected: Pending or On Hold.").format(
					work_order, doc.status
				)
			)
		started_at = now()
		doc.started_at = started_at
		apply_workflow(doc, "Resume" if doc.status == "On Hold" else "Start")
		# Same fix as complete_work_order()/advance_to_next_stage(): apply_workflow's
		# internal load_from_db() discards the started_at set above before its own
		# doc.save(), so it must be persisted explicitly or it silently stays NULL.
		frappe.db.set_value("IB Work Order", doc.name, "started_at", started_at)
		frappe.db.commit()
		_notify_floor_update()
		return {"status": "ok", "started_at": started_at}
	finally:
		frappe.db.sql("SELECT RELEASE_LOCK(%s)", lock_name)


@frappe.whitelist()
def complete_work_order(work_order, actual_qty=None):
	"""Compat shim -> run model advance_run(). SEVERE bug this replaces,
	confirmed live: this used to be the pre-rewrite per-stage-WO
	implementation, still written against doc.item_code/doc.order_sheet_item/
	doc.completed_qty/doc.wastage_qty/doc.wastage_pct — none of which are
	real fields on IB Work Order anymore (confirmed against the doctype's
	own field list: only total_output_qty/total_wastage_qty exist at the
	parent level now, per-output qty lives on the `outputs` child table).
	This is the literal function the UI's "Complete" button calls
	(ib_production_dashboard.js's _update_wo_status method_map) to finish
	the LAST stage of every run — it returned {"status": "ok", ...} with NO
	error (doc.item_code is silently None, not a crash), flipped the run's
	own status to Completed, but current_stage never advanced past its last
	stage to "Done", the Order Sheet Item never flipped to Completed, no FG
	batch/serials were generated via the real path, and Create Delivery
	Note never became available — for every single order completed by
	clicking this button. Confirmed via a live disposable run: exactly this
	sequence reproduced. advance_run() already handles "this is the last
	stage" correctly (calls _finish_run internally) — same delegation
	pattern already used by advance_to_next_stage() for the non-final-stage
	case, applied here for the final-stage case too.
	"""
	from instabiz.overrides.production_run import advance_run
	r = advance_run(work_order, output_qty=actual_qty)
	r = dict(r or {})
	r["status"] = "ok" if r.pop("ok", False) else "error"
	return r


@frappe.whitelist()
def put_on_hold(work_order):
	"""Set status=On Hold."""
	_require_production_role()
	lock_name = f"IB-WO-{work_order}"
	locked = frappe.db.sql("SELECT GET_LOCK(%s, 5)", lock_name)[0][0]
	if not locked:
		frappe.throw(_("Could not acquire lock for Work Order {0}. Please try again.").format(work_order))
	try:
		doc = frappe.get_doc("IB Work Order", work_order)
		if doc.status == "On Hold":
			frappe.throw(_("Work Order {0} is already On Hold.").format(work_order))
		apply_workflow(doc, "Hold")
		_notify_production_hold(doc)
		frappe.db.commit()
		_notify_floor_update()
		return {"status": "ok"}
	finally:
		frappe.db.sql("SELECT RELEASE_LOCK(%s)", lock_name)


# ---------------------------------------------------------------------------
# 7. DPR (Daily Production Report)
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_dpr(date=None):
	"""Return daily production report data.

	Sourced entirely from IB Work Order completions. This report originally
	read from IB Production Entry — that doctype has zero rows system-wide
	by design (confirmed repeatedly: get_weekly_dpr's and
	get_machine_wise_dashboard's own comments, and complete_work_order()'s
	own docstring), so every branch below the old "if not entries" check was
	dead code that never once ran against real data.

	Wastage is deliberately absent from this report, not just zeroed out:
	IB Work Order.wastage_qty/wastage_pct are hardcoded 0.0 at WO creation
	(see auto_create_all_stage_wos) and never written by any real completion
	path — Production Entry submission was the only place that ever set them
	to something real, and it never fires. Showing "0% wastage, 0 above
	norm" would read as measured quality control that was never actually
	captured; better to not claim a number this system has never recorded.
	"""
	_require_production_role()
	if not date:
		date = today()

	# `IB Work Order.stage`/`.completed_qty`/`.target_uom` are orphaned
	# pre-WO-per-run legacy DB columns — confirmed via DESCRIBE and via real
	# data that they're NULL/0 on every Work Order created by the current
	# model's create_run() (production_run.py). Querying them here made this
	# whole report silently show "0 Unknown" for every real completion since
	# the WO-per-run migration — the underlying WOs/dates were correctly
	# selected, only the output figure and unit were structurally always
	# empty. Confirmed live: a real day with 2 genuine completions showed
	# "2 WOs completed, 0 UNKNOWN output".
	#
	# The real per-stage source is IB WO Stage Event (one row per stage
	# actually completed that day, with real input_qty/output_qty/
	# started_at/completed_at) — also the only place per-STAGE granularity
	# still exists at all under the WO-per-run model, since a completed run's
	# own current_stage is just "Done" once finished, with no memory of which
	# stage did what. UOM isn't tracked on the stage event itself (a stage
	# event describes the whole run's progress through one stage, not one
	# output item) — resolved via the run's first real output row, same
	# first-output approximation already used elsewhere on this page for a
	# multi-output run.
	rows = frappe.db.sql(
		"""
		SELECT e.stage AS stage, e.machine AS machine, e.output_qty AS completed_qty,
			COALESCE(fo.uom, 'Unknown') AS target_uom,
			TIMESTAMPDIFF(MINUTE, e.started_at, e.completed_at) AS duration_min
		FROM `tabIB WO Stage Event` e
		LEFT JOIN `tabIB WO Output` fo
			ON fo.parent = e.parent
			AND fo.idx = (SELECT MIN(idx) FROM `tabIB WO Output` WHERE parent = e.parent)
		WHERE e.skipped = 0 AND DATE(e.completed_at) = %s
		ORDER BY e.stage, e.machine
		""",
		(date,),
		as_dict=True,
	)

	# Output is kept broken down by UOM everywhere below, never blended into
	# one scalar — a Work Order's target_uom varies by item (PCS/SQMT/ROLL/KG
	# all occur), and summing e.g. "288 PCS + 2148 SQMT" into a bare "2436"
	# is not a real unit of anything. Every qty this function returns is
	# {uom, qty} pairs; a caller that wants one number still has to pick a
	# UOM, which is the point — there is no unit-agnostic "total output".
	summary_by_uom = {}
	for r in rows:
		uom = r.target_uom or "Unknown"
		summary_by_uom[uom] = summary_by_uom.get(uom, 0.0) + flt(r.completed_qty)

	summary = {
		"wo_completed": len(rows),
		"output_by_uom": [{"uom": u, "qty": q} for u, q in sorted(summary_by_uom.items())],
		"total_hours": round(sum(flt(r.duration_min) for r in rows if r.duration_min) / 60, 2),
	}

	if not rows:
		return {"date": date, "summary": summary, "stages": [], "machine_breakdown": {}}

	stage_data = {}
	for r in rows:
		stage = r.stage or "Unknown"
		uom = r.target_uom or "Unknown"
		sd = stage_data.setdefault(stage, {
			"stage": stage, "wo_completed": 0, "minutes": 0.0, "by_uom": {}, "machines": {},
		})
		sd["wo_completed"] += 1
		sd["minutes"] += flt(r.duration_min) if r.duration_min else 0.0
		su = sd["by_uom"].setdefault(uom, {"uom": uom, "wo_completed": 0, "output_qty": 0.0, "minutes": 0.0})
		su["wo_completed"] += 1
		su["output_qty"] += flt(r.completed_qty)
		su["minutes"] += flt(r.duration_min) if r.duration_min else 0.0

		mkey = r.machine or "Unassigned"
		m = sd["machines"].setdefault(mkey, {"machine": mkey, "wo_completed": 0, "by_uom": {}})
		m["wo_completed"] += 1
		mu = m["by_uom"].setdefault(uom, {"uom": uom, "output_qty": 0.0})
		mu["output_qty"] += flt(r.completed_qty)

	ordered_stages = [s for s in STAGES if s in stage_data] + [s for s in stage_data if s not in STAGES]
	stage_table = []
	machine_breakdown = {}
	for stage in ordered_stages:
		sd = stage_data[stage]
		hours = round(sd["minutes"] / 60, 2)
		output = []
		for uom in sorted(sd["by_uom"]):
			su = sd["by_uom"][uom]
			su_hours = round(su["minutes"] / 60, 2)
			output.append({
				"uom": uom,
				"output_qty": su["output_qty"],
				"hourly_avg": round(su["output_qty"] / su_hours, 2) if su_hours else 0.0,
			})
		machines = []
		for m in sd["machines"].values():
			machines.append({
				"machine": m["machine"],
				"wo_completed": m["wo_completed"],
				"output": sorted(m["by_uom"].values(), key=lambda x: x["uom"]),
			})
		stage_table.append({
			"stage": stage,
			"wo_completed": sd["wo_completed"],
			"hours": hours,
			"output": output,
			"machines": machines,
		})
		machine_breakdown[stage] = machines

	return {
		"date": date,
		"stages": stage_table,
		"summary": summary,
		"machine_breakdown": machine_breakdown,
	}


@frappe.whitelist()
def get_weekly_dpr(week_start=None, date=None):
	"""Return 7-day production summary. `date` is an alias for `week_start` (JS sends `date`).

	Sourced from IB WO Stage Event, not IB Work Order.completed_qty/
	target_uom — see get_dpr()'s docstring: those columns are orphaned
	pre-WO-per-run legacy fields, always NULL/0 on every real modern WO, so
	this silently showed "0 Unknown" output for every real completion since
	the WO-per-run migration despite correctly finding the right WOs/dates.
	"""
	_require_production_role()
	if not week_start:
		week_start = date or today()
		today_dt = getdate(week_start)
		week_start = add_days(today_dt, -today_dt.weekday())
	else:
		week_start = getdate(week_start)

	week_end = add_days(week_start, 6)

	# Grouped by day AND uom — same reasoning as get_dpr(): a bare
	# SUM(output_qty) across rows of different UOMs (PCS/SQMT/ROLL/...)
	# isn't a real quantity of anything, so output is always kept as
	# {uom, qty} pairs, never blended into one number. UOM resolved via the
	# run's first real output row — a stage event describes the whole run's
	# progress through one stage, not one output item, so it carries no uom
	# of its own (same first-output approximation get_dpr() uses).
	wo_rows = frappe.db.sql(
		"""
		SELECT DATE(e.completed_at) AS day,
			COALESCE(fo.uom, 'Unknown') AS uom,
			COUNT(*) AS wo_completed,
			SUM(e.output_qty) AS output_qty,
			SUM(TIMESTAMPDIFF(MINUTE, e.started_at, e.completed_at)) AS total_minutes
		FROM `tabIB WO Stage Event` e
		LEFT JOIN `tabIB WO Output` fo
			ON fo.parent = e.parent
			AND fo.idx = (SELECT MIN(idx) FROM `tabIB WO Output` WHERE parent = e.parent)
		WHERE e.skipped = 0 AND DATE(e.completed_at) BETWEEN %s AND %s
		GROUP BY DATE(e.completed_at), COALESCE(fo.uom, 'Unknown')
		""",
		(week_start, week_end),
		as_dict=True,
	)
	day_map = {}
	for r in wo_rows:
		d = day_map.setdefault(str(r.day), {"wo_completed": 0, "minutes": 0.0, "by_uom": []})
		d["wo_completed"] += r.wo_completed
		d["minutes"] += flt(r.total_minutes)
		d["by_uom"].append({"uom": r.uom, "qty": flt(r.output_qty)})

	result = []
	for i in range(7):
		day = add_days(week_start, i)
		day_str = str(day)
		dr = day_map.get(day_str)
		result.append({
			"date": day_str,
			"wo_completed": dr["wo_completed"] if dr else 0,
			"output_by_uom": sorted(dr["by_uom"], key=lambda x: x["uom"]) if dr else [],
			"hours": round(dr["minutes"] / 60, 2) if dr else 0.0,
		})

	total_by_uom = {}
	for d in result:
		for o in d["output_by_uom"]:
			total_by_uom[o["uom"]] = total_by_uom.get(o["uom"], 0.0) + o["qty"]
	days_with_data = sum(1 for d in result if d["wo_completed"] > 0)
	avg_daily_by_uom = [
		{"uom": u, "qty": round(q / days_with_data, 1)} for u, q in sorted(total_by_uom.items())
	] if days_with_data else []

	return {
		"week_start": str(week_start),
		"week_end": str(week_end),
		"summary": {
			"output_by_uom": [{"uom": u, "qty": q} for u, q in sorted(total_by_uom.items())],
			"avg_daily_by_uom": avg_daily_by_uom,
		},
		"days": result,
	}


# ---------------------------------------------------------------------------
# Helpers (not whitelisted)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def advance_to_next_stage(work_order, actual_qty=None):
	"""Compat shim -> run model advance_run. Returns the old
	{status:'ok', next_stage, message} the dashboard JS checks."""
	from instabiz.overrides.production_run import advance_run
	r = advance_run(work_order, output_qty=actual_qty)
	r = dict(r or {})
	r["status"] = "ok" if r.pop("ok", False) else "error"
	return r


def _serial_stamp():
	return nowdate().replace("-", "")[2:]  # YYMMDD


def _next_serial_seq(item_code, stamp):
	prefix = f"{item_code}::{stamp}::"
	last = frappe.db.sql(
		"SELECT name FROM `tabIB FG Serial` WHERE name LIKE %s ORDER BY name DESC LIMIT 1",
		prefix + "%",
	)
	if not last:
		return 1
	try:
		return int(last[0][0].rsplit("::", 1)[-1]) + 1
	except (ValueError, IndexError):
		return 1


# bulk_wo_action() (mass Start/Next Stage across a checkbox selection)
# removed 2026-08-13 along with its frontend UI — the mass-select bulk
# feature was dropped as part of making the JIT stage picker (start_item_stage)
# the single way to start/move a Work Order (user's explicit decision, same
# session as the RTD/Delivered stage-model collapse). No other caller ever
# existed for it.


# Backward-compat alias used by older callers


@frappe.whitelist()
def get_production_plan(limit=None, start=0, location=None, search=None, priority=None):
	"""Compat shim -> run model get_run_plan (same {order_wise:[...]} shape)."""
	from instabiz.overrides.production_run import get_run_plan
	return get_run_plan(limit=limit, start=start, location=location, search=search, priority=priority)


@frappe.whitelist()
def hold_work_order(work_order):
	"""Alias for put_on_hold — called by the production stages JS."""
	return put_on_hold(work_order)


@frappe.whitelist()
def cancel_work_order(work_order, reason=None):
	"""Compat shim -> run model cancel_run(). Was fully built (locking,
	batch-qty restore, genealogy reversal) but had zero UI entry point —
	no button anywhere ever called it. Wired here so the WO panel's "More
	actions" menu can reach it."""
	from instabiz.overrides.production_run import cancel_run
	r = cancel_run(work_order, reason=reason)
	r = dict(r or {})
	r["status"] = "ok" if r.pop("ok", False) else "error"
	return r


@frappe.whitelist()
def skip_work_order_stage(work_order, reason=None):
	"""Compat shim -> run model skip_stage(). Same bug class as cancel_run:
	fully built (logs a real skipped=1 stage_log row — distinct from
	move_work_order_stage's blunt "move it anywhere" escape hatch — reassigns
	machine for the next stage, correctly finishes the run if it was the
	last one) but had zero UI entry point. Wired here so the WO panel's
	"More actions" menu can reach it."""
	from instabiz.overrides.production_run import skip_stage
	r = skip_stage(work_order, reason=reason)
	r = dict(r or {})
	r["status"] = "ok" if r.pop("ok", False) else "error"
	return r


@frappe.whitelist()
def assign_machine_to_wo(work_order, machine):
	"""Alias for assign_machine — called by the production stages JS."""
	return assign_machine(work_order, machine)


@frappe.whitelist()
def get_item_wise_view(from_date=None, to_date=None, item_code=None, location=None):
	"""Compat shim -> run model. Old Item-wise render wants one entry per output
	SKU with a `.work_orders` array (one pseudo-row per route stage: done ->
	Completed, current -> the run's status, future -> Pending).

	`location` was silently dropped here (never in this function's own
	signature, and the frontend never sent it either) — the Stages page's
	shared location filter looked like it applied everywhere, but Item-wise
	always showed every location's items regardless of the picker. Every
	sibling tab (Order-wise/Stage-wise/Machine-wise) already threads its own
	location arg through; this brings Item-wise in line.
	"""
	from instabiz.overrides.production_run import get_item_wise_board
	rows = get_item_wise_board(location=location, item_code=item_code)
	bucket = {}
	for r in rows:
		key = (r["item_code"], r["work_order"])
		if key in bucket:
			continue
		bucket[key] = r
	grouped = {}
	for (ic, _wo), r in bucket.items():
		g = grouped.setdefault(ic, {
			"item_code": ic, "item_name": r["item_name"], "uom": r["uom"],
			"work_orders": [], "orders": set(),
		})
		g["orders"].add(r["sales_order"])
		cur = r.get("current_stage")
		for st in (r.get("route") or []):
			if isinstance(st, dict):
				stage_name, done = st.get("stage"), bool(st.get("done"))
			else:
				stage_name, done = st, False
			if done:
				status = "Completed"
			elif stage_name == cur:
				status = r.get("status") or "In Progress"
			else:
				status = "Pending"
			g["work_orders"].append({
				"name": r["work_order"], "stage": stage_name, "status": status,
				"customer_name": r.get("customer") or "",
				"sales_order": r.get("sales_order"),
				"target_qty": r.get("planned_qty"), "completed_qty": r.get("produced_qty"),
				"machine": "", "target_uom": r.get("uom"),
			})
	out = []
	for g in grouped.values():
		g["order_count"] = len(g.pop("orders"))
		done = sum(1 for w in g["work_orders"] if w["status"] == "Completed")
		g["total_wos"] = len(g["work_orders"]) or 1
		g["completed_wos"] = done
		g["route_length"] = g["total_wos"]
		g["route_completed_count"] = done
		g["completion_pct"] = round(done / g["total_wos"] * 100, 1)
		out.append(g)
	return out


@frappe.whitelist()
def _get_available_hours_per_day(shift_hours=None):
	"""Planned available hours/day, used as the Utilization/OEE Availability denominator.

	IB Machine has no machine-to-shift link field at all (confirmed: zero
	Custom Fields on IB Machine, and no "shift" fieldname in its own JSON) —
	so there is no clean per-machine Shift Type join to query. Falls back to
	the real "Factory Shift" Shift Type's actual start_time/end_time span
	(08:00-20:00 = 12h in this site's data, verified live) as the
	standardized single-shift default for the whole factory floor. Callers
	(report filter / dashboard) may override via shift_hours.
	"""
	if shift_hours:
		return flt(shift_hours)
	row = frappe.db.get_value(
		"Shift Type", "Factory Shift", ["start_time", "end_time"], as_dict=True
	)
	if row and row.start_time is not None and row.end_time is not None:
		start = row.start_time.total_seconds() if hasattr(row.start_time, "total_seconds") else flt(row.start_time)
		end = row.end_time.total_seconds() if hasattr(row.end_time, "total_seconds") else flt(row.end_time)
		span = (end - start) / 3600.0
		if span <= 0:
			span += 24  # overnight-wrapping shift (e.g. Night: 22:00-06:00)
		if span > 0:
			return round(span, 2)
	return 8.0  # last-resort constant if the "Factory Shift" master is ever removed/misconfigured


def _capacity_per_hour(capacity, capacity_uom, available_hours):
	"""Normalize IB Machine.capacity to a per-hour rate.

	Returns None when capacity/capacity_uom is unset — many real machines have
	this blank (confirmed via prior audit + live query), and callers must
	treat None as "no data", never silently divide by / default to 0.
	"""
	if not capacity or not capacity_uom:
		return None
	if capacity_uom == "ctn/shift":
		return flt(capacity) / available_hours if available_hours else None
	# sqm/hour, rolls/hour, pcs/hour, kg/hour are already per-hour rates.
	return flt(capacity)


def compute_oee(run_hours, output_qty, avg_wastage_pct, wo_count, capacity, capacity_uom, available_hours):
	"""Pure calc: Availability x Performance x Quality for one machine on one day/window.

	Deliberately takes plain pre-aggregated numbers (no frappe.db calls, no
	doc objects) so it's directly unit-testable, and shared by
	get_machine_wise_dashboard()'s "today" per-machine stats via
	get_machine_day_stats() below — one formula, not scattered copies that
	can drift. (The Machine Utilization report that originally motivated
	pulling this out into its own reusable function was removed
	2026-08-30 at user's request — this helper stayed, still load-bearing
	for the live dashboard.)

	Grain: whatever the caller aggregated to (this app uses machine-per-day
	both places). Formulas, and why they're shaped this way given the real
	live data as of 2026-08-10 (verified via console before writing this):

	Availability = run_hours (real SUM(completed_at - started_at) across
	  Completed WOs in the window — the same field get_dpr()/
	  get_weekly_dpr() already trust) / available_hours, capped at 100%.
	  NOTE: in the live dataset, WOs are completed 0-67s after being started
	  (avg 5.8s across all 30 Completed WOs, verified live) because
	  production is still in a testing phase (CLAUDE.md item 96) — floor
	  users aren't yet leaving WOs "In Progress" for real durations. This
	  formula is correct and will self-correct automatically as real usage
	  matures; today it reads low for every machine, which honestly reflects
	  the current data-capture-maturity gap rather than a bug here (same
	  class of gap already flagged for wastage_pct in this file, see below).

	Performance = ideal hours to produce output_qty at the machine's rated
	  capacity, divided by run_hours, capped at 100% (standard OEE
	  convention — exceeding 100% just means the rate assumption/capacity
	  master is off, not that the machine outran physics; given run_hours is
	  currently tiny per the note above, the raw ratio is often far above
	  100% before capping). None when capacity/capacity_uom is unset on the
	  Machine (many real machines have this blank) or run_hours is 0.

	Quality = 1 - avg_wastage_pct/100. IB Work Order.wastage_qty/wastage_pct
	  are hardcoded 0.0 at WO creation and never written by any real
	  completion path system-wide (confirmed via grep + live query: 0/30
	  Completed WOs have nonzero wastage) — the exact gap get_dpr() already
	  documents and deliberately omits wastage for. Reported as None
	  ("no data") rather than a false 100%/perfect-quality reading, matching
	  that precedent, until a real wastage-capture flow exists. Known
	  limitation: a genuinely zero-wastage day would also read as "no data"
	  under this heuristic (there's no separate "measured" flag on the WO to
	  disambiguate) — acceptable today since no capture path ever writes a
	  real value at all yet; revisit if that ever changes.

	OEE = Availability x Performance x Quality, only when all three are
	  available; otherwise None.
	"""
	availability_pct = None
	if available_hours:
		availability_pct = round(min(100.0, flt(run_hours) / available_hours * 100), 1)

	capacity_per_hour = _capacity_per_hour(capacity, capacity_uom, available_hours)
	performance_pct = None
	if capacity_per_hour and flt(run_hours) > 0:
		ideal_hours = flt(output_qty) / capacity_per_hour
		performance_pct = round(min(100.0, ideal_hours / flt(run_hours) * 100), 1)

	quality_pct = None
	if wo_count and flt(avg_wastage_pct) > 0:
		quality_pct = round(100 - flt(avg_wastage_pct), 1)

	oee_pct = None
	if availability_pct is not None and performance_pct is not None and quality_pct is not None:
		oee_pct = round((availability_pct / 100) * (performance_pct / 100) * (quality_pct / 100) * 100, 1)

	return {
		"run_hours": round(flt(run_hours), 2),
		"available_hours": available_hours,
		"availability_pct": availability_pct,
		"performance_pct": performance_pct,
		"quality_pct": quality_pct,
		"oee_pct": oee_pct,
	}


def get_machine_day_stats(machine_names, from_date, to_date=None):
	"""Per-machine per-day production stats from real IB Work Order completions —
	powers get_machine_wise_dashboard()'s "today" per-machine stats (one call
	for every active machine). Takes a real from_date/to_date range (not just
	"today") because it originally also fed the since-removed Machine
	Utilization / OEE report — kept range-capable since it costs nothing and
	get_machine_wise_dashboard() itself just always passes today for both.

	Grain: one row per (machine, day) that machine had >=1 Completed WO. A
	(machine, day) with zero completions simply has no row — callers treat a
	missing key as zero activity, not an error (same convention DPR/weekly DPR
	already use for empty days).

	Grouped by DATE(COALESCE(completed_at, modified)) — matches
	get_machine_wise_dashboard()'s pre-existing "today" query, which already
	fell back to modified for a Completed WO somehow missing completed_at.
	run_hours itself is still computed from the raw started_at/completed_at
	pair (SQL SUM ignores NULL rather than erroring), so a WO missing either
	timestamp contributes 0 run_hours but still counts toward output_qty/
	wo_count for that day.
	"""
	to_date = to_date or from_date
	if not machine_names:
		return []
	# Sourced from IB WO Stage Event, not IB Work Order.completed_qty/
	# wastage_pct directly — those are orphaned pre-WO-per-run legacy
	# columns, confirmed NULL/0 on every real modern Work Order (same root
	# cause as get_dpr()/IB Production Report, fixed 2026-09-13) — this
	# query's WHERE clause always matched real completions, but output_qty
	# summed to 0 every time regardless of real floor output, silently
	# capping every machine's OEE/yield/output card at "0 output" since the
	# WO-per-run migration. wastage_pct stays unmeasured (never written by
	# any real completion path, same as DPR's own reasoning) — averaging a
	# column that's always 0 correctly yields 0, not wrong, just not a real
	# measurement; left as-is rather than expanding this fix's scope.
	return frappe.db.sql(
		"""
		SELECT
			e.machine AS machine,
			DATE(e.completed_at) AS prod_date,
			COALESCE(SUM(TIMESTAMPDIFF(SECOND, e.started_at, e.completed_at)), 0) / 3600.0 AS run_hours,
			COALESCE(SUM(e.output_qty), 0) AS output_qty,
			COALESCE(AVG(wo.wastage_pct), 0) AS avg_wastage_pct,
			COUNT(*) AS wo_count
		FROM `tabIB WO Stage Event` e
		JOIN `tabIB Work Order` wo ON wo.name = e.parent
		WHERE e.machine IN %(machines)s
		  AND e.skipped = 0
		  AND DATE(e.completed_at) BETWEEN %(from_date)s AND %(to_date)s
		GROUP BY e.machine, DATE(e.completed_at)
		""",
		{"machines": list(machine_names), "from_date": from_date, "to_date": to_date},
		as_dict=True,
	)


@frappe.whitelist()
def get_machine_wise_dashboard(location=None, floor=None):
	"""Machine-wise dashboard: per machine — current WOs, today stats, load %.

	location: optional (maharashtra/gujarat/chennai) — matches the shared
	Location filter already honored by Order-wise/Job Bundles on this page;
	previously ignored here so switching locations silently kept showing
	every machine regardless of tab.

	floor: optional (Link -> IB Production Floor). Gujarat is the only
	location with real floors configured today (item 145) — this tab is
	where floor scoping is cheapest and most correct, since IB Machine
	carries `floor` directly with no join needed, unlike a WO-grain view
	where floor only exists via whichever machine (if any) got assigned.
	"""
	_require_production_role()
	machine_filters = {"status": "Active"}
	if location:
		machine_filters["location"] = location
	if floor:
		machine_filters["floor"] = floor
	machines = frappe.db.get_all(
		"IB Machine",
		filters=machine_filters,
		fields=["name", "machine_code", "machine_name", "machine_type",
		        "location", "floor", "capacity", "capacity_uom", "wastage_norm_pct"],
		order_by="machine_type asc, machine_code asc",
	)

	today_date = today()
	available_hours = _get_available_hours_per_day()
	# Batched once for every machine on the page (was previously one SQL query
	# per machine inside the loop below — an N+1 fixed as a side effect of
	# wiring in the shared OEE stats function; see get_machine_day_stats()).
	machine_names = [m.name for m in machines]
	day_stats_by_machine = {
		row.machine: row for row in get_machine_day_stats(machine_names, today_date, today_date)
	}
	result = []
	for m in machines:
		current_wos = frappe.db.get_all(
			"IB Work Order",
			filters={"machine": m.name, "status": ["in", ["Pending", "In Progress"]]},
			fields=["name", "current_stage", "status", "total_output_qty",
			        "order_sheet", "source_batch", "started_at", "priority", "creation"],
			order_by="started_at asc",
		)
		# IB Work Order stopped carrying item_code/item_name/stage/target_qty/
		# completed_qty/jumbo_roll directly once the WO-per-run rewrite landed
		# (a run's finished SKUs live on its `outputs` child table, can be more
		# than one — Shape A, same item_code at different dims). Those old
		# columns are still physically in the DB (never dropped) and always
		# NULL/0 for a real run, so the query above never errors — it just
		# silently returns nothing useful, which is what left this tab's Item
		# column blank. Aliased onto the same key names the frontend already
		# reads (wo.item_code/item_name/stage/target_qty/completed_qty/
		# target_uom) rather than rewriting the JS's field names too.
		wo_names = [wo.name for wo in current_wos]
		outputs_by_wo = {}
		if wo_names:
			for o in frappe.db.get_all(
				"IB WO Output",
				filters={"parent": ["in", wo_names]},
				fields=["parent", "item_code", "item_name", "planned_qty", "uom"],
				order_by="parent asc, idx asc",
			):
				outputs_by_wo.setdefault(o.parent, []).append(o)
		for wo in current_wos:
			outs = outputs_by_wo.get(wo.name) or []
			wo["stage"] = wo.get("current_stage")
			wo["completed_qty"] = flt(wo.get("total_output_qty"))
			wo["target_qty"] = sum(flt(o.planned_qty) for o in outs)
			if len(outs) == 1:
				wo["item_code"] = outs[0].item_code
				wo["item_name"] = outs[0].item_name
			elif outs:
				wo["item_code"] = "{0} +{1} more".format(outs[0].item_code, len(outs) - 1)
				wo["item_name"] = "{0} item(s)".format(len(outs))
			wo["target_uom"] = outs[0].uom if outs else None
		# WOs on one machine can belong to different orders (no single shared
		# parent ETD like the order-scoped views have), so fetch each WO's own
		# Order Sheet delivery_date + customer here. Also carries customer_name
		# for the Machine-wise tab's WO table (added 2026-08-05 — that table
		# previously showed item_code only, with no customer column, unlike
		# every other WO table on this page).
		os_names = list({wo.order_sheet for wo in current_wos if wo.order_sheet})
		os_map = {}
		if os_names:
			os_map = {
				d.name: d
				for d in frappe.get_all(
					"IB Order Sheet",
					filters={"name": ["in", os_names]},
					fields=["name", "delivery_date", "customer", "customer_name", "sales_order"],
				)
			}
		for wo in current_wos:
			os_row = os_map.get(wo.order_sheet)
			wo["delivery_date"] = os_row.delivery_date if os_row else None
			wo["customer_name"] = (os_row.customer_name or os_row.customer) if os_row else None
			# sales_order wasn't selected on the WO itself here (unlike every
			# other WO-listing view on this page) — needed so the WO panel can
			# show which SO this machine's queued/running WO belongs to.
			wo["sales_order"] = os_row.sales_order if os_row else None

		# Today's stats from IB Work Order directly — NOT tabIB Production Entry,
		# which has zero rows ever (same fallback pattern already used by
		# get_production_dashboard()'s wastage_today: that table is unused by
		# design, real completions live on the WO itself). completed_qty/
		# completed_at are now reliably persisted by complete_work_order()/
		# advance_to_next_stage() (see fix alongside this one — apply_workflow's
		# internal load_from_db() was silently discarding them).
		stats = day_stats_by_machine.get(m.name) or {}
		avg_wastage = round(flt(stats.get("avg_wastage_pct")), 1)
		# Yield = the good-output fraction, the inverse of wastage — no other
		# "yield" definition exists anywhere else in this codebase (grepped).
		# NOTE: wastage_pct is never actually computed/written anywhere on IB
		# Work Order outside its 0.0 default at creation (create_work_orders_for_item) —
		# there is no capture flow that records real wastage per WO (same
		# unused-IB-Production-Entry gap noted above, one level deeper: even if
		# a real entry existed, nothing copies it onto the WO). So today_avg_wastage
		# and today_yield_pct are structurally correct but will read 0% / 100%
		# for every machine until a real wastage-capture flow is built — this is
		# a data-capture gap, not a bug in this query.
		yield_pct = round(100 - avg_wastage, 1)

		active_load = sum(1 for wo in current_wos if wo.status == "In Progress")
		# load_pct: each machine handles 1 WO at a time; >1 active = overloaded
		load_pct = min(200.0, round(active_load * 100.0, 1))

		# OEE (Availability x Performance x Quality) for today, computed live
		# from the same stats row — never persisted onto IB Machine/Work Order,
		# so it can't drift from source data (see compute_oee()'s own docstring
		# for the exact formulas + why each leg reads the way it does on this
		# app's real, still-testing-phase data). Rides along on this same
		# frappe.call the Machine-wise tab already re-fires on every
		# "ib_floor_update" realtime event (_notify_floor_update(), fired from
		# every Start/Complete/Hold/Advance) — no separate polling needed.
		oee = compute_oee(
			run_hours=stats.get("run_hours") or 0,
			output_qty=stats.get("output_qty") or 0,
			avg_wastage_pct=stats.get("avg_wastage_pct") or 0,
			wo_count=stats.get("wo_count") or 0,
			capacity=m.capacity,
			capacity_uom=m.capacity_uom,
			available_hours=available_hours,
		)

		result.append({
			**dict(m),
			"current_wos": [dict(wo) for wo in current_wos],
			"today_output": flt(stats.get("output_qty")),
			"today_avg_wastage": avg_wastage,
			"today_yield_pct": yield_pct,
			"active_load": active_load,
			"load_pct": load_pct,
			"today_run_hours": oee["run_hours"],
			"today_available_hours": oee["available_hours"],
			"today_availability_pct": oee["availability_pct"],
			"today_performance_pct": oee["performance_pct"],
			"today_quality_pct": oee["quality_pct"],
			"today_oee_pct": oee["oee_pct"],
		})

	return result


def _priority_from_delivery_date(delivery_date):
	"""Derive Order Sheet priority from delivery urgency (days remaining from today)."""
	if not delivery_date:
		return "Normal"
	days = (getdate(delivery_date) - getdate(today())).days
	if days <= 2:
		return "Urgent"
	if days <= 5:
		return "High"
	if days <= 10:
		return "Normal"
	return "Low"


def on_so_submit_create_order_sheet(doc, method=None):
	"""Sales Order on_submit doc_event: enqueue Order Sheet auto-creation.

	Runs in the background (after commit) rather than inline — create_order_sheet()
	does its own frappe.db.commit() and can throw (lock timeout, duplicate guard),
	neither of which should be coupled to the Sales Order's own submit transaction
	or ever block a sales user from submitting an SO.
	"""
	frappe.enqueue(
		"instabiz.overrides.production._create_order_sheet_for_so",
		queue="short",
		enqueue_after_commit=True,
		sales_order=doc.name,
	)


def _create_order_sheet_for_so(sales_order):
	"""Background job: create the Order Sheet (+ full WO chain) for one just-submitted SO."""
	# Runs as the submitting user (frappe.enqueue captures frappe.session.user) — that
	# user is typically a Sales role, not Factory Management, so _require_production_role()
	# would reject it. Elevate to Administrator, same as the old nightly scheduler did.
	frappe.set_user("Administrator")
	try:
		if frappe.db.exists(
			"IB Order Sheet", {"sales_order": sales_order, "status": ["!=", "Cancelled"]}
		):
			return
		delivery_date = frappe.db.get_value("Sales Order", sales_order, "delivery_date")
		priority = _priority_from_delivery_date(delivery_date)
		create_order_sheet(sales_order, priority=priority)
	except Exception:
		frappe.log_error(
			title=f"Production Auto-Create (on-submit): {sales_order}",
			message=frappe.get_traceback(),
		)


@frappe.whitelist()
def get_so_production_status(sales_order):
	"""Return full production status for a Sales Order.

	Shows per-item: route, current stage, completed stages, machine assignments.
	Used by the production dashboard SO-drill-down and the SO-form panel.
	"""
	_check_so_production_access(sales_order)
	os_name = frappe.db.get_value(
		"IB Order Sheet",
		{"sales_order": sales_order, "status": ["!=", "Cancelled"]},
		"name",
	)
	if not os_name:
		return {"has_order_sheet": False, "sales_order": sales_order}

	os_doc = frappe.get_doc("IB Order Sheet", os_name)
	location = frappe.db.get_value("Sales Order", sales_order, "custom_location")
	items_out = []

	# feature/wo-per-run: production is now one IB Work Order = one run, with a
	# `route` child (stages + .done) and `outputs` children carrying the source
	# Sales Order Item row. Build each Order Sheet Item's stage timeline from the
	# run(s) that produce it — matched by outputs.sales_order_item (exact), with
	# an item_code fallback for any run whose output row didn't capture it.
	runs = frappe.db.get_all(
		"IB Work Order",
		filters={"order_sheet": os_name, "status": ["!=", "Cancelled"]},
		fields=["name", "status", "current_stage", "machine", "started_at", "completed_at"],
	)
	run_map = {r.name: r for r in runs}
	runs_by_soi = {}
	runs_by_item = {}
	if runs:
		for o in frappe.db.get_all(
			"IB WO Output",
			filters={"parent": ["in", list(run_map)]},
			fields=["parent", "item_code", "sales_order_item"],
		):
			if o.sales_order_item:
				runs_by_soi.setdefault(o.sales_order_item, set()).add(o.parent)
			runs_by_item.setdefault(o.item_code, set()).add(o.parent)
	route_rows = {}
	if runs:
		for r in frappe.db.get_all(
			"IB WO Route Stage",
			filters={"parent": ["in", list(run_map)]},
			fields=["parent", "stage", "sequence", "done"],
		):
			route_rows.setdefault(r.parent, []).append(r)

	for item in os_doc.items:
		stage_route = _get_stage_route(item.item_code, location)
		my_runs = list(runs_by_soi.get(item.sales_order_item) or runs_by_item.get(item.item_code) or [])

		# collate route .done + which run is currently at each stage
		done_stages, active = set(), {}
		for rn in my_runs:
			run = run_map[rn]
			for rr in route_rows.get(rn, []):
				if rr.done:
					done_stages.add(rr.stage)
			if run.current_stage and run.current_stage not in ("Done", "Cancelled"):
				active[run.current_stage] = run

		stages_out = []
		current_stage = None
		for stage in stage_route:
			run = active.get(stage)
			if stage in done_stages and not run:
				status = "Completed"
			elif run:
				status = run.status
			elif my_runs:
				status = "Pending"
			else:
				status = "Not Created"
			stages_out.append({
				"stage":        stage,
				"wo_name":      run.name if run else None,
				"status":       status,
				"machine":      run.machine if run else None,
				"target_qty":   flt(item.qty),
				"completed_qty": 0,
				"wastage_pct":  0,
				"started_at":   run.started_at if run else None,
				"completed_at": run.completed_at if run else None,
			})
			if status in ("Pending", "In Progress", "On Hold") and not current_stage:
				current_stage = stage

		completion_pct = 0.0
		completed_count = sum(1 for s in stages_out if s["status"] == "Completed")
		if stage_route:
			completion_pct = round(completed_count / len(stage_route) * 100, 1)

		items_out.append({
			"item_code":      item.item_code,
			"item_name":      item.item_name,
			"qty":            flt(item.qty),
			"uom":            item.uom,
			"current_stage":  current_stage,
			"completion_pct": completion_pct,
			"stages":         stages_out,
		})

	return {
		"has_order_sheet": True,
		"sales_order":     sales_order,
		"order_sheet":     os_name,
		"priority":        os_doc.priority,
		"status":          os_doc.status,
		"delivery_date":   str(os_doc.delivery_date) if os_doc.delivery_date else None,
		"items":           items_out,
	}


def mark_wos_delivered(doc, method=None):
	"""Delivery Note on_submit doc_event: notify the sales person once the
	whole Sales Order's dispatch status reaches "Delivered".

	RTD/Delivered collapsed out of the stage model entirely (2026-08-13,
	user's explicit decision) — Packing is the real last Work Order stage
	now (nothing is physically manufactured at "Ready to Deliver", it was a
	manual click with no work behind it), and there is no more WO to
	transition here. "Delivered" is now purely a derived status read from
	the Delivery Note itself via _get_dispatch_info() (the same function
	already powering the SO form panel and list badges — single source of
	truth, not reimplemented here) — reflects the WHOLE order, not just this
	one DN, since a Sales Order can ship across more than one DN and isn't
	really "Delivered" until every item has gone out. Fires once per Sales
	Order via a marker (same dedup pattern as the progress-milestone
	notifier) so re-submitting/cancel-amend cycles on later DNs against an
	already-delivered order don't repeat it. Never throws — must not block a
	real Delivery Note submission if something here is unexpected.
	"""
	try:
		sales_orders = {row.against_sales_order for row in doc.items if row.against_sales_order}
		for so_name in sales_orders:
			dispatch = _get_dispatch_info(so_name)
			if dispatch.get("status") != "Delivered":
				continue

			sales_person_user = frappe.db.get_value("Sales Order", so_name, "custom_sales_person_user")
			if not sales_person_user:
				continue

			marker = f"[ib-delivered-{so_name}]"
			if frappe.db.exists("Notification Log", {"for_user": sales_person_user, "subject": ["like", f"%{marker}%"]}):
				continue

			customer = frappe.db.get_value("Sales Order", so_name, "customer_name") or ""
			frappe.get_doc({
				"doctype": "Notification Log",
				"subject": f"Order Delivered: {so_name} {marker}"[:140],
				"email_content": (
					f"<p>Sales Order <strong>{so_name}</strong> for <strong>{customer}</strong> "
					f"has been <strong>Delivered</strong>.</p>"
				),
				"for_user": sales_person_user,
				"type": "Alert",
				"document_type": "Sales Order",
				"document_name": so_name,
				"from_user": "Administrator",
			}).insert(ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		frappe.log_error(
			title=f"mark_wos_delivered: {doc.name}",
			message=frappe.get_traceback(),
		)


# ── Sales Order production panel ──────────────────────────────────────────────

@frappe.whitelist()
def get_so_production_panel(sales_order):
	"""Production stage progress + dispatch status for SO form panel."""
	result = get_so_production_status(sales_order)
	result["dispatch"] = _get_dispatch_info(sales_order)

	if result.get("has_order_sheet"):
		items = result.get("items", [])

		# Overall order-level pct/stage/risk — same numbers the Production
		# Tracker page shows, so the SO form and the tracker never disagree.
		overall_pct, overall_stage = _order_progress_summary(result["order_sheet"], items)
		result["overall_pct"] = overall_pct
		result["overall_current_stage"] = overall_stage
		# "Ready to Deliver" is derived from production being 100% done
		# (RTD/Delivered collapsed out of the stage model, 2026-08-13 —
		# Packing is the real last stage now), not a per-item WO stage
		# string that no longer exists. Matches get_order_dn_readiness's
		# own OS-status-Completed gate. "Delivered" overrides it once a real
		# Delivery Note has actually been submitted — _order_progress_summary
		# itself has no DN visibility (called from the hot milestone-notify
		# path too, kept cheap/pure-production), so the more authoritative
		# dispatch signal already fetched above takes precedence here.
		result["ready_to_deliver"] = overall_pct >= 100
		if result["dispatch"]["status"] == "Delivered":
			result["overall_current_stage"] = "Delivered"
		if result.get("delivery_date"):
			days_left = date_diff(getdate(result["delivery_date"]), getdate(today()))
			result["days_left"] = days_left
			if days_left < 0 and overall_pct < 100:
				result["risk"] = "overdue"
			elif days_left <= 2 and overall_pct < 100:
				result["risk"] = "at-risk"
			else:
				result["risk"] = "on-track"
		else:
			result["days_left"] = None
			result["risk"] = "none"
	else:
		result["ready_to_deliver"] = False

	return result


# ── Sales-facing Production Tracker ───────────────────────────────────────────

def _order_progress_summary(os_name, items):
	"""Aggregate per-item stage entries (from get_so_production_status) into one
	order-level pct + current stage, for the tracker list view."""
	total_steps = 0
	completed_steps = 0
	active_stages = []
	for item in items:
		stages = item.get("stages", [])
		total_steps += len(stages)
		completed_steps += sum(1 for s in stages if s["status"] == "Completed")
		if item.get("current_stage"):
			active_stages.append(item["current_stage"])

	pct = round(completed_steps / total_steps * 100, 1) if total_steps else 0.0
	# "Current stage" for the whole order = the earliest stage among items still
	# in progress (the bottleneck) — matches how a sales person would ask
	# "what's holding this order up".
	current_stage = None
	if active_stages:
		order_idx = {s: i for i, s in enumerate(STAGES)}
		current_stage = min(active_stages, key=lambda s: order_idx.get(s, 999))
	elif pct >= 100:
		current_stage = "Ready to Deliver"
	return pct, current_stage


@frappe.whitelist()
def get_my_production_orders(sales_person_user=None, show_completed=0):
	"""In-flight Sales Orders with a production progress summary, for the sales-
	facing Production Tracker page. Non-privileged users always see only their
	own orders regardless of sales_person_user; Sales Manager/System Manager/
	production roles may pass sales_person_user to view a specific rep, or
	omit it to see everyone.
	"""
	from instabiz.overrides.permissions import _is_privileged
	privileged = _is_privileged(frappe.session.user) or bool(_PRODUCTION_ROLES & set(frappe.get_roles()))
	target_user = frappe.session.user if not privileged else sales_person_user

	show_completed = int(show_completed or 0)
	conditions = ["os.status != 'Cancelled'", "so.docstatus = 1"]
	params = {}
	if target_user:
		conditions.append("so.custom_sales_person_user = %(user)s")
		params["user"] = target_user
	if not show_completed:
		conditions.append("os.status != 'Completed'")

	order_sheets = frappe.db.sql(f"""
		SELECT os.name AS order_sheet, os.sales_order, os.priority, os.status,
		       os.delivery_date, so.customer, so.customer_name,
		       so.custom_sales_person_user, so.custom_sales_person
		FROM `tabIB Order Sheet` os
		JOIN `tabSales Order` so ON so.name = os.sales_order
		WHERE {" AND ".join(conditions)}
		ORDER BY os.delivery_date ASC
	""", params, as_dict=True)

	today_date = getdate(today())
	out = []
	for row in order_sheets:
		# _so_progress_pct re-derives the order sheet by sales_order — cheap
		# enough at this scale and keeps one single source of truth for the
		# pct/stage math shared with the milestone notifier.
		pct, current_stage, _os_name = _so_progress_pct(row.sales_order)
		item_count = frappe.db.count("IB Order Sheet Item", {"parent": row.order_sheet})

		days_left = date_diff(row.delivery_date, today_date) if row.delivery_date else None
		if days_left is None:
			risk = "none"
		elif days_left < 0 and pct < 100:
			risk = "overdue"
		elif days_left <= 2 and pct < 100:
			risk = "at-risk"
		else:
			risk = "on-track"

		out.append({
			"sales_order": row.sales_order,
			"order_sheet": row.order_sheet,
			"customer": row.customer_name or row.customer,
			"sales_person": row.custom_sales_person or row.custom_sales_person_user,
			"priority": row.priority,
			"os_status": row.status,
			"delivery_date": str(row.delivery_date) if row.delivery_date else None,
			"days_left": days_left,
			"risk": risk,
			"pct": pct,
			"current_stage": current_stage,
			"item_count": item_count,
		})

	return out


@frappe.whitelist()
def get_so_production_timeline(sales_order):
	"""Full per-item stage timeline for one Sales Order — drill-down behind
	get_my_production_orders(). Reuses get_so_production_status's own access
	check (rep/owner/Sales Manager/System Manager/production role)."""
	return get_so_production_status(sales_order)


def _get_dispatch_info(sales_order):
	"""Return dispatch status from linked Delivery Notes."""
	dns = frappe.db.sql("""
		SELECT DISTINCT dn.name, dn.status, dn.posting_date,
		       dn.custom_lr_number, dn.lr_no, dn.transporter_name, dn.vehicle_no
		FROM `tabDelivery Note` dn
		JOIN `tabDelivery Note Item` dni ON dni.parent = dn.name
		WHERE dn.docstatus = 1 AND dni.against_sales_order = %s
		ORDER BY dn.posting_date DESC
		LIMIT 5
	""", (sales_order,), as_dict=True)

	if not dns:
		return {"status": "Not Dispatched", "dns": []}

	latest = dns[0]
	lr = latest.get("custom_lr_number") or latest.get("lr_no") or ""

	si_exists = frappe.db.sql("""
		SELECT 1 FROM `tabSales Invoice` si
		JOIN `tabSales Invoice Item` sii ON sii.parent = si.name
		WHERE si.docstatus = 1 AND sii.sales_order = %s LIMIT 1
	""", (sales_order,))

	if si_exists or latest.status == "Completed":
		dispatch_status = "Delivered"
	elif lr:
		dispatch_status = "In Transit"
	else:
		dispatch_status = "Dispatched"

	return {
		"status": dispatch_status,
		"latest_dn": latest.name,
		"lr_number": lr,
		"transporter": latest.transporter_name or "",
		"vehicle": latest.vehicle_no or "",
		"posting_date": str(latest.posting_date) if latest.posting_date else None,
		"dns": [dict(dn) for dn in dns],
	}


@frappe.whitelist()
def get_so_list_badges(sales_orders):
	"""Batch fetch production + dispatch badge for a list of SO names.

	Called from the Sales Order list view with whatever rows are already
	visible there (already scoped by the standard Sales Order row-level
	permission — see sales_order_has_permission in overrides/permissions.py).
	A direct API caller could otherwise pass arbitrary SO names to peek at
	other reps' dispatch/production badges, so re-check per name here rather
	than trusting the caller's list — same has_permission hook the SO
	list/doctype itself already uses, just applied explicitly since this is a
	raw-SQL endpoint that would otherwise bypass it.
	"""
	if isinstance(sales_orders, str):
		sales_orders = json.loads(sales_orders)
	if not sales_orders:
		return {}

	sales_orders = [so for so in sales_orders if frappe.has_permission("Sales Order", "read", so)]
	if not sales_orders:
		return {}

	ph = ", ".join(["%s"] * len(sales_orders))
	t = tuple(sales_orders)

	os_rows = frappe.db.sql(
		f"SELECT sales_order, name, status FROM `tabIB Order Sheet` WHERE sales_order IN ({ph}) AND status != 'Cancelled'",
		t, as_dict=True,
	)
	os_map = {r.sales_order: r for r in os_rows}

	dn_rows = frappe.db.sql(f"""
		SELECT DISTINCT dni.against_sales_order AS so, dn.name, dn.status,
		       dn.custom_lr_number, dn.lr_no
		FROM `tabDelivery Note` dn
		JOIN `tabDelivery Note Item` dni ON dni.parent = dn.name
		WHERE dn.docstatus = 1 AND dni.against_sales_order IN ({ph})
		ORDER BY dn.posting_date DESC
	""", t, as_dict=True)
	dn_map = {}
	for r in dn_rows:
		if r.so not in dn_map:
			dn_map[r.so] = r

	# "Ready to Deliver" is derived from IB Order Sheet.status == "Completed"
	# (set once every item's real last stage — Packing — is Completed, see
	# _update_order_sheet_progress) — not a WO stage query. Used to check for
	# a WO with stage='Ready to Deliver', but RTD/Delivered were collapsed
	# out of the stage model entirely 2026-08-13; that query now permanently
	# returns zero rows, which would have silently frozen every SO's badge
	# at "In Production" forever once production actually finished. Caught
	# before it shipped broken, not after — same os_map already fetched
	# above already carries the exact signal needed.

	result = {}
	for so in sales_orders:
		os = os_map.get(so)
		dn = dn_map.get(so)

		if dn:
			lr = dn.custom_lr_number or dn.lr_no or ""
			if dn.status == "Completed":
				badge, color = "Delivered", "#059669"
			elif lr:
				badge, color = "In Transit", "#0891b2"
			else:
				badge, color = "Dispatched", "#2563eb"
		elif os and os.status == "Completed":
			badge, color = "Ready to Deliver", "#ea580c"
		elif os:
			badge, color = "In Production", "#7c3aed"
		else:
			badge, color = "Not Started", "#9ca3af"

		result[so] = {"badge": badge, "color": color}

	return result


def _notify_floor_update():
	"""Fire on every WO status/machine-assignment change so any open Production
	page Stages tab live-refreshes across terminals (ib_production_dashboard.js's
	IBProductionStages._start_live_updates — merged into that file 2026-08-05,
	formerly its own ib_production_stages.js). Originally added for the
	since-removed Seat Map/Live Floor UI, but the event itself is a separate,
	still-active cross-terminal refresh mechanism — do not remove without also
	removing that listener."""
	frappe.publish_realtime("ib_floor_update", {}, after_commit=True)


# ── Production progress notifications (doc event) ────────────────────────────

def _so_progress_pct(so_name):
	"""Return (pct, current_stage, order_sheet_name) for a Sales Order's active
	Order Sheet, or (None, None, None) if it has none.

	feature/wo-per-run: delegates to production_run._so_progress, which reads the
	new one-Work-Order-per-run shape (route .done flags across the order's runs).
	Lazy import — production_run imports helpers from this module.
	"""
	from instabiz.overrides.production_run import _so_progress
	return _so_progress(so_name)


_PROGRESS_MILESTONES = [25, 50, 75, 100]


@frappe.whitelist()
def update_production_qty(work_order, pcs_to_make=None, logs_to_make=None):
	"""Factory manager reconciliation: set pcs_to_make / logs_to_make on a WO to
	account for wastage and plan how many pieces/logs to actually make from the
	target qty. Simple field update — IB Work Order is not submittable, so no
	need for a full doc.save() cycle here."""
	_require_production_role()
	wo_row = frappe.db.get_value("IB Work Order", work_order, ["status"], as_dict=True)
	if wo_row is None:
		frappe.throw(_("Work Order {0} not found").format(work_order))
	# IB Work Order.target_uom is an orphaned pre-WO-per-run legacy column,
	# always NULL on every real modern Work Order (same bug class fixed
	# elsewhere in this file 2026-09-13) — since neither "None != PCS" nor
	# "None != SQMT" is ever false, the validation two blocks down always
	# threw, unconditionally, for every real WO regardless of its actual
	# unit. Adjust Qty has been 100% non-functional since the WO-per-run
	# migration. Resolved from the run's real first output row instead
	# (same first-output approximation this page's other tabs already use).
	target_uom = frappe.db.get_value(
		"IB WO Output", {"parent": work_order},
		"uom", order_by="idx asc",
	)

	# Reconciling wastage/efficiency only makes sense before the item has
	# actually shipped — once Delivered (or Cancelled), the qty is history,
	# not something to plan against. Previously had no status check at all:
	# pcs_to_make/logs_to_make could be silently edited on an already-shipped
	# WO after the fact, which is meaningless and could misrepresent a
	# Job Order that's already been printed and handed to the customer.
	if wo_row.status in ("Completed", "Cancelled"):
		frappe.throw(_(
			"Work Order {0} is {1} — quantity reconciliation no longer applies once a Work Order has shipped or been cancelled."
		).format(work_order, wo_row.status))

	values = {}
	if pcs_to_make is not None and pcs_to_make != "":
		values["pcs_to_make"] = int(pcs_to_make)
	if logs_to_make is not None and logs_to_make != "":
		values["logs_to_make"] = int(logs_to_make)

	if not values:
		frappe.throw(_("Provide at least one of pcs_to_make or logs_to_make"))

	# pcs_to_make only means anything against a PCS-target WO, logs_to_make only
	# against SQMT — was previously accepted with no check at all (confirmed live:
	# logs_to_make silently stored on a PCS WO), which prints/reports garbage since
	# nothing else in the code re-derives which field is the "real" one from
	# target_uom itself.
	if "pcs_to_make" in values and target_uom != "PCS":
		frappe.throw(_("This Work Order's UOM is {0}, not PCS — pcs_to_make does not apply").format(target_uom))
	if "logs_to_make" in values and target_uom != "SQMT":
		frappe.throw(_("This Work Order's UOM is {0}, not SQMT — logs_to_make does not apply").format(target_uom))

	# Was previously silently accepting negative values (confirmed live: -5 and
	# -100 both persisted with no error) — a negative pieces/logs count is never
	# meaningful here and prints garbage onto the Job Order ("Pieces to Make: -5").
	for field, val in values.items():
		if val < 0:
			frappe.throw(_("{0} cannot be negative").format(field))

	frappe.db.set_value("IB Work Order", work_order, values)
	frappe.db.commit()

	return frappe.db.get_value(
		"IB Work Order", work_order, ["pcs_to_make", "logs_to_make"], as_dict=True
	)


def _notify_production_hold(doc):
	"""Alert the sales person when one of their order's items goes On Hold —
	a real delivery-delay risk they'd otherwise only discover by asking."""
	if not doc.order_sheet:
		return
	so_name = frappe.db.get_value("IB Order Sheet", doc.order_sheet, "sales_order")
	if not so_name:
		return
	sales_person_user = frappe.db.get_value("Sales Order", so_name, "custom_sales_person_user")
	if not sales_person_user:
		return

	marker = f"[ib-prod-hold-{doc.name}]"
	if frappe.db.exists("Notification Log", {"for_user": sales_person_user, "subject": ["like", f"%{marker}%"]}):
		return

	customer = frappe.db.get_value("Sales Order", so_name, "customer_name") or ""
	notes = frappe.utils.escape_html(doc.notes) if doc.notes else ""
	frappe.get_doc({
		"doctype": "Notification Log",
		"subject": f"Production Paused: {so_name} — {doc.stage} on hold {marker}"[:140],
		"email_content": (
			f"<p>Sales Order <strong>{so_name}</strong> for <strong>{customer}</strong> "
			f"has been placed <strong>On Hold</strong> at the <strong>{doc.stage}</strong> stage."
			f"{f' Note: {notes}' if notes else ''} This may affect the delivery date.</p>"
		),
		"for_user": sales_person_user,
		"type": "Alert",
		"document_type": "Sales Order",
		"document_name": so_name,
		"from_user": "Administrator",
	}).insert(ignore_permissions=True)

