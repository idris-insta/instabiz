// "Gate Pass" button on submitted Delivery Notes, Purchase Receipts, Stock Entries and Sales Invoices.
["Delivery Note", "Purchase Receipt", "Stock Entry", "Sales Invoice"].forEach((dt) => {
	frappe.ui.form.on(dt, {
		refresh(frm) {
			if (frm.doc.docstatus !== 1 || !frappe.model.can_create("IB Gate Pass")) return;
			frm.add_custom_button(__("Gate Pass"), () =>
				frappe.new_doc("IB Gate Pass", { reference_doctype: dt, reference_name: frm.doc.name }), __("Create"));
		},
	});
});
