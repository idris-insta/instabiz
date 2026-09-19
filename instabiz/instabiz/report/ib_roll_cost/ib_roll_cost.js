frappe.query_reports["IB Roll Cost"] = {
	filters: [
		{ fieldname: "from_date", label: __("From"), fieldtype: "Date", default: frappe.datetime.add_months(frappe.datetime.get_today(), -3) },
		{ fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "view", label: __("View"), fieldtype: "Select", options: "Run\nItem", default: "Item" },
		{ fieldname: "location", label: __("Location"), fieldtype: "Select", options: "\ngujarat\nmaharashtra\nchennai" },
		{ fieldname: "item_group", label: __("Item Group"), fieldtype: "Link", options: "Item Group" },
		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && column.fieldname === "margin_pct" && data.margin_pct != null) {
			const c = data.margin_pct < 0 ? "var(--red-500)" : data.margin_pct < 10 ? "var(--orange-500)" : "var(--green-600)";
			value = `<span style="color:${c};font-weight:600">${value}</span>`;
		}
		return value;
	},
	onload(report) {
		report.page.add_inner_button(__("Machine costs"), () => frappe.set_route("List", "IB Machine"));
	},
};
