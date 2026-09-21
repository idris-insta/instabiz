"""instabiz.overrides.production_run

Work-Order-per-run production lifecycle (feature/wo-per-run, Phase 1).

One `IB Work Order` = one production run, cradle to grave: one raw-material
`IB Batch` in, a `route` of stages it passes through, one or more finished
`outputs`, a `stage_log` of what actually happened at each stage, and — at the
end — an FG `IB Batch` + `IB FG Serial` per unit for genealogy.

Phase 1 scope: create / advance / skip / hold / resume / finish (FG batch +
serials) / cancel, plus the read APIs the Production Dashboard consumes via
production.py's compat shims (`get_production_kpis`, `get_stage_board`,
`get_item_wise_board`). An earlier native read-API layer meant to be
called directly (`get_run_list`/`get_run_detail`/`get_run_panel`/
`get_machine_board`/`get_route_for_item`/`get_order_sheet_runs_context`/
`get_dpr`/`get_weekly_dpr`) was superseded by the compat-shim approach —
the frontend was adapted to the old response shape rather than rebuilt —
and removed as dead code, zero callers anywhere in the app.

NOT in Phase 1: the Repack Stock Entry (ledger movement) — that is Phase 3,
behind the `ib_production_posts_stock` site_config flag. `_finish_run` here
creates the genealogy layer only, exactly like the old `_generate_fg_serials`.
"""
from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.model.workflow import apply_workflow
from frappe.utils import cint, flt, now, nowdate, today, getdate, add_days, date_diff, get_fullname

from instabiz.overrides.production import (
	STAGES,
	_STAGE_MACHINE_TYPE,
	_WAREHOUSE_ONLY_LOCATIONS,
	_WAREHOUSE_STAGE_ROUTE,
	_assign_machine_load_balanced,
	_assign_machine,
	_spec_from_run,
	_setup_sig,
	_stamp_machine_setup,
	_check_so_production_access,
	_get_stage_route,
	_notify_floor_update,
	_notify_production_hold,
	_priority_from_delivery_date,
	_require_production_role,
	_serial_stamp,
	_next_serial_seq,
)

_PRIORITY_RANK = {"Urgent": 0, "High": 1, "Normal": 2, "Low": 3}
_LIVE_STATUSES = ("Pending", "In Progress", "On Hold")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _wf(doc, action, then=None):
	"""Single choke point for workflow transitions.

	`apply_workflow()` reloads the doc from DB and discards every in-memory
	change (scalar AND child tables) — so callers MUST `doc.save()` first.
	`then` is a dict of scalar fields to force-persist right after, for the
	handful apply_workflow's own reload+save would otherwise leave stale.
	"""
	apply_workflow(doc, action)
	if then:
		frappe.db.set_value(doc.doctype, doc.name, then, update_modified=False)


def _parse(val):
	if isinstance(val, str):
		try:
			return json.loads(val)
		except (ValueError, TypeError):
			return val
	return val


def _run_location(doc):
	"""Lowercase location for this run (machine matching / route rules)."""
	loc = doc.get("location")
	if not loc and doc.get("sales_order"):
		loc = frappe.db.get_value("Sales Order", doc.sales_order, "custom_location")
	if not loc and doc.get("order_sheet"):
		so = frappe.db.get_value("IB Order Sheet", doc.order_sheet, "sales_order")
		if so:
			loc = frappe.db.get_value("Sales Order", so, "custom_location")
	return (loc or "").lower() or None


def _route_stages(doc):
	"""Ordered list of stage names on the run's route child table."""
	return [r.stage for r in sorted(doc.route or [], key=lambda r: cint(r.sequence))]


def _next_stage_after(doc, stage):
	seq = _route_stages(doc)
	try:
		i = seq.index(stage)
	except ValueError:
		return None
	return seq[i + 1] if i + 1 < len(seq) else None


def _prev_output_qty(doc):
	"""Input qty for the run's current stage = the last real (non-skipped) stage
	event's output, else the run's source qty (or Σ planned output)."""
	for ev in reversed(doc.stage_log or []):
		if not ev.skipped:
			return flt(ev.output_qty)
	if flt(doc.source_qty):
		return flt(doc.source_qty)
	return sum(flt(o.planned_qty) for o in (doc.outputs or []))


def _mark_route_done(doc, stage):
	for r in doc.route or []:
		if r.stage == stage:
			r.done = 1


def _batch_source_warehouse(batch_name):
	"""Where the RM sits — the batch's own `warehouse` field (snapshotted at
	receipt time, Phase 3) when set, else derived from the container / GRN
	it came from (batches created before that field existed)."""
	b = frappe.db.get_value(
		"IB Batch", batch_name, ["warehouse", "container_import", "purchase_receipt"], as_dict=True
	) or {}
	if b.get("warehouse"):
		return b.warehouse
	if b.get("container_import"):
		return frappe.db.get_value("IB Container Import", b.container_import, "warehouse")
	if b.get("purchase_receipt"):
		return frappe.db.get_value("Purchase Receipt", b.purchase_receipt, "set_warehouse")
	return None


def _validate_route(stages, location):
	"""stages: ordered list of stage names. Returns cleaned list or throws."""
	stages = [s for s in (stages or []) if s]
	if not stages:
		frappe.throw(_("A run needs at least one route stage."))
	bad = [s for s in stages if s not in STAGES]
	if bad:
		frappe.throw(_("Unknown production stage(s): {0}").format(", ".join(bad)))
	if (location or "").lower() in _WAREHOUSE_ONLY_LOCATIONS:
		off = [s for s in stages if s not in _WAREHOUSE_STAGE_ROUTE]
		if off:
			frappe.throw(_(
				"{0} is a warehouse-only location — only {1} can run there, not {2}."
			).format(location, ", ".join(_WAREHOUSE_STAGE_ROUTE), ", ".join(off)))
	return stages


# ---------------------------------------------------------------------------
# route lookup (Start dialog)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_osi_context(order_sheet_item):
	"""Server-side lookup for the Start Production dialog — the client can't
	read `IB Order Sheet Item` (an istable) directly (PermissionError, even for
	Administrator). Returns the parent Order Sheet + row basics + route."""
	_require_production_role()
	row = frappe.db.get_value(
		"IB Order Sheet Item", order_sheet_item,
		["name", "parent", "item_code", "item_name", "qty", "uom", "sales_order_item"],
		as_dict=True,
	)
	if not row:
		frappe.throw(_("Order Sheet Item {0} not found").format(order_sheet_item))
	location = _run_location(frappe._dict({"order_sheet": row.parent}))
	dims = frappe.db.get_value(
		"Item", row.item_code, ["width_mm", "length_mtr", "gsm"], as_dict=True
	) or {}
	return {
		"order_sheet": row.parent,
		"order_sheet_item": row.name,
		"sales_order_item": row.sales_order_item,
		"item_code": row.item_code,
		"item_name": row.item_name,
		"qty": flt(row.qty),
		"uom": row.uom,
		"width_mm": flt(dims.get("width_mm")),
		"length_mtr": flt(dims.get("length_mtr")),
		"gsm": flt(dims.get("gsm")),
		"route": _get_stage_route(row.item_code, location),
		"location": location,
	}


@frappe.whitelist()
def get_osi_context_batch(order_sheet_items):
	"""Batched get_osi_context — one query for N rows instead of N round trips.

	Real bug this exists to fix: the Start Run dialog (_ibStartRunDialog in
	ib_production_dashboard.js) only ever resolved sales_order_item/dims/route
	for the FIRST selected item via a single get_osi_context call, merging the
	result onto items[0] only — every other item in a multi-item bulk start
	(2+ dimension-variants of one SKU, or the Order-wise "Start All Items"
	button) silently reached create_run with sales_order_item missing.
	create_run defaults a missing sales_order_item to "" on the IB WO Output
	row, and _settle_order_sheet's completion check filters out falsy
	sales_order_item entirely — so those items' Order Sheet Item rows could
	never flip to Completed no matter how many real stages actually finished,
	permanently blocking the whole order's Create Delivery Note gate (which
	requires every item Completed). Confirmed live on real data: IB-WO-2026-25500
	(7 outputs, all stages genuinely Completed) had sales_order_item set on
	only 1 of 7 IB WO Output rows — items[0], exactly matching this bug.
	"""
	_require_production_role()
	names = _parse(order_sheet_items) or []
	if not names:
		return {}
	rows = frappe.get_all(
		"IB Order Sheet Item",
		filters={"name": ["in", names]},
		fields=["name", "parent", "item_code", "item_name", "qty", "uom", "sales_order_item"],
	)
	out = {}
	for row in rows:
		location = _run_location(frappe._dict({"order_sheet": row.parent}))
		dims = frappe.db.get_value(
			"Item", row.item_code, ["width_mm", "length_mtr", "gsm"], as_dict=True
		) or {}
		out[row.name] = {
			"order_sheet": row.parent,
			"order_sheet_item": row.name,
			"sales_order_item": row.sales_order_item,
			"item_code": row.item_code,
			"item_name": row.item_name,
			"qty": flt(row.qty),
			"uom": row.uom,
			"width_mm": flt(dims.get("width_mm")),
			"length_mtr": flt(dims.get("length_mtr")),
			"gsm": flt(dims.get("gsm")),
			"route": _get_stage_route(row.item_code, location),
		}
	return out


@frappe.whitelist()
def propose_runs(order_sheet, source_batches):
	"""Bin-pack an Order Sheet's not-yet-produced lines onto slitting passes.

	For each picked RM batch: take the OS lines whose finished item shares that
	batch's RM item, sort widest-first, greedily fill passes where
	  Σ widths ≤ batch_width − TRIM  AND  line count ≤ slitter knife positions.
	Each pass = one proposed run (its lines become `outputs`). The operator can
	merge / split / re-assign a jumbo before confirming — this is a suggestion.
	"""
	_require_production_role()
	from instabiz.overrides.production import _ASSUMED_TRIM_MM
	source_batches = _parse(source_batches) or []
	if isinstance(source_batches, str):
		source_batches = [source_batches]

	os_doc = frappe.get_doc("IB Order Sheet", order_sheet)
	location = _run_location(frappe._dict({"order_sheet": order_sheet}))

	# knife positions: max across active slitters (0 = no limit known)
	knives = frappe.db.sql(
		"""SELECT COALESCE(MAX(knife_positions), 0) FROM `tabIB Machine`
		   WHERE machine_type='Slitting' AND status='Active'"""
	)[0][0] or 0

	proposals = []
	for b in source_batches:
		bat = frappe.db.get_value("IB Batch", b, ["name", "item", "qty", "width_mm"], as_dict=True)
		if not bat:
			continue
		usable = flt(bat.width_mm) - _ASSUMED_TRIM_MM if flt(bat.width_mm) else 0

		lines = []
		for it in os_doc.items:
			if frappe.db.get_value("IB WO Output",
			                       {"sales_order_item": it.sales_order_item, "docstatus": ["<", 2]}, "name"):
				continue  # already in a run
			# finished -> RM via IB Production Recipe (if one exists for this item)
			rm = frappe.db.get_value("IB Production Recipe", {"finished_item": it.item_code}, "recipe_item")
			if rm and rm != bat.item:
				continue
			dims = frappe.db.get_value("Sales Order Item", it.sales_order_item,
			                           ["width_mm", "length_mtr"], as_dict=True) or {}
			im = frappe.db.get_value("Item", it.item_code,
			                         ["width_mm", "length_mtr", "gsm", "stock_uom"], as_dict=True) or {}
			lines.append({
				"order_sheet_item": it.name,
				"sales_order_item": it.sales_order_item,
				"item_code": it.item_code,
				"item_name": it.item_name,
				"planned_qty": flt(it.qty),
				"uom": it.uom or im.get("stock_uom"),
				"width_mm": flt(dims.get("width_mm") or im.get("width_mm")),
				"length_mtr": flt(dims.get("length_mtr") or im.get("length_mtr")),
				"gsm": flt(im.get("gsm")),
			})

		lines.sort(key=lambda x: x["width_mm"], reverse=True)
		passes = []
		for ln in lines:
			placed = False
			for p in passes:
				fits_width = (not usable) or (sum(o["width_mm"] for o in p) + ln["width_mm"] <= usable)
				fits_count = (not knives) or (len(p) + 1 <= knives)
				if fits_width and fits_count:
					p.append(ln)
					placed = True
					break
			if not placed:
				passes.append([ln])

		route = _get_stage_route(lines[0]["item_code"], location) if lines else list(STAGES)
		for idx, p in enumerate(passes, 1):
			proposals.append({
				"source_batch": bat.name,
				"source_batch_item": bat.item,
				"source_batch_width_mm": flt(bat.width_mm),
				"pass_no": idx,
				"total_pass_width_mm": sum(o["width_mm"] for o in p),
				"route": route,
				"outputs": p,
			})

	return {
		"order_sheet": order_sheet,
		"location": location,
		"knife_positions": knives,
		"trim_mm": _ASSUMED_TRIM_MM,
		"proposals": proposals,
	}


