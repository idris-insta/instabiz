/**
 * ib_sales_common.js
 * Shared Quotation / Sales Order behaviour.
 * Registered via doctype_js in hooks.py.
 *
 * The item search that used to live here now applies to every document that
 * takes items — see ib_item_picker.js, loaded globally.
 */

frappe.ui.form.on("Sales Order", {
	onload(frm) {
		if (frm.is_new() && !frm.doc.delivery_date) {
			frm.set_value("delivery_date", frappe.datetime.add_days(frm.doc.transaction_date || frappe.datetime.get_today(), ib_default_delivery_days()));
		}
	},
	// Default ETD = order date + 8 days — only while the doc is still new/unsaved,
	// so editing transaction_date on an existing order never touches a real delivery_date.
	transaction_date(frm) {
		if (frm.is_new()) {
			frm.set_value("delivery_date", frappe.datetime.add_days(frm.doc.transaction_date || frappe.datetime.get_today(), ib_default_delivery_days()));
		}
	},
});

// Advance-payment approval gate: a Draft SO with an unapproved advance can't
// be confirmed (blocked server-side in advance_approval.py). Approve/Reject
// buttons only shown to the designated approver.
// Approvers come from IB Sales Settings via boot (ib_settings.boot_session).
function ib_advance_approvers() {
	return (frappe.boot.ib_settings && frappe.boot.ib_settings.advance_approvers) || ["idris@instabizsolutions.com"];
}

function ib_default_delivery_days() {
	return (frappe.boot.ib_settings && frappe.boot.ib_settings.default_delivery_days) || 8;
}

frappe.ui.form.on("Sales Order", {
	refresh(frm) {
		if (frm.doc.docstatus !== 0) return;
		if (frm.doc.custom_advance_approval_status !== "Pending") return;
		const can_approve =
			ib_advance_approvers().includes(frappe.session.user) || frappe.user.has_role("System Manager");
		if (!can_approve) return;

		frm.add_custom_button(__("Approve"), () => ib_decide_advance(frm, "Approved"), __("Advance"));
		frm.add_custom_button(__("Reject"), () => ib_decide_advance(frm, "Rejected"), __("Advance"));
	},
});

function ib_decide_advance(frm, status) {
	frappe.prompt(
		[{ fieldname: "remarks", label: __("Remarks"), fieldtype: "Small Text" }],
		(values) => {
			frappe.call({
				method: "instabiz.overrides.advance_approval.set_advance_approval",
				args: { sales_order: frm.doc.name, status, remarks: values.remarks },
				callback: () => frm.reload_doc(),
			});
		},
		__(status === "Approved" ? "Approve Advance Payment" : "Reject Advance Payment"),
		__(status)
	);
}

// Record Advance (Deposit) — the only way to reach the advance-approval feature
// at all pre-submit. The standard "Create > Payment" button never shows for a
// Draft SO, and a Payment Entry referencing a non-submitted Sales Order in its
// references table is rejected outright by core ERPNext validation. This opens
// a plain on-account Payment Entry instead: no references row, just
// custom_advance_for_so pointing back at this order (see payment_entry.js /
// instabiz.overrides.payment_entry._update_advance_for_so). Uses the
// simplified dialog (ib_simple_payment_dialog.js, 2026-09-04) instead of the
// full native Payment Entry form — same reasoning as the Payment Entry list's
// own "+ Add" override, see payment_entry_list.js.
frappe.ui.form.on("Sales Order", {
	refresh(frm) {
		if (frm.doc.docstatus !== 0 || frm.is_new()) return;
		if (!frm.doc.customer) return;

		frm.add_custom_button(__("Record Advance (Deposit)"), () => {
			ib_show_simple_payment_dialog({
				customer: frm.doc.customer,
				lock_customer: true,
				advance_for_so: frm.doc.name,
				on_success(name) {
					frappe.set_route("Form", "Payment Entry", name);
				},
			});
		}, __("Create"));
	},
});

// Factory Digital Twin — "Can we deliver by...?" read-only feasibility check
// (instabiz.overrides.production_twin.simulate). Gated to the same roles
// simulate() itself requires server-side (_require_production_role — Factory
// Management / Factory Production / System Manager), so the button never
// shows to a user who'd just get a PermissionError from clicking it.
const IB_TWIN_ROLES = ["Factory Management", "Factory Production", "System Manager"];

frappe.ui.form.on("Sales Order", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.name) return;
		if (!IB_TWIN_ROLES.some((role) => frappe.user.has_role(role))) return;

		frm.add_custom_button(__("Can we deliver by...?"), () => ib_open_delivery_twin(frm), __("Production"));
	},
});

function ib_open_delivery_twin(frm) {
	const default_date = frm.doc.delivery_date || frappe.datetime.add_days(frappe.datetime.get_today(), 8);
	frappe.prompt(
		[
			{
				fieldname: "target_delivery_date",
				label: __("Target Delivery Date"),
				fieldtype: "Date",
				reqd: 1,
				default: default_date,
			},
		],
		(values) => {
			frappe.call({
				method: "instabiz.overrides.production_twin.simulate",
				args: { sales_order: frm.doc.name, target_delivery_date: values.target_delivery_date },
				freeze: true,
				freeze_message: __("Simulating factory capacity..."),
				callback: (r) => ib_render_twin_result(r.message),
			});
		},
		__("Factory Digital Twin — Delivery Feasibility"),
		__("Simulate")
	);
}

