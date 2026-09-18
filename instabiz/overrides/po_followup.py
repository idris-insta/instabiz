"""instabiz.overrides.po_followup

Daily scheduler: alert Purchase Manager/Purchase User when a submitted
Purchase Order has no linked GRN (Purchase Receipt) after 7 days.

Deduplication: [ib-po-followup] marker in Notification Log subject —
one alert per PO per day (checked via document_name + subject pattern).
"""
import frappe
from frappe.utils import add_days, nowdate, escape_html

_MARKER = "[ib-po-followup]"
_OVERDUE_DAYS = 7


def _overdue_days():
	from instabiz.overrides.ib_settings import get_int
	return get_int("po_followup_days", _OVERDUE_DAYS)


def run_po_followup():
	overdue_date = add_days(nowdate(), -_overdue_days())

	# POs submitted > 7 days ago with no linked submitted Purchase Receipt
	overdue_pos = frappe.db.sql(
		"""
		SELECT
			po.name,
			po.supplier,
			po.supplier_name,
			po.transaction_date,
			po.grand_total,
			po.currency
		FROM `tabPurchase Order` po
		WHERE po.docstatus = 1
		  AND po.status NOT IN ('Closed', 'Completed', 'Cancelled')
		  AND po.transaction_date <= %(overdue_date)s
		  AND NOT EXISTS (
			SELECT 1
			FROM `tabPurchase Receipt Item` pri
			INNER JOIN `tabPurchase Receipt` pr ON pr.name = pri.parent
			WHERE pri.purchase_order = po.name
			  AND pr.docstatus = 1
		  )
		""",
		{"overdue_date": overdue_date},
		as_dict=True,
	)

	if not overdue_pos:
		frappe.logger().info("[po_followup] no overdue POs without GRN")
		return

	notify_users = frappe.db.sql_list(
		"""
		SELECT DISTINCT u.name
		FROM `tabUser` u
		INNER JOIN `tabHas Role` hr ON hr.parent = u.name
		WHERE hr.role IN ('Purchase Manager', 'Purchase User')
		  AND u.enabled = 1
		  AND u.name != 'Administrator'
		"""
	)

	if not notify_users:
		frappe.logger().info("[po_followup] no purchase users to notify")
		return

	today = nowdate()
	created = 0

	for po in overdue_pos:
		# Dedup: skip if already alerted for this PO today
		already_sent = frappe.db.exists(
			"Notification Log",
			{
				"document_name": po.name,
				"subject": ["like", f"%{_MARKER}%"],
				"creation": [">=", today],
			},
		)
		if already_sent:
			continue

		subject = (
			f"{_MARKER} PO {po.name} — no GRN after {_overdue_days()}+ days "
			f"| {escape_html(po.supplier_name or po.supplier)} "
			f"| {po.currency} {po.grand_total:,.2f}"
		)

		for user in notify_users:
			frappe.get_doc({
				"doctype":       "Notification Log",
				"subject":       subject,
				"for_user":      user,
				"from_user":     "Administrator",
				"type":          "Alert",
				"document_type": "Purchase Order",
				"document_name": po.name,
			}).insert(ignore_permissions=True)

		created += 1

	if created:
		frappe.db.commit()

	frappe.logger().info(f"[po_followup] {created} overdue PO alerts sent")
