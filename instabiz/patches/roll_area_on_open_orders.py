"""Open Sales Orders entered in rolls of an SQMT item counted each roll as 1 m².
Set the conversion factor to the roll's real m² (width mm / 1000 × length m) on
lines not yet fully delivered, then recompute reserved qty for those bins.
Delivered / billed documents are left as they are."""
import frappe
from frappe.utils import flt

from instabiz.overrides.utils import ROLL_UOMS


def execute():
	rows = frappe.db.sql("""SELECT c.name, c.item_code, c.warehouse, c.qty, c.width_mm, c.length_mtr, c.conversion_factor
		FROM `tabSales Order Item` c JOIN `tabSales Order` p ON p.name = c.parent
		JOIN `tabItem` i ON i.name = c.item_code
		WHERE p.docstatus = 1 AND IFNULL(p.per_delivered, 0) < 100 AND p.status NOT IN ('Closed', 'Cancelled')
			AND i.stock_uom = 'SQMT' AND UPPER(c.uom) IN %s AND c.width_mm > 0 AND c.length_mtr > 0
			AND IFNULL(c.delivered_qty, 0) < c.qty""", (tuple(ROLL_UOMS),), as_dict=True)
	touched = set()
	for r in rows:
		area = flt(r.width_mm) / 1000 * flt(r.length_mtr)
		if abs(flt(r.conversion_factor) - area) < 1e-9:
			continue
		frappe.db.set_value("Sales Order Item", r.name, {"conversion_factor": area, "stock_qty": flt(r.qty) * area},
			update_modified=False)
		if r.warehouse:
			touched.add((r.item_code, r.warehouse))
	from erpnext.stock.stock_balance import get_reserved_qty, update_bin_qty

	for item_code, warehouse in touched:
		update_bin_qty(item_code, warehouse, {"reserved_qty": get_reserved_qty(item_code, warehouse)})
	print(f"roll area: {len(rows)} open lines checked, {len(touched)} bins recomputed")
