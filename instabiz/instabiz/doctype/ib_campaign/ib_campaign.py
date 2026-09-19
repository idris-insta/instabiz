"""IB Campaign — WhatsApp / email to a chosen group.

Build List fills the recipients from the filters (state, group, sales person,
quiet for N days, ordered recently, bought a family, has dues, or leads by
source / status). Send: email goes through the outgoing mail queue; WhatsApp
goes through the API when IB Messaging Settings is on API, otherwise each
sales person gets the list with ready wa.me links (the campaign form shows
them; a click marks the row sent). Results count the orders that followed
within the tracking days.
"""
from urllib.parse import quote

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, flt, getdate, now_datetime, today

from instabiz.overrides.messaging import _normalize_phone


class IBCampaign(Document):
	def validate(self):
		self.total_recipients = len(self.recipients)
		self.sent_count = sum(1 for r in self.recipients if r.status == "Sent")

	def render(self, r):
		ctx = frappe._dict(name=r.party_name or "", first_name=(r.party_name or "").split(" ")[0])
		sp = r.sales_person or frappe.db.get_value("Customer", r.party, "custom_sales_person_user") if r.party_type == "Customer" else r.sales_person
		ctx.sales_person = frappe.utils.get_fullname(sp) if sp else ""
		ctx.sales_person_phone = frappe.db.get_value("User", sp, "mobile_no") or "" if sp else ""
		if r.party_type == "Customer":
			last = frappe.db.get_value("Sales Order", {"customer": r.party, "docstatus": 1}, "transaction_date", order_by="transaction_date desc")
			ctx.last_order_date = frappe.utils.formatdate(last) if last else ""
			ctx.outstanding = frappe.utils.fmt_money(_outstanding(r.party), 0)
		else:
			ctx.last_order_date = ctx.outstanding = ""
		text = self.message or ""
		for k, v in ctx.items():
			text = text.replace("{" + k + "}", str(v or ""))
		if self.attachment:
			text += "\n" + frappe.utils.get_url(self.attachment)
		return text


def _outstanding(customer):
	from instabiz.overrides.portal import _outstanding as o

	return o(customer)


@frappe.whitelist()
def build_list(name):
	doc = frappe.get_doc("IB Campaign", name)
	doc.check_permission("write")
	have = {(r.party_type, r.party) for r in doc.recipients}
	added = 0
	if doc.audience in ("Customers", "Customers + Leads"):
		for c in _customers(doc):
			if ("Customer", c.name) not in have:
				doc.append("recipients", {"party_type": "Customer", "party": c.name, "party_name": c.customer_name,
					"phone": _normalize_phone(c.mobile_no), "email": c.email_id, "sales_person": c.custom_sales_person_user})
				added += 1
	if doc.audience in ("Leads", "Customers + Leads"):
		filters = {"status": ["!=", "Converted"]}
		if doc.lead_source:
			filters["source"] = doc.lead_source
		if doc.lead_status:
			filters["custom_status"] = doc.lead_status
		if doc.territory:
			filters["territory"] = doc.territory
		if doc.sales_person:
			filters["lead_owner"] = doc.sales_person
		for l in frappe.get_all("Lead", filters=filters, fields=["name", "lead_name", "company_name", "mobile_no", "email_id", "lead_owner"]):
			if ("Lead", l.name) not in have:
				doc.append("recipients", {"party_type": "Lead", "party": l.name, "party_name": l.company_name or l.lead_name,
					"phone": _normalize_phone(l.mobile_no), "email": l.email_id, "sales_person": l.lead_owner})
				added += 1
	doc.save()
	return added


