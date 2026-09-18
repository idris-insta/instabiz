frappe.ui.form.on("IB DPR Entry", {
	work_order(frm) {
		if (!frm.doc.work_order) return;
		frappe.db.get_doc("IB Work Order", frm.doc.work_order).then((wo) => {
			frm.set_value("sales_order", wo.sales_order);
			const out = (wo.outputs || [])[0];
			if (out) {
				if (!frm.doc.item_code) frm.set_value("item_code", out.item_code);
				if (!frm.doc.width_mm) frm.set_value("width_mm", out.width_mm);
				if (!frm.doc.length_mtr) frm.set_value("length_mtr", out.length_mtr);
			}
			if (!frm.doc.machine && wo.machine) frm.set_value("machine", wo.machine);
		});
	},
	refresh(frm) {
		frm.add_custom_button(__("DPR Sheet"), () => frappe.set_route("query-report", "IB DPR Sheet",
			{ from_date: frm.doc.posting_date, to_date: frm.doc.posting_date, view: (frm.doc.stage || "").startsWith("Coating") ? "Coating" : (frm.doc.stage || "Summary") }));
	},
});
