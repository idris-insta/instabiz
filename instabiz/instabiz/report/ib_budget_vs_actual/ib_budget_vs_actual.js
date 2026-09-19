frappe.query_reports["IB Budget vs Actual"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "date", label: __("Month of"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "fiscal_year", label: __("Financial Year"), fieldtype: "Link", options: "Fiscal Year",
			default: (frappe.boot.ib_fiscal_year && frappe.boot.ib_fiscal_year.name) || undefined },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && ["month_pct", "ytd_pct"].includes(column.fieldname)) {
			const p = data[column.fieldname];
			const c = p >= 100 ? "var(--red-500)" : p >= 90 ? "var(--orange-500)" : "var(--green-600)";
			value = `<span style="color:${c};font-weight:600">${value}</span>`;
		}
		return value;
	},
	onload(report) {
		report.page.add_inner_button(__("Budgets"), () => frappe.set_route("List", "Budget"));
		report.page.add_inner_button(__("New Budget"), () => frappe.new_doc("Budget", { budget_against: "Cost Center" }));
	},
};
