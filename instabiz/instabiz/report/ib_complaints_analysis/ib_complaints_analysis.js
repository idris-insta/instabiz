frappe.query_reports["IB Complaints Analysis"] = {
	filters: [
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: frappe.datetime.add_months(frappe.datetime.get_today(), -3), reqd: 1 },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
		{ fieldname: "group_by", label: __("Group By"), fieldtype: "Select", options: "Root Cause\nType\nCustomer\nItem\nOwner\nMonth\nSource\nList", default: "Root Cause" },
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "item_code", label: __("Item"), fieldtype: "Link", options: "Item" },
		{ fieldname: "ticket_type", label: __("Type"), fieldtype: "Select", options: "\nComplaint\nQuality Issue\nReturn\nDelivery\nPayment\nQuery\nReorder Request\nOther" },
		{ fieldname: "status", label: __("Status"), fieldtype: "Select", options: "\nOpen\nIn Progress\nWaiting on Customer\nResolved\nClosed" },
		{ fieldname: "assigned_to", label: __("Owner"), fieldtype: "Link", options: "User" },
	],
};
