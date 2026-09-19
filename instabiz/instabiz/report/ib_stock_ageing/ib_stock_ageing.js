frappe.query_reports["IB Stock Ageing"] = {
	filters: [
		{
			fieldname: "ranges",
			label: __("Ageing (days)"),
			fieldtype: "Data",
			default: "30,60,90",
			description: __("Bucket break points, e.g. 15,30,45,60,90"),
		},
		{
			fieldname: "warehouse",
			label: __("Warehouse"),
			fieldtype: "Link",
			options: "Warehouse",
		},
		{
			fieldname: "item_group",
			label: __("Item Group"),
			fieldtype: "Link",
			options: "Item Group",
		},
		{
			fieldname: "chart_type",
			label: __("Chart Type"),
			fieldtype: "Select",
			options: "bar\npie\ndonut\nline\npercentage",
			default: "bar",
		},
	],

	after_render(report) {
		const legend = report.chart_wrapper && report.chart_wrapper.querySelector(".chart-legend");
		if (legend) {
			legend.style.cssText = "display:flex;flex-wrap:wrap;justify-content:center;gap:6px 16px;";
		}
	},

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "age_days") {
			const age = data.age_days || 0;
			const color = age > 90 ? "#cf222e" : age > 60 ? "#ed7d31" : age > 30 ? "#d97757" : "#1a7f37";
			value = `<span style="color:${color};font-weight:600">${value}</span>`;
		}
		if (column.fieldname === "b90plus" && data.b90plus > 0) {
			value = `<span style="color:#cf222e;font-weight:600">${value}</span>`;
		}
		return value;
	},
};
