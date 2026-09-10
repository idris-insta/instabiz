// Row action on the list — draft containers get "Print Label" (pick an
// item if there's more than one, enter however many labels are needed
// right now, print them — independent of the recorded no_of_boxes, since
// nothing is final yet). Submitted containers get "Show Labels" instead —
// no picking, no count prompt: the recorded quantities are now the real
// ones, so it just opens the full label set (every item, real box counts)
// straight away via the standard "IB Container Label" print format.
frappe.provide("instabiz.container_import");

frappe.listview_settings["IB Container Import"] = {
	button: {
		show(doc) {
			return doc.docstatus !== 2;
		},
		get_label(doc) {
			return doc.docstatus === 1 ? __("Show Labels") : __("Print Label");
		},
		get_description(doc) {
			return doc.docstatus === 1
				? __("View/print labels for {0}", [doc.name])
				: __("Print labels for {0}", [doc.name]);
		},
		action(doc) {
			if (doc.docstatus === 1) {
				instabiz.container_import.show_labels(doc.name);
			} else {
				instabiz.container_import.print_label_flow(doc.name);
			}
		},
	},
};

// ── Submitted: straight to the real, full label set ─────────────────────────
instabiz.container_import.show_labels = function (container_import) {
	const url = `/printview?doctype=${encodeURIComponent("IB Container Import")}` +
		`&name=${encodeURIComponent(container_import)}` +
		`&format=${encodeURIComponent("IB Container Label")}`;
	window.open(url, "_blank");
};

// ── Draft: pick item (if needed) → how many → print ──────────────────────────
instabiz.container_import.print_label_flow = function (container_import) {
	frappe.call({
		method: "instabiz.instabiz.doctype.ib_container_import.ib_container_import.get_container_items",
		args: { container_import },
		callback: (r) => {
			const items = r.message || [];
			if (!items.length) {
				frappe.show_alert({ message: __("No items on this container."), indicator: "orange" });
				return;
			}
			if (items.length === 1) {
				instabiz.container_import.prompt_count(container_import, items[0].item_code);
			} else {
				instabiz.container_import.pick_item(container_import, items);
			}
		},
	});
};

instabiz.container_import.pick_item = function (container_import, items) {
	const options = items.map((i) => `${i.item_code} — ${i.item_name || ""}`);
	const d = new frappe.ui.Dialog({
		title: __("Which item?"),
		fields: [
			{
				fieldname: "item_option",
				fieldtype: "Select",
				label: __("Item"),
				options: options,
				reqd: 1,
			},
		],
		primary_action_label: __("Next"),
		primary_action: (vals) => {
			d.hide();
			const item_code = vals.item_option.split(" — ")[0];
			instabiz.container_import.prompt_count(container_import, item_code);
		},
	});
	d.show();
};

instabiz.container_import.prompt_count = function (container_import, item_code) {
	const d = new frappe.ui.Dialog({
		title: __("Print Labels — {0}", [item_code]),
		fields: [
			{
				fieldname: "count",
				fieldtype: "Int",
				label: __("How many labels?"),
				reqd: 1,
				default: 1,
				description: __("Each label is numbered Roll No. 1 through this count. Max 2000 per print run."),
			},
		],
		primary_action_label: __("Print"),
		primary_action: (vals) => {
			d.hide();
			frappe.show_alert({ message: __("Preparing labels…"), indicator: "blue" }, 3);
			open_url_post(
				"/api/method/instabiz.instabiz.doctype.ib_container_import.ib_container_import.generate_item_labels",
				{ container_import, item_code, count: vals.count },
				true,
			);
		},
	});
	d.show();
};
