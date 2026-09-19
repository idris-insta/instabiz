frappe.ui.form.on("IB Container Import", {
	// Submit posts a real Stock Entry immediately (see on_submit in
	// ib_container_import.py) — same Draft=safe/Submit=final/Cancel=reverses
	// convention every other transactional doctype in this app already
	// uses, kept deliberately (2026-08-30, user decision after asking
	// whether this should work differently). This is just a confirmation
	// nudge before that irreversible-in-spirit action, not a workflow
	// change — quantities are split by UOM, never blended into one number
	// (same reasoning as the DPR/report fixes elsewhere this app).
	before_submit(frm) {
		return new Promise((resolve, reject) => {
			const by_uom = {};
			(frm.doc.items || []).forEach((row) => {
				const uom = row.stock_uom || "";
				by_uom[uom] = (by_uom[uom] || 0) + flt(row.total_qty);
			});
			const qty_line = Object.entries(by_uom)
				.map(([uom, qty]) => `${flt(qty)} ${uom}`)
				.join(", ") || "0";
			const msg = __("This posts {0} into <strong>{1}</strong>. Confirm the quantities are correct before continuing.", [
				qty_line,
				frappe.utils.escape_html(frm.doc.warehouse || ""),
			]);
			frappe.confirm(msg, resolve, () => reject());
		});
	},

	refresh(frm) {
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Profitability"), () =>
				frappe.set_route("query-report", "IB Consignment Profitability", { container: frm.doc.name, view: "Container Line" }));
		}
		if (!frm.is_new()) {
			frm.fields_dict["items"].grid.add_custom_button(__("Reprint Labels"), () => {
				const selected = frm.fields_dict["items"].grid.get_selected();
				if (!selected.length) {
					frappe.msgprint(__("Select a row first"));
					return;
				}
				selected.forEach((row_name) => {
					const row = frm.doc.items.find((r) => r.name === row_name);
					if (!row || !row.item_code) return;
					window.open(
						frappe.urllib.get_full_url(
							"/api/method/instabiz.instabiz.doctype.ib_container_import.ib_container_import.reprint_item_labels" +
								"?container_import=" + encodeURIComponent(frm.doc.name) +
								"&item_code=" + encodeURIComponent(row.item_code)
						)
					);
				});
			});
		}
	},
});

frappe.ui.form.on("IB Container Import Item", {
	no_of_boxes(frm, cdt, cdn) {
		_ib_ctn_recalc(frm, cdt, cdn);
	},
	qty_per_box(frm, cdt, cdn) {
		_ib_ctn_recalc(frm, cdt, cdn);
	},
	width_mm(frm, cdt, cdn) {
		_ib_ctn_recalc(frm, cdt, cdn);
	},
	length_mtr(frm, cdt, cdn) {
		_ib_ctn_recalc(frm, cdt, cdn);
	},
	item_code(frm, cdt, cdn) {
		// stock_uom fetches async after item_code is set — recalc once it lands
		setTimeout(() => _ib_ctn_recalc(frm, cdt, cdn), 400);
	},
});

function _ib_ctn_recalc(frm, cdt, cdn) {
	const row = frappe.get_doc(cdt, cdn);
	const is_sqmt = (row.stock_uom || "").trim().toUpperCase() === "SQMT";
	if (is_sqmt) {
		row.area_per_unit = (flt(row.width_mm) / 1000) * flt(row.length_mtr);
		row.total_qty = flt(row.no_of_boxes) * flt(row.area_per_unit);
	} else {
		row.total_qty = flt(row.no_of_boxes) * flt(row.qty_per_box);
	}
	frm.refresh_field("items");
}
