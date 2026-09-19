"""instabiz.overrides.wastage_watch

Wastage norms. Every completed stage of a run records input, output and
wastage % (IB WO Stage Event). The norm is the machine's Wastage Norm %, else
IB Stock Settings "Default wastage norm %" (3). A stage above its norm:
  - bell to Factory Management (once per stage event), with operator and machine
    (no timeline comment: IB Work Order's "route" table collides with Frappe's
    comment cache-clear, which reads "route" as a web URL)
IB Wastage Analysis shows the trend by stage / machine / operator / item group.
"""
import frappe
from frappe import _
from frappe.utils import flt

from instabiz.overrides import ib_settings

MARK = "[ib-wastage-{0}]"


def norm_for(machine):
	return flt(machine and frappe.get_cached_value("IB Machine", machine, "wastage_norm_pct")) \
		or ib_settings.get_float("wastage_norm_default_pct", 3)


def check_run(doc, method=None):
	for ev in doc.get("stage_log") or []:
		if ev.skipped or not ev.completed_at or not flt(ev.input_qty):
			continue
		norm = norm_for(ev.machine)
		if flt(ev.wastage_pct) <= norm:
			continue
		marker = MARK.format(ev.name)
		if frappe.db.exists("Notification Log", {"document_name": doc.name, "subject": ["like", f"%{marker}%"]}):
			continue
		_alert(doc, ev, norm, marker)


def _alert(doc, ev, norm, marker):
	text = _("{0} at {1} wasted {2}% (norm {3}%) — {4} of {5} on {6}, {7}").format(
		doc.name, ev.stage, flt(ev.wastage_pct), norm, round(flt(ev.wastage_qty), 2), round(flt(ev.input_qty), 2),
		ev.machine or _("no machine"), (ev.operator or "-").split("@")[0])
	users = set(frappe.get_all("Has Role", filters={"role": "Factory Management", "parenttype": "User"}, pluck="parent"))
	users = {u for u in users if u != "Administrator" and frappe.db.get_value("User", u, "enabled")}
	for u in users:
		frappe.get_doc({"doctype": "Notification Log", "for_user": u, "type": "Alert",
			"subject": text[:138 - len(marker)] + " " + marker, "document_type": "IB Work Order",
			"document_name": doc.name}).insert(ignore_permissions=True)
	if not users:
		# keep the dedup marker even when nobody holds the role
		frappe.get_doc({"doctype": "Notification Log", "for_user": "Administrator", "type": "Alert",
			"subject": text[:138 - len(marker)] + " " + marker, "document_type": "IB Work Order",
			"document_name": doc.name}).insert(ignore_permissions=True)
