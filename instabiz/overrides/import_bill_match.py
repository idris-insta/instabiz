"""instabiz.overrides.import_bill_match — many-to-many PI <-> Container Import allocations."""
from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

ALLOC_DT = "IB Container Bill Allocation"


def ensure_allocation_doctype():
	if frappe.db.exists("DocType", ALLOC_DT):
		_ensure_ci_summary_fields()
		return ALLOC_DT
	doc = frappe.get_doc(
		{
			"doctype": "DocType",
			"name": ALLOC_DT,
			"module": "Instabiz",
			"custom": 1,
			"engine": "InnoDB",
			"naming_rule": "Random",
			"autoname": "hash",
			"is_submittable": 0,
			"permissions": [
				{"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
				{"role": "Accounts Manager", "read": 1, "write": 1, "create": 1, "delete": 1},
				{"role": "Accounts User", "read": 1, "write": 1, "create": 1},
			],
			"fields": [
				{"fieldname": "purchase_invoice", "label": "Purchase Invoice", "fieldtype": "Link", "options": "Purchase Invoice", "reqd": 1, "in_list_view": 1},
				{"fieldname": "container_import", "label": "Container Import", "fieldtype": "Link", "options": "IB Container Import", "reqd": 1, "in_list_view": 1},
				{"fieldname": "allocated_amount", "label": "Allocated Amount", "fieldtype": "Currency", "reqd": 1, "in_list_view": 1},
				{"fieldname": "allocated_qty", "label": "Allocated Qty", "fieldtype": "Float", "precision": "2"},
				{"fieldname": "remarks", "label": "Remarks", "fieldtype": "Small Text"},
			],
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.clear_cache()
	_ensure_ci_summary_fields()
	return ALLOC_DT


def _ensure_ci_summary_fields():
	for f in (
		{"dt": "IB Container Import", "fieldname": "custom_billed_amount", "label": "Billed Amount", "fieldtype": "Currency", "read_only": 1, "insert_after": "invoice_value_inr"},
		{"dt": "IB Container Import", "fieldname": "custom_pending_bill_amount", "label": "Pending Bill Amount", "fieldtype": "Currency", "read_only": 1, "insert_after": "custom_billed_amount"},
	):
		if frappe.db.exists("Custom Field", {"dt": f["dt"], "fieldname": f["fieldname"]}):
			continue
		try:
			frappe.get_doc({"doctype": "Custom Field", **f}).insert(ignore_permissions=True)
		except Exception:
			frappe.log_error("IB CI bill fields", frappe.get_traceback())


def _require_accounts_role():
	"""These endpoints write container billing figures — accounts staff only."""
	allowed = {"Accounts User", "Accounts Manager", "Purchase Manager", "System Manager"}
	if not (allowed & set(frappe.get_roles())):
		frappe.throw(
			_("Not permitted: container bill allocation is for accounts / purchase staff."),
			frappe.PermissionError,
		)


@frappe.whitelist()
def allocate_pi_to_container(purchase_invoice, container_import, allocated_amount, allocated_qty=None, remarks=None):
	_require_accounts_role()
	frappe.get_doc("Purchase Invoice", purchase_invoice).check_permission("write")
	ensure_allocation_doctype()
	amt = flt(allocated_amount)
	if amt <= 0:
		frappe.throw(_("Allocated amount must be greater than 0."))
	row = frappe.get_doc({
		"doctype": ALLOC_DT,
		"purchase_invoice": purchase_invoice,
		"container_import": container_import,
		"allocated_amount": amt,
		"allocated_qty": flt(allocated_qty),
		"remarks": remarks or "",
	}).insert(ignore_permissions=True)
	refresh_container_bill_totals(container_import)
	return row.name


@frappe.whitelist()
def refresh_container_bill_totals(container_import):
	_require_accounts_role()
	ensure_allocation_doctype()
	billed = flt(frappe.db.sql(
		"SELECT COALESCE(SUM(allocated_amount),0) FROM `tab%s` WHERE container_import=%%s" % ALLOC_DT,
		container_import,
	)[0][0])
	invoice_val = flt(
		frappe.db.get_value("IB Container Import", container_import, "invoice_value_inr")
		or frappe.db.get_value("IB Container Import", container_import, "invoice_value")
		or 0
	)
	pending = max(invoice_val - billed, 0)
	if frappe.get_meta("IB Container Import").has_field("custom_billed_amount"):
		frappe.db.set_value(
			"IB Container Import", container_import,
			{"custom_billed_amount": billed, "custom_pending_bill_amount": pending},
			update_modified=False,
		)
	return {"billed": billed, "pending": pending, "invoice_value": invoice_val}


def smoke_check():
	ensure_allocation_doctype()
	return {"allocation_dt": bool(frappe.db.exists("DocType", ALLOC_DT))}