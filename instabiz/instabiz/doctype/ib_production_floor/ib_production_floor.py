import frappe
from frappe import _
from frappe.model.document import Document

_ROOT_WAREHOUSE_LOCATION = {
	"MAHARASHTRA - IB": "maharashtra",
	"GUJARAT - IB": "gujarat",
	"CHENNAI - IB": "chennai",
}

STAGE_CHECK_FIELDS = {
	"Coating": "allow_coating",
	"Slitting": "allow_slitting",
	"Rewinding": "allow_rewinding",
	"Cutting": "allow_cutting",
	"Silicon": "allow_packing",
	"Packing": "allow_packing",
}


def _resolve_root_location(warehouse):
	seen = set()
	current = warehouse
	while current and current not in seen:
		seen.add(current)
		parent = frappe.db.get_value("Warehouse", current, "parent_warehouse")
		if not parent:
			return _ROOT_WAREHOUSE_LOCATION.get(current)
		current = parent
	return None


class IBProductionFloor(Document):
	def validate(self):
		if frappe.db.get_value("Warehouse", self.warehouse, "is_group"):
			frappe.throw(_("{0} is a group warehouse — pick a leaf warehouse (an actual floor), not a location grouping.").format(self.warehouse))

		location = _resolve_root_location(self.warehouse)
		if not location:
			frappe.throw(_("{0} does not sit under MAHARASHTRA - IB / GUJARAT - IB / CHENNAI - IB — cannot resolve which location this floor belongs to.").format(self.warehouse))
		self.location = location


def get_allowed_stages(floor_name):
	"""Return the set of production stage names this floor is equipped for."""
	if not floor_name:
		return set()
	row = frappe.db.get_value(
		"IB Production Floor", floor_name,
		["is_active"] + list(STAGE_CHECK_FIELDS.values()),
		as_dict=True,
	)
	if not row or not row.is_active:
		return set()
	return {stage for stage, fieldname in STAGE_CHECK_FIELDS.items() if row.get(fieldname)}
