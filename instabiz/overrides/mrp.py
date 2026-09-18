"""instabiz.overrides.mrp

MRP Phase 1 — flat single-level BOM explosion (via `IB Production Recipe`,
not ERPNext's native multi-level `BOM` doctype — Phase 1 spec wants a
lightweight flat table, deliberately not routed through native BOM).

Daily scheduler (run_mrp): explodes open Sales Order demand through
IB Production Recipe (finished_item -> recipe_item x qty_per) to get total
raw-material demand, compares it against company-wide Bin stock, and
auto-creates a draft (docstatus=0) Purchase Material Request for every
recipe_item where demand exceeds available stock. A later wave
(Guardrailed Autonomy) depends on these draft MRs existing, so this
function must actually create real documents, not just log/notify.

Assumptions (document here since none of this is spelled out elsewhere):
  - "Outstanding qty" per open Sales Order Item = stock_qty - delivered_qty
    (stock-UOM terms). This app's dimension-based items transact in a
    different UOM (e.g. PCS) than stock_uom (e.g. SQMT) — stock_qty is the
    already-converted figure ERPNext itself uses to derive delivered_qty /
    per_delivered, so it is the only apples-to-apples "how much raw
    material is this SO row still going to consume" number.
  - Bin stock is summed company-wide across all warehouses (this app has a
    single Company — "Instabiz Solutions India Pvt Ltd" — across its 3
    location warehouses MAHARASHTRA - IB / GUJARAT - IB / CHENNAI - IB).
    Sales Orders aren't reliably 1:1 warehouse-scoped to the location that
    will eventually fulfil them, so a company-wide shortfall check is the
    simplest correct model for Phase 1.
  - New draft MRs are created against Stock Settings' default warehouse,
    falling back to the Maharashtra warehouse.
  - Lead time: schedule_date = today + MRP_LEAD_TIME_DAYS. No per-item
    lead-time field exists yet in this app, so a flat generic default is
    used (documented, easy to promote to a per-item field later).
"""
import frappe
from frappe.utils import add_days, nowdate, flt

from instabiz.overrides.utils import LOCATION_WAREHOUSE

MRP_LEAD_TIME_DAYS = 14


# ── pure calculation helpers (no DB access — directly unit-testable) ───────

def _explode_demand(finished_demand, recipes):
	"""{finished_item: outstanding_qty} x [{finished_item, recipe_item,
	qty_per}, ...] -> {recipe_item: total_raw_material_demand}.
	"""
	raw_demand = {}
	for r in recipes:
		fi = r["finished_item"]
		outstanding = finished_demand.get(fi)
		if not outstanding:
			continue
		need = flt(outstanding) * flt(r["qty_per"])
		if need <= 0:
			continue
		raw_demand[r["recipe_item"]] = raw_demand.get(r["recipe_item"], 0) + need
	return raw_demand


def _compute_shortfalls(raw_demand, stock_map):
	"""{item: demand} x {item: stock} -> {item: shortfall_qty} — only items
	where demand exceeds available stock.
	"""
	out = {}
	for item_code, demand in raw_demand.items():
		stock = flt(stock_map.get(item_code, 0))
		shortfall = flt(demand) - stock
		if shortfall > 0:
			out[item_code] = shortfall
	return out


# ── DB-backed steps ─────────────────────────────────────────────────────────

def _open_so_demand():
	"""item_code -> total outstanding stock_qty across open Sales Orders
	(docstatus=1, not fully delivered, not Closed/Cancelled).
	"""
	from instabiz.overrides.ib_status import stored_statuses

	rows = frappe.db.sql(
		"""
		SELECT soi.item_code, SUM(soi.stock_qty - soi.delivered_qty) AS outstanding
		FROM `tabSales Order Item` soi
		INNER JOIN `tabSales Order` so ON so.name = soi.parent
		WHERE so.docstatus = 1
		  AND so.per_delivered < 100
		  AND so.status NOT IN %(closed)s
		GROUP BY soi.item_code
		HAVING outstanding > 0
		""",
		{"closed": stored_statuses("Sales Order", "Closed", "Cancelled")},
		as_dict=True,
	)
	return {r.item_code: flt(r.outstanding) for r in rows}


def _stock_by_item(item_codes):
	if not item_codes:
		return {}
	rows = frappe.db.sql(
		"""
		SELECT item_code, SUM(actual_qty) AS qty
		FROM `tabBin`
		WHERE item_code IN %(items)s
		GROUP BY item_code
		""",
		{"items": tuple(item_codes)},
		as_dict=True,
	)
	return {r.item_code: flt(r.qty) for r in rows}


