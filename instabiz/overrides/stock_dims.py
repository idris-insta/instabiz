"""Item dimension + specification fields on every transaction row.

Quotation is the reference layout: thickness, colour, width, length, qty/pkg,
total pkgs, branding, marking, specifications, description and attachment. The
same eleven fields are put on purchase, stock, material request, stock
reconciliation, subcontracting and manufacturing rows, so an item reads the
same wherever it is added and the mappers carry it down the chain unchanged
(the field names are identical everywhere, which is what get_mapped_doc copies
on).

They fetch from the Item and only when empty, so a cut width / length typed on
the row stays.

Grids hold about eleven columns' worth before Frappe starts dropping the rest,
so each grid is laid out here: item, the four dimensions, qty and the one or
two columns that matter. Branding, marking, specifications, description and the
attachment stay in the row form — the sales grids only carry them because their
whole layout was rebuilt by property setters (fixtures/property_setter.json),
and the purchase / stock grids are already at the cap.

Manufacturing rows (BOM, Work Order, Subcontracting) take the block read-only:
those lines are raw material and WIP, so the numbers belong to the Item, not to
whoever is typing the line.
"""
import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.utils import flt

from instabiz.overrides.utils import dimension_qty, roll_area

# fieldname, label, fieldtype, options, precision, in grid
# The first six are what a person reads to know which roll they are entering —
# the same six the Quotation grid shows — so they are columns, not form fields.
FIELDS = [
	("custom_thickness", "Thickness", "Data", None, None, 1),
	("color", "Color", "Link", "Item Color", None, 1),
	("width_mm", "Width (MM)", "Float", None, "3", 1),
	("length_mtr", "Length (MTR)", "Float", None, "3", 1),
	("qty_pkg", "QTY/PKG", "Float", None, "2", 1),
	("total_pkg", "Total PKG", "Float", None, "2", 1),
	("custom_branding", "Branding", "Link", "IB Branding", None, 0),
	("custom_marking", "Marking", "Data", None, None, 0),
	("custom_specifications", "Specifications", "Small Text", None, None, 0),
	("custom_description", "Description", "Small Text", None, None, 0),
	("custom_attachment", "Attachment", "Attach", None, None, 0),
]

# row fieldname -> the Item fieldname it fetches from. total_pkg, branding,
# marking, description and the attachment are per-line by nature and have no
# Item-level source — same as on Quotation.
ITEM_FETCH = {
	"custom_thickness": "custom_thickness",
	"color": "color",
	"width_mm": "width_mm",
	"length_mtr": "length_mtr",
	"qty_pkg": "qty_pkg",
	"custom_specifications": "description",
}

# Raw-material / WIP rows: the block is shown for traceability but never typed.
READ_ONLY_ROWS = {
	"BOM Item",
	"Work Order Item",
	"Subcontracting Order Item",
	"Subcontracting Receipt Item",
}

# Frappe's grid starts its width counter at 1 and abandons the rest of the row
# the moment the running total passes 11 (frappe/public/js/frappe/form/grid.js),
# so ten columns of weight 1 is the most that can ever show. Quotation's row is
# exactly that — item, the six spec fields, then the two numbers that price it —
# and it is the row everyone already reads, so every other grid is laid out to
# match it as closely as that doctype's own job allows.
#
# standard fields: {fieldname: columns}, 0 = out of the grid (still on the row
# form, and still addable per-user through the grid's own Configure Columns).
# The six spec fields are added by _ensure_fields at weight 1 each, so each grid
# below has exactly four slots left to spend.
_SPEC_COLUMNS = 6

