// Todo 38 + Todo 44/36 — IB Work Order plans, undersize apply, jumbo/carton serials
frappe.ui.form.on('IB Work Order', {
	refresh(frm) {
		if (frm.is_new()) return;

		const addPlan = (label, plan_type) => {
			frm.add_custom_button(__(label), () => {
				frappe.call({
					method: 'instabiz.overrides.mfg_plans.create_plan_from_wo',
					args: { work_order: frm.doc.name, plan_type },
					freeze: true,
					freeze_message: __('Building {0}…', [label]),
					callback(r) {
						const p = r.message || {};
						frappe.msgprint({
							title: __('Plan ready'),
							indicator: 'green',
							message: p.summary || JSON.stringify(p).slice(0, 800),
						});
						frm.reload_doc();
						const pd = p.plan_doc;
						if (pd && pd.doctype && pd.name) {
							frappe.set_route('Form', pd.doctype, pd.name);
						}
					},
				});
			}, __('Create Plan'));
		};
		addPlan('Slitting Plan', 'slitting');
		addPlan('Rewinding Plan', 'rewinding');
		addPlan('Cutting Plan', 'cutting');

		frm.add_custom_button(__('Auto (from route)'), () => {
			frappe.call({
				method: 'instabiz.overrides.mfg_plans.create_plan_from_wo',
				args: { work_order: frm.doc.name },
				freeze: true,
				callback(r) {
					const msg = r.message || {};
					const plans = msg.plans || [msg];
					const lines = plans.map((p) => p.summary || p.plan_type).join('<br>');
					frappe.msgprint({ title: __('Plans'), indicator: 'green', message: lines || __('Done') });
					frm.reload_doc();
				},
			});
		}, __('Create Plan'));

		frm.add_custom_button(__('Suggest multi-width layout'), () => {
			frappe.call({
				method: 'instabiz.overrides.mfg_plans.suggest_multi_width_layout',
				args: { work_order: frm.doc.name },
				callback(r) {
					const L = r.message || {};
					frappe.msgprint({
						title: __('Multi-width layout'),
						message:
							`Shafts: ${L.shaft_count || 0}<br>` +
							`Waste: ${L.total_waste_mm || 0} mm<br>` +
							`Usable: ${L.usable_width_mm || 0} mm`,
					});
				},
			});
		}, __('Create Plan'));

		// Todo44 — soft suggest then Confirm Apply
		frm.add_custom_button(__('Suggest cutting undersize'), () => {
			frappe.call({
				method: 'instabiz.overrides.mfg_plans.suggest_cutting_undersize',
				args: { work_order: frm.doc.name },
				callback(r) {
					const s = r.message || {};
					const sug = s.suggestion || {};
					const beforePcs = sug.pcs_at_ordered != null ? sug.pcs_at_ordered : (s.pcs_at_ordered || '—');
					const afterPcs = sug.pcs_at_suggested != null ? sug.pcs_at_suggested : '—';
					const wasteBefore = sug.waste_at_ordered_mm != null ? sug.waste_at_ordered_mm : (s.waste_at_ordered_mm || '—');
					const wasteAfter = sug.waste_at_suggested_mm != null ? sug.waste_at_suggested_mm : '—';
					const suggested = sug.suggested_width_mm;
					const ordered = s.ordered_width_mm || sug.ordered_width_mm;

					if (!suggested) {
						frappe.msgprint({
							title: __('Undersize suggestion (soft)'),
							message: s.message || JSON.stringify(s).slice(0, 600),
						});
						return;
					}

					const d = new frappe.ui.Dialog({
						title: __('Cutting undersize — confirm apply'),
						fields: [
							{
								fieldtype: 'HTML',
								options:
									`<p>${frappe.utils.escape_html(s.message || '')}</p>` +
									`<table class="table table-bordered" style="margin-top:8px">` +
									`<tr><th></th><th>Before</th><th>After</th></tr>` +
									`<tr><td>Width (mm)</td><td>${ordered || '—'}</td><td><b>${suggested}</b></td></tr>` +
									`<tr><td>Pcs</td><td>${beforePcs}</td><td><b>${afterPcs}</b></td></tr>` +
									`<tr><td>Waste (mm)</td><td>${wasteBefore}</td><td><b>${wasteAfter}</b></td></tr>` +
									`</table>` +
									`<p class="text-muted">Soft until you click Confirm Apply. Item master width is not changed.</p>`,
							},
							{
								fieldname: 'item_code',
								label: __('Item'),
								fieldtype: 'Data',
								default: sug.item_code || s.item_code || '',
							},
						],
						primary_action_label: __('Confirm Apply'),
						primary_action(values) {
							frappe.call({
								method: 'instabiz.overrides.cutting_undersize.apply_cutting_undersize',
								args: {
									work_order: frm.doc.name,
									suggestion_payload: s,
									suggested_width_mm: suggested,
									item_code: values.item_code || sug.item_code,
									confirm: 1,
									update_item_master: 0,
								},
								freeze: true,
								freeze_message: __('Applying undersize…'),
								callback(rr) {
									const m = rr.message || {};
									frappe.msgprint({
										title: m.applied ? __('Undersize applied') : __('Not applied'),
										indicator: m.applied ? 'green' : 'orange',
										message: m.message || JSON.stringify(m).slice(0, 600),
									});
									d.hide();
									frm.reload_doc();
								},
							});
						},
					});
					d.show();
				},
			});
		}, __('Create Plan'));

		// Todo36 — jumbo / carton serials
		frm.add_custom_button(__('Assign Jumbo Serials'), () => {
			const d = new frappe.ui.Dialog({
				title: __('Assign Jumbo Serials (multi-jumbo OK)'),
				fields: [
					{
						fieldname: 'source_batches',
						label: __('Batches / serials'),
						fieldtype: 'Small Text',
						description: __('One per line: BATCH_NAME or BATCH_NAME,qty'),
						reqd: 1,
					},
					{
						fieldname: 'replace',
						label: __('Replace existing list'),
						fieldtype: 'Check',
						default: 0,
					},
				],
				primary_action_label: __('Assign'),
				primary_action(values) {
					const rows = [];
					(values.source_batches || '').split(/\n/).forEach((line) => {
						line = (line || '').trim();
						if (!line) return;
						const parts = line.split(',').map((x) => x.trim());
						rows.push({ batch: parts[0], qty_taken: parts[1] ? flt(parts[1]) : 0 });
					});
					frappe.call({
						method: 'instabiz.overrides.mfg_serials.allocate_jumbo_serials_to_wo',
						args: {
							work_order: frm.doc.name,
							source_batches: rows,
							replace: values.replace ? 1 : 0,
						},
						freeze: true,
						callback(r) {
							const m = r.message || {};
							frappe.msgprint(m.message || JSON.stringify(m).slice(0, 500));
							d.hide();
							frm.reload_doc();
						},
					});
				},
			});
			d.show();
		}, __('Traceability'));

		frm.add_custom_button(__('Generate Carton Serials'), () => {
			const d = new frappe.ui.Dialog({
				title: __('Generate Carton Serials'),
				fields: [
					{ fieldname: 'boxes', label: __('Number of cartons/boxes'), fieldtype: 'Int', reqd: 1, default: 1 },
					{ fieldname: 'item_code', label: __('Item'), fieldtype: 'Link', options: 'Item' },
					{ fieldname: 'width_mm', label: __('Width mm'), fieldtype: 'Float' },
					{ fieldname: 'length_mtr', label: __('Length m'), fieldtype: 'Float' },
				],
				primary_action_label: __('Generate'),
				primary_action(values) {
					frappe.call({
						method: 'instabiz.overrides.mfg_serials.create_carton_serials_for_output',
						args: {
							work_order: frm.doc.name,
							boxes: values.boxes,
							item_code: values.item_code,
							width_mm: values.width_mm,
							length_mtr: values.length_mtr,
						},
						freeze: true,
						freeze_message: __('Creating carton serials…'),
						callback(r) {
							const m = r.message || {};
							frappe.msgprint(m.message || JSON.stringify(m).slice(0, 500));
							d.hide();
							frm.reload_doc();
						},
					});
				},
			});
			d.show();
		}, __('Traceability'));

		frm.add_custom_button(__('Trace chain'), () => {
			const d = new frappe.ui.Dialog({
				title: __('Trace chain'),
				fields: [
					{
						fieldname: 'serial_or_carton',
						label: __('FG / carton serial (or leave blank for this WO)'),
						fieldtype: 'Data',
						default: frm.doc.name,
					},
				],
				primary_action_label: __('Trace'),
				primary_action(values) {
					frappe.call({
						method: 'instabiz.overrides.mfg_serials.list_trace_chain',
						args: { serial_or_carton: values.serial_or_carton || frm.doc.name },
						callback(r) {
							frappe.msgprint({
								title: __('Trace'),
								message: `<pre style="white-space:pre-wrap">${frappe.utils.escape_html(
									JSON.stringify(r.message || {}, null, 2).slice(0, 3500)
								)}</pre>`,
							});
							d.hide();
						},
					});
				},
			});
			d.show();
		}, __('Traceability'));
	},
});
