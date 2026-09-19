"""instabiz.overrides.branch_transfer

Stock moving between branches in two steps, so what is on the truck is visible:

  dispatch  — Material Transfer from the sending warehouse into the transit
              warehouse (ERPNext "Add to Transit"), destination kept on the entry
              (custom_final_warehouse). Vehicle / LR / e-way bill live on the same
              Stock Entry (india_compliance fields).
  receive   — ERPNext's own "End Transit" entry from transit into the destination;
              received qty can be less than sent (the rest stays in transit).

IB Goods In Transit lists what has left and not arrived yet.
"""
import frappe
from frappe import _
from frappe.utils import flt, today

TRANSIT = "Goods In Transit - IB"


def transit_warehouse(company=None):
	name = frappe.db.get_value("Warehouse", {"warehouse_type": "Transit", "is_group": 0,
		"company": company or frappe.defaults.get_user_default("Company")}, "name")
	return name or TRANSIT


def _leaf(warehouse):
	if not warehouse or not frappe.db.exists("Warehouse", warehouse):
		frappe.throw(_("Warehouse {0} not found.").format(warehouse))
	if frappe.db.get_value("Warehouse", warehouse, "is_group"):
		frappe.throw(_("{0} is a group — pick the floor / warehouse inside it.").format(warehouse))


@frappe.whitelist()
def create_dispatch(from_warehouse, to_warehouse, items, vehicle_no=None, lr_no=None, remarks=None):
	"""Draft Stock Entry: sending warehouse → transit, destination remembered. Returns its name."""
	if not frappe.has_permission("Stock Entry", "create"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	_leaf(from_warehouse)
	_leaf(to_warehouse)
	if from_warehouse == to_warehouse:
		frappe.throw(_("From and To are the same warehouse."))
	items = [r for r in frappe.parse_json(items) if r.get("item_code") and flt(r.get("qty")) > 0]
	if not items:
		frappe.throw(_("Add at least one item with a quantity."))
	company = frappe.db.get_value("Warehouse", from_warehouse, "company")
	se = frappe.new_doc("Stock Entry")
	se.stock_entry_type = "Material Transfer"
	se.purpose = "Material Transfer"
	se.company = company
	se.posting_date = today()
	se.add_to_transit = 1
	se.from_warehouse = from_warehouse
	se.to_warehouse = transit_warehouse(company)
	se.custom_final_warehouse = to_warehouse
	se.vehicle_no = vehicle_no
	se.lr_no = lr_no
	se.remarks = remarks or _("Branch transfer {0} → {1}").format(from_warehouse, to_warehouse)
	for r in items:
		se.append("items", {"item_code": r["item_code"], "qty": flt(r["qty"]), "s_warehouse": from_warehouse,
			"t_warehouse": se.to_warehouse})
	se.insert()
	return se.name


@frappe.whitelist()
def receive(stock_entry):
	"""Draft receipt (transit → destination) for a dispatched branch transfer."""
	from erpnext.stock.doctype.stock_entry.stock_entry import make_stock_in_entry

	src = frappe.get_doc("Stock Entry", stock_entry)
	src.check_permission("read")
	if not src.add_to_transit or src.docstatus != 1:
		frappe.throw(_("{0} is not a submitted transit dispatch.").format(stock_entry))
	if flt(src.per_transferred) >= 100:
		frappe.throw(_("Already fully received."))
	dest = src.get("custom_final_warehouse")
	se = make_stock_in_entry(stock_entry)
	for row in se.items:
		if dest and not row.t_warehouse:
			row.t_warehouse = dest
	if dest:
		se.to_warehouse = dest
	se.insert()
	return se.name


def after_migrate():
	if not frappe.db.exists("Custom Field", {"dt": "Stock Entry", "fieldname": "custom_final_warehouse"}):
		frappe.get_doc({"doctype": "Custom Field", "dt": "Stock Entry", "fieldname": "custom_final_warehouse",
			"label": "Final Destination", "fieldtype": "Link", "options": "Warehouse", "insert_after": "to_warehouse",
			"depends_on": "eval:doc.add_to_transit || doc.custom_final_warehouse", "allow_on_submit": 1,
			"description": "Branch transfer: where the goods go when they arrive (Receive)."}).insert(ignore_permissions=True)
