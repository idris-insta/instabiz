"""instabiz.overrides.print_helpers

One place that works out what every customer / supplier document prints:
seller block (per location), bank details, bill-to / ship-to, item lines with
dimensions, HSN-wise tax summary, totals, statement lines. Print formats call
ib_print(doc) through the jinja hook and only lay the data out.

Location drives the seller: address, GSTIN, phone, bank and default terms all
follow the document's location (custom_location, else its warehouse), so a
Chennai document never prints the Maharashtra address or bank.
"""
import json

import frappe
from frappe.utils import add_days, flt, fmt_money, formatdate, getdate, money_in_words, today

from instabiz.overrides.ib_settings import get
from instabiz.overrides.utils import (
	LOCATION_COMPANY_ADDRESS,
	LOCATION_COMPANY_GSTIN,
	LOCATION_WAREHOUSE,
)

_DEFAULT_LETTERHEAD = "/files/Instabiz_LH_v2.png"
_DEFAULT_STAMP = "/files/IB_Stamp.jpeg"
_IFSC = __import__("re").compile(r"[A-Z]{4}0[A-Z0-9]{6}")

_TERMS_SETTING = {
	"Purchase Order": "purchase_order_terms",
	"Quotation": "quotation_terms",
	"Sales Order": "sales_order_terms",
	"Delivery Note": "challan_terms",
}


# ── location ───────────────────────────────────────────────────────────────────

def _location(doc):
	loc = (doc.get("custom_location") or "").lower()
	if loc in LOCATION_WAREHOUSE:
		return loc
	if doc.doctype in ("Customer", "Payment Entry"):
		loc = _party_location(doc)
		if loc:
			return loc
	gstin = doc.get("company_gstin") or ""
	for key, value in LOCATION_COMPANY_GSTIN.items():
		if gstin and value == gstin:
			return key
	wh = (doc.get("set_warehouse") or "").upper()
	for key in LOCATION_WAREHOUSE:
		if key.upper() in wh:
			return key
	return "maharashtra"


def _party_location(doc):
	"""Location of the order a receipt is for, else the customer's latest order."""
	so = doc.get("custom_advance_for_so") if doc.doctype == "Payment Entry" else None
	if not so and doc.doctype == "Payment Entry":
		refs = [r.reference_name for r in doc.get("references") or [] if r.reference_doctype == "Sales Order"]
		so = refs[0] if refs else None
	if so:
		return (frappe.db.get_value("Sales Order", so, "custom_location") or "").lower() or None
	customer = doc.name if doc.doctype == "Customer" else (doc.party if doc.get("party_type") == "Customer" else None)
	if not customer:
		return None
	loc = frappe.db.get_value(
		"Sales Order", {"customer": customer, "docstatus": 1}, "custom_location", order_by="transaction_date desc"
	)
	return (loc or "").lower() or None


def _warehouse_chain(loc):
	"""The location's warehouse and its parents (settings may sit on the group)."""
	out = []
	wh = LOCATION_WAREHOUSE.get(loc)
	while wh and wh not in out:
		out.append(wh)
		wh = frappe.db.get_value("Warehouse", wh, "parent_warehouse")
	return out


def _warehouse_value(loc, field):
	if not frappe.db.has_column("Warehouse", field):
		return None
	for wh in _warehouse_chain(loc):
		value = frappe.db.get_value("Warehouse", wh, field)
		if value:
			return value
	return None


def _address(name):
	if not name or not frappe.db.exists("Address", name):
		return None
	a = frappe.db.get_value(
		"Address", name,
		["address_title", "address_line1", "address_line2", "city", "state", "pincode", "gstin",
			"phone", "email_id", "country"],
		as_dict=True,
	)
	lines = [a.address_line1, a.address_line2]
	city = ", ".join(x for x in (a.city, a.state) if x)
	if a.pincode:
		city = f"{city} - {a.pincode}" if city else a.pincode
	lines.append(city)
	a.lines = [x for x in lines if x]
	a.state_code = (a.gstin or "")[:2]
	return a


