"""instabiz.overrides.payment_entry

validate      → enforce_sales_user_own_customer  (Sales User: own customers only)
before_submit → _auto_reconcile   (Receive, no refs → link open SIs FIFO)
on_submit     → _notify_accounts, _update_so_advance
on_cancel     → _update_so_advance
"""
import frappe
from frappe import _
from frappe.utils import flt, fmt_money
from instabiz.overrides.permissions import _PE_UNRESTRICTED_ROLES

_ACCOUNTS_ROLES = frozenset({"Accounts User", "Accounts Manager", "System Manager"})


def enforce_sales_user_own_customer(doc, method=None):
	"""Write-time mirror of permissions.payment_entry_has_permission — a plain
	Sales User (not Accounts User/Manager/Sales Manager/System Manager) can
	only save a Payment Entry against a Customer they currently handle. The
	permission-query/has_permission hooks already gate read/list access; this
	closes the same rule on the write path, since doc.has_permission("create")
	is always True before the party is even picked (2026-09-03, user request)."""
	user = frappe.session.user
	roles = frappe.get_roles(user)
	if _PE_UNRESTRICTED_ROLES & set(roles):
		return
	if "Sales User" not in roles:
		return
	if doc.party_type != "Customer" or not doc.party:
		frappe.throw(_("You can only create a Payment Entry against a Customer."))
	handled_by = frappe.db.get_value("Customer", doc.party, "custom_sales_person_user")
	if handled_by != user:
		frappe.throw(_("{0} is not one of your assigned customers.").format(doc.party))


_DEFAULT_BANK_ACCOUNT = "50200023672503 - HDFC - MH & GJ - IB"
_DEFAULT_COST_CENTER = "Main - IB"


@frappe.whitelist()
def create_simple_customer_receipt(
	customer, amount, paid_to=None, mode_of_payment=None,
	reference_no=None, reference_date=None, remarks=None,
	posting_date=None, advance_for_so=None, payment_proof=None,
):
	"""Backs the simplified "Record Payment" dialog (2026-09-04, user request)
	— Sales Users were confused by the full native Payment Entry form's ~34
	conditionally-shown fields, most of which don't apply to their one real
	scenario: receiving an on-account payment from a customer they handle.
	This always creates a plain Receive/Customer Payment Entry (no
	references row — matches the existing Record Advance flow, item 119)
	with just the handful of fields that scenario needs, several defaulted.
	Goes through the normal Document API (frappe.new_doc().insert()), so
	enforce_sales_user_own_customer and every other validate hook still run —
	this is a friendlier front door, not a bypass. payment_proof (optional) is
	a file url already uploaded by the dialog's Attach control — screenshot,
	UTR, bank statement for UPI/NEFT/RTGS/cheque proof (2026-09-04)."""
	co = frappe.db.get_single_value("Global Defaults", "default_company")
	doc = frappe.new_doc("Payment Entry")
	doc.payment_type = "Receive"
	doc.party_type = "Customer"
	doc.party = customer
	doc.company = co
	doc.posting_date = posting_date or frappe.utils.today()
	doc.paid_amount = flt(amount)
	doc.received_amount = flt(amount)
	doc.source_exchange_rate = 1
	doc.target_exchange_rate = 1
	doc.paid_to = paid_to or _DEFAULT_BANK_ACCOUNT
	doc.cost_center = _DEFAULT_COST_CENTER
	if mode_of_payment:
		doc.mode_of_payment = mode_of_payment
	if reference_no:
		doc.reference_no = reference_no
	doc.reference_date = reference_date or doc.posting_date
	if remarks:
		doc.remarks = remarks
	if advance_for_so:
		doc.custom_advance_for_so = advance_for_so
	if payment_proof:
		doc.custom_payment_proof = payment_proof
	doc.insert()
	frappe.db.commit()
	return {"name": doc.name}


def before_submit(doc, method=None):
	_auto_reconcile(doc)


def on_submit(doc, method=None):
	_notify_accounts(doc)
	_update_so_advance(doc)
	_update_customer_outstanding(doc)
	_update_advance_for_so(doc)


def on_cancel(doc, method=None):
	_update_so_advance(doc)
	_update_customer_outstanding(doc)
	_update_advance_for_so(doc)


