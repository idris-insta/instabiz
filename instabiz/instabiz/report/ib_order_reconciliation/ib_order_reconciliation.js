frappe.query_reports["IB Order Reconciliation"] = {
	filters: [
		{ fieldname: "from_date", label: __("From"), fieldtype: "Date", default: frappe.datetime.add_months(frappe.datetime.get_today(), -3) },
		{ fieldname: "to_date", label: __("To"), fieldtype: "Date" },
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
		{ fieldname: "sales_order", label: __("Sales Order"), fieldtype: "Link", options: "Sales Order" },
		{ fieldname: "location", label: __("Location"), fieldtype: "Select", options: "\nMAHARASHTRA\nGUJARAT\nCHENNAI" },
		{ fieldname: "flag", label: __("Flag"), fieldtype: "Select",
			options: "\nDispatched more than produced\nDispatched without production\nOver-dispatched\nProduced short\nProduced over\nReady, not dispatched" },
		{ fieldname: "only_flagged", label: __("Only flagged"), fieldtype: "Check", default: 1 },
		{ fieldname: "production_only", label: __("Factory orders only"), fieldtype: "Check" },
		{ fieldname: "include_closed", label: __("Include closed orders"), fieldtype: "Check" },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "flag" && data && data.flag) {
			return `<span style="color:var(--red-600);font-weight:600">${value}</span>`;
		}
		return value;
	},
};
