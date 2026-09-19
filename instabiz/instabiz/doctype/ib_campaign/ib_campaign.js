const IBC = "instabiz.instabiz.doctype.ib_campaign.ib_campaign.";

frappe.ui.form.on("IB Campaign", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Build List"), () =>
			frappe.call({ method: IBC + "build_list", args: { name: frm.doc.name }, freeze: true }).then((r) => {
				frappe.show_alert({ message: __("{0} added", [r.message]), indicator: "green" });
				frm.reload_doc();
			}));
		if ((frm.doc.recipients || []).some((r) => r.status === "Pending")) {
			frm.add_custom_button(__("Send"), () =>
				frappe.confirm(__("Send to {0} recipient(s)?", [frm.doc.recipients.filter((r) => r.status === "Pending").length]), () =>
					frappe.call({ method: IBC + "send", args: { name: frm.doc.name }, freeze: true }).then((r) => {
						frm.reload_doc();
						if ((r.message.links || []).length) show_links(frm, r.message.links);
					}))).addClass("btn-primary");
		}
		if (frm.doc.sent_on) {
			frm.add_custom_button(__("Refresh Results"), () =>
				frappe.call(IBC + "refresh_results", { name: frm.doc.name }).then(() => frm.reload_doc()));
			frm.dashboard.add_indicator(__("Orders after: {0} ({1})", [frm.doc.orders_after || 0, format_currency(frm.doc.order_value_after || 0)]), "green");
		}
	},
});

function show_links(frm, links) {
	const mine = links.filter((l) => !l.sales_person || l.sales_person === frappe.session.user || frappe.user.has_role("Sales Manager"));
	const html = mine.map((l) => `<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border-color)">
		<span>${frappe.utils.escape_html(l.name || "")}</span>
		<a class="btn btn-xs btn-primary ib-wa" data-row="${l.row}" href="${l.url}" target="_blank">${__("Send on WhatsApp")}</a></div>`).join("");
	const d = new frappe.ui.Dialog({ title: __("Send on WhatsApp ({0})", [mine.length]), fields: [{ fieldtype: "HTML", fieldname: "h" }] });
	d.fields_dict.h.$wrapper.html(`<div style="max-height:60vh;overflow:auto">${html}</div>`);
	d.$wrapper.on("click", ".ib-wa", function () {
		$(this).removeClass("btn-primary").addClass("btn-default").text(__("Sent"));
		frappe.call(IBC + "mark_sent", { name: frm.doc.name, row: $(this).data("row") });
	});
	d.onhide = () => frm.reload_doc();
	d.show();
}
