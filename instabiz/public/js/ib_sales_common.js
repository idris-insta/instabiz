/**
 * ib_sales_common.js
 * Shared item query override for all selling transactions.
 * Registered for Quotation and Sales Order via doctype_js in hooks.py.
 */

function ib_set_item_query(frm, customer_field) {
	frm.set_query("item_code", "items", function () {
		return {
			query: "instabiz.overrides.item.item_query",
			filters: { customer: frm.doc[customer_field] || "" },
			page_length: 30,
		};
	});
}

frappe.ui.form.on("Quotation", {
	refresh: (frm) => ib_set_item_query(frm, "party_name"),
});

frappe.ui.form.on("Sales Order", {
	refresh: (frm) => ib_set_item_query(frm, "customer"),
	onload(frm) {
		if (frm.is_new() && !frm.doc.delivery_date) {
			frm.set_value("delivery_date", frappe.datetime.add_days(frm.doc.transaction_date || frappe.datetime.get_today(), 8));
		}
	},
	// Default ETD = order date + 8 days — only while the doc is still new/unsaved,
	// so editing transaction_date on an existing order never touches a real delivery_date.
	transaction_date(frm) {
		if (frm.is_new()) {
			frm.set_value("delivery_date", frappe.datetime.add_days(frm.doc.transaction_date || frappe.datetime.get_today(), 8));
		}
	},
});

// Advance-payment approval gate: a Draft SO with an unapproved advance can't
// be confirmed (blocked server-side in advance_approval.py). Approve/Reject
// buttons only shown to the designated approver.
const IB_ADVANCE_APPROVER = "idris@instabizsolutions.com";

frappe.ui.form.on("Sales Order", {
	refresh(frm) {
		if (frm.doc.docstatus !== 0) return;
		if (frm.doc.custom_advance_approval_status !== "Pending") return;
		const can_approve =
			frappe.session.user === IB_ADVANCE_APPROVER || frappe.user.has_role("System Manager");
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
