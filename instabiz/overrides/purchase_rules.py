"""instabiz.overrides.purchase_rules

Locked Purchase rules (Idris 2026-09-20), implemented 2026-09-21:

1. Domestic path: PO -> PR -> PI (do not skip PO).
   Import PIs set custom_is_import=1 (no PO; stock already via Container Import).
2. Every inward truck: Inward IB Gate Pass on Purchase Receipt submit (auto).
3. Supplier item price lists: Standard Buying + per-supplier Buying - <name>.
4. Short receipt / claim: Material Issue (stock) + draft IB Debit Note (value).
"""
from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, cint, nowdate


def _is_stock_row(row) -> bool:
	if cint(row.get("is_non_stock_item")):
		return False
	item = row.get("item_code")
	if not item:
		return False
	return cint(frappe.db.get_value("Item", item, "is_stock_item") or 0) == 1


def assert_domestic_pr_has_po(doc):
	"""Purchase Receipt lines must reference a Purchase Order (domestic).

	Imports arrive without a PO (stock comes in via IB Container Import), and
	service / non-stock lines (freight, clearing) never have one — both are
	exempt, matching assert_domestic_pi_has_po_pr.
	"""
	if cint(doc.get("is_return")):
		return
	if cint(doc.get("custom_is_import")):
		return
	missing = []
	for row in doc.get("items") or []:
		if not row.get("item_code") or not _is_stock_row(row):
			continue
		if not row.get("purchase_order"):
			missing.append(row.idx)
	if missing:
		frappe.throw(
			_(
				"Domestic Purchase Receipt must come from a Purchase Order. "
				"Missing PO on row(s): {0}. Create / get items from PO first "
				"(locked path: PO → PR → PI)."
			).format(", ".join(str(i) for i in missing))
		)


def assert_domestic_pi_has_po_pr(doc):
	"""Purchase Invoice stock lines must reference PO + PR unless marked Import."""
	if cint(doc.get("is_return")):
		return
	if cint(doc.get("custom_is_import")):
		return
	# update_stock without PR is also blocked for domestic stock items
	bad_po, bad_pr = [], []
	for row in doc.get("items") or []:
		if not row.get("item_code") or not _is_stock_row(row):
			continue
		if not row.get("purchase_order"):
			bad_po.append(row.idx)
		if not row.get("purchase_receipt"):
			bad_pr.append(row.idx)
	if bad_po or bad_pr:
		parts = []
		if bad_po:
			parts.append(_("missing PO on row(s) {0}").format(", ".join(str(i) for i in bad_po)))
		if bad_pr:
			parts.append(_("missing Purchase Receipt on row(s) {0}").format(", ".join(str(i) for i in bad_pr)))
		frappe.throw(
			_(
				"Domestic Purchase Invoice must follow PO → PR → PI ({0}). "
				"For import billing (stock already via Container Import), tick "
				"<b>Is Import Bill</b> on this invoice."
			).format("; ".join(parts))
		)


def auto_inward_gate_pass_for_pr(pr_name: str) -> str | None:
	"""Idempotent Inward Gate Pass for a submitted Purchase Receipt."""
	from instabiz.instabiz.doctype.ib_gate_pass.ib_gate_pass import make_from

	if not pr_name:
		return None
	existing = frappe.db.exists(
		"IB Gate Pass",
		{"reference_doctype": "Purchase Receipt", "reference_name": pr_name, "docstatus": ["<", 2]},
	)
	if existing:
		return existing
	data = make_from("Purchase Receipt", pr_name)
	gp = frappe.get_doc(data)
	if not gp.vehicle_no:
		gp.vehicle_no = "TBD"
	gp.gate_pass_type = "Inward"
	# System-generated on PR submit — see auto_create_for_delivery_note.
	gp.flags.ignore_permissions = True
	gp.insert(ignore_permissions=True)
	gp.submit()
	return gp.name


def ensure_standard_buying_price_list() -> str:
	name = "Standard Buying"
	if not frappe.db.exists("Price List", name):
		frappe.get_doc(
			{
				"doctype": "Price List",
				"price_list_name": name,
				"buying": 1,
				"selling": 0,
				"enabled": 1,
				"currency": frappe.db.get_default("currency") or "INR",
			}
		).insert(ignore_permissions=True)
	return name


@frappe.whitelist()
def ensure_supplier_buying_price_list(supplier: str) -> str:
	"""Create/link Buying - <Supplier> price list for item rates."""
	if not supplier or not frappe.db.exists("Supplier", supplier):
		frappe.throw(_("Supplier {0} not found").format(supplier))
	ensure_standard_buying_price_list()
	sup_name = frappe.db.get_value("Supplier", supplier, "supplier_name") or supplier
	# keep name short
	pl_name = f"Buying - {sup_name}"[:140]
	if not frappe.db.exists("Price List", pl_name):
		frappe.get_doc(
			{
				"doctype": "Price List",
				"price_list_name": pl_name,
				"buying": 1,
				"selling": 0,
				"enabled": 1,
				"currency": frappe.db.get_default("currency") or "INR",
			}
		).insert(ignore_permissions=True)
	# link on supplier if field exists
	if frappe.get_meta("Supplier").has_field("default_price_list"):
		cur = frappe.db.get_value("Supplier", supplier, "default_price_list")
		if not cur:
			frappe.db.set_value("Supplier", supplier, "default_price_list", pl_name)
	if frappe.get_meta("Supplier").has_field("custom_buying_price_list"):
		frappe.db.set_value("Supplier", supplier, "custom_buying_price_list", pl_name)
	return pl_name


