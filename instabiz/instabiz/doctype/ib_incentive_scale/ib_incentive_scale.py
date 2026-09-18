import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class IBIncentiveScale(Document):
	def validate(self):
		slabs = sorted(self.slabs, key=lambda s: flt(s.from_amount))
		for a, b in zip(slabs, slabs[1:]):
			if not flt(a.to_amount):
				frappe.throw(_("Only the last slab can be open-ended (To = 0)."))
			if flt(b.from_amount) < flt(a.to_amount):
				frappe.throw(_("Slabs overlap: {0} starts before {1} ends.").format(b.slab_label or b.idx, a.slab_label or a.idx))
