"""instabiz.overrides.messaging

Send a document to its customer / supplier by WhatsApp or email, worded from
an IB Message Template.

WhatsApp has two modes (Instabiz Settings -> Messaging):
  - Free link (wa.me): the browser opens WhatsApp with the text filled in and
    the user presses Send. No account or API needed. This is the default.
  - API: the message is posted to a WhatsApp Business API endpoint. Only the
    connection fields exist today; fill them when a provider is chosen.

Email uses the site's outgoing Email Account through Frappe's own composer, so
it starts working as soon as SMTP is configured.

A document goes out as a PDF download link. The link carries a Document Share
Key that expires after "PDF Link Valid For (Days)", so the customer can open it
without logging in, and only for that one document.
"""
import re
from urllib.parse import quote, urlencode

import frappe
from frappe import _
from frappe.utils import add_days, fmt_money, formatdate, get_url, today
from frappe.utils.jinja import render_template

from instabiz.overrides.ib_settings import get, get_int

SUPPORTED_DOCTYPES = (
	"Quotation", "Sales Order", "Delivery Note", "Sales Invoice",
	"Payment Entry", "Customer", "Purchase Order",
)

_PARTY_LINK = {
	"Quotation": ("Customer", "party_name"),
	"Sales Order": ("Customer", "customer"),
	"Delivery Note": ("Customer", "customer"),
	"Sales Invoice": ("Customer", "customer"),
	"Purchase Order": ("Supplier", "supplier"),
}


# ── lookups ────────────────────────────────────────────────────────────────────

def _party(doc):
	if doc.doctype == "Customer":
		return "Customer", doc.name
	if doc.doctype == "Payment Entry":
		return doc.party_type, doc.party
	party_type, field = _PARTY_LINK.get(doc.doctype, (None, None))
	if doc.doctype == "Quotation" and doc.get("quotation_to") != "Customer":
		return None, None
	return party_type, doc.get(field) if field else None


def party_name(doc):
	for field in ("customer_name", "supplier_name", "party_name", "title"):
		if doc.get(field) and not (doc.doctype == "Quotation" and field == "party_name"):
			return doc.get(field)
	party_type, party = _party(doc)
	if party_type and party:
		label = "customer_name" if party_type == "Customer" else "supplier_name"
		return frappe.db.get_value(party_type, party, label) or party
	return doc.get("party_name") or ""


def _normalize_phone(raw):
	digits = re.sub(r"\D", "", raw or "")
	if not digits:
		return ""
	code = re.sub(r"\D", "", get("whatsapp_country_code", "91") or "91")
	if digits.startswith("00"):
		digits = digits[2:]
	if len(digits) == 11 and digits.startswith("0"):
		digits = digits[1:]
	if len(digits) == 10:
		digits = code + digits
	return digits


def party_phone(doc):
	for field in ("contact_mobile", "mobile_no", "contact_phone", "phone"):
		if doc.get(field):
			return _normalize_phone(doc.get(field))
	party_type, party = _party(doc)
	if party_type in ("Customer", "Supplier") and party:
		mobile = frappe.db.get_value(party_type, party, "mobile_no")
		if mobile:
			return _normalize_phone(mobile)
	return ""


def party_email(doc):
	for field in ("contact_email", "email_id"):
		if doc.get(field):
			return doc.get(field)
	party_type, party = _party(doc)
	if party_type in ("Customer", "Supplier") and party:
		return frappe.db.get_value(party_type, party, "email_id") or ""
	return ""


# ── templates ──────────────────────────────────────────────────────────────────

def _templates(doctype, channel):
	return frappe.get_all(
		"IB Message Template",
		filters={"reference_doctype": doctype, "channel": channel, "enabled": 1},
		fields=["name", "is_default"],
		order_by="is_default desc, modified desc",
	)


def _default_print_format(doctype):
	return frappe.get_meta(doctype).default_print_format or "Standard"


def pdf_link(doc, print_format=None):
	days = get_int("pdf_link_valid_days", 30)
	key = doc.get_document_share_key(expires_on=add_days(today(), days))
	fmt = print_format or _default_print_format(doc.doctype)
	query = urlencode({
		"doctype": doc.doctype, "name": doc.name, "format": fmt, "no_letterhead": 1, "key": key,
	})
	return get_url(f"/api/method/frappe.utils.print_format.download_pdf?{query}")


