frappe.query_reports["IB Day Book"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company",
			default: frappe.defaults.get_user_default("Company"), reqd: 1 },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
		{ fieldname: "voucher_type", label: __("Voucher Type"), fieldtype: "Select",
			options: ["", "Sales Invoice", "Purchase Invoice", "Payment Entry", "Journal Entry", "Delivery Note",
				"Purchase Receipt", "Stock Entry", "Stock Reconciliation", "IB Credit Note", "IB Debit Note", "IB Expense"].join("\n") },
		{ fieldname: "party", label: __("Party"), fieldtype: "Data" },
	],
};
