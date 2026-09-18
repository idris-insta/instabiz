"""instabiz.overrides.ib_settings

Business rules live on one settings page per module (single doctypes):
IB Sales / Accounts / Stock / HR / Print / Messaging Settings. Code asks for a
field by name; ib_settings_fields.json (written by the generator together
with the doctypes) says which page holds it. Every caller passes the value
the code used before the setting existed, so an unsaved page changes nothing.
"""
import json
import os

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

_FIELD_MAP = None


def _field_map():
	global _FIELD_MAP
	if _FIELD_MAP is None:
		with open(os.path.join(os.path.dirname(__file__), "ib_settings_fields.json")) as f:
			_FIELD_MAP = json.load(f)
	return _FIELD_MAP


def doctype_for(fieldname):
	return _field_map().get(fieldname)


def _stored(fieldname):
	"""(found, value) straight from tabSingles; found=False when never saved."""
	doctype = doctype_for(fieldname)
	if not doctype:
		return False, None
	try:
		doc = frappe.get_cached_doc(doctype)
	except Exception:
		return False, None
	value = doc.get(fieldname)
	return value not in (None, ""), value


def get(fieldname, default=None):
	found, value = _stored(fieldname)
	return value if found else default


def get_int(fieldname, default):
	"""Positive integer setting; 0 / blank means 'not set', use the default."""
	value = cint(get(fieldname, 0))
	return value if value > 0 else default


def get_float(fieldname, default):
	value = flt(get(fieldname, 0))
	return value if value > 0 else default


def get_check(fieldname, default):
	"""Check setting; falls back to the default only when the page was never saved."""
	doctype = doctype_for(fieldname)
	if not doctype:
		return bool(default)
	try:
		row = frappe.db.sql(
			"SELECT value FROM `tabSingles` WHERE doctype=%s AND field=%s LIMIT 1", (doctype, fieldname)
		)
	except Exception:
		return bool(default)
	return bool(cint(row[0][0])) if row else bool(default)


def get_password(fieldname):
	doctype = doctype_for(fieldname)
	if not doctype:
		return ""
	return frappe.get_single(doctype).get_password(fieldname, raise_exception=False) or ""


class ModuleSettings(Document):
	"""Shared checks for the IB * Settings pages."""

	def validate(self):
		n1, n2, n3 = (self.get("dormant_notice_1_days"), self.get("dormant_notice_2_days"),
			self.get("dormant_reassign_days"))
		if n1 and n2 and n3 and not (n1 < n2 < n3):
			frappe.throw(_("Dormant notice days must increase: first notice < second notice < reassign."))
		for field in ("ot_hours_per_day", "ot_rate_multiplier", "late_payment_interest_pct"):
			if self.meta.has_field(field) and flt(self.get(field)) < 0:
				frappe.throw(_("{0} cannot be negative.").format(self.meta.get_label(field)))

	def on_update(self):
		before = self.get_doc_before_save()
		if self.meta.has_field("ot_day_basis") and before and any(
			before.get(f) != self.get(f) for f in ("ot_day_basis", "ot_hours_per_day")
		):
			from instabiz.overrides.overtime import refresh_assignment_rates

			frappe.enqueue(refresh_assignment_rates, queue="short", enqueue_after_commit=True)


def boot_session(bootinfo):
	"""Expose the few settings the browser needs (hooks.extend_bootinfo)."""
	try:
		from instabiz.overrides.advance_approval import advance_approvers

		bootinfo.ib_settings = {
			"advance_approvers": advance_approvers(),
			"default_delivery_days": get_int("default_delivery_days", 8),
			"quotation_validity_days": get_int("quotation_validity_days", 30),
			"whatsapp_mode": get("whatsapp_mode", "Free link (wa.me)"),
		}
	except Exception:
		bootinfo.ib_settings = {}