def _context(doc, tpl):
	sender = frappe.get_cached_doc("User", frappe.session.user)
	return {
		"doc": doc,
		"party_name": party_name(doc),
		"company": doc.get("company") or frappe.defaults.get_global_default("company"),
		"sender": sender.full_name,
		"sender_phone": sender.mobile_no or sender.phone or "",
		"pdf_link": pdf_link(doc, tpl.print_format) if tpl and tpl.attach_pdf else "",
		"amount": lambda v, currency=None: fmt_money(v or 0, currency=currency or doc.get("currency") or "INR"),
		"date": lambda d: formatdate(d, "dd-MM-yyyy") if d else "",
	}


def _check(doctype, name):
	if doctype not in SUPPORTED_DOCTYPES:
		frappe.throw(_("Sending is not set up for {0}.").format(doctype))
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	# a share key is created per send; sharing needs more than just read
	if not (frappe.has_permission(doctype, "print", doc) or frappe.has_permission(doctype, "email", doc)):
		frappe.throw(_("You cannot share this {0}.").format(doctype), frappe.PermissionError)
	return doc


@frappe.whitelist()
def get_message(doctype, name, channel="WhatsApp", template=None):
	"""Rendered message + recipient for the Send dialog."""
	doc = _check(doctype, name)
	templates = _templates(doctype, channel)
	chosen = template or (templates[0].name if templates else None)
	tpl = frappe.get_doc("IB Message Template", chosen) if chosen else None
	ctx = _context(doc, tpl)
	if tpl:
		message = render_template(tpl.message, ctx)
		subject = render_template(tpl.subject or "", ctx) if tpl.subject else f"{doctype} {name}"
	else:
		message = f"Dear {ctx['party_name']},\n{doctype} {name}.\n{pdf_link(doc)}"
		subject = f"{doctype} {name}"
	return {
		"templates": [t.name for t in templates],
		"template": chosen,
		"message": message.strip(),
		"subject": subject,
		"phone": party_phone(doc),
		"email": party_email(doc),
		"print_format": (tpl.print_format if tpl and tpl.print_format else _default_print_format(doctype)),
		"attach_pdf": bool(tpl.attach_pdf) if tpl else True,
		"mode": get("whatsapp_mode", "Free link (wa.me)"),
	}


@frappe.whitelist()
def send_whatsapp(doctype, name, phone, message):
	"""Free-link mode: return the wa.me URL for the browser to open.
	API mode: post to the configured endpoint. Both log on the timeline."""
	doc = _check(doctype, name)
	number = _normalize_phone(phone)
	if not number:
		frappe.throw(_("Enter a mobile number."))
	mode = get("whatsapp_mode", "Free link (wa.me)")
	if mode == "API":
		_send_via_api(number, message, doc)
		_log(doc, f"WhatsApp sent to +{number} (API)", message)
		return {"sent": True}
	_log(doc, f"WhatsApp opened for +{number}", message)
	return {"url": "https://wa.me/" + number + "?text=" + quote(message, safe="")}


def _send_via_api(number, message, doc):
	import requests

	url = get("wa_api_url")
	if not url:
		frappe.throw(_("WhatsApp API is not configured. Fill the API section in Instabiz Settings, or switch Sending Mode to Free link."))
	settings = frappe.get_single("Instabiz Settings")
	token = settings.get_password("wa_api_token", raise_exception=False) or ""
	payload = {"to": number, "from": get("wa_sender_number", ""), "message": message,
		"reference_doctype": doc.doctype, "reference_name": doc.name}
	try:
		response = requests.post(url, json=payload, timeout=15,
			headers={"Authorization": f"Bearer {token}"} if token else {})
		response.raise_for_status()
	except Exception as e:
		frappe.log_error("IB WhatsApp API send failed", frappe.get_traceback())
		frappe.throw(_("WhatsApp API did not accept the message: {0}").format(str(e)[:200]))


def _log(doc, title, message):
	doc.add_comment("Info", f"{title}: {frappe.utils.escape_html(message[:500])}")
