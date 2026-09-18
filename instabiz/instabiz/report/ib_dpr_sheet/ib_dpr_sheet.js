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
		if (frappe.user.has_role(["System Manager", "Factory Management"])) {
			report.page.add_inner_button(__("Fill from Production"), () => {
				frappe.prompt({ fieldname: "from_date", fieldtype: "Date", label: __("Completed on or after"), default: report.get_filter_value("from_date") },
					(v) => frappe.call({ method: "instabiz.overrides.dpr_auto.backfill", args: v, freeze: true,
						callback: (r) => { frappe.show_alert(r.message); report.refresh(); } }),
					__("Create DPR lines from completed production stages"));
			});
		}
	},
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && data.bold) value = `<b>${value}</b>`;
		return value;
	},
};
