frappe.query_reports["IB Loan Register"] = {
	filters: [
		{ fieldname: "employee", label: __("Employee"), fieldtype: "Link", options: "Employee" },
		{ fieldname: "status", label: __("Status"), fieldtype: "Select", options: "\nActive\nRepaid\nCancelled", default: "Active" },
		{ fieldname: "loan_type", label: __("Type"), fieldtype: "Select", options: "\nSalary Advance\nPersonal Loan\nEmergency Loan" },
	],
};
