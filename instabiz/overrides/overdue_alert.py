"""instabiz.overrides.overdue_alert

Overdue Sales Invoice reminders — 3 tiers:
  7d  → bell to custom_sales_person_user on the invoice
  15d → bell to all Sales Manager / System Manager
  30d → bell to managers + blocks new SO submit for that customer
         (block is enforced in sales_order.py before_submit)
"""
import frappe
from frappe.utils import today, getdate, date_diff, flt


_MARKER_7  = "[ib-overdue-7-{name}]"
_MARKER_15 = "[ib-overdue-15-{name}]"
_MARKER_30 = "[ib-overdue-30-{name}]"

# Field stored on Customer to block SO submit
_BLOCK_FIELD = "custom_overdue_block"


def run_overdue_alert():
	"""Daily scheduler entry point."""
	today_date = getdate(today())

	overdue = frappe.db.sql(
		"""
		SELECT
			si.name,
			si.customer,
			si.outstanding_amount,
			si.due_date,
			si.custom_sales_person_user,
			si.grand_total,
			si.currency
		FROM `tabSales Invoice` si
		WHERE si.docstatus = 1
		AND si.outstanding_amount > 0
		AND si.due_date < %(today)s
		ORDER BY si.due_date ASC
		""",
		{"today": today_date},
		as_dict=True,
	)

	if not overdue:
		return

	managers = _get_managers()

	for inv in overdue:
		age = date_diff(today_date, getdate(inv.due_date))
		outstanding = flt(inv.outstanding_amount)
		rep  = inv.custom_sales_person_user
		name = inv.name

		if age >= 30:
			_notify_30(inv, age, outstanding, managers, name)
		elif age >= 15:
			_notify_15(inv, age, outstanding, managers, name)
		elif age >= 7:
			_notify_7(inv, age, outstanding, rep, name)


def _notify_7(inv, age, outstanding, rep, name):
	if not rep:
		return
	marker = _MARKER_7.format(name=name)
	if frappe.db.exists("Notification Log", {"for_user": rep, "document_name": name, "subject": ["like", f"%{marker}%"]}):
		return
	base = f"Overdue {age}d: {name} {inv.customer} {inv.currency} {outstanding:,.0f} due {inv.due_date}"
	_send(rep, "Sales Invoice", name, f"{base[:140 - len(marker) - 1]} {marker}")


def _notify_15(inv, age, outstanding, managers, name):
	marker = _MARKER_15.format(name=name)
	users  = managers
	if inv.custom_sales_person_user:
		users = list({inv.custom_sales_person_user} | set(managers))
	base = f"OVERDUE {age}d: {name} {inv.customer} {inv.currency} {outstanding:,.0f} due {inv.due_date}"
	subject = f"{base[:140 - len(marker) - 1]} {marker}"
	for user in users:
		if frappe.db.exists("Notification Log", {"for_user": user, "document_name": name, "subject": ["like", f"%{marker}%"]}):
			continue
		_send(user, "Sales Invoice", name, subject)


def _notify_30(inv, age, outstanding, managers, name):
	marker = _MARKER_30.format(name=name)
	users  = managers
	if inv.custom_sales_person_user:
		users = list({inv.custom_sales_person_user} | set(managers))
	base = f"CRITICAL OVERDUE {age}d: {name} {inv.customer} {inv.currency} {outstanding:,.0f} ACCOUNT FLAGGED"
	subject = f"{base[:140 - len(marker) - 1]} {marker}"
	for user in users:
		if frappe.db.exists("Notification Log", {"for_user": user, "document_name": name, "subject": ["like", f"%{marker}%"]}):
			continue
		_send(user, "Sales Invoice", name, subject)

	# Set block flag on Customer so SO before_submit can enforce it
	if not frappe.db.get_value("Customer", inv.customer, _BLOCK_FIELD):
		frappe.db.set_value("Customer", inv.customer, _BLOCK_FIELD, 1, update_modified=False)


def _send(user, doctype, docname, subject):
	frappe.get_doc({
		"doctype":       "Notification Log",
		"for_user":      user,
		"from_user":     "Administrator",
		"type":          "Alert",
		"document_type": doctype,
		"document_name": docname,
		"subject":       subject,
		"email_content": "",
	}).insert(ignore_permissions=True)


def _get_managers():
	rows = frappe.db.sql(
		"""
		SELECT DISTINCT u.name
		FROM `tabUser` u
		INNER JOIN `tabHas Role` hr ON hr.parent = u.name
		WHERE hr.role IN ('Sales Manager', 'System Manager')
		AND u.enabled = 1 AND u.name != 'Administrator'
		""",
		as_list=True,
	)
	return [r[0] for r in rows]
