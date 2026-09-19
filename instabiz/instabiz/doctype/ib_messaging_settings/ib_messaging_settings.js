frappe.ui.form.on("IB Messaging Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Preview Morning Briefing"), () =>
			frappe.call({ method: "instabiz.overrides.briefing.preview", freeze: true }).then((r) =>
				frappe.msgprint({ title: r.message.subject, message: r.message.html, wide: true })));
		frm.add_custom_button(__("Send Briefing Now"), () =>
			frappe.confirm(__("Send today's briefing to everyone in 'Send to roles' now?"), () =>
				frappe.call({ method: "instabiz.overrides.briefing.preview", args: { send: 1 }, freeze: true }).then(() =>
					frappe.show_alert({ message: __("Briefing sent"), indicator: "green" }))));
	},
});
