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

	# Prefer same-location machines; fall back to any
	preferred = [m for m in machines if not location or m.location == location]
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
def _auto_assign_machine(stage, location=None):
	return _assign_machine_load_balanced(stage, location)


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
	"""KPIs + stage pipeline counts + recent entries.

	location: optional Sales Order custom_location filter (maharashtra/gujarat/chennai) —
	narrows every count below to Work Orders whose Order Sheet's Sales Order is there.
	"""
	_require_production_role()
	today_date = today()

	loc_filter = ""
	params = {"today": today_date, "location": location}
	if location:
		loc_filter = """AND wo.order_sheet IN (
			SELECT os.name FROM `tabIB Order Sheet` os
			JOIN `tabSales Order` so ON so.name = os.sales_order
			WHERE so.custom_location = %(location)s
		)"""

	active_wo = frappe.db.sql(
		f"SELECT COUNT(*) FROM `tabIB Work Order` wo WHERE wo.status NOT IN ('Completed','Cancelled') {loc_filter}",
		params,
	)[0][0]
	pending_wo = frappe.db.sql(
		f"SELECT COUNT(*) FROM `tabIB Work Order` wo WHERE wo.status = 'Pending' {loc_filter}",
		params,
	)[0][0]

	completed_today = frappe.db.sql(
		f"""
		SELECT COUNT(*) FROM `tabIB Work Order` wo
		WHERE wo.status = 'Completed'
		  AND DATE(COALESCE(wo.completed_at, wo.modified)) = %(today)s
		  {loc_filter}
		""",
		params,
	)[0][0]

	machines_active = frappe.db.count(
		"IB Machine", {"status": "Active", **({"location": location} if location else {})}
	)

	# Stage pipeline
	# "In Progress" and "Completed" counts are always real (those states only
	# ever occur on an item's genuine current/already-passed stage). "Pending"
	# is not — auto_create_all_stage_wos() pre-creates one WO per stage in an
	# item's whole route up front, so a plain GROUP BY stage/status counted
	# every future stage's placeholder WO as if it were real backlog sitting
	# at that station (same root cause as the Stage-wise/Job Bundles fix
	# above). Confirmed live 2026-08-06: Packing and Ready to Deliver both
	# showed pending=42 (identical) here, while Stage-wise's corrected
	# current-position count for the same data was Packing=13, RTD=0. Fixed
	# by computing each item's true current stage (first non-Completed in
	# route order) the same way get_stage_pipeline() does, and only counting
	# a WO into "pending" when it IS that item's current stage.
	all_wo_rows = frappe.db.sql(
		f"""
		SELECT wo.stage, wo.status, wo.order_sheet, wo.order_sheet_item, wo.item_code
		FROM `tabIB Work Order` wo
		WHERE wo.status != 'Cancelled' {loc_filter}
		""",
		params,
		as_dict=True,
	)
	# Use lowercase_underscore keys so JS STAGE_COLORS lookup works directly
	def _stage_key(s):
		return s.lower().replace(" ", "_")

	# Warehouse-only locations never run Coating/Slitting/Rewinding/Cutting — don't
	# even show those as empty cards when a warehouse location is selected.
	visible_stages = (
		_WAREHOUSE_STAGE_ROUTE
		if (location or "").lower() in _WAREHOUSE_ONLY_LOCATIONS
		else STAGES
	)
	stage_map = {s: {"stage": _stage_key(s), "pending": 0, "in_progress": 0, "completed": 0} for s in visible_stages}

	def _ensure_stage(stage):
		if stage not in stage_map:
			if location and stage not in visible_stages:
				return None
			stage_map[stage] = {"stage": _stage_key(stage), "pending": 0, "in_progress": 0, "completed": 0}
		return stage_map[stage]

	stage_rank = {s: i for i, s in enumerate(STAGES)}
	item_groups = {}
	for row in all_wo_rows:
		if row.status == "In Progress":
			sm = _ensure_stage(row.stage)
			if sm:
				sm["in_progress"] += 1
		elif row.status == "Completed":
			sm = _ensure_stage(row.stage)
			if sm:
				sm["completed"] += 1
		key = row.order_sheet_item or f"{row.order_sheet}::{row.item_code}"
		item_groups.setdefault(key, []).append(row)

	for wos in item_groups.values():
		wos.sort(key=lambda r: stage_rank.get(r.stage, 999))
		current = next((r for r in wos if r.status != "Completed"), None)
		if current and current.status == "Pending":
			sm = _ensure_stage(current.stage)
			if sm:
				sm["pending"] += 1

	stage_pipeline = [stage_map[s] for s in STAGES if s in stage_map]

	# Priority overview — lowercase keys match JS badge lookup
	priority_rows = frappe.db.sql(
		f"""
		SELECT os.priority, COUNT(*) AS cnt
		FROM `tabIB Work Order` wo
		JOIN `tabIB Order Sheet` os ON os.name = wo.order_sheet
		WHERE 1=1 {loc_filter}
		GROUP BY os.priority
		""",
		params,
		as_dict=True,
	)
	priority_overview = {"urgent": 0, "high": 0, "normal": 0, "low": 0}
	for row in priority_rows:
		if row.priority:
			priority_overview[row.priority.lower()] = row.cnt

	# Wastage today — IB Production Entry is never populated in real usage (0 rows,
	# verified live) even though a capture dialog exists; source from completed Work
	# Orders instead, same fallback pattern already used in get_dpr().
	wastage_result = frappe.db.sql(
		f"""
		SELECT AVG(wo.wastage_pct) FROM `tabIB Work Order` wo
		WHERE wo.status = 'Completed' AND DATE(COALESCE(wo.completed_at, wo.modified)) = %(today)s
		{loc_filter}
		""",
		params,
	)
	wastage_today = round(flt(wastage_result[0][0]), 1) if wastage_result and wastage_result[0][0] else 0.0

	# Recent 10 completions (IB Production Entry has no real data — see above)
	recent_entries = frappe.db.sql(
		f"""
		SELECT wo.name, wo.stage, wo.machine, wo.completed_qty AS output_qty,
			wo.wastage_pct, DATE(COALESCE(wo.completed_at, wo.modified)) AS entry_date
		FROM `tabIB Work Order` wo
		WHERE wo.status = 'Completed'
		{loc_filter}
		ORDER BY COALESCE(wo.completed_at, wo.modified) DESC
		LIMIT 10
		""",
		params,
		as_dict=True,
	)

	return {
		"summary": {
			"active_work_orders": active_wo,
			"pending": pending_wo,
			"completed_today": completed_today,
			"machines_active": machines_active,
		},
		"pipeline": stage_pipeline,
		"priority_overview": priority_overview,
		"avg_wastage_today": wastage_today,
		"recent_entries": recent_entries,
	}


# ---------------------------------------------------------------------------
# 2. Machines
# ---------------------------------------------------------------------------

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

	# Item counts and completed item counts per order sheet
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
		completed = counts.completed_items if counts else 0
		progress_pct = round((flt(completed) / flt(total) * 100), 1) if total else 0.0
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
	"""Return each item's CURRENT stage only, grouped by stage — powers the
	Stage-wise view (a stage picker + flat table, not the old drag-and-drop
	Kanban this function originally backed — that was removed 2026-07-30 for
	being confusing, see item 119; this query survived, unwired, until now).
	On Hold is included deliberately: a stage supervisor's most important row
	is what's stuck at their own station, not just what's actively moving —
	the old Kanban-era query only ever showed Pending/In Progress.

	auto_create_all_stage_wos() pre-creates one IB Work Order per stage in an
	item's whole route up front (see item 84) — a 4-stage item that hasn't
	started yet already has 4 real WO rows, all sitting Pending. A naive
	"every Pending/In Progress/On Hold WO" query (the original shape of this
	function) therefore showed that one item at all 4 of its stages
	simultaneously, before it had actually reached any of them — confirmed
	live 2026-08-05. Fixed by grouping WOs per item (order_sheet_item, same
	key _update_order_sheet_item() uses, falling back to order_sheet+item_code
	for legacy WOs missing it) and keeping only that item's CURRENT stage: the
	first stage in STAGES order that's In Progress/On Hold, else the earliest
	Pending one — same "current_stage" rule already used elsewhere in this
	file (see get_production_plan()'s order_wise item loop).

	Returns everything for every stage in one call (counts double as each
	stage pill's badge) rather than a per-stage endpoint — this page's real
	WO volume doesn't justify N+1 fetches every time the picker changes tabs.
	"""
	_require_production_role()
	# Completed WOs excluded — a Completed Coating/Slitting/.../Packing WO
	# isn't "current" once the item has moved past it. Packing is always the
	# last real stage now (RTD/Delivered collapsed out of the stage model,
	# 2026-08-13 — see STAGES/mark_wos_delivered) so there's no terminal
	# Completed-but-still-current exception to carve out anymore.
	conditions = ["wo.status IN ('Pending', 'In Progress', 'On Hold')"]
	params = {}
	if location:
		conditions.append("so.custom_location = %(location)s")
		params["location"] = location.lower()
	where = " AND ".join(conditions)

	rows = frappe.db.sql(
		f"""
		SELECT wo.name, wo.item_code, wo.stage, wo.machine, wo.status,
			wo.target_qty, wo.target_uom, wo.completed_qty, wo.wastage_pct,
			wo.order_sheet, wo.order_sheet_item, wo.sales_order, wo.priority AS wo_priority,
			wo.creation,
			COALESCE(osi.item_name, wo.item_name) AS item_name,
			os.priority, os.customer_name, os.delivery_date
		FROM `tabIB Work Order` wo
		LEFT JOIN `tabIB Order Sheet` os ON os.name = wo.order_sheet
		LEFT JOIN `tabIB Order Sheet Item` osi ON osi.name = wo.order_sheet_item
		LEFT JOIN `tabSales Order` so ON so.name = wo.sales_order
		WHERE {where}
		ORDER BY wo.stage, FIELD(os.priority, 'Urgent', 'High', 'Normal', 'Low'), wo.creation
		""",
		params,
		as_dict=True,
	)

	stage_rank = {s: i for i, s in enumerate(STAGES)}
	groups = {}
	for row in rows:
		key = row.order_sheet_item or f"{row.order_sheet}::{row.item_code}"
		groups.setdefault(key, []).append(row)

	def _sk(s):
		return s.lower().replace(" ", "_")

	pipeline = {_sk(stage): [] for stage in STAGES}
	for wos in groups.values():
		wos.sort(key=lambda r: stage_rank.get(r.stage, 999))
		current = next((r for r in wos if r.status in ("In Progress", "On Hold")), None)
		if not current:
			current = next((r for r in wos if r.status == "Pending"), None)
		if not current:
			continue
		row = current
		key = _sk(row.get("stage", ""))
		entry = {
			"name": row.name,
			"item_code": row.item_code,
			"item_name": row.item_name,
			"machine": row.machine,
			"priority": row.priority or row.wo_priority,
			"status": row.status,
			"target_qty": row.target_qty,
			"target_uom": row.target_uom,
			"completed_qty": row.completed_qty,
			"wastage_pct": row.wastage_pct,
			"order_sheet": row.order_sheet,
			"order_sheet_item": row.order_sheet_item,
			"sales_order": row.sales_order,
			"customer_name": row.customer_name,
			"delivery_date": str(row.delivery_date) if row.delivery_date else None,
		}
		pipeline.setdefault(key, []).append(entry)

	return pipeline


