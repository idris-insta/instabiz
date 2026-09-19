frappe.query_reports["IB Wastage Analysis"] = {
	filters: [
		{ fieldname: "from_date", label: __("From"), fieldtype: "Date", default: frappe.datetime.add_months(frappe.datetime.get_today(), -1) },
		{ fieldname: "to_date", label: __("To"), fieldtype: "Date", default: frappe.datetime.get_today() },
		{ fieldname: "group_by", label: __("Group By"), fieldtype: "Select", options: "Machine\nStage\nOperator\nItem Group\nItem\nMonth", default: "Machine" },
		{ fieldname: "location", label: __("Location"), fieldtype: "Select", options: "\ngujarat\nmaharashtra\nchennai" },
		{ fieldname: "stage", label: __("Stage"), fieldtype: "Select", options: "\nCoating\nSlitting\nRewinding\nCutting\nSilicon\nPacking" },
		{ fieldname: "machine", label: __("Machine"), fieldtype: "Link", options: "IB Machine" },
		{ fieldname: "operator", label: __("Operator"), fieldtype: "Link", options: "User" },
		{ fieldname: "item_group", label: __("Item Group"), fieldtype: "Link", options: "Item Group" },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && ["gap", "wastage_pct"].includes(column.fieldname) && data.gap > 0) {
			value = `<span style="color:var(--red-500);font-weight:600">${value}</span>`;
		}
		return value;
	},
};
