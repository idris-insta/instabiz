"""IB MRP Plan — raw material needed for open Sales Orders.

Open order qty (not yet delivered) × IB Production Recipe → raw material
needed, against stock in hand and on open purchase orders. Shortfall = needed −
stock − on order. Finished items with open orders but no recipe are listed in
the message so recipes get filled. "Create Draft Requests" runs
instabiz.overrides.mrp.run_mrp (one draft Purchase Material Request per short
item, skipping items already covered by an open MRP request).
"""
import frappe
from frappe import _
from frappe.utils import flt

from instabiz.overrides.mrp import _explode_demand, _open_so_demand


def execute(filters=None):
	f = frappe._dict(filters or {})
	demand = _open_so_demand()
	recipes = frappe.get_all("IB Production Recipe", filters={"finished_item": ["in", list(demand) or [""]]},
		fields=["finished_item", "recipe_item", "qty_per"])
	mapped = {r.finished_item for r in recipes}
	raw = _explode_demand(demand, recipes)
	bins = {}
	if raw:
		for b in frappe.db.sql("""SELECT item_code, SUM(actual_qty) actual, SUM(ordered_qty) ordered
				FROM `tabBin` WHERE item_code IN %s GROUP BY item_code""", (tuple(raw),), as_dict=True):
			bins[b.item_code] = b
	names = {i.name: i for i in frappe.get_all("Item", filters={"name": ["in", list(raw) or [""]]},
		fields=["name", "item_name", "stock_uom"])}
	used_by = {}
	for r in recipes:
		if r.finished_item in demand:
			used_by.setdefault(r.recipe_item, []).append(r.finished_item)
	rows = []
	for item, need in raw.items():
		b = bins.get(item) or frappe._dict(actual=0, ordered=0)
		short = flt(need) - flt(b.actual) - flt(b.ordered)
		rows.append(frappe._dict(raw_item=item, item_name=(names.get(item) or {}).get("item_name"),
			uom=(names.get(item) or {}).get("stock_uom"), required=flt(need, 3), in_stock=flt(b.actual, 3),
			on_order=flt(b.ordered, 3), shortfall=flt(max(short, 0), 3), for_items=len(used_by.get(item, []))))
	if f.only_shortfall:
		rows = [r for r in rows if r.shortfall > 0]
	rows.sort(key=lambda r: -r.shortfall)
	unmapped = sorted(set(demand) - mapped)
	msg = None
	if unmapped:
		msg = _("{0} finished items have open orders but no IB Production Recipe, so their raw material is not in this plan: {1}").format(
			len(unmapped), ", ".join(unmapped[:15]) + (f" (+{len(unmapped) - 15} more)" if len(unmapped) > 15 else ""))
	cols = [
		{"label": _("Raw Material"), "fieldname": "raw_item", "fieldtype": "Link", "options": "Item", "width": 190},
		{"label": _("Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 200},
		{"label": _("UOM"), "fieldname": "uom", "fieldtype": "Data", "width": 65},
		{"label": _("Needed"), "fieldname": "required", "fieldtype": "Float", "width": 110},
		{"label": _("In Stock"), "fieldname": "in_stock", "fieldtype": "Float", "width": 110},
		{"label": _("On Order"), "fieldname": "on_order", "fieldtype": "Float", "width": 110},
		{"label": _("Shortfall"), "fieldname": "shortfall", "fieldtype": "Float", "width": 110},
		{"label": _("For Items"), "fieldname": "for_items", "fieldtype": "Int", "width": 80},
	]
	short = [r for r in rows if r.shortfall > 0]
	summary = [
		{"label": _("Raw materials planned"), "value": len(raw), "datatype": "Int"},
		{"label": _("Short"), "value": len(short), "datatype": "Int", "indicator": "red" if short else "green"},
		{"label": _("Items without recipe"), "value": len(unmapped), "datatype": "Int", "indicator": "orange" if unmapped else "green"},
	]
	chart = {"data": {"labels": [r.item_name or r.raw_item for r in short[:10]],
		"datasets": [{"name": _("Shortfall"), "values": [r.shortfall for r in short[:10]]}]}, "type": "bar",
		"colors": ["#d97757"]} if short else None
	return cols, rows, msg, chart, summary
