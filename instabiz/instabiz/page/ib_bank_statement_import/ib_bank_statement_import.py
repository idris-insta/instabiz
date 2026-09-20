"""IB Bank Statement Import — generic CSV column-mapper (any bank), creates Bank
Transaction records, and auto-creates + reconciles a Payment Entry against any
transaction whose amount confidently matches exactly one open Sales/Purchase
document. Everything else is left as an unreconciled Bank Transaction for the
native Bank Reconciliation Tool.
"""
import csv
import io
import json
import re
from datetime import datetime

import frappe
from frappe import _
from frappe.utils import flt

from erpnext.accounts.doctype.bank_reconciliation_tool.bank_reconciliation_tool import (
	create_payment_entry_bts,
	reconcile_vouchers,
)

from instabiz.overrides.billing_mode import (
	purchase_doctype,
	purchase_outstanding_expr,
	sales_doctype,
	sales_outstanding_expr,
)


def _parse_amount(val):
	"""Remove Indian-format commas and return float."""
	if not val:
		return 0.0
	return flt(re.sub(r",", "", str(val).strip()))


def _parse_date(val):
	"""DD/MM/YYYY → YYYY-MM-DD (also accepts a few other common export formats)."""
	val = str(val).strip()
	for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%m/%d/%Y"):
		try:
			return datetime.strptime(val, fmt).strftime("%Y-%m-%d")
		except ValueError:
			continue
	frappe.throw(_("Cannot parse date: {0}").format(val))


def _find_header_row(lines):
	"""Return index of the CSV header row — the first row containing at least
	two non-empty cells, used as a best-effort skip past bank letterhead/summary
	junk rows that precede the real column headers in most bank exports."""
	for i, line in enumerate(lines):
		cells = [c.strip() for c in line.split(",") if c.strip()]
		if len(cells) >= 3:
			return i
	frappe.throw(_("Could not find a header row in this file."))


@frappe.whitelist()
def get_csv_headers(csv_text):
	"""Return raw column headers + a few sample rows, for the column-mapping UI."""
	# Every other RPC in this file guards on Bank Transaction/IB Bank Import
	# Profile permission — this one didn't. Low real impact (csv_text is
	# caller-supplied, nothing server-side is disclosed), but any
	# authenticated user could call it; guarded for consistency.
	frappe.has_permission("Bank Transaction", "create", throw=True)
	lines = csv_text.splitlines()
	hdr_idx = _find_header_row(lines)
	reader = csv.DictReader(io.StringIO("\n".join(lines[hdr_idx:])))
	headers = reader.fieldnames or []
	samples = []
	for row in reader:
		samples.append(row)
		if len(samples) >= 3:
			break
	return {"headers": headers, "samples": samples}


@frappe.whitelist()
def get_saved_profile(bank_account):
	"""Return this bank account's saved column-mapping profile, if any."""
	frappe.has_permission("IB Bank Import Profile", "read", throw=True)
	if not frappe.db.exists("IB Bank Import Profile", bank_account):
		return None
	return frappe.get_doc("IB Bank Import Profile", bank_account).as_dict()


@frappe.whitelist()
def save_profile(bank_account, profile):
	"""Create/update the column-mapping profile for this bank account, so future
	imports for the same bank skip the mapping step entirely."""
	frappe.has_permission("IB Bank Import Profile", "write", throw=True)
	if isinstance(profile, str):
		profile = frappe.parse_json(profile)

	fields = ["mode", "col_date", "col_description", "col_reference",
	          "col_debit", "col_credit", "col_amount", "col_type", "credit_indicator"]
	if frappe.db.exists("IB Bank Import Profile", bank_account):
		doc = frappe.get_doc("IB Bank Import Profile", bank_account)
	else:
		doc = frappe.new_doc("IB Bank Import Profile")
		doc.bank_account = bank_account

	for f in fields:
		doc.set(f, profile.get(f))
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"name": doc.name}


