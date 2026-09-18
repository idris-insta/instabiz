"""IB Day Book — every accounting voucher for a period, one line per voucher,
like Tally's Day Book: date, type, number, party, accounts touched, debit,
credit, narration. Cancelled entries are left out."""
import frappe
from frappe import _
from frappe.utils import flt, getdate, today


def execute(filters=None):
	filters = frappe._dict(filters or {})
	data = _data(filters)
	return _columns(), data, None, None, _summary(data)


def _columns():
	return [
		{"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 95},
		{"label": _("Voucher Type"), "fieldname": "voucher_type", "fieldtype": "Data", "width": 140},
		{"label": _("Voucher No"), "fieldname": "voucher_no", "fieldtype": "Dynamic Link", "options": "voucher_type", "width": 170},
		{"label": _("Party"), "fieldname": "party", "fieldtype": "Data", "width": 180},
		{"label": _("Accounts"), "fieldname": "accounts", "fieldtype": "Data", "width": 260},
		{"label": _("Debit"), "fieldname": "debit", "fieldtype": "Currency", "width": 120},
		{"label": _("Credit"), "fieldname": "credit", "fieldtype": "Currency", "width": 120},
		{"label": _("Narration"), "fieldname": "remarks", "fieldtype": "Data", "width": 260},
	]


def _data(filters):
	cond, args = "", {
		"company": filters.company or frappe.defaults.get_user_default("company"),
		"from": getdate(filters.from_date or today()),
		"to": getdate(filters.to_date or filters.from_date or today()),
	}
	if filters.voucher_type:
		cond += " AND voucher_type = %(voucher_type)s"
		args["voucher_type"] = filters.voucher_type
	if filters.party:
		cond += " AND party = %(party)s"
		args["party"] = filters.party
	return frappe.db.sql(
		f"""
		SELECT posting_date, voucher_type, voucher_no,
		       MAX(IF(IFNULL(party, '') != '', party, NULL)) AS party,
		       GROUP_CONCAT(DISTINCT SUBSTRING_INDEX(account, ' - ', 1) ORDER BY account SEPARATOR ', ') AS accounts,
		       SUM(debit) AS debit, SUM(credit) AS credit,
		       MAX(IFNULL(remarks, '')) AS remarks
		FROM `tabGL Entry`
		WHERE is_cancelled = 0 AND company = %(company)s
		  AND posting_date BETWEEN %(from)s AND %(to)s {cond}
		GROUP BY posting_date, voucher_type, voucher_no
		ORDER BY posting_date, creation
		""",
		args, as_dict=True,
	)


def _summary(data):
	debit = sum(flt(r.debit) for r in data)
	credit = sum(flt(r.credit) for r in data)
	return [
		{"label": _("Vouchers"), "value": len(data), "datatype": "Int"},
		{"label": _("Total Debit"), "value": debit, "datatype": "Currency"},
		{"label": _("Total Credit"), "value": credit, "datatype": "Currency",
			"indicator": "green" if abs(debit - credit) < 0.01 else "red"},
	]
