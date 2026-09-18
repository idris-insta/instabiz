// Repeat an order in one click, and show what the customer last paid when an
// item is picked (instabiz.overrides.quick_actions).
(function () {
	const M = "instabiz.overrides.quick_actions";

	function open_repeat(args) {
		frappe.call({
			method: `${M}.repeat_order`,
			args,
			freeze: true,
			callback(r) {
				if (!r.message) return;
				const doc = frappe.model.sync(r.message)[0];
				frappe.set_route("Form", "Sales Order", doc.name);
			},
		});
	}

	frappe.ui.form.on("Customer", {
		refresh(frm) {
			if (frm.is_new() || !frappe.model.can_create("Sales Order")) return;
			frm.add_custom_button(__("Repeat Last Order"), () => open_repeat({ customer: frm.doc.name }), __("Create"));
		},
	});

	frappe.ui.form.on("Sales Order", {
		refresh(frm) {
			if (frm.doc.docstatus !== 1 || !frappe.model.can_create("Sales Order")) return;
			frm.add_custom_button(__("Repeat This Order"), () => open_repeat({ sales_order: frm.doc.name }), __("Create"));
		},
	});

	function show_hint(frm, cdt, cdn, customer) {
		const row = locals[cdt][cdn];
		if (!row.item_code) return;
		frappe.call({
			method: `${M}.price_hint`,
			args: { item_code: row.item_code, customer },
			callback(r) {
				const h = r.message || {};
				const parts = [];
				if (h.last) {
					parts.push(__("Last sold to this customer: {0} / {1} on {2}", [
						format_currency(h.last.rate), h.last.uom, frappe.datetime.str_to_user(h.last.date),
					]));
				}
				if (h.card && (h.card.face || h.card.last)) {
					parts.push(__("Rate card: {0} → {1}{2}", [
						format_currency(h.card.face), format_currency(h.card.last), h.card.unit ? " / " + h.card.unit : "",
					]));
				}
				if (parts.length) {
					frappe.show_alert({ message: `<b>${frappe.utils.escape_html(row.item_code)}</b><br>${parts.join("<br>")}`, indicator: "blue" }, 8);
				}
			},
		});
	}

	frappe.ui.form.on("Sales Order Item", {
		item_code(frm, cdt, cdn) { show_hint(frm, cdt, cdn, frm.doc.customer); },
	});
	frappe.ui.form.on("Quotation Item", {
		item_code(frm, cdt, cdn) {
			show_hint(frm, cdt, cdn, frm.doc.quotation_to === "Customer" ? frm.doc.party_name : null);
		},
	});
})();
