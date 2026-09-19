"""IB Dormant Accounts — ledgers, customers or suppliers with no entry for N days.

Shows the last entry date, days quiet and today's balance, so money stuck in a
quiet ledger (an old customer balance, a supplier advance, a suspense account)
is easy to find. Zero-balance ledgers are left out unless asked for.
"""
import frappe
from frappe import _
from frappe.utils import add_days, date_diff, flt, today


def execute(filters=None):
	f = frappe._dict(filters or {})
	days = int(f.days or 180)
	cutoff = add_days(today(), -days)
	kind = f.kind or "Ledgers"
	company = f.company or frappe.defaults.get_user_default("Company")
	if kind == "Ledgers":
		rows = frappe.db.sql("""SELECT gle.account AS name, a.account_type AS type, a.root_type AS root,
			MAX(gle.posting_date) AS last_date, SUM(gle.debit - gle.credit) AS balance
			FROM `tabGL Entry` gle JOIN `tabAccount` a ON a.name = gle.account
			WHERE gle.company = %s AND gle.is_cancelled = 0 AND a.root_type IN ('Asset', 'Liability')
			GROUP BY gle.account HAVING MAX(gle.posting_date) < %s""", (company, cutoff), as_dict=True)
		link = "Account"
	else:
		party_type = "Customer" if kind == "Customers" else "Supplier"
		rows = frappe.db.sql("""SELECT gle.party AS name, %s AS type, '' AS root, MAX(gle.posting_date) AS last_date,
			SUM(gle.debit - gle.credit) AS balance FROM `tabGL Entry` gle
			WHERE gle.company = %s AND gle.is_cancelled = 0 AND gle.party_type = %s
			GROUP BY gle.party HAVING MAX(gle.posting_date) < %s""", (party_type, company, party_type, cutoff), as_dict=True)
		link = party_type
		names = {r.name for r in rows}
		label = "customer_name" if party_type == "Customer" else "supplier_name"
		display = {d.name: d.get(label) for d in frappe.get_all(party_type, filters={"name": ["in", list(names) or [""]]},
			fields=["name", label])}
		for r in rows:
			r.display = display.get(r.name)
	if not f.include_zero:
		rows = [r for r in rows if abs(flt(r.balance)) >= 1]
	if flt(f.min_balance):
		rows = [r for r in rows if abs(flt(r.balance)) >= flt(f.min_balance)]
	for r in rows:
		r.days_quiet = date_diff(today(), r.last_date)
		r.debit_balance = flt(r.balance) if flt(r.balance) > 0 else 0
		r.credit_balance = -flt(r.balance) if flt(r.balance) < 0 else 0
	rows.sort(key=lambda r: -abs(flt(r.balance)))
	cols = [{"label": _(kind[:-1] if kind != "Ledgers" else "Ledger"), "fieldname": "name", "fieldtype": "Link", "options": link, "width": 240}]
	if kind != "Ledgers":
		cols.append({"label": _("Name"), "fieldname": "display", "fieldtype": "Data", "width": 220})
	else:
		cols.append({"label": _("Type"), "fieldname": "type", "fieldtype": "Data", "width": 120})
	cols += [{"label": _("Last Entry"), "fieldname": "last_date", "fieldtype": "Date", "width": 100},
		{"label": _("Days Quiet"), "fieldname": "days_quiet", "fieldtype": "Int", "width": 90},
		{"label": _("Debit Balance"), "fieldname": "debit_balance", "fieldtype": "Currency", "width": 130},
		{"label": _("Credit Balance"), "fieldname": "credit_balance", "fieldtype": "Currency", "width": 130}]
	summary = [{"label": _("Quiet for {0}+ days").format(days), "value": len(rows), "datatype": "Int"},
		{"label": _("Money sitting (debit)"), "value": sum(r.debit_balance for r in rows), "datatype": "Currency"},
		{"label": _("Money sitting (credit)"), "value": sum(r.credit_balance for r in rows), "datatype": "Currency"}]
	return cols, rows, None, None, summary
