frappe.query_reports["IB Range Review"] = {
	filters: [
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: frappe.datetime.add_months(frappe.datetime.get_today(), -6) },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "group_by", label: __("Group By"), fieldtype: "Select", options: "Item\nFamily\nColour", default: "Item" },
		{ fieldname: "item_group", label: __("Family"), fieldtype: "Link", options: "Item Group" },
		{ fieldname: "warehouse", label: __("Warehouse"), fieldtype: "Link", options: "Warehouse" },
		{ fieldname: "call", label: __("Call"), fieldtype: "Select", options: "\nReorder now\nHealthy\nOrder less\nTail\nDead" },
		{ fieldname: "include_dead", label: __("Include lines with stock but no sales"), fieldtype: "Check", default: 1 },
	],
	onload(report) {
		
	},
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (data.bold) value = `<b>${value}</b>`;
		if (column.fieldname === "call" && data.call) {
			const c = { "Reorder now": "red", "Order less": "orange", "Dead": "gray", "Tail": "yellow", "Healthy": "green" }[data.call] || "gray";
			value = `<span class="indicator-pill ${c}">${data.call}</span>`;
		}
		return value;
	},
};
