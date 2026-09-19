frappe.query_reports["IB Vendor Price History"] = {
	filters: [
		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
		{ fieldname: "supplier", label: __("Supplier"), fieldtype: "Link", options: "Supplier" },
		{ fieldname: "item_group", label: __("Item Group"), fieldtype: "Link", options: "Item Group" },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: frappe.datetime.add_months(frappe.datetime.get_today(), -12) },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "view", label: __("View"), fieldtype: "Select", options: "Lines\nBy Supplier", default: "Lines" },
		{ fieldname: "source", label: __("From"), fieldtype: "Select", options: "\nPurchase Order\nPurchase Invoice" },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && column.fieldname === "net_rate" && data._flag) {
			const c = data._flag === "high" ? "var(--red-500)" : "var(--green-600)";
			value = `<span style="color:${c};font-weight:600">${value}</span>`;
		}
		return value;
	},
};
