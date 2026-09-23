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
from frappe import _
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


def _real_uom_conversion_factor(item_code, uom, stock_uom):
	"""How many `stock_uom` one `uom` unit of item_code is worth, or None if
	there's no REAL UOM Conversion Detail row for this exact pair. Never
	falls back to a generic UOM-category conversion or a silent 1.0 the way
	ERPNext's own `get_item_details.get_conversion_factor` does — confirmed
	live (2026-09-21) that every real run's UOM WO Output row whose `uom`
	differs from its Item's `stock_uom` (11 of 11 sampled, e.g. produced_qty
	in PCS against an item stock-tracked in SQMT) has zero UOM Conversion
	Detail row for that pair. Posting `produced_qty` straight into a Stock
	Entry Item row with no explicit uom/conversion_factor silently defaults
	conversion_factor to 1.0 — i.e. "144 PCS produced" would post as "144
	SQMT received", an item-specific, unbounded, silently-wrong stock
	quantity the moment ib_production_posts_stock is switched on. Real fix:
	resolve every output row's conversion explicitly before posting; a row
	with no real conversion blocks the whole finish-transfer post (see
	post_run_finish_transfer) rather than posting a subset at a guessed
	factor."""
	if not uom or uom == stock_uom:
		return 1.0
	return frappe.db.get_value(
		"UOM Conversion Detail", {"parent": item_code, "uom": uom}, "conversion_factor"
	) or None


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
	# IB Batch has no separate uom field — batch.qty (source_qty's origin) is
	# always in the source item's own stock_uom, so this is a defensive
	# explicit statement of what's already true, not a conversion — same
	# reasoning as the explicit uom now set in post_run_finish_transfer below.
	se.append("items", {
		"item_code": doc.source_item,
		"qty": flt(doc.source_qty),
		"uom": frappe.get_cached_value("Item", doc.source_item, "stock_uom"),
		"conversion_factor": 1.0,
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

	# Real bug, fixed here: an IB WO Output row's `uom` (the unit the operator
	# actually recorded produced_qty in — PCS/KG/SQMT, independent per row)
	# can differ from its Item's `stock_uom`. Confirmed live: every real run
	# where that happens has zero real UOM Conversion Detail for the pair, so
	# posting `qty=produced_qty` with no explicit uom/conversion_factor would
	# have Frappe silently default conversion_factor to 1.0 — crediting FG
	# stock in the WRONG unit at face value (144 PCS posted as 144 SQMT).
	# Resolve every row's real conversion factor up front; if even one
	# output row can't be safely converted, refuse the whole finish-transfer
	# post rather than posting some rows correctly and silently dropping/
	# mis-posting others (which would also desync WIP-consumed vs FG-credited
	# qty). Matches this module's own no-guessing convention (_recipe_ratio).
	plan = []
	for o in doc.outputs:
		qty = flt(o.produced_qty)
		if qty <= 0:
			continue
		stock_uom = frappe.get_cached_value("Item", o.item_code, "stock_uom")
		factor = _real_uom_conversion_factor(o.item_code, o.uom, stock_uom)
		if factor is None:
			# Real bug, fixed here: this used to log_error + return None —
			# post_run_finish_transfer's caller (_finish_run) never checked
			# that return value, so the run still completed normally (FG
			# batch + serial genealogy created, workflow -> Completed) with
			# NO finish transfer ever posted. Confirmed live: WIP stock for
			# the source item is left stuck there forever (never credited
			# out), the FG item never actually lands in the FG warehouse's
			# Bin despite genealogy claiming a real unit was produced, and
			# `stock_entry` stays blank on the run — a completed run
			# reporting real output that was never actually received into
			# stock anywhere, silently. Raising here instead aborts the
			# whole Finish action (doc.save() above hasn't been committed
			# yet — frappe.db.commit() only runs after this in advance_run
			# — so the request rolls back the Completed status too, not
			# just the stock post), same "refuse rather than silently
			# drift" rule this module's own docstring already applies to
			# the posting logic, now applied to completion itself.
			frappe.throw(_(
				"Cannot complete this run: output '{0}' is recorded in '{1}' but its Item's "
				"stock unit is '{2}', and there is no UOM Conversion Detail for that exact "
				"pair. Add the conversion on the Item first, then try Finish again."
			).format(o.item_name or o.item_code, o.uom, stock_uom))
		plan.append({"item_code": o.item_code, "qty": qty, "uom": o.uom or stock_uom,
		             "conversion_factor": factor})

	if not plan:
		return None

	se = frappe.new_doc("Stock Entry")
	se.stock_entry_type = "Repack"
	se.company = _company()
	se.posting_date = nowdate()
	source_stock_uom = frappe.get_cached_value("Item", doc.source_item, "stock_uom")
	se.append("items", {
		"item_code": doc.source_item,
		"qty": flt(doc.source_qty),
		"uom": source_stock_uom,
		"conversion_factor": 1.0,
		"s_warehouse": wip,
	})

	produce_rows = 0
	total_fg_equiv = 0.0
	for row in plan:
		# Real bug, fixed here: a Repack entry's `t_warehouse`-only rows are
		# ALL treated as `is_finished_item` by core (mark_finished_and_scrap_
		# items — true for the scrap row below too, not just FG output rows,
		# since purpose == "Repack" flags every such row regardless of intent).
		# Core's validate_repack_entry() then hard-throws "the basic rate for
		# all finished goods must be set manually" the moment more than one
		# such row exists in one entry — reachable on every real multi-output
		# run (several real outputs sharing one source batch/pass is the
		# normal case here, not an edge case), confirmed live. Setting
		# set_basic_rate_manually + an explicit basic_rate on every one of
		# these rows up front avoids the throw regardless of row count.
		rate = flt(frappe.get_cached_value("Item", row["item_code"], "valuation_rate"))
		se_row = {
			"item_code": row["item_code"],
			"qty": row["qty"],
			"uom": row["uom"],
			"conversion_factor": row["conversion_factor"],
			"t_warehouse": fg,
			"set_basic_rate_manually": 1,
			"basic_rate": rate,
		}
		# Real bug, fixed here: an FG item produced for the first time ever
		# (no prior incoming-valued stock anywhere) has no resolvable
		# valuation rate — ERPNext's get_valuation_rate() then hard-throws
		# "Valuation Rate ... is required", an uncaught ValidationError that
		# would abort the whole Finish action (advance_run/_finish_run),
		# confirmed live. Same class of gap already fixed for Container
		# Import's Material Receipt (ib_container_import.py _make_stock_entry)
		# — same fallback: post at zero value rather than hard-blocking a
		# real production completion over a bookkeeping gap; a real cost can
		# be set on the item master and reposted later.
		if not rate:
			se_row["allow_zero_valuation_rate"] = 1
		se.append("items", se_row)
		produce_rows += 1
		ratio = _recipe_ratio(doc.source_item, row["item_code"])
		if ratio:
			total_fg_equiv += row["qty"] * flt(ratio)

	if not produce_rows:
		return None

	scrap = _wh(doc.location, "scrap")
	if scrap and total_fg_equiv:
		wastage_qty = flt(doc.source_qty) - total_fg_equiv
		if wastage_qty > 0:
			scrap_rate = flt(frappe.get_cached_value("Item", doc.source_item, "valuation_rate"))
			scrap_row = {
				"item_code": doc.source_item,
				"qty": wastage_qty,
				"uom": source_stock_uom,
				"conversion_factor": 1.0,
				"t_warehouse": scrap,
				"set_basic_rate_manually": 1,
				"basic_rate": scrap_rate,
			}
			if not scrap_rate:
				scrap_row["allow_zero_valuation_rate"] = 1
			se.append("items", scrap_row)

	se.remarks = f"IB Work Order {doc.name} — finish (WIP -> FG/Scrap)"
	se.insert(ignore_permissions=True)
	se.submit()
	return se.name


def reverse_run_stock(doc):
	"""Cancel whichever Stock Entries this run posted (finish entry first,
	then start entry — no real ordering dependency between two unlinked
	Stock Entries, but cancelling the later one first mirrors normal
	unwind order). Called from cancel_run(). A real Stock Entry .cancel()
	correctly reverses the ledger; never posts a manual counter-entry.

	Real bug, fixed here: advance_with_length_split() gives every sibling
	run the SAME start_stock_entry (the parent's one RM->WIP transfer,
	divided into shares — see that function's own comment). A naive
	unconditional cancel would reverse the WHOLE shared transfer the
	moment any ONE sibling got cancelled, clawing back material still
	legitimately in WIP for the other siblings — leaving them unable to
	Finish (their own Repack would try to consume from WIP that's no
	longer there). The shared transfer is only actually cancelled once
	every run referencing it has been dealt with (Cancelled itself, or
	this run's own doc, since cancel_run() calls this before the
	workflow transition below has flipped this run's own status yet)."""
	stock_entry = doc.get("stock_entry")
	if stock_entry and frappe.db.get_value("Stock Entry", stock_entry, "docstatus") == 1:
		frappe.get_doc("Stock Entry", stock_entry).cancel()

	start_se = doc.get("start_stock_entry")
	if start_se and frappe.db.get_value("Stock Entry", start_se, "docstatus") == 1:
		still_needed = frappe.db.exists("IB Work Order", {
			"start_stock_entry": start_se,
			"name": ["!=", doc.name],
			"status": ["!=", "Cancelled"],
		})
		if not still_needed:
			frappe.get_doc("Stock Entry", start_se).cancel()
