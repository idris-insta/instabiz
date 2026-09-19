frappe.query_reports["IB Tally Export"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company",
			default: frappe.defaults.get_user_default("Company"), reqd: 1 },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: frappe.datetime.month_start(), reqd: 1 },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
		{ fieldname: "voucher_type", label: __("Voucher Type"), fieldtype: "Select",
			options: ["", "Sales Invoice", "Purchase Invoice", "Payment Entry", "Journal Entry", "Delivery Note",
				"Purchase Receipt", "Stock Entry", "IB Credit Note", "IB Debit Note", "IB Expense"].join("\n") },
		{ fieldname: "include_masters", label: __("Include ledger masters"), fieldtype: "Check", default: 1 },
	],
	onload(report) {
		report.page.add_inner_button(__("Download Tally XML"), () => {
			const v = report.get_values();
			frappe.call({
				method: "instabiz.overrides.tally_export.download",
				args: { company: v.company, from_date: v.from_date, to_date: v.to_date,
					voucher_types: v.voucher_type || null, include_masters: v.include_masters },
				freeze: true,
			}).then((r) => {
				const m = r.message;
				const a = document.createElement("a");
				a.href = URL.createObjectURL(new Blob([m.content], { type: "application/xml" }));
				a.download = m.filename;
				a.click();
				frappe.show_alert({ message: __("{0} vouchers exported", [m.count]), indicator: "green" });
				if (m.skipped.length) frappe.msgprint(__("Left out (not balanced): {0}", [m.skipped.join(", ")]));
			});
		}).addClass("btn-primary");
		report.page.add_inner_button(__("Ledger names"), () => frappe.set_route("Form", "IB Tally Export Settings"));
	},
};