def _auto_reconcile(doc):
	"""Auto-link PE to outstanding SIs (oldest-first) when references are empty."""
	if doc.payment_type != "Receive" or doc.party_type != "Customer":
		return
	if doc.references:
		return

	remaining = flt(doc.paid_amount)
	# FOR UPDATE: without this, two Payment Entries submitted close together
	# against the same customer (two reps recording receipts, a double-click,
	# etc.) can both read the same invoice's outstanding_amount under MariaDB's
	# default REPEATABLE READ before either has committed — each independently
	# allocates the full outstanding amount, over-allocating the invoice once
	# both submits land. Same race, same fix, as _compute_so_advance_total()'s
	# own FOR UPDATE in this file: the row lock forces the second PE's read to
	# block until the first PE's whole submit transaction actually commits (or
	# rolls back), so it then sees the real, already-reduced outstanding_amount.
	open_invoices = frappe.db.sql(
		"""
		SELECT name, outstanding_amount
		FROM `tabSales Invoice`
		WHERE customer = %s
		  AND docstatus = 1
		  AND outstanding_amount > 0
		ORDER BY posting_date ASC, name ASC
		FOR UPDATE
		""",
		doc.party,
		as_dict=True,
	)

	added = False
	for inv in open_invoices:
		if remaining <= 0:
			break
		allocated = min(remaining, flt(inv.outstanding_amount))
		doc.append("references", {
			"reference_doctype": "Sales Invoice",
			"reference_name":    inv.name,
			"allocated_amount":  allocated,
		})
		remaining -= allocated
		added = True

	if added:
		doc.set_amounts()

	if remaining > 0.01:
		frappe.msgprint(
			f"₹{remaining:,.2f} could not be matched to any outstanding invoice. "
			"This amount will remain unallocated — reconcile manually if needed.",
			title="Partial Allocation",
			indicator="orange",
		)


def _notify_accounts(doc):
	"""Bell notification to Accounts roles on PE submit (Receive and Pay)."""
	if doc.payment_type not in ("Receive", "Pay"):
		return

	marker = f"[ib-payment-{doc.name}]"
	users = frappe.db.sql(
		"""
		SELECT DISTINCT ur.parent
		FROM `tabHas Role` ur
		INNER JOIN `tabUser` u ON u.name = ur.parent
		WHERE ur.role IN %(roles)s
		  AND ur.parent != 'Administrator'
		  AND u.enabled = 1
		""",
		{"roles": list(_ACCOUNTS_ROLES)},
		pluck="parent",
	)
	if not users:
		return

	direction = "received from" if doc.payment_type == "Receive" else "paid to"
	currency  = doc.paid_to_account_currency or frappe.defaults.get_global_default("currency") or "INR"
	amt_fmt   = fmt_money(doc.paid_amount, currency=currency)
	subject   = f"{marker} Payment {doc.payment_type}: {doc.party} — {amt_fmt}"
	content   = (
		f"Payment {direction} <b>{doc.party}</b>. "
		f"Amount: {amt_fmt}. "
		f"Ref No: {doc.reference_no or '—'}. "
		f"Doc: {doc.name}."
	)

	for user in users:
		if frappe.db.exists("Notification Log", {"subject": subject[:140], "for_user": user}):
			continue
		frappe.get_doc({
			"doctype":       "Notification Log",
			"subject":       subject[:140],
			"email_content": content,
			"for_user":      user,
			"from_user":     "Administrator",
			"type":          "Alert",
			"document_type": "Payment Entry",
			"document_name": doc.name,
		}).insert(ignore_permissions=True)


def _update_customer_outstanding(doc):
	"""Refresh custom_outstanding_amount on the customer after PE submit/cancel.
	Also clears the overdue block flag if the customer now has no overdue invoices.
	"""
	if doc.party_type != "Customer" or not doc.party:
		return
	from instabiz.overrides.customer import refresh_customer_outstanding
	refresh_customer_outstanding(doc.party)
	_maybe_clear_overdue_block(doc.party)

def _maybe_clear_overdue_block(customer):
	"""Lift custom_overdue_block when no more overdue invoices exist for customer."""
	if not frappe.db.get_value("Customer", customer, "custom_overdue_block"):
		return
	from frappe.utils import today
	still_overdue = frappe.db.sql(
		"""
		SELECT COUNT(*) FROM `tabSales Invoice`
		WHERE customer = %s AND docstatus = 1
		  AND outstanding_amount > 0
		  AND due_date < %s
		""",
		(customer, today()),
	)[0][0]
	if not still_overdue:
		frappe.db.set_value("Customer", customer, "custom_overdue_block", 0, update_modified=False)
		frappe.logger().info(f"IB: overdue block cleared for {customer} — all dues paid")


