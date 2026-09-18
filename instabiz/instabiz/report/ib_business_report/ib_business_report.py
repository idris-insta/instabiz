"""IB Business Report — the OTDS "FY Business Report" workbook, live.

One report, one financial year (the year picked in the navbar FY switch by
default), several views of the same data:

  Monthly Summary · Party-wise · Collection Status · Item-wise ·
  Item Monthly (top 50) · Party Monthly (top 30) · State-wise · Salesperson-wise

Sales come from submitted Sales Invoices (returns count as negative sales),
collections from receivable GL credits posted by Payment Entry / Journal Entry,
outstanding is the party's receivable balance on the To Date (opening included).
"""
from collections import defaultdict
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import date_diff, flt, formatdate, getdate

VIEWS = ["Monthly Summary", "Party-wise", "Collection Status", "Item-wise", "Item Monthly",
	"Party Monthly", "State-wise", "Salesperson-wise"]


def execute(filters=None):
	f = frappe._dict(filters or {})
	f.company = f.company or frappe.defaults.get_user_default("Company")
	f.from_date, f.to_date = _period(f)
	f.view = f.view or "Monthly Summary"

	inv = _invoices(f)
	months = _months(f.from_date, f.to_date)
	coll = _collections(f)

	builder = {
		"Monthly Summary": _monthly, "Party-wise": _party, "Collection Status": _collection_status,
		"Item-wise": _item, "Item Monthly": _item_monthly, "Party Monthly": _party_monthly,
		"State-wise": _state, "Salesperson-wise": _salesperson,
	}[f.view]
	columns, data, chart = builder(f, inv, coll, months)
	return columns, data, None, chart, _summary(f, inv, coll)


# ---------------------------------------------------------------- data

def _period(f):
	if f.from_date and f.to_date:
		return getdate(f.from_date), getdate(f.to_date)
	fy = f.fiscal_year
	if not fy:
		from instabiz.overrides.financial_year import selected_year
		fy = (selected_year() or {}).get("name")
	row = frappe.db.get_value("Fiscal Year", fy, ["year_start_date", "year_end_date"]) if fy else None
	if not row:
		from erpnext.accounts.utils import get_fiscal_year
		row = get_fiscal_year(f.to_date or f.from_date or getdate(), as_dict=True)
		row = (row.year_start_date, row.year_end_date)
	start, end = row
	return getdate(f.from_date or start), getdate(f.to_date or end)


def _months(start, end):
	out, d = [], getdate(start).replace(day=1)
	while d <= end:
		out.append(d.strftime("%Y-%m"))
		d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
	return out


def _cond(f, alias="si"):
	cond, args = "", {"company": f.company, "from": f.from_date, "to": f.to_date}
	if f.customer:
		cond += f" AND {alias}.customer = %(customer)s"
		args["customer"] = f.customer
	if f.handled_by:
		cond += " AND IFNULL(c.custom_sales_person, '') = %(handled_by)s"
		args["handled_by"] = f.handled_by
	if f.get("exclude_internal", 1) not in (0, "0"):
		# branch-to-branch transfers billed to an own-company customer are not sales
		cond += " AND IFNULL(c.is_internal_customer, 0) = 0 AND IFNULL(c.customer_name, '') NOT LIKE 'INSTABIZ%%'"
	return cond, args


def _invoices(f):
	cond, args = _cond(f)
	rows = frappe.db.sql(
		f"""
		SELECT si.name, si.posting_date, DATE_FORMAT(si.posting_date, '%%Y-%%m') AS month,
		       si.customer, c.customer_name, c.customer_group,
		       COALESCE(NULLIF(c.custom_bt_state, ''), SUBSTRING_INDEX(IFNULL(si.place_of_supply, ''), '-', -1)) AS state,
		       IFNULL(c.custom_bt_city, '') AS city,
		       IFNULL(NULLIF(c.custom_sales_person, ''), '') AS handled_by,
		       si.base_net_total AS base, si.base_total_taxes_and_charges AS gst,
		       si.base_rounded_total AS net_rounded, si.base_grand_total AS net_grand,
		       si.is_return
		FROM `tabSales Invoice` si
		LEFT JOIN `tabCustomer` c ON c.name = si.customer
		WHERE si.docstatus = 1 AND si.company = %(company)s
		  AND si.posting_date BETWEEN %(from)s AND %(to)s {cond}
		""",
		args, as_dict=True,
	)
	for r in rows:
		r.net = flt(r.net_rounded) or flt(r.net_grand)
		r.state = (r.state or "").strip()
	if f.state:
		rows = [r for r in rows if r.state == f.state]
	return rows


