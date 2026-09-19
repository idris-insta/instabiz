"""IB Support Ticket — customer complaints, queries and returns.

Deadlines come from priority (respond / resolve within N hours). The owner
defaults to the customer's sales person. An open Complaint / Quality Issue /
Return counts against Customer.custom_complaint_count, which feeds the customer
health score; resolving or deleting it releases the count. A daily run flags
tickets past their deadline and tells the owner and the Sales Managers.
"""
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_to_date, cint, now_datetime

SLA_HOURS = {"Urgent": (2, 8), "High": (4, 24), "Medium": (8, 48), "Low": (24, 96)}
COMPLAINT_TYPES = ("Complaint", "Quality Issue", "Return")
OPEN_STATES = ("Open", "In Progress", "Waiting on Customer")


class IBSupportTicket(Document):
	def validate(self):
		if not self.opened_at:
			self.opened_at = now_datetime()
		self.priority = self.priority or "Medium"
		if not self.assigned_to and self.customer:
			self.assigned_to = frappe.db.get_value("Customer", self.customer, "custom_sales_person_user")
		respond, resolve = SLA_HOURS.get(self.priority, SLA_HOURS["Medium"])
		self.response_due = add_to_date(self.opened_at, hours=respond)
		self.resolution_due = add_to_date(self.opened_at, hours=resolve)
		if self.status != "Open" and not self.first_responded_at:
			self.first_responded_at = now_datetime()
		if self.status in ("Resolved", "Closed"):
			self.resolved_at = self.resolved_at or now_datetime()
			if self.ticket_type in COMPLAINT_TYPES and not self.root_cause:
				frappe.throw(_("Pick a Root Cause before resolving a {0}.").format(self.ticket_type))
		else:
			self.resolved_at = None
		end = self.resolved_at or now_datetime()
		self.sla_breached = 1 if self.resolution_due and end > frappe.utils.get_datetime(self.resolution_due) else 0
		self._sync_complaint_count()

	def on_update(self):
		before = self.get_doc_before_save()
		if self.assigned_to and self.assigned_to != frappe.session.user and (not before or before.assigned_to != self.assigned_to):
			_bell(self.assigned_to, _("{0} {1}: {2}").format(self.priority, self.ticket_type, self.customer_name or self.customer), self.name)

	def on_trash(self):
		if self.customer and self._counts():
			_bump(self.customer, -1)

	def _counts(self, doc=None):
		d = doc or self
		return bool(d.customer and d.ticket_type in COMPLAINT_TYPES and d.status in OPEN_STATES)

	def _sync_complaint_count(self):
		before = None if self.is_new() else self.get_doc_before_save()
		was, now = bool(before and self._counts(before)), self._counts()
		if before and before.customer != self.customer:
			if was:
				_bump(before.customer, -1)
			if now:
				_bump(self.customer, 1)
		elif was != now:
			_bump(self.customer, 1 if now else -1)


def _bump(customer, delta):
	if not frappe.db.has_column("Customer", "custom_complaint_count"):
		return
	cur = cint(frappe.db.get_value("Customer", customer, "custom_complaint_count"))
	frappe.db.set_value("Customer", customer, "custom_complaint_count", max(0, cur + delta), update_modified=False)


def _bell(user, subject, name):
	frappe.get_doc({"doctype": "Notification Log", "for_user": user, "type": "Alert", "subject": subject[:140],
		"document_type": "IB Support Ticket", "document_name": name}).insert(ignore_permissions=True)


KEYWORDS = {
	"Quality Issue": ("defect", "peel", "adhesion", "not sticking", "bubble", "wrinkle", "quality", "faulty", "thickness", "shade"),
	"Return": ("return", "replace", "wrong item", "send back", "refund"),
	"Delivery": ("delivery", "dispatch", "not received", "delay", "transport", "lr ", "courier", "short"),
	"Payment": ("payment", "invoice", "overcharge", "bill", "gst", "credit note", "amount"),
}
URGENT = ("urgent", "immediately", "asap", "line stopped", "stopped", "critical", "legal")


@frappe.whitelist()
def classify(subject, description=None):
	"""Suggest type and priority from the text (keyword rules)."""
	low = f"{subject or ''} {description or ''}".lower()
	ticket_type = next((t for t, kws in KEYWORDS.items() if any(k in low for k in kws)), "Complaint" if "complain" in low else "Query")
	priority = "Urgent" if any(u in low for u in URGENT) else ("High" if ticket_type in COMPLAINT_TYPES else "Medium")
	return {"ticket_type": ticket_type, "priority": priority}


def run_ticket_deadlines():
	"""Daily: mark open tickets past their deadline and tell the owner + Sales Managers once."""
	now = now_datetime()
	late = frappe.get_all("IB Support Ticket", filters={"status": ["in", OPEN_STATES], "resolution_due": ["<", now],
		"sla_breached": 0}, fields=["name", "subject", "customer_name", "assigned_to", "priority"])
	if not late:
		return
	managers = set(frappe.get_all("Has Role", filters={"role": "Sales Manager", "parenttype": "User"}, pluck="parent"))
	for t in late:
		frappe.db.set_value("IB Support Ticket", t.name, "sla_breached", 1, update_modified=False)
		subject = _("Past deadline: {0} — {1}").format(t.customer_name or "", t.subject)
		for user in {t.assigned_to, *managers} - {None, "", "Administrator"}:
			if frappe.db.get_value("User", user, "enabled"):
				_bell(user, subject, t.name)
	frappe.db.commit()