@frappe.whitelist()
def get_setup_batches(stage, location=None):
	"""Runs currently AT `stage` grouped by machine-setup signature. Any group
	with 2+ runs = 'set the knives once, run these N' — surfaced on Machine-wise.
	"""
	_require_production_role()
	filters = {"current_stage": stage, "status": ["in", ["In Progress", "On Hold"]]}
	runs = frappe.get_all("IB Work Order", filters=filters, fields=["name", "machine", "location"])
	groups = {}
	for r in runs:
		if location and (r.location or "").lower() != location.lower():
			continue
		doc = frappe.get_doc("IB Work Order", r.name)
		spec = _spec_from_run(doc)
		sig = _setup_sig(stage, spec)
		g = groups.setdefault(sig, {"sig": sig, "stage": stage, "runs": [], "machines": set()})
		g["runs"].append({
			"work_order": r.name,
			"machine": r.machine,
			"output_widths_mm": spec["output_widths_mm"],
			"output_length_m": spec["output_length_m"],
		})
		if r.machine:
			g["machines"].add(r.machine)
	out = []
	for g in groups.values():
		if len(g["runs"]) < 2:
			continue
		g["machines"] = sorted(g["machines"])
		g["run_count"] = len(g["runs"])
		out.append(g)
	out.sort(key=lambda x: -x["run_count"])
	return out


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------

@frappe.whitelist()
def create_run(order_sheet, source_batch, source_qty=None, outputs=None,
               route=None, start_stage=None, priority=None, notes=None):
	"""Create ONE IB Work Order (a run) and start it.

	outputs: [{order_sheet_item, item_code, planned_qty, uom, width_mm, length_mtr,
	           gsm, pack_count, brand, core, ctn, shrink_film, packing_type}]
	route:   ordered list of stage names (default: first output item's group route)
	start_stage: stage to begin at (default: route[0])
	"""
	_require_production_role()
	outputs = _parse(outputs) or []
	route = _parse(route)
	if not outputs:
		frappe.throw(_("A run needs at least one output item."))

	# Real gap, closed: nothing anywhere in create_run/_finish_run checked
	# that a run's outputs share one UOM. A run's `source_qty` default sums
	# every output's planned_qty (line below, unchanged), and _finish_run
	# later splits ONE operator-entered scalar (output_qty from the Advance
	# dialog) across outputs proportionally by that same planned_qty ratio —
	# both are meaningless the moment two outputs are in different units.
	# This is reachable, not theoretical: several real item groups here mix
	# stock_uom within the group (PLASTIC/PVC/FOIL all have both KG and SQMT
	# members), and the Start Run dialog's own bulk-group key is the route
	# sequence only, not item_code/uom — two same-route items with different
	# UOM would otherwise silently land in one run. Caught here, before any
	# batch-qty reservation or doc insert, so it's a clean abort.
	resolved_uoms = set()
	for o in outputs:
		item_code = o.get("item_code")
		u = o.get("uom") or (item_code and frappe.db.get_value("Item", item_code, "stock_uom"))
		resolved_uoms.add(u)
	if len(resolved_uoms) > 1:
		frappe.throw(_(
			"This run's outputs mix units ({0}) — a run can only produce output in one UOM. "
			"Start these as separate runs instead."
		).format(", ".join(sorted(u for u in resolved_uoms if u))))

	os_row = frappe.db.get_value(
		"IB Order Sheet", order_sheet, ["name", "sales_order", "priority", "status"], as_dict=True
	)
	if not os_row:
		frappe.throw(_("Order Sheet {0} not found").format(order_sheet))
	sales_order = os_row.sales_order
	location = (frappe.db.get_value("Sales Order", sales_order, "custom_location") or "").lower() or None

	batch = frappe.db.get_value(
		"IB Batch", source_batch, ["name", "kind", "item", "item_name", "qty", "status"], as_dict=True
	)
	if not batch:
		frappe.throw(_("Source batch {0} not found").format(source_batch))
	if batch.kind != "Raw Material":
		frappe.throw(_("Source batch {0} is not a Raw Material batch").format(source_batch))
	if batch.status != "Active":
		frappe.throw(_("Source batch {0} is {1}, not Active").format(source_batch, batch.status))

	source_qty = flt(source_qty) or sum(flt(o.get("planned_qty")) for o in outputs)

	# Real gap, now closed: IB Batch.qty was never checked or decremented
	# anywhere — the same batch could be used as the source for unlimited
	# runs, consuming far more material than it physically has, with no
	# warning. Reserve BEFORE building/inserting the run (not after) so a
	# failed reservation never leaves an orphaned Work Order with no real
	# material behind it — nothing has been created yet at this point, a
	# throw here is a clean abort. The UPDATE's own "AND qty >= %s" guard
	# (not a plain read-then-write) makes this atomic: two create_run calls
	# against the same batch from two DIFFERENT order sheets (the per-
	# order-sheet lock below doesn't cover that case) can't both succeed
	# past each other's deduction the way a Python-side check-then-write
	# would allow. cancel_run() restores this if the run is later
	# cancelled. Length-split (advance_with_length_split) doesn't call
	# create_run for its child runs — it redistributes THIS run's already-
	# reserved source_qty across siblings, so no double-reservation there.
	if flt(source_qty) > flt(batch.qty):
		frappe.throw(_(
			"Source batch {0} only has {1} remaining, but this run needs {2}."
		).format(source_batch, batch.qty, source_qty))
	# frappe.db.sql() itself returns () for an UPDATE — the real affected-
	# row count only shows up on the driver cursor. Verified live (bench
	# execute): 1 for a real matching change, 0 when the guard excludes it.
	frappe.db.sql(
		"UPDATE `tabIB Batch` SET qty = qty - %s WHERE name = %s AND qty >= %s",
		(source_qty, source_batch, source_qty),
	)
	if frappe.db._cursor.rowcount == 0:
		frappe.throw(_(
			"Source batch {0} no longer has {1} available — someone else just allocated from it. Please retry."
		).format(source_batch, source_qty))

	# route: explicit, else derive from the first output's item group
	if not route:
		route = _get_stage_route(outputs[0].get("item_code"), location)
	route = _validate_route(route, location)

	start_stage = start_stage or route[0]
	if start_stage not in route:
		frappe.throw(_("Start stage {0} is not in this run's route").format(start_stage))

	lock = f"IB-RUN-{order_sheet}-{source_batch}"
	if not frappe.db.sql("SELECT GET_LOCK(%s, 5)", lock)[0][0]:
		frappe.throw(_("Could not acquire lock for run creation. Please try again."))
	try:
		doc = frappe.new_doc("IB Work Order")
		doc.sales_order = sales_order
		doc.order_sheet = order_sheet
		doc.priority = priority or os_row.priority or "Normal"
		doc.location = location or ""
		doc.posting_date = today()
		doc.source_batch = source_batch
		doc.source_item = batch.item
		doc.source_qty = source_qty
		doc.source_warehouse = _batch_source_warehouse(source_batch) or ""
		doc.notes = notes or ""

		for i, s in enumerate(route):
			doc.append("route", {
				"stage": s, "sequence": i + 1,
				"machine_type": _STAGE_MACHINE_TYPE.get(s, ""), "done": 0,
			})

		for o in outputs:
			item_code = o.get("item_code")
			if not item_code or not frappe.db.exists("Item", item_code):
				frappe.throw(_("Output item {0} does not exist").format(item_code))

			# Real gap, closed: sales_order_item is the ONLY link IB WO Output
			# carries back to an Order Sheet Item (the doctype has no
			# order_sheet_item field at all — see _recompute_osi_status, which
			# joins purely on sales_order_item). Every caller today happens to
			# resolve it correctly before calling (get_osi_context_batch for
			# the Start dialog, os_doc.items directly for propose_runs), but
			# nothing here ever verified that — a caller that supplies
			# order_sheet_item without sales_order_item (a future UI path, a
			# direct API call, a regression in either existing caller) would
			# silently reproduce the exact IB-WO-2026-25500 class of bug
			# get_osi_context_batch's own docstring describes: the item can
			# NEVER reach Completed no matter how many real stages finish,
			# permanently blocking that order's Create Delivery Note gate,
			# with no error anywhere. Resolved server-side from the one
			# source of truth instead of trusting the caller.
			if o.get("order_sheet_item") and not o.get("sales_order_item"):
				o["sales_order_item"] = frappe.db.get_value(
					"IB Order Sheet Item", o["order_sheet_item"], "sales_order_item"
				)

			im = frappe.db.get_value(
				"Item", item_code, ["item_name", "stock_uom", "width_mm", "length_mtr", "gsm"], as_dict=True
			) or {}
			# Finished dims: explicit (from the dialog) -> the originating Sales
			# Order Item's own dimensions (one item_code can vary W/L per SO line)
			# -> the Item master. Order Sheet Item carries no dims.
			soi = {}
			if o.get("sales_order_item"):
				soi = frappe.db.get_value(
					"Sales Order Item", o["sales_order_item"], ["width_mm", "length_mtr"], as_dict=True
				) or {}
			doc.append("outputs", {
				"item_code": item_code,
				"item_name": im.get("item_name"),
				"planned_qty": flt(o.get("planned_qty")),
				"uom": o.get("uom") or im.get("stock_uom"),
				"width_mm": flt(o.get("width_mm") or soi.get("width_mm") or im.get("width_mm")),
				"length_mtr": flt(o.get("length_mtr") or soi.get("length_mtr") or im.get("length_mtr")),
				"gsm": flt(o.get("gsm") or im.get("gsm")),
				"pack_count": cint(o.get("pack_count")),
				"brand": o.get("brand"),
				"core": o.get("core"),
				"ctn": o.get("ctn"),
				"shrink_film": o.get("shrink_film"),
				"packing_type": o.get("packing_type"),
				"sales_order_item": o.get("sales_order_item") or "",
			})

		# stages before the chosen start stage are implicitly skipped
		skipped_before = route[: route.index(start_stage)]
		ts = now()
		for s in skipped_before:
			doc.append("stage_log", {
				"stage": s, "skipped": 1, "operator": frappe.session.user,
				"started_at": ts, "completed_at": ts,
				"input_qty": source_qty, "output_qty": source_qty,
				"notes": "Skipped — run started at a later stage",
			})
			_mark_route_done(doc, s)

		doc.current_stage = start_stage
		# dimension-aware pick (feasible -> least changeover -> least load).
		# outputs + source_batch are on `doc` already, so the spec is complete.
		machine = _assign_machine(start_stage, location, _spec_from_run(doc)) or ""
		doc.machine = machine
		doc.insert(ignore_permissions=True)

		# Phase 3 (real stock-ledger integration, gated behind
		# ib_production_posts_stock) — RM warehouse -> WIP for this run's
		# full source_qty. A no-op returning None when the flag is off, so
		# every existing create_run caller/test is unaffected until someone
		# explicitly turns it on. Persisted the same way as started_at/
		# machine below (apply_workflow's reload would otherwise discard it).
		from instabiz.overrides.production_stock import post_run_start_transfer
		start_se = post_run_start_transfer(doc)

		# start it (Pending -> In Progress). apply_workflow reloads from DB, so
		# every field above is already persisted by insert() — safe.
		_wf(doc, "Start", {
			"started_at": ts, "machine": machine, "current_stage": start_stage,
			"start_stock_entry": start_se,
		})

		# reflect on the Order Sheet + its items
		if os_row.status == "Draft":
			frappe.db.set_value("IB Order Sheet", order_sheet, "status", "In Progress")
		osi_names = [o.get("order_sheet_item") for o in outputs if o.get("order_sheet_item")]
		for n in osi_names:
			frappe.db.set_value("IB Order Sheet Item", n, "status", "In Progress")

		frappe.db.commit()
		_notify_floor_update()
		return doc.name
	finally:
		frappe.db.sql("SELECT RELEASE_LOCK(%s)", lock)


