frappe.query_reports["IB Party Ledger"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company",
			default: frappe.defaults.get_user_default("Company"), reqd: 1 },
		{ fieldname: "customer", label: __("Party"), fieldtype: "Link", options: "Customer", reqd: 1 },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date",
			default: erpnext.utils.get_fiscal_year(frappe.datetime.get_today(), true)[1] },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today() },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (data.bold) value = `<b>${value}</b>`;
		if (column.fieldname === "received" && data.received) value = `<span style="color: var(--green-600)">${value}</span>`;
		if (column.fieldname === "balance" && data.balance < 0) value = `<span style="color: var(--green-600)">${value}</span>`;
		return value;
	},
};
