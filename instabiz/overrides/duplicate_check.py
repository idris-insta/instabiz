"""instabiz.overrides.duplicate_check

Warns (does not block) when a purchase bill or a payment looks like one already
entered, and lists every suspected pair in the IB Duplicate Check report.

  Purchase Invoice — same supplier + same bill no (ignoring case / spaces / -/),
                     or same supplier + same total within 3 days.
  Payment Entry    — same party + same amount + same direction within 3 days,
                     or same party + same reference / UTR no.
"""
import re

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate

WINDOW_DAYS = 3


def _norm(s):
	return re.sub(r"[\s\-/\\.]", "", (s or "").upper())


def _link(dt, name):
	return f'<a href="/app/{frappe.scrub(dt).replace("_", "-")}/{name}">{name}</a>'


def pi_matches(doc):
	if doc.is_return or not doc.supplier:
		return []
	out = []
	if doc.bill_no:
		for r in frappe.get_all("Purchase Invoice", filters={"supplier": doc.supplier, "docstatus": ["!=", 2],
				"name": ["!=", doc.name or ""], "is_return": 0, "bill_no": ["is", "set"]}, fields=["name", "bill_no"]):
			if _norm(r.bill_no) == _norm(doc.bill_no):
				out.append((r.name, _("same bill no {0}").format(r.bill_no)))
	day = getdate(doc.bill_date or doc.posting_date)
	if flt(doc.grand_total) > 0:
		for r in frappe.get_all("Purchase Invoice", filters={"supplier": doc.supplier, "docstatus": ["!=", 2],
				"name": ["!=", doc.name or ""], "is_return": 0, "grand_total": flt(doc.grand_total),
				"posting_date": ["between", [add_days(day, -WINDOW_DAYS), add_days(day, WINDOW_DAYS)]]}, pluck="name"):
			if r not in [m[0] for m in out]:
				out.append((r, _("same amount within {0} days").format(WINDOW_DAYS)))
	return out


def pe_matches(doc):
	if not doc.party or flt(doc.paid_amount) <= 0:
		return []
	out = []
	base = {"party": doc.party, "party_type": doc.party_type, "docstatus": ["!=", 2], "name": ["!=", doc.name or ""]}
	day = getdate(doc.posting_date)
	for r in frappe.get_all("Payment Entry", filters={**base, "payment_type": doc.payment_type, "paid_amount": flt(doc.paid_amount),
			"posting_date": ["between", [add_days(day, -WINDOW_DAYS), add_days(day, WINDOW_DAYS)]]}, pluck="name"):
		out.append((r, _("same amount within {0} days").format(WINDOW_DAYS)))
	ref = _norm(doc.reference_no)
	if ref and ref not in ("CASH", "NA", "NIL"):
		for r in frappe.get_all("Payment Entry", filters={**base, "reference_no": ["is", "set"]}, fields=["name", "reference_no"]):
			if _norm(r.reference_no) == ref and r.name not in [m[0] for m in out]:
				out.append((r.name, _("same reference no {0}").format(r.reference_no)))
	return out


def _warn(doc, matches):
	if not matches or doc.flags.ignore_duplicate_warning:
		return
	lines = "<br>".join(f"{_link(doc.doctype, n)} — {why}" for n, why in matches[:5])
	frappe.msgprint(_("This may be a duplicate of:<br>{0}").format(lines), title=_("Possible duplicate"), indicator="orange")


def warn_purchase_invoice(doc, method=None):
	_warn(doc, pi_matches(doc))


def warn_payment_entry(doc, method=None):
	_warn(doc, pe_matches(doc))