def _existing_mrp_draft_covers(item_code):
	"""True if an open MRP-sourced Purchase MR (draft, or submitted but not
	yet fully ordered) already exists for this item — skip creating a
	duplicate draft for the same shortfall on every day's run.
	"""
	return bool(frappe.db.sql(
		"""
		SELECT mri.parent
		FROM `tabMaterial Request Item` mri
		INNER JOIN `tabMaterial Request` mr ON mr.name = mri.parent
		WHERE mri.item_code = %s
		  AND mr.custom_mrp_source = 1
		  AND mr.docstatus IN (0, 1)
		  AND mr.status NOT IN ('Cancelled', 'Stopped')
		  AND (mri.qty - IFNULL(mri.ordered_qty, 0)) > 0
		LIMIT 1
		""",
		(item_code,),
	))


def _create_draft_mr(item_code, qty):
	rounded_qty = round(flt(qty), 2)
	if rounded_qty <= 0:
		# Sub-0.01 shortfall rounds to 0.00 — Material Request Item rejects
		# qty <= 0 on insert, which would otherwise turn a negligible
		# shortfall into a daily recurring Error Log entry (the draft never
		# gets created, so _existing_mrp_draft_covers never suppresses the
		# retry). Skip silently instead.
		return None

	item = frappe.db.get_value("Item", item_code, ["item_name", "stock_uom"], as_dict=True)
	if not item:
		return None

	company = frappe.db.get_single_value("Global Defaults", "default_company")
	warehouse = (
		frappe.db.get_single_value("Stock Settings", "default_warehouse")
		or LOCATION_WAREHOUSE.get("maharashtra")
	)

	mr = frappe.get_doc({
		"doctype": "Material Request",
		"material_request_type": "Purchase",
		"transaction_date": nowdate(),
		"company": company,
		"custom_mrp_source": 1,
	})
	mr.append("items", {
		"item_code": item_code,
		"item_name": item.item_name,
		"qty": rounded_qty,
		"uom": item.stock_uom,
		"stock_uom": item.stock_uom,
		"conversion_factor": 1,
		"warehouse": warehouse,
		"schedule_date": add_days(nowdate(), MRP_LEAD_TIME_DAYS),
	})
	mr.insert(ignore_permissions=True)

	return mr.name


# ── entry points ─────────────────────────────────────────────────────────

def run_mrp(trigger="schedule"):
	"""Daily scheduler entry point (also callable on-demand via run_mrp_now(),
	console/API only — no dashboard button wired to it yet). Never throws —
	every failure is caught, logged, and isolated so one bad item can't zero
	out the whole run.
	"""
	result = {"shortfalls": 0, "created": [], "errors": 0}
	try:
		finished_demand = _open_so_demand()
		if not finished_demand:
			frappe.logger().info("[mrp] no open SO demand")
			return result

		recipes = frappe.get_all(
			"IB Production Recipe",
			filters={"finished_item": ["in", list(finished_demand.keys())]},
			fields=["finished_item", "recipe_item", "qty_per"],
		)
		if not recipes:
			frappe.logger().info("[mrp] no IB Production Recipe rows match open SO demand")
			return result

		raw_demand = _explode_demand(finished_demand, recipes)
		stock_map = _stock_by_item(list(raw_demand.keys()))
		shortfalls = _compute_shortfalls(raw_demand, stock_map)
		result["shortfalls"] = len(shortfalls)

		for idx, (item_code, shortfall_qty) in enumerate(shortfalls.items()):
			# Savepoint name must be a valid unqualified SQL identifier — a raw
			# item_code (hyphens/dots, e.g. "IS-52143V-140CRRBNL-2") breaks this,
			# same gotcha already hit and documented in auto_absent.py. Use a
			# plain index instead of sanitizing the item_code.
			save_point = f"mrp_row_{idx}"
			try:
				frappe.db.savepoint(save_point)
				if _existing_mrp_draft_covers(item_code):
					continue
				name = _create_draft_mr(item_code, shortfall_qty)
				if name:
					result["created"].append(name)
			except Exception:
				result["errors"] += 1
				frappe.log_error(
					title=f"run_mrp: failed to create draft MR for {item_code}",
					message=frappe.get_traceback(),
				)
				frappe.db.rollback(save_point=save_point)
				continue

		if result["created"]:
			frappe.db.commit()

		frappe.logger().info(
			f"[mrp] {result['shortfalls']} shortfalls, "
			f"{len(result['created'])} draft MRs created, {result['errors']} errors"
		)
	except Exception:
		frappe.log_error(title="run_mrp: fatal error", message=frappe.get_traceback())
		result["errors"] += 1

	return result


@frappe.whitelist()
def run_mrp_now():
	"""Whitelisted wrapper for the 'Run MRP' Production Dashboard button."""
	allowed_roles = {"System Manager", "Factory Management", "Purchase Manager", "Stock Manager"}
	if not (allowed_roles & set(frappe.get_roles())):
		frappe.throw("Not permitted to run MRP.", frappe.PermissionError)
	return run_mrp(trigger="manual")
