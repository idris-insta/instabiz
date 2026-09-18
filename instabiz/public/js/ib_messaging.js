// Send a document by WhatsApp or email from its form (instabiz.overrides.messaging).
// WhatsApp: free wa.me link today (user presses Send in WhatsApp); switches to
// the API automatically once Instabiz Settings -> Messaging is set to API.
// Email: Frappe's own composer, pre-filled from the IB Message Template;
// sends once an outgoing Email Account exists.
(function () {
	const DOCTYPES = [
		"Quotation", "Sales Order", "Delivery Note", "Sales Invoice",
		"Payment Entry", "Customer", "Purchase Order",
	];
	const M = "instabiz.overrides.messaging";

	function ready(frm) {
		return !frm.is_new() && frm.doc.docstatus !== 2;
	}

	function whatsapp(frm, template) {
		frappe.call({
			method: `${M}.get_message`,
			args: { doctype: frm.doctype, name: frm.doc.name, channel: "WhatsApp", template },
			freeze: true,
			callback: (r) => r.message && whatsapp_dialog(frm, r.message),
		});
	}

	function whatsapp_dialog(frm, data) {
		const api = data.mode === "API";
		const d = new frappe.ui.Dialog({
			title: __("Send on WhatsApp"),
			size: "large",
			fields: [
				{
					fieldname: "template", label: __("Template"), fieldtype: "Select",
					options: data.templates.length ? data.templates : [""],
					default: data.template, hidden: !data.templates.length,
					change() {
						const t = d.get_value("template");
						if (t && t !== data.template) { d.hide(); whatsapp(frm, t); }
					},
				},
				{ fieldname: "phone", label: __("Mobile Number"), fieldtype: "Data", reqd: 1, default: data.phone,
					description: __("With country code, e.g. 919876543210. 10-digit numbers get the default code.") },
				{ fieldname: "message", label: __("Message"), fieldtype: "Small Text", reqd: 1, default: data.message },
				{ fieldname: "note", fieldtype: "HTML", options: `<p class="text-muted small">${
					api ? __("Sends through the WhatsApp API.")
						: __("Opens WhatsApp with this message ready. Press Send there.")
				} ${data.templates.length ? "" : __("No template set up for this document yet — edit wording in IB Message Template.")}</p>` },
			],
			primary_action_label: api ? __("Send") : __("Open WhatsApp"),
			primary_action(values) {
				// open the window inside the click so the browser doesn't block it
				const win = api ? null : window.open("", "_blank");
				frappe.call({
					method: `${M}.send_whatsapp`,
					args: { doctype: frm.doctype, name: frm.doc.name, phone: values.phone, message: values.message },
					callback: (r) => {
						d.hide();
						if (r.message && r.message.url) {
							if (win) win.location = r.message.url; else window.open(r.message.url, "_blank");
						} else {
							frappe.show_alert({ message: __("WhatsApp sent"), indicator: "green" });
						}
						frm.reload_doc();
					},
					error: () => win && win.close(),
				});
			},
		});
		d.show();
	}

	function email(frm) {
		frappe.call({
			method: `${M}.get_message`,
			args: { doctype: frm.doctype, name: frm.doc.name, channel: "Email" },
			freeze: true,
			callback: (r) => {
				const data = r.message || {};
				const composer = new frappe.views.CommunicationComposer({
					doc: frm.doc,
					frm,
					subject: data.subject,
					recipients: data.email || "",
					message: (data.message || "").replace(/\n/g, "<br>"),
					attach_document_print: data.attach_pdf,
				});
				if (data.print_format && composer.dialog.fields_dict.select_print_format) {
					composer.dialog.set_value("select_print_format", data.print_format);
				}
			},
		});
	}

	DOCTYPES.forEach((doctype) => {
		frappe.ui.form.on(doctype, {
			refresh(frm) {
				if (!ready(frm)) return;
				frm.add_custom_button(__("WhatsApp"), () => whatsapp(frm), __("Send"));
				frm.add_custom_button(__("Email"), () => email(frm), __("Send"));
			},
		});
	});
})();
