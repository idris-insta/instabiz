frappe.query_reports["IB Consignment Profitability"] = {
	filters: [
		{ fieldname: "view", label: __("View"), fieldtype: "Select", options: "Container\nContainer Line", default: "Container" },
		{ fieldname: "container", label: __("Container"), fieldtype: "Link", options: "IB Container Import" },
		{ fieldname: "supplier", label: __("Supplier"), fieldtype: "Link", options: "Supplier" },
		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
		{ fieldname: "from_date", label: __("Imported From"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("Imported To"), fieldtype: "Date" },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && ["profit", "margin_pct"].includes(column.fieldname) && data[column.fieldname] < 0) value = `<span class="text-danger">${value}</span>`;
		return value;
	},
};
