frappe.query_reports["IB Dormant Accounts"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "kind", label: __("Show"), fieldtype: "Select", options: "Ledgers\nCustomers\nSuppliers", default: "Customers" },
		{ fieldname: "days", label: __("No entry for (days)"), fieldtype: "Int", default: 180 },
		{ fieldname: "min_balance", label: __("Balance at least"), fieldtype: "Currency" },
		{ fieldname: "include_zero", label: __("Include zero balance"), fieldtype: "Check" },
	],
};
