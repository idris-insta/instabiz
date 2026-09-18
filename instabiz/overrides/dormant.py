import frappe
from frappe.utils import add_days, nowdate

DORMANT_DAYS = 60
_MARKER = "[ib-dormant-reminder]"


def _dormant_days():
	from instabiz.overrides.ib_settings import get_int
	return get_int("dormant_days", DORMANT_DAYS)


@frappe.whitelist()
def run_dormant_check():
	frappe.only_for("System Manager")
	threshold = add_days(nowdate(), -_dormant_days())

	# LEFT JOIN so customers with NO submitted SO ever are included too (they're
	# the most dormant of all) — matches the same pattern customer_assignment.py's
	# classify_customer()/get_dormant_pool() already use. The old INNER-JOIN-shaped
	# GROUP BY required at least one submitted SO to even be considered, so ~1100
	# real customers who never ordered were structurally invisible to this check.
	dormant = frappe.db.sql(
		"""
		SELECT c.name AS customer, MAX(so.transaction_date) AS last_order_date,
			c.custom_sales_person_user AS customer_sales_person
		FROM `tabCustomer` c
		LEFT JOIN `tabSales Order` so ON so.customer = c.name AND so.docstatus = 1
		WHERE c.disabled = 0
		GROUP BY c.name
		HAVING last_order_date <= %(threshold)s OR last_order_date IS NULL
		""",
		{"threshold": threshold},
		as_dict=True,
	)

	created = 0
	for row in dormant:
		if row.last_order_date:
			so = frappe.db.get_value(
				"Sales Order",
				{"customer": row.customer, "docstatus": 1},
				["custom_sales_person_user", "name"],
				order_by="transaction_date desc",
				as_dict=True,
			)
			sales_user = so.custom_sales_person_user if so else None
		else:
			# Never ordered — no SO to read a sales person off of, fall back to
			# the Customer's own assignment (same field get_dormant_pool() reads).
			sales_user = row.customer_sales_person

		if not sales_user:
			continue

		# skip if open dormant ToDo already exists for this customer
		if frappe.db.exists("ToDo", {
			"reference_type": "Customer",
			"reference_name": row.customer,
			"status": "Open",
			"description": ["like", f"%{_MARKER}%"],
		}):
			continue

		if row.last_order_date:
			desc = (
				f"<b>{row.customer}</b> has not placed an order in over {_dormant_days()} days "
				f"(last order: {frappe.utils.formatdate(row.last_order_date)}).<br><br>"
				+ _MARKER
			)
		else:
			desc = (
				f"<b>{row.customer}</b> has never placed an order.<br><br>"
				+ _MARKER
			)

		frappe.get_doc({
			"doctype":        "ToDo",
			"status":         "Open",
			"priority":       "Medium",
			"date":           add_days(nowdate(), 3),
			"allocated_to":   sales_user,
			"reference_type": "Customer",
			"reference_name": row.customer,
			"description":    desc,
		}).insert(ignore_permissions=True)

		frappe.get_doc({
			"doctype":        "Notification Log",
			"subject":        f"Follow up: {row.customer} — no order in {_dormant_days()}+ days",
			"email_content":  desc,
			"for_user":       sales_user,
			"from_user":      "Administrator",
			"type":           "Alert",
			"document_type":  "Customer",
			"document_name":  row.customer,
		}).insert(ignore_permissions=True)

		created += 1

	frappe.db.commit()
	frappe.logger().info(f"[dormant] created {created} follow-up tasks")
