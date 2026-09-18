frappe.query_reports["IB DPR Sheet"] = {
	filters: [
		{ fieldname: "view", label: __("Sheet"), fieldtype: "Select", reqd: 1, default: "Summary",
			options: ["Summary", "Coating", "Slitting", "Rewinding", "Cutting", "Silicon", "Packing"].join("\n") },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
		{ fieldname: "location", label: __("Location"), fieldtype: "Select", options: "\ngujarat\nmaharashtra\nchennai" },
		{ fieldname: "shift", label: __("Shift"), fieldtype: "Select", options: "\nDay\nNight" },
		{ fieldname: "machine", label: __("Machine"), fieldtype: "Link", options: "IB Machine" },
	],
	onload(report) {
		report.page.add_inner_button(__("New DPR Line"), () => frappe.new_doc("IB DPR Entry"));
	},
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && data.bold) value = `<b>${value}</b>`;
		return value;
	},
};
