"""instabiz.overrides.expiry_alert — daily batch expiry alert for adhesive products."""
import frappe
from frappe.utils import today, add_days, escape_html

_ALERT_DAYS = 30
_MARKER = "[ib-expiry]"
_COOLDOWN_DAYS = 7


def _alert_days():
	from instabiz.overrides.ib_settings import get_int
	return get_int("batch_expiry_alert_days", _ALERT_DAYS)


def run_expiry_alert():
	"""Daily job — sends bell notifications for batches expiring within 30 days."""
	target_date = add_days(today(), _alert_days())
	batches = frappe.db.sql(
		"""
		SELECT b.name, b.item, b.expiry_date, i.item_name,
		       DATEDIFF(b.expiry_date, CURDATE()) AS days_left
		FROM `tabBatch` b
		JOIN `tabItem` i ON i.name = b.item
		WHERE b.expiry_date IS NOT NULL
		  AND b.expiry_date <= %(target)s
		  AND b.expiry_date >= CURDATE()
		  AND i.has_expiry_date = 1
		  AND (b.batch_qty > 0 OR b.batch_qty IS NULL)
		ORDER BY b.expiry_date ASC
		""",
		{"target": target_date},
		as_dict=True,
	)

	if not batches:
		return

	recipients = _get_warehouse_managers()
	if not recipients:
		return

	for user in recipients:
		for batch in batches:
			if _already_notified(user, batch.name):
				continue
			_notify(user, batch)

	frappe.db.commit()


def _get_warehouse_managers():
	rows = frappe.db.sql("""
		SELECT DISTINCT hr.parent
		FROM `tabHas Role` hr
		JOIN `tabUser` u ON u.name = hr.parent
		WHERE hr.role IN ('Warehouse Manager', 'Stock User', 'Purchase Manager', 'System Manager')
		  AND hr.parenttype = 'User'
		  AND u.enabled = 1
		  AND hr.parent NOT IN ('Administrator', 'Guest')
	""", as_dict=True)
	return [r.parent for r in rows]


def _already_notified(user: str, batch: str) -> bool:
	cutoff = add_days(today(), -_COOLDOWN_DAYS)
	return frappe.db.exists(
		"Notification Log",
		{
			"for_user": user,
			"subject": ["like", f"%{_MARKER}%{batch}%"],
			"creation": [">=", cutoff],
		},
	)


def _notify(user: str, batch: dict) -> None:
	days = int(batch.days_left or 0)
	urgency = "URGENT — " if days <= 7 else ""
	frappe.get_doc({
		"doctype": "Notification Log",
		"for_user": user,
		"from_user": "Administrator",
		"subject": (
			f"{_MARKER} {urgency}Batch {batch.name} ({escape_html(batch.item_name or batch.item)}) "
			f"expires in {days} day{'s' if days != 1 else ''} on {batch.expiry_date}"
		),
		"type": "Alert",
		"document_type": "Batch",
		"document_name": batch.name,
	}).insert(ignore_permissions=True)
