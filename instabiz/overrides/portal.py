"""instabiz.overrides.portal

Customer self-service at /portal. The customer is always worked out on the
server from the login (Contact.user → Dynamic Link → Customer); nothing the
browser sends can point at another customer. A customer sees their own orders
with production progress, invoices / orders and outstanding, statement, rates
they were given, technical documents for items they buy, and their complaints;
they can raise a complaint or ask for a reorder (both become IB Support
Tickets for their sales person — a customer never creates a financial document).
"""
import frappe
from frappe import _
from frappe.utils import flt, getdate

from instabiz.overrides.billing_mode import is_dev_billing_mode, sales_doctype

OPEN_TICKETS = ("Open", "In Progress", "Waiting on Customer")
PRINTABLE = {"Quotation": "IB Quotation", "Sales Order": "IB Sales Order",
	"Delivery Note": "IB Delivery Challan", "Sales Invoice": "IB GST Tax Invoice"}


def get_portal_customer(throw=True):
	user = frappe.session.user
	if not user or user == "Guest":
		if throw:
			frappe.throw(_("Please log in."), frappe.PermissionError)
		return None
	cust = frappe.db.sql(
		"""SELECT dl.link_name FROM `tabContact` c
		JOIN `tabDynamic Link` dl ON dl.parent = c.name AND dl.parenttype = 'Contact'
		WHERE c.user = %s AND dl.link_doctype = 'Customer' LIMIT 1""", user)
	if cust:
		return cust[0][0]
	if throw:
		frappe.throw(_("No customer account is linked to your login."), frappe.PermissionError)
	return None


def _own(doctype, name, customer):
	field = "party_name" if doctype == "Quotation" else "customer"
	if frappe.db.get_value(doctype, name, field) != customer:
		frappe.throw(_("Not your document."), frappe.PermissionError)


def _outstanding(customer):
	from instabiz.overrides.ib_status import stored_statuses

	if is_dev_billing_mode():
		expr = "GREATEST(grand_total - IFNULL(custom_advance_paid, 0), 0)"
		cond = "docstatus = 1 AND per_billed < 100 AND status NOT IN %(closed)s"
	else:
		expr, cond = "outstanding_amount", "docstatus = 1 AND outstanding_amount > 0"
	val = frappe.db.sql(f"SELECT IFNULL(SUM({expr}), 0) FROM `tab{sales_doctype()}` WHERE customer = %(c)s AND {cond}",
		{"c": customer, "closed": stored_statuses("Sales Order", "Closed", "Completed")})
	return flt(val[0][0])


@frappe.whitelist()
def portal_summary():
	customer = get_portal_customer()
	rep = frappe.db.get_value("Customer", customer, ["customer_name", "custom_sales_person_user"], as_dict=True)
	rep_user = frappe.db.get_value("User", rep.custom_sales_person_user, ["full_name", "mobile_no", "email"], as_dict=True) if rep.custom_sales_person_user else None
	return {
		"customer": customer, "customer_name": rep.customer_name,
		"open_orders": frappe.db.count("Sales Order", {"customer": customer, "docstatus": 1, "per_delivered": ["<", 100]}),
		"open_tickets": frappe.db.count("IB Support Ticket", {"customer": customer, "status": ["in", OPEN_TICKETS]}),
		"outstanding": _outstanding(customer),
		"rep": rep_user,
	}


@frappe.whitelist()
def get_my_orders(limit=50):
	from instabiz.overrides.production import _so_progress_pct

	customer = get_portal_customer()
	orders = frappe.db.sql(
		"""SELECT name, transaction_date AS date, delivery_date, grand_total, per_delivered, po_no
		FROM `tabSales Order` WHERE customer = %s AND docstatus = 1
		ORDER BY transaction_date DESC LIMIT %s""", (customer, int(limit)), as_dict=True)
	for o in orders:
		pct, stage, _os = (None, None, None)
		try:
			pct, stage, _os = _so_progress_pct(o.name)
		except Exception:
			pass
		if flt(o.per_delivered) >= 100:
			o.state, o.pct = _("Delivered"), 100
		elif flt(o.per_delivered) > 0:
			o.state, o.pct = _("Part delivered"), max(flt(pct), flt(o.per_delivered))
		elif pct is None:
			o.state, o.pct = _("Order confirmed"), 0
		else:
			o.state, o.pct = (_("In production — {0}").format(stage) if stage else _("In production")), flt(pct)
	return orders


