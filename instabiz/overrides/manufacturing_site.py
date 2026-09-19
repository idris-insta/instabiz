"""instabiz.overrides.manufacturing_site

Two kinds of stock location:

  factory   — Warehouse "Manufacturing" ticked (on the warehouse or any group above
              it, so ticking GUJARAT - IB covers every floor under it). Orders
              supplied from here go through production (order sheet, runs, stages)
              and the finished goods are posted to stock when a run completes.
  warehouse — everything else. Material only comes in and goes out: an order
              supplied from here gets no production at all; the Delivery Note
              takes the stock out directly.

A Sales Order is made in the factory when the warehouse it ships from (header,
else its lines, else its location's main warehouse) is a factory.
"""
import frappe
from frappe import _

FIELD = "custom_manufacturing_enabled"


def is_factory(warehouse):
	if not warehouse or not frappe.db.has_column("Warehouse", FIELD):
		return False
	cache = frappe.flags.setdefault("ib_factory_wh", {})
	if warehouse in cache:
		return cache[warehouse]
	row = frappe.db.get_value("Warehouse", warehouse, ["lft", "rgt", FIELD], as_dict=True)
	val = bool(row and (row.get(FIELD) or frappe.db.exists("Warehouse", {"lft": ["<", row.lft], "rgt": [">", row.rgt], FIELD: 1})))
	cache[warehouse] = val
	return val


def location_has_factory(location):
	"""A location (maharashtra / gujarat / chennai) counts as a factory when its main
	warehouse, anything under it, or anything above it is ticked."""
	from instabiz.overrides.utils import LOCATION_WAREHOUSE

	wh = LOCATION_WAREHOUSE.get((location or "").lower())
	if not wh or not frappe.db.has_column("Warehouse", FIELD):
		return False
	if is_factory(wh):
		return True
	lft, rgt = frappe.db.get_value("Warehouse", wh, ["lft", "rgt"]) or (0, 0)
	return bool(frappe.db.exists("Warehouse", {"lft": [">", lft], "rgt": ["<", rgt], FIELD: 1}))


def factory_warehouses(location=None):
	"""Leaf warehouses where production can happen (optionally for one location)."""
	out = []
	for w in frappe.get_all("Warehouse", filters={"is_group": 0, "disabled": 0}, fields=["name"]):
		if is_factory(w.name) and (not location or _location_of(w.name) == (location or "").lower()):
			out.append(w.name)
	return out


def _location_of(warehouse):
	from instabiz.overrides.utils import LOCATION_WAREHOUSE

	lft, rgt = frappe.db.get_value("Warehouse", warehouse, ["lft", "rgt"]) or (0, 0)
	for loc, main in LOCATION_WAREHOUSE.items():
		m = frappe.db.get_value("Warehouse", main, ["lft", "rgt"], as_dict=True)
		if m and m.lft <= lft and m.rgt >= rgt:
			return loc
	return None


def so_needs_production(sales_order):
	so = frappe.get_doc("Sales Order", sales_order) if isinstance(sales_order, str) else sales_order
	whs = [so.get("set_warehouse")] + [r.warehouse for r in so.items]
	whs = [w for w in whs if w]
	if whs:
		return any(is_factory(w) for w in whs)
	return location_has_factory(so.get("custom_location"))


class _WarehouseOnlyLocations:
	"""Drop-in for the old hard-coded {"maharashtra", "chennai"}: a location is
	warehouse-only when nothing in it is ticked Manufacturing."""

	def __contains__(self, location):
		loc = (location or "").lower()
		if not loc:
			return False
		cache = frappe.flags.setdefault("ib_wh_only_loc", {})
		if loc not in cache:
			cache[loc] = not location_has_factory(loc)
		return cache[loc]

	def __iter__(self):
		from instabiz.overrides.utils import LOCATION_WAREHOUSE

		return iter([loc for loc in LOCATION_WAREHOUSE if loc in self])


def after_migrate():
	if not frappe.db.exists("Custom Field", {"dt": "Warehouse", "fieldname": FIELD}):
		frappe.get_doc({"doctype": "Custom Field", "dt": "Warehouse", "fieldname": FIELD, "fieldtype": "Check",
			"label": "Manufacturing (material is processed / cut here)", "insert_after": "is_group", "in_list_view": 1,
			"in_standard_filter": 1,
			"description": "Ticked: orders shipped from here go through production and finished goods are posted when a run completes. "
				"Not ticked: a plain warehouse — stock only comes in and goes out, the Delivery Note takes it out directly. "
				"Ticking a group (e.g. GUJARAT - IB) covers every floor under it."}).insert(ignore_permissions=True)
		# first time: keep today's behaviour — Gujarat is the factory
		if frappe.db.exists("Warehouse", "GUJARAT - IB"):
			frappe.db.set_value("Warehouse", "GUJARAT - IB", FIELD, 1, update_modified=False)
