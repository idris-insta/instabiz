"""instabiz.overrides.winback

Daily scheduler: two win-back nudges for sales reps.

1. Stale quotations — Open/Replied quotation with no update in QUOTE_STALE_DAYS.
2. Cold leads — Lead in a non-progressing status with no activity in LEAD_STALE_DAYS.

Re-alerts every WINBACK_COOLDOWN_DAYS so reps keep getting nudged on chronically stale docs.
"""
import frappe
from frappe.utils import add_days, nowdate, escape_html

QUOTE_STALE_DAYS    = 14
LEAD_STALE_DAYS     = 30
WINBACK_COOLDOWN_DAYS = 14
_MARKER             = "[ib-winback]"
_LEAD_STALE_STATUSES = ("Cold Lead", "Contacted", "Warm Lead")


def _quote_days():
	from instabiz.overrides.ib_settings import get_int
	return get_int("quote_stale_days", QUOTE_STALE_DAYS)


def _lead_days():
	from instabiz.overrides.ib_settings import get_int
	return get_int("lead_stale_days", LEAD_STALE_DAYS)


def _cooldown_days():
	from instabiz.overrides.ib_settings import get_int
	return get_int("winback_cooldown_days", WINBACK_COOLDOWN_DAYS)


def run_winback():
	_stale_quotations()
	_cold_leads()
	frappe.db.commit()


# ── Stale quotations ──────────────────────────────────────────────────────────

def _stale_quotations():
	cutoff = add_days(nowdate(), -_quote_days())

	quotes = frappe.get_all(
		"Quotation",
		filters={
			# CustomQuotation.STATUS_MAP persists Open/Replied as "Pending"
			# (same fix as quotation_expiry.py); raw values kept for legacy rows.
			"status":   ["in", ["Pending", "Open", "Replied"]],
			"docstatus": 1,
			"modified": ["<", cutoff],
		},
		fields=["name", "customer_name", "grand_total",
		        "custom_sales_person_user", "valid_till", "modified"],
	)

	created = 0
	for q in quotes:
		if not q.custom_sales_person_user:
			continue
		if _already_notified("Quotation", q.name):
			continue

		subject = (
			f"{_MARKER} Stale quotation: {q.name} ({escape_html(q.customer_name or '')}) — "
			f"no activity in {_quote_days()}+ days"
		)
		frappe.get_doc({
			"doctype":       "Notification Log",
			"subject":       subject,
			"for_user":      q.custom_sales_person_user,
			"from_user":     "Administrator",
			"type":          "Alert",
			"document_type": "Quotation",
			"document_name": q.name,
		}).insert(ignore_permissions=True)
		created += 1

	frappe.logger().info(f"[winback] stale quotation alerts: {created}")


# ── Cold / stalled leads ──────────────────────────────────────────────────────

def _cold_leads():
	cutoff = add_days(nowdate(), -_lead_days())

	leads = frappe.get_all(
		"Lead",
		filters={
			"custom_status": ["in", list(_LEAD_STALE_STATUSES)],
			"status":        ["not in", ["Converted", "Do Not Contact"]],
			"modified":      ["<", cutoff],
		},
		fields=["name", "lead_name", "lead_owner",
		        "custom_status", "modified"],
	)

	created = 0
	for lead in leads:
		if not lead.lead_owner:
			continue
		if _already_notified("Lead", lead.name):
			continue

		subject = (
			f"{_MARKER} Cold lead: {escape_html(lead.lead_name or lead.name)} — "
			f"no activity in {_lead_days()}+ days (status: {lead.custom_status})"
		)
		frappe.get_doc({
			"doctype":       "Notification Log",
			"subject":       subject,
			"for_user":      lead.lead_owner,
			"from_user":     "Administrator",
			"type":          "Alert",
			"document_type": "Lead",
			"document_name": lead.name,
		}).insert(ignore_permissions=True)
		created += 1

	frappe.logger().info(f"[winback] cold lead alerts: {created}")


def _already_notified(doctype, docname):
	cutoff = add_days(nowdate(), -_cooldown_days())
	return frappe.db.exists("Notification Log", {
		"document_type": doctype,
		"document_name": docname,
		"subject":       ["like", f"%{_MARKER}%"],
		"creation":      [">=", cutoff],
	})
