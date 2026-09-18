frappe.query_reports["IB Business Report"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company",
			default: frappe.defaults.get_user_default("Company"), reqd: 1 },
		{ fieldname: "view", label: __("View"), fieldtype: "Select", reqd: 1, default: "Monthly Summary",
			options: ["Monthly Summary", "Party-wise", "Collection Status", "Item-wise", "Item Monthly",
				"Party Monthly", "State-wise", "Salesperson-wise"].join("\n") },
		{ fieldname: "fiscal_year", label: __("Financial Year"), fieldtype: "Link", options: "Fiscal Year",
			default: (frappe.boot.ib_fiscal_year && frappe.boot.ib_fiscal_year.name) || frappe.defaults.get_user_default("fiscal_year"),
			on_change: (report) => {
				const fy = report.get_filter_value("fiscal_year");
				if (!fy) return;
				frappe.db.get_value("Fiscal Year", fy, ["year_start_date", "year_end_date"]).then(({ message }) => {
					report.set_filter_value({ from_date: message.year_start_date, to_date: message.year_end_date });
				});
			} },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date" },
		{ fieldname: "customer", label: __("Party"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "handled_by", label: __("Handled By"), fieldtype: "Data" },
		{ fieldname: "state", label: __("State"), fieldtype: "Data" },
	],
	onload(report) {
		const fy = report.get_filter_value("fiscal_year");
		if (fy && !report.get_filter_value("from_date")) {
			frappe.db.get_value("Fiscal Year", fy, ["year_start_date", "year_end_date"]).then(({ message }) => {
				if (message) report.set_filter_value({ from_date: message.year_start_date, to_date: message.year_end_date });
			});
		}
	},
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (data.bold) value = `<b>${value}</b>`;
		if (column.fieldname === "status") {
			const color = { "Overdue > 30 days": "red", "Overdue 1-30 days": "orange", "Cleared": "green",
				"Advance": "blue", "Not Due": "gray" }[data.status] || "gray";
			value = `<span class="indicator-pill ${color}">${data.status}</span>`;
		}
		if (["outstanding", "difference"].includes(column.fieldname) && data[column.fieldname] < 0) {
			value = `<span style="color: var(--green-600)">${value}</span>`;
		}
		return value;
	},
};
