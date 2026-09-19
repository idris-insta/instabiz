frappe.query_reports["IB MRP Plan"] = {
	filters: [{ fieldname: "only_shortfall", label: __("Only Shortfalls"), fieldtype: "Check", default: 0 }],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && column.fieldname === "shortfall" && data.shortfall > 0) value = `<span class="text-danger bold">${value}</span>`;
		return value;
	},
	onload(report) {
		report.page.add_inner_button(__("Create Draft Requests"), () =>
			frappe.confirm(__("Create a draft Purchase Material Request for each short raw material (items already on an open MRP request are skipped)?"), () =>
				frappe.call({ method: "instabiz.overrides.mrp.run_mrp_now", freeze: true }).then((r) => {
					const m = r.message || {};
					const made = (m.created || []).length;
					frappe.msgprint(made ? __("{0} draft Material Request(s) created: {1}", [made, m.created.join(", ")]) : __("Nothing new to request."));
				}))).addClass("btn-primary");
		report.page.add_inner_button(__("Recipes"), () => frappe.set_route("List", "IB Production Recipe"));
	},
};
