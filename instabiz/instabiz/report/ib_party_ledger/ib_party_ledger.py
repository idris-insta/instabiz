"""IB Party Ledger — the OTDS party account sheet, live.

One customer, one period: opening balance, then every receivable movement in
date order. Sales invoices open into their item lines (challan, description,
width, length, qty/pkg, pkgs, qty, rate, amount) with the invoice total, GST and
running balance on the invoice's first line; receipts, journals and credit
notes are single lines. Balances come from the GL, so they match the books.
"""
import frappe
from frappe import _
from frappe.utils import flt, getdate


def execute(filters=None):
	f = frappe._dict(filters or {})
	if not f.customer:
		return _columns(), [], None, None, []
	if not frappe.has_permission("Customer", "read", f.customer):
		frappe.throw(frappe._("You can only see the ledger of customers you handle."), frappe.PermissionError)
	f.company = f.company or frappe.defaults.get_user_default("Company")
	f.from_date = getdate(f.from_date) if f.from_date else getdate("1900-01-01")
	f.to_date = getdate(f.to_date) if f.to_date else getdate()
	data, totals = _data(f)
	return _columns(), data, None, None, _summary(totals)


def _columns():
	cur = lambda label, fn, w=110: {"label": label, "fieldname": fn, "fieldtype": "Currency", "width": w}
	return [
		{"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 92},
		{"label": _("Voucher Type"), "fieldname": "voucher_type", "fieldtype": "Data", "width": 110},
		{"label": _("Voucher No"), "fieldname": "voucher_no", "fieldtype": "Dynamic Link", "options": "voucher_type", "width": 150},
		{"label": _("Challan"), "fieldname": "challan", "fieldtype": "Link", "options": "Delivery Note", "width": 140},
		{"label": _("Description"), "fieldname": "description", "fieldtype": "Data", "width": 220},
		{"label": _("Width (mm)"), "fieldname": "width", "fieldtype": "Float", "width": 80},
		{"label": _("Length (m)"), "fieldname": "length", "fieldtype": "Float", "width": 80},
		{"label": _("Qty / Pkg"), "fieldname": "qty_pkg", "fieldtype": "Float", "width": 75},
		{"label": _("Pkgs"), "fieldname": "pkgs", "fieldtype": "Float", "width": 65},
		{"label": _("Qty"), "fieldname": "qty", "fieldtype": "Float", "width": 80},
		cur(_("Rate"), "rate", 90), cur(_("Amount"), "amount"),
		cur(_("Invoice Amt"), "invoice_amount"), cur(_("GST"), "gst", 95),
		cur(_("Received"), "received"), cur(_("Balance"), "balance", 120),
		{"label": _("Transport"), "fieldname": "transport", "fieldtype": "Data", "width": 120},
		{"label": _("LR No"), "fieldname": "lr_no", "fieldtype": "Data", "width": 100},
		{"label": _("Remarks"), "fieldname": "remarks", "fieldtype": "Data", "width": 200},
	]


def _data(f):
	args = {"company": f.company, "customer": f.customer, "from": f.from_date, "to": f.to_date}
	opening = flt(frappe.db.sql(
		"""SELECT SUM(debit - credit) FROM `tabGL Entry`
		WHERE is_cancelled = 0 AND company = %(company)s AND party_type = 'Customer'
		  AND party = %(customer)s AND posting_date < %(from)s""", args)[0][0])

	vouchers = frappe.db.sql(
		"""SELECT posting_date, voucher_type, voucher_no, SUM(debit) AS debit, SUM(credit) AS credit,
		          MAX(IFNULL(remarks, '')) AS remarks, MIN(creation) AS created
		FROM `tabGL Entry`
		WHERE is_cancelled = 0 AND company = %(company)s AND party_type = 'Customer'
		  AND party = %(customer)s AND posting_date BETWEEN %(from)s AND %(to)s
		GROUP BY posting_date, voucher_type, voucher_no
		ORDER BY posting_date, created""", args, as_dict=True)

	invoices = [v.voucher_no for v in vouchers if v.voucher_type == "Sales Invoice"]
	inv_head, inv_items = _invoice_details(invoices)

	rows = [frappe._dict(description="<b>" + _("Opening Balance") + "</b>", balance=opening, bold=1)]
	balance = opening
	totals = frappe._dict(opening=opening, invoiced=0, gst=0, received=0, other=0)
	for v in vouchers:
		net = flt(v.debit) - flt(v.credit)
		balance += net
		base = frappe._dict(posting_date=v.posting_date, voucher_type=v.voucher_type, voucher_no=v.voucher_no)
		if v.voucher_type == "Sales Invoice" and v.voucher_no in inv_head:
			head = inv_head[v.voucher_no]
			items = inv_items.get(v.voucher_no) or [frappe._dict()]
			for i, it in enumerate(items):
				row = frappe._dict(base, challan=it.delivery_note, description=it.item_name or it.item_code,
					width=it.width_mm, length=it.length_mtr, qty_pkg=it.qty_pkg, pkgs=it.total_pkg,
					qty=it.qty, rate=it.rate, amount=it.amount)
				if i == 0:
					row.update(invoice_amount=net, gst=head.gst, balance=balance, transport=head.transport,
						lr_no=head.lr_no, remarks=_("Return") if head.is_return else "")
				rows.append(row)
			if net >= 0:
				totals.invoiced += net
			else:
				totals.other += net
			totals.gst += flt(head.gst)
		else:
			received = flt(v.credit) - flt(v.debit)
			row = frappe._dict(base, description=v.voucher_type, balance=balance, remarks=v.remarks[:140])
			if v.voucher_type in ("Payment Entry", "Journal Entry"):
				row.received = received
				totals.received += received
			else:
				row.invoice_amount = net
				totals.other += net
			rows.append(row)
	rows.append(frappe._dict(description="<b>" + _("Closing Balance") + "</b>", balance=balance, bold=1))
	totals.closing = balance
	return rows, totals


def _invoice_details(names):
	if not names:
		return {}, {}
	transport_field = "IFNULL(NULLIF(si.custom_transport, ''), IFNULL(si.transporter_name, ''))" \
		if frappe.db.has_column("Sales Invoice", "custom_transport") else "IFNULL(si.transporter_name, '')"
	lr_field = "IFNULL(si.lr_no, '')" if frappe.db.has_column("Sales Invoice", "lr_no") else "''"
	heads = frappe.db.sql(
		f"""SELECT si.name, si.base_total_taxes_and_charges AS gst, si.is_return,
		           {transport_field} AS transport, {lr_field} AS lr_no
		FROM `tabSales Invoice` si WHERE si.name IN %(n)s""", {"n": tuple(names)}, as_dict=True)
	dim = {c: frappe.db.has_column("Sales Invoice Item", c) for c in ("width_mm", "length_mtr", "qty_pkg", "total_pkg")}
	extra = ", ".join(f"sii.{c}" if ok else f"NULL AS {c}" for c, ok in dim.items())
	items = frappe.db.sql(
		f"""SELECT sii.parent, sii.item_code, sii.item_name, sii.delivery_note, sii.qty, sii.rate,
		           sii.amount, {extra}
		FROM `tabSales Invoice Item` sii WHERE sii.parent IN %(n)s ORDER BY sii.parent, sii.idx""",
		{"n": tuple(names)}, as_dict=True)
	by_inv = {}
	for it in items:
		by_inv.setdefault(it.parent, []).append(it)
	return {h.name: h for h in heads}, by_inv


def _summary(t):
	if not t:
		return []
	return [
		{"label": _("Opening"), "value": t.opening, "datatype": "Currency"},
		{"label": _("Invoiced"), "value": t.invoiced, "datatype": "Currency", "indicator": "blue"},
		{"label": _("GST in Invoices"), "value": t.gst, "datatype": "Currency"},
		{"label": _("Received"), "value": t.received, "datatype": "Currency", "indicator": "green"},
		{"label": _("Returns / Adjustments"), "value": t.other, "datatype": "Currency"},
		{"label": _("Closing Balance"), "value": t.closing, "datatype": "Currency",
			"indicator": "red" if t.closing > 0.5 else "green"},
	]
