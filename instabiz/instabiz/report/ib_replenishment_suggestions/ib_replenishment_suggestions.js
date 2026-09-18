frappe.query_reports["IB Replenishment Suggestions"] = {
	filters: [
		{ fieldname: "item_group", label: __("Item Group"), fieldtype: "Link", options: "Item Group" },
		{ fieldname: "lookback_days", label: __("Look back (days)"), fieldtype: "Int", default: 90 },
		{ fieldname: "default_lead_days", label: __("Lead time if not set (days)"), fieldtype: "Int", default: 14 },
		{ fieldname: "review_days", label: __("Review cycle (days)"), fieldtype: "Int", default: 7 },
		{ fieldname: "show_all", label: __("Show items with enough stock"), fieldtype: "Check", default: 0 },
	],

	onload(report) {
		report.page.add_inner_button(__("Create Material Request"), () => {
			const dt = report.datatable;
			const checked = dt ? dt.rowmanager.getCheckedRows().map((i) => report.data[i]) : [];
			const rows = (checked.length ? checked : report.data || []).filter((r) => r && r.suggested > 0);
			if (!rows.length) {
				frappe.msgprint(__("Nothing to order. Tick rows that have a suggested quantity."));
				return;
			}
			frappe.model.with_doctype("Material Request", () => {
				const mr = frappe.model.get_new_doc("Material Request");
				mr.material_request_type = "Purchase";
				mr.schedule_date = frappe.datetime.add_days(frappe.datetime.get_today(), 7);
				rows.forEach((r) => {
					const row = frappe.model.add_child(mr, "items");
					row.item_code = r.item_code;
					row.item_name = r.item_name;
					row.qty = r.suggested;
					row.uom = r.uom;
					row.stock_uom = r.uom;
					row.conversion_factor = 1;
					row.schedule_date = mr.schedule_date;
				});
				frappe.set_route("Form", "Material Request", mr.name);
			});
		});
	},

	get_datatable_options(options) {
		return Object.assign(options, { checkboxColumn: true });
	},

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "cover_days") {
			const cls =
				data.cover_days < data.lead_time ? "red" : data.cover_days < data.lead_time + 7 ? "orange" : "green";
			return `<span class="indicator-pill ${cls} no-indicator-dot">${value}</span>`;
		}
		if (column.fieldname === "trend") {
			const cls = { Rising: "blue", Falling: "gray", Steady: "green" }[data.trend] || "gray";
			return `<span class="indicator-pill ${cls} no-indicator-dot">${value}</span>`;
		}
		return value;
	},
};
