"""instabiz.overrides.slitting_plan — which jumbo to slit, and which widths
together, for the least trim waste.

For every open Order Sheet in a factory location, the lines not yet in a run
whose route includes Slitting are grouped by raw material: the item itself
(item codes are jumbo specs — the Sales Order line carries the cut width and
length), or the IB Production Recipe item when a roll is made from another item. For each group every Active raw-material IB Batch of
that item with a width is tried: widths are packed best-fit-decreasing into
passes (Σ widths ≤ jumbo width − edge trim, ≤ knife positions of the slitters)
and the jumbo that leaves the least trim wins; equal trim → the oldest batch
(FIFO). No batch yet (stock that came in before batch tracking): the item's
stock in the location's warehouses counts as one jumbo of the item's width, and
Create Run registers it as an IB Batch first. Plan only — "Create Run" hands one
pass to production_run.create_run, the same path as starting a run by hand.
"""
import json

import frappe
from frappe import _
from frappe.utils import flt, getdate

from instabiz.overrides import ib_settings


def _trim():
	return ib_settings.get_float("slitting_trim_mm", 20)


def _knives():
	return frappe.db.sql("""SELECT COALESCE(MAX(knife_positions), 0) FROM `tabIB Machine`
		WHERE machine_type = 'Slitting' AND status = 'Active'""")[0][0] or 0


def _line(osi, os_name):
	dims = frappe.db.get_value("Sales Order Item", osi.sales_order_item, ["width_mm", "length_mtr"], as_dict=True) or {}
	im = frappe.db.get_value("Item", osi.item_code, ["width_mm", "length_mtr", "stock_uom"], as_dict=True) or {}
	gsm = frappe.db.get_value("Item", osi.item_code, "gsm") if frappe.db.has_column("Item", "gsm") else 0
	return {"order_sheet": os_name, "order_sheet_item": osi.name, "sales_order_item": osi.sales_order_item,
		"item_code": osi.item_code, "item_name": osi.item_name, "planned_qty": flt(osi.qty),
		"uom": osi.uom or im.get("stock_uom"), "width_mm": flt(dims.get("width_mm") or im.get("width_mm")),
		"length_mtr": flt(dims.get("length_mtr") or im.get("length_mtr")), "gsm": flt(gsm),
		"m2": _m2(osi.item_code, osi.uom or im.get("stock_uom"), flt(dims.get("width_mm") or im.get("width_mm")),
			flt(dims.get("length_mtr") or im.get("length_mtr")), flt(osi.qty))}


def _m2(item_code, uom, width_mm, length_mtr, qty):
	"""Line qty in the jumbo's unit: rolls × m² per roll for tape, else the qty."""
	from instabiz.overrides.utils import roll_area

	area = roll_area(item_code, uom, width_mm, length_mtr)
	return qty * area if area else qty


def _pending_lines(os_name, location):
	from instabiz.overrides.production import _get_stage_route

	out = []
	for osi in frappe.get_all("IB Order Sheet Item", filters={"parent": os_name},
			fields=["name", "item_code", "item_name", "qty", "uom", "sales_order_item", "status"]):
		if osi.status in ("Completed", "Cancelled") or flt(osi.qty) <= 0:
			continue
		if osi.sales_order_item and frappe.db.exists("IB WO Output",
				{"sales_order_item": osi.sales_order_item, "docstatus": ["<", 2]}):
			continue
		if "Slitting" not in (_get_stage_route(osi.item_code, location) or []):
			continue
		out.append(_line(osi, os_name))
	return out


def _pack(lines, usable, knives):
	"""Best-fit decreasing. Returns (passes, too_wide)."""
	passes, too_wide = [], []
	for ln in sorted(lines, key=lambda x: x["width_mm"], reverse=True):
		if usable and ln["width_mm"] > usable:
			too_wide.append(ln)
			continue
		best, best_left = None, None
		for p in passes:
			left = usable - sum(o["width_mm"] for o in p) - ln["width_mm"] if usable else 0
			if (not usable or left >= 0) and (not knives or len(p) < knives):
				if best is None or left < best_left:
					best, best_left = p, left
		if best is None:
			passes.append([ln])
		else:
			best.append(ln)
	return passes, too_wide


