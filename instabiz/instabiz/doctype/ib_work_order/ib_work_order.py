import frappe
from frappe.model.document import Document
from frappe.utils import flt

# stage -> machine type, mirrors instabiz.overrides.production._STAGE_MACHINE_TYPE
_STAGE_MACHINE_TYPE = {
	"Coating": "Coating",
	"Slitting": "Slitting",
	"Rewinding": "Rewinding",
	"Silicon": "Silicon",
	"Cutting": "Cutting",
	"Packing": "Packing",
}


class IBWorkOrder(Document):
	"""One IB Work Order = one production run (cradle to grave).

	The run lifecycle (create / advance / skip / hold / resume / finish / cancel)
	lives in instabiz.overrides.production_run. This controller only keeps the
	derived roll-up fields consistent on every save.
	"""

	def validate(self):
		self._number_route()
		self._roll_up_stage_events()
		self._roll_up_totals()

	def _number_route(self):
		for i, row in enumerate(self.route or [], start=1):
			if not row.sequence:
				row.sequence = i
			if not row.machine_type:
				row.machine_type = _STAGE_MACHINE_TYPE.get(row.stage, "")

	def _roll_up_stage_events(self):
		for ev in self.stage_log or []:
			ev.wastage_qty = max(flt(ev.input_qty) - flt(ev.output_qty), 0.0)
			ev.wastage_pct = (
				round(ev.wastage_qty / flt(ev.input_qty) * 100, 2) if flt(ev.input_qty) else 0.0
			)

	def _roll_up_totals(self):
		self.total_output_qty = sum(flt(o.produced_qty) for o in (self.outputs or []))
		self.total_wastage_qty = sum(flt(ev.wastage_qty) for ev in (self.stage_log or []))
