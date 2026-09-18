"""IB DPR Entry — one machine run on one day, computed the way the DPR sheet does.

Formulas follow "DPR Format NEW.xlsx" line for line:
  Coating WB / PVC  film/sqm = mic × 0.91 / 1000, adhesive/sqm = (mic × 1.11 / 0.5449) / 1000,
                    adhesive solid = adhesive used × 0.54, roll weight = film + adhesive solid
  Coating HM        film/sqm = mic × density / 1000 (Foil 2.71, Foam 0.135, Kraft 1.0,
                    HDPE 1.2, DS Poly 0.91), adhesive/sqm = mic × sides / 1000,
                    liner/sqm = mic / 1000, roll weight = film + adhesive + liner
  Slitting          sqm/ctn = W/1000 × L × qty/ctn, pcs/shaft = jumbo width / W, ...
  Rewinding         total mtr = logs × L, balance = jumbo mtr − total − wastage
  Cutting           pcs/log = log width / W, balance = total pcs − qty/ctn × ctns
  Packing           total pcs = ctns × pcs/ctn
  Silicon           total pcs = ctns × pcs/ctn, pcs/drum = drum kg × 1000 / pc g
"""
import frappe
from frappe.model.document import Document
from frappe.utils import flt

FILM_DENSITY = {
	"BOPP": 0.91, "PVC": 0.91, "DS Polyester": 0.91,
	"Aluminium Foil": 2.71, "Foam": 0.135, "Kraft Paper": 1.0, "HDPE": 1.2,
}

# fields each stage computes; everything else computed is cleared so a stage
# change never leaves stale numbers behind
COMPUTED = {
	"coating": ("film_per_sqm", "adh_per_sqm", "liner_per_sqm", "film_used", "adh_used", "liner_used",
		"adh_solid", "roll_weight", "film_total", "adh_total", "liner_total", "time_per_roll"),
	"Slitting": ("sqm_per_ctn", "total_sqm", "shafts_used_per_ctn", "shafts_req_per_ctn", "pcs_per_shaft",
		"total_pcs", "pcs_used", "balance_pcs", "time_per_shaft"),
	"Rewinding": ("total_mtrs", "sqm_per_roll", "total_sqm", "balance_mtrs", "time_per_log"),
	"Cutting": ("pcs_per_log", "total_pcs", "pcs_used", "balance_pcs", "time_per_log"),
	"Packing": ("total_pcs",),
	"Silicon": ("total_pcs", "pcs_per_drum", "ctns_per_drum"),
}
ALL_COMPUTED = {f for fields in COMPUTED.values() for f in fields}


def _div(a, b):
	return flt(a) / flt(b) if flt(b) else 0


class IBDPREntry(Document):
	def validate(self):
		if self.work_order and not self.sales_order:
			self.sales_order = frappe.db.get_value("IB Work Order", self.work_order, "sales_order")
		for fieldname in ALL_COMPUTED:
			self.set(fieldname, 0)
		stage = self.stage or ""
		if stage.startswith("Coating"):
			self._coating(stage)
		elif stage == "Slitting":
			self._slitting()
		elif stage == "Rewinding":
			self._rewinding()
		elif stage == "Cutting":
			self._cutting()
		elif stage == "Packing":
			self.total_pcs = flt(self.total_ctns) * flt(self.pcs_per_ctn)
		elif stage == "Silicon":
			self.total_pcs = flt(self.total_ctns) * flt(self.pcs_per_ctn or 24)
			self.pcs_per_drum = _div(flt(self.weight_per_drum) * 1000, self.weight_per_pc)
			self.ctns_per_drum = _div(self.pcs_per_drum, self.pcs_per_ctn or 24)

	def _coating(self, stage):
		sqm = flt(self.width_mm) / 1000 * flt(self.length_mtr)
		if stage == "Coating HM":
			density = FILM_DENSITY.get(self.coating_substrate or "", 1.0)
			self.film_per_sqm = flt(self.film_mic) * density / 1000
			self.adh_per_sqm = flt(self.adh_mic) * flt(self.adhesive_sides or 1) / 1000
			self.liner_per_sqm = flt(self.liner_mic) / 1000
			self.film_used = sqm * self.film_per_sqm
			self.adh_used = sqm * self.adh_per_sqm
			self.liner_used = sqm * self.liner_per_sqm
			self.roll_weight = self.film_used + self.adh_used + self.liner_used
		else:
			density = FILM_DENSITY.get(self.coating_substrate or "", 0.91)
			self.film_per_sqm = flt(self.film_mic) * density / 1000
			self.adh_per_sqm = (flt(self.adh_mic) * 1.11 / 0.5449) / 1000
			self.film_used = sqm * self.film_per_sqm
			self.adh_used = sqm * self.adh_per_sqm
			self.adh_solid = self.adh_used * 0.54
			self.roll_weight = self.film_used + self.adh_solid
		rolls = flt(self.no_of_rolls)
		self.film_total = rolls * self.film_used
		self.adh_total = rolls * self.adh_used
		self.liner_total = rolls * flt(self.liner_used)
		self.total_sqm = rolls * sqm
		self.time_per_roll = _div(self.time_taken, rolls)

	def _slitting(self):
		w, qty, ctns = flt(self.width_mm), flt(self.qty_per_ctn), flt(self.total_ctns)
		self.sqm_per_ctn = w / 1000 * flt(self.length_mtr) * qty
		self.total_sqm = self.sqm_per_ctn * ctns
		self.shafts_used_per_ctn = _div(self.shafts, ctns)
		self.shafts_req_per_ctn = _div(w * qty, self.jumbo_width_mm or 1300)
		self.pcs_per_shaft = _div(self.jumbo_width_mm, w)
		self.total_pcs = self.pcs_per_shaft * flt(self.shafts)
		self.pcs_used = qty * ctns
		self.balance_pcs = self.total_pcs - self.pcs_used
		self.time_per_shaft = _div(self.time_taken, self.shafts)

	def _rewinding(self):
		logs = flt(self.no_of_logs)
		self.total_mtrs = logs * flt(self.length_mtr)
		self.sqm_per_roll = flt(self.width_mm) / 1000 * flt(self.length_mtr)
		self.total_sqm = self.sqm_per_roll * logs
		self.balance_mtrs = flt(self.jumbo_mtr) - self.total_mtrs - flt(self.wastage_mtr)
		self.time_per_log = _div(self.time_taken, logs)

	def _cutting(self):
		logs = flt(self.no_of_logs)
		self.pcs_per_log = _div(self.log_width_mm, self.width_mm)
		self.total_pcs = self.pcs_per_log * logs
		self.pcs_used = flt(self.qty_per_ctn) * flt(self.total_ctns)
		self.balance_pcs = self.total_pcs - self.pcs_used
		self.time_per_log = _div(self.time_taken, logs)
