frappe.query_reports["IB Payment Register"] = {
	filters: [
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: frappe.datetime.month_start(), reqd: 1 },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
		{ fieldname: "direction", label: __("Direction"), fieldtype: "Select", options: "\nReceipts\nPayments\nInternal Transfer" },
		{ fieldname: "party_type", label: __("Party Type"), fieldtype: "Select", options: "\nCustomer\nSupplier\nEmployee\nShareholder" },
		{ fieldname: "party", label: __("Party"), fieldtype: "Dynamic Link", options: "party_type" },
		{ fieldname: "mode_of_payment", label: __("Mode"), fieldtype: "Link", options: "Mode of Payment" },
		{ fieldname: "account", label: __("Bank / Cash Account"), fieldtype: "Link", options: "Account",
			get_query: () => ({ filters: { account_type: ["in", ["Bank", "Cash"]], is_group: 0 } }) },
		{ fieldname: "branch", label: __("Branch"), fieldtype: "Link", options: "Branch" },
		{ fieldname: "sales_person", label: __("Sales Person"), fieldtype: "Link", options: "User" },
		{ fieldname: "min_amount", label: __("Min Amount"), fieldtype: "Currency" },
		{ fieldname: "group_by", label: __("Group By"), fieldtype: "Select",
			options: "\nParty\nMode of Payment\nBank / Cash Account\nBranch\nSales Person\nDay\nMonth" },
	],
};
