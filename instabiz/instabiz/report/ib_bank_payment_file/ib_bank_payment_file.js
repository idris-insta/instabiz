frappe.query_reports["IB Bank Payment File"] = {
	filters: [
		{ fieldname: "source", label: __("Pay"), fieldtype: "Select", options: "Salary\nVendor", default: "Salary", reqd: 1 },
		{ fieldname: "month", label: __("Salary Month"), fieldtype: "Date", default: frappe.datetime.month_start(),
			depends_on: "eval:doc.source=='Salary'" },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: frappe.datetime.get_today(),
			depends_on: "eval:doc.source=='Vendor'" },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today(),
			depends_on: "eval:doc.source=='Vendor'" },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "problem" && data && data.problem) value = `<span class="text-danger">${value}</span>`;
		return value;
	},
	onload(report) {
		report.page.add_inner_button(__("Download Bank File"), () => {
			frappe.call({
				method: "instabiz.overrides.bank_payment_file.download",
				args: report.get_values(),
				freeze: true,
			}).then((r) => {
				const m = r.message;
				const blob = new Blob([m.content], { type: "text/csv" });
				const a = document.createElement("a");
				a.href = URL.createObjectURL(blob);
				a.download = m.filename;
				a.click();
				frappe.show_alert({ message: __("{0} payments, {1}", [m.count, format_currency(m.total)]), indicator: "green" });
			});
		}).addClass("btn-primary");
	},
};