@frappe.whitelist()
def make_short_claim(purchase_receipt: str, rows=None):
	"""Short / claim: Material Issue for claimed qty + draft IB Debit Note.

	rows: optional [{item_code, qty, rate, warehouse, purchase_invoice?}]
	If omitted, uses (PO qty - received qty) for each PR line that is short.
	"""
	pr = frappe.get_doc("Purchase Receipt", purchase_receipt)
	pr.check_permission("write")
	if pr.docstatus != 1:
		frappe.throw(_("Submit the Purchase Receipt first."))

	claim_rows = frappe.parse_json(rows) if rows else None
	if not claim_rows:
		claim_rows = []
		for row in pr.items:
			po_qty = flt(row.get("ordered_qty") or 0)
			# fallback: look up PO item qty
			if not po_qty and row.purchase_order and row.purchase_order_item:
				po_qty = flt(
					frappe.db.get_value("Purchase Order Item", row.purchase_order_item, "qty")
				)
			short = po_qty - flt(row.qty)
			if short > 0.0001:
				claim_rows.append(
					{
						"item_code": row.item_code,
						"qty": short,
						"rate": flt(row.rate),
						"warehouse": row.warehouse,
						"uom": row.uom,
						"description": f"Short vs PO on {pr.name} row {row.idx}",
					}
				)
	if not claim_rows:
		frappe.throw(_("No shortage found on {0} (received ≥ ordered).").format(pr.name))

	company = pr.company
	# Material Issue for stock already received that is being claimed/rejected
	# (quality claim). For pure short-delivery (never arrived), skip issue — only DN.
	# Heuristic: if row warehouse qty path says "claim", user passes claim_type.
	se_name = None
	issue_rows = [r for r in claim_rows if cint(r.get("issue_stock"))]
	if issue_rows:
		se = frappe.new_doc("Stock Entry")
		se.stock_entry_type = "Material Issue"
		se.purpose = "Material Issue"
		se.company = company
		se.posting_date = nowdate()
		for r in issue_rows:
			se.append(
				"items",
				{
					"item_code": r["item_code"],
					"qty": flt(r["qty"]),
					"s_warehouse": r.get("warehouse") or pr.set_warehouse,
					"basic_rate": flt(r.get("rate") or 0),
				},
			)
		se.insert(ignore_permissions=True)
		se_name = se.name

	dn = None
	if frappe.db.exists("DocType", "IB Debit Note"):
		dn = frappe.new_doc("IB Debit Note")
		dn.company = company
		dn.supplier = pr.supplier
		dn.posting_date = nowdate()
		dn.reason_code = "Short Receipt"
		dn.remarks = f"Short/claim from Purchase Receipt {pr.name}"
		if dn.meta.has_field("against_purchase_receipt"):
			dn.against_purchase_receipt = pr.name
		for r in claim_rows:
			dn.append(
				"items",
				{
					"item_code": r["item_code"],
					"qty": flt(r["qty"]),
					"rate": flt(r.get("rate") or 0),
					"amount": flt(r["qty"]) * flt(r.get("rate") or 0),
					"description": r.get("description") or "",
				},
			)
		dn.insert(ignore_permissions=True)

	return {"material_issue": se_name, "debit_note": dn.name if dn else None, "rows": len(claim_rows)}


def ensure_purchase_lock_setup():
	"""Custom fields + Standard Buying price list."""
	ensure_standard_buying_price_list()
	fields = [
		{
			"dt": "Purchase Invoice",
			"fieldname": "custom_is_import",
			"label": "Is Import Bill",
			"fieldtype": "Check",
			"insert_after": "supplier",
			"description": "Tick when billing import stock already received via Container Import (no PO/PR required).",
		},
		{
			"dt": "Supplier",
			"fieldname": "custom_buying_price_list",
			"label": "Buying Price List",
			"fieldtype": "Link",
			"options": "Price List",
			"insert_after": "default_price_list",
		},
	]
	for f in fields:
		if frappe.db.exists("Custom Field", {"dt": f["dt"], "fieldname": f["fieldname"]}):
			continue
		try:
			if frappe.get_meta(f["dt"]).has_field(f["fieldname"]):
				continue
		except Exception:
			pass
		# insert_after may not exist on Supplier
		doc = frappe.get_doc({"doctype": "Custom Field", **f})
		try:
			doc.insert(ignore_permissions=True)
		except Exception:
			f.pop("insert_after", None)
			frappe.get_doc({"doctype": "Custom Field", **f}).insert(ignore_permissions=True)
	frappe.clear_cache()
	return {"standard_buying": "Standard Buying", "custom_is_import": True}


def smoke_check():
	ensure_purchase_lock_setup()
	return {
		"standard_buying": frappe.db.exists("Price List", "Standard Buying"),
		"custom_is_import": frappe.get_meta("Purchase Invoice").has_field("custom_is_import"),
	}