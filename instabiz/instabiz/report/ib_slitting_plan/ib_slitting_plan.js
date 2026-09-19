frappe.query_reports["IB Slitting Plan"] = {
	filters: [
		{ fieldname: "location", label: __("Location"), fieldtype: "Select", options: "\ngujarat\nmaharashtra\nchennai", default: "gujarat" },
		{ fieldname: "order_sheet", label: __("Order Sheet"), fieldtype: "Link", options: "IB Order Sheet" },
		{ fieldname: "source_batch", label: __("Use this jumbo"), fieldtype: "Link", options: "IB Batch",
			get_query: () => ({ filters: { kind: "Raw Material", status: "Active" } }) },
		{ fieldname: "show_unplanned", label: __("Show lines not planned"), fieldtype: "Check", default: 1 },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "trim_pct" && data.trim_pct != null) {
			const c = data.trim_pct <= 3 ? "var(--green-600)" : data.trim_pct <= 8 ? "var(--orange-500)" : "var(--red-500)";
			value = `<span style="color:${c};font-weight:600">${value}</span>`;
		}
		if (column.fieldname === "action" && data.pass_no) {
			value = `<button class="btn btn-xs btn-primary ib-slit-run" data-os="${data.order_sheet}" data-batch="${data.source_batch}" data-osi='${data.osi}'>${__("Create Run")}</button>`;
		}
		if (column.fieldname === "note" && data.note) value = `<span style="color:var(--orange-600)">${value}</span>`;
		return value;
	},
	onload(report) {
		$(report.page.wrapper).on("click", ".ib-slit-run", function () {
			const b = $(this);
			frappe.confirm(__("Start a run on {0} with these widths?", [b.data("batch")]), () =>
				frappe.call({ method: "instabiz.overrides.slitting_plan.create_pass", freeze: true,
					args: { order_sheet: b.data("os"), source_batch: b.data("batch"), order_sheet_items: JSON.stringify(b.data("osi")) },
				}).then((r) => { frappe.show_alert({ message: __("Run {0} started", [r.message]), indicator: "green" }); report.refresh(); }));
		});
		report.page.add_inner_button(__("Production Recipes"), () => frappe.set_route("List", "IB Production Recipe"));
	},
};
