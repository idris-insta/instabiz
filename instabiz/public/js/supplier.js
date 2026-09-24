// Ported from the "IB Supplier Buying Price List" Client Script (2026-09-23).
// instabiz.overrides.purchase_rules.ensure_supplier_buying_price_list has
// always been in the app; only this entry point lived in the database.

frappe.ui.form.on("Supplier", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(
			__("Ensure Buying Price List"),
			() => {
				frappe.call({
					method: "instabiz.overrides.purchase_rules.ensure_supplier_buying_price_list",
					args: { supplier: frm.doc.name },
					freeze: true,
					callback(r) {
						if (!r.message) return;
						frappe.show_alert({
							message: __("Price List: {0}", [r.message]),
							indicator: "green",
						});
						frm.reload_doc();
					},
				});
			},
			__("Buying")
		);
	},
});
