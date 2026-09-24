"""IB Debit Note — supplier-side debit / purchase return.

GL logic (on submit):
  Per item row:  DR Accounts Payable  /  CR expense_account  (item amount)
  Per tax row:   DR Accounts Payable  /  CR tax_account      (tax amount)

Net: AP reduced by grand_total (pre-tax + GST ITC reversal).
Stock ledger entry created only for reason_code == "Purchase Return".
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


class IBDebitNote(AccountsController):
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
        # Only a Purchase Return moves stock. "Short Receipt" goods never entered
        # stock (the PR recorded the received qty only), and purchase_rules.
        # make_short_claim already raises a Material Issue for claimed-but-received
        # goods — setting update_stock here deducted the same qty a second time.
        # "Import Variance" is a value-only adjustment.
        self.update_stock = 1 if self.reason_code == "Purchase Return" else 0
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
        if self.against_purchase_invoice:
            g = frappe.db.get_value("Purchase Invoice", self.against_purchase_invoice, "company_gstin")
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
        """Expand Purchase Taxes template and compute total_taxes_and_charges."""
        if not self.taxes_and_charges:
            self.total_taxes_and_charges = 0.0
            self.grand_total = self.total
            return

        template = frappe.get_cached_doc("Purchase Taxes and Charges Template", self.taxes_and_charges)
        tax_total = 0.0
        for t in template.taxes:
            if t.charge_type == "On Net Total":
                tax_total += flt(self.total * flt(t.rate) / 100, 2)
            elif t.charge_type == "Actual":
                tax_total += flt(t.tax_amount, 2)
        self.total_taxes_and_charges = flt(tax_total, 2)
        self.grand_total = flt(self.total + self.total_taxes_and_charges, 2)

    # ── Validation ────────────────────────────────────────────────────────────

    def _validate_items(self) -> None:
        if not self.items:
            frappe.throw(_("Add at least one item row."))
        for row in self.items:
            if flt(row.qty) <= 0:
                frappe.throw(_("Row {0}: Qty must be greater than 0.").format(row.idx))
            if not row.expense_account:
                frappe.throw(_("Row {0}: Expense Account is mandatory.").format(row.idx))

    def _validate_against_invoice(self) -> None:
        if not self.against_purchase_invoice:
            if self.reason_code == "Purchase Return":
                frappe.throw(_("Against Purchase Invoice is mandatory for 'Purchase Return'."))
            return

        pi = frappe.db.get_value(
            "Purchase Invoice",
            self.against_purchase_invoice,
            ["grand_total", "supplier", "docstatus"],
            as_dict=True,
        )
        if not pi:
            frappe.throw(_("Purchase Invoice {0} not found.").format(self.against_purchase_invoice))
        if pi.docstatus != 1:
            frappe.throw(
                _("Purchase Invoice {0} must be Submitted before issuing a Debit Note.").format(
                    self.against_purchase_invoice
                )
            )
        if pi.supplier != self.supplier:
            frappe.throw(
                _("Supplier on Debit Note must match Purchase Invoice {0}.").format(
                    self.against_purchase_invoice
                )
            )
        # Sum of all submitted DNs (excluding self) against this PI
        already_issued = flt(
            frappe.db.sql(
                """SELECT IFNULL(SUM(grand_total), 0)
                   FROM `tabIB Debit Note`
                   WHERE against_purchase_invoice = %s
                     AND docstatus = 1
                     AND name != %s""",
                (self.against_purchase_invoice, self.name or "__new__"),
            )[0][0]
        )
        if already_issued + flt(self.grand_total) > flt(pi.grand_total) + 0.01:
            frappe.throw(
                _(
                    "Total Debit Notes ({0}) would exceed Purchase Invoice amount ({1}). "
                    "Already issued: {2}."
                ).format(
                    frappe.format_value(already_issued + flt(self.grand_total), {"fieldtype": "Currency"}),
                    frappe.format_value(flt(pi.grand_total), {"fieldtype": "Currency"}),
                    frappe.format_value(already_issued, {"fieldtype": "Currency"}),
                )
            )

    def _check_duplicate(self) -> None:
        """Block: same PI item row cannot have two submitted DNs."""
        if not self.against_purchase_invoice:
            return
        for row in self.items:
            if not row.against_pi_item:
                continue
            existing = frappe.db.get_value(
                "IB Debit Note Item",
                {
                    "against_pi_item": row.against_pi_item,
                    "docstatus": 1,
                    "parent": ["!=", self.name or "__new__"],
                },
                "parent",
            )
            if existing:
                frappe.throw(
                    _("Row {0}: PI item {1} already has a submitted Debit Note ({2}).").format(
                        row.idx, row.against_pi_item, existing
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
        ap_account = get_party_account("Supplier", self.supplier, self.company)
        cost_center = self._location_cost_center()
        remark = (self.remarks or "").strip() or (
            "Debit Note {name} against {pi}".format(
                name=self.name, pi=self.against_purchase_invoice or "N/A"
            )
        )
        against_voucher_type = "Purchase Invoice" if self.against_purchase_invoice else self.doctype
        against_voucher = self.against_purchase_invoice or self.name

        gl = []

        # ── Item rows: DR AP / CR expense ────────────────────────────────────
        for row in self.items:
            amt = flt(row.amount, 2)
            if not amt:
                continue
            gl.append(
                self.get_gl_dict(
                    {
                        "account": ap_account,
                        "debit": amt,
                        "credit": 0.0,
                        "against": row.expense_account,
                        "party_type": "Supplier",
                        "party": self.supplier,
                        "against_voucher_type": against_voucher_type,
                        "against_voucher": against_voucher,
                        "cost_center": cost_center,
                        "remarks": remark,
                    }
                )
            )
            gl.append(
                self.get_gl_dict(
                    {
                        "account": row.expense_account,
                        "debit": 0.0,
                        "credit": amt,
                        "against": ap_account,
                        "cost_center": cost_center,
                        "remarks": remark,
                    }
                )
            )

        # ── Tax rows: DR AP / CR tax_account (ITC reversal) ──────────────────
        if self.taxes_and_charges and flt(self.total_taxes_and_charges):
            template = frappe.get_cached_doc("Purchase Taxes and Charges Template", self.taxes_and_charges)
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
                            "account": ap_account,
                            "debit": tax_amt,
                            "credit": 0.0,
                            "against": t.account_head,
                            "party_type": "Supplier",
                            "party": self.supplier,
                            "against_voucher_type": against_voucher_type,
                            "against_voucher": against_voucher,
                            "cost_center": cost_center,
                            "remarks": remark,
                        }
                    )
                )
                gl.append(
                    self.get_gl_dict(
                        {
                            "account": t.account_head,
                            "debit": 0.0,
                            "credit": tax_amt,
                            "against": ap_account,
                            "cost_center": cost_center,
                            "remarks": remark,
                        }
                    )
                )

        make_gl_entries(gl, cancel=cancel, adv_adj=False)

    # ── Stock Ledger Entries ──────────────────────────────────────────────────

    def _make_sl_entries(self, cancel: bool = False) -> None:
        sl = []
        for row in self.items:
            wh = row.warehouse or ""
            if not wh:
                frappe.throw(
                    _("Row {0}: Warehouse is required for Purchase Return stock entry.").format(row.idx)
                )
            # Negative qty = stock sent back to supplier
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
                        "actual_qty": flt(row.qty) * (1 if cancel else -1),
                        "incoming_rate": 0.0,
                        "company": self.company,
                        "is_cancelled": 1 if cancel else 0,
                    }
                )
            )
        if sl:
            make_sl_entries(sl)