def _collections(f):
	"""{(customer, month): collected} from receivable credits by payments / journals."""
	cond, args = _cond(f, "gle")
	cond = cond.replace("gle.customer", "gle.party")
	rows = frappe.db.sql(
		f"""
		SELECT gle.party AS customer, DATE_FORMAT(gle.posting_date, '%%Y-%%m') AS month,
		       SUM(gle.credit - gle.debit) AS amount
		FROM `tabGL Entry` gle
		LEFT JOIN `tabCustomer` c ON c.name = gle.party
		WHERE gle.is_cancelled = 0 AND gle.company = %(company)s AND gle.party_type = 'Customer'
		  AND gle.voucher_type IN ('Payment Entry', 'Journal Entry')
		  AND gle.posting_date BETWEEN %(from)s AND %(to)s {cond}
		GROUP BY gle.party, month
		""",
		args, as_dict=True,
	)
	out = defaultdict(float)
	for r in rows:
		out[(r.customer, r.month)] += flt(r.amount)
	return out


def _balances(f, customers=None):
	"""Receivable balance per customer on the To Date (opening included)."""
	args = {"company": f.company, "to": f.to_date}
	cond = ""
	if customers is not None:
		if not customers:
			return {}
		cond = " AND party IN %(customers)s"
		args["customers"] = tuple(customers)
	return dict(frappe.db.sql(
		f"""SELECT party, SUM(debit - credit) FROM `tabGL Entry`
		WHERE is_cancelled = 0 AND company = %(company)s AND party_type = 'Customer'
		  AND posting_date <= %(to)s {cond} GROUP BY party""",
		args,
	))


def _overdue(f, customers):
	"""{customer: (oldest unpaid due date, overdue amount)} on the To Date."""
	if not customers:
		return {}
	rows = frappe.db.sql(
		"""SELECT customer, MIN(due_date), SUM(IF(due_date < %(to)s, outstanding_amount, 0))
		FROM `tabSales Invoice`
		WHERE docstatus = 1 AND company = %(company)s AND outstanding_amount > 0.5
		  AND customer IN %(customers)s GROUP BY customer""",
		{"company": f.company, "to": f.to_date, "customers": tuple(customers)},
	)
	return {r[0]: (r[1], flt(r[2])) for r in rows}


def _items(f, inv):
	names = [r.name for r in inv]
	if not names:
		return []
	return frappe.db.sql(
		"""SELECT sii.parent, sii.item_code, sii.item_name, sii.item_group, sii.stock_qty AS qty,
		          sii.base_net_amount AS amount
		FROM `tabSales Invoice Item` sii WHERE sii.parent IN %(names)s""",
		{"names": tuple(names)}, as_dict=True,
	)


# ---------------------------------------------------------------- helpers

def _cur(label, fieldname, width=130):
	return {"label": label, "fieldname": fieldname, "fieldtype": "Currency", "width": width}


def _pct(a, b):
	return round(flt(a) * 100 / flt(b), 1) if flt(b) else 0


def _mlabel(m):
	return formatdate(m + "-01", "MMM YYYY")


def _party_rollup(f, inv, coll):
	p = {}
	for r in inv:
		d = p.setdefault(r.customer, frappe._dict(customer=r.customer, customer_name=r.customer_name,
			state=r.state, city=r.city, customer_group=r.customer_group, handled_by=r.handled_by,
			invoices=0, base=0, gst=0, net=0, collected=0, months=set()))
		d.invoices += 0 if r.is_return else 1
		d.base += flt(r.base)
		d.gst += flt(r.gst)
		d.net += flt(r.net)
		d.months.add(r.month)
	for (cust, _m), amt in coll.items():
		if cust in p:
			p[cust].collected += amt
		elif not (f.state or f.handled_by):
			p[cust] = frappe._dict(customer=cust, customer_name=frappe.db.get_value("Customer", cust, "customer_name"),
				state="", city="", customer_group="", handled_by="", invoices=0, base=0, gst=0, net=0,
				collected=amt, months=set())
	bal = _balances(f, list(p))
	for d in p.values():
		d.outstanding = flt(bal.get(d.customer))
		d.coll_pct = _pct(d.collected, d.net)
		d.active_months = len(d.months)
	return p