def _customers(doc):
	cond, args = ["c.disabled = 0"], {}
	for key, sql in (("territory", "c.territory = %(territory)s"), ("customer_group", "c.customer_group = %(customer_group)s"),
			("sales_person", "c.custom_sales_person_user = %(sales_person)s")):
		if doc.get(key):
			cond.append(sql)
			args[key] = doc.get(key)
	last = "(SELECT MAX(so.transaction_date) FROM `tabSales Order` so WHERE so.customer = c.name AND so.docstatus = 1)"
	if cint(doc.no_order_days):
		cond.append(f"IFNULL({last}, '1900-01-01') < %(quiet)s")
		args["quiet"] = add_days(today(), -cint(doc.no_order_days))
	if cint(doc.ordered_within_days):
		cond.append(f"{last} >= %(recent)s")
		args["recent"] = add_days(today(), -cint(doc.ordered_within_days))
	if doc.bought_item_group:
		cond.append("""EXISTS (SELECT 1 FROM `tabSales Order Item` soi JOIN `tabSales Order` so2 ON so2.name = soi.parent
			WHERE so2.customer = c.name AND so2.docstatus = 1 AND soi.item_group = %(ig)s)""")
		args["ig"] = doc.bought_item_group
	rows = frappe.db.sql(f"""SELECT c.name, c.customer_name, c.mobile_no, c.email_id, c.custom_sales_person_user
		FROM `tabCustomer` c WHERE {' AND '.join(cond)} ORDER BY c.customer_name""", args, as_dict=True)
	if doc.with_outstanding:
		rows = [r for r in rows if _outstanding(r.name) > 0]
	return rows


@frappe.whitelist()
def send(name):
	"""Email + API WhatsApp now; free-link WhatsApp → returns the links for the browser."""
	from instabiz.overrides.ib_settings import get

	doc = frappe.get_doc("IB Campaign", name)
	doc.check_permission("write")
	wa = doc.channel in ("WhatsApp", "WhatsApp + Email")
	mail = doc.channel in ("Email", "WhatsApp + Email")
	api = get("whatsapp_mode", "Free link (wa.me)") == "API"
	links = []
	for r in doc.recipients:
		if r.status == "Sent":
			continue
		text = doc.render(r)
		ok, err = False, None
		try:
			if mail and r.email:
				frappe.sendmail(recipients=[r.email], subject=doc.subject or doc.campaign_name, message=text.replace("\n", "<br>"),
					reference_doctype="IB Campaign", reference_name=doc.name)
				ok = True
			if wa and r.phone:
				if api:
					from instabiz.overrides.messaging import _send_via_api
					_send_via_api(r.phone, text, doc)
					ok = True
				else:
					links.append({"row": r.name, "name": r.party_name, "sales_person": r.sales_person,
						"url": "https://wa.me/" + r.phone + "?text=" + quote(text, safe="")})
		except Exception as e:
			err = frappe.utils.strip_html(str(e))[:140]
		if ok:
			r.status, r.sent_on = "Sent", now_datetime()
		elif err:
			r.status, r.error = "Failed", err
		elif not (r.phone or r.email):
			r.status, r.error = "Skipped", _("no mobile / email")
	doc.status = "Sent" if not links else "Sending"
	doc.sent_on = doc.sent_on or today()
	doc.save()
	return {"links": links, "sent": doc.sent_count}


@frappe.whitelist()
def mark_sent(name, row):
	doc = frappe.get_doc("IB Campaign", name)
	doc.check_permission("write")
	for r in doc.recipients:
		if r.name == row:
			r.status, r.sent_on = "Sent", now_datetime()
	if all(r.status != "Pending" for r in doc.recipients):
		doc.status = "Sent"
	doc.save()


@frappe.whitelist()
def refresh_results(name):
	doc = frappe.get_doc("IB Campaign", name)
	if not doc.sent_on:
		return
	customers = [r.party for r in doc.recipients if r.party_type == "Customer" and r.status == "Sent"]
	leads = [r.party for r in doc.recipients if r.party_type == "Lead" and r.status == "Sent"]
	if leads:
		customers += frappe.get_all("Customer", filters={"lead_name": ["in", leads]}, pluck="name")
	end = add_days(doc.sent_on, cint(doc.track_days) or 30)
	row = frappe.db.sql("""SELECT COUNT(*), IFNULL(SUM(base_net_total), 0) FROM `tabSales Order`
		WHERE docstatus = 1 AND customer IN %s AND transaction_date BETWEEN %s AND %s""",
		(tuple(customers) or ("",), doc.sent_on, end))[0]
	frappe.db.set_value("IB Campaign", name, {"orders_after": row[0], "order_value_after": flt(row[1])}, update_modified=False)
	return {"orders": row[0], "value": flt(row[1])}
