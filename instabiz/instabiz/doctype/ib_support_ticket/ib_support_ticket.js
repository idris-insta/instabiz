frappe.ui.form.on("IB Support Ticket", {
	refresh(frm) {
		if (frm.doc.sla_breached && !["Resolved", "Closed"].includes(frm.doc.status)) {
			frm.dashboard.set_headline_alert(__("Past its deadline ({0})", [frappe.datetime.str_to_user(frm.doc.resolution_due)]), "red");
		}
		if (frm.doc.batch || frm.doc.fg_serial) {
			frm.add_custom_button(__("Trace"), () => frappe.set_route("ib-trace", { id: frm.doc.fg_serial || frm.doc.batch }));
		}
		if (!frm.is_new() && frm.doc.customer && ["Complaint", "Quality Issue", "Return"].includes(frm.doc.ticket_type) && !frm.doc.credit_note) {
			frm.add_custom_button(__("Credit Note"), () =>
				frappe.new_doc("IB Credit Note", {
					customer: frm.doc.customer,
					against_sales_invoice: frm.doc.reference_doctype === "Sales Invoice" ? frm.doc.reference_name : undefined,
					remarks: __("Against ticket {0}", [frm.doc.name]),
				}), __("Create"));
		}
		if (!frm.is_new() && frm.doc.status === "Open") {
			frm.add_custom_button(__("Start Working"), () => { frm.set_value("status", "In Progress"); frm.save(); });
		}
	},
	subject(frm) { suggest(frm); },
	description(frm) { suggest(frm); },
	fg_serial(frm) {
		if (!frm.doc.fg_serial) return;
		frappe.db.get_value("IB FG Serial", frm.doc.fg_serial, ["item_code", "fg_batch"]).then((r) => {
			const v = r.message || {};
			if (v.item_code && !frm.doc.item_code) frm.set_value("item_code", v.item_code);
			if (v.fg_batch && !frm.doc.batch) frm.set_value("batch", v.fg_batch);
		});
	},
});

function suggest(frm) {
	if (!frm.is_new() || !frm.doc.subject) return;
	frappe.call("instabiz.instabiz.doctype.ib_support_ticket.ib_support_ticket.classify",
		{ subject: frm.doc.subject, description: frm.doc.description }).then((r) => {
		const s = r.message || {};
		if (s.ticket_type && frm.doc.ticket_type !== s.ticket_type && !frm.__type_touched) frm.set_value("ticket_type", s.ticket_type);
		if (s.priority && !frm.__priority_touched) frm.set_value("priority", s.priority);
	});
}
