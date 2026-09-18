"""instabiz.overrides.advance_approval

Gate: a Sales Order that has an advance payment collected while still Draft
(custom_advance_paid > 0, docstatus == 0) can't be submitted/confirmed until
the designated approver signs off. custom_advance_approval_status is set to
"Pending" automatically the first time an advance lands on a Draft SO (see
payment_entry.py._update_so_advance) and resolved here via set_advance_approval().

Orders where the advance is collected AFTER the SO is already submitted are
unaffected — the gate only applies pre-confirmation.
"""
import frappe
from frappe import _
from frappe.utils import flt, fmt_money

APPROVER_EMAIL = "idris@instabizsolutions.com"  # default when Instabiz Settings has none


def advance_approvers():
	"""Users who can approve advances (Instabiz Settings: main + backup)."""
	from instabiz.overrides.ib_settings import get

	main = get("advance_approver", APPROVER_EMAIL)
	backup = get("advance_approver_backup")
	return [u for u in (main, backup) if u]


def approver_label():
	return " / ".join(advance_approvers())


def _is_advance_approver(user=None):
	user = user or frappe.session.user
	if user in advance_approvers():
		return True
	return "System Manager" in frappe.get_roles(user)


@frappe.whitelist()
def get_advance_approval_queue():
	"""Pending advance approvals + recent decision history, for the Advance
	Approvals dashboard. Approver-only (same gate as set_advance_approval)."""
	if not _is_advance_approver():
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	pending = frappe.db.sql("""
		SELECT so.name, so.customer_name, so.custom_advance_paid AS advance_paid,
		       so.custom_sales_person_user AS sales_person_user,
		       COALESCE(u.full_name, so.custom_sales_person_user) AS sales_person_name,
		       so.currency, so.transaction_date, so.creation
		FROM `tabSales Order` so
		LEFT JOIN `tabUser` u ON u.name = so.custom_sales_person_user
		WHERE so.docstatus = 0 AND so.custom_advance_approval_status = 'Pending'
		ORDER BY so.creation ASC
	""", as_dict=True)

	history = frappe.db.sql("""
		SELECT so.name, so.customer_name, so.custom_advance_paid AS advance_paid,
		       so.custom_advance_approval_status AS status,
		       so.custom_advance_approval_remarks AS remarks,
		       COALESCE(u.full_name, so.custom_sales_person_user) AS sales_person_name,
		       so.currency, so.modified
		FROM `tabSales Order` so
		LEFT JOIN `tabUser` u ON u.name = so.custom_sales_person_user
		WHERE so.custom_advance_approval_status IN ('Approved', 'Rejected')
		ORDER BY so.modified DESC
		LIMIT 30
	""", as_dict=True)

	return {"pending": pending, "history": history}


def check_advance_approval(doc):
	"""Called from Sales Order.before_submit()."""
	# Rejected stays hard-blocked even though the advance display was zeroed
	# out — zeroing was purely so the order stops being credited with money
	# that isn't backing it anymore, not a way to clear the gate. Confirming
	# a Rejected order needs a fresh decision (re-request approval, or the
	# rep sorts out a corrected advance), not "reject" quietly turning into
	# "never mind, submit anyway."
	if doc.custom_advance_approval_status == "Rejected":
		frappe.throw(
			_("Cannot confirm this Sales Order: its advance payment was rejected by {0}. "
			  "Resolve that before submitting.").format(approver_label())
		)
	if flt(doc.custom_advance_paid) > 0 and doc.custom_advance_approval_status != "Approved":
		frappe.throw(
			_("Cannot confirm this Sales Order: an advance payment of {0} was collected "
			  "but has not been approved yet. {1} must approve it first.").format(
				fmt_money(doc.custom_advance_paid, currency=doc.currency),
				approver_label(),
			)
		)


@frappe.whitelist()
def set_advance_approval(sales_order, status, remarks=None):
	"""Approve or reject the advance collected against a Draft Sales Order."""
	if status not in ("Approved", "Rejected"):
		frappe.throw(_("Status must be Approved or Rejected."))
	if not _is_advance_approver():
		frappe.throw(_("Only {0} can approve advance payments.").format(approver_label()))

	doc = frappe.get_doc("Sales Order", sales_order)
	if doc.docstatus != 0:
		frappe.throw(_("This Sales Order is no longer in Draft — nothing to approve."))
	if flt(doc.custom_advance_paid) <= 0:
		frappe.throw(_("No advance payment recorded against this order."))

	# Capture before any zeroing below — the notification/comment should still
	# state the real amount that was rejected, not 0.
	rejected_amount = flt(doc.custom_advance_paid)

	doc.db_set("custom_advance_approval_status", status, update_modified=False)
	doc.db_set("custom_advance_approval_remarks", remarks or "", update_modified=False)

	if status == "Rejected":
		# A rejected advance no longer counts against this order — it stops
		# reducing the order's outstanding balance and stops showing as
		# "received" here. The underlying Payment Entry is untouched (real
		# cash was genuinely received); if it needs refunding or
		# re-allocating, that's a separate real accounting action, not
		# something this field should silently paper over. _update_so_advance
		# also skips recomputing this field once a SO is Rejected, so a later
		# unrelated PE event on the same order can't quietly revive it.
		doc.db_set("custom_advance_paid", 0, update_modified=False)
		customer = doc.customer
		if customer:
			from instabiz.overrides.customer import refresh_customer_outstanding
			refresh_customer_outstanding(customer)

	doc.add_comment(
		"Info",
		_("Advance payment {0} by {1}{2}").format(
			status, frappe.session.user, f" — {remarks}" if remarks else ""
		),
	)

	if doc.custom_sales_person_user:
		frappe.get_doc({
			"doctype":       "Notification Log",
			"subject":       f"[ib-advance-approval-{doc.name}] Advance {status.lower()} for {doc.name}"[:140],
			"email_content": _("Advance payment of {0} for {1} was {2} by {3}.{4}").format(
				fmt_money(rejected_amount, currency=doc.currency),
				doc.name, status.lower(), frappe.session.user,
				f" Remarks: {remarks}" if remarks else "",
			),
			"for_user":      doc.custom_sales_person_user,
			"from_user":     frappe.session.user,
			"type":          "Alert",
			"document_type": "Sales Order",
			"document_name": doc.name,
		}).insert(ignore_permissions=True)

	return {"status": status}