GRIDS = {
	# Selling. These four were flagging 14-19 columns' worth, so Frappe gave up
	# part-way through the row and a user with no saved column preference saw
	# four to seven of them — Quotation rendered item, rate, attachment and
	# thickness, and dropped colour, width, length, QTY/PKG and Total PKG. The
	# tidy row everyone quotes from is a per-user Configure Columns setting, not
	# what the app ships. Spelled out here so it is the default for everybody.
	# (A user's own saved layout still wins over this — nobody loses theirs.)
	"Quotation Item": {"item_code": 1, "uom": 1, "rate": 1, "amount": 1,
		"qty": 0, "custom_attachment": 0},
	"Sales Order Item": {"item_code": 1, "uom": 1, "rate": 1, "amount": 1,
		"qty": 0, "custom_attachment": 0, "delivery_date": 0, "warehouse": 0},
	# A delivery is about which goods left which floor, so the warehouse earns a
	# column here that the invoice spends on money.
	"Delivery Note Item": {"item_code": 1, "uom": 1, "qty": 1, "warehouse": 1,
		"rate": 0, "amount": 0, "batch_no": 0, "custom_attachment": 0,
		"custom_qty_adjustment_note": 0, "custom_total_weight_kg": 0},
	"Sales Invoice Item": {"item_code": 1, "uom": 1, "rate": 1, "amount": 1,
		"qty": 0, "custom_attachment": 0, "warehouse": 0},
	# Buying: same ten columns as Quotation. qty leaves the grid — it is derived
	# from QTY/PKG x Total PKG, which are now both columns, so the inputs are
	# visible instead of the result.
	"Purchase Order Item": {"item_code": 1, "uom": 1, "rate": 1, "amount": 1,
		"qty": 0, "schedule_date": 0, "warehouse": 0},
	# Receipts care where the goods land more than what they total to.
	"Purchase Receipt Item": {"item_code": 1, "uom": 1, "rate": 1, "warehouse": 1,
		"qty": 0, "amount": 0, "rejected_qty": 0, "net_amount": 0},
	"Purchase Invoice Item": {"item_code": 1, "uom": 1, "rate": 1, "amount": 1, "qty": 0},
	"Supplier Quotation Item": {"item_code": 1, "uom": 1, "rate": 1, "amount": 1,
		"qty": 0, "warehouse": 0},
	# Stock: both warehouses have to stay — a transfer is meaningless without
	# them — so the rate column goes to the row form instead.
	"Stock Entry Detail": {"item_code": 1, "uom": 1, "s_warehouse": 1, "t_warehouse": 1,
		"qty": 0, "basic_rate": 0, "item_tax_template": 0},
	"Material Request Item": {"item_code": 1, "uom": 1, "warehouse": 1, "qty": 1,
		"schedule_date": 0},
	"Stock Reconciliation Item": {"item_code": 1, "warehouse": 1, "qty": 1,
		"valuation_rate": 1, "stock_uom": 0},
	# Manufacturing rows are raw material and WIP: the spec is there to read, not
	# to type, so the remaining slots go to quantities rather than prices.
	"BOM Item": {"item_code": 1, "uom": 1, "qty": 1, "rate": 1, "amount": 0},
	"Work Order Item": {"item_code": 1, "required_qty": 1, "transferred_qty": 1,
		"source_warehouse": 1, "consumed_qty": 0, "returned_qty": 0},
	"Subcontracting Order Item": {"item_code": 1, "qty": 1, "rate": 1, "amount": 1,
		"bom": 0, "item_tax_template": 0},
	"Subcontracting Receipt Item": {"item_code": 1, "qty": 1, "rate": 1, "warehouse": 1,
		"rejected_qty": 0, "amount": 0, "item_tax_template": 0},
}


def after_migrate():
	for dt, grid in GRIDS.items():
		if not frappe.db.exists("DocType", dt):
			continue
		_ensure_fields(dt)
		meta = frappe.get_meta(dt)
		for fieldname, columns in grid.items():
			if not meta.get_field(fieldname):
				continue
			_set_column(dt, meta, fieldname, columns)

		# Anything else still flagged as a column would push the row past the
		# cap and silently drop whatever came after it, so the planned set is
		# the whole set. Nothing is lost: every field stays on the row form, and
		# a user can add it back for themselves via Configure Columns.
		planned = set(grid) | {f[0] for f in FIELDS}
		for df in meta.fields:
			if df.in_list_view and df.fieldname not in planned:
				_set_column(dt, meta, df.fieldname, 0)

		frappe.clear_cache(doctype=dt)


def _set_column(dt, meta, fieldname, columns):
	"""in_list_view + width for one field, whichever layer owns it."""
	df = meta.get_field(fieldname)
	if not df:
		return
	if df.get("is_custom_field"):
		frappe.db.set_value("Custom Field", {"dt": dt, "fieldname": fieldname},
			{"in_list_view": 1 if columns else 0, "columns": columns})
		return
	make_property_setter(dt, fieldname, "in_list_view", 1 if columns else 0, "Check",
		validate_fields_for_doctype=False)
	if columns:
		make_property_setter(dt, fieldname, "columns", columns, "Int",
			validate_fields_for_doctype=False)


