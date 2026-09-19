"""instabiz.overrides.approvals

Maker / checker on accounting entries (IB Accounts Settings → Approvals):

  Journal Entry (memorandum / adjustment entries) and, when switched on,
  outgoing Payment Entries (vendor / expense payments) above the set limit.

The maker saves the draft and presses "Send for Approval"; the approvers
(Accounts Manager, System Manager) get a bell and see it under IB Pending
Approvals, where they approve (the entry is submitted) or reject with a note.
A maker without the approver role cannot submit such an entry directly.
Entries made by the system (no logged-in desk request, or flagged
ignore_approval) are never held up.

get_pending() also lists the other approval queues in the app (advance on
Sales Orders, leave, overtime, expense claims, draft company expenses) so one
screen shows everything waiting on someone.
"""
import frappe
from frappe import _
from frappe.utils import flt

from instabiz.overrides import ib_settings

APPROVER_ROLES = ("Accounts Manager", "System Manager")


def _rules(doctype, doc=None):
	if doctype == "Journal Entry":
		on = ib_settings.get_check("je_needs_approval", True)
		amount = flt(doc.total_debit) if doc else 0
	else:
		on = ib_settings.get_check("payment_needs_approval", False) and (not doc or doc.payment_type == "Pay")
		amount = flt(doc.paid_amount) if doc else 0
	limit = flt(ib_settings.get("approval_limit", 0))
	return on and (not doc or amount >= limit)


def _is_approver(user=None):
	return bool(set(APPROVER_ROLES) & set(frappe.get_roles(user or frappe.session.user)))


def check_before_submit(doc, method=None):
	"""before_submit on Journal Entry / Payment Entry."""
	if doc.flags.ignore_approval or not getattr(frappe.local, "request", None) or frappe.session.user == "Administrator":
		return
	if not _rules(doc.doctype, doc) or _is_approver():
		if doc.meta.has_field("custom_approval_status") and doc.get("custom_approval_status") == "Pending":
			doc.custom_approval_status = "Approved"
			doc.custom_approved_by = frappe.session.user
		return
	frappe.throw(_("This {0} needs approval. Save it and press Send for Approval.").format(doc.doctype), title=_("Approval needed"))


@frappe.whitelist()
def send_for_approval(doctype, name):
	if doctype not in ("Journal Entry", "Payment Entry"):
		frappe.throw(_("Not supported"))
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("write")
	if doc.docstatus != 0:
		frappe.throw(_("Only a draft can be sent for approval."))
	doc.db_set({"custom_approval_status": "Pending", "custom_approval_note": None})
	amount = flt(doc.get("total_debit") or doc.get("paid_amount"))
	subject = _("Approve {0} {1} — {2} by {3}").format(doctype, name, frappe.utils.fmt_money(amount, 0),
		frappe.utils.get_fullname(frappe.session.user))
	for u in _approvers():
		if u != frappe.session.user:
			frappe.get_doc({"doctype": "Notification Log", "for_user": u, "type": "Alert", "subject": subject[:140],
				"document_type": doctype, "document_name": name}).insert(ignore_permissions=True)
	doc.add_comment("Info", _("Sent for approval"))
	return "Pending"


@frappe.whitelist()
def decide(doctype, name, approve, note=None):
	if not _is_approver():
		frappe.throw(_("Only an Accounts Manager can approve."), frappe.PermissionError)
	doc = frappe.get_doc(doctype, name)
	if doc.docstatus != 0 or doc.get("custom_approval_status") != "Pending":
		frappe.throw(_("{0} is not waiting for approval.").format(name))
	approve = frappe.utils.cint(approve)
	doc.custom_approval_status = "Approved" if approve else "Rejected"
	doc.custom_approved_by = frappe.session.user
	doc.custom_approval_note = note
	if approve:
		doc.flags.ignore_approval = True
		doc.submit()
	else:
		doc.save()
	doc.add_comment("Info", _("{0} by {1}{2}").format(doc.custom_approval_status, frappe.utils.get_fullname(),
		f": {note}" if note else ""))
	if doc.owner != frappe.session.user:
		frappe.get_doc({"doctype": "Notification Log", "for_user": doc.owner, "type": "Alert",
			"subject": _("{0} {1} {2}").format(doctype, name, doc.custom_approval_status.lower())[:140],
			"document_type": doctype, "document_name": name}).insert(ignore_permissions=True)
	return doc.custom_approval_status


