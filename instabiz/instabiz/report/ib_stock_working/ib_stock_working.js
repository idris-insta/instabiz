frappe.query_reports["IB Stock Working"] = {
	filters: [
		{ fieldname: "view", label: __("View"), fieldtype: "Select", options: "Summary\nLedger", default: "Summary" },
		{ fieldname: "item_code", label: __("Material"), fieldtype: "Link", options: "Item" },
		{ fieldname: "item_group", label: __("Item Group"), fieldtype: "Link", options: "Item Group" },
		{ fieldname: "warehouse", label: __("Warehouse"), fieldtype: "Link", options: "Warehouse" },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "hide_zero", label: __("Hide zero stock"), fieldtype: "Check", default: 1 },
		{ fieldname: "by_warehouse", label: __("Warehouse-wise"), fieldtype: "Check", default: 1 },
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
