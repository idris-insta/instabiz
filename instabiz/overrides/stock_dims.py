"""Item dimensions (thickness, colour, width, length, qty/pkg, pkgs) on stock and
purchase rows: Stock Entry, Material Request, Stock Reconciliation, Purchase
Order / Receipt / Invoice. They fetch from the Item (only when empty, so a cut
width / length typed on the row stays) and are copied along the document chain
by the standard mappers (same field names as on Sales Order / Delivery Note).

Grids show at most ~10 columns, so each grid is laid out here: item, the four
dimensions, qty and the one or two columns that matter; the rest stay in the
row form."""
import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter
from frappe.utils import flt

from instabiz.overrides.utils import roll_area

# fieldname, label, fieldtype, options, precision, in grid
FIELDS = [
	("custom_thickness", "Thickness", "Data", None, None, 1),
	("color", "Color", "Link", "Item Color", None, 1),
	("width_mm", "Width (MM)", "Float", None, "3", 1),
	("length_mtr", "Length (MTR)", "Float", None, "3", 1),
	("qty_pkg", "QTY/PKG", "Float", None, "2", 0),
	("total_pkg", "Total PKG", "Float", None, "2", 0),
]
ITEM_FIELDS = {"custom_thickness", "color", "width_mm", "length_mtr", "qty_pkg"}  # fetched from Item

# standard fields: {fieldname: columns}, 0 = out of the grid
GRIDS = {
	"Stock Entry Detail": {"s_warehouse": 1, "t_warehouse": 1, "qty": 1, "basic_rate": 1, "item_tax_template": 0},
	"Material Request Item": {"schedule_date": 0, "qty": 1, "uom": 1},
	"Stock Reconciliation Item": {"stock_uom": 0, "qty": 1, "valuation_rate": 1},
	"Purchase Order Item": {"schedule_date": 0, "warehouse": 0, "qty": 1, "uom": 1, "rate": 1, "amount": 1},
	"Purchase Receipt Item": {"rejected_qty": 0, "net_amount": 0, "qty": 1, "rate": 1, "amount": 1, "warehouse": 1},
	"Purchase Invoice Item": {"qty": 1, "rate": 1, "amount": 1},
}


def after_migrate():
	for dt, grid in GRIDS.items():
		_ensure_fields(dt)
		meta = frappe.get_meta(dt)
		for fieldname, columns in grid.items():
			if not meta.get_field(fieldname):
				continue
			if meta.get_field(fieldname).get("is_custom_field"):
				frappe.db.set_value("Custom Field", {"dt": dt, "fieldname": fieldname},
					{"in_list_view": 1 if columns else 0, "columns": columns})
				continue
			make_property_setter(dt, fieldname, "in_list_view", 1 if columns else 0, "Check", validate_fields_for_doctype=False)
			if columns:
				make_property_setter(dt, fieldname, "columns", columns, "Int", validate_fields_for_doctype=False)
		frappe.clear_cache(doctype=dt)


def _ensure_fields(dt):
	after = "item_name"
	for fieldname, label, fieldtype, options, precision, in_grid in FIELDS:
		values = {"in_list_view": in_grid, "columns": 1 if in_grid else 0}
		name = frappe.db.get_value("Custom Field", {"dt": dt, "fieldname": fieldname})
		if name:
			frappe.db.set_value("Custom Field", name, values)
		elif not frappe.get_meta(dt).get_field(fieldname):
			frappe.get_doc({"doctype": "Custom Field", "dt": dt, "fieldname": fieldname, "label": label,
				"fieldtype": fieldtype, "options": options, "precision": precision, "insert_after": after,
				"fetch_from": f"item_code.{fieldname}" if fieldname in ITEM_FIELDS else None,
				"fetch_if_empty": 1, **values}).insert(ignore_permissions=True)
		after = fieldname


def stock_entry_before_validate(doc, method=None):
	"""Transfers / receipts / issues in rolls of an SQMT item: conversion factor =
	m² per roll from the row's width × length, so the ledger moves real m².
	Production (Repack / Manufacture) sets its own factor per output."""
	if doc.purpose in ("Repack", "Manufacture"):
		return
	for row in doc.get("items") or []:
		area = roll_area(row.item_code, row.uom, row.get("width_mm"), row.get("length_mtr"))
		if area:
			row.conversion_factor = area
			row.transfer_qty = flt(row.qty) * area
