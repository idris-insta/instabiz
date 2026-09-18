"""instabiz.overrides.financial_year

Financial year handling, modelled on Tally (F2 "change period", books
beginning, previous years one click away) and SAP (posting periods locked,
year-end balance carry-forward):

- every user picks the financial year they are looking at (navbar); reports
  and date filters then open inside that year. The pick is a user default,
  so it never changes anyone else's view and never touches posting dates.
- the Financial Year page lists every year with its totals, creates the next
  year, locks the books up to a date (Accounts Settings "Accounts Frozen
  Till"), and walks year-end closing (Period Closing Voucher) with a checklist.
"""
import frappe
from frappe import _
from frappe.utils import add_days, add_years, flt, getdate, today

_KEY = "ib_fiscal_year"
_MANAGER_ROLES = ("Accounts Manager", "System Manager")
_VIEW_ROLES = ("Accounts User", "Accounts Manager", "System Manager", "Sales Manager", "Purchase Manager",
	"Stock Manager", "HR Manager", "Factory Management")


def _company():
	return frappe.defaults.get_user_default("company") or frappe.defaults.get_global_default("company")


def _years():
	return frappe.get_all(
		"Fiscal Year", filters={"disabled": 0},
		fields=["name", "year_start_date", "year_end_date"], order_by="year_start_date desc",
	)


def _current_year():
	on = getdate(today())
	for fy in _years():
		if getdate(fy.year_start_date) <= on <= getdate(fy.year_end_date):
			return fy
	return None


def selected_year(user=None):
	"""The year this user is looking at: their pick, else the one containing today."""
	name = frappe.defaults.get_user_default(_KEY, user=user)
	if name and frappe.db.exists("Fiscal Year", name):
		fy = frappe.db.get_value("Fiscal Year", name, ["name", "year_start_date", "year_end_date"], as_dict=True)
		return fy
	return _current_year()


def boot_session(bootinfo):
	"""Tell the browser which year to open reports in (runs after ERPNext's boot)."""
	fy = selected_year()
	current = _current_year()
	if not fy:
		return
	bootinfo.ib_fiscal_year = {
		"name": fy.name, "start": str(fy.year_start_date), "end": str(fy.year_end_date),
		"is_current": bool(current and current.name == fy.name),
		"current": current.name if current else None,
	}


@frappe.whitelist()
def set_year(fiscal_year=None):
	"""Switch the year this user looks at; blank goes back to the current year."""
	if fiscal_year and not frappe.db.exists("Fiscal Year", fiscal_year):
		frappe.throw(_("Financial year {0} does not exist.").format(fiscal_year))
	current = _current_year()
	if not fiscal_year or (current and fiscal_year == current.name):
		frappe.defaults.clear_user_default(_KEY)
	else:
		frappe.defaults.set_user_default(_KEY, fiscal_year)
	return selected_year()


def _totals(fy):
	"""Headline numbers for one year, straight from the ledger."""
	company = _company()
	args = {"from": fy.year_start_date, "to": fy.year_end_date, "company": company}
	rows = frappe.db.sql(
		"""
		SELECT a.root_type, SUM(gle.debit) AS debit, SUM(gle.credit) AS credit
		FROM `tabGL Entry` gle INNER JOIN `tabAccount` a ON a.name = gle.account
		WHERE gle.is_cancelled = 0 AND gle.company = %(company)s
		  AND gle.posting_date BETWEEN %(from)s AND %(to)s
		  AND gle.voucher_type != 'Period Closing Voucher'
		GROUP BY a.root_type
		""", args, as_dict=True,
	)
	by = {r.root_type: r for r in rows}
	income = flt(by.get("Income", {}).get("credit")) - flt(by.get("Income", {}).get("debit"))
	expense = flt(by.get("Expense", {}).get("debit")) - flt(by.get("Expense", {}).get("credit"))
	orders = frappe.db.sql(
		"SELECT COUNT(*), COALESCE(SUM(base_grand_total), 0) FROM `tabSales Order` "
		"WHERE docstatus = 1 AND company = %(company)s AND transaction_date BETWEEN %(from)s AND %(to)s", args,
	)[0]
	purchases = frappe.db.sql(
		"SELECT COALESCE(SUM(base_grand_total), 0) FROM `tabPurchase Order` "
		"WHERE docstatus = 1 AND company = %(company)s AND transaction_date BETWEEN %(from)s AND %(to)s", args,
	)[0][0]
	receipts = frappe.db.sql(
		"SELECT COALESCE(SUM(base_received_amount), 0) FROM `tabPayment Entry` WHERE docstatus = 1 "
		"AND payment_type = 'Receive' AND company = %(company)s AND posting_date BETWEEN %(from)s AND %(to)s", args,
	)[0][0]
	vouchers = frappe.db.sql(
		"SELECT COUNT(DISTINCT voucher_no) FROM `tabGL Entry` WHERE is_cancelled = 0 AND company = %(company)s "
		"AND posting_date BETWEEN %(from)s AND %(to)s", args,
	)[0][0]
	return {"income": income, "expense": expense, "profit": income - expense, "orders": orders[0],
		"order_value": flt(orders[1]), "purchases": flt(purchases), "receipts": flt(receipts), "vouchers": vouchers}


