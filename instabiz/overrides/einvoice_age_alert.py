"""instabiz.overrides.einvoice_age_alert

Daily scheduler: warn Accounts when a submitted Sales Invoice still has no IRN
as its 30-day e-invoice reporting window closes. From 1 Apr 2026, businesses
with AATO >= Rs 10 Cr cannot get an IRN for an invoice more than 30 days old,
and the invoice is not legally valid without one.

Alerts from day 20 onwards (and daily-deduplicated per invoice via an indexed
document_name lookup). No-op when e-invoicing is not enabled in GST Settings.
"""
import frappe
from frappe.utils import add_days, date_diff, getdate, today

WARN_FROM_DAYS = 20
IRN_WINDOW_DAYS = 30
_MARKER = "[ib-irn-age]"
_OPEN_STATES = ("Pending", "Failed", "Auto-Retry", "")


def _warn_days():
	from instabiz.overrides.ib_settings import get_int
	return get_int("irn_warn_from_day", WARN_FROM_DAYS)


def run_einvoice_age_alert():
	if not frappe.db.get_single_value("GST Settings", "enable_e_invoice"):
		return
	if not frappe.db.has_column("Sales Invoice", "einvoice_status"):
		return

	today_date = getdate(today())
	invoices = frappe.db.sql(
		"""
		SELECT name, customer_name, posting_date, grand_total, einvoice_status
		FROM `tabSales Invoice`
		WHERE docstatus = 1
		  AND IFNULL(irn, '') = ''
		  AND IFNULL(einvoice_status, '') IN %(open)s
		  AND IFNULL(billing_address_gstin, '') != ''
		  AND posting_date <= %(warn_before)s
		  AND posting_date >= %(oldest)s
		ORDER BY posting_date
		""",
		{
			"open": _OPEN_STATES,
			"warn_before": add_days(today_date, -_warn_days()),
			# keep alerting a few days past the window so an expired one isn't silent
			"oldest": add_days(today_date, -(IRN_WINDOW_DAYS + 5)),
		},
		as_dict=True,
	)
	if not invoices:
		return

	users = frappe.db.sql(
		"""
		SELECT DISTINCT ur.parent FROM `tabHas Role` ur
		INNER JOIN `tabUser` u ON u.name = ur.parent
		WHERE ur.role IN ('Accounts Manager', 'Accounts User') AND u.enabled = 1
		  AND ur.parent != 'Administrator'
		""",
		pluck="parent",
	)
	for inv in invoices:
		age = date_diff(today_date, getdate(inv.posting_date))
		left = IRN_WINDOW_DAYS - age
		when = f"{left}d left" if left > 0 else "30-day window passed"
		marker = f"{_MARKER}-{inv.name}-{today_date}"
		subject = f"No IRN on {inv.name} ({inv.customer_name}) — {when} {marker}"[:140]
		for user in users:
			if frappe.db.exists("Notification Log", {
				"for_user": user, "document_name": inv.name, "subject": ["like", f"%{marker}%"],
			}):
				continue
			frappe.get_doc({
				"doctype": "Notification Log",
				"for_user": user,
				"from_user": "Administrator",
				"type": "Alert",
				"document_type": "Sales Invoice",
				"document_name": inv.name,
				"subject": subject,
				"email_content": (
					f"Sales Invoice {inv.name} dated {inv.posting_date} has no e-invoice IRN "
					f"(status: {inv.einvoice_status or 'not generated'}). {when}. Generate it from the "
					"invoice before the window closes; after 30 days the IRP rejects it."
				),
			}).insert(ignore_permissions=True)
	frappe.db.commit()
