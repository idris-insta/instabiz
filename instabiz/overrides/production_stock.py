"""instabiz.overrides.production_stock

Phase 3 — real stock-ledger integration for the WO-per-run production model.

Everything here is gated behind the `ib_production_posts_stock` site_config
flag (off by default, per the name already promised in production_run.py's
own module docstring since Phase 1). When the flag is off, every function
below is a no-op — IB Batch's existing annotation-level qty tracking
(separate from this, unaffected) is the only accounting that happens,
exactly as it has all along.

Flow per run, when the flag is on:

  Start  (create_run):  RM warehouse -> WIP warehouse         (Material Transfer)
  Finish (_finish_run):  WIP warehouse -> FG warehouse(s)      (Repack, one row
                          per real output row with produced_qty > 0)
                       -> WIP warehouse -> Scrap warehouse     (Repack, same
                          entry, RM-equivalent wastage qty) -- ONLY when a
                          real IB Production Recipe ratio exists for the
                          RM/FG item pair. Never guessed for a pair with no
                          recipe data; that pair's wastage simply isn't
                          posted to Scrap (matches how wastage already works
                          for every item today — a tracked number on the
                          run, no stock movement).
  Cancel (cancel_run):   reverses whichever of the above already posted, via
                          a real Stock Entry .cancel() (correctly reverses
                          the ledger), not a manual counter-posting.

Only Gujarat has real production machines/floors today (established
throughout this app's history — Maharashtra/Chennai are warehouse-only) —
warehouse resolution below is Gujarat-only by design, same as every other
location-gated piece of this module (_WAREHOUSE_ONLY_LOCATIONS,
IB Production Floor, etc).
"""
import frappe
from frappe.utils import flt, nowdate

_LOCATION_WAREHOUSES = {
	"gujarat": {
		"wip": "WIP - GUJARAT - IB",
		"fg": "Finished Goods - GUJARAT - IB",
		"scrap": "Scrap - GUJARAT - IB",
	},
}


def posts_stock():
	return bool(frappe.conf.get("ib_production_posts_stock"))


def _wh(location, kind):
	return (_LOCATION_WAREHOUSES.get((location or "").lower()) or {}).get(kind)


def _company():
	return frappe.db.get_single_value("Global Defaults", "default_company")


def _recipe_ratio(rm_item, fg_item):
	"""RM qty consumed per 1 unit of fg_item, or None if no real recipe
	exists for this exact pair. Never guessed/defaulted — see this module's
	own docstring for why."""
	if not rm_item or not fg_item:
		return None
	return frappe.db.get_value(
		"IB Production Recipe", {"finished_item": fg_item, "recipe_item": rm_item}, "qty_per"
	)


def post_run_start_transfer(doc):
	"""RM warehouse -> WIP, for the run's full source_qty. Called from
	create_run(), inside its existing per-order-sheet lock, right after the
	IB Batch qty reservation. Returns the Stock Entry name, or None if stock
	posting is off, the run's location isn't wired (non-Gujarat), or the
	source batch has no resolvable warehouse (e.g. a batch created before
	this feature existed and never backfilled)."""
	if not posts_stock():
		return None
	wip = _wh(doc.location, "wip")
	if not wip or not doc.source_warehouse:
		return None
	se = frappe.new_doc("Stock Entry")
	se.stock_entry_type = "Material Transfer"
	se.company = _company()
	se.posting_date = nowdate()
	se.append("items", {
		"item_code": doc.source_item,
		"qty": flt(doc.source_qty),
		"s_warehouse": doc.source_warehouse,
		"t_warehouse": wip,
	})
	se.remarks = f"IB Work Order {doc.name} — start transfer (RM -> WIP)"
	se.insert(ignore_permissions=True)
	se.submit()
	return se.name


def post_run_finish_transfer(doc):
	"""WIP -> FG (one row per real output) + WIP -> Scrap (RM-equivalent
	wastage, only where a real recipe ratio resolves). Called from
	_finish_run() after doc.outputs' produced_qty is final. Returns the
	Stock Entry name, or None if there's nothing real to post (stock
	posting off, no start transfer ever happened for this run, or every
	output produced zero)."""
	if not posts_stock():
		return None
	wip = _wh(doc.location, "wip")
	fg = _wh(doc.location, "fg")
	if not wip or not fg or not doc.get("start_stock_entry"):
		return None

	se = frappe.new_doc("Stock Entry")
	se.stock_entry_type = "Repack"
	se.company = _company()
	se.posting_date = nowdate()
	se.append("items", {
		"item_code": doc.source_item,
		"qty": flt(doc.source_qty),
		"s_warehouse": wip,
	})

	produce_rows = 0
	total_fg_equiv = 0.0
	for o in doc.outputs:
		qty = flt(o.produced_qty)
		if qty <= 0:
			continue
		se.append("items", {
			"item_code": o.item_code,
			"qty": qty,
			"t_warehouse": fg,
		})
		produce_rows += 1
		ratio = _recipe_ratio(doc.source_item, o.item_code)
		if ratio:
			total_fg_equiv += qty * flt(ratio)

	if not produce_rows:
		return None

	scrap = _wh(doc.location, "scrap")
	if scrap and total_fg_equiv:
		wastage_qty = flt(doc.source_qty) - total_fg_equiv
		if wastage_qty > 0:
			se.append("items", {
				"item_code": doc.source_item,
				"qty": wastage_qty,
				"t_warehouse": scrap,
			})

	se.remarks = f"IB Work Order {doc.name} — finish (WIP -> FG/Scrap)"
	se.insert(ignore_permissions=True)
	se.submit()
	return se.name


def reverse_run_stock(doc):
	"""Cancel whichever Stock Entries this run posted (finish entry first,
	then start entry — no real ordering dependency between two unlinked
	Stock Entries, but cancelling the later one first mirrors normal
	unwind order). Called from cancel_run(). A real Stock Entry .cancel()
	correctly reverses the ledger; never posts a manual counter-entry."""
	for fieldname in ("stock_entry", "start_stock_entry"):
		name = doc.get(fieldname)
		if not name:
			continue
		if frappe.db.get_value("Stock Entry", name, "docstatus") == 1:
			frappe.get_doc("Stock Entry", name).cancel()