@frappe.whitelist()
def get_order_detail(sales_order):
	"""Per line: current stage and % done (no machine / internal names)."""
	from instabiz.overrides.production import get_so_production_status

	customer = get_portal_customer()
	_own("Sales Order", sales_order, customer)
	lines = frappe.get_all("Sales Order Item", filters={"parent": sales_order},
		fields=["item_code", "item_name", "qty", "uom", "delivered_qty"], order_by="idx")
	frappe.flags.ib_portal_so = sales_order
	try:
		status = get_so_production_status(sales_order)
	finally:
		frappe.flags.ib_portal_so = None
	prod = {i["item_code"]: i for i in status.get("items", [])} if status.get("has_order_sheet") else {}
	dns = frappe.db.sql_list("""SELECT DISTINCT dni.parent FROM `tabDelivery Note Item` dni
		JOIN `tabDelivery Note` dn ON dn.name = dni.parent WHERE dni.against_sales_order = %s AND dn.docstatus = 1""", sales_order)
	for ln in lines:
		p = prod.get(ln.item_code)
		stages = (p or {}).get("stages") or []
		done = bool(stages) and all(s["status"] == "Completed" for s in stages)
		ln.stage = (p or {}).get("current_stage") or (_("Ready") if done else _("Not started"))
		ln.pct = (p or {}).get("completion_pct", 0)
		ln.stages = [{"stage": s["stage"], "status": s["status"]} for s in (p or {}).get("stages", [])]
	return {"sales_order": sales_order, "lines": lines, "delivery_notes": dns}


@frappe.whitelist()
def get_my_invoices(limit=60):
	customer = get_portal_customer()
	out = frappe.db.sql(
		"""SELECT 'Sales Invoice' AS doctype, name, posting_date AS date, grand_total, outstanding_amount AS outstanding, status
		FROM `tabSales Invoice` WHERE customer = %s AND docstatus = 1 ORDER BY posting_date DESC LIMIT %s""",
		(customer, int(limit)), as_dict=True)
	if is_dev_billing_mode():
		out += frappe.db.sql(
			"""SELECT 'Sales Order' AS doctype, name, transaction_date AS date, grand_total,
			       GREATEST(grand_total - IFNULL(custom_advance_paid, 0), 0) AS outstanding, status
			FROM `tabSales Order` WHERE customer = %s AND docstatus = 1 AND per_billed < 100
			ORDER BY transaction_date DESC LIMIT %s""", (customer, int(limit)), as_dict=True)
	return sorted(out, key=lambda r: getdate(r.date), reverse=True)


@frappe.whitelist()
def get_my_quotations(limit=30):
	customer = get_portal_customer()
	return frappe.db.sql(
		"""SELECT name, transaction_date AS date, valid_till, grand_total, status FROM `tabQuotation`
		WHERE quotation_to = 'Customer' AND party_name = %s AND docstatus = 1
		ORDER BY transaction_date DESC LIMIT %s""", (customer, int(limit)), as_dict=True)


@frappe.whitelist()
def get_my_prices(item_code=None):
	"""Last rate given for each item this customer has ordered."""
	customer = get_portal_customer()
	cond = " AND i.item_code = %(item)s" if item_code else ""
	rows = frappe.db.sql(
		f"""SELECT i.item_code, i.item_name, i.uom, i.rate, so.transaction_date AS date, so.name AS document
		FROM `tabSales Order Item` i JOIN `tabSales Order` so ON so.name = i.parent
		WHERE so.docstatus = 1 AND so.customer = %(customer)s {cond}
		ORDER BY so.transaction_date DESC LIMIT 500""", {"customer": customer, "item": item_code}, as_dict=True)
	last = {}
	for r in rows:
		last.setdefault(r.item_code, r)
	return list(last.values())


@frappe.whitelist()
def get_my_documents():
	"""Current TDS / SDS / COA for items this customer buys."""
	from instabiz.instabiz.doctype.ib_item_document.ib_item_document import current_documents

	customer = get_portal_customer()
	items = frappe.db.sql_list("""SELECT DISTINCT i.item_code FROM `tabSales Order Item` i
		JOIN `tabSales Order` so ON so.name = i.parent WHERE so.docstatus = 1 AND so.customer = %s""", customer)
	docs = current_documents(items, customer_facing=True) if items else []
	names = {i.name: i.item_name for i in frappe.get_all("Item", filters={"name": ["in", items or [""]]}, fields=["name", "item_name"])}
	return [{"name": d.name, "item_code": d.item_code, "item_name": names.get(d.item_code), "document_type": d.document_type,
		"version": d.version} for d in docs]


@frappe.whitelist()
def download_item_document(name):
	customer = get_portal_customer()
	d = frappe.db.get_value("IB Item Document", name, ["item_code", "file", "share_with_customers", "is_current"], as_dict=True)
	bought = frappe.db.sql("""SELECT 1 FROM `tabSales Order Item` i JOIN `tabSales Order` so ON so.name = i.parent
		WHERE so.docstatus = 1 AND so.customer = %s AND i.item_code = %s LIMIT 1""", (customer, d and d.item_code))
	if not d or not d.share_with_customers or not bought:
		frappe.throw(_("Not available."), frappe.PermissionError)
	f = frappe.get_doc("File", {"file_url": d.file})
	frappe.local.response.filename = f.file_name
	frappe.local.response.filecontent = f.get_content()
	frappe.local.response.type = "download"