def seller(doc):
	loc = _location(doc)
	company_name = doc.get("company") or frappe.defaults.get_global_default("company")
	company = frappe.get_cached_doc("Company", company_name) if company_name else None
	address_name = doc.get("company_address") or LOCATION_COMPANY_ADDRESS.get(loc)
	# a document whose company_address still points at another location's
	# address prints the location's own address instead
	location_address = LOCATION_COMPANY_ADDRESS.get(loc)
	if doc.get("custom_location") and location_address and frappe.db.get_value("Address", location_address, "disabled") == 0:
		address_name = location_address
	addr = _address(address_name)
	gstin = doc.get("company_gstin") or LOCATION_COMPANY_GSTIN.get(loc) or (company.get("gstin") if company else "")
	return frappe._dict(
		name=(company.company_name if company else doc.get("company")) or "",
		lines=addr.lines if addr else [],
		gstin=gstin,
		state_code=(gstin or "")[:2],
		state=_state_name(gstin),
		pan=company.get("pan") if company else "",
		phone=_warehouse_value(loc, "custom_phone") or (company.phone_no if company else ""),
		email=company.email if company else "",
		website=company.website if company else "",
		location=loc.title(),
	)


def _state_name(gstin):
	code = (gstin or "")[:2]
	if not code.isdigit():
		return ""
	try:
		from india_compliance.gst_india.utils import get_state

		return get_state(code) or ""
	except Exception:
		from instabiz.overrides.utils import GSTIN_STATE_MAP

		return GSTIN_STATE_MAP.get(code, "")


def bank(doc):
	loc = _location(doc)
	name = _warehouse_value(loc, "custom_bank_details") or get(f"bank_account_{loc}")
	company = doc.get("company") or frappe.defaults.get_global_default("company")
	if not name and company:
		name = frappe.db.get_value(
			"Bank Account", {"company": company, "is_company_account": 1, "is_default": 1}, "name"
		)
	if not name or not frappe.db.exists("Bank Account", name):
		return None
	ba = frappe.db.get_value(
		"Bank Account", name,
		["account_name", "bank", "bank_account_no", "branch_code", "company", "iban"], as_dict=True,
	)
	raw = ba.branch_code or ""
	match = _IFSC.search(raw.upper())
	ifsc = match.group(0) if match else raw.split("&")[-1].strip()
	branch = raw.replace(ifsc, "").strip(" &,-") if match else ""
	return frappe._dict(
		holder=ba.company or doc.get("company"),
		bank=frappe.db.get_value("Bank", ba.bank, "bank_name") or ba.bank,
		account_no=ba.bank_account_no,
		ifsc=ifsc,
		branch=branch,
	)


# ── parties ────────────────────────────────────────────────────────────────────

def party(doc):
	"""Bill-to / ship-to for customer or supplier documents."""
	if doc.doctype == "Customer":
		name, ship_name = doc.customer_name, None
		bill_name = doc.get("customer_primary_address") or _linked_address("Customer", doc.name)
	elif doc.doctype == "Payment Entry":
		name = doc.party_name or doc.party
		bill_name = (doc.get("customer_address") or doc.get("party_address")
			or (_linked_address(doc.party_type, doc.party) if doc.party_type in ("Customer", "Supplier") else None))
		ship_name = None
	elif doc.doctype in ("Purchase Order", "Purchase Receipt", "Purchase Invoice"):
		name = doc.supplier_name or doc.supplier
		bill_name, ship_name = doc.get("supplier_address"), None
	else:
		name = doc.get("customer_name") or doc.get("party_name")
		bill_name = doc.get("customer_address")
		ship_name = doc.get("shipping_address_name") or bill_name
	bill = _address(bill_name)
	ship = _address(ship_name) if ship_name and ship_name != bill_name else None
	gstin = (doc.get("billing_address_gstin") or (bill.gstin if bill else "") or doc.get("supplier_gstin")
		or (doc.get("gstin") if doc.doctype == "Customer" else "") or "")
	return frappe._dict(
		name=name or "",
		bill=bill,
		ship=ship,
		gstin=gstin,
		state=_state_name(gstin) or (bill.state if bill else ""),
		state_code=(gstin or "")[:2],
		place_of_supply=doc.get("place_of_supply") or "",
		contact=_contact(doc, name),
		mobile=doc.get("contact_mobile") or doc.get("mobile_no") or "",
		email=doc.get("contact_email") or doc.get("email_id") or "",
	)


def _contact(doc, party_name):
	contact = (doc.get("contact_display") or doc.get("custom_contact_person_name") or "").strip()
	return "" if contact.lower() == (party_name or "").strip().lower() else contact


