frappe.query_reports["IB Reorder Rhythm"] = {
	filters: [
		{ fieldname: "lookback_days", label: __("Look back (days)"), fieldtype: "Int", default: 365 },
		{ fieldname: "min_orders", label: __("Min. order days"), fieldtype: "Int", default: 3 },
		{ fieldname: "status", label: __("Status"), fieldtype: "Select", options: "\nOverdue\nDue now\nOn rhythm" },
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "show_all", label: __("Show on-rhythm accounts too"), fieldtype: "Check" },
	],
	onload(report) {
		
	},
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (data.bold) value = `<b>${value}</b>`;
		if (column.fieldname === "status" && data.status) {
			const c = { Overdue: "red", "Due now": "orange", "On rhythm": "green" }[data.status];
			value = `<span class="indicator-pill ${c}">${data.status}</span>`;
		}
		return value;
	},
};
