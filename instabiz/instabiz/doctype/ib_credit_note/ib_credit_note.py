"""IB Credit Note — customer-side credit / sales return.

GL logic (on submit):
  Per item row:  DR income_account  /  CR Accounts Receivable  (item amount)
  Per tax row:   DR tax_account     /  CR Accounts Receivable  (tax amount)

Net: AR reduced by grand_total (pre-tax + GST).
Stock ledger entry created only for reason_code == "Sales Return".
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, nowtime
from erpnext.controllers.accounts_controller import AccountsController
from erpnext.accounts.general_ledger import make_gl_entries
from erpnext.accounts.party import get_party_account
from erpnext.stock.stock_ledger import make_sl_entries
from instabiz.overrides.utils import recalculate_items, LOCATION_WAREHOUSE, LOCATION_COST_CENTER


# ── GST template names (mirrors quotation.py) ────────────────────────────────
_GST_INSTATE  = "Output GST In-state - IB"
_GST_OUTSTATE = "Output GST Out-state - IB"


class IBCreditNote(AccountsController):
    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def validate(self) -> None:
        self._set_defaults()
        recalculate_items(self)
        self._set_total()
        self._set_taxes()
        self._validate_items()
        self._validate_against_invoice()
        self._check_duplicate()
        self._sync_status()

    def on_submit(self) -> None:
        self._sync_status()
        self.update_stock = 1 if self.reason_code == "Sales Return" else 0
        self.db_set("update_stock", self.update_stock)
        self._make_gl_entries(cancel=False)
        if self.update_stock:
            self._make_sl_entries(cancel=False)
        self.db_set("outstanding_amount", flt(self.grand_total, 2))

    def on_cancel(self) -> None:
        self.ignore_linked_doctypes = (
            "GL Entry",
            "Stock Ledger Entry",
            "Payment Ledger Entry",
            "Repost Item Valuation",
            "Repost Payment Ledger",
            "Repost Payment Ledger Items",
            "Repost Accounting Ledger",
            "Repost Accounting Ledger Items",
            "Unreconcile Payment",
            "Unreconcile Payment Entries",
        )
        # Re-read update_stock from DB (in-memory value may be stale on amend)
        update_stock = frappe.db.get_value(self.doctype, self.name, "update_stock") or 0
        self._make_gl_entries(cancel=True)
        if update_stock:
            self._make_sl_entries(cancel=True)
        self._sync_status()
        self.db_set("outstanding_amount", 0)

    # ── Defaults ──────────────────────────────────────────────────────────────

    def _set_defaults(self) -> None:
        if not self.posting_date:
            self.posting_date = frappe.utils.today()
        if not self.company:
            self.company = frappe.defaults.get_user_default("company") or frappe.db.get_single_value(
                "Global Defaults", "default_company"
            )

    def _get_company_gstin(self) -> str:
        """Fetch company GSTIN — required by india_compliance for GST account GL entries."""
        if self.against_sales_invoice:
            g = frappe.db.get_value("Sales Invoice", self.against_sales_invoice, "company_gstin")
            if g:
                return g
        row = frappe.db.sql(
            """SELECT addr.gstin FROM `tabAddress` addr
               JOIN `tabDynamic Link` dl ON dl.parent = addr.name
               WHERE dl.link_doctype = 'Company' AND dl.link_name = %s
                 AND addr.gstin IS NOT NULL AND addr.gstin != ''
               ORDER BY addr.is_primary_address DESC LIMIT 1""",
            self.company,
        )
        return row[0][0] if row else ""

    # ── Amounts ──────────────────────────────────────────────────────────────

    def _set_total(self) -> None:
        self.total = flt(sum(flt(r.amount) for r in self.items), 2)

    def _set_taxes(self) -> None:
        """Expand taxes_and_charges template and compute total_taxes_and_charges."""
        if not self.taxes_and_charges:
            self.total_taxes_and_charges = 0.0
            self.grand_total = self.total
            return

        template = frappe.get_cached_doc("Sales Taxes and Charges Template", self.taxes_and_charges)
        tax_total = 0.0
        for t in template.taxes:
            if t.charge_type == "On Net Total":
                tax_total += flt(self.total * flt(t.rate) / 100, 2)
            elif t.charge_type == "Actual":
                tax_total += flt(t.tax_amount, 2)
            # "On Previous Row Total" rows are ignored — uncommon in instabiz templates
        self.total_taxes_and_charges = flt(tax_total, 2)
        self.grand_total = flt(self.total + self.total_taxes_and_charges, 2)

    # ── Validation ────────────────────────────────────────────────────────────

    def _validate_items(self) -> None:
        if not self.items:
            frappe.throw(_("Add at least one item row."))
        for row in self.items:
            if flt(row.qty) <= 0:
                frappe.throw(_("Row {0}: Qty must be greater than 0.").format(row.idx))
            if not row.income_account:
                frappe.throw(_("Row {0}: Income Account is mandatory.").format(row.idx))

    def _validate_against_invoice(self) -> None:
        if not self.against_sales_invoice:
            if self.reason_code == "Sales Return":
                frappe.throw(_("Against Sales Invoice is mandatory for 'Sales Return'."))
            return

        si = frappe.db.get_value(
            "Sales Invoice",
            self.against_sales_invoice,
            ["grand_total", "customer", "docstatus"],
            as_dict=True,
        )
        if not si:
            frappe.throw(_("Sales Invoice {0} not found.").format(self.against_sales_invoice))
        if si.docstatus != 1:
            frappe.throw(
                _("Sales Invoice {0} must be Submitted before issuing a Credit Note.").format(
                    self.against_sales_invoice
                )
            )
        if si.customer != self.customer:
            frappe.throw(
                _("Customer on Credit Note must match Sales Invoice {0}.").format(
                    self.against_sales_invoice
                )
            )
        # Sum of all submitted CNs (excluding self) against this SI
        already_issued = flt(
            frappe.db.sql(
                """SELECT IFNULL(SUM(grand_total), 0)
                   FROM `tabIB Credit Note`
                   WHERE against_sales_invoice = %s
                     AND docstatus = 1
                     AND name != %s""",
                (self.against_sales_invoice, self.name or "__new__"),
            )[0][0]
        )
        if already_issued + flt(self.grand_total) > flt(si.grand_total) + 0.01:
            frappe.throw(
                _(
                    "Total Credit Notes ({0}) would exceed Sales Invoice amount ({1}). "
                    "Already issued: {2}."
                ).format(
                    frappe.format_value(already_issued + flt(self.grand_total), {"fieldtype": "Currency"}),
                    frappe.format_value(flt(si.grand_total), {"fieldtype": "Currency"}),
                    frappe.format_value(already_issued, {"fieldtype": "Currency"}),
                )
            )

    def _check_duplicate(self) -> None:
        """Block: same SI item row cannot have two submitted CNs."""
        if not self.against_sales_invoice:
            return
        for row in self.items:
            if not row.against_si_item:
                continue
            existing = frappe.db.get_value(
                "IB Credit Note Item",
                {
                    "against_si_item": row.against_si_item,
                    "docstatus": 1,
                    "parent": ["!=", self.name or "__new__"],
                },
                "parent",
            )
            if existing:
                frappe.throw(
                    _("Row {0}: SI item {1} already has a submitted Credit Note ({2}).").format(
                        row.idx, row.against_si_item, existing
                    )
                )

    def _sync_status(self) -> None:
        self.status = {0: "Draft", 1: "Submitted", 2: "Cancelled"}.get(self.docstatus, "Draft")

    # ── GL Entries ────────────────────────────────────────────────────────────

    def _location_cost_center(self) -> str:
        """Derive location cost center from item warehouse; falls back to company default."""
        warehouse_to_loc = {w: l for l, w in LOCATION_WAREHOUSE.items()}
        for row in self.items:
            loc = warehouse_to_loc.get(row.get("warehouse"))
            if loc:
                cc = LOCATION_COST_CENTER.get(loc)
                if cc:
                    return cc
        return frappe.db.get_value("Company", self.company, "cost_center") or ""

    def _make_gl_entries(self, cancel: bool = False) -> None:
        if not getattr(self, "company_gstin", None):
            self.company_gstin = self._get_company_gstin()
        # Real bug, fixed: get_party_account() is a LIVE lookup of the
        # customer's current receivable account — re-run on both submit and
        # cancel. If that mapping changes between the two (a real, separate
        # document a customer's own AR account can be repointed on at any
        # time), cancel's reversal posts against the NEW account instead of
        # the one actually debited/credited at submit, leaving the original
        # entry unreversed — a real GL imbalance. Cancel now reads back what
        # was actually posted; only submit re-derives fresh. (Same fix
        # applied to IB Expense / IB Debit Note for the identical gap.)
        if cancel and getattr(self, "posted_ar_account", None):
            ar_account = self.posted_ar_account
        else:
            ar_account = get_party_account("Customer", self.customer, self.company)
        cost_center = self._location_cost_center()
        remark = (self.remarks or "").strip() or (
            "Credit Note {name} against {si}".format(
                name=self.name, si=self.against_sales_invoice or "N/A"
            )
        )
        against_voucher_type = "Sales Invoice" if self.against_sales_invoice else self.doctype
        against_voucher = self.against_sales_invoice or self.name

        gl = []

        # ── Item rows: DR income / CR AR ─────────────────────────────────────
        for row in self.items:
            amt = flt(row.amount, 2)
            if not amt:
                continue
            gl.append(
                self.get_gl_dict(
                    {
                        "account": row.income_account,
                        "debit": amt,
                        "credit": 0.0,
                        "against": ar_account,
                        "cost_center": cost_center,
                        "remarks": remark,
                    }
                )
            )
            gl.append(
                self.get_gl_dict(
                    {
                        "account": ar_account,
                        "debit": 0.0,
                        "credit": amt,
                        "against": row.income_account,
                        "party_type": "Customer",
                        "party": self.customer,
                        "against_voucher_type": against_voucher_type,
                        "against_voucher": against_voucher,
                        "cost_center": cost_center,
                        "remarks": remark,
                    }
                )
            )

        # ── Tax rows: DR tax_account / CR AR ────────────────────────────────
        if self.taxes_and_charges and flt(self.total_taxes_and_charges):
            template = frappe.get_cached_doc("Sales Taxes and Charges Template", self.taxes_and_charges)
            for t in template.taxes:
                tax_amt = 0.0
                if t.charge_type == "On Net Total":
                    tax_amt = flt(self.total * flt(t.rate) / 100, 2)
                elif t.charge_type == "Actual":
                    tax_amt = flt(t.tax_amount, 2)
                if not tax_amt:
                    continue
                gl.append(
                    self.get_gl_dict(
                        {
                            "account": t.account_head,
                            "debit": tax_amt,
                            "credit": 0.0,
                            "against": ar_account,
                            "cost_center": cost_center,
                            "remarks": remark,
                        }
                    )
                )
                gl.append(
                    self.get_gl_dict(
                        {
                            "account": ar_account,
                            "debit": 0.0,
                            "credit": tax_amt,
                            "against": t.account_head,
                            "party_type": "Customer",
                            "party": self.customer,
                            "against_voucher_type": against_voucher_type,
                            "against_voucher": against_voucher,
                            "cost_center": cost_center,
                            "remarks": remark,
                        }
                    )
                )

        make_gl_entries(gl, cancel=cancel, adv_adj=False)

        if not cancel:
            frappe.db.set_value(self.doctype, self.name, "posted_ar_account", ar_account)

    # ── Stock Ledger Entries ──────────────────────────────────────────────────

    def _make_sl_entries(self, cancel: bool = False) -> None:
        sl = []
        for row in self.items:
            wh = row.warehouse or ""
            if not wh:
                frappe.throw(
                    _("Row {0}: Warehouse is required for Sales Return stock entry.").format(row.idx)
                )
            # Positive qty = stock received back from customer
            sl.append(
                frappe._dict(
                    {
                        "doctype": "Stock Ledger Entry",
                        "item_code": row.item_code,
                        "warehouse": wh,
                        "posting_date": self.posting_date,
                        "posting_time": nowtime(),
                        "voucher_type": self.doctype,
                        "voucher_no": self.name,
                        "voucher_detail_no": row.name,
                        "actual_qty": flt(row.qty) * (-1 if cancel else 1),
                        "incoming_rate": flt(
                            frappe.db.get_value("Item", row.item_code, "valuation_rate") or row.rate
                        ),
                        "company": self.company,
                        "is_cancelled": 1 if cancel else 0,
                    }
                )
            )
        if sl:
            make_sl_entries(sl)
