"""IB Payment Register — customer receipts and vendor / other payments.

Every submitted Payment Entry for the dates, or grouped by party, mode,
bank account, branch, sales person, day or month. Filters: direction, party
type, party, mode of payment, bank account, branch, sales person, min amount.
"""
import frappe
from frappe import _
from frappe.utils import flt

GROUPS = {"Party": "party_name", "Mode of Payment": "mode_of_payment", "Bank / Cash Account": "bank",
	"Branch": "branch", "Sales Person": "sales_person", "Day": "posting_date", "Month": "month"}


def execute(filters=None):
	f = frappe._dict(filters or {})
	rows = _rows(f)
	if f.group_by and f.group_by in GROUPS:
		return _grouped(rows, f.group_by)
	cols = [
		{"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 95},
		{"label": _("Entry"), "fieldname": "name", "fieldtype": "Link", "options": "Payment Entry", "width": 165},
		{"label": _("Type"), "fieldname": "payment_type", "fieldtype": "Data", "width": 80},
		{"label": _("Party"), "fieldname": "party_name", "fieldtype": "Data", "width": 200},
		{"label": _("Mode"), "fieldname": "mode_of_payment", "fieldtype": "Data", "width": 100},
		{"label": _("Bank / Cash"), "fieldname": "bank", "fieldtype": "Data", "width": 170},
		{"label": _("Ref / UTR"), "fieldname": "reference_no", "fieldtype": "Data", "width": 120},
		{"label": _("Received"), "fieldname": "received", "fieldtype": "Currency", "width": 120},
		{"label": _("Paid"), "fieldname": "paid", "fieldtype": "Currency", "width": 120},
		{"label": _("Against"), "fieldname": "against", "fieldtype": "Data", "width": 200},
		{"label": _("Branch"), "fieldname": "branch", "fieldtype": "Data", "width": 90},
		{"label": _("Sales Person"), "fieldname": "sales_person", "fieldtype": "Data", "width": 130},
	]
	return cols, rows, None, _chart(rows), _summary(rows)


def _rows(f):
	cond, args = ["pe.docstatus = 1", "pe.posting_date BETWEEN %(from_date)s AND %(to_date)s"], {"from_date": f.from_date, "to_date": f.to_date}
	direction = {"Receipts": "Receive", "Payments": "Pay", "Internal Transfer": "Internal Transfer"}.get(f.direction)
	if direction:
		cond.append("pe.payment_type = %(pt)s")
		args["pt"] = direction
	for key, sql in (("party_type", "pe.party_type = %(party_type)s"), ("party", "pe.party = %(party)s"),
			("mode_of_payment", "pe.mode_of_payment = %(mode_of_payment)s"),
			("account", "(pe.paid_to = %(account)s OR pe.paid_from = %(account)s)")):
		if f.get(key):
			cond.append(sql)
			args[key] = f.get(key)
	has_branch = frappe.db.has_column("Payment Entry", "branch")
	if f.branch and has_branch:
		cond.append("pe.branch = %(branch)s")
		args["branch"] = f.branch
	if f.sales_person:
		cond.append("c.custom_sales_person_user = %(sp)s")
		args["sp"] = f.sales_person
	if flt(f.min_amount):
		cond.append("pe.paid_amount >= %(min)s")
		args["min"] = flt(f.min_amount)
	rows = frappe.db.sql(
		f"""SELECT pe.name, pe.posting_date, pe.payment_type, pe.party_type, pe.party, pe.party_name, pe.mode_of_payment,
		       pe.reference_no, pe.paid_amount, pe.base_paid_amount, pe.base_received_amount,
		       IF(pe.payment_type = 'Receive', pe.paid_to, pe.paid_from) AS bank,
		       {'pe.branch' if has_branch else "''"} AS branch, c.custom_sales_person AS sales_person,
		       DATE_FORMAT(pe.posting_date, '%%Y-%%m') AS month,
		       (SELECT GROUP_CONCAT(DISTINCT per.reference_name SEPARATOR ', ') FROM `tabPayment Entry Reference` per
		        WHERE per.parent = pe.name) AS against
		FROM `tabPayment Entry` pe
		LEFT JOIN `tabCustomer` c ON pe.party_type = 'Customer' AND c.name = pe.party
		WHERE {' AND '.join(cond)} ORDER BY pe.posting_date, pe.name""", args, as_dict=True)
	for r in rows:
		r.received = flt(r.base_received_amount) if r.payment_type == "Receive" else 0
		r.paid = flt(r.base_paid_amount) if r.payment_type == "Pay" else 0
		r.bank = (r.bank or "").rsplit(" - ", 1)[0]
	return rows


def _grouped(rows, group_by):
	key = GROUPS[group_by]
	agg = {}
	for r in rows:
		g = agg.setdefault(r.get(key) or _("(none)"), frappe._dict(group=r.get(key) or _("(none)"), count=0, received=0, paid=0))
		g.count += 1
		g.received += r.received
		g.paid += r.paid
	data = sorted(agg.values(), key=lambda g: -(g.received + g.paid))
	for g in data:
		g.net = g.received - g.paid
	cols = [
		{"label": _(group_by), "fieldname": "group", "fieldtype": "Data", "width": 220},
		{"label": _("Entries"), "fieldname": "count", "fieldtype": "Int", "width": 80},
		{"label": _("Received"), "fieldname": "received", "fieldtype": "Currency", "width": 140},
		{"label": _("Paid"), "fieldname": "paid", "fieldtype": "Currency", "width": 140},
		{"label": _("Net"), "fieldname": "net", "fieldtype": "Currency", "width": 140},
	]
	chart = {"data": {"labels": [str(g.group) for g in data[:15]], "datasets": [
		{"name": _("Received"), "values": [round(g.received) for g in data[:15]]},
		{"name": _("Paid"), "values": [round(g.paid) for g in data[:15]]}]}, "type": "bar", "fieldtype": "Currency",
		"colors": ["#16a34a", "#d97757"]} if data else None
	return cols, data, None, chart, _summary(rows)


def _chart(rows):
	by_day = {}
	for r in rows:
		d = by_day.setdefault(str(r.posting_date), [0, 0])
		d[0] += r.received
		d[1] += r.paid
	if not by_day:
		return None
	days = sorted(by_day)[-40:]
	return {"data": {"labels": days, "datasets": [{"name": _("Received"), "values": [round(by_day[d][0]) for d in days]},
		{"name": _("Paid"), "values": [round(by_day[d][1]) for d in days]}]}, "type": "bar", "fieldtype": "Currency",
		"colors": ["#16a34a", "#d97757"]}


def _summary(rows):
	rec, paid = sum(r.received for r in rows), sum(r.paid for r in rows)
	return [{"label": _("Received"), "value": rec, "datatype": "Currency", "indicator": "green"},
		{"label": _("Paid"), "value": paid, "datatype": "Currency", "indicator": "orange"},
		{"label": _("Net"), "value": rec - paid, "datatype": "Currency"},
		{"label": _("Entries"), "value": len(rows), "datatype": "Int"}]