def _status(balance, due, to_date):
	if balance < -0.5:
		return "Advance", 0
	if balance <= 0.5:
		return "Cleared", 0
	if not due:
		return "Not Due", 0
	days = date_diff(to_date, due)
	if days > 30:
		return "Overdue > 30 days", days
	if days > 0:
		return "Overdue 1-30 days", days
	return "Not Due", 0


# ---------------------------------------------------------------- views

def _monthly(f, inv, coll, months):
	m = {k: frappe._dict(month=_mlabel(k), base=0, gst=0, net=0, collected=0, invoices=0, parties=set())
		for k in months}
	for r in inv:
		d = m.get(r.month)
		if d:
			d.base += flt(r.base)
			d.gst += flt(r.gst)
			d.net += flt(r.net)
			d.invoices += 0 if r.is_return else 1
			d.parties.add(r.customer)
	for (_c, month), amt in coll.items():
		if month in m:
			m[month].collected += amt
	data = []
	for k in months:
		d = m[k]
		d.difference = d.net - d.collected
		d.parties = len(d.parties)
		d.coll_pct = _pct(d.collected, d.net)
		data.append(d)
	tot = frappe._dict(month="<b>" + _("Full Year Total") + "</b>", bold=1)
	for key in ("base", "gst", "net", "collected", "difference", "invoices"):
		tot[key] = sum(flt(d[key]) for d in data)
	tot.parties = len({r.customer for r in inv})
	tot.coll_pct = _pct(tot.collected, tot.net)
	data.append(tot)
	columns = [
		{"label": _("Month"), "fieldname": "month", "fieldtype": "Data", "width": 130},
		_cur(_("Sales (Base)"), "base"), _cur(_("GST"), "gst", 115), _cur(_("Net Invoiced"), "net"),
		_cur(_("Collections"), "collected"), _cur(_("Billed − Collected"), "difference"),
		{"label": _("Invoices"), "fieldname": "invoices", "fieldtype": "Int", "width": 85},
		{"label": _("Parties"), "fieldname": "parties", "fieldtype": "Int", "width": 80},
		{"label": _("Coll %"), "fieldname": "coll_pct", "fieldtype": "Percent", "width": 85},
	]
	chart = {
		"data": {"labels": [d.month for d in data[:-1]], "datasets": [
			{"name": _("Net Invoiced"), "values": [round(d.net) for d in data[:-1]]},
			{"name": _("Collections"), "values": [round(d.collected) for d in data[:-1]]},
		]},
		"type": "bar", "fieldtype": "Currency", "colors": ["#d97757", "#2f9e44"],
	}
	return columns, data, chart


def _party_columns():
	return [
		{"label": _("Party"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 200},
		{"label": _("State"), "fieldname": "state", "fieldtype": "Data", "width": 110},
		{"label": _("City"), "fieldname": "city", "fieldtype": "Data", "width": 110},
		{"label": _("Type"), "fieldname": "customer_group", "fieldtype": "Data", "width": 110},
		{"label": _("Handled By"), "fieldname": "handled_by", "fieldtype": "Data", "width": 110},
		{"label": _("Invoices"), "fieldname": "invoices", "fieldtype": "Int", "width": 80},
		_cur(_("Base Sales"), "base"), _cur(_("GST"), "gst", 110), _cur(_("Net Invoiced"), "net"),
		_cur(_("Collected"), "collected"), _cur(_("Outstanding"), "outstanding"),
		{"label": _("Coll %"), "fieldname": "coll_pct", "fieldtype": "Percent", "width": 80},
		{"label": _("Active Months"), "fieldname": "active_months", "fieldtype": "Int", "width": 90},
	]


def _party(f, inv, coll, months):
	p = _party_rollup(f, inv, coll)
	data = sorted(p.values(), key=lambda d: -d.base)
	for d in data:
		d.pop("months", None)
	return _party_columns(), data, _top_chart(data, "customer", "base", _("Top 10 parties by sales"))


def _collection_status(f, inv, coll, months):
	p = _party_rollup(f, inv, coll)
	due = _overdue(f, list(p))
	limits = dict(frappe.db.sql(
		"""SELECT parent, MAX(credit_limit) FROM `tabCustomer Credit Limit`
		WHERE company = %s GROUP BY parent""", f.company))
	data = []
	for d in p.values():
		d.pop("months", None)
		oldest, overdue_amt = due.get(d.customer, (None, 0))
		d.status, d.days_overdue = _status(d.outstanding, oldest, f.to_date)
		d.overdue_amount = overdue_amt
		d.credit_limit = flt(limits.get(d.customer))
		d.over_limit = 1 if d.credit_limit and d.outstanding > d.credit_limit else 0
		data.append(d)
	data.sort(key=lambda d: -d.outstanding)
	columns = [c for c in _party_columns() if c["fieldname"] not in ("city", "customer_group", "base", "gst")]
	columns += [
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 140},
		{"label": _("Days Overdue"), "fieldname": "days_overdue", "fieldtype": "Int", "width": 95},
		_cur(_("Overdue Amount"), "overdue_amount"), _cur(_("Credit Limit"), "credit_limit"),
		{"label": _("Over Limit"), "fieldname": "over_limit", "fieldtype": "Check", "width": 80},
	]
	counts = defaultdict(float)
	for d in data:
		if d.outstanding > 0.5:
			counts[d.status] += d.outstanding
	chart = None if not counts else {"data": {"labels": list(counts), "datasets": [{"name": _("Outstanding"), "values": [round(v) for v in counts.values()]}]},
		"type": "donut", "fieldtype": "Currency"}
	return columns, data, chart