# ---------------------------------------------------------------------------
# advance / skip / hold / resume
# ---------------------------------------------------------------------------

@frappe.whitelist()
def advance_run(work_order, output_qty=None, outputs_qty=None,
                machine=None, operator=None, notes=None):
	"""Complete the run's current stage and move to the next (or finish).

	output_qty : aggregate real output for this stage (operator-entered).
	outputs_qty: {output_row_name: qty} — only used at the FINAL stage of a
	             multi-output run to split produced_qty per output.
	"""
	_require_production_role()
	outputs_qty = _parse(outputs_qty)
	if output_qty is not None and flt(output_qty) < 0:
		frappe.throw(_("Output qty cannot be negative."))

	lock = f"IB-WO-{work_order}"
	if not frappe.db.sql("SELECT GET_LOCK(%s, 5)", lock)[0][0]:
		frappe.throw(_("Could not acquire lock for run {0}. Please try again.").format(work_order))
	try:
		doc = frappe.get_doc("IB Work Order", work_order)
		if doc.status == "Completed":
			return {"ok": True, "next_stage": None, "message": _("Run already complete")}
		if doc.status != "In Progress":
			frappe.throw(_("Run {0} must be In Progress to advance (it is {1}).").format(
				work_order, doc.status))

		stage = doc.current_stage
		if not stage or stage == "Done":
			frappe.throw(_("Run {0} has no active stage.").format(work_order))

		input_qty = _prev_output_qty(doc)
		out_qty = flt(output_qty) if output_qty is not None else input_qty

		last_completed = None
		for ev in reversed(doc.stage_log or []):
			if ev.completed_at:
				last_completed = ev.completed_at
				break
		ts = now()
		ran_on = machine or doc.machine
		doc.append("stage_log", {
			"stage": stage,
			"machine": ran_on,
			"operator": operator or frappe.session.user,
			"skipped": 0,
			"started_at": last_completed or doc.started_at or ts,
			"completed_at": ts,
			"input_qty": input_qty,
			"output_qty": out_qty,
			"notes": notes or "",
			# wastage_qty/wastage_pct deliberately not set here — the doctype
			# controller's validate() -> _roll_up_stage_events() computes them
			# on every save from input_qty/output_qty (and _roll_up_totals()
			# rolls stage_log into total_wastage_qty on the parent), so
			# setting them here too would just be duplicate logic that has
			# to stay in sync with the controller by hand. Verified: 0
			# wastage_qty across every real stage event in this dev dataset
			# is correct, not a bug — every real advance so far has been a
			# full pass-through (no operator has entered a lower actual
			# output yet), not evidence the computation is missing.
		})
		_mark_route_done(doc, stage)

		spec = _spec_from_run(doc)
		# remember what this machine is now set up for -> zero changeover for the next match
		_stamp_machine_setup(ran_on, stage, spec)

		nxt = _next_stage_after(doc, stage)
		if nxt:
			doc.current_stage = nxt
			doc.machine = _assign_machine(nxt, _run_location(doc), spec) or ""
			doc.save(ignore_permissions=True)
			frappe.db.commit()
			_notify_floor_update()
			return {"ok": True, "next_stage": nxt,
			        "message": _("{0} done — {1} is next").format(stage, nxt)}

		# last stage → finish
		result = _finish_run(doc, outputs_qty)
		frappe.db.commit()
		_notify_floor_update()
		result.update({"ok": True, "next_stage": None})
		return result
	finally:
		frappe.db.sql("SELECT RELEASE_LOCK(%s)", lock)


@frappe.whitelist()
def get_length_split_plan(work_order):
	"""Read-only: if this run's next stage is Cutting and its finished length
	exceeds every real Cutting machine's max_length_m, suggest an even split
	into N batches that each fit a real machine. A job that's infeasible for
	other reasons too (width, knife count) isn't helped by splitting length —
	returns needed=False, same as a job that already fits."""
	_require_production_role()
	doc = frappe.get_doc("IB Work Order", work_order)
	stage = doc.current_stage
	nxt = _next_stage_after(doc, stage)
	if nxt != "Cutting":
		return {"needed": False}
	spec = _spec_from_run(doc)
	length = flt(spec.get("output_length_m"))
	if not length:
		return {"needed": False}
	location = _run_location(doc)
	machines = frappe.db.get_all(
		"IB Machine", filters={"machine_type": "Cutting", "status": "Active"},
		fields=["name", "max_length_m", "location"],
	)
	if location:
		pref = [m for m in machines if m.location == location]
		machines = pref or machines
	real_caps = [flt(m.max_length_m) for m in machines if flt(m.max_length_m) > 0]
	if not real_caps:
		return {"needed": False}  # no real length limit known on any machine — nothing to split for
	best = max(real_caps)
	if length <= best:
		return {"needed": False}
	import math
	batches = math.ceil(length / best)
	return {
		"needed": True, "next_stage": nxt, "total_length_m": length,
		"best_machine_capacity_m": best, "batches": batches,
		"batch_length_m": round(length / batches, 2),
	}