def _linked_address(link_doctype, link_name):
	rows = frappe.db.sql(
		"""SELECT a.name FROM `tabAddress` a
		INNER JOIN `tabDynamic Link` dl ON dl.parent = a.name AND dl.parenttype = 'Address'
		WHERE dl.link_doctype = %s AND dl.link_name = %s AND a.disabled = 0
		ORDER BY a.is_primary_address DESC, a.address_type = 'Billing' DESC, a.modified DESC LIMIT 1""",
		(link_doctype, link_name),
	)
	return rows[0][0] if rows else None


# ── items / tax ────────────────────────────────────────────────────────────────

def _fmt_num(v):
	v = flt(v)
	return str(int(v)) if v == int(v) else f"{v:g}"


def item_spec(row):
	"""Dimension / spec line for a sales item (width x length, thickness, colour...)."""
	parts = []
	if row.get("width_mm") and row.get("length_mtr"):
		parts.append(f"{_fmt_num(row.width_mm)} mm × {_fmt_num(row.length_mtr)} m")
	elif row.get("width_mm"):
		parts.append(f"{_fmt_num(row.width_mm)} mm")
	for field in ("custom_thickness", "color"):
		if row.get(field):
			parts.append(str(row.get(field)))
	if row.get("custom_branding"):
		parts.append(f"Branding: {row.custom_branding}")
	if row.get("custom_marking"):
		parts.append(f"Marking: {row.custom_marking}")
	if row.get("qty_pkg") and row.get("total_pkg"):
		parts.append(f"{_fmt_num(row.qty_pkg)} per pkg × {_fmt_num(row.total_pkg)} pkg")
	elif row.get("total_pkg"):
		parts.append(f"{_fmt_num(row.total_pkg)} pkg")
	return " · ".join(parts)


def _tax_kind(tax):
	text = f"{tax.get('description') or ''} {tax.get('account_head') or ''}".upper()
	for kind in ("IGST", "CGST", "SGST", "UTGST", "CESS"):
		if kind in text:
			return "SGST" if kind == "UTGST" else kind
	return None


def _row_rates(doc, row):
	"""GST rate per tax kind for one item row, honouring its Item Tax Template."""
	item_rates = json.loads(row.item_tax_rate) if row.get("item_tax_rate") else {}
	rates = {}
	for tax in doc.get("taxes") or []:
		kind = _tax_kind(tax)
		if not kind or tax.charge_type not in ("On Net Total", "On Item Quantity"):
			continue
		rate = flt(item_rates.get(tax.account_head, tax.rate))
		rates[kind] = rates.get(kind, 0) + rate
	return rates


def _extra_text(value, row):
	"""Free text for an item line, dropped when it only repeats the item name/code."""
	value = (value or "").strip()
	if value.lower() in ((row.item_name or "").strip().lower(), (row.item_code or "").strip().lower()):
		return ""
	return value


def items(doc):
	out = []
	for i, row in enumerate(doc.get("items") or [], start=1):
		rates = _row_rates(doc, row) if doc.get("taxes") else {}
		gst = sum(v for k, v in rates.items() if k != "CESS")
		out.append(frappe._dict(
			idx=i,
			row=row,
			item_code=row.item_code,
			item_name=row.item_name or row.item_code,
			description=_extra_text(row.get("custom_description"), row),
			spec=item_spec(row),
			specifications=_extra_text(row.get("custom_specifications"), row),
			hsn=row.get("gst_hsn_code") or "",
			qty=flt(row.qty),
			uom=row.uom or row.get("stock_uom") or "",
			rate=flt(row.rate),
			price_list_rate=flt(row.get("price_list_rate")),
			discount_pct=flt(row.get("discount_percentage")),
			amount=flt(row.amount),
			taxable=flt(row.get("net_amount") or row.amount),
			gst_rate=gst,
			tax=flt(flt(row.get("net_amount") or row.amount) * gst / 100, 2),
			total=flt(flt(row.amount) + flt(row.get("net_amount") or row.amount) * gst / 100, 2),
			weight=flt(row.get("custom_total_weight_kg") or row.get("total_weight")),
			note=(row.get("custom_qty_adjustment_note") or "").strip(),
			packages=flt(row.get("total_pkg")),
		))
	return out