@frappe.whitelist()
def download_pdf(doctype, name):
	"""PDF of one of the customer's own quotations / orders / challans / invoices, or their statement."""
	customer = get_portal_customer()
	if doctype == "Statement":
		doctype, name, fmt = "Customer", customer, "IB Outstanding Statement"
	elif doctype in PRINTABLE:
		_own(doctype, name, customer)
		if frappe.db.get_value(doctype, name, "docstatus") != 1:
			frappe.throw(_("Not available."), frappe.PermissionError)
		fmt = PRINTABLE[doctype] if frappe.db.exists("Print Format", PRINTABLE[doctype]) else None
	else:
		frappe.throw(_("Not available."), frappe.PermissionError)
	# ownership is checked above; the print formats read Company / Address records a
	# customer login can't, so render as Administrator and switch straight back
	user = frappe.session.user
	frappe.flags.ib_portal_customer = customer
	try:
		frappe.set_user("Administrator")
		pdf = frappe.get_print(doctype, name, fmt, as_pdf=True)
	finally:
		frappe.set_user(user)
		frappe.flags.ib_portal_customer = None
	frappe.local.response.filename = f"{name.replace('/', '-')}.pdf"
	frappe.local.response.filecontent = pdf
	frappe.local.response.type = "pdf"


@frappe.whitelist()
def get_my_tickets(limit=50):
	customer = get_portal_customer()
	return frappe.get_all("IB Support Ticket", filters={"customer": customer},
		fields=["name", "subject", "ticket_type", "status", "opened_at", "resolved_at", "resolution"],
		order_by="creation desc", limit_page_length=int(limit))


@frappe.whitelist()
def raise_ticket(subject, description=None, ticket_type="Complaint", reference_name=None, item_code=None):
	customer = get_portal_customer()
	if not (subject or "").strip():
		frappe.throw(_("Subject is required."))
	if ticket_type not in ("Complaint", "Quality Issue", "Return", "Delivery", "Payment", "Query", "Reorder Request"):
		ticket_type = "Query"
	ref_dt = None
	if reference_name:
		_own("Sales Order", reference_name, customer)
		ref_dt = "Sales Order"
	doc = frappe.get_doc({"doctype": "IB Support Ticket", "customer": customer, "subject": subject.strip()[:140],
		"description": description, "ticket_type": ticket_type, "source": "Portal", "status": "Open",
		"priority": "High" if ticket_type in ("Complaint", "Quality Issue", "Return") else "Medium",
		"reference_doctype": ref_dt, "reference_name": reference_name or None,
		"item_code": item_code if item_code and frappe.db.exists("Item", item_code) else None})
	doc.insert(ignore_permissions=True)
	return doc.name


@frappe.whitelist()
def give_portal_login(customer, email, full_name=None, mobile=None):
	"""Sales side: create (or reuse) the customer's portal login and return a set-password link
	to send on WhatsApp — email may not be set up yet."""
	if not frappe.has_permission("Customer", "write", customer):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	email = (email or "").strip().lower()
	frappe.utils.validate_email_address(email, throw=True)
	if frappe.db.exists("User", email) and frappe.db.get_value("User", email, "user_type") == "System User":
		frappe.throw(_("{0} is a staff login — use the customer's own email.").format(email))
	name = full_name or frappe.db.get_value("Customer", customer, "customer_name")
	if not frappe.db.exists("User", email):
		user = frappe.get_doc({"doctype": "User", "email": email, "first_name": name[:140], "mobile_no": mobile,
			"user_type": "Website User", "send_welcome_email": 0, "roles": [{"role": "Customer"}]})
		user.flags.ignore_permissions = True
		user.insert()
	contact = frappe.db.get_value("Contact", {"email_id": email}, "name") or frappe.db.get_value("Contact", {"user": email}, "name")
	if contact:
		c = frappe.get_doc("Contact", contact)
	else:
		c = frappe.get_doc({"doctype": "Contact", "first_name": name[:140], "email_ids": [{"email_id": email, "is_primary": 1}]})
		if mobile:
			c.append("phone_nos", {"phone": mobile, "is_primary_mobile_no": 1})
	c.user = email
	if not any(l.link_doctype == "Customer" and l.link_name == customer for l in c.links):
		c.append("links", {"link_doctype": "Customer", "link_name": customer})
	c.flags.ignore_permissions = True
	c.save()
	user = frappe.get_doc("User", email)
	link = user._reset_password(send_email=False)  # returns the /update-password?key=… link
	frappe.get_doc("Customer", customer).add_comment("Info", _("Portal login given to {0}").format(email))
	return {"email": email, "link": link, "portal": frappe.utils.get_url("/portal")}


@frappe.whitelist()
def request_reorder(sales_order, note=None):
	customer = get_portal_customer()
	_own("Sales Order", sales_order, customer)
	return raise_ticket(_("Reorder of {0}").format(sales_order), note or _("Please repeat this order."), "Reorder Request", sales_order)
