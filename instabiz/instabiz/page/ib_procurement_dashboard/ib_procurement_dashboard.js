frappe.pages["ib-procurement-dashboard"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({ parent: wrapper, title: "Procurement", single_column: true });
	wrapper._ib_proc = new IBProcurementDashboard(wrapper.page);
};

frappe.pages["ib-procurement-dashboard"].on_page_show = function (wrapper) {
	if (!wrapper._ib_proc) return;
	wrapper._ib_proc.refresh();
	if (!wrapper._ib_proc._auto_refresh) {
		wrapper._ib_proc._auto_refresh = setInterval(() => wrapper._ib_proc.refresh(), 5 * 60 * 1000);
	}
};

frappe.pages["ib-procurement-dashboard"].on_page_hide = function (wrapper) {
	if (wrapper._ib_proc && wrapper._ib_proc._auto_refresh) {
		clearInterval(wrapper._ib_proc._auto_refresh);
		wrapper._ib_proc._auto_refresh = null;
	}
};

// Rebuilt on the IB Design System (window.ibUI / .ib-ui-* components), 2026-09-21.
class IBProcurementDashboard {
	constructor(page) {
		this.page = page;
		this._chart = null;
		this.$el = ibUI.mount(page);
		this._inject_styles();
		this._build_layout();
		this._build_controls();
		// refresh + timer started by on_page_show to avoid double call on first load
	}

	// Vendor/Item bar-lists are relative-magnitude bars, not status
	// indicators — kept as plain neutral progress bars (own fixed hue per
	// panel) rather than ibUI.bar()'s ok/warn/danger thresholds, which
	// would misrepresent "2nd biggest vendor" as a warning.
	_inject_styles() {
		if (document.getElementById("ib-proc-css")) return;
		const s = document.createElement("style");
		s.id = "ib-proc-css";
		s.textContent = `
.ib-proc-bar-row { display:flex; align-items:center; gap:8px; margin-bottom:8px; font-size:12px; }
.ib-proc-bar-row .lbl { width:130px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; color:var(--text-color); }
.ib-proc-bar-track { flex:1; background:var(--control-bg); border-radius:3px; height:7px; }
.ib-proc-bar-fill { height:7px; border-radius:3px; transition:width .4s; }
.ib-proc-bar-amt { min-width:80px; text-align:right; color:var(--text-muted); }
`;
		document.head.appendChild(s);
	}

	_build_layout() {
		this.$el.html(`
			${ibUI.toolbar([
				ibUI.btn("Purchase Orders", { variant: "ghost", attrs: 'id="ib-proc-btn-po"' }),
				ibUI.btn("Purchase Invoices", { variant: "ghost", attrs: 'id="ib-proc-btn-pi"' }),
				ibUI.btn("Receipts (GRN)", { variant: "ghost", attrs: 'id="ib-proc-btn-grn"' }),
				ibUI.btn("Refresh", { variant: "ghost", icon: "refresh-cw", attrs: 'id="ib-proc-refresh" style="margin-left:auto"' }),
			])}
			<div id="ib-proc-kpis"></div>
			<div class="ib-ui-grid ib-ui-grid--2" style="margin-top:var(--ib-space-3)">
				${ibUI.card({ kind: "TREND", title: "Spend Trend — 6 Months", body: `<div style="height:175px" id="ib-proc-chart"></div>` })}
				${ibUI.card({ kind: "VENDORS", title: "Vendor Spend MTD", body: `<div id="ib-proc-vendors"></div>` })}
				${ibUI.card({ kind: "ITEMS", title: "Top Purchased Items MTD", body: `<div id="ib-proc-items"></div>` })}
				${ibUI.card({ kind: "OPEN", title: "Open Purchase Orders", body: `<div id="ib-proc-po"></div>` })}
			</div>
		`);

		this.$el.find("#ib-proc-btn-po").on("click", () => { frappe.route_options = { docstatus: 1 }; frappe.set_route("List", "Purchase Order"); });
		this.$el.find("#ib-proc-btn-pi").on("click", () => frappe.set_route("List", "Purchase Invoice"));
		this.$el.find("#ib-proc-btn-grn").on("click", () => frappe.set_route("List", "Purchase Receipt"));
		this.$el.find("#ib-proc-refresh").on("click", () => this.refresh());
	}

	refresh() {
		const opts = ib_guarded_call(this, {
			method: "instabiz.instabiz.page.ib_procurement_dashboard.ib_procurement_dashboard.get_procurement_data",
			callback: (r) => { if (r.message) this._render(r.message); },
		});
		if (opts) {
			this.$el.find("#ib-proc-kpis").html(`<div class="ib-ui-stat-grid">${ibUI.skeleton(5)}</div>`);
			frappe.call(opts);
		}
	}

	_render(d) {
		this._render_kpis(d);
		this._render_chart(d.spend_trend);
		this._render_vendors(d.by_vendor);
		this._render_items(d.top_items);
		this._render_po(d.open_po_list);
	}