# ---------------------------------------------------------------------------
# 5. Order Sheet Detail
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_order_sheet_detail(order_sheet):
	"""Full detail for one Order Sheet: doc, work_orders, views."""
	_require_production_role()
	doc = frappe.get_doc("IB Order Sheet", order_sheet)

	items = []
	for item in doc.items:
		items.append({
			"name": item.name,
			"item_code": item.item_code,
			"item_name": item.item_name,
			"qty": item.qty,
			"uom": item.uom,
			"completed_qty": item.completed_qty,
			"status": item.status,
		})

	work_orders = frappe.get_all(
		"IB Work Order",
		filters={"order_sheet": order_sheet},
		fields=[
			"name",
			"item_code",
			"order_sheet_item",
			"stage",
			"machine",
			"operator",
			"status",
			"target_qty",
			"target_uom",
			"pcs_to_make",
			"logs_to_make",
			"completed_qty",
			"wastage_qty",
			"wastage_pct",
			"started_at",
			"completed_at",
			"sales_order",
			"order_sheet",
			"jumbo_roll",
			"source_batch",
			"fg_batch",
			"produced_serials",
			"creation",
		],
		order_by="creation asc",
	)
	# Stamp the order's own customer_name onto every WO — the WO panel (and
	# any other surface that only has a bare WO to hand) needs this to show
	# which SO/customer a WO belongs to without a second round-trip.
	for wo in work_orders:
		wo["customer_name"] = doc.customer_name

	# Order-wise view: items with their WOs listed per item. Grouping by plain
	# item_code (wo_by_item, still used below for product_wise_view) conflates
	# WOs across multiple Order Sheet Item rows that share the same item_code
	# (e.g. one SKU ordered as separate line items at different quantities) —
	# every row matching that item_code would show the full merged bucket
	# instead of just its own WOs. Same fragility already fixed on the write
	# side in _update_order_sheet_item(): key by order_sheet_item (the unique
	# child-row name) when the WO has it; fall back to an item_code match only
	# for genuinely legacy WOs that predate order_sheet_item being populated.
	order_wise_view = []
	wo_by_item = {}
	wo_by_osi = {}
	wo_by_item_legacy = {}
	for wo in work_orders:
		wo_by_item.setdefault(wo.item_code, []).append(wo)
		if wo.order_sheet_item:
			wo_by_osi.setdefault(wo.order_sheet_item, []).append(wo)
		else:
			wo_by_item_legacy.setdefault(wo.item_code, []).append(wo)

	# Needed for next_stage_suggestion below — same route-aware default the
	# Active Production Plan's Start Production picker already uses (see
	# get_production_plan()). Order-wise's own table had no "start" action at
	# all under the JIT stage model (2026-08-13) — an item with zero Work
	# Orders (the normal starting state now) just rendered "No Work Orders"
	# with nothing clickable, a dead end reported live.
	location = _get_os_location(order_sheet)

	for item in items:
		row_wos = wo_by_osi.get(item["name"], []) + wo_by_item_legacy.get(item["item_code"], [])
		next_stage_suggestion = None
		if not any(wo.status in ("Pending", "In Progress", "On Hold") for wo in row_wos):
			stage_route = _get_stage_route(item["item_code"], location)
			completed_stages = {wo.stage for wo in row_wos if wo.status == "Completed"}
			next_stage_suggestion = next((s for s in stage_route if s not in completed_stages), None)
		order_wise_view.append({
			**item,
			"work_orders": row_wos,
			"next_stage_suggestion": next_stage_suggestion,
		})

	# Product-wise view: per item → {stage: {status, wo_name, completed_qty, target_qty}}
	product_wise_view = {}
	for item in items:
		stage_dict = {}
		for stage in STAGES:
			stage_dict[stage] = {
				"status": None,
				"wo_name": None,
				"completed_qty": 0,
				"target_qty": 0,
			}
		for wo in wo_by_item.get(item["item_code"], []):
			if wo.stage in stage_dict:
				stage_dict[wo.stage] = {
					"status": wo.status,
					"wo_name": wo.name,
					"completed_qty": wo.completed_qty,
					"target_qty": wo.target_qty,
				}
		product_wise_view[item["item_code"]] = stage_dict

	# Machine-wise view: per machine assigned to WOs of this OS
	machines_in_use = list({wo.machine for wo in work_orders if wo.machine})
	machine_wise_view = {}
	if machines_in_use:
		machine_docs = frappe.get_all(
			"IB Machine",
			filters={"machine_code": ["in", machines_in_use]},
			fields=["machine_code", "machine_name", "machine_type"],
		)
		minfo = {m.machine_code: m for m in machine_docs}
		for machine_code in machines_in_use:
			info = minfo.get(machine_code, frappe._dict())
			machine_wise_view[machine_code] = {
				"machine_code": machine_code,
				"machine_name": info.get("machine_name", machine_code),
				"type": info.get("machine_type", ""),
				"wos": [wo for wo in work_orders if wo.machine == machine_code],
			}

	os_fields = {
		"name": doc.name,
		"sales_order": doc.sales_order,
		"customer": doc.customer,
		"order_date": doc.order_date,
		"delivery_date": doc.delivery_date,
		"priority": doc.priority,
		"status": doc.status,
		"notes": doc.get("notes", ""),
	}

	return {
		"order_sheet": os_fields,
		"items": items,
		"work_orders": [dict(wo) for wo in work_orders],
		"order_wise_view": order_wise_view,
		"product_wise_view": product_wise_view,
		"machine_wise_view": machine_wise_view,
	}


