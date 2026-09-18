import frappe
from frappe.model.document import Document


class IBMessageTemplate(Document):
	def validate(self):
		from frappe.utils.jinja import validate_template

		validate_template(self.message or "")
		if self.subject:
			validate_template(self.subject)

	def on_update(self):
		# one default per document type + channel
		if self.is_default:
			frappe.db.sql(
				"""UPDATE `tabIB Message Template` SET is_default = 0
				WHERE reference_doctype = %s AND channel = %s AND name != %s""",
				(self.reference_doctype, self.channel, self.name),
			)
