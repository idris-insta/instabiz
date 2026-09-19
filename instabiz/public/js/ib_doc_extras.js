// Item documents on sales documents + two-step branch transfer on Stock Entry.
(() => {
	["Quotation", "Sales Order", "Delivery Note"].forEach((dt) => {
		frappe.ui.form.on(dt, {
			refresh(frm) {
				if (frm.is_new() || frm.doc.docstatus === 2) return;
				frm.add_custom_button(__("Attach Item Documents"), () =>
					frappe.call("instabiz.instabiz.doctype.ib_item_document.ib_item_document.attach_to",
						{ doctype: dt, name: frm.doc.name }).then((r) => {
						const m = r.message || {};
						frappe.show_alert({ indicator: m.available ? "green" : "orange",
							message: m.available ? __("{0} document(s) attached", [m.added]) : __("No TDS / SDS / COA uploaded for these items") });
						frm.reload_doc();
					}), __("Create"));
			},
		});
	});

	frappe.ui.form.on("Customer", {
		refresh(frm) {
			if (frm.is_new() || !frappe.model.can_write("Customer")) return;
			frm.add_custom_button(__("Portal Login"), () => {
				frappe.prompt([
					{ fieldtype: "Data", fieldname: "email", label: __("Customer's email (login)"), options: "Email", reqd: 1, default: frm.doc.email_id },
					{ fieldtype: "Data", fieldname: "mobile", label: __("Mobile"), default: frm.doc.mobile_no },
				], (v) => frappe.call("instabiz.overrides.portal.give_portal_login", { customer: frm.doc.name, ...v }).then((r) => {
					const m = r.message;
					const text = __("Your Instabiz account: {0}\nSet your password here: {1}\nThen log in with {2}", [m.portal, m.link, m.email]);
					const phone = (v.mobile || "").replace(/\D/g, "").slice(-10);
					frappe.msgprint({ title: __("Portal login ready"), message:
						`<p>${__("Send this to the customer (the link sets their password):")}</p><pre style="white-space:pre-wrap">${frappe.utils.escape_html(text)}</pre>` +
						(phone ? `<a class="btn btn-primary btn-sm" target="_blank" href="https://wa.me/91${phone}?text=${encodeURIComponent(text)}">${__("Send on WhatsApp")}</a>` : "") });
				}), __("Customer Portal Login"), __("Create"));
			}, __("Actions"));
		},
	});

	["Journal Entry", "Payment Entry"].forEach((dt) => {
		frappe.ui.form.on(dt, {
			refresh(frm) {
				const st = frm.doc.custom_approval_status;
				if (st) frm.dashboard.add_indicator(__("Approval: {0}", [__(st)]), st === "Approved" ? "green" : st === "Rejected" ? "red" : "orange");
				if (frm.doc.custom_approval_note) frm.dashboard.set_headline(__("Approver: {0}", [frappe.utils.escape_html(frm.doc.custom_approval_note)]));
				if (frm.doc.docstatus !== 0 || frm.is_new()) return;
				if (st !== "Pending") {
					frm.add_custom_button(__("Send for Approval"), () =>
						frappe.call("instabiz.overrides.approvals.send_for_approval", { doctype: dt, name: frm.doc.name })
							.then(() => frm.reload_doc()));
				} else if (frappe.user.has_role(["Accounts Manager", "System Manager"])) {
					frm.add_custom_button(__("Approve"), () =>
						frappe.call("instabiz.overrides.approvals.decide", { doctype: dt, name: frm.doc.name, approve: 1 })
							.then(() => frm.reload_doc())).addClass("btn-primary");
					frm.add_custom_button(__("Reject"), () =>
						frappe.prompt({ fieldtype: "Small Text", fieldname: "note", label: __("Reason"), reqd: 1 }, (v) =>
							frappe.call("instabiz.overrides.approvals.decide", { doctype: dt, name: frm.doc.name, approve: 0, note: v.note })
								.then(() => frm.reload_doc())));
				}
			},
		});
	});

	frappe.ui.form.on("Item", {
		refresh(frm) {
			if (frm.is_new()) return;
			frm.add_custom_button(__("Documents (TDS / SDS / COA)"), () =>
				frappe.set_route("List", "IB Item Document", { item_code: frm.doc.name }));
		},
	});

	frappe.ui.form.on("Stock Entry", {
		refresh(frm) {
			const d = frm.doc;
			if (d.docstatus === 1 && d.add_to_transit && flt(d.per_transferred) < 100) {
				frm.add_custom_button(__("Receive at {0}", [d.custom_final_warehouse || __("destination")]), () =>
					frappe.call("instabiz.overrides.branch_transfer.receive", { stock_entry: d.name })
						.then((r) => frappe.set_route("Form", "Stock Entry", r.message))).addClass("btn-primary");
			}
		},
	});

	window.ib_branch_transfer_dialog = function () {
		const d = new frappe.ui.Dialog({
			title: __("Stock Transfer — branch, floor or sub-warehouse"),
			size: "large",
			fields: [
				{ fieldtype: "Link", fieldname: "from_warehouse", label: __("From"), options: "Warehouse", reqd: 1,
					get_query: () => ({ filters: { is_group: 0, warehouse_type: ["!=", "Transit"] } }) },
				{ fieldtype: "Column Break" },
				{ fieldtype: "Link", fieldname: "to_warehouse", label: __("To"), options: "Warehouse", reqd: 1,
					get_query: () => ({ filters: { is_group: 0, warehouse_type: ["!=", "Transit"] } }) },
				{ fieldtype: "HTML", fieldname: "how", options: `<p class="text-muted small">${__("Same premises (floor to floor, sub-warehouse to sub-warehouse): moved in one entry. Another branch: goes into Goods In Transit and is received there.")}</p>` },
				{ fieldtype: "Section Break" },
				{ fieldtype: "Table", fieldname: "items", label: __("Items"), in_place_edit: true, data: [], reqd: 1,
					fields: [
						{ fieldtype: "Link", fieldname: "item_code", label: __("Item"), options: "Item", in_list_view: 1, reqd: 1, columns: 6 },
						{ fieldtype: "Float", fieldname: "qty", label: __("Qty (stock UOM)"), in_list_view: 1, reqd: 1, columns: 3 },
					] },
				{ fieldtype: "Section Break" },
				{ fieldtype: "Data", fieldname: "vehicle_no", label: __("Vehicle No") },
				{ fieldtype: "Column Break" },
				{ fieldtype: "Data", fieldname: "lr_no", label: __("LR No") },
			],
			primary_action_label: __("Create Transfer"),
			primary_action(v) {
				frappe.call({ method: "instabiz.overrides.branch_transfer.create_dispatch", freeze: true,
					args: { ...v, items: (v.items || []).map((r) => ({ item_code: r.item_code, qty: r.qty })) } })
					.then((r) => { d.hide(); frappe.set_route("Form", "Stock Entry", r.message); });
			},
		});
		d.show();
	};
})();
