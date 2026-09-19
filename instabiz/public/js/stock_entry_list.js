// Adds "Branch Transfer" to the Stock Entry list without replacing ERPNext's own list settings.
(() => {
	const s = frappe.listview_settings["Stock Entry"] || {};
	const prev = s.onload;
	s.onload = function (listview) {
		if (prev) prev.call(this, listview);
		listview.page.add_inner_button(__("Branch Transfer"), () => window.ib_branch_transfer_dialog());
		listview.page.add_inner_button(__("Goods In Transit"), () => frappe.set_route("query-report", "IB Goods In Transit"));
	};
	frappe.listview_settings["Stock Entry"] = s;
})();
