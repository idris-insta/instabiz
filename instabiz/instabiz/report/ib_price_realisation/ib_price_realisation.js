frappe.query_reports["IB Price Realisation"] = {
	filters: [
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: frappe.datetime.add_months(frappe.datetime.get_today(), -6) },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "view", label: __("View"), fieldtype: "Select", options: "Item\nCustomer", default: "Item" },
		{ fieldname: "item_group", label: __("Family"), fieldtype: "Link", options: "Item Group" },
		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "min_lines", label: __("Min. sale lines"), fieldtype: "Int", default: 3 },
	],
	onload(report) {
		
	},
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (data.bold) value = `<b>${value}</b>`;
		if (column.fieldname === "gap" && data.gap > 0) value = `<span style="color: var(--red-600)">${value}</span>`;
		return value;
	},
};
