frappe.query_reports["IB Sales Forecast"] = {
	filters: [
		{ fieldname: "group_by", label: __("Forecast by"), fieldtype: "Select", options: "Total\nFamily\nItem\nCustomer\nSales Person", default: "Total" },
		{ fieldname: "months", label: __("Months ahead"), fieldtype: "Int", default: 3 },
		{ fieldname: "measure", label: __("Measure"), fieldtype: "Select", options: "Value\nQuantity", default: "Value" },
		{ fieldname: "item_group", label: __("Item Group"), fieldtype: "Link", options: "Item Group" },
		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "top_n", label: __("Top N"), fieldtype: "Int" },
	],
};