def _checklist(fy):
	"""Year-end / period-close checks, SAP/Tally style."""
	company = _company()
	end = fy.year_end_date
	frozen = frappe.db.get_single_value("Accounts Settings", "acc_frozen_upto")
	next_exists = frappe.db.exists("Fiscal Year", {"year_start_date": add_days(end, 1)})
	pcv = frappe.db.get_value("Period Closing Voucher",
		{"company": company, "docstatus": 1, "period_end_date": ["between", [fy.year_start_date, end]]}, "name")
	drafts = {}
	for dt, date_field in (("Sales Invoice", "posting_date"), ("Purchase Invoice", "posting_date"),
			("Payment Entry", "posting_date"), ("Journal Entry", "posting_date"), ("Delivery Note", "posting_date"),
			("Purchase Receipt", "posting_date"), ("Stock Entry", "posting_date")):
		drafts[dt] = frappe.db.count(dt, {"docstatus": 0, date_field: ["between", [fy.year_start_date, end]]})
	unreconciled = frappe.db.count("Bank Transaction", {"docstatus": 1, "status": "Unreconciled",
		"date": ["between", [fy.year_start_date, end]]}) if frappe.db.exists("DocType", "Bank Transaction") else 0
	neg_stock = frappe.db.count("Bin", {"actual_qty": ["<", 0]})
	no_irn = 0
	if frappe.db.has_column("Sales Invoice", "irn"):
		no_irn = frappe.db.sql(
			"SELECT COUNT(*) FROM `tabSales Invoice` WHERE docstatus = 1 AND IFNULL(irn, '') = '' "
			"AND IFNULL(billing_address_gstin, '') != '' AND posting_date BETWEEN %s AND %s",
			(fy.year_start_date, end),
		)[0][0]
	items = [
		("Next financial year created", bool(next_exists), "Create it before the first entry of the new year."),
		("No draft vouchers left", sum(drafts.values()) == 0,
			", ".join(f"{v} {k}" for k, v in drafts.items() if v) or "All submitted or deleted."),
		("Bank lines reconciled", unreconciled == 0, f"{unreconciled} unreconciled bank lines."),
		("Every B2B invoice has an IRN", no_irn == 0, f"{no_irn} invoices without IRN."),
		("No negative stock", neg_stock == 0, f"{neg_stock} item-warehouse rows below zero."),
		("Books locked up to year end", bool(frozen and getdate(frozen) >= getdate(end)),
			f"Accounts frozen till {frozen or 'not set'}."),
		("Profit transferred (Period Closing Voucher)", bool(pcv), pcv or "Not yet posted."),
	]
	return [{"label": a, "ok": b, "detail": c} for a, b, c in items]


@frappe.whitelist()
def get_overview():
	frappe.only_for(_VIEW_ROLES)
	sel = selected_year()
	current = _current_year()
	years = []
	for fy in _years():
		row = dict(fy)
		row["is_current"] = bool(current and current.name == fy.name)
		row["is_selected"] = bool(sel and sel.name == fy.name)
		row["totals"] = _totals(fy)
		years.append(row)
	return {
		"years": years,
		"selected": sel.name if sel else None,
		"current": current.name if current else None,
		"frozen_upto": frappe.db.get_single_value("Accounts Settings", "acc_frozen_upto"),
		"checklist": _checklist(sel) if sel else [],
		"can_manage": bool(set(_MANAGER_ROLES) & set(frappe.get_roles())),
		"company": _company(),
	}


@frappe.whitelist()
def create_next_year():
	frappe.only_for(_MANAGER_ROLES)
	latest = frappe.get_all("Fiscal Year", fields=["name", "year_end_date"], order_by="year_end_date desc", limit=1)
	if not latest:
		frappe.throw(_("No financial year exists yet."))
	start = getdate(add_days(latest[0].year_end_date, 1))
	end = getdate(add_days(add_years(start, 1), -1))
	name = f"{start.year}-{end.year}"
	if frappe.db.exists("Fiscal Year", name):
		frappe.throw(_("Financial year {0} already exists.").format(name))
	fy = frappe.get_doc({"doctype": "Fiscal Year", "year": name, "year_start_date": start, "year_end_date": end,
		"companies": [{"company": _company()}]})
	fy.insert()
	return fy.name


@frappe.whitelist()
def lock_books(upto=None):
	"""Freeze all accounting entries up to a date (SAP posting-period close,
	Tally 'lock' of earlier vouchers). Blank unlocks."""
	frappe.only_for(_MANAGER_ROLES)
	settings = frappe.get_single("Accounts Settings")
	settings.acc_frozen_upto = upto or None
	if upto and not settings.frozen_accounts_modifier:
		settings.frozen_accounts_modifier = "Accounts Manager"
	settings.save()
	return settings.acc_frozen_upto