def _parse_csv_with_profile(csv_text, profile):
	"""Parse CSV using an explicit column mapping (no per-bank guessing).

	profile: dict with mode ("Separate Debit/Credit Columns" | "Single Amount
	Column"), col_date, col_description, col_reference, and either
	(col_debit, col_credit) or (col_amount, col_type, credit_indicator).
	"""
	lines = csv_text.splitlines()
	hdr_idx = _find_header_row(lines)
	reader = csv.DictReader(io.StringIO("\n".join(lines[hdr_idx:])))

	mode = profile.get("mode")
	col_date = profile.get("col_date")
	col_desc = profile.get("col_description")
	col_ref = profile.get("col_reference")
	col_debit = profile.get("col_debit")
	col_credit = profile.get("col_credit")
	col_amount = profile.get("col_amount")
	col_type = profile.get("col_type")
	credit_indicator = (profile.get("credit_indicator") or "").strip().lower()

	rows = []
	for row in reader:
		raw_date = (row.get(col_date) or "").strip()
		if not raw_date:
			continue
		try:
			date = _parse_date(raw_date)
		except Exception:
			continue

		description = (row.get(col_desc) or "").strip() if col_desc else ""
		reference_no = (row.get(col_ref) or "").strip() if col_ref else ""

		if mode == "Single Amount Column":
			amt = _parse_amount(row.get(col_amount))
			if col_type:
				is_credit = (row.get(col_type) or "").strip().lower() == credit_indicator
				withdrawal = 0.0 if is_credit else abs(amt)
				deposit = abs(amt) if is_credit else 0.0
			else:
				# Signed amount convention: positive = credit/deposit, negative = debit/withdrawal.
				withdrawal = abs(amt) if amt < 0 else 0.0
				deposit = amt if amt > 0 else 0.0
		else:
			withdrawal = _parse_amount(row.get(col_debit)) if col_debit else 0.0
			deposit = _parse_amount(row.get(col_credit)) if col_credit else 0.0

		if withdrawal == 0 and deposit == 0:
			continue

		rows.append({
			"date":             date,
			"description":      description,
			"reference_number": reference_no,
			"withdrawal":       withdrawal,
			"deposit":          deposit,
		})

	return rows


@frappe.whitelist()
def preview_statement(bank_account, csv_text, profile):
	"""Return parsed rows for client-side preview table."""
	frappe.has_permission("Bank Transaction", "create", throw=True)
	if isinstance(profile, str):
		profile = frappe.parse_json(profile)
	rows = _parse_csv_with_profile(csv_text, profile)
	return {
		"rows":          rows,
		"count":         len(rows),
		"total_deposit": sum(r["deposit"] for r in rows),
		"total_withdrawal": sum(r["withdrawal"] for r in rows),
	}


def _find_confident_match(amount, receiving, company=None):
	"""Exactly one open Sales/Purchase document with this outstanding amount,
	system-wide (scoped to the bank's own company, if given) — anything less
	certain (0 or 2+ candidates) is left for manual reconciliation via the
	native Bank Reconciliation Tool. Respects instabiz.overrides.billing_mode
	so this matches against Sales/Purchase Order in dev mode (billing isn't
	live) the same way the rest of the app does.

	Company filter: `import_statement()` already resolves the bank account's
	own company but never passed it down here, so a deposit could in principle
	auto-match an open order/invoice belonging to a different company (single-
	company today, so currently a no-op in practice — kept as a real guard,
	not dead code, since this app's own per-location accounting has been
	moving toward stricter separation, see the per-location stock account
	work). Left unscoped (None) only preserves the prior no-filter behavior
	for any caller that doesn't have a company to hand.
	"""
	if receiving:
		dt, expr, party_field, party_type = sales_doctype(), sales_outstanding_expr("t"), "customer", "Customer"
	else:
		dt, expr, party_field, party_type = purchase_doctype(), purchase_outstanding_expr("t"), "supplier", "Supplier"

	company_cond = "AND t.company = %(company)s" if company else ""
	rows = frappe.db.sql(
		f"""
		SELECT t.name, t.{party_field} AS party
		FROM `tab{dt}` t
		WHERE t.docstatus = 1 AND ROUND({expr}, 2) = %(amount)s
		{company_cond}
		""",
		{"amount": round(flt(amount), 2), "company": company},
		as_dict=True,
	)
	if len(rows) == 1 and rows[0].party:
		return rows[0].name, rows[0].party, party_type, dt
	return None, None, None, None