def hsn_summary(doc):
	groups = {}
	for line in items(doc):
		rates = _row_rates(doc, line.row)
		g = groups.setdefault(line.hsn or "—", frappe._dict(hsn=line.hsn or "—", taxable=0, igst=0, cgst=0,
			sgst=0, cess=0, igst_rate=0, cgst_rate=0, sgst_rate=0))
		g.taxable += line.taxable
		for kind, rate in rates.items():
			key = kind.lower()
			g[key] += line.taxable * rate / 100
			if key + "_rate" in g:
				g[key + "_rate"] = rate
	rows = list(groups.values())
	total = frappe._dict(taxable=0, igst=0, cgst=0, sgst=0, cess=0)
	for r in rows:
		for k in ("igst", "cgst", "sgst", "cess"):
			r[k] = flt(r[k], 2)
		r.tax = r.igst + r.cgst + r.sgst + r.cess
		for k in total:
			total[k] += r[k]
	total.tax = total.igst + total.cgst + total.sgst + total.cess
	interstate = any(r.igst for r in rows)
	if not total.tax:
		rows = []  # untaxed document: no summary table
	return frappe._dict(rows=rows, total=total, interstate=interstate)


def totals(doc):
	net = flt(doc.get("net_total"))
	taxes = [t for t in doc.get("taxes") or [] if flt(t.tax_amount)]
	tax_total = flt(doc.get("total_taxes_and_charges"))
	grand = flt(doc.get("rounded_total") or doc.get("grand_total"))
	discount = flt(doc.get("discount_amount"))
	extra = flt(doc.get("grand_total")) - net - tax_total
	rounding = flt(doc.get("rounding_adjustment"))
	words = doc.get("in_words")
	gst = flt(doc.get("custom_gst_amount"))
	if doc.doctype == "Sales Order" and gst and not any(t.charge_type != "Actual" for t in taxes):
		# the order carries no GST rows; the customer still owes the invoice amount
		taxes = [*taxes, frappe._dict(description=frappe._("GST (charged on invoice)"), rate=0, tax_amount=gst)]
		grand = flt(doc.get("custom_total_with_gst")) or flt(doc.get("grand_total")) + gst
		rounding = flt(grand - flt(doc.get("grand_total")) - gst, 2)
		words = None
	return frappe._dict(
		total=flt(doc.get("total")),
		discount=discount,
		net=net,
		taxes=taxes,
		extra=flt(extra, 2) if abs(extra) > 0.5 else 0,
		rounding=rounding,
		grand=grand,
		words=words or money_in_words(grand, doc.get("currency") or "INR"),
		total_qty=flt(doc.get("total_qty")),
		advance=flt(doc.get("custom_advance_paid") or doc.get("advance_paid")),
	)


def terms(doc, kind=None):
	if kind == "proforma" and get("proforma_terms"):
		return get("proforma_terms")
	if doc.get("terms"):
		return doc.terms
	setting = _TERMS_SETTING.get(doc.doctype)
	if setting and get(setting):
		return get(setting)
	return _warehouse_value(_location(doc), "custom_terms__conditions") or ""


def sales_person(doc):
	user = doc.get("custom_sales_person_user")
	if not user:
		return None
	u = frappe.db.get_value("User", user, ["full_name", "mobile_no", "phone", "email"], as_dict=True)
	return frappe._dict(name=u.full_name, phone=u.mobile_no or u.phone or "", email=u.email) if u else None


# ── statement of account ───────────────────────────────────────────────────────

