"""Require sales person on Sales Invoice so incentive net (Invoice - tax) is attributable.

The field (custom_sales_person_user) is hidden + read-only on the form, so a bare
throw is a dead end: the user is told to set a field they cannot reach. Resolve it
from the document's own lineage first (Sales Order -> Delivery Note -> Customer ->
owner) and only refuse when nothing in that chain names a rep.
"""
import frappe
from frappe import _
from frappe.utils import cint

FIELD = "custom_sales_person_user"


def _resolve_sales_person(doc):
	"""Walk the invoice's own lineage for a real rep. Returns None if none found."""
	for row in doc.get("items") or []:
		for dt, fieldname in (
			("Sales Order", row.get("sales_order")),
			("Delivery Note", row.get("delivery_note")),
		):
			if not fieldname:
				continue
			sp = frappe.db.get_value(dt, fieldname, FIELD)
			if sp and sp != "Administrator":
				return sp
	if doc.get("customer"):
		sp = frappe.db.get_value("Customer", doc.customer, FIELD)
		if sp and sp != "Administrator":
			return sp
	owner = doc.get("owner") or frappe.session.user
	if owner and owner != "Administrator":
		return owner
	return None


def assert_sales_person_for_incentive(doc, method=None):
	if cint(doc.get("is_return")):
		return
	sp = (doc.get(FIELD) or "").strip()
	if sp and sp != "Administrator":
		return

	resolved = _resolve_sales_person(doc)
	if resolved:
		doc.set(FIELD, resolved)
		name = frappe.db.get_value("User", resolved, "full_name") or resolved
		if doc.meta.has_field("custom_sales_person") and not doc.get("custom_sales_person"):
			doc.set("custom_sales_person", name)
		return

	# Never block a document that already exists — an old invoice with no rep on
	# it must stay editable (amend, credit note, GST correction). Warn instead.
	if not doc.get("__islocal"):
		frappe.msgprint(
			_(
				"No sales person on this invoice, so it will not carry incentive. "
				"Set the rep on the Customer or the source Sales Order."
			),
			indicator="orange",
			alert=True,
			title=_("No Incentive Attribution"),
		)
		return

	frappe.throw(
		_(
			"This invoice has no sales person and none could be taken from its "
			"Sales Order, Delivery Note or Customer. Incentive is Invoice - tax by "
			"role slab and needs a real rep: set <b>Sales Person</b> on the Customer "
			"({0}) first."
		).format(doc.get("customer") or "-"),
		title=_("Sales Person Required"),
	)
