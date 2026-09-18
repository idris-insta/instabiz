frappe.query_reports["IB Production Report"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_start(),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "stage",
			label: __("Stage"),
			fieldtype: "Select",
			options: "\nCoating\nSlitting\nRewinding\nCutting\nSilicon\nPacking",
		},
		{
			fieldname: "machine",
			label: __("Machine"),
			fieldtype: "Link",
			options: "IB Machine",
		},
		{
			fieldname: "operator",
			label: __("Operator"),
			fieldtype: "Link",
			options: "User",
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
		const $legend = $(report.wrapper).find(".chart-legend");
		if ($legend.length) $legend.css("flex-wrap", "wrap");
	},
};
