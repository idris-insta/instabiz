"""instabiz.overrides.tally_export

Vouchers → Tally XML (Gateway of Tally → Import → Transactions), built from the
General Ledger so whatever ERPNext posted is what Tally gets: one Tally voucher
per ERPNext voucher, one ledger line per account (and party), debits and credits
balanced to the paisa.

Voucher types: Sales Invoice → Sales, Purchase Invoice → Purchase, Payment Entry
→ Receipt / Payment / Contra, everything else → Journal. Ledger names: the
mapping table on IB Tally Export Settings first, then Sales / Purchase / Round
Off ledgers for the company defaults, then the account name without the company
abbreviation; parties use their name (or code). With "include masters" the file
also creates the ledgers under the usual Tally groups.
"""
from collections import OrderedDict
from xml.sax.saxutils import escape

import frappe
from frappe import _
from frappe.utils import flt, getdate

ROLES = ("System Manager", "Accounts Manager", "Accounts User")
SETTINGS = "IB Tally Export Settings"
VOUCHER_TYPES = {"Sales Invoice": "Sales", "Purchase Invoice": "Purchase"}


def _settings():
	s = frappe.get_cached_doc(SETTINGS)
	return frappe._dict(
		sales=s.sales_ledger or "Sales", purchase=s.purchase_ledger or "Purchase",
		round_off=s.round_off_ledger or "Round Off", party_name=bool(s.use_party_name if s.use_party_name is not None else 1),
		map={r.account: r.tally_ledger for r in (s.account_map or [])},
	)


class Ledgers:
	"""account / party → Tally ledger name and group."""

	def __init__(self, company):
		self.s = _settings()
		c = frappe.get_cached_doc("Company", company)
		self.abbr = c.abbr
		self.special = {c.default_income_account: self.s.sales, c.round_off_account: self.s.round_off}
		if c.get("default_expense_account"):
			self.special[c.default_expense_account] = self.s.purchase
		self.accounts = {a.name: a for a in frappe.get_all("Account", filters={"company": company},
			fields=["name", "account_name", "root_type", "account_type"])}
		self.groups = {}

	def account(self, name):
		if name in self.s.map:
			ledger = self.s.map[name]
		elif name in self.special and self.special[name]:
			ledger = self.special[name]
		else:
			ledger = (self.accounts.get(name) or frappe._dict(account_name=name)).account_name
		self.groups.setdefault(ledger, self._group(name, ledger))
		return ledger

	def party(self, party_type, party):
		label = party
		if self.s.party_name:
			field = {"Customer": "customer_name", "Supplier": "supplier_name", "Employee": "employee_name"}.get(party_type)
			label = (field and frappe.db.get_value(party_type, party, field)) or party
		self.groups.setdefault(label, {"Customer": "Sundry Debtors", "Supplier": "Sundry Creditors"}.get(party_type, "Sundry Creditors"))
		return label

	def _group(self, account, ledger):
		a = self.accounts.get(account) or frappe._dict()
		if ledger == self.s.sales:
			return "Sales Accounts"
		if ledger == self.s.purchase:
			return "Purchase Accounts"
		t, r = a.account_type or "", a.root_type or ""
		if t == "Bank":
			return "Bank Accounts"
		if t == "Cash":
			return "Cash-in-Hand"
		if t == "Tax":
			return "Duties & Taxes"
		if t in ("Stock", "Stock Received But Not Billed"):
			return "Stock-in-Hand" if t == "Stock" else "Current Liabilities"
		return {"Income": "Indirect Incomes", "Expense": "Indirect Expenses", "Asset": "Current Assets",
			"Liability": "Current Liabilities", "Equity": "Capital Account"}.get(r, "Suspense A/c")


def _gl(company, from_date, to_date, voucher_types=None):
	cond, args = "", {"company": company, "from": from_date, "to": to_date}
	if voucher_types:
		cond = " AND voucher_type IN %(vt)s"
		args["vt"] = tuple(voucher_types)
	return frappe.db.sql(
		f"""SELECT voucher_type, voucher_no, posting_date, account, party_type, party,
		       SUM(debit) AS debit, SUM(credit) AS credit, MAX(remarks) AS remarks
		FROM `tabGL Entry`
		WHERE company = %(company)s AND is_cancelled = 0 AND posting_date BETWEEN %(from)s AND %(to)s {cond}
		GROUP BY voucher_type, voucher_no, posting_date, account, party_type, party
		ORDER BY posting_date, voucher_no""", args, as_dict=True)


