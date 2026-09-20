frappe.pages["ib-advance-approvals"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Advance Approvals",
		single_column: true,
	});
	wrapper._ib_aa = new IBAdvanceApprovals(page);
};

frappe.pages["ib-advance-approvals"].on_page_show = function (wrapper) {
	if (wrapper._ib_aa) wrapper._ib_aa.refresh();
};

// Rebuilt on the IB Design System (window.ibUI / .ib-ui-* components), 2026-09-21.
class IBAdvanceApprovals {
	constructor(page) {
		this.page = page;
		this.$el = ibUI.mount(page);
		this._inject_styles();
		this._build_layout();
		page.add_inner_button(__("Refresh"), () => this.refresh());
		this.refresh();
	}

	// Reject action needs a danger-toned button — ib-ui only ships primary/
	// ghost variants, layered here rather than adding a new global variant
	// for one page's one button.
	_inject_styles() {
		if (document.getElementById("ib-aa-page-styles")) return;
		const s = document.createElement("style");
		s.id = "ib-aa-page-styles";
		s.textContent = `
.ib-aa-btn-danger { border-color: var(--ib-danger-fg); color: var(--ib-danger-fg); }
.ib-aa-btn-danger:hover { background: var(--ib-danger-bg); color: var(--ib-danger-fg); }
.ib-aa-amount { font-weight: 700; color: var(--ib-primary); }
.ib-aa-age { font-size: 10.5px; color: var(--text-muted); }
`;
		document.head.appendChild(s);
	}

	_build_layout() {
		this.$el.html(`
			${ibUI.toolbar([`<span id="ib-aa-ts" class="ib-ui-hint" style="margin-left:auto"></span>`])}
			<div id="ib-aa-kpis"></div>
			${ibUI.section("Pending Approval", `<div id="ib-aa-pending"></div>`, { action: '<span id="ib-aa-pending-count" class="ib-ui-hint"></span>' })}
			${ibUI.section("Recent Decisions", `<div id="ib-aa-history"></div>`)}
		`);
	}

	refresh() {
		this.$el.find("#ib-aa-kpis").html(ibUI.skeleton(4));
		this.$el.find("#ib-aa-ts").text("Loading…");
		frappe.call({
			method: "instabiz.overrides.advance_approval.get_advance_approval_queue",
			callback: (r) => {
				const d = r.message || { pending: [], history: [] };
				this._render_kpis(d.pending, d.history);
				this._render_pending(d.pending);
				this._render_history(d.history);
				this.$el.find("#ib-aa-ts").text("Updated " + frappe.datetime.now_time());
			},
			error: () => this.$el.find("#ib-aa-ts").text("Error — click Refresh"),
		});
	}

	_render_kpis(pending, history) {
		const today = frappe.datetime.get_today();
		const total_pending_amt = pending.reduce((s, r) => s + (parseFloat(r.advance_paid) || 0), 0);
		const approved_today = history.filter((r) => r.status === "Approved" && (r.modified || "").slice(0, 10) === today).length;
		const rejected_today = history.filter((r) => r.status === "Rejected" && (r.modified || "").slice(0, 10) === today).length;

		this.$el.find("#ib-aa-kpis").html(ibUI.statGrid([
			{ v: pending.length, l: "Pending Requests" },
			{ v: ibUI.money(total_pending_amt), l: "Pending Amount" },
			{ v: approved_today, l: "Approved Today" },
			{ v: rejected_today, l: "Rejected Today" },
		]));
	}

	_days_ago(dt) {
		const d = frappe.datetime.get_diff(frappe.datetime.get_today(), (dt || "").slice(0, 10));
		if (d <= 0) return "today";
		if (d === 1) return "1 day ago";
		return `${d} days ago`;
	}

	_render_pending(rows) {
		this.$el.find("#ib-aa-pending-count").text(rows.length ? `(${rows.length})` : "");
		if (!rows.length) {
			this.$el.find("#ib-aa-pending").html(ibUI.empty("Nothing waiting on you right now.", "clock"));
			return;
		}
		this.$el.find("#ib-aa-pending").html(ibUI.table({
			head: ["Sales Order", "Customer", "Sales Person", "Advance", "Status", "Decide"],
			rows: rows.map((r) => [
				`<a data-so="${ibUI.esc(r.name)}" href="/app/sales-order/${encodeURIComponent(r.name)}">${ibUI.esc(r.name)}</a>`,
				ibUI.esc(r.customer_name || ""),
				ibUI.esc(r.sales_person_name || "—"),
				`<span class="ib-aa-amount">${this._fmt(r.advance_paid, r.currency)}</span>`,
				`${ibUI.pill("Pending", "warn")}<br><span class="ib-aa-age">${this._days_ago(r.creation)}</span>`,
				`<span style="white-space:nowrap">
					${ibUI.btn("Approve", { variant: "primary", icon: "check-circle", attrs: `data-so="${ibUI.esc(r.name)}" class="ib-aa-approve"` })}
					${ibUI.btn("Reject", { icon: "minus", attrs: `data-so="${ibUI.esc(r.name)}" class="ib-aa-reject ib-aa-btn-danger"` })}
				</span>`,
			]),
		}));

		this.$el.find(".ib-aa-approve").on("click", (e) => this._decide($(e.currentTarget).data("so"), "Approved"));
		this.$el.find(".ib-aa-reject").on("click", (e) => this._decide($(e.currentTarget).data("so"), "Rejected"));
	}

	_fmt(v, ccy) {
		return "₹" + Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 }) + (ccy && ccy !== "INR" ? ` ${ccy}` : "");
	}

	_decide(sales_order, status) {
		frappe.prompt(
			[{ fieldname: "remarks", label: __("Remarks"), fieldtype: "Small Text" }],
			(values) => {
				frappe.call({
					method: "instabiz.overrides.advance_approval.set_advance_approval",
					args: { sales_order, status, remarks: values.remarks },
					callback: () => {
						frappe.show_alert({ message: `${sales_order} ${status.toLowerCase()}`, indicator: status === "Approved" ? "green" : "orange" });
						this.refresh();
					},
				});
			},
			__(status === "Approved" ? "Approve Advance Payment" : "Reject Advance Payment"),
			__(status)
		);
	}

	_render_history(rows) {
		if (!rows.length) {
			this.$el.find("#ib-aa-history").html(ibUI.empty("No decisions yet.", "activity"));
			return;
		}
		this.$el.find("#ib-aa-history").html(ibUI.table({
			head: ["Sales Order", "Customer", "Sales Person", "Advance", "Decision", "Remarks", "When"],
			rows: rows.map((r) => [
				`<a href="/app/sales-order/${encodeURIComponent(r.name)}">${ibUI.esc(r.name)}</a>`,
				ibUI.esc(r.customer_name || ""),
				ibUI.esc(r.sales_person_name || "—"),
				`<span class="ib-aa-amount">${this._fmt(r.advance_paid, r.currency)}</span>`,
				ibUI.pill(r.status, r.status === "Approved" ? "ok" : "danger"),
				`<span style="color:var(--text-muted)">${ibUI.esc(r.remarks || "—")}</span>`,
				`<span class="ib-aa-age">${frappe.datetime.str_to_user(r.modified)}</span>`,
			]),
		}));
	}
}
