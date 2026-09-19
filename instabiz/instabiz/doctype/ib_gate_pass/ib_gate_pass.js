frappe.ui.form.on("IB Gate Pass", {
	onload(frm) {
		// opened from a Delivery Note / Purchase Receipt / Stock Entry → fill party, vehicle and items from it
		if (frm.is_new() && frm.doc.reference_name && !(frm.doc.items || []).filter((r) => r.item_code || r.description).length) fill_from(frm);
	},
	refresh(frm) {
		const returnable = ["Returnable", "Job Work", "Sample"].includes(frm.doc.purpose);
		if (frm.doc.docstatus === 1 && returnable && ["Open", "Partly Returned"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Record Return"), () => record_return(frm)).addClass("btn-primary");
		}
		if (frm.doc.docstatus === 0 && frm.doc.reference_doctype && frm.doc.reference_name && !(frm.doc.items || []).length) {
			frm.add_custom_button(__("Get Items"), () => fill_from(frm));
		}
	},
	reference_name(frm) {
		if (frm.doc.reference_name && !(frm.doc.items || []).filter((r) => r.item_code || r.description).length) fill_from(frm);
	},
});

function fill_from(frm) {
	frappe.call("instabiz.instabiz.doctype.ib_gate_pass.ib_gate_pass.make_from",
		{ doctype: frm.doc.reference_doctype, name: frm.doc.reference_name }).then((r) => {
		const d = r.message;
		["gate_pass_type", "purpose", "party_type", "party", "party_name", "location", "vehicle_no", "lr_no", "lr_date", "transporter"]
			.forEach((f) => { if (d[f]) frm.doc[f] = d[f]; });
		frm.clear_table("items");
		(d.items || []).forEach((it) => frm.add_child("items", it));
		frm.refresh_fields();
	});
}

function record_return(frm) {
	const rows = frm.doc.items.filter((r) => flt(r.qty) > flt(r.returned_qty));
	const d = new frappe.ui.Dialog({
		title: __("What came back?"),
		fields: rows.map((r) => ({ fieldtype: "Float", fieldname: r.name,
			label: `${r.item_code || r.description} — ${__("pending")} ${flt(r.qty) - flt(r.returned_qty)} ${r.uom || ""}` })),
		primary_action_label: __("Save"),
		primary_action(v) {
			const returns = rows.filter((r) => flt(v[r.name])).map((r) => ({ row: r.name, qty: v[r.name] }));
			if (!returns.length) return d.hide();
			frappe.call("instabiz.instabiz.doctype.ib_gate_pass.ib_gate_pass.record_return",
				{ gate_pass: frm.doc.name, returns }).then(() => { d.hide(); frm.reload_doc(); });
		},
	});
	d.show();
}
