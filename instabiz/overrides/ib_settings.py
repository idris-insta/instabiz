"""instabiz.overrides.ib_settings

Read business rules from the "Instabiz Settings" single doctype, falling back
to the value the code used before the setting existed. Every caller passes
its own old constant as the default, so an unsaved or half-filled settings
page never changes behaviour.
"""
import frappe
from frappe.utils import cint, flt

DOCTYPE = "Instabiz Settings"


def _doc():
	try:
		return frappe.get_cached_doc(DOCTYPE)
	except Exception:
		# table missing before the first migrate, or any read error: use defaults
		return None


def get(fieldname, default=None):
	doc = _doc()
	value = doc.get(fieldname) if doc else None
	return default if value in (None, "") else value


def get_int(fieldname, default):
	"""Positive integer setting; 0 / blank means 'not set', use the default."""
	value = cint(get(fieldname, 0))
	return value if value > 0 else default


def get_float(fieldname, default):
	value = flt(get(fieldname, 0))
	return value if value > 0 else default


def get_check(fieldname, default):
	"""Check setting. Falls back to the default only when the page has never
	been saved (no stored value at all)."""
	try:
		stored = frappe.db.sql(
			"SELECT value FROM `tabSingles` WHERE doctype=%s AND field=%s LIMIT 1", (DOCTYPE, fieldname)
		)
	except Exception:
		return bool(default)
	if not stored:
		return bool(default)
	return bool(cint(stored[0][0]))


def boot_session(bootinfo):
	"""Expose the few settings the browser needs (hooks.extend_bootinfo)."""
	from instabiz.overrides.advance_approval import advance_approvers

	try:
		bootinfo.ib_settings = {
			"advance_approvers": advance_approvers(),
			"default_delivery_days": get_int("default_delivery_days", 8),
			"whatsapp_mode": get("whatsapp_mode", "Free link (wa.me)"),
		}
	except Exception:
		bootinfo.ib_settings = {}
