"""instabiz.overrides.billing_mode

Central switch for the "billing isn't live yet" workaround used across
revenue/AR/AP reporting (Sales Target, AR/AP Aging, Business Pulse, Main
Dashboard, Analytics Hub, Finance Dashboard, Party Outstanding Summary).

Real Sales/Purchase Invoices barely exist in this instance yet, so every
one of those was individually hardcoded to read Sales Order / Purchase
Order instead — each with its own comment, each done at a different time,
some only partially (e.g. a dashboard's revenue figure switched but its
AR/outstanding figure quietly left pointing at Sales Invoice, still
reading zero). That drift is exactly the bug this module exists to stop:
one flag, checked everywhere, so flipping to real invoicing later is a
one-line config change instead of re-auditing 7 files again.

Toggle via site_config.json:
    "ib_billing_mode": "dev"   — read Sales Order / Purchase Order (default)
    "ib_billing_mode": "prod"  — read Sales Invoice / Purchase Invoice

Defaults to "dev" because that's the true current state: Delivery Note and
Sales Invoice aren't part of the live workflow yet, so a Sales Order's own
`status` never moves past "Pending" — it carries no billing signal at all.
Revenue/AR/AP must be read off Sales Order / Purchase Order or the numbers
are just wrong, not "conservatively zero".
"""
import frappe


def is_dev_billing_mode():
	"""True when revenue/AR/AP should be computed from Sales Order / Purchase
	Order instead of Sales Invoice / Purchase Invoice."""
	return (frappe.conf.get("ib_billing_mode") or "dev").lower() != "prod"


def sales_doctype():
	"""Doctype to read for 'what was sold' / accounts receivable."""
	return "Sales Order" if is_dev_billing_mode() else "Sales Invoice"


def purchase_doctype():
	"""Doctype to read for 'what was bought' / accounts payable."""
	return "Purchase Order" if is_dev_billing_mode() else "Purchase Invoice"


def sales_total_expr(alias="so"):
	"""SQL expression for what the customer owes for a row, GST included.

	Sales Orders carry no GST rows (GST goes on the invoice); their
	custom_total_with_gst holds the invoice amount. Older orders that still
	had GST rows fall back to grand_total."""
	p = f"{alias}." if alias else ""
	if is_dev_billing_mode():
		return f"COALESCE(NULLIF({p}custom_total_with_gst, 0), {p}grand_total)"
	return f"{p}grand_total"


def sales_outstanding_expr(alias="so"):
	"""SQL expression for a Sales Order/Invoice row's outstanding amount.

	Sales Order has no native outstanding_amount (that's an invoice-only
	concept) — the closest real signal pre-invoice is grand_total minus
	whatever advance has actually been paid against it (custom_advance_paid,
	see payment_entry.py _update_so_advance). Sales Invoice already has a
	real outstanding_amount maintained by ERPNext itself.
	"""
	if is_dev_billing_mode():
		return f"({sales_total_expr(alias)} - COALESCE({alias}.custom_advance_paid, 0))"
	return f"{alias}.outstanding_amount"


def purchase_outstanding_expr(alias="po"):
	"""SQL expression for a Purchase Order/Invoice row's outstanding amount.

	No advance-paid tracking exists against Purchase Order (no equivalent
	of custom_advance_paid on the purchase side) — full grand_total is the
	best available approximation pre-invoice.
	"""
	if is_dev_billing_mode():
		return f"{alias}.grand_total"
	return f"{alias}.outstanding_amount"
