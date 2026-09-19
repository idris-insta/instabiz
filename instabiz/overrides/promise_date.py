"""instabiz.overrides.promise_date

A delivery date the rep can actually promise, worked out line by line while the
Sales Order is being entered (instead of order date + 8 days for everything):

  stock       free stock in the order's location (all floors / sub-warehouses)
              covers the line → dispatch in `promise_dispatch_days` (1).
              Free = stock on hand − what other open orders of the last
              `promise_open_order_days` (30) still need from that location.
              ERPNext's reserved qty isn't used: orders here are rarely closed
              with a Delivery Note, so reservations from months ago never clear.
  transit     stock on its way to this location (branch transfer in Goods In
              Transit, not yet received) → dispatch date + `promise_transit_days` (4)
  production  factory location: the delivery simulator's finish date for the
              line (real machine backlog and throughput) + 1 day
  purchase    nothing to hand → `replenishment_lead_days` (7)

Lines of the same item draw on the same free stock in order. The order's promise
date is the latest line. Read only — nothing is written.
"""
import json

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, nowdate

from instabiz.overrides import ib_settings


def _location_tree(location):
	"""(lft, rgt) covering every warehouse of a location (group + floors)."""
	loc = (location or "").strip().upper()
	if not loc:
		return None
	row = frappe.db.get_value("Warehouse", {"name": ["like", f"{loc} - %"], "is_group": 1}, ["lft", "rgt"]) \
		or frappe.db.get_value("Warehouse", {"name": ["like", f"{loc} - %"]}, ["lft", "rgt"])
	if not row:
		from instabiz.overrides.utils import LOCATION_WAREHOUSE

		wh = LOCATION_WAREHOUSE.get(loc.lower())
		row = wh and frappe.db.get_value("Warehouse", wh, ["lft", "rgt"])
	return row or None


def _warehouses(location, set_warehouse=None):
	tree = _location_tree(location)
	if not tree and set_warehouse:
		tree = frappe.db.get_value("Warehouse", set_warehouse, ["lft", "rgt"])
	if not tree:
		return []
	return frappe.get_all("Warehouse", filters={"lft": [">=", tree[0]], "rgt": ["<=", tree[1]], "is_group": 0}, pluck="name")


def _free_stock(item_codes, warehouses, exclude_so=None):
	if not item_codes or not warehouses:
		return {}
	stock = {r.item_code: flt(r.qty) for r in frappe.db.sql("""SELECT item_code, SUM(actual_qty) AS qty FROM `tabBin`
		WHERE item_code IN %s AND warehouse IN %s GROUP BY item_code""", (tuple(item_codes), tuple(warehouses)), as_dict=True)}
	demand = open_demand(item_codes, warehouses, exclude_so)
	return {i: stock.get(i, 0) - demand.get(i, 0) for i in item_codes}


def open_demand(item_codes, warehouses, exclude_so=None):
	"""Qty still to deliver on submitted orders of the last promise_open_order_days
	that ship from these warehouses (line warehouse, else the order's)."""
	days = ib_settings.get_int("promise_open_order_days", 30)
	rows = frappe.db.sql("""SELECT c.item_code,
			SUM(GREATEST(c.stock_qty - IFNULL(c.delivered_qty, 0) * IFNULL(c.conversion_factor, 1), 0)) AS qty
		FROM `tabSales Order Item` c JOIN `tabSales Order` p ON p.name = c.parent
		WHERE p.docstatus = 1 AND p.transaction_date >= %s AND IFNULL(p.per_delivered, 0) < 100
			AND p.status NOT IN ('Closed', 'Cancelled') AND p.name != %s
			AND COALESCE(NULLIF(c.warehouse, ''), p.set_warehouse) IN %s AND c.item_code IN %s
		GROUP BY c.item_code""", (add_days(nowdate(), -days), exclude_so or "", tuple(warehouses), tuple(item_codes)), as_dict=True)
	return {r.item_code: flt(r.qty) for r in rows}


def _in_transit(item_codes, warehouses):
	"""{item: [(qty, dispatched_on), ...]} still in transit to these warehouses."""
	if not item_codes or not warehouses:
		return {}
	rows = frappe.db.sql("""SELECT d.item_code, d.transfer_qty * (1 - IFNULL(se.per_transferred, 0) / 100) AS qty,
			se.posting_date FROM `tabStock Entry Detail` d JOIN `tabStock Entry` se ON se.name = d.parent
		WHERE se.docstatus = 1 AND se.add_to_transit = 1 AND IFNULL(se.per_transferred, 0) < 100
			AND se.custom_final_warehouse IN %s AND d.item_code IN %s ORDER BY se.posting_date""",
		(tuple(warehouses), tuple(item_codes)), as_dict=True) \
		if frappe.db.has_column("Stock Entry", "custom_final_warehouse") else []
	out = {}
	for r in rows:
		out.setdefault(r.item_code, []).append([flt(r.qty), r.posting_date])
	return out


