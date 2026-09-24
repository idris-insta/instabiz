// Todo36 — IB Batch helper buttons (jumbo assign context / trace)
frappe.ui.form.on('IB Batch', {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__('Trace chain'), () => {
			frappe.call({
				method: 'instabiz.overrides.mfg_serials.list_trace_chain',
				args: { serial_or_carton: frm.doc.name },
				callback(r) {
					frappe.msgprint({
						title: __('Trace'),
						message: `<pre style="white-space:pre-wrap">${frappe.utils.escape_html(
							JSON.stringify(r.message || {}, null, 2).slice(0, 3500)
						)}</pre>`,
					});
				},
			});
		}, __('Traceability'));

		frm.add_custom_button(__('Assign this Jumbo to WO'), () => {
			const d = new frappe.ui.Dialog({
				title: __('Assign jumbo to Work Order'),
				fields: [
					{ fieldname: 'work_order', label: __('IB Work Order'), fieldtype: 'Link', options: 'IB Work Order', reqd: 1 },
					{ fieldname: 'qty_taken', label: __('Qty taken'), fieldtype: 'Float', default: frm.doc.batch_qty || frm.doc.qty || 0 },
				],
				primary_action_label: __('Assign'),
				primary_action(values) {
					frappe.call({
						method: 'instabiz.overrides.mfg_serials.allocate_jumbo_serials_to_wo',
						args: {
							work_order: values.work_order,
							source_batches: [{ batch: frm.doc.name, qty_taken: values.qty_taken }],
							replace: 0,
						},
						freeze: true,
						callback(r) {
							frappe.msgprint((r.message || {}).message || __('Done'));
							d.hide();
						},
					});
				},
			});
			d.show();
		}, __('Traceability'));
	},
});

// Ported from the "IB Batch Coating Jumbo Label" Client Script (2026-09-23).
// Same button, now shipped with the app instead of living only in the
// database, where a fresh site would never have had it.
// The IB Coating Jumbo Label print format itself is still DB-only.
frappe.ui.form.on("IB Batch", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(
			__("Print Coating Jumbo Label"),
			() => {
				const url = frappe.urllib.get_full_url(
					"/api/method/instabiz.overrides.manufacturing_rules.print_coating_jumbo_label?batch=" +
						encodeURIComponent(frm.doc.name)
				);
				window.open(url, "_blank");
			},
			__("Label")
		);
	},
});
