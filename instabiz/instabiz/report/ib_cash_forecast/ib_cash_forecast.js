frappe.query_reports["IB Cash Forecast"] = {
	filters: [
		{ fieldname: "weeks", label: __("Weeks ahead"), fieldtype: "Int", default: 12 },
		{ fieldname: "credit_days", label: __("Credit days (orders without invoice)"), fieldtype: "Int", default: 30 },
		{ fieldname: "adjust_for_delay", label: __("Push by how late each customer pays"), fieldtype: "Check", default: 1 },
		{ fieldname: "show", label: __("Show"), fieldtype: "Select", options: "Weeks\nDocuments", default: "Weeks" },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && ["closing", "net"].includes(column.fieldname) && data[column.fieldname] < 0) value = `<span class="text-danger">${value}</span>`;
		return value;
	},
};
