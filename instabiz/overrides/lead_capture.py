"""instabiz.overrides.lead_capture

New enquiries straight into Leads, from:
  * IndiaMART — the CRM listing API is pulled every 15 minutes (IB Lead Capture
    Settings holds the key); each enquiry's UNIQUE_QUERY_ID is kept on the Lead
    so a pull never creates it twice.
  * the website / any other site — web_lead() takes a POST with the capture token.

A Lead with the same mobile or email already exists → the enquiry goes on that
Lead's timeline and its owner gets a bell notification, instead of the duplicate
block the normal Lead form raises. New leads go through the usual Lead hooks
(territory from GSTIN/pincode, score, round-robin when it is on).
"""
import json
import re
from datetime import timedelta

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import cint, get_datetime, now_datetime

SETTINGS = "IB Lead Capture Settings"
IM_URL = "https://mapi.indiamart.com/wservce/crm/crmListing/v2/"
SOURCES = ("IndiaMART", "Website", "JustDial", "TradeIndia", "Meta Ads", "Google Ads")


# ── shared ────────────────────────────────────────────────────────────────────

def _mobile(raw):
	digits = re.sub(r"\D", "", raw or "")
	if len(digits) > 10 and digits.startswith("91"):
		digits = digits[2:]
	return digits[-10:] if len(digits) >= 10 else digits


def _territory(state, pincode=None):
	settings = frappe.get_cached_doc(SETTINGS)
	state = (state or "").strip()
	if state:
		hit = frappe.db.get_value("Territory", {"name": state}) or frappe.db.get_value(
			"Territory", {"territory_name": ["like", state]})
		if hit:
			return hit
	return settings.default_territory or None


def _existing(mobile, email):
	if mobile:
		name = frappe.db.get_value("Lead", {"mobile_no": mobile})
		if name:
			return name
	if email:
		return frappe.db.get_value("Lead", {"email_id": email})
	return None


def _enquiry_text(e):
	parts = [e.get("product") and f"Product: {e['product']}", e.get("message"),
		e.get("city") and f"City: {e['city']}", e.get("ref") and f"Ref: {e['ref']}"]
	return "\n".join(p for p in parts if p)


def capture(e):
	"""e: dict(source, ref, name, mobile, email, company, city, state, pincode, product, message, when).
	Returns ("created"|"updated"|"skipped", lead name)."""
	if e.get("ref") and frappe.db.exists("Lead", {"custom_capture_ref": e["ref"]}):
		return "skipped", frappe.db.get_value("Lead", {"custom_capture_ref": e["ref"]})
	mobile, email = _mobile(e.get("mobile")), (e.get("email") or "").strip().lower() or None
	if not mobile and not email:
		return "skipped", None
	text = _enquiry_text(e)
	dup = _existing(mobile, email)
	if dup:
		lead = frappe.get_doc("Lead", dup)
		lead.add_comment("Info", _("New {0} enquiry: {1}").format(e.get("source") or "", text or "-"))
		if lead.lead_owner:
			frappe.get_doc({"doctype": "Notification Log", "for_user": lead.lead_owner, "type": "Alert",
				"subject": _("{0} enquired again via {1}").format(lead.company_name or lead.first_name or dup, e.get("source")),
				"document_type": "Lead", "document_name": dup}).insert(ignore_permissions=True)
		return "updated", dup

	settings = frappe.get_cached_doc(SETTINGS)
	lead = frappe.new_doc("Lead")
	lead.first_name = (e.get("name") or e.get("company") or mobile or email)[:140]
	lead.company_name = e.get("company") or None
	lead.mobile_no = mobile or None
	lead.email_id = email
	lead.city = e.get("city") or None
	lead.custom_pincode = (e.get("pincode") or "").strip() or None
	lead.source = e.get("source") if frappe.db.exists("Lead Source", e.get("source")) else None
	lead.custom_capture_ref = e.get("ref") or None
	lead.custom_enquiry = text or None
	lead.custom_lead_temperature = "Warm"
	# state name → Territory; with only a pincode the Lead hook looks it up; neither → the default
	if e.get("state") or not lead.custom_pincode:
		lead.territory = _territory(e.get("state"))
	if settings.default_owner and not cint(frappe.conf.get("ib_lead_round_robin_enabled", 0)):
		lead.lead_owner = settings.default_owner
	# territory is mandatory on the form; an enquiry with no state/pincode and no default still gets in
	lead.flags.ignore_mandatory = not lead.territory and not lead.custom_pincode
	lead.insert(ignore_permissions=True)
	if text:
		lead.add_comment("Info", _("{0} enquiry: {1}").format(e.get("source") or "", text))
	if lead.lead_owner and lead.lead_owner != "Administrator":
		frappe.get_doc({"doctype": "Notification Log", "for_user": lead.lead_owner, "type": "Alert",
			"subject": _("New {0} enquiry: {1}").format(e.get("source"), lead.first_name),
			"document_type": "Lead", "document_name": lead.name}).insert(ignore_permissions=True)
	return "created", lead.name


# ── IndiaMART ─────────────────────────────────────────────────────────────────

def _im_time(dt):
	return dt.strftime("%d-%b-%Y%H:%M:%S")


