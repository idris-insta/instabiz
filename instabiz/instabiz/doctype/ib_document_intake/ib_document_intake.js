// Copyright (c) 2026, Instabiz Solutions India Pvt Ltd and Contributors
// See license.txt

frappe.ui.form.on("IB Document Intake", {
	refresh(frm) {
		if (frm.is_new()) return;

		if (frm.doc.status !== "Converted" && frm.doc.scanned_document) {
			frm.add_custom_button(__("Run OCR"), () => {
				frappe.call({
					method: "run_ocr",
					doc: frm.doc,
					freeze: true,
					freeze_message: __("Reading the scanned document…"),
					callback: (r) => {
						frm.reload_doc();
						const res = r.message || {};
						if (res.ok) {
							frappe.show_alert({ message: __("OCR complete — review Raw Text below, then Extract."), indicator: "green" });
						} else {
							frappe.msgprint({
								title: __("OCR unavailable"),
								indicator: "orange",
								message: res.message || __("Could not read the document — see OCR Status / Error."),
							});
						}
					},
				});
			});
		}

		if (frm.doc.status !== "Converted") {
			frm.add_custom_button(__("Extract"), () => {
				frappe.call({
					method: "extract",
					doc: frm.doc,
					freeze: true,
					freeze_message: __("Asking Claude to extract fields…"),
					callback: (r) => {
						frm.reload_doc();
						const res = r.message || {};
						if (res.ok) {
							frappe.show_alert({ message: __("Extraction complete — review the fields below."), indicator: "green" });
						} else {
							frappe.msgprint({
								title: __("Extraction unavailable"),
								indicator: "orange",
								message: res.message || __("Could not extract — see Extraction Status / Error."),
							});
						}
					},
				});
			});
		}

		if (frm.doc.status === "Extracted") {
			frm.add_custom_button(__("Convert to Draft"), () => {
				frappe.confirm(
					__("This creates a real draft {0} from the reviewed extraction. Continue?", [frm.doc.intake_type]),
					() => {
						frappe.call({
							method: "convert_to_draft",
							doc: frm.doc,
							freeze: true,
							callback: (r) => {
								frm.reload_doc();
								const res = r.message || {};
								if (res.open_new) {
									// bill read without its lines: open a new Purchase Invoice with the header filled
									frappe.new_doc("Purchase Invoice", res.open_new);
									return;
								}
								if (res.ok) {
									frappe.show_alert({ message: __("Created {0} {1}", [res.doctype, res.docname]), indicator: "green" });
									frappe.set_route("Form", res.doctype, res.docname);
								}
							},
						});
					}
				);
			}).addClass("btn-primary");
		}

		if (frm.doc.created_docname) {
			frm.add_custom_button(__("View {0}", [frm.doc.created_doctype]), () => {
				frappe.set_route("Form", frm.doc.created_doctype, frm.doc.created_docname);
			});
		}

		if (frm.doc.match_status) {
			const colors = {
				"Exact Match": "green",
				"Fuzzy Match": "orange",
				"Ambiguous": "red",
				"Not Matched": "red",
			};
			frm.dashboard.add_indicator(__(frm.doc.match_status), colors[frm.doc.match_status] || "gray");
		}
	},
});
