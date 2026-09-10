/**
 * ib_simple_payment_dialog.js — global (app_include_js)
 *
 * Simplified Payment Entry capture for Sales Users (2026-09-04, user
 * request). The real native Payment Entry form has ~34 conditionally-shown
 * fields — built for Accounts/Finance staff handling every scenario
 * (Receive/Pay/Internal Transfer, Customer/Supplier/Employee, GST tax
 * templates, tax withholding, bank reconciliation). Sales Users only ever
 * do one thing — receive an on-account payment from a customer they
 * handle — and are already locked server-side to exactly that (see
 * overrides/payment_entry.py enforce_sales_user_own_customer). This dialog
 * shows every field that scenario needs, always, with no cascade, and
 * presets what's presettable — instead of unhiding the general form (which
 * would also surface fields that don't apply, like a Supplier tax
 * template, for every user including Accounts/Finance staff who rely on
 * the guided flow for the scenarios this dialog doesn't cover).
 *
 * ib_show_simple_payment_dialog(opts):
 *   opts.customer        - Customer name, pre-filled. If provided without
 *                           opts.lock_customer, still editable.
 *   opts.lock_customer    - true to make the Customer field read-only
 *                           (called from a Sales Order's own context).
 *   opts.advance_for_so   - Sales Order name, silently attached, not shown
 *                           as a separate field (matches the existing
 *                           "Record Advance" flow, item 119).
 *   opts.on_success(name) - called with the new Payment Entry name.
 */
function ib_show_simple_payment_dialog(opts) {
	opts = opts || {};

	const d = new frappe.ui.Dialog({
		title: __("Record Payment"),
		fields: [
			{
				fieldname: "customer",
				fieldtype: "Link",
				label: __("Customer"),
				options: "Customer",
				reqd: 1,
				default: opts.customer || "",
				read_only: !!opts.lock_customer,
				get_query() {
					// Same scoping as the server-side write guard — a Sales
					// User only ever sees their own customers here, so the
					// dialog can't even offer a value the backend would
					// reject. Managers/Accounts see every customer.
					const privileged = ["Sales Manager", "System Manager", "Accounts User", "Accounts Manager"]
						.some((r) => frappe.user.has_role(r));
					if (privileged) return {};
					return { filters: { custom_sales_person_user: frappe.session.user } };
				},
			},
			{ fieldtype: "Column Break" },
			{
				fieldname: "posting_date",
				fieldtype: "Date",
				label: __("Date"),
				reqd: 1,
				default: frappe.datetime.get_today(),
			},
			{ fieldtype: "Section Break" },
			{
				fieldname: "amount",
				fieldtype: "Currency",
				label: __("Amount Received"),
				reqd: 1,
			},
			{ fieldtype: "Column Break" },
			{
				fieldname: "paid_to",
				fieldtype: "Link",
				label: __("Deposit To (Bank Account)"),
				options: "Account",
				reqd: 1,
				default: "50200023672503 - HDFC - MH & GJ - IB",
				get_query() {
					return { filters: { account_type: "Bank", is_group: 0, company: frappe.defaults.get_default("company") } };
				},
			},
			{ fieldtype: "Section Break" },
			{
				fieldname: "mode_of_payment",
				fieldtype: "Link",
				label: __("Mode of Payment"),
				options: "Mode of Payment",
			},
			{ fieldtype: "Column Break" },
			{
				fieldname: "reference_no",
				fieldtype: "Data",
				label: __("Cheque / Reference No"),
				reqd: 1,
				description: __("Cheque number, UTR, transaction ID — or just \"CASH\" for a cash receipt. Required by accounting for any bank deposit."),
			},
			{ fieldtype: "Section Break" },
			{
				fieldname: "reference_date",
				fieldtype: "Date",
				label: __("Cheque / Reference Date"),
				reqd: 1,
				default: frappe.datetime.get_today(),
			},
			{ fieldtype: "Column Break" },
			{
				fieldname: "payment_proof",
				fieldtype: "Attach",
				label: __("Payment Proof"),
				description: __("Screenshot, UTR, bank statement — for UPI/NEFT/RTGS/cheque, attach proof of the transaction."),
			},
			{ fieldtype: "Section Break" },
			{
				fieldname: "remarks",
				fieldtype: "Small Text",
				label: __("Remarks"),
			},
		],
		primary_action_label: __("Save"),
		primary_action(values) {
			d.get_primary_btn().prop("disabled", true);
			frappe.call({
				method: "instabiz.overrides.payment_entry.create_simple_customer_receipt",
				args: {
					customer: values.customer,
					amount: values.amount,
					paid_to: values.paid_to,
					mode_of_payment: values.mode_of_payment,
					reference_no: values.reference_no,
					reference_date: values.reference_date,
					remarks: values.remarks,
					posting_date: values.posting_date,
					advance_for_so: opts.advance_for_so,
					payment_proof: values.payment_proof,
				},
				callback(r) {
					if (!r.message) {
						d.get_primary_btn().prop("disabled", false);
						return;
					}
					frappe.show_alert({ message: __("Payment recorded"), indicator: "green" });
					d.hide();
					if (opts.on_success) opts.on_success(r.message.name);
				},
				error() {
					d.get_primary_btn().prop("disabled", false);
				},
			});
		},
	});

	d.show();
}