def _compute_so_advance_total(so_name):
	"""Total submitted-Receive advance against this SO from BOTH tracking
	paths — the Payment Entry Reference table (post-submit path, used once
	the SO is already submitted) and custom_advance_for_so (pre-submit
	on-account path, see _update_advance_for_so / advance_approval.py). A
	given PE only ever uses one path or the other — the on-account "Record
	Advance (Deposit)" button never fills the references child table (that's
	the whole reason it exists: PaymentEntry.validate_reference_documents()
	throws if references points at a non-submitted SO) — so summing both
	here is safe, not a double-count. Without this shared helper, whichever
	path's own on_submit/on_cancel handler ran most recently would overwrite
	custom_advance_paid with only its own half of the total and silently
	drop whatever the other path had already collected — the same
	inline-duplicate-math class of bug already fixed once in
	ib_analytics_hub.py's advance_collected KPI.

	FOR UPDATE on both queries: without it, two Payment Entries submitted
	against the same SO close together (two reps recording deposits, a
	double-click, etc.) race under MariaDB's default REPEATABLE READ — each
	runs this SUM on its own connection/transaction, and a plain (non-locking)
	SELECT can't see the other PE's row until that other transaction commits,
	which for a doc-event hook doesn't happen until the whole request ends
	(long after on_submit returns). Both would then independently compute a
	total that only includes their own amount, and whichever set_value() in
	_recompute_so_advance_locked() lands last "wins" — silently dropping the
	other PE's contribution, with nothing else ever re-summing it afterward to
	self-correct. FOR UPDATE forces a genuine locking read: InnoDB's gap/
	insert-intention locking on the WHERE-clause index means a concurrent
	transaction's still-uncommitted matching INSERT/UPDATE blocks this read
	until that transaction actually commits or rolls back — not just until its
	hook function returns — which is what actually closes the gap (same
	mechanism, same reasoning, as create_order_sheet()'s own FOR UPDATE fix in
	production.py). Deliberately not "fixed" by an early frappe.db.commit()
	inside the hook instead — that would break the atomicity of the rest of
	this Payment Entry's own submit/cancel request (any later step failing
	would no longer roll back the already-committed advance-total write).
	"""
	from_references = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(per.allocated_amount), 0)
		FROM `tabPayment Entry` pe
		INNER JOIN `tabPayment Entry Reference` per ON per.parent = pe.name
		WHERE per.reference_doctype = 'Sales Order'
		  AND per.reference_name    = %s
		  AND pe.payment_type       = 'Receive'
		  AND pe.docstatus          = 1
		FOR UPDATE
		""",
		so_name,
	)[0][0]
	from_on_account = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(pe.paid_amount), 0)
		FROM `tabPayment Entry` pe
		WHERE pe.custom_advance_for_so = %s
		  AND pe.payment_type       = 'Receive'
		  AND pe.docstatus          = 1
		FOR UPDATE
		""",
		so_name,
	)[0][0]
	return flt(from_references) + flt(from_on_account)


def _recompute_so_advance_locked(so_name):
	"""Recompute + persist custom_advance_paid for one Sales Order.

	Wrapped in an advisory lock (GET_LOCK, same IB-* pattern already used for
	Work Order status mutations in production.py) as a defensive, fast-failing
	layer on top of _compute_so_advance_total()'s own FOR UPDATE locking reads
	— bounds contention to a friendly 5s "please retry" instead of two
	concurrent calls both proceeding into (and one of them waiting out) InnoDB's
	own lock-wait timeout with a raw DB error.
	"""
	lock_name = f"IB-SO-ADVANCE-{so_name}"
	locked = frappe.db.sql("SELECT GET_LOCK(%s, 5)", lock_name)[0][0]
	if not locked:
		frappe.throw(_("Could not acquire lock for Sales Order {0}. Please try again.").format(so_name))
	try:
		# A Rejected advance is a deliberate decision that the current advance
		# no longer counts for this order — don't let an unrelated PE event
		# (submit/cancel of some other PE still referencing this SO) silently
		# recompute it back to a nonzero value. See set_advance_approval().
		if frappe.db.get_value("Sales Order", so_name, "custom_advance_approval_status") == "Rejected":
			return
		total = flt(_compute_so_advance_total(so_name))
		frappe.db.set_value("Sales Order", so_name, "custom_advance_paid", total)
		_maybe_flag_advance_pending(so_name, total)
		# Dev-mode customer outstanding (Customer.custom_outstanding_amount) is
		# grand_total - custom_advance_paid — an advance landing changes it
		# just as much as the SO submit/cancel events that already refresh it.
		customer = frappe.db.get_value("Sales Order", so_name, "customer")
		if customer:
			from instabiz.overrides.customer import refresh_customer_outstanding
			refresh_customer_outstanding(customer)
	finally:
		frappe.db.sql("SELECT RELEASE_LOCK(%s)", lock_name)


