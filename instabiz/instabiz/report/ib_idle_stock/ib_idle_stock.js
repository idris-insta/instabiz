frappe.query_reports["IB Idle Stock"] = {
	filters: [
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: frappe.datetime.add_months(frappe.datetime.get_today(), -6) },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "item_group", label: __("Family"), fieldtype: "Link", options: "Item Group" },
		{ fieldname: "warehouse", label: __("Warehouse"), fieldtype: "Link", options: "Warehouse" },
		{ fieldname: "cover_limit", label: __("Cover limit (months)"), fieldtype: "Float", default: 4 },
		{ fieldname: "show_moving", label: __("Show moving lines too"), fieldtype: "Check" },
	],
	onload(report) {
		
	},
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (data.bold) value = `<b>${value}</b>`;
		if (column.fieldname === "state" && data.state) {
			const c = { Dead: "red", Overstock: "orange", Slow: "yellow", Moving: "green" }[data.state] || "gray";
			value = `<span class="indicator-pill ${c}">${data.state}</span>`;
		}
		return value;
	},
};