def _im_row(r):
	return {
		"source": "IndiaMART", "ref": f"IM-{r.get('UNIQUE_QUERY_ID')}",
		"name": r.get("SENDER_NAME"), "mobile": r.get("SENDER_MOBILE") or r.get("SENDER_MOBILE_ALT"),
		"email": r.get("SENDER_EMAIL") or r.get("SENDER_EMAIL_ALT"), "company": r.get("SENDER_COMPANY"),
		"city": r.get("SENDER_CITY"), "state": r.get("SENDER_STATE"), "pincode": r.get("SENDER_PINCODE"),
		"product": r.get("QUERY_PRODUCT_NAME") or r.get("SUBJECT"), "message": r.get("QUERY_MESSAGE"),
	}


def pull_indiamart(manual=False):
	"""Scheduler (every 15 min) and the 'Pull now' button. IndiaMART allows a window of
	at most 7 days and one call every 5 minutes."""
	import requests

	settings = frappe.get_doc(SETTINGS)
	if not cint(settings.enable_indiamart):
		return {"message": _("IndiaMART pull is off.")}
	key = settings.get_password("indiamart_key", raise_exception=False)
	if not key:
		return {"message": _("IndiaMART CRM key is not set.")}
	end = now_datetime()
	start = get_datetime(settings.indiamart_last_pull) if settings.indiamart_last_pull else end - timedelta(days=1)
	start = max(start, end - timedelta(days=7))
	try:
		resp = requests.get(IM_URL, params={"glusr_crm_key": key, "start_time": _im_time(start),
			"end_time": _im_time(end)}, timeout=30)
		data = resp.json()
	except Exception as exc:
		_note(settings, f"Failed: {str(exc)[:200]}", None)
		return {"message": _("IndiaMART did not answer: {0}").format(str(exc)[:200])}
	code = cint(data.get("CODE"))
	if code != 200:
		# 204 = nothing new in the window; anything else is an error (bad key, too frequent)
		msg = data.get("MESSAGE") or data.get("STATUS") or str(code)
		_note(settings, f"{code}: {msg}", end if code == 204 else None)
		return {"message": msg}
	counts = {"created": 0, "updated": 0, "skipped": 0}
	for r in data.get("RESPONSE") or []:
		try:
			outcome, _name = capture(_im_row(r))
			counts[outcome] += 1
		except Exception:
			frappe.log_error("IndiaMART lead", f"{json.dumps(r)[:2000]}\n{frappe.get_traceback()}")
			counts["skipped"] += 1
	_note(settings, "New {created}, repeat {updated}, skipped {skipped}".format(**counts), end)
	return {"message": _("New {0}, repeat enquiries {1}, skipped {2}").format(counts["created"], counts["updated"], counts["skipped"])}


def _note(settings, text, pulled_to):
	values = {"indiamart_last_result": f"{now_datetime():%d-%m %H:%M} {text}"}
	if pulled_to:
		values["indiamart_last_pull"] = pulled_to
	for k, v in values.items():
		frappe.db.set_single_value(SETTINGS, k, v)
	frappe.db.commit()


@frappe.whitelist()
def pull_now():
	frappe.only_for(("System Manager", "Sales Manager"))
	return pull_indiamart(manual=True)


# ── website / other sources ───────────────────────────────────────────────────

@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=30, seconds=3600)
def web_lead(token=None, name=None, mobile=None, email=None, company=None, city=None, state=None,
		pincode=None, product=None, message=None, source=None, website=None):
	"""Enquiry form on the website (or any other site) → Lead. `website` is a honeypot."""
	settings = frappe.get_cached_doc(SETTINGS)
	if not cint(settings.enable_web) or not settings.web_token or token != settings.web_token:
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	if website:
		return {"ok": True}
	source = source if source in SOURCES else "Website"
	outcome, lead = capture({"source": source, "name": name, "mobile": mobile, "email": email,
		"company": company, "city": city, "state": state, "pincode": pincode,
		"product": product, "message": (message or "")[:2000]})
	frappe.db.commit()
	return {"ok": outcome != "skipped"}


@frappe.whitelist()
def new_token():
	frappe.only_for(("System Manager", "Sales Manager"))
	token = frappe.generate_hash(length=24)
	frappe.db.set_single_value(SETTINGS, "web_token", token)
	return token


# ── setup ─────────────────────────────────────────────────────────────────────

def after_migrate():
	for src in SOURCES:
		if not frappe.db.exists("Lead Source", src):
			frappe.get_doc({"doctype": "Lead Source", "source_name": src}).insert(ignore_permissions=True)
	for fieldname, spec in {
		"custom_capture_ref": {"label": "Capture Ref", "fieldtype": "Data", "read_only": 1, "hidden": 1,
			"search_index": 1, "insert_after": "source", "no_copy": 1},
		"custom_enquiry": {"label": "Enquiry", "fieldtype": "Small Text", "read_only": 1,
			"insert_after": "custom_remark", "no_copy": 1},
	}.items():
		if not frappe.db.exists("Custom Field", {"dt": "Lead", "fieldname": fieldname}):
			frappe.get_doc({"doctype": "Custom Field", "dt": "Lead", "fieldname": fieldname, **spec}).insert(ignore_permissions=True)
