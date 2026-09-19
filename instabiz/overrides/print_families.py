"""Print format families: every business document in three layouts, all on the
shared engine (templates/print/docs/*.html + ib_print_macros.html), all with
the letterhead. "<Title> - Classic / Modern / Compact" print formats only set
the layout and include the document template, so one template serves all three.

write_files() (developer step) writes the print_format folders;
apply_defaults() makes the chosen layout each document's default print format
(IB Print Settings → Default layout)."""
import json
import os

import frappe

LAYOUTS = ("Classic", "Modern", "Compact")

# (doctype, title, template)
FAMILIES = [
	("Quotation", "Quotation", "quotation"),
	("Sales Order", "Sales Order", "sales_order"),
	("Sales Order", "Proforma Invoice", "proforma"),
	("Delivery Note", "Delivery Challan", "delivery_challan"),
	("Sales Invoice", "Tax Invoice", "tax_invoice"),
	("Purchase Order", "Purchase Order", "purchase_order"),
	("Purchase Receipt", "Goods Receipt Note", "grn"),
	("Purchase Invoice", "Purchase Invoice", "purchase_invoice"),
	("Payment Entry", "Payment Voucher", "payment"),
	("Journal Entry", "Journal Voucher", "journal_voucher"),
	("IB Credit Note", "IB Credit Note", "party_note"),
	("IB Debit Note", "IB Debit Note", "party_note"),
	("IB Expense", "Expense Voucher", "expense_voucher"),
	("IB PDC", "PDC Receipt", "pdc_receipt"),
	("Customer", "Statement of Account", "statement"),
	("Stock Entry", "Stock Entry Note", "stock_entry"),
	("Material Request", "Material Request", "material_request"),
	("IB Gate Pass", "Gate Pass", "gate_pass"),
]
# the main family per doctype (its layout becomes the default print format)
DEFAULT_FAMILY = {dt: title for dt, title, _t in reversed(FAMILIES) if title != "Proforma Invoice"}


def format_name(title, layout):
	return f"{title} - {layout}"


def write_files():
	base = frappe.get_app_path("instabiz", "instabiz", "print_format")
	for doctype, title, template in FAMILIES:
		for layout in LAYOUTS:
			name = format_name(title, layout)
			folder = os.path.join(base, frappe.scrub(name))
			os.makedirs(folder, exist_ok=True)
			open(os.path.join(folder, "__init__.py"), "a").close()
			with open(os.path.join(folder, frappe.scrub(name) + ".html"), "w") as f:
				f.write(f'{{% set ib_layout = "{layout.lower()}" %}}\n'
					f'{{% include "templates/print/docs/{template}.html" %}}\n')
			doc = {
				"absolute_value": 0, "align_labels_right": 0, "creation": "2026-09-20 20:00:00", "custom_format": 1,
				"default_print_language": "en", "disabled": 0, "doc_type": doctype, "docstatus": 0,
				"doctype": "Print Format", "font": "Default", "font_size": 0, "idx": 0, "line_breaks": 0,
				"margin_bottom": 0.0, "margin_left": 0.0, "margin_right": 0.0, "margin_top": 0.0,
				"modified": "2026-09-20 20:00:00", "modified_by": "Administrator", "module": "Instabiz", "name": name,
				"owner": "Administrator", "print_designer": 0, "print_format_builder": 0, "print_format_builder_beta": 0,
				"print_format_for": "DocType", "print_format_type": "Jinja", "raw_printing": 0,
				"show_section_headings": 0, "standard": "Yes",
			}
			with open(os.path.join(folder, frappe.scrub(name) + ".json"), "w") as f:
				f.write(json.dumps(doc, indent=1) + "\n")


def apply_defaults(layout=None):
	"""Make '<Title> - <layout>' the default print format of each document."""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	from instabiz.overrides.ib_settings import get

	layout = (layout or get("print_default_layout", "") or "").title()
	if layout not in LAYOUTS:
		return 0
	done = 0
	for doctype, title in DEFAULT_FAMILY.items():
		name = format_name(title, layout)
		if frappe.db.exists("Print Format", name):
			make_property_setter(doctype, None, "default_print_format", name, "Data", for_doctype=True,
				validate_fields_for_doctype=False)
			done += 1
	frappe.clear_cache()
	return done


def after_migrate():
	"""Default Letter Head for every standard print (Employee, Leave Application,
	masters...). Instabiz formats draw their own letterhead and never render
	Frappe's, so this does not double up on them."""
	from instabiz.overrides.ib_settings import get

	if frappe.db.exists("Letter Head", {"is_default": 1, "disabled": 0}):
		return
	image = get("print_letterhead_image", "") or "/files/Instabiz_LH_v2.png"
	name = "Instabiz"
	if frappe.db.exists("Letter Head", name):
		lh = frappe.get_doc("Letter Head", name)
	else:
		lh = frappe.new_doc("Letter Head")
		lh.letter_head_name = name
	lh.update({"source": "HTML", "is_default": 1, "disabled": 0,
		"content": f'<div style="text-align:center"><img src="{image}" style="width:100%;height:auto;display:block"></div>'})
	lh.flags.ignore_permissions = True
	lh.save() if not lh.is_new() else lh.insert()
