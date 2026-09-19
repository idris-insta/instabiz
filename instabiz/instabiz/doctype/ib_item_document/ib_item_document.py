"""IB Item Document — TDS / SDS / COA / test report per item, versioned.

Only one version per item and document type is Current; saving a new current
one retires the old. attach_to() copies the current documents of every item on
a Quotation / Sales Order / Delivery Note onto that document, so they go out
with the email and print.
"""
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today


class IBItemDocument(Document):
	def validate(self):
		self.title = f"{self.item_code} — {(self.document_type or '').split(' - ')[0]} v{self.version or 1}"
		if self.valid_till and getdate(self.valid_till) < getdate(self.valid_from or today()):
			frappe.throw(_("Valid Till is before Valid From."))

	def on_update(self):
		if self.is_current:
			for other in frappe.get_all("IB Item Document", filters={"item_code": self.item_code,
					"document_type": self.document_type, "is_current": 1, "name": ["!=", self.name]}, pluck="name"):
				frappe.db.set_value("IB Item Document", other, "is_current", 0)


def current_documents(item_codes, customer_facing=False):
	filters = {"item_code": ["in", list(item_codes)], "is_current": 1}
	if customer_facing:
		filters["share_with_customers"] = 1
	docs = frappe.get_all("IB Item Document", filters=filters,
		fields=["name", "item_code", "document_type", "version", "file", "valid_till"])
	return [d for d in docs if not d.valid_till or getdate(d.valid_till) >= getdate(today())]


@frappe.whitelist()
def attach_to(doctype, name):
	"""Attach the current item documents of every item on this document (skips ones already attached)."""
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("write" if doc.docstatus == 0 else "read")
	docs = current_documents({r.item_code for r in doc.items if r.item_code})
	have = set(frappe.get_all("File", filters={"attached_to_doctype": doctype, "attached_to_name": name}, pluck="file_url"))
	added = 0
	for d in docs:
		if d.file in have:
			continue
		frappe.get_doc({"doctype": "File", "file_url": d.file, "attached_to_doctype": doctype, "attached_to_name": name,
			"file_name": f"{d.item_code} {d.document_type.split(' - ')[0]} v{d.version or 1}"}).insert(ignore_permissions=True)
		added += 1
	return {"added": added, "available": len(docs)}
