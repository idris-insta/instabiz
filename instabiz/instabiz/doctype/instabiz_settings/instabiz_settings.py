import frappe
from frappe.model.document import Document


class InstabizSettings(Document):
	def validate(self):
		for field in ("dormant_notice_1_days", "dormant_notice_2_days", "dormant_reassign_days"):
			if self.get(field) is not None and self.get(field) < 0:
				frappe.throw(frappe._("{0} cannot be negative.").format(self.meta.get_label(field)))
		n1, n2, n3 = self.dormant_notice_1_days, self.dormant_notice_2_days, self.dormant_reassign_days
		if n1 and n2 and n3 and not (n1 < n2 < n3):
			frappe.throw(frappe._("Dormant notice days must increase: first notice < second notice < reassign."))
		if self.ot_hours_per_day is not None and self.ot_hours_per_day < 0:
			frappe.throw(frappe._("Working Hours per Day cannot be negative."))

	def on_update(self):
		before = self.get_doc_before_save()
		if before and any(
			before.get(f) != self.get(f) for f in ("ot_day_basis", "ot_hours_per_day")
		):
			from instabiz.overrides.overtime import refresh_assignment_rates

			frappe.enqueue(refresh_assignment_rates, queue="short", enqueue_after_commit=True)