def vouchers(company, from_date, to_date, voucher_types=None):
	"""OrderedDict voucher_no → {type, date, lines: [(ledger, amount_dr_positive)], narration}."""
	led = Ledgers(company)
	out = OrderedDict()
	for g in _gl(company, from_date, to_date, voucher_types):
		v = out.setdefault(g.voucher_no, frappe._dict(name=g.voucher_no, doctype=g.voucher_type, date=g.posting_date,
			lines=OrderedDict(), narration=(g.remarks or "")[:250], party=None))
		name = led.party(g.party_type, g.party) if g.party else led.account(g.account)
		if g.party and not v.party:
			v.party = name
		v.lines[name] = flt(v.lines.get(name, 0) + flt(g.debit) - flt(g.credit), 2)
	for no, v in out.items():
		v.lines = OrderedDict((k, a) for k, a in v.lines.items() if a)
		v.tally_type = _tally_type(v)
		v.balance = round(sum(v.lines.values()), 2)
	return out, led


def _tally_type(v):
	if v.doctype in VOUCHER_TYPES:
		return VOUCHER_TYPES[v.doctype]
	if v.doctype == "Payment Entry":
		pt = frappe.db.get_value("Payment Entry", v.name, "payment_type")
		return {"Receive": "Receipt", "Pay": "Payment"}.get(pt, "Contra")
	return "Journal"


def build_xml(company, from_date, to_date, voucher_types=None, include_masters=True):
	vs, led = vouchers(company, from_date, to_date, voucher_types)
	company_name = frappe.db.get_value("Company", company, "company_name")
	parts = ["<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER><BODY><IMPORTDATA>",
		f"<REQUESTDESC><REPORTNAME>All Masters</REPORTNAME><STATICVARIABLES><SVCURRENTCOMPANY>{escape(company_name)}"
		"</SVCURRENTCOMPANY></STATICVARIABLES></REQUESTDESC><REQUESTDATA>"]
	if include_masters:
		for ledger, group in sorted(led.groups.items()):
			parts.append(f'<TALLYMESSAGE xmlns:UDF="TallyUDF"><LEDGER NAME="{escape(ledger)}" ACTION="Create">'
				f"<NAME.LIST><NAME>{escape(ledger)}</NAME></NAME.LIST><PARENT>{escape(group)}</PARENT>"
				"</LEDGER></TALLYMESSAGE>")
	for no, v in vs.items():
		if not v.lines or abs(v.balance) > 0.01:
			continue
		date = getdate(v.date).strftime("%Y%m%d")
		parts.append(f'<TALLYMESSAGE xmlns:UDF="TallyUDF"><VOUCHER VCHTYPE="{v.tally_type}" ACTION="Create">'
			f"<DATE>{date}</DATE><VOUCHERTYPENAME>{v.tally_type}</VOUCHERTYPENAME>"
			f"<VOUCHERNUMBER>{escape(no)}</VOUCHERNUMBER><NARRATION>{escape(v.narration)}</NARRATION>"
			+ (f"<PARTYLEDGERNAME>{escape(v.party)}</PARTYLEDGERNAME>" if v.party else ""))
		for ledger, amount in v.lines.items():
			# Tally: debit = negative amount with ISDEEMEDPOSITIVE Yes
			parts.append(f"<ALLLEDGERENTRIES.LIST><LEDGERNAME>{escape(ledger)}</LEDGERNAME>"
				f"<ISDEEMEDPOSITIVE>{'Yes' if amount > 0 else 'No'}</ISDEEMEDPOSITIVE>"
				f"<AMOUNT>{-amount:.2f}</AMOUNT></ALLLEDGERENTRIES.LIST>")
		parts.append("</VOUCHER></TALLYMESSAGE>")
	parts.append("</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>")
	return "".join(parts), vs


@frappe.whitelist()
def download(company, from_date, to_date, voucher_types=None, include_masters=1):
	frappe.only_for(ROLES)
	if isinstance(voucher_types, str):
		voucher_types = frappe.parse_json(voucher_types) if voucher_types.startswith("[") else [voucher_types]
	xml, vs = build_xml(company, from_date, to_date, voucher_types or None, bool(frappe.utils.cint(include_masters)))
	skipped = [no for no, v in vs.items() if v.lines and abs(v.balance) > 0.01]
	return {"filename": f"tally_{from_date}_{to_date}.xml", "content": xml,
		"count": len(vs) - len(skipped), "skipped": skipped}
