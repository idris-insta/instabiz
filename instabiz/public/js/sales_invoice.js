frappe.ui.form.on("Sales Invoice", {
	async refresh(frm) {
		if (frm.doc.docstatus === 1) {
			// Native is_return path is blocked server-side (see is_return handler
			// below + instabiz.overrides.sales_invoice) — the button stays, but now
			// opens a prefilled IB Credit Note instead of the native return flow.
			frm.page.remove_inner_button(__("Return / Credit Note"), __("Create"));
			frm.add_custom_button(__("Return / Credit Note"), () => ib_si_open_credit_note(frm), __("Create"));
			ib_watch_ewaybill_dialog(frm);
			let gstin = frm.doc.billing_address_gstin || frm.doc.shipping_address_gstin || "";
			if (!gstin && frm.doc.customer_address) {
				try {
					const r = await frappe.db.get_value("Address", frm.doc.customer_address, "gstin");
					gstin = r?.message?.gstin || "";
				} catch (_) {}
			}
			localStorage.setItem("ib_ewb_gstin", gstin);
		}

		if (frm.doc.docstatus === 0) {
			ib_si_setup_row_buttons(frm);
			ib_si_source_floor_button(frm);
		}
	},

	// Server also blocks this on save (instabiz.overrides.sales_invoice) — this
	// just catches it the moment the box is checked instead of after the form
	// is filled in. IB Credit Note is the only supported path since 2026-08-12.
	is_return(frm) {
		if (frm.doc.is_return && frm.is_new()) {
			frm.set_value("is_return", 0);
			frappe.msgprint({
				title: __("Use IB Credit Note Instead"),
				indicator: "orange",
				message: __("Don't create a return here — use <b>IB Credit Note</b> instead (Workspace → IB Credit Note → New)."),
			});
		}
	},
});

function ib_si_open_credit_note(frm) {
	// IB Credit Note's own against_sales_invoice field handler already fetches
	// the SI, maps every item, and refreshes totals — reuse it via set_value
	// (a real field-trigger) instead of duplicating that logic here. A raw
	// Object.assign prefill bypasses field triggers entirely, which is exactly
	// what left Total/Tax/Grand Total sitting at 0 until save.
	frappe.model.with_doctype("IB Credit Note", () => {
		const doc = frappe.model.get_new_doc("IB Credit Note");
		frappe.set_route("Form", "IB Credit Note", doc.name).then(() => {
			cur_frm.set_value("against_sales_invoice", frm.doc.name);
		});
	});
}

function ib_si_setup_row_buttons(frm) {
	const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
	if (!grid) return;

	if (!grid._ib_si_patched) {
		grid._ib_si_patched = true;
		const _orig = grid.refresh.bind(grid);
		grid.refresh = function (...args) {
			const r = _orig(...args);
			ib_si_inject_row_btns(frm, grid);
			return r;
		};
	}

	ib_si_inject_row_btns(frm, grid);
}

function ib_si_inject_row_btns(frm, grid) {
	grid.wrapper.find(".grid-row").each(function () {
		const $row = $(this);
		if ($row.find(".ib-si-row-btns").length) return;

		const $openBtn = $row.find(".btn-open-row");
		if (!$openBtn.length) return;

		const $col = $openBtn.parent();
		$col.css({
			display: "flex",
			"align-items": "center",
			gap: "3px",
			"min-width": "68px",
			padding: "0 4px",
		});

		const $copy = $(
			`<button class="btn btn-xs btn-default ib-si-copy-btn" type="button" title="Copy row"
				style="height:22px;width:22px;padding:0;font-size:11px;flex-shrink:0;border-radius:3px">
				<i class="fa fa-copy"></i>
			</button>`
		);
		const $ndup = $(
			`<button class="btn btn-xs btn-default ib-si-ndup-btn" type="button" title="N copies"
				style="height:22px;width:22px;padding:0;font-size:11px;font-weight:700;flex-shrink:0;border-radius:3px">
				N
			</button>`
		);

		$copy.on("click", function (e) {
			e.stopPropagation();
			e.preventDefault();
			ib_si_copy_row(frm, parseInt($(this).closest(".grid-row").attr("data-idx")));
		});

		$ndup.on("click", function (e) {
			e.stopPropagation();
			e.preventDefault();
			ib_si_ndup_row(frm, parseInt($(this).closest(".grid-row").attr("data-idx")));
		});

		$('<span class="ib-si-row-btns" style="display:inline-flex;align-items:center;gap:3px"></span>')
			.append($copy)
			.append($ndup)
			.prependTo($col);
	});
}

const _SI_SKIP = new Set([
	"name", "idx", "creation", "modified", "modified_by",
	"owner", "docstatus", "__unedited",
]);

function ib_si_copy_row(frm, idx) {
	const src = frm.doc.items[idx - 1];
	if (!src) return;
	const row = frm.add_child("items");
	Object.keys(src).forEach(k => { if (!_SI_SKIP.has(k)) row[k] = src[k]; });
	frm.refresh_field("items");
	frm.dirty();
}

function ib_si_ndup_row(frm, idx) {
	frappe.prompt(
		{ label: __("Number of copies"), fieldname: "n", fieldtype: "Int", default: 2, reqd: 1 },
		({ n }) => {
			if (!n || n < 1) return;
			const src = frm.doc.items[idx - 1];
			if (!src) return;
			for (let i = 0; i < n; i++) {
				const row = frm.add_child("items");
				Object.keys(src).forEach(k => { if (!_SI_SKIP.has(k)) row[k] = src[k]; });
			}
			frm.refresh_field("items");
			frm.dirty();
		},
		__("How many copies?"),
		__("Create")
	);
}

// Only relevant when the invoice itself moves stock (update_stock) — otherwise
// the Delivery Note already decided which floor the goods left from.
// Shared dialog lives in ib_source_floor.js.
function ib_si_source_floor_button(frm) {
	if (!cint(frm.doc.update_stock)) return;
	if (!(frm.doc.items || []).length) return;
	frm.add_custom_button(__("Source Floor"), () =>
		ib_pick_floor(frm, { row_field: "warehouse", header_field: "set_warehouse" })
	);
}

// Ported from the "IB Transport Charges SI" Client Script (2026-09-23).
// Mirrors the freight tax row while typing; the real GST-on-transport
// calculation happens server-side on save, hence the nudge.
frappe.ui.form.on("Sales Invoice", {
	custom_transport_charges(frm) {
		const amt = flt(frm.doc.custom_transport_charges);
		const freight_row = (frm.doc.taxes || []).find((r) =>
			(r.account_head || "").toLowerCase().includes("freight")
		);
		if (freight_row) {
			frappe.model.set_value(freight_row.doctype, freight_row.name, "tax_amount", amt);
			frm.refresh_field("taxes");
		}
		if (amt) {
			frappe.show_alert(
				{
					message: __("Transport charges set. Save to apply GST on transport."),
					indicator: "blue",
				},
				4
			);
		}
	},
});
