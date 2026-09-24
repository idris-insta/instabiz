// Floor pickers on Stock Entry. A Stock Entry carries no custom_location of its
// own, so the location is inferred from whatever warehouse the document already
// points at; with none set, ib_pick_floor falls back to every enabled leaf.
// Shared dialog lives in ib_source_floor.js.

frappe.ui.form.on("Stock Entry", {
	refresh(frm) {
		if (frm.doc.docstatus !== 0) return;
		if (!(frm.doc.items || []).length) return;

		const purpose = frm.doc.purpose || frm.doc.stock_entry_type || "";

		// Anything that consumes stock has a source side.
		if (purpose !== "Material Receipt") {
			frm.add_custom_button(
				__("Source Floor"),
				() =>
					ib_pick_floor(frm, {
						row_field: "s_warehouse",
						header_field: "from_warehouse",
						mode: "source",
						location: ib_se_location(frm, "source"),
						title: __("Pick source floor"),
					}),
				__("Floor")
			);
		}

		// Anything that receives stock has a target side.
		if (purpose !== "Material Issue") {
			frm.add_custom_button(
				__("Target Floor"),
				() =>
					ib_pick_floor(frm, {
						row_field: "t_warehouse",
						header_field: "to_warehouse",
						mode: "target",
						location: ib_se_location(frm, "target"),
						title: __("Pick target floor"),
					}),
				__("Floor")
			);
		}
	},
});

// Infer the location from a warehouse already on the document, preferring the
// side being picked so a cross-location transfer offers the right tree for each.
function ib_se_location(frm, side) {
	const rows = frm.doc.items || [];
	const own = side === "target" ? frm.doc.to_warehouse : frm.doc.from_warehouse;
	const other = side === "target" ? frm.doc.from_warehouse : frm.doc.to_warehouse;
	const row_field = side === "target" ? "t_warehouse" : "s_warehouse";
	const row_other = side === "target" ? "s_warehouse" : "t_warehouse";

	return (
		own ||
		(rows.find((r) => r[row_field]) || {})[row_field] ||
		other ||
		(rows.find((r) => r[row_other]) || {})[row_other] ||
		null
	);
}