@frappe.whitelist()
def advance_with_length_split(work_order, batches, output_qty=None, operator=None, notes=None):
	"""Same "complete the current stage" half as advance_run(), but instead of
	one _assign_machine() call for the next stage (which would just throw
	again), splits the run into N sibling runs — same width/core, each 1/N of
	the finished length — so each independently fits a real Cutting machine's
	max_length_m. Every sibling stays on the SAME sales_order (a run is
	always exactly one order's job, IB Work Order.sales_order is a single
	Link — it can't span customers); cross-order efficiency instead comes
	from get_setup_batches() grouping same-setup runs — this order's new
	batches included — for one shared knife setup, not from merging orders
	into one run's data.

	Known simplification: qty/pack_count are split evenly (length_mtr / N,
	planned_qty / N, pack_count // N) rather than via a real per-product
	length->weight formula — good enough for a first version; a batch's
	numbers can be corrected by hand afterward if the real split isn't even.
	"""
	_require_production_role()
	batches = cint(batches)
	if batches < 2:
		frappe.throw(_("Need at least 2 batches to split."))

	lock = f"IB-WO-{work_order}"
	if not frappe.db.sql("SELECT GET_LOCK(%s, 5)", lock)[0][0]:
		frappe.throw(_("Could not acquire lock for run {0}. Please try again.").format(work_order))
	try:
		doc = frappe.get_doc("IB Work Order", work_order)
		if doc.status != "In Progress":
			frappe.throw(_("Run {0} must be In Progress to advance (it is {1}).").format(
				work_order, doc.status))
		stage = doc.current_stage
		if not stage or stage == "Done":
			frappe.throw(_("Run {0} has no active stage.").format(work_order))
		nxt = _next_stage_after(doc, stage)
		if not nxt:
			frappe.throw(_("Run {0} has no next stage to split into.").format(work_order))

		input_qty = _prev_output_qty(doc)
		out_qty = flt(output_qty) if output_qty is not None else input_qty
		ts = now()
		last_completed = None
		for ev in reversed(doc.stage_log or []):
			if ev.completed_at:
				last_completed = ev.completed_at
				break
		doc.append("stage_log", {
			"stage": stage, "machine": doc.machine, "operator": operator or frappe.session.user,
			"skipped": 0, "started_at": last_completed or doc.started_at or ts, "completed_at": ts,
			"input_qty": input_qty, "output_qty": out_qty,
			"notes": ((notes or "") + " [split into {0} batches at {1} — length exceeded machine capacity]"
			          .format(batches, nxt)).strip(),
		})
		_mark_route_done(doc, stage)
		spec = _spec_from_run(doc)
		_stamp_machine_setup(doc.machine, stage, spec)

		route_stages = _route_stages(doc)
		nxt_idx = route_stages.index(nxt)
		location = _run_location(doc)

		children = []
		for i in range(batches):
			child = frappe.new_doc("IB Work Order")
			child.sales_order = doc.sales_order
			child.order_sheet = doc.order_sheet
			child.priority = doc.priority
			child.location = doc.location
			child.posting_date = today()
			child.source_batch = doc.source_batch
			child.source_item = doc.source_item
			child.source_qty = flt(doc.source_qty) / batches if doc.source_qty else 0
			child.source_warehouse = doc.source_warehouse
			# Phase 3 (real stock-ledger integration) — the parent's ONE
			# Start-time RM->WIP transfer already moved the material this
			# split is dividing; a child must NOT trigger a second transfer
			# (that would double-count against the real RM warehouse). It
			# inherits the same reference so its own Finish-time posting
			# (which keys off start_stock_entry being set) still fires —
			# each child's Finish independently consumes its own qty share
			# from the shared WIP balance, which is the physically correct
			# behavior, not a double-count.
			child.start_stock_entry = doc.start_stock_entry
			child.notes = _("Batch {0}/{1} split from {2} (length exceeded machine capacity)").format(
				i + 1, batches, doc.name)

			for r in doc.route:
				child.append("route", {
					"stage": r.stage, "sequence": r.sequence,
					"machine_type": r.machine_type, "done": r.done,
				})
			for o in doc.outputs:
				child.append("outputs", {
					"item_code": o.item_code, "item_name": o.item_name,
					"planned_qty": flt(o.planned_qty) / batches,
					"uom": o.uom, "width_mm": o.width_mm,
					"length_mtr": flt(o.length_mtr) / batches if o.length_mtr else 0,
					"gsm": o.gsm,
					"pack_count": (cint(o.pack_count) // batches) or cint(o.pack_count),
					"brand": o.brand, "core": o.core, "ctn": o.ctn,
					"shrink_film": o.shrink_film, "packing_type": o.packing_type,
					"sales_order_item": o.sales_order_item,
				})
			# Carry the parent's real stage history forward (scaled down) rather
			# than marking earlier stages "skipped" — the work genuinely
			# happened once, on the parent, before the split.
			for ev in doc.stage_log:
				child.append("stage_log", {
					"stage": ev.stage, "machine": ev.machine, "operator": ev.operator,
					"skipped": ev.skipped, "started_at": ev.started_at, "completed_at": ev.completed_at,
					"input_qty": flt(ev.input_qty) / batches if ev.input_qty else 0,
					"output_qty": flt(ev.output_qty) / batches if ev.output_qty else 0,
					"notes": ev.notes,
				})
			for r in child.route[:nxt_idx]:
				r.done = 1
			child.current_stage = nxt
			child.machine = _assign_machine(nxt, location, _spec_from_run(child)) or ""
			child.insert(ignore_permissions=True)
			_wf(child, "Start", {"started_at": ts, "machine": child.machine, "current_stage": nxt})
			children.append(child.name)

		# Original run is superseded by its children — Cancel via the real
		# workflow transition (not a raw db_set), same as every other status
		# change in this file.
		doc.save(ignore_permissions=True)
		_wf(doc, "Cancel")
		frappe.db.set_value(
			"IB Work Order", doc.name, "notes",
			(doc.notes or "") + "\n[Split] {0} done, {1} needs {2} shorter passes — continued as {3}".format(
				stage, nxt, batches, ", ".join(children)),
		)

		frappe.db.commit()
		_notify_floor_update()
		return {"ok": True, "batches": children, "next_stage": nxt}
	finally:
		frappe.db.sql("SELECT RELEASE_LOCK(%s)", lock)


@frappe.whitelist()
def skip_stage(work_order, reason=None):
	"""Bypass the current stage (no work done) and move on."""
	_require_production_role()
	lock = f"IB-WO-{work_order}"
	if not frappe.db.sql("SELECT GET_LOCK(%s, 5)", lock)[0][0]:
		frappe.throw(_("Could not acquire lock for run {0}. Please try again.").format(work_order))
	try:
		doc = frappe.get_doc("IB Work Order", work_order)
		if doc.status != "In Progress":
			frappe.throw(_("Run {0} must be In Progress to skip a stage.").format(work_order))
		stage = doc.current_stage
		if not stage or stage == "Done":
			frappe.throw(_("Run {0} has no active stage.").format(work_order))

		qty = _prev_output_qty(doc)
		ts = now()
		doc.append("stage_log", {
			"stage": stage, "skipped": 1, "operator": frappe.session.user,
			"started_at": ts, "completed_at": ts,
			"input_qty": qty, "output_qty": qty,
			"notes": reason or "Stage skipped",
		})
		_mark_route_done(doc, stage)

		nxt = _next_stage_after(doc, stage)
		if nxt:
			doc.current_stage = nxt
			doc.machine = _assign_machine(nxt, _run_location(doc), _spec_from_run(doc)) or ""
			doc.save(ignore_permissions=True)
			frappe.db.commit()
			_notify_floor_update()
			return {"ok": True, "next_stage": nxt, "message": _("{0} skipped").format(stage)}

		result = _finish_run(doc, None)
		frappe.db.commit()
		_notify_floor_update()
		result.update({"ok": True, "next_stage": None})
		return result
	finally:
		frappe.db.sql("SELECT RELEASE_LOCK(%s)", lock)


@frappe.whitelist()
def hold_run(work_order, reason=None):
	# Real gap, fixed: every other mutating function in this file
	# (advance_run/create_run/cancel_run/skip_stage/assign_machine) takes
	# the same GET_LOCK('IB-WO-{name}') — this one didn't, so a double-
	# click or two tabs hitting Hold/Resume/Advance on the same run at once
	# could race past each other's status check before either write lands.
	_require_production_role()
	lock = f"IB-WO-{work_order}"
	if not frappe.db.sql("SELECT GET_LOCK(%s, 5)", lock)[0][0]:
		frappe.throw(_("Could not acquire lock for run {0}. Please try again.").format(work_order))
	try:
		doc = frappe.get_doc("IB Work Order", work_order)
		if reason:
			doc.notes = (doc.notes or "") + f"\n[Hold] {reason}"
			doc.save(ignore_permissions=True)
		# free the machine while held
		_wf(doc, "Hold", {"machine": ""})
		# Real gap, closed: this is the Command Center Hold button's own RPC
		# (called directly, not via production.put_on_hold) — the sales-
		# person delivery-risk alert (_notify_production_hold) only ever
		# fired from put_on_hold's own implementation, so holding a run from
		# Command Center never notified anyone, while holding the exact same
		# run from the Stages tab's WO panel did. Both surfaces now funnel
		# through this one real Hold implementation (put_on_hold is a compat
		# shim onto this function — see its own docstring), so there is only
		# one notification path to keep correct.
		_notify_production_hold(doc)
		frappe.db.commit()
		_notify_floor_update()
		return {"ok": True, "status": "On Hold"}
	finally:
		frappe.db.sql("SELECT RELEASE_LOCK(%s)", lock)


@frappe.whitelist()
def resume_run(work_order):
	_require_production_role()
	lock = f"IB-WO-{work_order}"
	if not frappe.db.sql("SELECT GET_LOCK(%s, 5)", lock)[0][0]:
		frappe.throw(_("Could not acquire lock for run {0}. Please try again.").format(work_order))
	try:
		doc = frappe.get_doc("IB Work Order", work_order)
		machine = _assign_machine(doc.current_stage, _run_location(doc), _spec_from_run(doc)) or ""
		_wf(doc, "Resume", {"machine": machine})
		frappe.db.commit()
		_notify_floor_update()
		return {"ok": True, "status": "In Progress", "machine": machine}
	finally:
		frappe.db.sql("SELECT RELEASE_LOCK(%s)", lock)


@frappe.whitelist()
def cancel_run(work_order, reason=None):
	"""Cancel a run: undo its genealogy (serials + FG batch), then transition
	the workflow to Cancelled. (Phase 3 will also reverse the Repack here.)

	Real bug, fixed here: cancelling a run that had already Completed (its
	genealogy just got reversed above) never re-checked the Order Sheet
	Item(s) it had finished — _settle_order_sheet only ever SET an item to
	Completed, nothing ever un-set one. An order whose only completing run
	got cancelled kept showing Completed / kept passing
	get_order_dn_readiness, letting Create Delivery Note stay open for
	production that had just been undone. Recompute every affected item
	(and the Order Sheet's own rollup) after the cancel, same as a finish
	does — see _recompute_osi_status's own comment for the real rule.

	Second real bug, fixed here: unlike every sibling mutator in this file
	(create_run/advance_run/skip_stage/hold_run/resume_run), this function
	had no GET_LOCK at all — a double-click on the UI's Cancel Run button
	(no double-submit guard on a frappe.ui.Dialog's primary_action by
	default) or two tabs racing could both read run_row.status !=
	'Cancelled' before either write landed, and both run the batch-qty
	restore UPDATE below — silently double-crediting the source batch's
	remaining qty. Same lock convention as every other mutator here.
	"""
	_require_production_role()
	lock_name = f"IB-WO-{work_order}"
	locked = frappe.db.sql("SELECT GET_LOCK(%s, 5)", lock_name)[0][0]
	if not locked:
		frappe.throw(_("Could not acquire lock for run {0}. Please try again.").format(work_order))
	try:
		run_row = frappe.db.get_value(
			"IB Work Order", work_order,
			["order_sheet", "status", "source_batch", "source_qty"], as_dict=True,
		)
		if not run_row:
			frappe.throw(_("Run {0} not found").format(work_order))
		sales_order_items = frappe.get_all(
			"IB WO Output", filters={"parent": work_order}, pluck="sales_order_item"
		)

		# Give back what this run had reserved from its source batch (see
		# create_run's own comment for why that reservation exists) — a
		# cancelled run's material was never actually consumed. Guarded on the
		# run's status BEFORE this call, not just "not already restored" —
		# cancel_run can be called again on an already-Cancelled run (the
		# workflow-transition fallback below tolerates it) and must not
		# restore the same qty twice.
		if run_row.status != "Cancelled" and run_row.source_batch and flt(run_row.source_qty):
			frappe.db.sql(
				"UPDATE `tabIB Batch` SET qty = qty + %s WHERE name = %s",
				(run_row.source_qty, run_row.source_batch),
			)

		_reverse_run_genealogy(work_order)  # also nulls fg_batch links on the run + outputs

		if reason:
			note = (frappe.db.get_value("IB Work Order", work_order, "notes") or "")
			frappe.db.set_value("IB Work Order", work_order, "notes",
			                    f"{note}\n[Cancelled] {reason}".strip(), update_modified=False)

		doc = frappe.get_doc("IB Work Order", work_order)

		# Phase 3 (real stock-ledger integration) — reverse whichever real
		# Stock Entries this run posted (Start transfer, and Finish repack
		# if it got that far). No-op when ib_production_posts_stock is off
		# or this run never posted any (both fields blank).
		from instabiz.overrides.production_stock import reverse_run_stock
		reverse_run_stock(doc)

		try:
			_wf(doc, "Cancel", {"current_stage": "Cancelled"})
		except Exception:
			# "Completed" has no "Cancel" transition in the workflow — force it.
			frappe.db.set_value("IB Work Order", work_order,
			                    {"status": "Cancelled", "current_stage": "Cancelled"})

		if run_row.order_sheet:
			for soi in sales_order_items:
				if soi:
					_recompute_osi_status(run_row.order_sheet, soi)
			_roll_up_order_sheet_status(run_row.order_sheet)

		frappe.db.commit()
		_notify_floor_update()
		return {"ok": True, "status": "Cancelled"}
	finally:
		frappe.db.sql("SELECT RELEASE_LOCK(%s)", lock_name)


def _reverse_run_genealogy(work_order):
	"""Delete this run's FG serials + FG batch and clear every link to them on
	the run itself, so a subsequent doc.save() doesn't fail link validation."""
	for sn in frappe.get_all("IB FG Serial", filters={"work_order": work_order}, pluck="name"):
		frappe.delete_doc("IB FG Serial", sn, force=True, ignore_permissions=True)
	frappe.db.set_value("IB Work Order", work_order, "fg_batch", None, update_modified=False)
	frappe.db.sql(
		"UPDATE `tabIB WO Output` SET fg_batch = NULL, serial_count = 0 WHERE parent = %s",
		(work_order,),
	)
	for b in frappe.get_all(
		"IB Batch", filters={"work_order": work_order, "kind": "Finished Good"}, pluck="name"
	):
		frappe.delete_doc("IB Batch", b, force=True, ignore_permissions=True)


def reverse_run_stock(doc, method=None):
	"""IB Work Order on_trash hook — clean up genealogy if a run is hard-deleted."""
	try:
		_reverse_run_genealogy(doc.name)
	except Exception:
		frappe.log_error("reverse_run_stock", frappe.get_traceback())


# ---------------------------------------------------------------------------
# finish — FG batch + serials  (NO Repack in Phase 1)
# ---------------------------------------------------------------------------

def _finish_run(doc, outputs_qty=None):
	"""Called with the final stage_log row already appended in-memory.

	1. persist the run (so apply_workflow's reload keeps it)
	2. create FG IB Batch (parent = source batch)
	3. per output: produced_qty (from outputs_qty or planned ratio of final output),
	   IB FG Serial per unit (item-group gated), write produced_qty/serial_count/fg_batch
	4. workflow -> Completed, current_stage -> "Done"
	"""
	final_out = flt(doc.stage_log[-1].output_qty) if doc.stage_log else 0.0
	planned_total = sum(flt(o.planned_qty) for o in doc.outputs) or 0.0

	# resolve produced_qty per output row. The proportional-split branches
	# (planned-ratio and even-split) used to round each row independently,
	# which can drift the SUM away from final_out by a few thousandths per
	# extra output row (harmless at 2-3 outputs, a real minor discrepancy
	# on a run with many outputs). Fixed by rounding every row except the
	# last, then giving the last row whatever's left — sum(produced) always
	# exactly equals final_out. Not applied to the outputs_qty branch: those
	# are operator-entered exact values, which may legitimately not sum to
	# final_out (e.g. real measured wastage differs per output) — forcing
	# them to match would silently overwrite what the operator typed.
	produced = {}
	split_rows = [o for o in doc.outputs if not (outputs_qty and (o.name in outputs_qty or o.item_code in outputs_qty))]
	running_total = 0.0
	for i, o in enumerate(doc.outputs):
		if outputs_qty and (o.name in outputs_qty or o.item_code in outputs_qty):
			produced[o.name] = flt(outputs_qty.get(o.name, outputs_qty.get(o.item_code)))
		elif len(doc.outputs) == 1:
			produced[o.name] = final_out
		elif o is split_rows[-1]:
			produced[o.name] = round(final_out - running_total, 3)
		elif planned_total:
			produced[o.name] = round(final_out * flt(o.planned_qty) / planned_total, 3)
			running_total += produced[o.name]
		else:
			produced[o.name] = round(final_out / len(doc.outputs), 3)
			running_total += produced[o.name]

	ts = now()
	doc.current_stage = "Done"
	doc.completed_at = ts
	for o in doc.outputs:
		o.produced_qty = produced.get(o.name, 0.0)
	doc.save(ignore_permissions=True)

	# Phase 3 (real stock-ledger integration) — WIP -> FG/Scrap, now that
	# every output's produced_qty is final. No-op when
	# ib_production_posts_stock isn't set, or this particular run never had
	# a Start-time transfer posted (e.g. created before the flag was turned
	# on, or a non-Gujarat location).
	from instabiz.overrides.production_stock import post_run_finish_transfer
	finish_se = post_run_finish_transfer(doc)

	# FG batch (genealogy root for this run's output) — one per distinct
	# output item_code, not one batch blended across all outputs. A run's
	# outputs can be genuine different SKUs (not just dimension-variants of
	# one SKU) — lumping every output's produced_qty under the first
	# output's item_code silently mis-attributed other SKUs' quantity to
	# the wrong Item's batch. Single-output runs keep the old `FG::{name}`
	# id unchanged; multi-item runs get `FG::{name}::{item_code}` per item.
	item_codes = []
	for o in doc.outputs:
		if o.item_code not in item_codes:
			item_codes.append(o.item_code)

	fg_batch_by_item = {}
	for item_code in item_codes:
		rows = [o for o in doc.outputs if o.item_code == item_code]
		fg_batch_id = f"FG::{doc.name}" if len(item_codes) == 1 else f"FG::{doc.name}::{item_code}"
		fg_batch_by_item[item_code] = fg_batch_id
		if not frappe.db.exists("IB Batch", fg_batch_id):
			primary = rows[0]
			fb = frappe.new_doc("IB Batch")
			fb.batch_id = fg_batch_id
			fb.kind = "Finished Good"
			fb.item = item_code
			fb.item_name = primary.item_name
			fb.qty = sum(flt(o.produced_qty) for o in rows)
			fb.status = "Active"
			fb.source_type = "Production"
			fb.work_order = doc.name
			fb.received_date = today()
			fb.parent_batches = json.dumps([doc.source_batch] if doc.source_batch else [])
			fb.gsm = flt(primary.gsm)
			fb.width_mm = flt(primary.width_mm)
			fb.insert(ignore_permissions=True)

	fg_batch_id = fg_batch_by_item[item_codes[0]]  # WO.fg_batch stays a single Link — primary/first item's batch

	serials_made = 0
	truncated_items = []  # real gap, fixed: this cap used to be silent — see the message built below
	try:
		from instabiz.overrides.item import _SERIAL_ITEM_GROUPS

		for o in doc.outputs:
			row_fg_batch = fg_batch_by_item[o.item_code]
			grp = frappe.db.get_value("Item", o.item_code, "item_group") or ""
			if grp not in _SERIAL_ITEM_GROUPS:
				o.db_set("fg_batch", row_fg_batch)
				continue
			real_count = cint(o.pack_count) or 1
			if real_count > 2000:
				truncated_items.append((o.item_code, real_count))
			n_units = min(real_count, 2000)
			stamp = _serial_stamp()
			seq = _next_serial_seq(o.item_code, stamp)
			made = 0
			for i in range(n_units):
				sn_name = f"{o.item_code}::{stamp}::{seq + i:04d}"
				if frappe.db.exists("IB FG Serial", sn_name):
					continue
				sn = frappe.new_doc("IB FG Serial")
				sn.serial_no = sn_name
				sn.item_code = o.item_code
				sn.item_name = o.item_name
				sn.status = "In Stock"
				sn.fg_batch = row_fg_batch
				sn.source_batch = doc.source_batch
				sn.work_order = doc.name
				sn.order_sheet = doc.order_sheet
				sn.sales_order = doc.sales_order
				sn.produced_on = ts
				sn.box_no = i + 1
				sn.width_mm = flt(o.width_mm)
				sn.length_mtr = flt(o.length_mtr)
				sn.gsm = flt(o.gsm)
				sn.insert(ignore_permissions=True)
				made += 1
			o.db_set("serial_count", made)
			o.db_set("fg_batch", row_fg_batch)
			serials_made += made
	except Exception:
		frappe.log_error("IB run serial gen", frappe.get_traceback())

	frappe.db.set_value("IB Work Order", doc.name,
	                    {"fg_batch": fg_batch_id, "stock_entry": finish_se}, update_modified=False)
	_wf(doc, "Complete", {"current_stage": "Done", "completed_at": ts})

	# roll the Order Sheet / its items up
	_settle_order_sheet(doc)

	message = _("Run complete — FG batch {0}, {1} serial(s)").format(fg_batch_id, serials_made)
	if truncated_items:
		# Was silent before — a genuinely large run (2000+ real units) just
		# under-reported its serial count with nothing telling anyone it
		# happened. Now surfaced both in the immediate response (shown as
		# the alert after Advance/Complete) and logged for later audit.
		detail = ", ".join(f"{code} ({count})" for code, count in truncated_items)
		message += " " + _(
			"⚠ Serial generation capped at 2000 per item — {0} produced more than that; "
			"only the first 2000 got real IB FG Serial records each."
		).format(detail)
		frappe.log_error(
			title="IB FG Serial cap hit",
			message=f"Work Order {doc.name}: {detail} exceeded the 2000-serial-per-item cap.",
		)

	return {
		"message": message,
		"fg_batch": fg_batch_id,
		"serials": serials_made,
	}


def _recompute_osi_status(order_sheet, soi):
	"""Full, idempotent recompute of one Order Sheet Item's status from its
	REAL current run history — not an incremental "mark Completed and never
	look again" flag. Real bug this replaces: the old _settle_order_sheet
	only ever SET an item to Completed, never reconsidered it — cancel_run()
	reverses a Completed run's genealogy (deletes its FG serials/batch) but
	had no path to also un-complete the Order Sheet Item it had finished,
	so an order whose only completing run got cancelled still showed
	"Completed" / still passed get_order_dn_readiness — Create Delivery
	Note stayed open for production that had just been undone.

	Real rule: Completed only if at least one non-cancelled run for this
	item actually reached Completed AND nothing for it is still open
	(Pending/In Progress/On Hold). Any non-cancelled run existing at all
	(even if none finished yet) means real work has been attempted -> In
	Progress. Zero non-cancelled runs ever (fresh item, or every run for it
	got cancelled) -> Pending, matching a never-started item.
	"""
	row = frappe.db.get_value(
		"IB Order Sheet Item", {"parent": order_sheet, "sales_order_item": soi}, "name"
	)
	if not row:
		return
	runs = frappe.db.sql(
		"""SELECT w.status FROM `tabIB WO Output` o
		   JOIN `tabIB Work Order` w ON w.name = o.parent
		   WHERE o.sales_order_item = %s AND w.status != 'Cancelled'""",
		(soi,), as_dict=True,
	)
	if not runs:
		new_status = "Pending"
	elif any(r.status in ("Pending", "In Progress", "On Hold") for r in runs):
		new_status = "In Progress"
	elif any(r.status == "Completed" for r in runs):
		new_status = "Completed"
	else:
		new_status = "Pending"
	frappe.db.set_value("IB Order Sheet Item", row, "status", new_status)


def _roll_up_order_sheet_status(order_sheet):
	"""Order Sheet status from its items' CURRENT states — symmetric both
	ways (Completed can also revert back to In Progress), shared by both
	call sites that need it after changing an item's status (a run
	finishing via _settle_order_sheet, a run being cancelled via
	cancel_run) so the two can't drift into different rollup rules.

	Real gap, closed: create_run() flips a Draft Order Sheet to In Progress
	the moment its first run is created — but nothing ever flipped it back.
	Cancelling that one run (a real, expected action — wrong batch, wrong
	item, operator mistake) already reverts every one of its items back to
	Pending via _recompute_osi_status; the Order Sheet itself stayed stuck
	In Progress forever, permanently misrepresenting an order that has
	genuinely never had a single real production step happen on it. Confirmed
	live: create -> cancel one run on a fresh Draft Order Sheet left every
	item Pending but the sheet In Progress. Only reverts to Draft — never
	auto-promotes TO Draft from Completed, and never touches a sheet a user
	explicitly holds at some other real state — so this can't fight any
	other status this function or a human sets."""
	states = frappe.get_all(
		"IB Order Sheet Item", filters={"parent": order_sheet}, pluck="status"
	)
	current = frappe.db.get_value("IB Order Sheet", order_sheet, "status")
	if states and all(s == "Completed" for s in states):
		if current != "Completed":
			frappe.db.set_value("IB Order Sheet", order_sheet, "status", "Completed")
	elif current == "Completed":
		frappe.db.set_value("IB Order Sheet", order_sheet, "status", "In Progress")
	elif states and all(s == "Pending" for s in states) and current == "In Progress":
		frappe.db.set_value("IB Order Sheet", order_sheet, "status", "Draft")


def _settle_order_sheet(doc):
	"""Recompute every item this run produces, then roll the Order Sheet's
	own status up from them — symmetric both ways (Completed can also
	revert, see _recompute_osi_status's own comment for why that matters)."""
	if not doc.order_sheet:
		return
	osi_done = {o.sales_order_item for o in doc.outputs if o.sales_order_item}
	for soi in osi_done:
		_recompute_osi_status(doc.order_sheet, soi)
	_roll_up_order_sheet_status(doc.order_sheet)


# ---------------------------------------------------------------------------
# read APIs — run grain
# ---------------------------------------------------------------------------

_RUN_LIST_FIELDS = [
	"name", "sales_order", "order_sheet", "priority", "status", "location",
	"current_stage", "machine", "posting_date", "source_batch", "source_item",
	"source_qty", "total_output_qty", "total_wastage_qty", "started_at", "completed_at",
]


def _run_row(w, os_map=None, so_map=None):
	so = (so_map or {}).get(w.sales_order, {})
	route = frappe.get_all(
		"IB WO Route Stage", filters={"parent": w.name},
		fields=["stage", "sequence", "done"], order_by="sequence asc",
	)
	outs = frappe.get_all(
		"IB WO Output", filters={"parent": w.name},
		fields=["item_code", "item_name", "planned_qty", "produced_qty", "uom"],
	)
	return {
		"work_order": w.name,
		"sales_order": w.sales_order,
		"order_sheet": w.order_sheet,
		"customer": so.get("customer_name") or so.get("customer") or "",
		"delivery_date": str(so.get("delivery_date")) if so.get("delivery_date") else None,
		"priority": w.priority,
		"status": w.status,
		"location": w.location,
		"current_stage": w.current_stage,
		"machine": w.machine,
		"posting_date": str(w.posting_date) if w.posting_date else None,
		"source_batch": w.source_batch,
		"source_item": w.source_item,
		"source_qty": flt(w.source_qty),
		"total_output_qty": flt(w.total_output_qty),
		"total_wastage_qty": flt(w.total_wastage_qty),
		"started_at": str(w.started_at) if w.started_at else None,
		"completed_at": str(w.completed_at) if w.completed_at else None,
		"route": [{"stage": r.stage, "done": bool(r.done),
		           "is_current": r.stage == w.current_stage} for r in route],
		"outputs": [{"item_code": o.item_code, "item_name": o.item_name,
		             "planned_qty": flt(o.planned_qty), "produced_qty": flt(o.produced_qty),
		             "uom": o.uom} for o in outs],
	}


_STAGE_KEY = {s: s.lower().replace(" ", "_") for s in STAGES}


@frappe.whitelist()
def get_production_kpis(location=None):
	"""Dashboard cards + stage pipeline — run grain.

	Shape kept compatible with the old production.get_production_dashboard so
	ib_production_dashboard.js's _render_kpis / _render_pipeline need no change:
	  {summary: {active_work_orders, pending, in_progress, completed_today,
	             machines_active, avg_wastage_pct},
	   pipeline: [{stage: <lc_key>, pending, in_progress, on_hold, completed}]}
	"""
	_require_production_role()
	loc = location.lower() if location else None
	cond = "WHERE 1=1"
	params = {}
	if loc:
		cond += " AND location = %(loc)s"
		params["loc"] = loc

	rows = frappe.db.sql(
		f"SELECT status, current_stage, machine, completed_at FROM `tabIB Work Order` {cond}",
		params, as_dict=True,
	)
	today_d = getdate(today())
	in_progress = sum(1 for r in rows if r.status == "In Progress")
	on_hold = sum(1 for r in rows if r.status == "On Hold")
	pending = sum(1 for r in rows if r.status == "Pending")
	completed_today = sum(
		1 for r in rows if r.status == "Completed" and r.completed_at
		and getdate(r.completed_at) == today_d
	)
	machines_active = len({r.machine for r in rows if r.status == "In Progress" and r.machine})

	# stage events completed today, grouped by stage (the "completed" pipeline count)
	ev_today = frappe.db.sql(
		"""SELECT e.stage, COUNT(*) n
		   FROM `tabIB WO Stage Event` e JOIN `tabIB Work Order` w ON w.name = e.parent
		   WHERE DATE(e.completed_at) = %(d)s""" + (" AND w.location = %(loc)s" if loc else "") + """
		   GROUP BY e.stage""",
		{"d": nowdate(), "loc": loc}, as_dict=True,
	)
	done_by_stage = {r.stage: r.n for r in ev_today}

	# Warehouse-only locations (Maharashtra/Chennai) never run Coating/Slitting/
	# Rewinding/Cutting — physically nothing happens there but Packing. Showing
	# all 5 always-zero pipeline cards regardless of location was confusing (a
	# manager picking Maharashtra saw 4 dead cards next to the page's own hint
	# text explaining those stages don't apply there). Filter to the location's
	# real stage set; "All Locations" (no filter) keeps showing all 5, since a
	# company-wide view legitimately spans both models.
	pipeline_stages = _WAREHOUSE_STAGE_ROUTE if loc in _WAREHOUSE_ONLY_LOCATIONS else STAGES

	pipeline = []
	for s in pipeline_stages:
		at = [r for r in rows if r.current_stage == s]
		pipeline.append({
			"stage": _STAGE_KEY[s],
			"in_progress": sum(1 for r in at if r.status == "In Progress"),
			"on_hold": sum(1 for r in at if r.status == "On Hold"),
			"pending": sum(1 for r in at if r.status == "Pending"),
			"completed": done_by_stage.get(s, 0),
		})

	wr = frappe.db.sql(
		"""SELECT AVG(e.wastage_pct) AS avg_pct, SUM(e.wastage_qty) AS total_qty
		   FROM `tabIB WO Stage Event` e
		   JOIN `tabIB Work Order` w ON w.name = e.parent
		   WHERE e.skipped = 0 AND DATE(e.completed_at) = %(d)s
		   """ + (" AND w.location = %(loc)s" if loc else ""),
		{"d": nowdate(), "loc": loc}, as_dict=True,
	)
	wastage = wr[0] if wr else {}

	return {
		"summary": {
			"active_work_orders": in_progress + pending + on_hold,
			"pending": pending,
			# Real bug, fixed: the Dashboard tab's "Pending" KPI used to read
			# `pending` above (IB Work Order.status == "Pending") — under
			# this WO-per-run model create_run() never leaves a run Pending
			# (inserted already Started), so that's structurally always 0.
			# Confirmed live: 0 of 29 real Work Orders were ever Pending,
			# while the real not-yet-started backlog (Order Sheet Items with
			# no run yet — the same "Ready to Run" queue Command Center
			# shows) was 346. `pending` is kept above for anything else that
			# reads it; the Dashboard KPI now reads this instead.
			"ready_to_run": get_ready_to_run_count(loc),
			"in_progress": in_progress,
			"runs_on_hold": on_hold,
			"completed_today": completed_today,
			"machines_active": machines_active,
			"avg_wastage_pct": round(flt(wastage.get("avg_pct")), 2),
			"wastage_qty_today": round(flt(wastage.get("total_qty")), 2),
		},
		"pipeline": pipeline,
	}


@frappe.whitelist()
def get_stage_board(location=None):
	"""Stage-wise tab — live runs grouped by their current stage (one per run).

	Stage set is location-aware, same fix as get_production_kpis's Pipeline
	cards: a warehouse-only location (Maharashtra/Chennai) only ever has
	Packing — showing 4 permanently-zero pills (Coating/Slitting/Rewinding/
	Cutting), defaulting to "Coating" (which can never have anything under
	it there), was the same dead-UI confusion already fixed on the Dashboard
	tab but missed here.
	"""
	_require_production_role()
	loc = location.lower() if location else None
	filters = {"status": ["in", _LIVE_STATUSES]}
	if loc:
		filters["location"] = loc
	rows = frappe.get_all("IB Work Order", filters=filters, fields=_RUN_LIST_FIELDS,
	                      order_by="field(priority,'Urgent','High','Normal','Low'), posting_date asc")
	so_map = {}
	so_names = list({r.sales_order for r in rows if r.sales_order})
	if so_names:
		for s in frappe.get_all("Sales Order", filters={"name": ["in", so_names]},
		                        fields=["name", "customer", "customer_name", "delivery_date"]):
			so_map[s.name] = s
	stage_set = _WAREHOUSE_STAGE_ROUTE if loc in _WAREHOUSE_ONLY_LOCATIONS else STAGES
	board = {s: [] for s in stage_set}
	for r in rows:
		key = r.current_stage if r.current_stage in board else (r.current_stage or "—")
		board.setdefault(key, []).append(_run_row(r, so_map=so_map))
	return {"stages": stage_set, "board": board,
	        "counts": {k: len(v) for k, v in board.items()}}


@frappe.whitelist()
def get_item_wise_board(location=None, item_code=None):
	"""Item-wise tab — output SKUs across runs, each with its run's route matrix.

	Cancelled runs are excluded — a Cancelled Work Order (e.g. the parent of a
	length-split, or a plain restarted/reworked run) still carries its own
	full route table, and summing it in with its live replacement(s) produced
	nonsense stage-completion fractions like "11/15 stages" for what a floor
	user sees as one single item still in progress. Confirmed live: a real
	380kg BOPP run split via advance_with_length_split left a Cancelled
	parent (5-stage route) sitting alongside its 2 live children (5 stages
	each) under the same item_code, inflating the denominator to 15.
	"""
	_require_production_role()
	filters = {"status": ["!=", "Cancelled"]}
	if location:
		filters["location"] = location.lower()
	runs = frappe.get_all("IB Work Order", filters=filters, fields=_RUN_LIST_FIELDS,
	                      order_by="posting_date desc")
	so_map = {}
	so_names = list({r.sales_order for r in runs if r.sales_order})
	if so_names:
		for s in frappe.get_all("Sales Order", filters={"name": ["in", so_names]},
		                        fields=["name", "customer", "customer_name", "delivery_date"]):
			so_map[s.name] = s

	out = []
	for r in runs:
		row = _run_row(r, so_map=so_map)
		for o in row["outputs"]:
			if item_code and o["item_code"] != item_code:
				continue
			out.append({
				"item_code": o["item_code"],
				"item_name": o["item_name"],
				"planned_qty": o["planned_qty"],
				"produced_qty": o["produced_qty"],
				"uom": o["uom"],
				"work_order": row["work_order"],
				"sales_order": row["sales_order"],
				"customer": row["customer"],
				"status": row["status"],
				"machine": row["machine"],
				"current_stage": row["current_stage"],
				"route": row["route"],
			})
	return out


# ---------------------------------------------------------------------------
# DPR — real per-stage output / wastage / hours from IB WO Stage Event
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# sales-facing progress (new shape) — replaces production._so_progress_pct path
# ---------------------------------------------------------------------------

def _so_progress(sales_order):
	"""(pct, current_stage, order_sheet) for a Sales Order from its runs."""
	os_name = frappe.db.get_value(
		"IB Order Sheet", {"sales_order": sales_order, "status": ["!=", "Cancelled"]}, "name"
	)
	if not os_name:
		return None, None, None
	runs = frappe.get_all(
		"IB Work Order",
		filters={"order_sheet": os_name, "status": ["!=", "Cancelled"]},
		fields=["name", "status", "current_stage"],
	)
	if not runs:
		return 0.0, None, os_name

	total_steps = done_steps = 0
	active = []
	for run in runs:
		route = frappe.get_all("IB WO Route Stage", filters={"parent": run.name},
		                       fields=["stage", "done", "sequence"], order_by="sequence asc")
		total_steps += len(route)
		done_steps += sum(1 for r in route if r.done)
		if run.status in ("In Progress", "On Hold") and run.current_stage not in (None, "Done"):
			active.append(run.current_stage)
	pct = round(done_steps / total_steps * 100, 1) if total_steps else 0.0
	current = None
	if active:
		order_idx = {s: i for i, s in enumerate(STAGES)}
		current = min(active, key=lambda s: order_idx.get(s, 999))
	elif pct >= 100:
		current = "Ready to Deliver"
	return pct, current, os_name


def on_work_order_update_notify(doc, method=None):
	"""IB Work Order on_update — milestone bell to the sales person (run grain)."""
	if doc.status != "Completed":
		return
	if not doc.get("order_sheet"):
		return
	so_name = frappe.db.get_value("IB Order Sheet", doc.order_sheet, "sales_order")
	if not so_name:
		return
	sales_person_user = frappe.db.get_value("Sales Order", so_name, "custom_sales_person_user")
	if not sales_person_user:
		return
	pct, current_stage, _os = _so_progress(so_name)
	if pct is None:
		return
	milestone = max((m for m in (25, 50, 75, 100) if pct >= m), default=None)
	if milestone is None:
		return
	marker = f"[ib-prod-{so_name}-{milestone}]"
	if frappe.db.exists("Notification Log", {"for_user": sales_person_user, "subject": ["like", f"%{marker}%"]}):
		return
	customer = frappe.db.get_value("Sales Order", so_name, "customer_name") or ""
	if milestone == 100:
		subject = f"Order Ready for Dispatch: {so_name}"
		body = (f"<p>Sales Order <strong>{so_name}</strong> for <strong>{customer}</strong> "
		        f"has completed all production stages and is <strong>Ready to Deliver</strong>.</p>")
	else:
		stage_txt = f" — now in <strong>{current_stage}</strong>" if current_stage else ""
		subject = f"Production Update: {so_name} is {milestone}% complete"
		body = (f"<p>Sales Order <strong>{so_name}</strong> for <strong>{customer}</strong> "
		        f"is now <strong>{milestone}% through production</strong>{stage_txt}.</p>")
	frappe.get_doc({
		"doctype": "Notification Log",
		"subject": f"{subject} {marker}"[:140],
		"email_content": body,
		"for_user": sales_person_user,
		"type": "Alert",
		"document_type": "Sales Order",
		"document_name": so_name,
		"from_user": "Administrator",
	}).insert(ignore_permissions=True)
	frappe.db.commit()


# ---------------------------------------------------------------------------
# Dashboard-compat read APIs
# ---------------------------------------------------------------------------
# These keep the exact response contract the *existing* ib_production_dashboard.js
# render functions expect (a run is presented as an Order-Sheet card with one
# "item row" per output, and each row's `stage_map` is built from the run's
# `route`), so the UI is adapted — not rebuilt — for the run model.

_ROW_BTN_STATUS = {"In Progress": "In Progress", "On Hold": "On Hold",
                   "Pending": "Pending", "Completed": "Completed", "Cancelled": "Cancelled"}


def _latest_run_for_osi(soi, item_code, os_name):
	"""The run currently producing an Order Sheet Item — matched by
	outputs.sales_order_item, item_code fallback, newest non-cancelled first."""
	rows = _all_runs_for_osi(soi, item_code, os_name)
	return rows[-1] if rows else None


def _all_runs_for_osi(soi, item_code, os_name):
	"""EVERY non-cancelled run producing an Order Sheet Item, oldest first.

	An item is not always produced by exactly one run — confirmed live,
	real data (IB-OS-2026-02860 / IS-51211V-038TRWBNL): a partial run held
	or a length-split can leave 2+ separate real runs against the same
	item. get_order_sheet_detail() used to call the single-row
	_latest_run_for_osi() here, silently hiding every earlier run's own
	stage progress/machine history from the Order-wise tab — the item's
	own `qty` still showed the true total, but the stage-chip row only
	ever reflected whichever run happened to be created last, making the
	tab look wrong/incomplete for exactly this "one order took two runs"
	case. Returns oldest-first so callers building a chip row read
	left-to-right in the order the runs actually happened.
	"""
	return frappe.db.sql(
		"""SELECT w.name, w.status, w.current_stage, w.machine, w.priority,
		          w.source_batch, w.source_qty, w.posting_date, w.started_at,
		          w.completed_at, w.fg_batch, w.pcs_to_make, w.logs_to_make,
		          o.uom, o.planned_qty, o.produced_qty
		   FROM `tabIB Work Order` w
		   JOIN `tabIB WO Output` o ON o.parent = w.name
		   WHERE w.order_sheet = %(os)s AND w.status != 'Cancelled'
		     AND (o.sales_order_item = %(soi)s OR (o.sales_order_item = '' AND o.item_code = %(ic)s))
		   ORDER BY w.creation ASC""",
		{"os": os_name, "soi": soi or "", "ic": item_code}, as_dict=True,
	)


def _stage_map_for_run(run):
	"""{StageLabel: {status, wo_name, completed_qty, target_qty, target_uom}} from
	the run's route + stage_log.

	Real gap, fixed here: a `done` stage previously always showed status
	"Completed" — including one that was actually skip_stage()'d (no real
	work done, real output_qty always 0 for that stage's own event row).
	Since skip_stage's UI entry point didn't exist until this same session
	(see its own docstring/commit), this state was never reachable before
	and the gap was invisible; now that it is reachable, a skipped stage
	would render identically to a genuinely-worked, zero-output stage
	everywhere this feeds (Active Production Plan, Order-wise chip row) —
	indistinguishable from a real data problem. Kept as its own "Skipped"
	status instead.
	"""
	route = frappe.get_all(
		"IB WO Route Stage", filters={"parent": run.name},
		fields=["stage", "sequence", "done"], order_by="sequence asc",
	)
	events = {e.stage: e for e in frappe.get_all(
		"IB WO Stage Event", filters={"parent": run.name},
		fields=["stage", "output_qty", "skipped"],
	)}
	tgt_uom = run.get("uom") or ""
	smap = {}
	for r in route:
		ev = events.get(r.stage)
		if r.done and ev and ev.skipped:
			st = "Skipped"
		elif r.done:
			st = "Completed"
		elif r.stage == run.current_stage:
			st = run.status if run.status in ("In Progress", "On Hold") else "Pending"
		else:
			st = "Pending"
		smap[r.stage] = {
			"status": st,
			"wo_name": run.name,
			"completed_qty": flt(ev.output_qty) if (r.done and ev and not ev.skipped) else 0,
			"target_qty": flt(run.get("source_qty")) or flt(run.get("planned_qty")),
			"target_uom": tgt_uom,
			# Real bug, fixed (QC pass, subagent-confirmed live): hardcoded to
			# 0 unconditionally — since 0 is falsy, the Dashboard's "adj →"
			# badge (which only renders when pcs_to_make/logs_to_make differ
			# from target_qty) could never show, regardless of what a manager
			# actually set via the (separately correct) Adjust Qty dialog /
			# update_production_qty(). _all_runs_for_osi's own SELECT now
			# carries these two real columns through; read them here instead
			# of a literal 0.
			"pcs_to_make": cint(run.get("pcs_to_make")) or 0,
			"logs_to_make": cint(run.get("logs_to_make")) or 0,
		}
	return smap, route


def _plan_item_row(osi, os_name, location):
	run = _latest_run_for_osi(osi.get("sales_order_item"), osi["item_code"], os_name)
	base = {
		"name": osi["name"],
		"item_code": osi["item_code"],
		"item_name": osi.get("item_name"),
		"qty": flt(osi.get("qty")),
		"uom": osi.get("uom"),
		# Was missing entirely — see get_osi_context_batch's own comment for
		# why this specific omission is what let the bulk Start Run dialog
		# silently drop sales_order_item on every item past the first one.
		"sales_order_item": osi.get("sales_order_item"),
	}
	if not run:
		route = _get_stage_route(osi["item_code"], location)
		base.update({
			"current_stage": "",
			"stage_map": {},
			"route_length": len(route),
			"route_completed_count": 0,
			"is_fully_done": False,
			"next_stage_suggestion": route[0] if route else "",
		})
		return base
	smap, route = _stage_map_for_run(run)
	done = sum(1 for r in route if r.done)
	is_done = run.status == "Completed"
	base.update({
		"current_stage": "" if run.current_stage in (None, "Done", "Cancelled") else run.current_stage,
		"stage_map": smap,
		"route_length": len(route),
		"route_completed_count": done,
		"is_fully_done": is_done,
		"next_stage_suggestion": "",
		"run": run.name,
		"run_status": run.status,
	})
	return base


@frappe.whitelist()
def get_run_plan(limit=None, start=0, location=None, search=None, priority=None):
	"""Active Production Plan (Dashboard tab) — Order-Sheet cards, one item row
	per Order Sheet Item, each row carrying its run's stage_map. Same
	{order_wise: [...]} contract as the old production.get_production_plan."""
	_require_production_role()
	limit = cint(limit) or 25
	start = cint(start)

	conds = ["os.status != 'Cancelled'"]
	params = {}
	if location:
		conds.append("LOWER(so.custom_location) = %(loc)s")
		params["loc"] = location.lower()
	if priority:
		conds.append("os.priority = %(prio)s")
		params["prio"] = priority
	if search:
		conds.append("(os.sales_order LIKE %(s)s OR os.customer_name LIKE %(s)s OR EXISTS "
		             "(SELECT 1 FROM `tabIB Order Sheet Item` i WHERE i.parent = os.name AND i.item_code LIKE %(s)s))")
		params["s"] = f"%{search}%"

	sheets = frappe.db.sql(
		f"""SELECT os.name, os.sales_order, os.customer, os.customer_name, os.status,
		           os.priority, os.delivery_date, os.creation, so.custom_location AS location
		    FROM `tabIB Order Sheet` os
		    JOIN `tabSales Order` so ON so.name = os.sales_order
		    WHERE {' AND '.join(conds)}
		    ORDER BY FIELD(os.priority,'Urgent','High','Normal','Low'), os.creation DESC
		    LIMIT %(lim)s OFFSET %(off)s""",
		dict(params, lim=limit, off=start), as_dict=True,
	)
	out = []
	for sh in sheets:
		items = frappe.get_all(
			"IB Order Sheet Item", filters={"parent": sh.name},
			fields=["name", "item_code", "item_name", "qty", "uom", "sales_order_item"],
		)
		loc = (sh.location or "").lower() or None
		rows = [_plan_item_row(dict(it), sh.name, loc) for it in items]
		out.append({
			"name": sh.name,
			"sales_order": sh.sales_order,
			"customer": sh.customer,
			"customer_name": sh.customer_name,
			"status": sh.status,
			"priority": sh.priority,
			"delivery_date": str(sh.delivery_date) if sh.delivery_date else None,
			"creation": str(sh.creation),
			"comment_count": 0,
			"items": rows,
		})
	return {"order_wise": out}


# ---------------------------------------------------------------------------
# Command Center — factory-manager live board (2026-09-20)
# ---------------------------------------------------------------------------
# create_run() always inserts a run already Started (Pending -> In Progress in
# one call, see its own docstring) — there is no persisted "Pending, not yet
# started" IB Work Order under the run model. So the only two real live
# states a run itself can sit in are In Progress ("Processing") and On Hold
# ("Halted"); the third card type here ("Ready") isn't a run at all, it's an
# Order Sheet Item with zero non-Cancelled run ever created against it —
# i.e. exactly what _plan_item_row's `next_stage_suggestion` branch means,
# just queried directly/flat instead of per-page-of-25-Order-Sheets.


def _command_center_runs(location=None):
	conds = ["wo.status IN ('In Progress', 'On Hold')"]
	params = {}
	if location:
		conds.append("LOWER(wo.location) = %(loc)s")
		params["loc"] = location.lower()
	rows = frappe.db.sql(
		f"""SELECT wo.name, wo.sales_order, wo.order_sheet, wo.status, wo.priority,
		           wo.location, wo.current_stage, wo.machine, wo.started_at, wo.notes,
		           so.customer_name
		    FROM `tabIB Work Order` wo
		    LEFT JOIN `tabSales Order` so ON so.name = wo.sales_order
		    WHERE {' AND '.join(conds)}
		    ORDER BY FIELD(wo.priority, 'Urgent', 'High', 'Normal', 'Low'), wo.started_at ASC""",
		params, as_dict=True,
	)
	names = [r.name for r in rows]
	outs_by_wo = {}
	if names:
		for o in frappe.get_all(
			"IB WO Output", filters={"parent": ["in", names]},
			fields=["parent", "item_code", "item_name", "planned_qty", "produced_qty", "uom"],
		):
			outs_by_wo.setdefault(o.parent, []).append(o)
	out = []
	for r in rows:
		outs = outs_by_wo.get(r.name, [])
		out.append({
			"work_order": r.name, "sales_order": r.sales_order, "order_sheet": r.order_sheet,
			"status": r.status, "priority": r.priority or "Normal", "location": r.location,
			"current_stage": r.current_stage, "machine": r.machine,
			"started_at": str(r.started_at) if r.started_at else None,
			"customer": r.customer_name, "notes": r.notes,
			"item_code": outs[0].item_code if outs else "",
			"item_name": outs[0].item_name if outs else "",
			"extra_items": len(outs) - 1 if len(outs) > 1 else 0,
			"planned_qty": sum(flt(o.planned_qty) for o in outs),
			"produced_qty": sum(flt(o.produced_qty) for o in outs),
			"uom": outs[0].uom if outs else "",
		})
	return out


def _ready_to_run_conds(location=None):
	# "No run" = zero IB WO Output rows for this Order Sheet Item on any
	# non-Cancelled run, ever — the same condition _plan_item_row's `if not
	# run:` branch checks via _latest_run_for_osi, just as one set query
	# across every Order Sheet instead of one _latest_run_for_osi() call per
	# item (get_run_plan's page-of-25 approach doesn't scale to "every
	# not-yet-started item company-wide", which is what a control room
	# actually needs to show as the queue).
	# IB WO Output has no `order_sheet_item` field at all (real fields:
	# item_code/planned_qty/produced_qty/.../sales_order_item) — the real,
	# shared key between an Order Sheet Item and the WO Output row(s) it was
	# ever produced through is `sales_order_item` (both point at the same
	# real Sales Order Item). Blank-vs-blank must never count as a match —
	# an OSI with no sales_order_item set would otherwise look "already
	# produced" the moment ANY unrelated run also had a blank one.
	conds = ["os.status != 'Cancelled'", "i.status != 'Completed'", """NOT EXISTS (
		SELECT 1 FROM `tabIB WO Output` o
		JOIN `tabIB Work Order` w ON w.name = o.parent
		WHERE o.sales_order_item = i.sales_order_item
		  AND i.sales_order_item IS NOT NULL AND i.sales_order_item != ''
		  AND w.status != 'Cancelled'
	)"""]
	params = {}
	if location:
		conds.append("LOWER(so.custom_location) = %(loc)s")
		params["loc"] = location.lower()
	return conds, params


def get_ready_to_run_count(location=None):
	"""Real total — NOT capped by _command_center_ready's own LIMIT 60 (that
	limit bounds how many cards a live board renders, not how many items are
	actually queued). Real bug this fixes: get_command_center_data's own
	`counts.ready` was `len(ready)` — always <= 60 by construction, so the
	Command Center KPI showed "60" when the real queue (confirmed live) was
	346 — a silent 5.7x understatement with no indication anything was
	capped. Also backs the Dashboard tab's own KPI (see get_production_kpis)
	— that card used to read IB Work Order.status == 'Pending', which is
	structurally always 0 under this WO-per-run model (create_run never
	leaves a WO Pending — it's inserted already Started), a dead metric
	confirmed live: 0 of 29 real Work Orders were ever Pending, while the
	real ready-to-start backlog was 346. Both cards now read this same real
	count, cheap on its own (a plain COUNT(*), same WHERE as the capped list)."""
	conds, params = _ready_to_run_conds(location)
	return cint(frappe.db.sql(
		f"""SELECT COUNT(*) FROM `tabIB Order Sheet Item` i
		    JOIN `tabIB Order Sheet` os ON os.name = i.parent
		    JOIN `tabSales Order` so ON so.name = os.sales_order
		    WHERE {' AND '.join(conds)}""",
		params,
	)[0][0])


def _command_center_ready(location=None, limit=60):
	conds, params = _ready_to_run_conds(location)
	rows = frappe.db.sql(
		f"""SELECT i.name, i.item_code, i.item_name, i.qty, i.uom, i.sales_order_item,
		           os.name AS order_sheet, os.sales_order, os.customer_name, os.priority, os.creation,
		           so.custom_location AS location
		    FROM `tabIB Order Sheet Item` i
		    JOIN `tabIB Order Sheet` os ON os.name = i.parent
		    JOIN `tabSales Order` so ON so.name = os.sales_order
		    WHERE {' AND '.join(conds)}
		    ORDER BY FIELD(os.priority, 'Urgent', 'High', 'Normal', 'Low'), os.creation ASC
		    LIMIT %(lim)s""",
		dict(params, lim=cint(limit)), as_dict=True,
	)
	out = []
	for r in rows:
		loc = (r.location or "").lower() or None
		route = _get_stage_route(r.item_code, loc)
		out.append({
			"order_sheet_item": r.name, "item_code": r.item_code, "item_name": r.item_name,
			"qty": flt(r.qty), "uom": r.uom, "sales_order_item": r.sales_order_item,
			"order_sheet": r.order_sheet, "sales_order": r.sales_order, "customer": r.customer_name,
			"priority": r.priority or "Normal", "location": loc,
			"next_stage_suggestion": route[0] if route else "",
		})
	return out


@frappe.whitelist()
def get_command_center_data(location=None):
	"""Factory-manager live control board — every genuinely active run
	(Processing/Halted) plus the queue of items with nothing started yet
	(Ready), across one or all locations. Drives the Command Center tab;
	callers should re-poll/re-fetch on the existing "ib_floor_update"
	realtime event (already published by create_run/hold_run/resume_run/
	advance_run/skip_stage/_finish_run) rather than a fixed interval.
	"""
	_require_production_role()
	runs = _command_center_runs(location)
	processing = [r for r in runs if r["status"] == "In Progress"]
	halted = [r for r in runs if r["status"] == "On Hold"]
	ready = _command_center_ready(location)
	ready_total = get_ready_to_run_count(location)
	return {
		"processing": processing,
		"halted": halted,
		"ready": ready,
		# "ready" (the rendered list) stays capped at _command_center_ready's
		# own limit=60 -- a live board doesn't need 300+ cards on screen --
		# but the count must be the real total, not len(ready). See
		# get_ready_to_run_count's own docstring for the live bug this fixes.
		"counts": {"processing": len(processing), "halted": len(halted), "ready": ready_total},
		"ready_shown": len(ready),
	}


@frappe.whitelist()
def get_order_sheet_detail(order_sheet):
	"""Order-wise tab drill-in. Same {order_sheet, order_wise_view} contract as
	the old production.get_order_sheet_detail — but `work_orders` per item row is
	the run(s) producing it, expanded to one entry per route stage (so the
	stage-chip row renders), each chip opening the run panel."""
	_require_production_role()
	os_doc = frappe.db.get_value(
		"IB Order Sheet", order_sheet,
		["name", "sales_order", "customer", "customer_name", "status", "priority",
		 "delivery_date", "order_date"], as_dict=True,
	)
	if not os_doc:
		frappe.throw(_("Order Sheet {0} not found").format(order_sheet))
	location = (frappe.db.get_value("Sales Order", os_doc.sales_order, "custom_location") or "").lower() or None

	items = frappe.get_all(
		"IB Order Sheet Item", filters={"parent": order_sheet},
		fields=["name", "item_code", "item_name", "qty", "uom", "sales_order_item"],
	)
	view = []
	for it in items:
		runs = _all_runs_for_osi(it.sales_order_item, it.item_code, order_sheet)
		wo_entries = []
		all_wo_objects = []  # one full panel-openable dict per run — see wo_data below
		next_sugg = ""
		current_wo = None
		total_produced = 0.0
		# Every non-cancelled run producing this item, not just the latest —
		# see _all_runs_for_osi's own comment for why (a partial/held run
		# followed by a second run, or a length-split, both leave 2+ real
		# runs against one item; showing only the newest one hid the
		# earlier run's stage/machine history entirely).
		for run in runs:
			smap, route = _stage_map_for_run(run)
			total_produced += flt(run.produced_qty)
			for r in route:
				info = smap[r.stage]
				is_current = r.stage == run.current_stage
				wo_entries.append({
					"name": run.name,
					"stage": r.stage,
					"status": info["status"],
					"completed_qty": info["completed_qty"],
					"target_qty": info["target_qty"],
					"target_uom": info["target_uom"],
					"creation": str(run.posting_date) if run.posting_date else None,
					# Same fix as _stage_map_for_run's own copy of this —
					# hardcoded 0 made the Order-wise/WO-panel "adj" indicator
					# blind to whatever a manager actually set via Adjust Qty.
					"pcs_to_make": info.get("pcs_to_make", 0), "logs_to_make": info.get("logs_to_make", 0),
					# Every one of a run's 5 stage chips describes the SAME
					# real Work Order (one run, expanded per route stage for
					# the pill row) — only one is ever actually actionable.
					# is_current flags it so the frontend doesn't open the
					# panel using whichever pseudo-stage entry happened to be
					# rendered/clobbered last (was always "Packing", the last
					# stage in route order, regardless of which pill was
					# clicked or the run's real current stage — confirmed
					# live). With multiple runs now in play, at most one
					# chip across ALL of them is_current at a time.
					"is_current": is_current,
				})
			# Real current-state object for opening the WO panel — same shape
			# _run_row()-derived data uses elsewhere. Built for EVERY run
			# (not just whichever ends up "the" current_wo below) so the
			# frontend can populate _wo_data for every chip it renders —
			# without this, clicking an older/completed run's chip silently
			# did nothing (its name was never in _wo_data at all).
			cur_info = smap.get(run.current_stage) or {}
			all_wo_objects.append({
				"name": run.name,
				"stage": run.current_stage,
				"status": run.status,
				"machine": run.machine,
				"priority": os_doc.priority,
				"sales_order": os_doc.sales_order,
				"customer_name": os_doc.customer_name,
				"order_sheet": order_sheet,
				"completed_qty": cur_info.get("completed_qty", 0),
				"target_qty": cur_info.get("target_qty") or flt(run.planned_qty),
				"target_uom": cur_info.get("target_uom") or run.uom,
				"creation": str(run.posting_date) if run.posting_date else None,
				"delivery_date": str(os_doc.delivery_date) if os_doc.delivery_date else None,
				"pcs_to_make": cur_info.get("pcs_to_make", 0), "logs_to_make": cur_info.get("logs_to_make", 0),
			})

		if runs:
			# current_wo = whichever run is actually live right now (there's
			# at most one — a second run only ever gets created once the
			# first one is Completed/Cancelled); falls back to the most
			# recent run (last in oldest-first `runs`) if none are live, so
			# there's always something sane to open.
			live = next((r for r in runs if r.status in ("In Progress", "On Hold")), None)
			latest = runs[-1]
			target = live or latest
			current_wo = all_wo_objects[runs.index(target)]
			if latest.status == "Completed":
				next_sugg = ""
			elif latest.current_stage in (None, "Done"):
				next_sugg = ""
		else:
			rt = _get_stage_route(it.item_code, location)
			next_sugg = rt[0] if rt else ""
		view.append({
			"name": it.name,
			"item_code": it.item_code,
			"item_name": it.item_name,
			"qty": flt(it.qty),
			"uom": it.uom,
			"next_stage_suggestion": next_sugg,
			"work_orders": wo_entries,
			"current_wo": current_wo,
			# Every run's own panel data, keyed by run name — frontend needs
			# this to make every chip clickable, not just the current run's.
			"wo_data": {w["name"]: w for w in all_wo_objects},
			"total_produced_qty": round(total_produced, 4),
			"run_count": len(runs),
		})

	return {
		"order_sheet": {
			"name": os_doc.name,
			"sales_order": os_doc.sales_order,
			"customer": os_doc.customer,
			"customer_name": os_doc.customer_name,
			"status": os_doc.status,
			"priority": os_doc.priority,
			"delivery_date": str(os_doc.delivery_date) if os_doc.delivery_date else None,
			"order_date": str(os_doc.order_date) if os_doc.order_date else None,
		},
		"order_wise_view": view,
	}


