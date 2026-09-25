"""IB Expense — general company/operational expense (rent, utilities, misc
direct spend), not employee reimbursement (that's native ERPNext Expense
Claim, deliberately left unwired — see docs/superpowers/specs/
2026-08-27-expense-entry-design.md for the full design/decision trail).

GL logic (on submit), mirrors IB Credit Note / IB Debit Note's own pattern:
  DR expense_account                     amount
  CR mode_of_payment's account (Paid)    amount
     -- or --
  CR payable_account (Unpaid)            amount

HR Manager creates and submits directly (self-approval, same trust level
they already have on IB Full Final Settlement / Salary Slip) — Accounts
User can draft but not submit; Accounts Manager/System Manager have full
oversight rights.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt
from erpnext.controllers.accounts_controller import AccountsController
from erpnext.accounts.general_ledger import make_gl_entries
from erpnext.accounts.doctype.sales_invoice.sales_invoice import get_bank_cash_account

from instabiz.overrides.utils import LOCATION_COST_CENTER

# Deliberately created with a blank account_type (not "Payable") — ERPNext
# core (GL Entry.check_mandatory) requires party_type/party on every GL line
# against a real "Payable"-typed account, but paid_to here is free text by
# design (most of these aren't real Suppliers on file), so no party is ever
# set. Confirmed live: submitting against a "Payable"-typed account threw
# "Supplier is required against Payable account" before this was fixed.
_DEFAULT_PAYABLE_ACCOUNT = "Expenses Payable - IB"


class IBExpense(AccountsController):
	# ── Lifecycle ─────────────────────────────────────────────────────────────

	def validate(self) -> None:
		self._set_defaults()
		self._validate_payment_fields()
		self._sync_status()

	def on_submit(self) -> None:
		self._sync_status()
		self._make_gl_entries(cancel=False)

	def on_cancel(self) -> None:
		self.ignore_linked_doctypes = (
			"GL Entry",
			"Payment Ledger Entry",
			"Repost Accounting Ledger",
			"Repost Accounting Ledger Items",
			"Unreconcile Payment",
			"Unreconcile Payment Entries",
		)
		self._make_gl_entries(cancel=True)
		self._sync_status()

	# ── Defaults ──────────────────────────────────────────────────────────────

	def _set_defaults(self) -> None:
		if not self.posting_date:
			self.posting_date = frappe.utils.today()
		if not self.company:
			self.company = frappe.defaults.get_user_default("company") or frappe.db.get_single_value(
				"Global Defaults", "default_company"
			)
		if self.payment_status == "Unpaid" and not self.payable_account:
			if frappe.db.exists("Account", _DEFAULT_PAYABLE_ACCOUNT):
				self.payable_account = _DEFAULT_PAYABLE_ACCOUNT

	def _validate_payment_fields(self) -> None:
		if flt(self.amount) <= 0:
			frappe.throw(_("Amount must be greater than 0."))
		if not self.expense_account:
			frappe.throw(_("Expense Account is mandatory."))
		if frappe.db.get_value("Account", self.expense_account, "root_type") != "Expense":
			frappe.throw(_("{0} is not an Expense-type account.").format(self.expense_account))
		if self.payment_status == "Paid" and not self.mode_of_payment:
			frappe.throw(_("Mode of Payment is mandatory when Payment Status is Paid."))
		if self.payment_status == "Unpaid" and not self.payable_account:
			frappe.throw(_("Payable Account is mandatory when Payment Status is Unpaid."))

	def _sync_status(self) -> None:
		self.status = {0: "Draft", 1: "Submitted", 2: "Cancelled"}.get(self.docstatus, "Draft")

	# ── GL Entries ────────────────────────────────────────────────────────────

	def _cost_center(self) -> str:
		loc = (self.location or "").lower()
		cc = LOCATION_COST_CENTER.get(loc)
		if cc:
			return cc
		return frappe.db.get_value("Company", self.company, "cost_center") or ""

	def _credit_account(self) -> str:
		if self.payment_status == "Paid":
			bank_cash = get_bank_cash_account(self.mode_of_payment, self.company)
			account = bank_cash.get("account") if bank_cash else None
			if not account:
				frappe.throw(
					_("Could not resolve an account for Mode of Payment {0}.").format(self.mode_of_payment)
				)
			return account
		return self.payable_account

	def _make_gl_entries(self, cancel: bool = False) -> None:
		cost_center = self._cost_center()
		# Real bug, fixed: this used to call _credit_account() fresh on BOTH
		# submit and cancel — for Paid expenses that's a live Mode of Payment
		# -> account lookup (erpnext's get_bank_cash_account), a mapping that
		# lives on a separate document and can change at any time regardless
		# of this doc's own submitted state. If it changes between submit and
		# cancel, the cancel reversal posts against the NEW account instead
		# of the one actually debited/credited at submit — the original
		# entry never gets properly reversed, a real GL imbalance. Cancel now
		# reads back what was actually posted; only submit re-derives fresh.
		# (Same gap exists in IB Credit Note / IB Debit Note — not fixed here.)
		if cancel:
			credit_account = self.posted_credit_account or self._credit_account()
		else:
			credit_account = self._credit_account()
		amount = flt(self.amount, 2)
		remark = (self.remarks or "").strip() or (
			_("Expense {0} — {1}").format(self.name, self.description or "")
		)

		gl = [
			self.get_gl_dict(
				{
					"account": self.expense_account,
					"debit": amount,
					"credit": 0.0,
					"against": credit_account,
					"cost_center": cost_center,
					"remarks": remark,
				}
			),
		]

		# paid_to is deliberately free text (spec: "most of these aren't real
		# suppliers on file"), so no party/party_type is set on the credit
		# leg even when Unpaid — nothing to reconcile against a Party ledger.
		# against_voucher is still set so a later Payment Entry can find and
		# settle this specific expense.
		credit_row = {
			"account": credit_account,
			"debit": 0.0,
			"credit": amount,
			"against": self.expense_account,
			"cost_center": cost_center,
			"remarks": remark,
		}
		if self.payment_status == "Unpaid":
			credit_row["against_voucher_type"] = self.doctype
			credit_row["against_voucher"] = self.name
		gl.append(self.get_gl_dict(credit_row))

		make_gl_entries(gl, cancel=cancel, adv_adj=False)

		if not cancel:
			# Persist what was actually posted — apply_workflow-style pattern
			# this app already uses elsewhere (e.g. production_run.py) for a
			# field set during submit that a plain doc.save() might not
			# reliably carry through; explicit db.set_value is unambiguous.
			frappe.db.set_value(self.doctype, self.name, "posted_credit_account", credit_account)
