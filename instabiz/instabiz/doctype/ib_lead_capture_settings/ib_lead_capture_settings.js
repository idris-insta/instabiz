frappe.ui.form.on("IB Lead Capture Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Pull IndiaMART now"), () => {
			frappe.call({ method: "instabiz.overrides.lead_capture.pull_now", freeze: true })
				.then((r) => { frappe.msgprint((r.message || {}).message || __("Done")); frm.reload_doc(); });
		});
		frm.add_custom_button(__("New token"), () => {
			frappe.confirm(__("The website must be updated with the new token. Continue?"), () =>
				frappe.call("instabiz.overrides.lead_capture.new_token").then(() => frm.reload_doc()));
		});
		frm.add_custom_button(__("Captured leads"), () =>
			frappe.set_route("List", "Lead", { source: ["in", ["IndiaMART", "Website", "JustDial", "TradeIndia", "Meta Ads", "Google Ads"]] }));
	},
});