def _update_so_advance(doc):
	"""Recompute custom_advance_paid on every Sales Order referenced by this PE."""
	so_names = {
		ref.reference_name
		for ref in doc.references
		if ref.reference_doctype == "Sales Order"
	}
	for so_name in so_names:
		_recompute_so_advance_locked(so_name)


def _maybe_flag_advance_pending(so_name, total_advance):
	"""First time an advance lands on a still-Draft SO, flag it Pending approval
	(see advance_approval.py). Only matters pre-confirmation — once the SO is
	submitted the gate no longer applies, so leave submitted orders untouched."""
	if total_advance <= 0:
		return
	row = frappe.db.get_value(
		"Sales Order", so_name,
		["docstatus", "custom_advance_approval_status", "customer_name", "currency"],
		as_dict=True,
	)
	if row and row.docstatus == 0 and not row.custom_advance_approval_status:
		frappe.db.set_value(
			"Sales Order", so_name, "custom_advance_approval_status", "Pending", update_modified=False
		)
		_notify_advance_approver(so_name, row.customer_name, total_advance, row.currency)


def _update_advance_for_so(doc):
	"""On-account advance path: doc.custom_advance_for_so (set on a Receive PE
	that carries NO references row — see payment_entry.js / ib_sales_common.js's
	"Record Advance (Deposit)" button) drives the same Pending-flag +
	custom_advance_paid tracking that _update_so_advance() does for
	reference-row-based PEs on already-submitted SOs. This is the path that
	actually works for a Draft SO, since PaymentEntry.validate_reference_documents()
	unconditionally throws "Sales Order X must be submitted" the moment a PE's
	references table contains a row pointing at a non-submitted Sales Order —
	structurally impossible for the old path to ever fire pre-submit. Mirrors
	the old path's Rejected-guard so a rejected advance can't be silently
	revived by an unrelated PE event on the same SO.

	Delegates the actual recompute to the shared, lock-protected
	_recompute_so_advance_locked() (same helper _update_so_advance() uses) —
	this used to duplicate that logic inline with no locking at all, which is
	exactly the "two Payment Entries against the same Draft SO" race this
	on-account path is most exposed to (it's the only way to record an advance
	pre-submit at all, per this function's own docstring above).
	"""
	if doc.payment_type != "Receive" or not doc.custom_advance_for_so:
		return
	_recompute_so_advance_locked(doc.custom_advance_for_so)


def _notify_advance_approver(so_name, customer_name, total_advance, currency):
	"""Ping the designated approver — without this, a Pending advance sits silent
	until someone happens to reopen that Draft SO; the approve/reject UI already
	existed but nothing ever told the approver there was something to act on."""
	from instabiz.overrides.advance_approval import APPROVER_EMAIL

	if not frappe.db.exists("User", APPROVER_EMAIL):
		return
	marker = f"[ib-advance-pending-{so_name}]"
	frappe.get_doc({
		"doctype":       "Notification Log",
		"subject":       f"Advance approval needed: {so_name} {marker}"[:140],
		"email_content": (
			f"An advance payment of {fmt_money(total_advance, currency=currency)} was collected against "
			f"Draft Sales Order {so_name} ({customer_name or ''}). It cannot be confirmed until you approve it."
		),
		"for_user":      APPROVER_EMAIL,
		"from_user":     "Administrator",
		"type":          "Alert",
		"document_type": "Sales Order",
		"document_name": so_name,
	}).insert(ignore_permissions=True)
