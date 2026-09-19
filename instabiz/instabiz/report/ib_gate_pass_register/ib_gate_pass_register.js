frappe.query_reports["IB Gate Pass Register"] = {
	filters: [
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: frappe.datetime.month_start(), reqd: 1 },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
		{ fieldname: "gate_pass_type", label: __("In / Out"), fieldtype: "Select", options: "\nOutward\nInward" },
		{ fieldname: "purpose", label: __("Purpose"), fieldtype: "Select", options: "\nDelivery\nPurchase Receipt\nBranch Transfer\nReturnable\nNon-Returnable\nJob Work\nSample\nOther" },
		{ fieldname: "location", label: __("Location"), fieldtype: "Select", options: "\ngujarat\nmaharashtra\nchennai" },
		{ fieldname: "vehicle_no", label: __("Vehicle"), fieldtype: "Data" },
		{ fieldname: "only_pending", label: __("Only returnables still out"), fieldtype: "Check" },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && data.late && ["pending", "days_out"].includes(column.fieldname)) value = `<span class="text-danger bold">${value}</span>`;
		return value;
	},
};
