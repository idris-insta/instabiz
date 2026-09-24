// Copyright (c) 2026, Instabiz Solutions India Pvt Ltd and contributors
// For license information, please see license.txt

frappe.query_reports["Item SKU Split Candidates"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_days(frappe.datetime.get_today(), -90),
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
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "document_type",
			label: __("Document Type"),
			fieldtype: "Select",
			options: ["Both", "Quotation", "Sales Order"].join("\n"),
			default: "Both",
		},
		{
			fieldname: "only_submitted",
			label: __("Only Submitted"),
			fieldtype: "Check",
			default: 1,
		},
		{
			fieldname: "item_code",
			label: __("Item"),
			fieldtype: "Link",
			options: "Item",
		},
		{
			fieldname: "mismatch_field",
			label: __("Mismatch Field"),
			fieldtype: "Select",
			options: ["Any", "thickness", "color"].join("\n"),
			default: "Any",
		},
	],
};