def _item(f, inv, coll, months):
	month_of = {r.name: r.month for r in inv}
	cust_of = {r.name: r.customer for r in inv}
	it = {}
	for r in _items(f, inv):
		d = it.setdefault(r.item_code, frappe._dict(item_code=r.item_code, item_name=r.item_name,
			item_group=r.item_group, amount=0, qty=0, orders=set(), parties=set(), by_month=defaultdict(float)))
		d.amount += flt(r.amount)
		d.qty += flt(r.qty)
		d.orders.add(r.parent)
		d.parties.add(cust_of[r.parent])
		d.by_month[month_of[r.parent]] += flt(r.amount)
	total = sum(d.amount for d in it.values())
	data = []
	for d in sorted(it.values(), key=lambda d: -d.amount):
		peak = max(d.by_month.items(), key=lambda kv: kv[1]) if d.by_month else ("", 0)
		data.append(frappe._dict(item_code=d.item_code, item_name=d.item_name, item_group=d.item_group,
			amount=d.amount, share=_pct(d.amount, total), qty=d.qty, orders=len(d.orders),
			parties=len(d.parties), peak_month=_mlabel(peak[0]) if peak[0] else "", peak_sales=peak[1]))
	columns = [
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 150},
		{"label": _("Description"), "fieldname": "item_name", "fieldtype": "Data", "width": 220},
		{"label": _("Item Group"), "fieldname": "item_group", "fieldtype": "Data", "width": 130},
		_cur(_("Total Sales"), "amount"), {"label": _("% of Total"), "fieldname": "share", "fieldtype": "Percent", "width": 85},
		{"label": _("Qty"), "fieldname": "qty", "fieldtype": "Float", "width": 90},
		{"label": _("Invoices"), "fieldname": "orders", "fieldtype": "Int", "width": 80},
		{"label": _("Parties"), "fieldname": "parties", "fieldtype": "Int", "width": 75},
		{"label": _("Peak Month"), "fieldname": "peak_month", "fieldtype": "Data", "width": 100},
		_cur(_("Peak Month Sales"), "peak_sales"),
	]
	return columns, data, _top_chart(data, "item_name", "amount", _("Top 10 items by sales"))


def _pivot(rows, key, months, top, label, link):
	agg = {}
	for k, month, amt, name in rows:
		d = agg.setdefault(k, frappe._dict({key: k, "name": name, "total": 0}))
		d[month.replace("-", "_")] = flt(d.get(month.replace("-", "_"))) + flt(amt)
		d.total += flt(amt)
	data = sorted(agg.values(), key=lambda d: -d.total)[:top]
	columns = [{"label": label, "fieldname": key, "fieldtype": "Link", "options": link, "width": 170},
		{"label": _("Name"), "fieldname": "name", "fieldtype": "Data", "width": 180}]
	columns += [_cur(_mlabel(m), m.replace("-", "_"), 105) for m in months]
	columns.append(_cur(_("Total"), "total"))
	return columns, data


