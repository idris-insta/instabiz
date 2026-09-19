frappe.ui.form.on("IB Employee Loan", {
	refresh(frm) {
		if (frm.doc.docstatus === 1 && frm.doc.status === "Active") {
			frm.add_custom_button(__("Skip a Month"), () => {
				const pending = (frm.doc.schedule || []).filter((r) => r.status === "Pending");
				frappe.prompt({ fieldtype: "Select", fieldname: "row", label: __("Instalment"), reqd: 1,
					options: pending.map((r) => ({ value: r.name, label: `${frappe.datetime.str_to_user(r.payroll_month)} — ${format_currency(r.amount)}` })) },
				(v) => frappe.call("instabiz.instabiz.doctype.ib_employee_loan.ib_employee_loan.skip_month",
					{ loan: frm.doc.name, row_name: v.row }).then(() => frm.reload_doc()),
				__("Skip which month?"));
			});
			if (!frm.doc.payment_entry) {
				frm.add_custom_button(__("Pay Out"), () =>
					frappe.new_doc("Payment Entry", { payment_type: "Pay", party_type: "Employee", party: frm.doc.employee,
						paid_amount: frm.doc.amount, received_amount: frm.doc.amount, remarks: __("Loan {0}", [frm.doc.name]) }));
			}
		}
		if (frm.doc.docstatus === 1) {
			frm.dashboard.add_indicator(__("Recovered {0}", [format_currency(frm.doc.recovered_amount)]), "green");
			frm.dashboard.add_indicator(__("Balance {0}", [format_currency(frm.doc.balance_amount)]), frm.doc.balance_amount > 0 ? "orange" : "green");
		}
	},
	amount: preview,
	instalments: preview,
	repayment_start: preview,
});

function preview(frm) {
	if (frm.doc.amount && frm.doc.instalments) frm.set_value("emi", Math.round(frm.doc.amount / frm.doc.instalments));
}