function ib_render_twin_result(result) {
	if (!result) return;
	const verdict = result.feasible
		? `<span style="color:var(--green-600, #29a745); font-weight:600;">&#10003; ${__("Yes — feasible")}</span>`
		: `<span style="color:var(--red-600, #d33); font-weight:600;">&#10007; ${__("No — at risk")}</span>`;

	let bottleneck_html = "";
	if (result.bottleneck) {
		const b = result.bottleneck;
		bottleneck_html = `
			<p><b>${__("Bottleneck")}:</b> ${frappe.utils.escape_html(b.item_code || "")} &mdash;
			${frappe.utils.escape_html(b.stage || "")}
			${b.machine ? "@ " + frappe.utils.escape_html(b.machine) : ""}
			(${frappe.utils.escape_html(b.reason || "")})</p>`;
	}

	const rows = (result.per_item_breakdown || [])
		.map(
			(it) => `
			<tr>
				<td>${frappe.utils.escape_html(it.item_code)}</td>
				<td>${frappe.utils.escape_html(String(it.qty))}</td>
				<td>${frappe.utils.escape_html(it.estimated_completion_date)}</td>
				<td>${frappe.utils.escape_html(String(it.total_hours))}h</td>
			</tr>`
		)
		.join("");

	const html = `
		<div>
			<p style="font-size:16px;">${verdict}</p>
			<p><b>${__("Estimated Completion")}:</b> ${frappe.utils.escape_html(result.estimated_completion_date)}
			&nbsp;|&nbsp; <b>${__("Target")}:</b> ${frappe.utils.escape_html(result.target_delivery_date)}</p>
			${bottleneck_html}
			<table class="table table-bordered" style="margin-top:10px;">
				<thead><tr><th>${__("Item")}</th><th>${__("Qty")}</th><th>${__("Est. Completion")}</th><th>${__("Hours")}</th></tr></thead>
				<tbody>${rows}</tbody>
			</table>
		</div>`;

	frappe.msgprint({
		title: __("Delivery Feasibility"),
		message: html,
		indicator: result.feasible ? "green" : "red",
	});
}

// Promise date — the date the rep can actually commit, line by line: stock in the
// location → transit from another branch → factory backlog → purchase lead time
// (instabiz.overrides.promise_date). Shown as a headline; "Use" sets Delivery Date.
frappe.ui.form.on("Sales Order", {
	refresh(frm) {
		ib_promise_refresh(frm);
	},
	custom_location(frm) {
		ib_promise_refresh(frm);
	},
	set_warehouse(frm) {
		ib_promise_refresh(frm);
	},
});
frappe.ui.form.on("Sales Order Item", {
	item_code(frm) {
		ib_promise_refresh(frm);
	},
	qty(frm) {
		ib_promise_refresh(frm);
	},
	items_remove(frm) {
		ib_promise_refresh(frm);
	},
});

function ib_promise_refresh(frm) {
	if (frm.doc.docstatus === 2 || !(frm.doc.items || []).some((r) => r.item_code)) return;
	if (frm.doc.docstatus === 1 && ["Completed", "Closed", "Confirmed"].includes(frm.doc.status) && frm.doc.per_delivered >= 100) return;
	clearTimeout(frm._ib_promise_t);
	frm._ib_promise_t = setTimeout(() => {
		const args = frm.doc.docstatus === 1 ? { sales_order: frm.doc.name } : { doc: JSON.stringify(frm.doc) };
		frappe.call({ method: "instabiz.overrides.promise_date.get_promise", args, quiet: true }).then((r) => {
			const p = r.message;
			if (!p) return;
			if (Object.keys(p.counts).every((k) => k === "Delivered")) return;
			const labels = { Stock: __("from stock"), Transit: __("in transit"), Production: __("to make"),
				Purchase: __("to buy / transfer"), Delivered: __("delivered") };
			const parts = Object.entries(p.counts).map(([k, n]) => `${n} ${labels[k] || k}`).join(" · ");
			const late = frm.doc.delivery_date && frm.doc.delivery_date < p.promise_date;
			const colour = late ? "var(--red-600)" : "var(--green-700)";
			let html = `<span style="color:${colour};font-weight:600">${__("Can deliver by {0}", [frappe.datetime.str_to_user(p.promise_date)])}</span>
				<span class="text-muted"> — ${parts}</span>
				<a class="ib-promise-detail" style="margin-left:8px">${__("Details")}</a>`;
			if (frm.doc.docstatus === 0 && frm.doc.delivery_date !== p.promise_date) {
				html += ` <a class="ib-promise-use" style="margin-left:8px">${__("Use this date")}</a>`;
			}
			if (late) html += `<div class="text-muted small">${__("Delivery Date on the order is earlier than this.")}</div>`;
			frm.dashboard.set_headline(html);
			const $h = frm.dashboard.$headline || $(frm.dashboard.wrapper).find(".form-headline");
			$h.find(".ib-promise-use").on("click", () => frm.set_value("delivery_date", p.promise_date));
			$h.find(".ib-promise-detail").on("click", () => ib_promise_dialog(p));
		});
	}, 600);
}

function ib_promise_dialog(p) {
	const e = frappe.utils.escape_html;
	const rows = p.lines.map((l) => `<tr><td>${l.idx || ""}</td><td>${e(l.item_code)}</td><td>${e(String(l.qty))}</td>
		<td>${e(l.source)}</td><td>${frappe.datetime.str_to_user(l.date)}</td><td class="text-muted">${e(l.note || "")}</td></tr>`).join("");
	frappe.msgprint({
		title: __("Promise date {0}", [frappe.datetime.str_to_user(p.promise_date)]),
		wide: true,
		message: `<table class="table table-bordered table-sm"><thead><tr><th>#</th><th>${__("Item")}</th><th>${__("Qty")}</th>
			<th>${__("From")}</th><th>${__("Ready by")}</th><th>${__("Note")}</th></tr></thead><tbody>${rows}</tbody></table>
			<div class="text-muted small">${__("Days used are in Sales Settings (dispatch, transit) and Stock Settings (replenishment lead time).")}</div>`,
	});
}
