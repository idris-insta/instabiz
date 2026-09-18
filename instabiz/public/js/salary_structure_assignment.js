// Per-day / per-hour rate beside the monthly base (overtime is paid at this
// rate). Computed server-side on save (instabiz.overrides.overtime); this keeps
// the figures live while the base is being typed on a draft.
function ib_ssa_preview_rates(frm) {
	if (frm.doc.docstatus !== 0 || !frm.doc.base) return;
	frappe.call({
		method: "instabiz.overrides.overtime.preview_rates",
		args: { monthly: frm.doc.base, on_date: frm.doc.from_date },
		callback: (r) => {
			if (!r.message) return;
			frm.set_value("custom_per_day_rate", r.message.per_day);
			frm.set_value("custom_per_hour_rate", r.message.per_hour);
		},
	});
}

frappe.ui.form.on("Salary Structure Assignment", {
	base: ib_ssa_preview_rates,
	from_date: ib_ssa_preview_rates,
	refresh(frm) {
		// Printing a Salary Structure Assignment itself is never useful (it's
		// just the assignment record, no pay figures) — redirect the toolbar
		// Print action to this employee's own Salary Slip print instead.
		// Picks the most recent Salary Slip (submitted preferred over draft,
		// via docstatus desc in the sort — see resolved question 2026-08-13);
		// if none exists yet, says so instead of opening a blank/wrong print.
		frm.print_doc = function () {
			if (!frm.doc.employee) {
				frappe.msgprint(__("No Employee set on this Salary Structure Assignment."));
				return;
			}
			frappe.db.get_list("Salary Slip", {
				filters: { employee: frm.doc.employee, docstatus: ["!=", 2] },
				fields: ["name"],
				order_by: "docstatus desc, posting_date desc",
				limit: 1,
			}).then((rows) => {
				if (!rows.length) {
					frappe.msgprint(
						__("No Salary Slip found yet for {0}.", [frm.doc.employee_name || frm.doc.employee])
					);
					return;
				}
				frappe.set_route("print", "Salary Slip", rows[0].name);
			});
		};
	},
});
