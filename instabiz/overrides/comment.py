"""instabiz.overrides.comment — notify doc owner (and, for Sales Orders in
active production, factory roles) when a comment is posted on Q or SO."""
import frappe


WATCHED_DOCTYPES = {"Quotation", "Sales Order"}

# Same "notify everyone with role X" query pattern as payment_entry.py's
# _notify_accounts() / reorder_alert.py — role-based recipient lookup via
# `tabHas Role`, not a hardcoded user list.
_FACTORY_ROLES = frozenset({"Factory Management", "Factory Production", "System Manager"})


def notify_owner_on_comment(doc, method=None):
	"""
	Fires on Comment.after_insert.
	Sends an in-app notification + email to the document owner (custom_sales_person_user)
	whenever a real user comment is added to a Quotation or Sales Order.
	Skips if the commenter IS the owner.

	For Sales Orders that already have an active Order Sheet (production has
	actually started), also alerts Factory Management / Factory Production /
	System Manager — a comment on an in-flight production order is relevant
	to the floor, not just the rep. Quotations, and Sales Orders with no
	production started yet, are left as sales-rep-only (would be pure noise
	for factory roles otherwise).
	"""
	if doc.comment_type != "Comment":
		return
	if doc.reference_doctype not in WATCHED_DOCTYPES:
		return

	commenter = frappe.session.user
	commenter_name = frappe.db.get_value("User", commenter, "full_name") or commenter

	_notify_sales_owner(doc, commenter, commenter_name)

	if doc.reference_doctype == "Sales Order":
		_notify_factory_roles(doc, commenter, commenter_name)


def _notify_sales_owner(doc, commenter, commenter_name):
	owner_user, customer_name = frappe.db.get_value(
		doc.reference_doctype,
		doc.reference_name,
		["custom_sales_person_user", "customer_name"],
	) or (None, None)

	if not owner_user:
		return
	if commenter == owner_user:
		return

	# subject is what Frappe's bell dropdown actually renders (via .html(), see
	# notifications.js) — customer_name is free-text a Sales User controls, so
	# it must be escaped before going in here, same fix as dispatch_notification.py.
	customer_bit = f" — {frappe.utils.escape_html(customer_name)}" if customer_name else ""
	subject = f"New comment on {doc.reference_doctype} {doc.reference_name}{customer_bit}"
	message = (
		f"<b>{commenter_name}</b> commented on "
		f"<b>{doc.reference_doctype} {doc.reference_name}</b>:<br><br>"
		f"{doc.content}"
	)

	# ── In-app notification (bell icon + realtime event) ─────────────────────
	# Frappe's NotificationLog.after_insert automatically publishes a built-in
	# "notification" realtime event to the owner — no manual publish needed.
	frappe.get_doc({
		"doctype":       "Notification Log",
		"subject":       subject,
		"email_content": message,
		"document_type": doc.reference_doctype,
		"document_name": doc.reference_name,
		"for_user":      owner_user,
		"from_user":     commenter,
		"type":          "Alert",
	}).insert(ignore_permissions=True)


def _notify_factory_roles(doc, commenter, commenter_name):
	has_active_production = frappe.db.exists(
		"IB Order Sheet",
		{"sales_order": doc.reference_name, "status": ["!=", "Cancelled"]},
	)
	if not has_active_production:
		return

	users = frappe.db.sql(
		"""
		SELECT DISTINCT ur.parent
		FROM `tabHas Role` ur
		INNER JOIN `tabUser` u ON u.name = ur.parent
		WHERE ur.role IN %(roles)s
		  AND ur.parent != 'Administrator'
		  AND u.enabled = 1
		""",
		{"roles": list(_FACTORY_ROLES)},
		pluck="parent",
	)
	if not users:
		return

	customer_name = frappe.db.get_value("Sales Order", doc.reference_name, "customer_name")
	customer_bit = f" — {frappe.utils.escape_html(customer_name)}" if customer_name else ""
	subject = f"New comment on Sales Order {doc.reference_name}{customer_bit}"
	message = (
		f"<b>{commenter_name}</b> commented on "
		f"<b>Sales Order {doc.reference_name}</b> (in production):<br><br>"
		f"{doc.content}"
	)

	for user in users:
		if user == commenter:
			continue
		frappe.get_doc({
			"doctype":       "Notification Log",
			"subject":       subject,
			"email_content": message,
			"document_type": doc.reference_doctype,
			"document_name": doc.reference_name,
			"for_user":      user,
			"from_user":     commenter,
			"type":          "Alert",
		}).insert(ignore_permissions=True)


from frappe.core.doctype.comment.comment import Comment as _FrappeComment

# Doctypes with a Table field named "route": Frappe's update_comment_in_doc()
# reads `route` of the commented document as a web route and hands the child
# rows to redis → DataError, so every comment on these failed.
_TABLE_ROUTE_DOCTYPES = {"IB Work Order"}


class IBComment(_FrappeComment):
	def on_update(self):
		if self.reference_doctype not in _TABLE_ROUTE_DOCTYPES:
			return super().on_update()
		from frappe.core.doctype.comment import comment as core

		orig = core.clear_cache
		core.clear_cache = lambda *args, **kwargs: None  # these doctypes have no web page to clear
		try:
			return super().on_update()
		finally:
			core.clear_cache = orig