def _item_monthly(f, inv, coll, months):
	month_of = {r.name: r.month for r in inv}
	rows = [(r.item_code, month_of[r.parent], r.amount, r.item_name) for r in _items(f, inv)]
	columns, data = _pivot(rows, "item_code", months, 50, _("Item"), "Item")
	return columns, data, None


def _party_monthly(f, inv, coll, months):
	rows = [(r.customer, r.month, r.base, r.customer_name) for r in inv]
	columns, data = _pivot(rows, "customer", months, 30, _("Party"), "Customer")
	return columns, data, None


def _group(f, inv, coll, keyname):
	p = _party_rollup(f, inv, coll)
	g = {}
	total = sum(flt(d.base) for d in p.values())
	for d in p.values():
		k = d.get(keyname) or _("Not Set")
		x = g.setdefault(k, frappe._dict({keyname: k, "base": 0, "net": 0, "collected": 0, "outstanding": 0,
			"invoices": 0, "parties": 0}))
		for fld in ("base", "net", "collected", "outstanding", "invoices"):
			x[fld] += flt(d[fld])
		x.parties += 1
	data = sorted(g.values(), key=lambda d: -d.base)
	for d in data:
		d.share = _pct(d.base, total)
		d.coll_pct = _pct(d.collected, d.net)
	return data


def _group_columns(label, keyname):
	return [
		{"label": label, "fieldname": keyname, "fieldtype": "Data", "width": 170},
		_cur(_("Base Sales"), "base"), {"label": _("% Share"), "fieldname": "share", "fieldtype": "Percent", "width": 85},
		_cur(_("Net Invoiced"), "net"), _cur(_("Collections"), "collected"), _cur(_("Outstanding"), "outstanding"),
		{"label": _("Invoices"), "fieldname": "invoices", "fieldtype": "Int", "width": 80},
		{"label": _("Parties"), "fieldname": "parties", "fieldtype": "Int", "width": 75},
		{"label": _("Coll %"), "fieldname": "coll_pct", "fieldtype": "Percent", "width": 80},
	]


def _state(f, inv, coll, months):
	data = _group(f, inv, coll, "state")
	return _group_columns(_("State"), "state"), data, _top_chart(data, "state", "base", _("Sales by state"))


def _salesperson(f, inv, coll, months):
	data = _group(f, inv, coll, "handled_by")
	return _group_columns(_("Handled By"), "handled_by"), data, _top_chart(data, "handled_by", "base", _("Sales by salesperson"))


def _top_chart(data, label_key, value_key, title):
	top = data[:10]
	if not top:
		return None
	return {"title": title, "data": {"labels": [str(d.get(label_key) or "")[:22] for d in top],
		"datasets": [{"name": title, "values": [round(flt(d.get(value_key))) for d in top]}]},
		"type": "bar", "fieldtype": "Currency", "colors": ["#d97757"]}


def _summary(f, inv, coll):
	base = sum(flt(r.base) for r in inv)
	gst = sum(flt(r.gst) for r in inv)
	net = sum(flt(r.net) for r in inv)
	collected = sum(coll.values())
	customers = {r.customer for r in inv}
	bal = _balances(f)
	outstanding = sum(v for v in bal.values() if flt(v) > 0)
	products = frappe.db.sql("""SELECT COUNT(DISTINCT item_code) FROM `tabSales Invoice Item`
		WHERE parent IN %(n)s""", {"n": tuple(r.name for r in inv)})[0][0] if inv else 0
	return [
		{"label": _("Total Sales (Base)"), "value": base, "datatype": "Currency", "indicator": "blue"},
		{"label": _("Net Invoiced"), "value": net, "datatype": "Currency"},
		{"label": _("GST"), "value": gst, "datatype": "Currency"},
		{"label": _("Collected"), "value": collected, "datatype": "Currency", "indicator": "green"},
		{"label": _("Outstanding (receivable)"), "value": outstanding, "datatype": "Currency", "indicator": "red"},
		{"label": _("Invoices"), "value": sum(0 if r.is_return else 1 for r in inv), "datatype": "Int"},
		{"label": _("Active Parties"), "value": len(customers), "datatype": "Int"},
		{"label": _("Products Sold"), "value": products, "datatype": "Int"},
		{"label": _("Collection %"), "value": _pct(collected, net), "datatype": "Percent"},
	]
