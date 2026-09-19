"""IB Tally Export — preview of the vouchers that go into the Tally XML file:
Tally voucher type, party, debit/credit and whether it balances. The Download
button writes the file (instabiz.overrides.tally_export)."""
import frappe
from frappe import _

from instabiz.overrides.tally_export import ROLES, vouchers


def execute(filters=None):
	f = frappe._dict(filters or {})
	frappe.only_for(ROLES)
	f.company = f.company or frappe.defaults.get_user_default("Company") or frappe.db.get_single_value("Global Defaults", "default_company")
	f.from_date = f.from_date or frappe.utils.get_first_day(frappe.utils.today())
	f.to_date = f.to_date or frappe.utils.today()
	vs, led = vouchers(f.company, f.from_date, f.to_date, [f.voucher_type] if f.voucher_type else None)
	data = []
	for no, v in vs.items():
		dr = sum(a for a in v.lines.values() if a > 0)
		data.append({"date": v.date, "doctype": v.doctype, "voucher": no, "tally_type": v.tally_type,
			"party": v.party, "lines": len(v.lines), "amount": dr,
			"status": _("Balanced") if abs(v.balance) <= 0.01 else _("Off by {0}").format(v.balance)})
	cols = [
		{"label": _("Date"), "fieldname": "date", "fieldtype": "Date", "width": 95},
		{"label": _("Doctype"), "fieldname": "doctype", "fieldtype": "Data", "hidden": 1},
		{"label": _("Voucher"), "fieldname": "voucher", "fieldtype": "Dynamic Link", "options": "doctype", "width": 190},
		{"label": _("Tally Type"), "fieldname": "tally_type", "fieldtype": "Data", "width": 90},
		{"label": _("Party Ledger"), "fieldname": "party", "fieldtype": "Data", "width": 220},
		{"label": _("Ledger Lines"), "fieldname": "lines", "fieldtype": "Int", "width": 90},
		{"label": _("Amount"), "fieldname": "amount", "fieldtype": "Currency", "width": 130},
		{"label": _("Check"), "fieldname": "status", "fieldtype": "Data", "width": 110},
	]
	bad = sum(1 for d in data if d["status"] != _("Balanced"))
	summary = [
		{"label": _("Vouchers"), "value": len(data), "datatype": "Int"},
		{"label": _("Ledgers"), "value": len(led.groups), "datatype": "Int"},
		{"label": _("Not balanced (left out)"), "value": bad, "datatype": "Int", "indicator": "red" if bad else "green"},
	]
	return cols, data, None, None, summary