def _try_auto_match(bt_name, date, company=None):
	"""Best-effort — never blocks the import if matching/PE-creation fails.

	Builds the Payment Entry via ERPNext's own create_payment_entry_bts (proven
	account/currency/exchange-rate resolution) with allow_edit=True so it's
	returned unsaved, then attaches an explicit, fully-allocated reference to
	the one specific document that matched — rather than relying on
	instabiz.overrides.payment_entry._auto_reconcile's generic FIFO fallback,
	which only handles Receive/Customer against Sales Invoice and would miss
	both Sales-Order-based dev-mode billing and the entire Purchase/Pay side.
	"""
	try:
		bt = frappe.db.get_value(
			"Bank Transaction", bt_name, ["deposit", "withdrawal", "reference_number"], as_dict=True
		)
		amount = bt.deposit or bt.withdrawal
		if not amount:
			return False

		doc_name, party, party_type, ref_doctype = _find_confident_match(
			amount, receiving=bool(bt.deposit), company=company
		)
		if not party:
			return False

		pe = create_payment_entry_bts(
			bt_name,
			reference_number=bt.reference_number or bt_name,
			reference_date=date,
			posting_date=date,
			party_type=party_type,
			party=party,
			allow_edit=True,
		)
		pe.append("references", {
			"reference_doctype": ref_doctype,
			"reference_name": doc_name,
			"total_amount": amount,
			"outstanding_amount": amount,
			"allocated_amount": amount,
		})
		pe.insert(ignore_permissions=True)
		pe.submit()

		# Link the Bank Transaction itself to this Payment Entry — without this,
		# the PE exists and is correctly allocated, but the transaction still
		# shows Unreconciled/unallocated in the native Bank Reconciliation Tool.
		reconcile_vouchers(bt_name, json.dumps([
			{"payment_doctype": "Payment Entry", "payment_name": pe.name, "amount": amount},
		]))
		return True
	except Exception as e:
		frappe.log_error("IB Bank Auto-Match", f"{bt_name}: {e}")
		return False


@frappe.whitelist()
def import_statement(bank_account, csv_text, profile):
	"""
	Parse CSV (via the given column-mapping profile) and create Bank Transaction
	records. Skips rows where (bank_account + date + reference_number + deposit +
	withdrawal) already exists to prevent duplicates. For each new transaction,
	attempts a confident auto-match to an open Sales/Purchase document and, if
	found, creates + submits + reconciles a Payment Entry against it.
	"""
	frappe.has_permission("Bank Transaction", "create", throw=True)
	if isinstance(profile, str):
		profile = frappe.parse_json(profile)

	company = frappe.db.get_value("Bank Account", bank_account, "company")
	if not company:
		frappe.throw(_("Bank Account {0} not found or has no company.").format(bank_account))

	rows = _parse_csv_with_profile(csv_text, profile)
	created = 0
	skipped = 0
	auto_matched = 0
	errors = []

	for r in rows:
		filters = {
			"bank_account": bank_account,
			"date":         r["date"],
			"deposit":      r["deposit"],
			"withdrawal":   r["withdrawal"],
		}
		if r["reference_number"]:
			filters["reference_number"] = r["reference_number"]

		if frappe.db.exists("Bank Transaction", filters):
			skipped += 1
			continue

		try:
			bt = frappe.new_doc("Bank Transaction")
			bt.bank_account      = bank_account
			bt.company           = company
			bt.date              = r["date"]
			bt.description       = r["description"]
			bt.reference_number  = r["reference_number"]
			bt.deposit           = r["deposit"]
			bt.withdrawal        = r["withdrawal"]
			bt.currency          = frappe.db.get_value("Company", company, "default_currency") or "INR"
			bt.status            = "Pending"
			bt.insert(ignore_permissions=True)
			bt.submit()
			created += 1
			if _try_auto_match(bt.name, r["date"], company=company):
				auto_matched += 1
		except Exception as e:
			errors.append({"row": r, "error": str(e)})

	frappe.db.commit()
	return {"created": created, "skipped": skipped, "auto_matched": auto_matched, "errors": errors}