def _production_date(sales_order, item_code, qty, location):
	from instabiz.overrides.production import _get_stage_route
	from instabiz.overrides.production_twin import _simulate_item

	try:
		route = _get_stage_route(item_code, location)
		res = _simulate_item(sales_order, item_code, qty, route, location)
		if any(s.get("status") == "no_machine_available" for s in res.get("stages") or []):
			return None, _("no machine set up for a stage")
		return add_days(getdate(res["estimated_completion_date"]), 1), None
	except Exception:
		frappe.log_error("IB promise date", frappe.get_traceback())
		return None, _("production estimate unavailable")


def promise(doc):
	"""doc: Sales Order doc or dict with items / custom_location / set_warehouse."""
	doc = frappe._dict(doc)
	items = [frappe._dict(i) for i in (doc.get("items") or []) if i.get("item_code")]
	location = (doc.get("custom_location") or "").strip()
	if location.lower() == "select":
		location = ""
	today = getdate(nowdate())
	dispatch = ib_settings.get_int("promise_dispatch_days", 1)
	transit_days = ib_settings.get_int("promise_transit_days", 4)
	lead = ib_settings.get_int("replenishment_lead_days", 7)

	whs = _warehouses(location, doc.get("set_warehouse"))
	codes = list({i.item_code for i in items})
	free = _free_stock(codes, whs, doc.get("name"))
	transit = _in_transit(codes, whs)
	factory = False
	if location:
		from instabiz.overrides.manufacturing_site import is_factory, location_has_factory

		factory = is_factory(doc.set_warehouse) if doc.get("set_warehouse") else location_has_factory(location)
	so_name = doc.get("name") if doc.get("docstatus") == 1 else None

	lines = []
	for i in items:
		need = flt(i.stock_qty) or flt(i.qty) * (flt(i.conversion_factor) or 1)
		if so_name:  # only what is still to deliver (this order is left out of open demand)
			need = max(need - flt(i.delivered_qty) * (flt(i.conversion_factor) or 1), 0)
		line = {"idx": i.idx, "item_code": i.item_code, "qty": need}
		have = free.get(i.item_code, 0)
		if need <= 0:
			line.update(source="Delivered", date=str(today), note=_("nothing left to deliver"))
		elif have >= need:
			free[i.item_code] = have - need
			line.update(source="Stock", date=str(add_days(today, dispatch)), note=_("in stock"))
		else:
			short = need - max(have, 0)
			free[i.item_code] = min(have, 0) - short if have < 0 else 0
			covered_on = None
			for batch in transit.get(i.item_code, []):
				if short <= 0:
					break
				take = min(batch[0], short)
				batch[0] -= take
				short -= take
				covered_on = batch[1]
			if short <= 0 and covered_on:
				d = max(add_days(getdate(covered_on), transit_days), add_days(today, dispatch))
				line.update(source="Transit", date=str(d), note=_("stock on its way from another branch"))
			elif factory:
				d, err = _production_date(so_name, i.item_code, need, location.lower())
				if d:
					line.update(source="Production", date=str(max(d, add_days(today, dispatch))),
						note=_("to be made — {0} short").format(round(short, 2)))
				else:
					line.update(source="Production", date=str(add_days(today, lead)),
						note=_("to be made ({0}) — default lead time used").format(err))
			else:
				line.update(source="Purchase", date=str(add_days(today, lead)),
					note=_("{0} short, no stock or transit — buy / transfer lead time").format(round(short, 2)))
		lines.append(line)

	overall = max((getdate(line["date"]) for line in lines), default=add_days(today, dispatch))
	counts = {}
	for line in lines:
		counts[line["source"]] = counts.get(line["source"], 0) + 1
	return {"promise_date": str(overall), "lines": lines, "counts": counts, "location": location}


@frappe.whitelist()
def get_promise(doc=None, sales_order=None):
	if sales_order:
		so = frappe.get_doc("Sales Order", sales_order)
		so.check_permission("read")
		return promise(so.as_dict())
	if isinstance(doc, str):
		doc = json.loads(doc)
	if not doc:
		frappe.throw(_("Nothing to check."))
	if not frappe.has_permission("Sales Order", "read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return promise(doc)
