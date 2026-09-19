frappe.query_reports["IB Goods In Transit"] = {
	filters: [
		{ fieldname: "from_warehouse", label: __("From"), fieldtype: "Link", options: "Warehouse" },
		{ fieldname: "to_warehouse", label: __("To"), fieldtype: "Link", options: "Warehouse" },
	],
	formatter(value, row, column, data, default_formatter) {
		if (column.fieldname === "receive" && data && data.receive) {
			return `<a class="btn btn-xs btn-primary" onclick="frappe.call('instabiz.overrides.branch_transfer.receive',{stock_entry:'${data.receive}'}).then(r=>frappe.set_route('Form','Stock Entry',r.message))">${__("Receive")}</a>`;
		}
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "days" && data && data.days > 7) value = `<span class="text-danger">${value}</span>`;
		return value;
	},
	onload(report) {
		report.page.add_inner_button(__("New Stock Transfer"), () => window.ib_branch_transfer_dialog()).addClass("btn-primary");
	},
};