def grid_budgets():
	"""What each row actually renders, and whether it fits.

	Frappe starts the counter at 1 and bails past 11, so 10 is the real budget.
	"""
	out = {}
	for dt in GRIDS:
		if not frappe.db.exists("DocType", dt):
			continue
		meta = frappe.get_meta(dt)
		cols = [(df.fieldname, df.columns or 1) for df in meta.fields if df.in_list_view]
		out[dt] = {"total": sum(c for _, c in cols), "columns": cols}
	return out


def _ensure_fields(dt):
	read_only = 1 if dt in READ_ONLY_ROWS else 0
	after = "item_name"
	for fieldname, label, fieldtype, options, precision, in_grid in FIELDS:
		values = {"in_list_view": in_grid, "columns": 1 if in_grid else 0, "read_only": read_only}
		name = frappe.db.get_value("Custom Field", {"dt": dt, "fieldname": fieldname})
		if name:
			frappe.db.set_value("Custom Field", name, values)
			# An older run (or the fixtures) may have created the field without a
			# source; fill it in, but never overwrite one that is already set.
			source = ITEM_FETCH.get(fieldname)
			if source and not frappe.db.get_value("Custom Field", name, "fetch_from"):
				frappe.db.set_value("Custom Field", name, {
					"fetch_from": f"item_code.{source}", "fetch_if_empty": 1})
		elif not frappe.get_meta(dt).get_field(fieldname):
			source = ITEM_FETCH.get(fieldname)
			frappe.get_doc({"doctype": "Custom Field", "dt": dt, "fieldname": fieldname, "label": label,
				"fieldtype": fieldtype, "options": options, "precision": precision, "insert_after": after,
				"fetch_from": f"item_code.{source}" if source else None,
				"fetch_if_empty": 1, **values}).insert(ignore_permissions=True)
		after = fieldname
	# Purchase rows already had colour / width / length further down: keep thickness with them
	thickness = frappe.db.get_value("Custom Field", {"dt": dt, "fieldname": "custom_thickness"}, ["name", "insert_after"],
		as_dict=True)
	if thickness and thickness.insert_after == "item_name" and frappe.db.get_value(
			"Custom Field", {"dt": dt, "fieldname": "color"}, "insert_after") not in (None, "custom_thickness"):
		frappe.db.set_value("Custom Field", thickness.name, "insert_after", "length_mtr")


def apply_dimension_qty(doc, method=None):
	"""before_validate: derive qty from the row's dimensions.

	Same rule as Quotation (utils.dimension_qty) — an SQMT row multiplies out its
	width, length, qty/pkg and pkgs; any other UOM is qty/pkg × pkgs; a row whose
	dimensions don't add up to an answer keeps whatever qty was typed.

	Runs before the controller's own validate() so ERPNext recomputes amounts and
	totals from the derived qty, not from the one the user started with.
	"""
	for row in doc.get("items") or []:
		if not row.get("item_code"):
			continue
		derived = dimension_qty(row.get("uom") or row.get("stock_uom"), row.get("width_mm"),
			row.get("length_mtr"), row.get("qty_pkg"), row.get("total_pkg"))
		if derived is not None:
			row.qty = round(derived, 6)


def stock_entry_before_validate(doc, method=None):
	"""Transfers / receipts / issues in rolls of an SQMT item: conversion factor =
	m² per roll from the row's width × length, so the ledger moves real m².
	Production (Repack / Manufacture) sets its own factor per output."""
	if doc.purpose in ("Repack", "Manufacture"):
		return
	# qty first — transfer_qty below is derived from it, so a dimension-driven
	# qty has to land before the conversion factor is applied to it.
	apply_dimension_qty(doc)
	for row in doc.get("items") or []:
		area = roll_area(row.item_code, row.uom, row.get("width_mm"), row.get("length_mtr"))
		if area:
			row.conversion_factor = area
			row.transfer_qty = flt(row.qty) * area
