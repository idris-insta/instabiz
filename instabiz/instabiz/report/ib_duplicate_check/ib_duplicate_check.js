frappe.query_reports["IB Duplicate Check"] = {
	filters: [
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: frappe.datetime.add_months(frappe.datetime.get_today(), -3), reqd: 1 },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
		{ fieldname: "doctype", label: __("Type"), fieldtype: "Select", options: "\nPurchase Invoice\nPayment Entry" },
	],
};