def _batches(rm_item, location):
	from instabiz.overrides.production_run import _batch_source_warehouse
	from instabiz.overrides.promise_date import _warehouses

	whs = set(_warehouses(location))
	out = []
	for b in frappe.get_all("IB Batch", filters={"kind": "Raw Material", "status": "Active", "item": rm_item,
			"qty": [">", 0], "width_mm": [">", 0]}, fields=["name", "item", "qty", "width_mm", "received_date", "creation"]):
		wh = _batch_source_warehouse(b.name)
		if whs and wh and wh not in whs:
			continue
		out.append(b)
	out.sort(key=lambda b: (getdate(b.received_date or b.creation), b.name))
	return out


def _stock_as_jumbo(item, location):
	"""Stock of the item in the location (no IB Batch yet) → one pseudo jumbo per warehouse."""
	from instabiz.overrides.promise_date import _warehouses

	width = flt(frappe.db.get_value("Item", item, "width_mm"))
	whs = _warehouses(location)
	if not width or not whs:
		return []
	out = []
	for wh, qty in frappe.db.sql("""SELECT warehouse, actual_qty FROM `tabBin` WHERE item_code = %s
			AND warehouse IN %s AND actual_qty > 0 ORDER BY actual_qty DESC""", (item, tuple(whs))):
		out.append(frappe._dict(name=f"STOCK::{item}::{wh}", item=item, qty=flt(qty), width_mm=width,
			received_date=None, creation=frappe.utils.nowdate(), warehouse=wh))
	return out


def _register_stock_batch(pseudo):
	_prefix, item, wh = pseudo.split("::", 2)
	qty = flt(frappe.db.get_value("Bin", {"item_code": item, "warehouse": wh}, "actual_qty"))
	if qty <= 0:
		frappe.throw(_("No stock of {0} left in {1}.").format(item, wh))
	n = frappe.db.count("IB Batch", {"batch_id": ["like", f"{item}::STOCK::%"]}) + 1
	b = frappe.get_doc({"doctype": "IB Batch", "batch_id": f"{item}::STOCK::{frappe.utils.nowdate()}::{n}",
		"kind": "Raw Material", "item": item, "qty": qty, "status": "Active", "received_date": frappe.utils.nowdate(),
		"width_mm": flt(frappe.db.get_value("Item", item, "width_mm"))}).insert(ignore_permissions=True)
	return b.name, wh


def _best(lines, batches, trim, knives):
	"""Try each distinct jumbo width (oldest batch of it); least trim % wins."""
	best = None
	seen = set()
	for b in batches:
		if flt(b.width_mm) in seen:
			continue
		seen.add(flt(b.width_mm))
		usable = flt(b.width_mm) - trim
		passes, too_wide = _pack(lines, usable, knives)
		if not passes:
			continue
		trim_total = sum(flt(b.width_mm) - sum(o["width_mm"] for o in p) for p in passes)
		waste = trim_total / (flt(b.width_mm) * len(passes)) * 100
		score = (len(too_wide), round(waste, 3))
		if best is None or score < best[0]:
			best = (score, b, passes, too_wide, waste)
	return best


