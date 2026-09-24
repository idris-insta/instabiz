/**
 * Shared "pick a floor" dialog for Delivery Note, Sales Invoice and Stock Entry.
 *
 * Floors are an internal split of one location — same GSTIN either way — so
 * moving the pick between them is a stock question, never a tax one. The dialog
 * shows what each floor can actually cover for the rows on the document, so the
 * operator picks on real availability instead of guessing.
 *
 * ib_pick_floor(frm, {
 *   row_field:    "warehouse" | "s_warehouse" | "t_warehouse",
 *   header_field: "set_warehouse" | "from_warehouse" | "to_warehouse",
 *   mode:         "source" (default) | "target",
 *   title:        dialog heading,
 *   location:     optional override; falls back to frm.doc.custom_location
 * })
 */
function ib_pick_floor(frm, opts) {
	opts = opts || {};
	const row_field = opts.row_field || "warehouse";
	const header_field = opts.header_field || "set_warehouse";
	const mode = opts.mode === "target" ? "target" : "source";

	const items = (frm.doc.items || [])
		.filter((r) => r.item_code)
		.map((r) => ({
			item_code: r.item_code,
			qty: flt(r.transfer_qty || r.stock_qty || r.qty || 0),
		}));

	if (!items.length) {
		frappe.msgprint(__("Add items first."));
		return;
	}

	frappe.call({
		method: "instabiz.overrides.source_warehouse.get_source_options",
		args: {
			location: opts.location || frm.doc.custom_location || null,
			company: frm.doc.company,
			items: JSON.stringify(items),
			mode: mode,
		},
		freeze: true,
		freeze_message: __("Checking floors…"),
		callback: (r) => {
			const list = (r.message || {}).warehouses || [];
			if (!list.length) {
				frappe.msgprint(
					__("No usable floor found. Check the Location on this document, or that the warehouse is enabled.")
				);
				return;
			}
			ib_show_floor_dialog(frm, list, {
				row_field,
				header_field,
				mode,
				title: opts.title || (mode === "target" ? __("Pick target floor") : __("Pick source floor")),
				item_count: items.length,
			});
		},
	});
}

function ib_show_floor_dialog(frm, list, cfg) {
	const esc = frappe.utils.escape_html;
	const current = frm.doc[cfg.header_field] || "";
	const is_target = cfg.mode === "target";

	const rows = list
		.map((w) => {
			let tone = "gray";
			let note = "";
			if (is_target) {
				note = w.on_hand
					? __("holds {0} of these items", [format_number(w.on_hand, null, 2)])
					: __("empty for these items");
				tone = "blue";
			} else {
				const full = w.covered === w.total;
				tone = full ? "green" : w.covered ? "orange" : "red";
				note = full
					? __("covers all {0} items", [w.total])
					: __("{0} of {1} items, short {2}", [w.covered, w.total, format_number(w.shortfall, null, 2)]);
			}

			const short = (w.lines || [])
				.filter((l) => !l.full)
				.slice(0, 4)
				.map(
					(l) =>
						`<div class="text-muted small">${esc(l.item_code)} — ${__("need")} ${format_number(
							l.need,
							null,
							2
						)}, ${__("have")} ${format_number(l.available, null, 2)}</div>`
				)
				.join("");

			return `
				<label class="ib-floor" data-wh="${esc(w.warehouse)}">
					<input type="radio" name="ib_floor_pick" value="${esc(w.warehouse)}" ${
						w.warehouse === current ? "checked" : ""
					}>
					<span class="ib-floor-body">
						<span class="ib-floor-head">
							<b>${esc(w.label)}</b>
							<span class="indicator-pill ${tone} no-indicator-dot">${esc(note)}</span>
							${
								w.dispatchable
									? ""
									: `<span class="text-muted small">${__("not a dispatch floor")}</span>`
							}
						</span>
						<span class="text-muted small">${esc(w.warehouse)}</span>
						${short}
					</span>
				</label>`;
		})
		.join("");

	const d = new frappe.ui.Dialog({
		title: cfg.title,
		size: "large",
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "floors",
				options: `
					<div class="ib-floors">
						<p class="text-muted small">${__(
							"Same GSTIN either way — this only changes which floor the stock moves from."
						)}</p>
						${rows}
					</div>
					<style>
						.ib-floors .ib-floor { display:flex; gap:10px; align-items:flex-start;
							padding:10px 12px; border:1px solid var(--border-color); border-radius:var(--border-radius-md);
							margin-bottom:8px; cursor:pointer; font-weight:normal; }
						.ib-floors .ib-floor:hover { border-color:var(--primary); }
						.ib-floor-body { display:flex; flex-direction:column; gap:2px; min-width:0; }
						.ib-floor-head { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
					</style>`,
			},
			{
				fieldtype: "Check",
				fieldname: "only_blank",
				label: __("Only fill lines that have no warehouse yet"),
				default: 0,
			},
		],
		primary_action_label: __("Apply to {0} lines", [cfg.item_count]),
		primary_action: () => {
			const picked = d.$wrapper.find("input[name=ib_floor_pick]:checked").val();
			if (!picked) {
				frappe.msgprint(__("Pick a floor."));
				return;
			}
			const only_blank = d.get_value("only_blank") ? 1 : 0;
			let changed = 0;
			(frm.doc.items || []).forEach((row) => {
				if (only_blank && row[cfg.row_field]) return;
				if (row[cfg.row_field] !== picked) {
					frappe.model.set_value(row.doctype, row.name, cfg.row_field, picked);
					changed++;
				}
			});
			if (frm.meta.fields.some((f) => f.fieldname === cfg.header_field)) {
				frm.set_value(cfg.header_field, picked);
			}
			d.hide();
			frappe.show_alert({
				message: __("{0} — {1} lines repointed", [picked.split(" - ")[0], changed]),
				indicator: "green",
			});
		},
	});
	d.show();
}
