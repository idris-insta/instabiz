/**
 * payment_entry_list.js
 * Sales User (only) gets the simplified "Record Payment" dialog instead of
 * Frappe's own "+ Add Payment Entry" route into the full native form
 * (2026-09-04, user request — see ib_simple_payment_dialog.js for why).
 * Accounts/Finance/Sales Manager/System Manager keep the standard button —
 * they need the full form's other scenarios (Supplier payments, Internal
 * Transfer, GST/tax-withholding fields) this dialog deliberately excludes.
 */
frappe.listview_settings["Payment Entry"] = {
	onload(listview) {
		const is_privileged = ["Sales Manager", "System Manager", "Accounts User", "Accounts Manager"]
			.some((r) => frappe.user.has_role(r));
		if (is_privileged) return;

		listview.page.set_primary_action(__("Record Payment"), () => {
			ib_show_simple_payment_dialog({
				on_success(name) {
					frappe.set_route("Form", "Payment Entry", name);
				},
			});
		}, "add");
	},
};