def _approvers():
	return {u for u in frappe.get_all("Has Role", filters={"role": ["in", list(APPROVER_ROLES)], "parenttype": "User"},
		pluck="parent") if u != "Administrator" and frappe.db.get_value("User", u, "enabled")}


def get_pending(user=None):
	"""Everything waiting on an approver, as rows: kind, doctype, name, date, party / employee, amount, by, action."""
	user = user or frappe.session.user
	roles = set(frappe.get_roles(user))
	rows = []

	def add(kind, doctype, name, date, who, amount, by, can):
		rows.append(frappe._dict(kind=kind, doctype=doctype, name=name, date=date, who=who, amount=flt(amount), by=by, can_act=can))

	approver = bool(roles & set(APPROVER_ROLES))
	for dt, amt, party in (("Journal Entry", "total_debit", "user_remark"), ("Payment Entry", "paid_amount", "party_name")):
		if frappe.db.has_column(dt, "custom_approval_status"):
			for d in frappe.get_all(dt, filters={"docstatus": 0, "custom_approval_status": "Pending"},
					fields=["name", "posting_date", amt, party, "owner"]):
				add(_("Accounting entry"), dt, d.name, d.posting_date, (d.get(party) or "")[:60], d.get(amt), d.owner, approver)
	if frappe.db.has_column("Sales Order", "custom_advance_approval_status"):
		for d in frappe.get_all("Sales Order", filters={"docstatus": 0, "custom_advance_approval_status": "Pending"},
				fields=["name", "transaction_date", "customer_name", "custom_advance_paid", "owner"]):
			add(_("Advance on order"), "Sales Order", d.name, d.transaction_date, d.customer_name, d.custom_advance_paid, d.owner,
				bool(roles & {"System Manager"}) or user == ib_settings.get("advance_approver", ""))
	hr = bool(roles & {"HR Manager", "HR User", "System Manager"})
	for d in frappe.get_all("Leave Application", filters={"docstatus": 0, "status": "Open"},
			fields=["name", "from_date", "employee_name", "total_leave_days", "leave_approver", "owner"]):
		if hr or d.leave_approver == user:
			add(_("Leave"), "Leave Application", d.name, d.from_date, d.employee_name, d.total_leave_days, d.owner, True)
	if frappe.db.exists("DocType", "IB Overtime Request"):
		for d in frappe.get_all("IB Overtime Request", filters={"status": "Pending Approval"},
				fields=["name", "date", "employee_name", "overtime_hours", "owner"]):
			add(_("Overtime"), "IB Overtime Request", d.name, d.date, d.employee_name, d.overtime_hours, d.owner, hr)
	for d in frappe.get_all("Expense Claim", filters={"docstatus": 0, "approval_status": "Draft"},
			fields=["name", "posting_date", "employee_name", "total_claimed_amount", "expense_approver", "owner"]):
		if hr or d.expense_approver == user:
			add(_("Expense claim"), "Expense Claim", d.name, d.posting_date, d.employee_name, d.total_claimed_amount, d.owner, True)
	return rows


def after_migrate():
	if not frappe.db.exists("Number Card", "Pending Approvals"):
		frappe.get_doc({"doctype": "Number Card", "name": "Pending Approvals", "label": "Pending Approvals", "type": "Custom",
			"method": "instabiz.instabiz.report.ib_pending_approvals.ib_pending_approvals.pending_count",
			"is_public": 1, "show_percentage_stats": 0, "color": "#d97757", "module": "Instabiz"}).insert(ignore_permissions=True)
	fields = {
		"custom_approval_status": {"label": "Approval", "fieldtype": "Select", "options": "\nPending\nApproved\nRejected",
			"read_only": 1, "allow_on_submit": 1, "no_copy": 1, "in_standard_filter": 1},
		"custom_approved_by": {"label": "Approved By", "fieldtype": "Link", "options": "User", "read_only": 1,
			"allow_on_submit": 1, "no_copy": 1},
		"custom_approval_note": {"label": "Approval Note", "fieldtype": "Small Text", "read_only": 1, "allow_on_submit": 1, "no_copy": 1},
	}
	after = {"Journal Entry": "user_remark", "Payment Entry": "remarks"}
	for dt, anchor in after.items():
		prev = anchor
		for fieldname, spec in fields.items():
			if not frappe.db.exists("Custom Field", {"dt": dt, "fieldname": fieldname}):
				frappe.get_doc({"doctype": "Custom Field", "dt": dt, "fieldname": fieldname, "insert_after": prev, **spec}).insert(
					ignore_permissions=True)
			prev = fieldname
