"""instabiz.overrides.dimensions

Accounting dimensions Branch and Department (ERPNext Accounting Dimension), so
every ledger line — and P&L, Balance Sheet, General Ledger, Trial Balance —
can be filtered by them. Branch is filled by itself from the document's
location / warehouse (Bhiwandi, Sarigram, Chennai); Department is picked on the
document where it matters (expenses, journals, payments).
"""
import frappe

BRANCH_OF = {"maharashtra": "Bhiwandi", "gujarat": "Sarigram", "chennai": "Chennai"}
DIMENSIONS = ("Branch", "Department")


def after_migrate():
	for b in BRANCH_OF.values():
		if not frappe.db.exists("Branch", b):
			frappe.get_doc({"doctype": "Branch", "branch": b}).insert(ignore_permissions=True)
	from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import make_dimension_in_accounting_doctypes

	for dt in DIMENSIONS:
		name = frappe.db.get_value("Accounting Dimension", {"document_type": dt})
		if not name:
			frappe.flags.in_test, was = True, frappe.flags.in_test  # ERPNext adds the fields inline instead of queueing
			try:
				frappe.get_doc({"doctype": "Accounting Dimension", "document_type": dt}).insert(ignore_permissions=True)
			finally:
				frappe.flags.in_test = was
			continue
		# fields missing on any dimension doctype (first run queued, or a new custom doctype added) → add now
		fieldname = frappe.db.get_value("Accounting Dimension", name, "fieldname")
		if not frappe.get_meta("GL Entry").has_field(fieldname) or not frappe.get_meta("IB Expense").has_field(fieldname):
			make_dimension_in_accounting_doctypes(doc=frappe.get_doc("Accounting Dimension", name))


def _dimension_doctypes():
	if frappe.flags.ib_dim_doctypes is None:
		frappe.flags.ib_dim_doctypes = set(frappe.get_hooks("accounting_dimension_doctypes")) | {
			"Sales Order", "Delivery Note", "Purchase Order", "Purchase Receipt", "Stock Entry", "Material Request"}
	return frappe.flags.ib_dim_doctypes


def _location(doc):
	loc = (doc.get("custom_location") or doc.get("location") or "").strip().lower()
	if loc in BRANCH_OF:
		return loc
	whs = [doc.get("set_warehouse"), doc.get("from_warehouse"), doc.get("to_warehouse"), doc.get("warehouse")]
	for row in doc.get("items") or []:
		whs += [row.get("warehouse"), row.get("s_warehouse"), row.get("t_warehouse")]
	for wh in filter(None, whs):
		up = wh.upper()
		for key in BRANCH_OF:
			if key.upper() in up:
				return key
		parent = frappe.get_cached_value("Warehouse", wh, "parent_warehouse") or ""
		for key in BRANCH_OF:
			if key.upper() in parent.upper():
				return key
	return None


def set_branch(doc, method=None):
	"""validate: fill Branch from the location when it's empty (header and lines)."""
	if doc.doctype not in _dimension_doctypes() or not doc.meta.has_field("branch"):
		return
	loc = _location(doc)
	branch = BRANCH_OF.get(loc) if loc else None
	if not branch or not frappe.db.exists("Branch", branch):
		return
	if not doc.get("branch"):
		doc.branch = branch
	for table in ("items", "accounts", "taxes"):
		for row in doc.get(table) or []:
			if hasattr(row, "meta") and row.meta.has_field("branch") and not row.get("branch"):
				row.branch = doc.branch
