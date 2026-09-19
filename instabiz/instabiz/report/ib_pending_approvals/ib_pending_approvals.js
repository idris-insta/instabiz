frappe.query_reports["IB Pending Approvals"] = {
	filters: [
		{ fieldname: "kind", label: __("What"), fieldtype: "Select",
			options: ["", "Accounting entry", "Advance on order", "Leave", "Overtime", "Expense claim"].join("\n") },
		{ fieldname: "only_mine", label: __("Only what I can approve"), fieldtype: "Check", default: 1 },
	],
	formatter(value, row, column, data, default_formatter) {
		if (column.fieldname === "action" && data && data.action) {
			if (["Journal Entry", "Payment Entry"].includes(data.doctype)) {
				const dt = encodeURIComponent(data.doctype), n = encodeURIComponent(data.name);
				return `<a class="btn btn-xs btn-primary" onclick="ib_decide('${dt}','${n}',1)">${__("Approve")}</a>
					<a class="btn btn-xs btn-default" onclick="ib_decide('${dt}','${n}',0)">${__("Reject")}</a>`;
			}
			return `<a class="btn btn-xs btn-default" href="/app/${frappe.router.slug(data.doctype)}/${encodeURIComponent(data.name)}">${__("Open")}</a>`;
		}
		return default_formatter(value, row, column, data);
	},
};

window.ib_decide = function (dt, name, approve) {
	dt = decodeURIComponent(dt);
	name = decodeURIComponent(name);
	const go = (note) => frappe.call({ method: "instabiz.overrides.approvals.decide", args: { doctype: dt, name, approve, note }, freeze: true })
		.then(() => { frappe.show_alert({ message: approve ? __("Approved") : __("Rejected"), indicator: approve ? "green" : "orange" }); frappe.query_report.refresh(); });
	if (approve) frappe.confirm(__("Approve and submit {0}?", [name]), () => go());
	else frappe.prompt({ fieldtype: "Small Text", fieldname: "note", label: __("Reason"), reqd: 1 }, (v) => go(v.note), __("Reject {0}", [name]));
};
