frappe.query_reports["IB Cross Sell"] = {
	filters: [
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: frappe.datetime.add_months(frappe.datetime.get_today(), -12) },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "view", label: __("View"), fieldtype: "Select", options: "Customer\nPairs", default: "Customer" },
		{ fieldname: "family", label: __("Buys family"), fieldtype: "Link", options: "Item Group" },
		{ fieldname: "single_family", label: __("Single-family accounts only"), fieldtype: "Check" },
	],
	onload(report) {
		
	},
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (data.bold) value = `<b>${value}</b>`;
		
		return value;
	},
};
