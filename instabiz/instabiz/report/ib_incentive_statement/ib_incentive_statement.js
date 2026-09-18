frappe.query_reports["IB Incentive Statement"] = {
	filters: [
		{ fieldname: "view", label: __("View"), fieldtype: "Select", options: "Month\nYear", default: "Month" },
		{ fieldname: "month", label: __("Month"), fieldtype: "Date", default: frappe.datetime.month_start(), reqd: 1 },
		{ fieldname: "sales_person", label: __("Sales Person"), fieldtype: "Link", options: "User" },
		{ fieldname: "deduct_unpaid", label: __("Deduct unpaid (receivable)"), fieldtype: "Check" },
	],
	onload(report) {
		report.page.add_inner_button(__("Incentive Scales"), () => frappe.set_route("List", "IB Incentive Scale"));
	},
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (data.bold) value = `<b>${value}</b>`;
		
		return value;
	},
};