def statement(customer, from_date=None, to_date=None):
	"""Ledger lines for a customer: opening, entries, running balance.
	Follows billing_mode: orders + receipts while billing runs on Sales Orders,
	the general ledger once real invoicing is on."""
	from instabiz.overrides.billing_mode import is_dev_billing_mode

	to_date = getdate(to_date or today())
	if not from_date:
		try:
			from erpnext.accounts.utils import get_fiscal_year

			from_date = get_fiscal_year(to_date, as_dict=True).year_start_date
		except Exception:
			from_date = add_days(to_date, -365)
	from_date = getdate(from_date)

	if is_dev_billing_mode():
		entries = frappe.db.sql(
			"""
			SELECT transaction_date AS date, 'Sales Order' AS voucher_type, name AS voucher_no,
			       COALESCE(NULLIF(custom_total_with_gst, 0), grand_total) AS debit, 0 AS credit, IFNULL(po_no, '') AS remarks
			FROM `tabSales Order` WHERE customer = %(c)s AND docstatus = 1
			UNION ALL
			SELECT posting_date, 'Payment Entry', name, 0, paid_amount,
			       CONCAT(IFNULL(mode_of_payment, ''), IF(reference_no IS NULL OR reference_no = '', '', CONCAT(' / ', reference_no)))
			FROM `tabPayment Entry` WHERE party_type = 'Customer' AND party = %(c)s AND docstatus = 1
			  AND payment_type = 'Receive'
			UNION ALL
			SELECT posting_date, 'Payment Entry', name, paid_amount, 0, 'Refund'
			FROM `tabPayment Entry` WHERE party_type = 'Customer' AND party = %(c)s AND docstatus = 1
			  AND payment_type = 'Pay'
			ORDER BY date, voucher_no
			""",
			{"c": customer}, as_dict=True,
		)
	else:
		entries = frappe.db.sql(
			"""
			SELECT posting_date AS date, voucher_type, voucher_no,
			       SUM(debit) AS debit, SUM(credit) AS credit, MAX(IFNULL(remarks, '')) AS remarks
			FROM `tabGL Entry`
			WHERE party_type = 'Customer' AND party = %(c)s AND is_cancelled = 0
			GROUP BY posting_date, voucher_type, voucher_no
			ORDER BY posting_date, voucher_no
			""",
			{"c": customer}, as_dict=True,
		)

	opening = sum(flt(e.debit) - flt(e.credit) for e in entries if getdate(e.date) < from_date)
	lines, balance = [], opening
	total_debit = total_credit = 0
	for e in entries:
		d = getdate(e.date)
		if d < from_date or d > to_date:
			continue
		balance += flt(e.debit) - flt(e.credit)
		total_debit += flt(e.debit)
		total_credit += flt(e.credit)
		e.balance = balance
		e.remarks = (e.remarks or "")[:80]
		lines.append(e)
	return frappe._dict(
		from_date=from_date, to_date=to_date, opening=opening, lines=lines,
		total_debit=total_debit, total_credit=total_credit, closing=balance,
		basis="orders" if is_dev_billing_mode() else "ledger",
	)


# ── the one jinja entry point ──────────────────────────────────────────────────

def ib_print(doc, kind=None):
	"""Everything a print format needs, as one dict."""
	accent = get("print_accent_color", "#c0392b") or "#c0392b"
	s = seller(doc)
	note = get("print_footer_note", "")
	jurisdiction = get("jurisdiction", "")
	if jurisdiction:
		note = f"Subject to {jurisdiction} jurisdiction. {note}".strip()
	return frappe._dict(
		seller=s,
		website=get("print_website", s.website or "www.instabizsolutions.com"),
		phone=get("print_phone", s.phone or ""),
		email=get("print_email", s.email or ""),
		bank=bank(doc),
		party=party(doc),
		letterhead=get("print_letterhead_image", _DEFAULT_LETTERHEAD),
		stamp=get("print_stamp_image", _DEFAULT_STAMP),
		accent=accent,
		footer_note=note,
		terms=terms(doc, kind) if kind != "none" else "",
		sales_person=sales_person(doc),
		is_draft=bool(doc.meta.is_submittable) and doc.docstatus == 0,
		is_cancelled=doc.docstatus == 2,
	)


def ib_money(value, currency="INR"):
	return fmt_money(flt(value), precision=2, currency=currency)


def ib_date(value, fmt="dd-MM-yyyy"):
	return formatdate(value, fmt) if value else ""


# jinja exposes methods by function name — keep every exported name prefixed
# so none shadows a template variable (a bare "items" global once broke a format)
def ib_items(doc):
	return items(doc)


def ib_hsn_summary(doc):
	return hsn_summary(doc)


def ib_totals(doc):
	return totals(doc)


def ib_statement(customer, from_date=None, to_date=None):
	return statement(customer, from_date, to_date)


def ib_outstanding_rows(customer):
	"""IB Outstanding Statement rows without frappe.call (which needs an HTTP request)."""
	from instabiz.overrides.customer import get_outstanding_statement_rows

	return get_outstanding_statement_rows(customer)


def ib_gst_label(lines):
	"""Heading for the GST column: 'GST (18%)' when every line has one rate."""
	rates = {round(line.gst_rate, 2) for line in lines if line.gst_rate}
	return f"GST ({next(iter(rates)):g}%)" if len(rates) == 1 else "GST"