def plan(location=None, order_sheet=None, source_batch=None):
	"""Open lines of every order in the location (or one Order Sheet), grouped by raw
	material ACROSS orders, so strips of different customers share one jumbo pass."""
	trim, knives = _trim(), _knives()
	filters = {"status": ["in", ["Draft", "In Progress"]]}
	if order_sheet:
		filters["name"] = order_sheet
	groups, heads, unplanned = {}, {}, []
	for os in frappe.get_all("IB Order Sheet", filters=filters, fields=["name", "sales_order", "priority"],
			order_by="creation asc"):
		so = frappe.db.get_value("Sales Order", os.sales_order, ["custom_location", "customer", "delivery_date"],
			as_dict=True) or frappe._dict()
		loc = (so.custom_location or "").lower()
		if location and loc != location.lower():
			continue
		head = {"order_sheet": os.name, "sales_order": os.sales_order, "customer": so.customer,
			"delivery_date": so.delivery_date, "priority": os.priority}
		heads[os.name] = head
		for ln in _pending_lines(os.name, loc):
			rm = frappe.db.get_value("IB Production Recipe", {"finished_item": ln["item_code"]}, "recipe_item") \
				or ln["item_code"]
			groups.setdefault((loc, rm), []).append({**head, **ln})

	rows = []
	for (loc, rm), glines in groups.items():
		if source_batch:
			b = frappe.db.get_value("IB Batch", source_batch, ["name", "item", "qty", "width_mm", "received_date",
				"creation"], as_dict=True)
			cands = [b] if b and flt(b.width_mm) else []
		else:
			cands = _batches(rm, loc) or _stock_as_jumbo(rm, loc)
		if not cands:
			for ln in glines:
				unplanned.append({**ln, "reason": _("no {0} jumbo in {1} stock").format(rm, loc.title())})
			continue
		found = _best(glines, cands, trim, knives)
		if not found:
			continue
		_score, b, passes, too_wide, _waste = found
		for ln in too_wide:
			unplanned.append({**ln, "reason": _("wider than the {0} jumbo").format(b.item)})
		for i, p in enumerate(passes, 1):
			used = sum(o["width_mm"] for o in p)
			need = round(sum(flt(o["m2"]) for o in p), 2)
			sheets = sorted({o["order_sheet"] for o in p})
			first = heads[sheets[0]]
			rows.append({"order_sheet": sheets[0] if len(sheets) == 1 else _("{0} orders").format(len(sheets)),
				"sales_order": first["sales_order"] if len(sheets) == 1 else "",
				"customer": ", ".join(sorted({heads[s]["customer"] or "" for s in sheets}))[:140],
				"delivery_date": min((heads[s]["delivery_date"] for s in sheets if heads[s]["delivery_date"]), default=None),
				"orders": len(sheets), "rm_item": b.item, "source_batch": b.name, "jumbo_width": flt(b.width_mm),
				"jumbo_qty": flt(b.qty), "need_qty": need,
				"note": _("this jumbo covers {0} of {1}; the rest stays in the plan").format(flt(b.qty), need)
				if flt(b.qty) < need else "",
				"pass_no": i, "widths": " + ".join(f"{o['width_mm']:g}" for o in p), "lines": len(p),
				"used_width": used, "trim_mm": round(flt(b.width_mm) - used, 1),
				"trim_pct": round((flt(b.width_mm) - used) / flt(b.width_mm) * 100, 2),
				"osi": json.dumps([o["order_sheet_item"] for o in p]),
				"items": "; ".join(f"{o['customer'] or ''}: {o['width_mm']:g}mm ×{o['planned_qty']:g}" for o in p)})
	rows.sort(key=lambda r: (r["rm_item"], r["pass_no"]))
	return {"rows": rows, "unplanned": unplanned, "trim_mm": trim, "knives": knives}


@frappe.whitelist()
def create_pass(source_batch, order_sheet_items, order_sheet=None):
	"""One run per order in the pass, all on the same jumbo (same knife setup). The
	jumbo qty is split by width — every strip runs the full length of the jumbo."""
	from instabiz.overrides.production_run import create_run

	names = json.loads(order_sheet_items) if isinstance(order_sheet_items, str) else order_sheet_items
	by_sheet = {}
	for n in names or []:
		osi = frappe.db.get_value("IB Order Sheet Item", n, ["name", "parent", "item_code", "item_name", "qty", "uom",
			"sales_order_item"], as_dict=True)
		if not osi:
			frappe.throw(_("Line {0} not found — refresh the plan.").format(n))
		by_sheet.setdefault(osi.parent, []).append(_line(osi, osi.parent))
	if not by_sheet:
		frappe.throw(_("Nothing to run."))
	stock_wh = None
	if source_batch.startswith("STOCK::"):
		source_batch, stock_wh = _register_stock_batch(source_batch)
	# every strip runs the full jumbo length: each order gets the jumbo in proportion to its widths
	have_total = flt(frappe.db.get_value("IB Batch", source_batch, "qty"))
	used_width = sum(flt(o["width_mm"]) for outs in by_sheet.values() for o in outs) or 1
	runs, waiting = [], []
	for sheet, outputs in by_sheet.items():
		have = flt(frappe.db.get_value("IB Batch", source_batch, "qty"))
		share = have_total * sum(flt(o["width_mm"]) for o in outputs) / used_width
		need = sum(flt(o["m2"]) for o in outputs)
		take = round(min(need, share, have), 3)
		if take <= 0:
			waiting.append(sheet)
			continue
		run = create_run(sheet, source_batch, source_qty=take, outputs=json.dumps(outputs))
		if stock_wh:
			frappe.db.set_value("IB Work Order", run, "source_warehouse", stock_wh, update_modified=False)
		runs.append(run)
	return {"runs": runs, "waiting": waiting}
