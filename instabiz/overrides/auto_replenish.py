"""instabiz.overrides.auto_replenish

Weekly: draft one Purchase Material Request from IB Replenishment Suggestions
(every item whose projected stock is below its reorder point), and tell the
purchase team it is waiting for review. Nothing is ordered automatically; the
buyer edits and submits the draft. One draft per week at most.
"""
import frappe
from frappe.utils import add_days, nowdate

from instabiz.overrides.ib_settings import get, get_check

_MARKER = "[ib-auto-replenish]"


def run_weekly_material_request():
	if not get_check("auto_material_request", True):
		return
	if frappe.db.exists("Material Request", {
		"docstatus": 0, "terms": ["like", f"%{_MARKER}%"], "creation": [">=", add_days(nowdate(), -6)],
	}):
		return

	from instabiz.instabiz.report.ib_replenishment_suggestions.ib_replenishment_suggestions import _data

	rows = [r for r in _data(frappe._dict()) if r["suggested"] > 0]
	if not rows:
		return
	company = frappe.defaults.get_global_default("company")
	warehouse = (get("auto_mr_warehouse") or frappe.db.get_single_value("Stock Settings", "default_warehouse")
		or frappe.db.get_value("Warehouse", {"company": company, "is_group": 0, "disabled": 0}))
	schedule = add_days(nowdate(), 7)
	mr = frappe.get_doc({
		"doctype": "Material Request",
		"material_request_type": "Purchase",
		"company": company,
		"transaction_date": nowdate(),
		"schedule_date": schedule,
		"set_warehouse": warehouse,
		"terms": f"Drafted automatically from Replenishment Suggestions. Review quantities before submitting. {_MARKER}",
		"items": [{
			"item_code": r["item_code"], "qty": r["suggested"], "uom": r["uom"], "stock_uom": r["uom"],
			"conversion_factor": 1, "schedule_date": schedule, "warehouse": warehouse,
		} for r in rows],
	})
	mr.flags.ignore_permissions = True
	mr.insert()

	users = frappe.db.sql(
		"""SELECT DISTINCT hr.parent FROM `tabHas Role` hr INNER JOIN `tabUser` u ON u.name = hr.parent
		WHERE hr.role IN ('Purchase Manager', 'Purchase User') AND u.enabled = 1 AND hr.parent != 'Administrator'""",
		pluck="parent",
	)
	for user in users:
		frappe.get_doc({
			"doctype": "Notification Log", "for_user": user, "from_user": "Administrator", "type": "Alert",
			"document_type": "Material Request", "document_name": mr.name,
			"subject": f"Weekly reorder draft ready: {len(rows)} items ({mr.name})",
			"email_content": "Review the quantities and submit the Material Request, or delete it if nothing is needed.",
		}).insert(ignore_permissions=True)
	frappe.db.commit()
	return mr.name