	// ibUI.stat()'s `sub` field is HTML-escaped internally (plain text only,
	// see ib_main_dashboard.js's own sub: usages) — ibUI.money()'s <span>
	// markup can't go there, it renders as literal escaped tags instead of
	// formatted currency. Plain-text formatter for KPI sub-lines only.
	_money_text(v) {
		return "₹" + Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 });
	}

	_delta_text(delta) {
		if (!delta) return "flat vs last month";
		return `${delta > 0 ? "▲" : "▼"} ${Math.abs(Math.round(delta))}% vs last month`;
	}

	_render_kpis(d) {
		const delta = d.spend_delta;
		this._kpis = [
			{ v: d.open_po_count, l: "Open POs", sub: this._money_text(d.open_po_value),
				go: () => { frappe.route_options = { docstatus: 1 }; frappe.set_route("List", "Purchase Order"); } },
			{ v: d.pending_grn, l: "Pending GRN", sub: "orders to receive",
				go: () => { frappe.route_options = { docstatus: 1, status: ["in", ["To Receive and Bill", "To Receive"]] }; frappe.set_route("List", "Purchase Order"); } },
			{ v: ibUI.money(d.spend_mtd, { compact: true }), l: "Spend MTD", sub: this._delta_text(delta),
				go: () => { frappe.route_options = { docstatus: 1 }; frappe.set_route("List", d.spend_doctype); } },
			{ v: ibUI.money(d.overdue_ap, { compact: true }), l: "Overdue AP", sub: "past due date",
				go: () => { frappe.route_options = { docstatus: 1, outstanding_amount: [">", 0] }; frappe.set_route("List", "Purchase Invoice"); } },
			{ v: d.pending_pi, l: "Draft Bills", sub: "not submitted",
				go: () => { frappe.route_options = { docstatus: 0 }; frappe.set_route("List", "Purchase Invoice"); } },
		];
		this.$el.find("#ib-proc-kpis").html(
			`<div class="ib-ui-stat-grid">${this._kpis
				.map((k, i) => ibUI.stat({ v: k.v, l: k.l, sub: k.sub, route: `#kpi-${i}` }))
				.join("")}</div>`
		).find(".ib-ui-stat--link").on("click", (e) => {
			e.stopPropagation();
			const i = parseInt($(e.currentTarget).data("route").replace("#kpi-", ""), 10);
			this._kpis[i].go();
		});
	}

	_render_chart(trend) {
		const el = this.$el.find("#ib-proc-chart")[0];
		if (!el || !trend || !trend.length) return;
		if (this._chart) { this._chart.destroy && this._chart.destroy(); this._chart = null; $(el).empty(); }
		this._chart = new frappe.Chart(el, {
			type: "line",
			height: 170,
			colors: ["#d97757"],
			data: {
				labels: trend.map((r) => r.label),
				datasets: [{ name: "Spend", values: trend.map((r) => Number(r.amount || 0)) }],
			},
			lineOptions: { regionFill: 1, spline: 1 },
			axisOptions: { xIsSeries: true },
			tooltipOptions: { formatTooltipY: (v) => ibUI.esc("₹" + Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 })) },
		});
	}

	_bar_list(rows, color) {
		if (!rows || !rows.length) return `<p class="ib-ui-hint">No data</p>`;
		const max = Math.max(...rows.map((v) => Number(v.amount)));
		return rows.map((v) => `
			<div class="ib-proc-bar-row">
				<div class="lbl" title="${ibUI.esc(v.label)}">${ibUI.esc(v.label)}</div>
				<div class="ib-proc-bar-track"><div class="ib-proc-bar-fill" style="width:${max ? Math.round(Number(v.amount) / max * 100) : 0}%;background:${color}"></div></div>
				<div class="ib-proc-bar-amt">${ibUI.money(v.amount)}</div>
			</div>`).join("");
	}

	_render_vendors(vendors) {
		this.$el.find("#ib-proc-vendors").html(this._bar_list(vendors, "var(--ib-primary)"));
	}

	_render_items(items) {
		this.$el.find("#ib-proc-items").html(this._bar_list(items, "#8b5cf6"));
	}

	_render_po(rows) {
		const $wrap = this.$el.find("#ib-proc-po");
		if (!rows || !rows.length) {
			$wrap.html(ibUI.empty("No open POs", "package"));
			return;
		}
		$wrap.html(ibUI.table({
			head: ["PO", "Vendor", "Schedule", "Status", "Value"],
			rows: rows.map((r) => {
				const overdue = r.days_overdue > 0;
				const variant = r.days_overdue > 14 ? "danger" : r.days_overdue > 0 ? "warn" : "ok";
				return [
					`<a data-name="${ibUI.esc(r.name)}" style="color:var(--ib-primary)">${ibUI.esc(r.name)}</a>`,
					ibUI.esc(r.supplier_name || r.supplier || ""),
					(r.schedule_date ? frappe.datetime.str_to_user(r.schedule_date) : "—") +
						(overdue ? ` ${ibUI.pill("+" + r.days_overdue + "d", variant)}` : ""),
					ibUI.pill(r.status, r.status === "To Receive" ? "warn" : "ok"),
					`<span class="num" style="font-weight:600">${ibUI.money(r.grand_total)}</span>`,
				];
			}),
		}));
		$wrap.find("tbody tr").each((i, tr) => {
			$(tr).css("cursor", "pointer").on("click", () => frappe.set_route("Form", "Purchase Order", rows[i].name));
		});
	}
}
