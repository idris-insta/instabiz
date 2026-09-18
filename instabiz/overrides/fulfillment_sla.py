"""instabiz.overrides.fulfillment_sla

Daily scheduler: alert sales rep when a submitted SO has no linked submitted
Delivery Note after SLA_HOURS hours. Deduplicates via [ib-sla-alert] marker.
"""
import frappe
from frappe.utils import now_datetime, add_to_date

from instabiz.overrides.ib_status import stored_statuses

SLA_HOURS = 48
_MARKER   = "[ib-sla-alert]"


def _sla_hours():
	from instabiz.overrides.ib_settings import get_int
	return get_int("fulfillment_sla_hours", SLA_HOURS)


def run_fulfillment_sla():
	cutoff = add_to_date(now_datetime(), hours=-_sla_hours())

	# SOs submitted before the cutoff with no submitted DN
	overdue = frappe.db.sql(
		"""
		SELECT so.name, so.customer, so.transaction_date,
		       so.custom_sales_person_user, so.grand_total
		FROM `tabSales Order` so
		WHERE so.docstatus = 1
		  AND so.status NOT IN %(closed)s
		  AND so.creation <= %(cutoff)s
		  AND NOT EXISTS (
		        SELECT 1
		        FROM `tabDelivery Note Item` dni
		        INNER JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		        WHERE dni.against_sales_order = so.name
		          AND dn.docstatus = 1
		  )
		""",
		{"cutoff": cutoff, "closed": stored_statuses("Sales Order", "Closed", "Cancelled")},
		as_dict=True,
	)

	created = 0
	for so in overdue:
		if not so.custom_sales_person_user:
			continue

		# skip if an open SLA alert already exists for this SO
		if frappe.db.exists("Notification Log", {
			"document_type": "Sales Order",
			"document_name": so.name,
			"subject": ["like", f"%{_MARKER}%"],
		}):
			continue

		subject = (
			f"{_MARKER} SLA breach: {so.name} ({so.customer}) — "
			f"no delivery note after {_sla_hours()}h"
		)
		frappe.get_doc({
			"doctype":       "Notification Log",
			"subject":       subject,
			"for_user":      so.custom_sales_person_user,
			"from_user":     "Administrator",
			"type":          "Alert",
			"document_type": "Sales Order",
			"document_name": so.name,
		}).insert(ignore_permissions=True)

		created += 1

	if created:
		frappe.db.commit()
	frappe.logger().info(f"[fulfillment_sla] {created} SLA alerts sent")
