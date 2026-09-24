frappe.ui.form.on("Delivery Note", {
	async refresh(frm) {
		if (frm.doc.docstatus === 1) {
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

		// Keep submitted DNs editable (LR number, transporter updates etc.)
		if (frm.doc.docstatus === 1) {
			frm.enable_save();
			frm.set_df_property("items", "read_only", 0);
		}

		ib_dn_setup_row_buttons(frm);
		ib_dn_source_floor_button(frm);
	},
});

// Floors of one location share a GSTIN, so moving the pick between them is an
// internal stock decision — shared dialog lives in ib_source_floor.js.
function ib_dn_source_floor_button(frm) {
	if (frm.doc.docstatus !== 0 || !(frm.doc.items || []).length) return;
	frm.add_custom_button(__("Source Floor"), () =>
		ib_pick_floor(frm, { row_field: "warehouse", header_field: "set_warehouse" })
	);
}

function ib_dn_setup_row_buttons(frm) {
	const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
	if (!grid) return;

	// Patch grid.refresh once so buttons survive re-renders
	if (!grid._ib_patched) {
		grid._ib_patched = true;
		const _orig = grid.refresh.bind(grid);
		grid.refresh = function (...args) {
			const r = _orig(...args);
			ib_dn_inject_row_btns(frm, grid);
			return r;
		};
	}

	ib_dn_inject_row_btns(frm, grid);
}

function ib_dn_inject_row_btns(frm, grid) {
	grid.wrapper.find(".grid-row").each(function () {
		const $row = $(this);
		if ($row.find(".ib-row-btns").length) return; // already injected

		const $openBtn = $row.find(".btn-open-row");
		if (!$openBtn.length) return;

		// .btn-open-row lives inside a .col div that has its own toggle_view click
		// handler.  We MUST use direct binding (not delegation) so stopPropagation
		// fires on the button itself — before the event bubbles to .col or .data-row.
		const $col = $openBtn.parent();

		// Make the pencil col flex so our buttons + pencil sit side-by-side
		$col.css({
			display: "flex",
			"align-items": "center",
			gap: "3px",
			"min-width": "68px",
			padding: "0 4px",
		});

		const $copy = $(
			`<button class="btn btn-xs btn-default ib-copy-row" type="button" title="Copy row"
				style="height:22px;width:22px;padding:0;font-size:11px;flex-shrink:0;border-radius:3px">
				<i class="fa fa-copy"></i>
			</button>`
		);
		const $ndup = $(
			`<button class="btn btn-xs btn-default ib-ndup-row" type="button" title="N Duplicates"
				style="height:22px;width:22px;padding:0;font-size:11px;font-weight:700;flex-shrink:0;border-radius:3px">
				N
			</button>`
		);

		// Direct binding — stopPropagation fires before .col / .data-row handlers
		$copy.on("click", function (e) {
			e.stopPropagation();
			e.preventDefault();
			ib_dn_copy_row(frm, parseInt($(this).closest(".grid-row").attr("data-idx")));
		});

		$ndup.on("click", function (e) {
			e.stopPropagation();
			e.preventDefault();
			ib_dn_ndup_row(frm, parseInt($(this).closest(".grid-row").attr("data-idx")));
		});

		$('<span class="ib-row-btns" style="display:inline-flex;align-items:center;gap:3px"></span>')
			.append($copy)
			.append($ndup)
			.prependTo($col); // prepend → buttons appear left of pencil in flex row
	});
}

const _SKIP = new Set([
	"name", "idx", "creation", "modified", "modified_by",
	"owner", "docstatus", "__unedited",
]);

function ib_dn_copy_row(frm, idx) {
	const src = frm.doc.items[idx - 1];
	if (!src) return;
	const row = frm.add_child("items");
	Object.keys(src).forEach(k => { if (!_SKIP.has(k)) row[k] = src[k]; });
	frm.refresh_field("items");
	frm.dirty();
}

function ib_dn_ndup_row(frm, idx) {
	frappe.prompt(
		{ label: __("Number of copies"), fieldname: "n", fieldtype: "Int", default: 2, reqd: 1 },
		({ n }) => {
			if (!n || n < 1) return;
			const src = frm.doc.items[idx - 1];
			if (!src) return;
			for (let i = 0; i < n; i++) {
				const row = frm.add_child("items");
				Object.keys(src).forEach(k => { if (!_SKIP.has(k)) row[k] = src[k]; });
			}
			frm.refresh_field("items");
			frm.dirty();
		},
		__("How many copies?"),
		__("Create")
	);
}
