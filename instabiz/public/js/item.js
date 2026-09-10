// Renders the scannable Code128 barcode image on the Item form, under the
// read-only "Barcode" field (custom_barcode, synced from the Barcodes table
// by instabiz.overrides.item.sync_barcode_field on save).
frappe.ui.form.on("Item", {
	refresh(frm) {
		_ib_render_barcode_preview(frm);
	},
	custom_barcode(frm) {
		_ib_render_barcode_preview(frm);
	},
});

function _ib_render_barcode_preview(frm) {
	const field = frm.get_field("custom_barcode_preview");
	if (!field) return;
	const value = frm.doc.custom_barcode;
	if (!value) {
		field.$wrapper.empty();
		return;
	}
	frappe.call({
		method: "instabiz.instabiz.doctype.ib_container_import.ib_container_import.get_barcode_data_uri",
		args: { value },
		callback: (r) => {
			if (!r.message) return;
			field.$wrapper.html(
				`<img src="${r.message}" alt="${frappe.utils.escape_html(value)}" ` +
					`style="height:60px;max-width:100%;image-rendering:pixelated;">` +
					`<div style="font-family:monospace;font-size:11px;color:var(--text-muted);margin-top:2px;">${frappe.utils.escape_html(value)}</div>`,
			);
		},
	});
}