@frappe.whitelist()
def get_order_sheet_wo_names(order_sheet):
	"""Names of the ONE currently-actionable Work Order per item under an
	Order Sheet — for the Order-wise list's bulk "Print Job Order" action.

	Was previously every non-Cancelled WO for every item, across every stage
	in that item's route — a 6-stage item printed 6 pages (3 Completed, 1
	In Progress, 2 not-yet-started) instead of the single page a floor
	worker actually needs. Now: walk each item's real stage route (same
	route _get_stage_route()/get_production_plan() already use) in order,
	and take the first stage whose WO is NOT Completed (Pending/In Progress/
	On Hold) — that's the one thing this item still needs done. An item
	whose every stage is already Completed contributes nothing (nothing
	left to hand a floor worker).
	"""
	_require_production_role()
	location = _get_os_location(order_sheet)
	items = frappe.db.get_all(
		"IB Order Sheet Item",
		filters={"parent": order_sheet},
		fields=["name", "item_code"],
	)
	if not items:
		return []

	names = []
	for item in items:
		stage_route = _get_stage_route(item.item_code, location)
		wos = frappe.db.get_all(
			"IB Work Order",
			filters={
				"order_sheet": order_sheet,
				"order_sheet_item": item.name,
				"status": ["!=", "Cancelled"],
			},
			fields=["name", "stage", "status"],
		)
		wo_by_stage = {wo.stage: wo for wo in wos}
		for stage in stage_route:
			wo = wo_by_stage.get(stage)
			if wo and wo.status != "Completed":
				names.append(wo.name)
				break

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
	location = _get_os_location(order_sheet)
	sales_order = frappe.db.get_value("IB Order Sheet", order_sheet, "sales_order")
	items = frappe.db.get_all(
		"IB Order Sheet Item",
		filters={"parent": order_sheet},
		fields=["name", "item_code", "item_name", "qty", "uom",
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

		stage_route = _get_stage_route(item.item_code, location)
		wos = frappe.db.get_all(
			"IB Work Order",
			filters={
				"order_sheet": order_sheet,
				"order_sheet_item": item.name,
				"status": ["!=", "Cancelled"],
			},
			fields=["name", "stage", "status", "machine", "operator", "pcs_to_make", "logs_to_make",
			        "target_qty", "target_uom"],
		)
		wo_by_stage = {wo.stage: wo for wo in wos}

		# Same "one actionable stage" rule as get_order_sheet_wo_names(): first
		# stage in real route order whose WO is not yet Completed.
		current_stage = None
		for stage in stage_route:
			wo = wo_by_stage.get(stage)
			if wo and wo.status != "Completed":
				current_stage = stage
				break

		stages_out = []
		for stage in _SUMMARY_STAGES:
			if stage not in stage_route:
				stages_out.append({
					"stage": stage, "in_route": False, "machine": None,
					"status": None, "is_current": False,
				})
				continue
			wo = wo_by_stage.get(stage)
			stages_out.append({
				"stage": stage,
				"in_route": True,
				"machine": wo.machine if wo else None,
				# get_fullname caches per-request (frappe.local.fullnames) so
				# resolving this per-stage/per-item doesn't turn into N+1 —
				# printed sheets should show a real name, not a raw user email.
				"operator": get_fullname(wo.operator) if (wo and wo.operator) else None,
				"status": wo.status if wo else None,
				"is_current": stage == current_stage,
			})

		# Manager reconciliation (Adjust Qty) is set on whichever stage WO the
		# manager opened — check the whole chain, not just one stage.
		pcs_to_make = next((flt(wo.pcs_to_make) for wo in wos if wo.pcs_to_make), 0)
		logs_to_make = next((flt(wo.logs_to_make) for wo in wos if wo.logs_to_make), 0)
		target_uom = next((wo.target_uom for wo in wos if wo.target_uom), item.uom)

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


def _compute_completion_qty(doc, actual_qty):
	"""Resolve (qty_done, wastage_qty, wastage_pct) for a WO being completed.

	actual_qty is the operator-entered real output (from the "Complete
	Stage" dialog's "Actual Output" prompt) — the first real wastage-capture
	path in the system. wastage = target_qty - actual_qty, clamped at 0
	(over-target output is not negative wastage). When actual_qty isn't
	given at all (older/API callers that predate the prompt), falls back to
	the pre-existing behavior: qty_done = target_qty, wastage stays 0/
	unmeasured — same as before this existed, not asserted as a real zero.
	"""
	if actual_qty is not None:
		qty_done = flt(actual_qty)
		target = flt(doc.target_qty)
		wastage_qty = max(target - qty_done, 0.0)
		wastage_pct = round((wastage_qty / target) * 100, 2) if target else 0.0
		return qty_done, wastage_qty, wastage_pct
	# completed_qty is never otherwise populated (IB Production Entry is
	# unused by design) — fall back to target_qty so the WO/Order Sheet Item
	# actually reach "Completed" status.
	return (flt(doc.completed_qty) or flt(doc.target_qty)), 0.0, 0.0


@frappe.whitelist()
def complete_work_order(work_order, actual_qty=None):
	"""Set status=Completed, record completed_at + real output/wastage
	(when actual_qty is given). Also updates Order Sheet Item status."""
	_require_production_role()
	if actual_qty is not None and flt(actual_qty) < 0:
		frappe.throw(_("Actual output cannot be negative."))
	lock_name = f"IB-WO-{work_order}"
	locked = frappe.db.sql("SELECT GET_LOCK(%s, 5)", lock_name)[0][0]
	if not locked:
		frappe.throw(_("Could not acquire lock for Work Order {0}. Please try again.").format(work_order))
	try:
		doc = frappe.get_doc("IB Work Order", work_order)
		if doc.status == "Completed":
			frappe.throw(_("Work Order {0} is already Completed.").format(work_order))
		if doc.status not in ("In Progress",):
			frappe.throw(
				_("Work Order {0} cannot be completed from status '{1}'. Expected: In Progress.").format(
					work_order, doc.status
				)
			)
		completed_at = now()
		qty_done, wastage_qty, wastage_pct = _compute_completion_qty(doc, actual_qty)
		doc.completed_at = completed_at
		doc.completed_qty = qty_done
		doc.wastage_qty = wastage_qty
		doc.wastage_pct = wastage_pct
		# apply_workflow saves the doc via the IB Work Order Workflow, which fires
		# standard Document events — IB Work Order.on_update (on_work_order_update_notify)
		# runs automatically, no manual call needed.
		apply_workflow(doc, "Complete")
		# apply_workflow() internally does frappe.get_doc(doc).load_from_db() before
		# applying the transition — load_from_db() re-inits every field from the DB
		# row, silently discarding the completed_at/completed_qty/wastage_* we just
		# set above in memory (doc.save() inside apply_workflow then persists the
		# DISCARDED/stale values, not ours). Confirmed live: real WOs completed
		# since the apply_workflow migration (2026-07-30) have completed_qty=0/
		# completed_at=NULL despite this function's own return value claiming
		# otherwise. Set them explicitly after the transition so they persist.
		frappe.db.set_value("IB Work Order", doc.name, {
			"completed_at": completed_at, "completed_qty": qty_done,
			"wastage_qty": wastage_qty, "wastage_pct": wastage_pct,
		})

		_generate_fg_serials(doc)

		# Update Order Sheet Item completed_qty and status
		if doc.order_sheet and doc.item_code:
			_update_order_sheet_item(doc.order_sheet, doc.item_code, qty_done,
									 order_sheet_item=doc.order_sheet_item or None)
			_update_order_sheet_progress(doc.order_sheet)

		frappe.db.commit()
		_notify_floor_update()
		return {"status": "ok", "completed_at": completed_at, "wastage_qty": wastage_qty}
	finally:
		frappe.db.sql("SELECT RELEASE_LOCK(%s)", lock_name)


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


@frappe.whitelist()
def create_work_orders_for_item(order_sheet, item_code, stages):
	"""Create IB Work Order records for specified stages for an item."""
	_require_production_role()
	if isinstance(stages, str):
		stages = json.loads(stages)

	# Look up the Order Sheet Item row by item_code
	osi_name = frappe.db.get_value(
		"IB Order Sheet Item",
		{"parent": order_sheet, "item_code": item_code},
		"name",
	)
	if not osi_name:
		frappe.throw(_("Item {0} not found in Order Sheet {1}").format(item_code, order_sheet))
	osi = frappe.get_doc("IB Order Sheet Item", osi_name)

	# Requested stage must be part of THIS item's actual route (route-aware — item
	# group / warehouse-only location can both drop stages). Without this check, the
	# manual "+" picker (which lists all canonical stages regardless of route)
	# could silently create an orphan Work Order for a stage the item never needs.
	location = _get_os_location(order_sheet)
	stage_route = _get_stage_route(osi.item_code, location)

	created = []
	for stage in stages:
		if stage not in stage_route:
			frappe.throw(
				_("{0} is not a valid stage for item {1}'s production route ({2}).").format(
					stage, osi.item_code, " → ".join(stage_route)
				)
			)
		# Skip if a WO already exists for this order_sheet + item_code + stage
		existing = frappe.db.exists(
			"IB Work Order",
			{"order_sheet": order_sheet, "item_code": osi.item_code, "stage": stage},
		)
		if existing:
			continue

		wo = frappe.new_doc("IB Work Order")
		wo.order_sheet = order_sheet
		wo.item_code = osi.item_code
		wo.stage = stage
		wo.status = "Pending"
		wo.target_qty = osi.qty
		wo.completed_qty = 0.0
		wo.wastage_qty = 0.0
		wo.wastage_pct = 0.0
		wo.insert(ignore_permissions=True)
		created.append(wo.name)

	frappe.db.commit()
	return {"created": created}


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

	rows = frappe.db.sql(
		"""
		SELECT wo.stage, wo.machine, wo.completed_qty, wo.target_uom,
			TIMESTAMPDIFF(MINUTE, wo.started_at, wo.completed_at) AS duration_min
		FROM `tabIB Work Order` wo
		WHERE wo.status = 'Completed' AND DATE(COALESCE(wo.completed_at, wo.modified)) = %s
		ORDER BY wo.stage, wo.machine
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

	Sourced from IB Work Order completions — see get_dpr()'s docstring for
	why IB Production Entry (this function's original source) is permanently
	empty, and why wastage isn't reported (never written by any real
	completion path, would misleadingly always show 0%).
	"""
	_require_production_role()
	if not week_start:
		week_start = date or today()
		today_dt = getdate(week_start)
		week_start = add_days(today_dt, -today_dt.weekday())
	else:
		week_start = getdate(week_start)

	week_end = add_days(week_start, 6)

	# Grouped by day AND target_uom — same reasoning as get_dpr(): a bare
	# SUM(completed_qty) across rows of different UOMs (PCS/SQMT/ROLL/...)
	# isn't a real quantity of anything, so output is always kept as
	# {uom, qty} pairs, never blended into one number.
	wo_rows = frappe.db.sql(
		"""
		SELECT DATE(COALESCE(completed_at, modified)) AS day,
			COALESCE(target_uom, 'Unknown') AS uom,
			COUNT(*) AS wo_completed,
			SUM(completed_qty) AS output_qty,
			SUM(TIMESTAMPDIFF(MINUTE, started_at, completed_at)) AS total_minutes
		FROM `tabIB Work Order`
		WHERE status = 'Completed'
			AND DATE(COALESCE(completed_at, modified)) BETWEEN %s AND %s
		GROUP BY DATE(COALESCE(completed_at, modified)), COALESCE(target_uom, 'Unknown')
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

def _update_order_sheet_item(order_sheet, item_code, completed_qty, order_sheet_item=None):
	"""Update IB Order Sheet Item completed_qty and flip status.

	Uses order_sheet_item (child row name) as direct key when available — avoids
	updating all rows when the same item_code appears multiple times in one OS.
	Falls back to item_code scan for legacy WOs.

	Status is "Completed" only once a Completed Work Order exists for EVERY
	stage in this item's actual route (_get_stage_route) — not merely once
	every Work Order that currently *exists* is Completed. Those were
	equivalent back when auto_create_all_stage_wos() pre-created the whole
	route's Work Orders upfront (every stage always had a row, so "all
	existing WOs done" and "all route stages done" meant the same thing).
	Under the JIT stage model (2026-08-13) most stages have no Work Order at
	all until a user explicitly starts them — "all existing WOs Completed"
	would go true after stage 1 of N every single time, the exact bug this
	function was already fixed for once before (see git history: 8/17
	Completed items and 2/7 Completed Order Sheets were wrongly flagged
	before that first fix) — route-awareness is what actually has to hold,
	not just "no WO is left incomplete".
	"""
	if order_sheet_item:
		row = frappe.db.get_value("IB Order Sheet Item", order_sheet_item, ["name", "qty"], as_dict=True)
		rows = [row] if row else []
	else:
		rows = frappe.db.get_all(
			"IB Order Sheet Item",
			filters={"parent": order_sheet, "item_code": item_code},
			fields=["name", "qty"],
		)
	if not rows:
		return
	location = _get_os_location(order_sheet)
	stage_route = set(_get_stage_route(item_code, location))
	for row in rows:
		wo_filters = {"order_sheet": order_sheet, "status": ["not in", ["Cancelled"]]}
		if order_sheet_item:
			wo_filters["order_sheet_item"] = row.name
		else:
			wo_filters["item_code"] = item_code
		wo_rows = frappe.db.get_all("IB Work Order", filters=wo_filters, fields=["stage", "status"])
		completed_stages = {w.stage for w in wo_rows if w.status == "Completed"}
		all_done = bool(stage_route) and stage_route.issubset(completed_stages)
		new_status = "Completed" if all_done else "In Progress"
		frappe.db.set_value(
			"IB Order Sheet Item",
			row.name,
			{
				"completed_qty": completed_qty,
				"status": new_status,
			},
		)


def _update_order_sheet_progress(order_sheet_name):
	"""Check if all items complete → mark OS as Completed.

	Symmetric: also reopens a previously-Completed OS back to "In Progress" if
	it no longer has every item Completed. Originally one-directional (Completed
	only ever got set, never unset) — harmless as long as an item's status only
	ever moves forward, but start_item_stage()'s rework path (reactivating an
	already-Completed stage's WO for rework) can legitimately un-complete an
	item. Without this, an Order Sheet reopened that way would stay stuck
	showing "Completed" indefinitely, since nothing else ever re-evaluates it
	downward.
	"""
	items = frappe.db.get_all(
		"IB Order Sheet Item",
		filters={"parent": order_sheet_name},
		fields=["status"],
	)
	if not items:
		return
	all_done = all(item.status == "Completed" for item in items)
	current_status = frappe.db.get_value("IB Order Sheet", order_sheet_name, "status")
	if all_done and current_status != "Completed":
		frappe.db.set_value("IB Order Sheet", order_sheet_name, "status", "Completed")
	elif not all_done and current_status == "Completed":
		frappe.db.set_value("IB Order Sheet", order_sheet_name, "status", "In Progress")


@frappe.whitelist()
def advance_to_next_stage(work_order, actual_qty=None):
	"""Complete the current Work Order's stage.

	JIT stage model (2026-08-13, user's explicit decision): this used to also
	auto-create/activate the next stage's Work Order, since
	auto_create_all_stage_wos() had already pre-built the whole route's chain
	upfront at Order Sheet creation. That pre-creation is gone — completing a
	stage now just completes it. Getting the item moving again means calling
	start_item_stage() and picking a stage (the frontend defaults that pick to
	next_stage below, but it's freely overridable to any stage this order's
	location can reach). Kept as its own endpoint — not folded into
	complete_work_order(), which does identical completion work — only so
	existing call sites (the Active Production Plan's "Next Stage →"/"Finish"
	button, the WO panel) keep working without an unrelated rename; the one
	real behavioral difference is the next_stage suggestion returned here.
	"""
	_require_production_role()
	if actual_qty is not None and flt(actual_qty) < 0:
		frappe.throw(_("Actual output cannot be negative."))
	lock_name = f"IB-WO-{work_order}"
	locked = frappe.db.sql("SELECT GET_LOCK(%s, 5)", lock_name)[0][0]
	if not locked:
		frappe.throw(_("Could not acquire lock for Work Order {0}. Please try again.").format(work_order))
	try:
		doc = frappe.get_doc("IB Work Order", work_order)
		location = _get_os_location(doc.order_sheet)
		stage_route = _get_stage_route(doc.item_code, location)

		def _next_default_stage(current_stage):
			try:
				idx = stage_route.index(current_stage)
			except ValueError:
				return None
			return stage_route[idx + 1] if idx < len(stage_route) - 1 else None

		if doc.status == "Completed":
			# Idempotency — nothing to complete again, just repeat the suggestion.
			next_stage = _next_default_stage(doc.stage)
			return {
				"status": "ok",
				"next_stage": next_stage,
				"message": "Already completed" if next_stage else "Production complete — item delivered",
			}

		if doc.status != "In Progress":
			frappe.throw(_("Work Order {0} must be In Progress to advance. Current status: {1}").format(work_order, doc.status))

		completed_at = now()
		qty_done, wastage_qty, wastage_pct = _compute_completion_qty(doc, actual_qty)
		doc.completed_at = completed_at
		doc.completed_qty = qty_done
		doc.wastage_qty = wastage_qty
		doc.wastage_pct = wastage_pct
		# apply_workflow saves the doc via the IB Work Order Workflow, which fires
		# standard Document events — IB Work Order.on_update (on_work_order_update_notify)
		# runs automatically, no manual call needed.
		apply_workflow(doc, "Complete")
		# See identical fix + comment in complete_work_order() — apply_workflow's
		# internal load_from_db() discards the completed_at/completed_qty/wastage_*
		# set above before its own doc.save(), so they must be persisted explicitly.
		frappe.db.set_value("IB Work Order", doc.name, {
			"completed_at": completed_at, "completed_qty": qty_done,
			"wastage_qty": wastage_qty, "wastage_pct": wastage_pct,
		})

		_generate_fg_serials(doc)

		_update_order_sheet_item(doc.order_sheet, doc.item_code, qty_done,
								 order_sheet_item=doc.order_sheet_item or None)
		_update_order_sheet_progress(doc.order_sheet)

		next_stage = _next_default_stage(doc.stage)
		frappe.db.commit()
		_notify_floor_update()
		return {
			"status": "ok",
			"next_stage": next_stage,
			"message": (
				f"{doc.stage} complete — start {next_stage} when ready"
				if next_stage else "Production complete — item delivered"
			),
		}
	finally:
		frappe.db.sql("SELECT RELEASE_LOCK(%s)", lock_name)


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


def _generate_fg_serials(doc):
	"""Final-stage completion → FG Batch + one IB FG Serial per physical unit
	produced, each stamped with the full genealogy. Phase 2: annotation only,
	no stock ledger entry (native Serial No + ledger integration is Phase 3).
	Never raises — a serial failure must not block Work Order completion."""
	try:
		from instabiz.overrides.item import _SERIAL_ITEM_GROUPS

		if flt(doc.get("produced_serials")):
			return
		if (frappe.db.get_value("Item", doc.item_code, "item_group") or "") not in _SERIAL_ITEM_GROUPS:
			return
		route = _get_stage_route(doc.item_code, _get_os_location(doc.order_sheet))
		if not route or doc.stage != route[-1]:
			return
		if frappe.db.exists("IB FG Serial", {"work_order": doc.name}):
			return

		n_units = min(cint(doc.get("logs_to_make")) or cint(doc.get("pcs_to_make")) or 1, 2000)
		item = frappe.db.get_value(
			"Item", doc.item_code, ["width_mm", "length_mtr", "gsm", "item_name"], as_dict=True
		) or {}

		fg_batch_id = f"FG::{doc.item_code}::{doc.name}"
		if not frappe.db.exists("Batch", fg_batch_id):
			fb = frappe.new_doc("Batch")
			fb.batch_id = fg_batch_id
			fb.item = doc.item_code
			fb.custom_batch_kind = "Finished Good"
			fb.custom_work_order = doc.name
			fb.custom_received_date = today()
			fb.custom_parent_batches = json.dumps([doc.source_batch] if doc.get("source_batch") else [])
			fb.custom_gsm = flt(item.get("gsm"))
			fb.custom_width_mm = flt(item.get("width_mm"))
			fb.insert(ignore_permissions=True)

		stamp = _serial_stamp()
		seq = _next_serial_seq(doc.item_code, stamp)
		produced_on = now()
		created = 0
		for i in range(n_units):
			sn_name = f"{doc.item_code}::{stamp}::{seq + i:04d}"
			if frappe.db.exists("IB FG Serial", sn_name):
				continue
			sn = frappe.new_doc("IB FG Serial")
			sn.serial_no = sn_name
			sn.item_code = doc.item_code
			sn.item_name = item.get("item_name")
			sn.status = "In Stock"
			sn.fg_batch = fg_batch_id
			sn.source_batch = doc.get("source_batch")
			sn.work_order = doc.name
			sn.order_sheet = doc.order_sheet
			sn.sales_order = doc.sales_order
			sn.produced_on = produced_on
			sn.box_no = i + 1
			sn.width_mm = flt(item.get("width_mm"))
			sn.length_mtr = flt(item.get("length_mtr"))
			sn.gsm = flt(item.get("gsm"))
			sn.insert(ignore_permissions=True)
			created += 1

		frappe.db.set_value(
			"IB Work Order", doc.name, {"fg_batch": fg_batch_id, "produced_serials": created}
		)
	except Exception:
		frappe.log_error("IB serial gen", frappe.get_traceback())


def _thread_source_batch(order_sheet_item, wo_name, explicit=None):
	"""Set the RM source batch on this Work Order. An explicit pick wins;
	otherwise carry forward whatever an earlier stage of the same item row
	already has, so the batch flows down the stage chain without re-picking."""
	batch = explicit
	if not batch:
		batch = frappe.db.get_value(
			"IB Work Order",
			{
				"order_sheet_item": order_sheet_item,
				"source_batch": ["is", "set"],
				"status": ["!=", "Cancelled"],
			},
			"source_batch",
		)
	if batch and frappe.db.exists("Batch", batch):
		frappe.db.set_value("IB Work Order", wo_name, "source_batch", batch)


@frappe.whitelist()
def set_wo_source_batch(work_order, source_batch):
	"""Manually set / correct the RM source batch on a Work Order — propagates
	to every non-cancelled stage WO of the same order sheet item."""
	_require_production_role()
	if not frappe.db.exists("Batch", source_batch):
		frappe.throw(_("Batch {0} not found").format(source_batch))
	osi = frappe.db.get_value("IB Work Order", work_order, "order_sheet_item")
	targets = (
		frappe.get_all(
			"IB Work Order",
			filters={"order_sheet_item": osi, "status": ["!=", "Cancelled"]},
			pluck="name",
		)
		if osi
		else [work_order]
	)
	for name in targets:
		frappe.db.set_value("IB Work Order", name, "source_batch", source_batch)
	frappe.db.commit()
	return {"status": "ok", "updated": len(targets)}


@frappe.whitelist()
def start_item_stage(order_sheet_item, stage, source_batch=None):
	"""JIT stage entry point (2026-08-13): create exactly one Work Order for
	the picked stage and put it straight to work — In Progress, machine
	auto-assigned. Replaces auto_create_all_stage_wos()'s old "pre-create the
	whole route upfront" model — an Order Sheet Item now has zero Work Orders
	until a production user explicitly starts it and picks a stage, every
	time (the frontend's picker defaults to _get_stage_route()'s next
	uncompleted stage, but any canonical stage this order's location can
	physically reach is a valid pick — location-only restriction, not the
	stricter item-group route check, since a route is a default suggestion
	here, not a hard ceiling). This is now the ONLY way to start or move a
	Work Order to a stage — the separate manual "shuffle" stage-move feature
	(move_work_order_stage) was removed 2026-08-13, same user decision as
	this JIT model itself.
	"""
	_require_production_role()
	osi = frappe.db.get_value(
		"IB Order Sheet Item",
		order_sheet_item,
		["name", "parent", "item_code", "item_name", "qty", "uom"],
		as_dict=True,
	)
	if not osi:
		frappe.throw(_("Order Sheet Item {0} not found").format(order_sheet_item))

	location = _get_os_location(osi.parent)
	allowed_stages = (
		_WAREHOUSE_STAGE_ROUTE
		if (location or "").lower() in _WAREHOUSE_ONLY_LOCATIONS
		else list(STAGES)
	)
	if stage not in allowed_stages:
		frappe.throw(
			_("{0} is not available at this order's location ({1}).").format(
				stage, ", ".join(allowed_stages)
			)
		)

	# One lock per (item row, stage) — serializes this endpoint's own
	# existence-check-then-create/reactivate race for this exact target.
	# Sufficient here because this endpoint is the only path that creates a
	# Work Order for a not-yet-existing order_sheet_item+stage combination;
	# once the row exists, the transition below reuses the same doc within
	# this same locked section.
	lock_name = f"IB-OSI-{order_sheet_item}-{stage}"
	locked = frappe.db.sql("SELECT GET_LOCK(%s, 5)", lock_name)[0][0]
	if not locked:
		frappe.throw(_("Could not acquire lock. Please try again."))
	try:
		existing = frappe.db.get_value(
			"IB Work Order",
			{"order_sheet_item": order_sheet_item, "stage": stage, "status": ["!=", "Cancelled"]},
			["name", "status"],
			as_dict=True,
		)
		sales_order = frappe.db.get_value("IB Order Sheet", osi.parent, "sales_order")
		is_rework = bool(existing and existing.status == "Completed")

		if existing and existing.status == "Completed":
			# Rework — "Completed" has no apply_workflow transition back out
			# (IB Work Order Workflow), so reactivate via a direct db write.
			frappe.db.set_value(
				"IB Work Order", existing.name,
				{"status": "Pending", "started_at": None, "completed_at": None, "completed_qty": 0},
			)
			wo_name = existing.name
		elif existing and existing.status in ("Pending", "On Hold"):
			wo_name = existing.name
		elif existing:
			frappe.throw(_("Work Order {0} for this stage is already {1}.").format(existing.name, existing.status))
		else:
			wo = frappe.new_doc("IB Work Order")
			wo.order_sheet = osi.parent
			wo.order_sheet_item = osi.name
			wo.sales_order = sales_order or ""
			wo.item_code = osi.item_code
			wo.item_name = osi.item_name
			wo.stage = stage
			wo.priority = frappe.db.get_value("IB Order Sheet", osi.parent, "priority") or "Normal"
			wo.target_qty = flt(osi.qty)
			wo.target_uom = osi.uom
			wo.status = "Pending"
			wo.insert(ignore_permissions=True)
			wo_name = wo.name

		_thread_source_batch(order_sheet_item, wo_name, source_batch)

		# Also hold the same per-WO lock every other status-mutating function
		# uses (assign_machine/start_work_order/complete_work_order/put_on_hold/
		# advance_to_next_stage all lock "IB-WO-{name}") — the OSI-scoped lock
		# above only serializes this endpoint's own existence-check-then-create
		# race; without this, a concurrent call on one of those other endpoints
		# for the same WO has no mutual exclusion against what happens next.
		wo_lock = f"IB-WO-{wo_name}"
		wo_locked = frappe.db.sql("SELECT GET_LOCK(%s, 5)", wo_lock)[0][0]
		if not wo_locked:
			frappe.throw(_("Could not acquire lock for Work Order {0}. Please try again.").format(wo_name))
		try:
			if not frappe.db.get_value("IB Work Order", wo_name, "machine"):
				machine = _assign_machine_load_balanced(stage, location) or ""
				if machine:
					frappe.db.set_value("IB Work Order", wo_name, "machine", machine)
			else:
				machine = frappe.db.get_value("IB Work Order", wo_name, "machine")

			doc = frappe.get_doc("IB Work Order", wo_name)
			started_at = now()
			doc.started_at = started_at
			apply_workflow(doc, "Resume" if doc.status == "On Hold" else "Start")
			# Same apply_workflow load_from_db discard as start_work_order()/
			# complete_work_order() — persist explicitly or it silently stays NULL.
			frappe.db.set_value("IB Work Order", wo_name, "started_at", started_at)

			if is_rework:
				# Reactivating a Completed stage un-completes the item — without
				# this, IB Order Sheet Item/IB Order Sheet stayed stuck showing
				# "Completed" while the stage was genuinely back in progress, and
				# get_order_dn_readiness() (which only checks Order Sheet status)
				# would still let a Delivery Note be created mid-rework.
				_update_order_sheet_item(osi.parent, osi.item_code, 0, order_sheet_item=osi.name)
				_update_order_sheet_progress(osi.parent)
		finally:
			frappe.db.sql("SELECT RELEASE_LOCK(%s)", wo_lock)

		if frappe.db.get_value("IB Order Sheet", osi.parent, "status") == "Draft":
			frappe.db.set_value("IB Order Sheet", osi.parent, "status", "In Progress")

		frappe.db.commit()
		_notify_floor_update()
		return {"status": "ok", "work_order": wo_name, "stage": stage, "machine": machine}
	finally:
		frappe.db.sql("SELECT RELEASE_LOCK(%s)", lock_name)


@frappe.whitelist()
def bulk_start_item_stages(item_stages, brand=None, core=None, ctn=None,
	shrink_film=None, no_of_logs=None, packing_type=None, size=None):
	"""Start stage(s) on several Order Sheet Items in one call — e.g. one SKU
	sold as several line items at different dimensions (width/color/etc),
	each its own Order Sheet Item, all needing production kicked off
	together instead of clicking Start Production once per row.

	item_stages is a list of {order_sheet_item, stages} — deliberately
	per-item, not one shared stage list for the whole batch: two selected
	items can each be resting at a genuinely different point in their own
	route (one brand new needing Coating first, another already past
	Coating/Slitting and just resting between stages needing Rewinding
	next) even though both show the same "Start Production" button — a
	single shared stage picker applied to everyone would silently force the
	wrong stage onto whichever items don't match it. The frontend defaults
	each item's own picker to that item's own next_stage_suggestion, but
	still sends one independent stage list per item so a user who leaves
	them at their defaults gets each item's own correct next step, not one
	guess applied to all.

	Pure orchestration: every (item, stage) pair is still run through
	start_item_stage() one at a time, so it gets that function's own
	locking, location/route validation, and machine assignment exactly as
	if started individually — no new write path. This is additive to the
	JIT model, not a departure from it: start_item_stage stays the one place
	a Work Order actually gets created/moved (see bulk_wo_action's
	2026-08-13 removal note just below this function) — the old bulk
	feature that got removed mass-flipped raw pre-created WO status
	directly, from before the JIT model existed; this one never touches a
	Work Order except through that same single entry point.

	Every item's one-time packing-details form (custom_packing_captured) is
	still required before its first stage — Brand/Core/CTN/Shrink Film/
	Packing Type are asked here once for the whole batch, since
	dimension-variants of one SKU almost always share those (real Item/
	Brand links, not something normally re-picked per line). Size and
	No. of Logs are different — those describe the physical line itself and
	genuinely do vary per dimension-variant in practice (a 72-roll line and
	a 24-roll line of the same base SKU don't share a log count), so each
	row in item_stages MAY carry its own "size"/"no_of_logs" override; when
	present it wins over the shared size/no_of_logs argument for that one
	item, same "per-item beats shared default" reasoning as the stage list
	above. Only items that don't have custom_packing_captured yet get any of
	this written; an item that already captured its own (different) details
	is left alone. If nothing (shared or per-item) is given, items missing
	capture are skipped rather than saving an empty form silently.
	"""
	_require_production_role()
	if isinstance(item_stages, str):
		item_stages = json.loads(item_stages)
	if not item_stages:
		frappe.throw(_("No items selected."))

	shared_given = any([brand, core, ctn, shrink_film, no_of_logs, packing_type, size])

	results = []
	started = 0
	skipped = 0
	failed = 0

	for row in item_stages:
		osi = row.get("order_sheet_item")
		row_stages = row.get("stages") or []
		row_size = row.get("size") or size
		row_no_of_logs = row.get("no_of_logs") or no_of_logs
		item_label = frappe.db.get_value("IB Order Sheet Item", osi, "item_code") or osi
		if not row_stages:
			results.append({"order_sheet_item": osi, "item_code": item_label, "status": "skipped",
				"message": "No stage picked for this item."})
			skipped += 1
			continue
		# Stable stage order (route order, not click order) — same reasoning
		# _show_start_stage_dialog's frontend counterpart uses for a single item.
		ordered_stages = [s for s in STAGES if s in row_stages]

		captured = frappe.db.get_value("IB Order Sheet Item", osi, "custom_packing_captured")
		if not captured:
			if not shared_given and not row_size and not row_no_of_logs:
				results.append({"order_sheet_item": osi, "item_code": item_label, "status": "skipped",
					"message": "Packing details not captured yet — start this one individually first."})
				skipped += 1
				continue
			save_packing_details(osi, brand=brand, core=core, ctn=ctn, shrink_film=shrink_film,
				no_of_logs=row_no_of_logs, packing_type=packing_type, size=row_size)
		for stage in ordered_stages:
			try:
				r = start_item_stage(osi, stage)
				results.append({"order_sheet_item": osi, "item_code": item_label, "stage": stage,
					"status": "ok", "machine": r.get("machine")})
				started += 1
			except Exception as e:
				results.append({"order_sheet_item": osi, "item_code": item_label, "stage": stage,
					"status": "error", "message": str(e)})
				failed += 1

	return {
		"total_items": len(item_stages),
		"started": started,
		"skipped": skipped,
		"failed": failed,
		"details": results,
	}


@frappe.whitelist()
def get_packing_capture_status(order_sheet_item):
	"""Whether the pre-stage-picker packing-details form has already been
	filled for this Order Sheet Item. Checked fresh from the DB (not from
	whatever data the calling tab happened to have loaded) so the "ask once
	per item, before its first stage" rule holds no matter which of the
	Dashboard's several entry points (Active Plan, Item-wise, Stage-wise,
	Machine-wise, WO panel post-complete prompt) triggered the stage picker.
	"""
	_require_production_role()
	return bool(frappe.db.get_value("IB Order Sheet Item", order_sheet_item, "custom_packing_captured"))


@frappe.whitelist()
def save_packing_details(order_sheet_item, brand=None, core=None, ctn=None,
                          shrink_film=None, no_of_logs=None, packing_type=None, size=None):
	"""Saves the pre-stage packing-details form (Brand/Core/CTN/Shrink Film/
	No. of Logs/Packing Type/Size) onto the Order Sheet Item and marks it
	captured so it isn't asked again for this item. Direct db.set_value, not
	doc.save() — these are plain descriptive/reference fields, no doctype
	validate() logic depends on them, and every other JIT-picker mutation in
	this module (start_item_stage, advance_to_next_stage) already writes to
	IB Order Sheet Item / IB Work Order the same way."""
	_require_production_role()
	if not frappe.db.exists("IB Order Sheet Item", order_sheet_item):
		frappe.throw(_("Order Sheet Item {0} not found").format(order_sheet_item))

	frappe.db.set_value("IB Order Sheet Item", order_sheet_item, {
		"custom_brand": brand or None,
		"custom_core": core or None,
		"custom_ctn": ctn or None,
		"custom_shrink_film": shrink_film or None,
		"custom_no_of_logs": cint(no_of_logs) if no_of_logs else 0,
		"custom_packing_type": packing_type or None,
		"custom_size": size or None,
		"custom_packing_captured": 1,
	})
	frappe.db.commit()
	return {"status": "ok"}


# bulk_wo_action() (mass Start/Next Stage across a checkbox selection)
# removed 2026-08-13 along with its frontend UI — the mass-select bulk
# feature was dropped as part of making the JIT stage picker (start_item_stage)
# the single way to start/move a Work Order (user's explicit decision, same
# session as the RTD/Delivered stage-model collapse). No other caller ever
# existed for it.


@frappe.whitelist()
def auto_create_all_stage_wos(order_sheet):
	"""Create Work Orders for ALL applicable stages for every item in an Order Sheet.

	Stage route is determined per item_group (e.g. PLASTIC gets Coating→Slitting→…,
	PVC skips Coating, Aerosol items only get Packing→RTD).

	Only the first stage gets a machine assigned immediately (load-balanced).
	Subsequent stages are created as Pending with no machine — machine is assigned
	when advance_to_next_stage() fires after the preceding stage completes.
	"""
	_require_production_role()
	os_doc = frappe.get_doc("IB Order Sheet", order_sheet)
	location = _get_os_location(order_sheet)
	created = []

	for item in os_doc.items:
		stage_route = _get_stage_route(item.item_code, location)

		for idx, stage in enumerate(stage_route):
			# Per-row key: order_sheet + order_sheet_item (child row name) + stage
			existing = frappe.db.get_value(
				"IB Work Order",
				{"order_sheet": order_sheet, "order_sheet_item": item.name,
				 "stage": stage, "status": ["not in", ["Cancelled"]]},
				"name",
			)
			if existing:
				created.append(existing)
				continue

			wo = frappe.new_doc("IB Work Order")
			wo.order_sheet       = order_sheet
			wo.order_sheet_item  = item.name   # per-row key
			wo.sales_order       = os_doc.sales_order or ""
			wo.item_code         = item.item_code
			wo.item_name         = item.item_name
			wo.stage             = stage
			wo.priority          = os_doc.priority or "Normal"
			wo.target_qty        = flt(item.qty)
			wo.target_uom        = item.uom
			wo.status            = "Pending"
			# Assign machine only to first stage — rest assigned when stage activates
			if idx == 0:
				wo.machine = _assign_machine_load_balanced(stage, location) or ""
			wo.insert(ignore_permissions=True)
			created.append(wo.name)

	frappe.db.set_value("IB Order Sheet", order_sheet, "status", "In Progress")
	frappe.db.commit()
	return {"created": created, "route_used": {
		item.item_code: _get_stage_route(item.item_code, location) for item in os_doc.items
	}}


# Backward-compat alias used by older callers
def auto_create_first_stage_wos(order_sheet):
	return auto_create_all_stage_wos(order_sheet)


@frappe.whitelist()
def get_production_plan(limit=None, start=0, location=None, search=None, priority=None):
	"""Return order-wise data for the Active Production Plan table.

	limit: max number of order sheets to return in order_wise (default: all).
	       Dashboard passes limit=25 per page for infinite scroll.
	start: offset for the order_wise page (infinite scroll).
	location: optional Sales Order custom_location filter (maharashtra/gujarat/chennai).
	search: optional match against Sales Order name, customer name, or an item
	        code/name on any of the order's items — the last of these matters
	        when the same customer has two different Sales Orders carrying the
	        same item: searching by SO/customer alone can't tell you which one
	        you're looking at, but searching the item code surfaces both so
	        their (already-distinct) SO number/creation date/qty on screen do.
	priority: optional Order Sheet priority filter (Urgent/High/Normal/Low).
	"""
	_require_production_role()
	limit = int(limit) if limit and str(limit).isdigit() else None
	start = int(start) if str(start).isdigit() else 0
	limit_clause = f"LIMIT {limit} OFFSET {start}" if limit else ""
	# Always joined now (used to be conditional on the location filter being
	# set) — custom_location is needed per order sheet regardless of filter
	# state to compute each item's route-aware next_stage_suggestion below.
	loc_join = "JOIN `tabSales Order` so ON so.name = os.sales_order"
	loc_where = "AND so.custom_location = %(location)s" if location else ""
	search_where = (
		"AND (os.sales_order LIKE %(search)s OR os.customer_name LIKE %(search)s "
		"OR EXISTS (SELECT 1 FROM `tabIB Order Sheet Item` osi "
		"WHERE osi.parent = os.name AND (osi.item_code LIKE %(search)s OR osi.item_name LIKE %(search)s)))"
	) if search else ""
	priority_where = "AND os.priority = %(priority)s" if priority else ""

	# ── Order-wise: active order sheets with item stage status ──────────────
	order_sheets = frappe.db.sql(
		f"""
		SELECT os.name, os.sales_order, os.customer_name, os.priority, os.status,
		       os.delivery_date, os.order_date, os.creation, so.custom_location AS location
		FROM `tabIB Order Sheet` os
		{loc_join}
		WHERE os.status IN ('Draft', 'In Progress')
		{loc_where}
		{search_where}
		{priority_where}
		ORDER BY
		  FIELD(os.priority, 'Urgent','High','Normal','Low'),
		  os.delivery_date ASC
		{limit_clause}
		""",
		{"location": location, "search": f"%{search}%" if search else None, "priority": priority},
		as_dict=True,
	)

	# Items + Work Orders for every order sheet on this page, fetched as two
	# batch queries instead of one query per order sheet plus one more per item
	# (was a real N+1 — 25 order sheets x ~2-3 items each meant ~90 queries per
	# dashboard load for this section alone).
	#
	# The old per-item WO lookup also matched by item_code alone — the exact
	# cross-contamination bug already fixed in get_order_sheet_detail's
	# order-wise view (2026-07-31, see that fix's own comment): a Sales Order
	# with the same item_code on multiple lines (confirmed live on real current
	# data, e.g. IB-OS-2026-02331 has 6 Order Sheet Item rows sharing one
	# item_code) made every one of those item rows on this Dashboard table show
	# the same merged Work Orders instead of its own. Fixed the same way — key
	# by the Work Order's own order_sheet_item link (falls back to order_sheet
	# + item_code only for legacy WOs predating that field, none exist live).
	os_names = [os.name for os in order_sheets]
	items_by_os = {}
	wos_by_key = {}
	if os_names:
		all_items = frappe.db.get_all(
			"IB Order Sheet Item",
			filters={"parent": ["in", os_names]},
			fields=["name", "parent", "item_code", "item_name", "qty", "uom", "completed_qty", "status",
			        "custom_packing_captured"],
		)
		for it in all_items:
			items_by_os.setdefault(it.parent, []).append(it)

		all_wos = frappe.db.get_all(
			"IB Work Order",
			filters={"order_sheet": ["in", os_names], "status": ["not in", ["Cancelled"]]},
			fields=["name", "order_sheet", "order_sheet_item", "item_code", "stage", "status",
			        "completed_qty", "target_qty", "target_uom", "pcs_to_make", "logs_to_make", "machine"],
		)
		for wo in all_wos:
			key = (wo.order_sheet, wo.order_sheet_item) if wo.order_sheet_item \
				else (wo.order_sheet, f"ic:{wo.item_code}")
			wos_by_key.setdefault(key, []).append(wo)

	for os in order_sheets:
		items = items_by_os.get(os.name, [])
		item_route_cache = {}
		# Per item: dict of stage → WO info
		for item in items:
			wos = wos_by_key.get((os.name, item.name)) or wos_by_key.get((os.name, f"ic:{item.item_code}"), [])
			stage_map = {wo.stage: wo for wo in wos}
			item["stage_map"] = {s: {
				"status": stage_map[s].status if s in stage_map else None,
				"wo_name": stage_map[s].name if s in stage_map else None,
				"completed_qty": stage_map[s].completed_qty if s in stage_map else 0,
				"target_qty": stage_map[s].target_qty if s in stage_map else 0,
				"target_uom": stage_map[s].target_uom if s in stage_map else None,
				"pcs_to_make": stage_map[s].pcs_to_make if s in stage_map else 0,
				"logs_to_make": stage_map[s].logs_to_make if s in stage_map else 0,
				"machine": stage_map[s].machine if s in stage_map else None,
			} for s in STAGES}
			# On Hold counts as "current" alongside In Progress — an item
			# paused mid-stage is still sitting there, not back to nothing
			# (matches get_stage_pipeline()'s own On Hold inclusion).
			item["current_stage"] = next(
				(s for s in STAGES if s in stage_map and stage_map[s].status in ("In Progress", "On Hold")),
				next((s for s in STAGES if s in stage_map and stage_map[s].status == "Pending"), None)
			)
			# JIT stage model (2026-08-13): once current_stage is empty — the
			# item has nothing active/pending right now, either because it's
			# never been started or because its last-started stage just
			# completed — the frontend needs to know which stage to default
			# the Start dialog to. Route-aware: the first stage in the item's
			# own route with no Completed WO yet (not just "first uncompleted
			# WO", since under JIT most stages have no WO at all).
			#
			# Real bug fixed here (2026-08-30): "is this item fully done" used
			# to be computed client-side by counting stage_map entries with a
			# status at all — but under JIT, stage_map only ever has an entry
			# per stage that's had a Work Order created, not per stage in the
			# item's real route. An item that just finished stage 1 of a real
			# 5-stage route has exactly one stage_map entry (Completed), so
			# that old count read "1 of 1 done" — 100% — and with "Hide
			# completed items" on by default (it is), the item vanished from
			# the Active Production Plan entirely with no way to continue it,
			# right after its very first stage. is_fully_done is now computed
			# here, against the item's real route length, once — the
			# frontend no longer guesses.
			if item.item_code not in item_route_cache:
				item_route_cache[item.item_code] = _get_stage_route(item.item_code, os.get("location"))
			route = item_route_cache[item.item_code]
			completed = {s for s in route if s in stage_map and stage_map[s].status == "Completed"}
			item["is_fully_done"] = bool(route) and completed == set(route)
			# Same real-route basis for progress % — the frontend previously
			# divided by "stages with any WO at all", which is the identical
			# bug as is_fully_done above and read 100% after just stage 1.
			item["route_length"] = len(route)
			item["route_completed_count"] = len(completed)

			if not item["current_stage"]:
				item["next_stage_suggestion"] = next((s for s in route if s not in completed), None)
			else:
				item["next_stage_suggestion"] = None
		os["items"] = items

	# Comment count per underlying Sales Order — one grouped query for the
	# whole page instead of an N+1 per-card lookup (the dashboard shows a
	# count badge next to each card's comment icon).
	so_names = list({os.sales_order for os in order_sheets if os.sales_order})
	comment_counts = {}
	if so_names:
		placeholders = ", ".join(["%s"] * len(so_names))
		count_rows = frappe.db.sql(
			f"""
			SELECT reference_name, COUNT(*) AS cnt
			FROM `tabComment`
			WHERE reference_doctype = 'Sales Order'
			  AND comment_type = 'Comment'
			  AND reference_name IN ({placeholders})
			GROUP BY reference_name
			""",
			tuple(so_names),
			as_dict=True,
		)
		comment_counts = {r.reference_name: r.cnt for r in count_rows}
	for os in order_sheets:
		os["comment_count"] = comment_counts.get(os.sales_order, 0)

	return {
		"stages": STAGES,
		"order_wise": order_sheets,
	}


@frappe.whitelist()
def hold_work_order(work_order):
	"""Alias for put_on_hold — called by the production stages JS."""
	return put_on_hold(work_order)


@frappe.whitelist()
def assign_machine_to_wo(work_order, machine):
	"""Alias for assign_machine — called by the production stages JS."""
	return assign_machine(work_order, machine)


@frappe.whitelist()
def get_item_wise_view(from_date=None, to_date=None, item_code=None):
	"""Item-wise production view.

	Returns per-item: active WOs, jumbo roll batches, stage progress.
	Groups by item_code across all order sheets.
	"""
	_require_production_role()
	filters = {"status": ["not in", ["Cancelled"]]}
	if item_code:
		filters["item_code"] = item_code

	wos = frappe.db.get_all(
		"IB Work Order",
		filters=filters,
		fields=[
			"name", "item_code", "item_name", "stage", "status",
			"machine", "jumbo_roll", "target_qty", "target_uom", "completed_qty",
			"wastage_qty", "wastage_pct", "order_sheet", "order_sheet_item",
			"sales_order", "started_at", "completed_at", "creation",
		],
		order_by="item_code asc, stage asc",
	)

	# WOs here are grouped by item_code across ALL order sheets — no single
	# shared parent ETD like the single-Order-Sheet item detail view has — so
	# fetch each WO's own Order Sheet delivery_date + customer_name to show
	# alongside its own creation date — customer_name in particular so this
	# view (like every other WO listing on this page) can show which SO/
	# customer a WO belongs to, not just its item code.
	os_names = list({wo.order_sheet for wo in wos if wo.order_sheet})
	os_map = {}
	if os_names:
		os_map = {
			d.name: d
			for d in frappe.get_all(
				"IB Order Sheet",
				filters={"name": ["in", os_names]},
				fields=["name", "delivery_date", "customer_name"],
			)
		}
	for wo in wos:
		os_row = os_map.get(wo.order_sheet)
		wo["delivery_date"] = os_row.delivery_date if os_row else None
		wo["customer_name"] = os_row.customer_name if os_row else None

	# Group by item_code
	item_map = {}
	for wo in wos:
		ic = wo.item_code or "Unknown"
		if ic not in item_map:
			item_map[ic] = {
				"item_code": ic,
				"item_name": wo.item_name or ic,
				"work_orders": [],
				"jumbo_rolls": set(),
				"stages_active": set(),
				"stages_done": set(),
			}
		item_map[ic]["work_orders"].append(dict(wo))
		if wo.jumbo_roll:
			item_map[ic]["jumbo_rolls"].add(wo.jumbo_roll)
		if wo.status == "In Progress":
			item_map[ic]["stages_active"].add(wo.stage)
		elif wo.status == "Completed":
			item_map[ic]["stages_done"].add(wo.stage)

	# Fetch JR details for linked rolls
	all_jr_names = list({jr for data in item_map.values() for jr in data["jumbo_rolls"]})
	jr_detail_map = {}
	if all_jr_names:
		jrs = frappe.db.get_all(
			"IB Jumbo Roll",
			filters={"name": ["in", all_jr_names]},
			fields=["name", "batch_no", "supplier", "gsm", "width_mm",
			        "length_mtr", "sqm", "liner_type", "status"],
		)
		jr_detail_map = {jr.name: dict(jr) for jr in jrs}

	# Build result list
	result = []
	for ic, data in sorted(item_map.items()):
		jr_list = [jr_detail_map.get(jr, {"name": jr}) for jr in data["jumbo_rolls"]]

		# Build stage progress from STAGES order
		stage_progress = {}
		for wo in data["work_orders"]:
			s = wo.get("stage", "")
			if s not in stage_progress or wo["status"] == "In Progress":
				stage_progress[s] = {
					"stage": s,
					"status": wo["status"],
					"wo_name": wo["name"],
					"completed_qty": wo["completed_qty"],
					"target_qty": wo["target_qty"],
					"machine": wo["machine"],
					"jumbo_roll": wo.get("jumbo_roll"),
				}

		# Batch lineage: per JR, chain the WOs that reference it
		batch_chains = []
		for jr_name in data["jumbo_rolls"]:
			chain_wos = [wo for wo in data["work_orders"] if wo.get("jumbo_roll") == jr_name]
			batch_chains.append({
				"jumbo_roll": jr_detail_map.get(jr_name, {"name": jr_name}),
				"work_orders": chain_wos,
			})

		total_wos = len(data["work_orders"])
		completed_wos = sum(1 for wo in data["work_orders"] if wo["status"] == "Completed")
		pct = round(completed_wos / total_wos * 100, 1) if total_wos else 0.0

		result.append({
			"item_code": ic,
			"item_name": data["item_name"],
			"total_wos": total_wos,
			"completed_wos": completed_wos,
			"completion_pct": pct,
			"stages_active": list(data["stages_active"]),
			"stages_done": list(data["stages_done"]),
			"jumbo_rolls": jr_list,
			"stage_progress": stage_progress,
			"batch_chains": batch_chains,
			"work_orders": data["work_orders"],
		})

	return result


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
	return frappe.db.sql(
		"""
		SELECT
			machine,
			DATE(COALESCE(completed_at, modified)) AS prod_date,
			COALESCE(SUM(TIMESTAMPDIFF(SECOND, started_at, completed_at)), 0) / 3600.0 AS run_hours,
			COALESCE(SUM(completed_qty), 0) AS output_qty,
			COALESCE(AVG(wastage_pct), 0) AS avg_wastage_pct,
			COUNT(*) AS wo_count
		FROM `tabIB Work Order`
		WHERE machine IN %(machines)s
		  AND status = 'Completed'
		  AND DATE(COALESCE(completed_at, modified)) BETWEEN %(from_date)s AND %(to_date)s
		GROUP BY machine, DATE(COALESCE(completed_at, modified))
		""",
		{"machines": list(machine_names), "from_date": from_date, "to_date": to_date},
		as_dict=True,
	)


@frappe.whitelist()
def get_machine_wise_dashboard(location=None):
	"""Machine-wise dashboard: per machine — current WOs, today stats, load %.

	location: optional (maharashtra/gujarat/chennai) — matches the shared
	Location filter already honored by Order-wise/Job Bundles on this page;
	previously ignored here so switching locations silently kept showing
	every machine regardless of tab.
	"""
	_require_production_role()
	machine_filters = {"status": "Active"}
	if location:
		machine_filters["location"] = location
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
			fields=["name", "item_code", "item_name", "stage", "status",
			        "target_qty", "completed_qty", "order_sheet", "jumbo_roll",
			        "started_at", "priority", "creation"],
			order_by="started_at asc",
		)
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

	# Fetch all non-cancelled WOs for the order sheet once, then partition per
	# item by order_sheet_item (preferred) with item_code as a legacy-only
	# fallback — same pattern already used in get_order_sheet_detail's
	# order_wise_view. Without this, two Order Sheet Items sharing the same
	# item_code (e.g. one SKU ordered as two line items at different qty)
	# both matched every WO for that item_code, so both items displayed the
	# same merged/wrong stage data (confirmed live via a disposable Order
	# Sheet with a duplicate item_code: the qty=1500 row showed the qty=500
	# row's Work Orders).
	all_wos = frappe.db.get_all(
		"IB Work Order",
		filters={"order_sheet": os_name, "status": ["not in", ["Cancelled"]]},
		fields=["name", "item_code", "order_sheet_item", "stage", "status", "machine",
		        "target_qty", "completed_qty", "wastage_pct", "started_at", "completed_at"],
	)
	wo_by_osi = {}
	wo_by_item_legacy = {}
	for wo in all_wos:
		if wo.order_sheet_item:
			wo_by_osi.setdefault(wo.order_sheet_item, []).append(wo)
		else:
			wo_by_item_legacy.setdefault(wo.item_code, []).append(wo)

	for item in os_doc.items:
		stage_route = _get_stage_route(item.item_code, location)
		wos = wo_by_osi.get(item.name) or wo_by_item_legacy.get(item.item_code, [])
		wo_by_stage = {wo.stage: wo for wo in wos}

		stages_out = []
		current_stage = None
		for stage in stage_route:
			wo = wo_by_stage.get(stage)
			entry = {
				"stage":        stage,
				"wo_name":      wo.name if wo else None,
				"status":       wo.status if wo else "Not Created",
				"machine":      wo.machine if wo else None,
				"target_qty":   flt(wo.target_qty) if wo else 0,
				"completed_qty": flt(wo.completed_qty) if wo else 0,
				"wastage_pct":  flt(wo.wastage_pct) if wo else 0,
				"started_at":   wo.started_at if wo else None,
				"completed_at": wo.completed_at if wo else None,
			}
			stages_out.append(entry)
			if wo and wo.status in ("Pending", "In Progress") and not current_stage:
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
	Order Sheet, or (None, None, None) if it has none. Internal — no permission
	check, callers must already be in a trusted/system context (this is what
	the sales-facing whitelisted APIs call, after their own access check).

	Keyed by order_sheet_item (child row name), not bare item_code — same fix
	already applied to get_so_production_status/get_order_sheet_detail (see
	their comments). This function was missed during that pass: an Order Sheet
	with two lines sharing one item_code (a real, valid scenario) had both
	lines' Work Orders merged into a single stage set here, so the Production
	Tracker's pct/current_stage and the 25/50/75/100% milestone notifications
	(on_work_order_update_notify, which calls this) could both be wrong for
	such an order even though the drill-down timeline (get_so_production_status)
	already showed the correct per-item split.
	"""
	os_name = frappe.db.get_value(
		"IB Order Sheet", {"sales_order": so_name, "status": ["!=", "Cancelled"]}, "name"
	)
	if not os_name:
		return None, None, None

	location = frappe.db.get_value("Sales Order", so_name, "custom_location")
	items = frappe.db.get_all("IB Order Sheet Item", filters={"parent": os_name}, fields=["name", "item_code"])
	wos = frappe.db.get_all(
		"IB Work Order",
		filters={"order_sheet": os_name, "status": ["!=", "Cancelled"]},
		fields=["item_code", "order_sheet_item", "stage", "status"],
	)
	wo_by_osi = {}
	wo_by_item_legacy = {}
	for wo in wos:
		if wo.order_sheet_item:
			wo_by_osi.setdefault(wo.order_sheet_item, []).append(wo)
		else:
			wo_by_item_legacy.setdefault(wo.item_code, []).append(wo)

	items_summary = []
	for item in items:
		route = _get_stage_route(item.item_code, location)
		item_wos_list = wo_by_osi.get(item.name) or wo_by_item_legacy.get(item.item_code, [])
		item_wos = {w.stage: w for w in item_wos_list}
		stages = [{"stage": s, "status": item_wos[s].status if s in item_wos else "Not Created"} for s in route]
		current = next((s["stage"] for s in stages if s["status"] in ("Pending", "In Progress")), None)
		items_summary.append({"stages": stages, "current_stage": current})

	pct, current_stage = _order_progress_summary(os_name, items_summary)
	return pct, current_stage, os_name


_PROGRESS_MILESTONES = [25, 50, 75, 100]


def on_work_order_update_notify(doc, method=None):
	"""Notify the sales person as their order's production progresses, at
	25/50/75/100% milestones — not just the old Ready-to-Deliver-only signal.
	Each milestone fires once ever per Sales Order (dedup via subject marker,
	no date bound — unlike the old RTD-only version, a milestone should never
	repeat, not just never-repeat-same-day)."""
	if doc.status != "Completed":
		return
	if not doc.order_sheet:
		return

	so_name = frappe.db.get_value("IB Order Sheet", doc.order_sheet, "sales_order")
	if not so_name:
		return

	sales_person_user = frappe.db.get_value("Sales Order", so_name, "custom_sales_person_user")
	if not sales_person_user:
		return

	pct, current_stage, _os_name = _so_progress_pct(so_name)
	if pct is None:
		return

	milestone = max((m for m in _PROGRESS_MILESTONES if pct >= m), default=None)
	if milestone is None:
		return

	marker = f"[ib-prod-{so_name}-{milestone}]"
	if frappe.db.exists("Notification Log", {"for_user": sales_person_user, "subject": ["like", f"%{marker}%"]}):
		return

	customer = frappe.db.get_value("Sales Order", so_name, "customer_name") or ""
	if milestone == 100:
		subject = f"Order Ready for Dispatch: {so_name}"
		body = (
			f"<p>Sales Order <strong>{so_name}</strong> for <strong>{customer}</strong> "
			f"has completed all production stages and is <strong>Ready to Deliver</strong>. "
			f"Please arrange packaging and dispatch to the customer's delivery address.</p>"
		)
	else:
		stage_txt = f" — now in <strong>{current_stage}</strong>" if current_stage else ""
		subject = f"Production Update: {so_name} is {milestone}% complete"
		body = (
			f"<p>Sales Order <strong>{so_name}</strong> for <strong>{customer}</strong> "
			f"is now <strong>{milestone}% through production</strong>{stage_txt}.</p>"
		)

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


@frappe.whitelist()
def update_production_qty(work_order, pcs_to_make=None, logs_to_make=None):
	"""Factory manager reconciliation: set pcs_to_make / logs_to_make on a WO to
	account for wastage and plan how many pieces/logs to actually make from the
	target qty. Simple field update — IB Work Order is not submittable, so no
	need for a full doc.save() cycle here."""
	_require_production_role()
	wo_row = frappe.db.get_value("IB Work Order", work_order, ["target_uom", "status"], as_dict=True)
	if wo_row is None:
		frappe.throw(_("Work Order {0} not found").format(work_order))
	target_uom = wo_row.target_uom

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

