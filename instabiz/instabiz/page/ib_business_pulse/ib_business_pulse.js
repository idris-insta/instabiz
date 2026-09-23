frappe.pages["ib-business-pulse"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({
		parent: wrapper,
		title: "Business Pulse",
		single_column: true,
	});
	wrapper._ib_pulse = new IBBusinessPulse(wrapper.page);
};

frappe.pages["ib-business-pulse"].on_page_show = function (wrapper) {
	if (!wrapper._ib_pulse) return;
	wrapper._ib_pulse.refresh();
	wrapper._ib_pulse._start_auto();
};

frappe.pages["ib-business-pulse"].on_page_hide = function (wrapper) {
	if (wrapper._ib_pulse) wrapper._ib_pulse._stop_auto();
};

// ─────────────────────────────────────────────────────────────────────────────
// Each domain card shows real counts/amounts only — no synthetic 0-100 score.
// Every metric routes to the actual filtered record list it was counted from;
// the card footer routes to the domain's own dashboard page.
// Rebuilt on the IB Design System (window.ibUI / .ib-ui-* components), 2026-09-21.

class IBBusinessPulse {
	constructor(page) {
		this.page = page;
		this._data = null;
		this._trend_chart = null;
		this._auto_timer = null;
		this.$el = ibUI.mount(page);
		this._inject_styles();
		this._build_layout();
		this._bind_toolbar();
		// refresh + timer started by on_page_show to avoid double call on first load
	}

	_inject_styles() {
		if (document.getElementById("ib-bp-styles")) return;
		const s = document.createElement("style");
		s.id = "ib-bp-styles";
		s.textContent = `
.ib-bp-domain { padding: 0; overflow: hidden; }
.ib-bp-domain .ib-ui-card-h { padding: var(--ib-space-3) var(--ib-space-4) var(--ib-space-2); margin: 0; }
.ib-bp-metric-row { display: flex; align-items: center; justify-content: space-between;
  padding: 8px var(--ib-space-4); border-top: 1px solid var(--border-color); cursor: pointer; transition: background .12s; }
.ib-bp-metric-row:hover { background: var(--control-bg); }
.ib-bp-metric-lbl { font-size: 11.5px; color: var(--text-muted); }
.ib-bp-metric-val { font-size: 14px; font-weight: 700; color: var(--heading-color); }
.ib-bp-metric-badge { font-size: 10px; font-weight: 600; margin-left: 6px; }
.ib-bp-metric-badge.up { color: var(--ib-ok-fg); }
.ib-bp-metric-badge.down { color: var(--ib-danger-fg); }
.ib-bp-domain-footer { display: block; padding: 7px var(--ib-space-4); font-size: 10.5px; font-weight: 600;
  color: var(--ib-primary); text-align: right; border-top: 1px solid var(--border-color);
  cursor: pointer; text-transform: uppercase; letter-spacing: .04em; }
.ib-bp-domain-footer:hover { text-decoration: underline; }
`;
		document.head.appendChild(s);
	}

	_build_layout() {
		this.$el.html(`
			<div id="ib-bp-ts" class="ib-ui-hint" style="text-align:right;margin-bottom:var(--ib-space-3)">Loading…</div>
			<div class="ib-ui-grid ib-ui-grid--3" id="ib-bp-domains" style="margin-bottom:var(--ib-space-5)"></div>
			${ibUI.section("14-Day Revenue Trend", `<div style="height:180px" id="ib-bp-trend"></div>`)}
		`);
	}

	_bind_toolbar() {
		this.page.add_button(__("Dashboard"), () => frappe.set_route("ib-main-dashboard"));
		this.page.add_button(__("Analytics Hub"), () => frappe.set_route("ib-analytics-hub"));
		this.page.add_inner_button(__("Refresh"), () => this.refresh());
	}

	refresh() {
		this.$el.find("#ib-bp-ts").text("Loading…");
		frappe.call({
			method: "instabiz.instabiz.page.ib_business_pulse.ib_business_pulse.get_pulse_data",
			callback: (r) => {
				if (r.message) {
					this._data = r.message;
					this._render(r.message);
					this.$el.find("#ib-bp-ts").text("Updated " + frappe.datetime.now_time() + " · Auto-refresh every 2 min");
				}
			},
			error: () => this.$el.find("#ib-bp-ts").text("Error loading data"),
		});
	}

	_start_auto() {
		if (this._auto_timer) return;
		this._auto_timer = setInterval(() => this.refresh(), 120000);
	}

	_stop_auto() {
		if (this._auto_timer) { clearInterval(this._auto_timer); this._auto_timer = null; }
	}

	_fmt(v) { return "₹" + Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 }); }

	// KPI-metric version — crore/lakh scale with the exact amount as a
	// hover title, same convention as the other dashboards' KPI cards.
	_fmtC(v) {
		return `<span title="${this._fmt(v)}">${window.ib_fmt_inr_compact ? window.ib_fmt_inr_compact(v) : this._fmt(v)}</span>`;
	}

	_render(d) {
		this._render_domains(d);
		this._render_trend(d.trend_14 || []);
	}

	// Route filters below mirror the same date_field/doctype the backend just
	// aggregated with (billing_mode toggle — Sales Order in dev, Sales Invoice
	// in prod) so a click always lands on the exact rows that were counted.
	_domains(d) {
		const doctype = d.sales_doctype;
		const date_field = d.date_field;
		const between = [d.month_start, d.today];
		const status_filter = d.dev_mode ? { status: ["!=", "Cancelled"] } : { is_return: 0 };

		return [
			{
				key: "Revenue", icon: "wallet", route: "ib-main-dashboard",
				metrics: [
					{
						label: "Revenue MTD", value: this._fmtC(d.rev_mtd),
						badge: d.rev_change_pct == null ? "" :
							`<span class="ib-bp-metric-badge ${d.rev_change_pct >= 0 ? "up" : "down"}">${d.rev_change_pct >= 0 ? "▲" : "▼"} ${Math.abs(d.rev_change_pct)}% vs last mo</span>`,
						route: () => frappe.set_route("List", doctype, Object.assign({ docstatus: 1, [`${date_field},Between`]: between }, status_filter)),
					},
					{ label: "Collection Rate", value: d.collection_rate + "%", route: () => frappe.set_route("query-report", "IB Collections Report") },
					{ label: "Outstanding AR", value: this._fmtC(d.ar), route: () => frappe.set_route("query-report", "IB AR Aging") },
				],
			},
			{
				key: "Sales", icon: "file-text", route: "ib-customer-board",
				metrics: [
					{ label: "Open Leads", value: d.open_leads, route: () => frappe.set_route("List", "Lead", { status: ["not in", ["Converted", "Do Not Contact"]] }) },
					{ label: "Open Quotations", value: d.open_quotes, route: () => frappe.set_route("List", "Quotation", { docstatus: 1, status: ["not in", ["Ordered", "Lost", "Cancelled", "Expired"]] }) },
				],
			},
			{
				key: "Inventory", icon: "package", route: "ib-stock-dashboard",
				metrics: [
					{ label: "Items In Stock", value: d.total_items, route: () => frappe.set_route("ib-stock-dashboard") },
					{ label: "Low / Reorder Stock", value: d.low_stock, route: () => frappe.set_route("ib-stock-dashboard") },
				],
			},
			{
				key: "Procurement", icon: "shopping-cart", route: "ib-procurement-dashboard",
				metrics: [
					{ label: "Open Purchase Orders", value: d.open_po, route: () => frappe.set_route("List", "Purchase Order", { docstatus: 1, status: ["not in", ["Completed", "Cancelled", "Closed"]] }) },
				],
			},
			{
				key: "HR", icon: "users", route: "ib-hrms-dashboard",
				metrics: [
					{ label: "Active Employees", value: d.total_emp, route: () => frappe.set_route("List", "Employee", { status: "Active" }) },
					{ label: "Present Today", value: d.present_today, route: () => frappe.set_route("List", "Attendance", { attendance_date: d.today, status: "Present", docstatus: 1 }) },
				],
			},
			{
				key: "Production", icon: "factory", route: "ib-production-dashboard",
				metrics: [
					{ label: "Active Work Orders", value: d.wo_active, route: () => frappe.set_route("List", "IB Work Order", { status: ["in", ["Pending", "In Progress", "On Hold"]] }) },
					{ label: "Completed This Month", value: d.wo_completed, route: () => frappe.set_route("List", "IB Work Order", { status: "Completed", "completed_at,>=": d.month_start }) },
				],
			},
		];
	}

	_render_domains(d) {
		const domains = this._domains(d);
		const html = domains.map((dom, di) => `
			<div class="ib-ui-card ib-bp-domain">
				<div class="ib-ui-card-h">${ibUI.icon(dom.icon)}<span class="t">${ibUI.esc(dom.key)}</span></div>
				${dom.metrics.map((m, mi) => `
					<div class="ib-bp-metric-row" data-domain="${di}" data-metric="${mi}">
						<span class="ib-bp-metric-lbl">${ibUI.esc(m.label)}</span>
						<span><span class="ib-bp-metric-val">${m.value}</span>${m.badge || ""}</span>
					</div>
				`).join("")}
				<div class="ib-bp-domain-footer" data-route="${ibUI.esc(dom.route)}">Open ${ibUI.esc(dom.key)} Dashboard →</div>
			</div>
		`).join("");

		const $el = this.$el.find("#ib-bp-domains").html(html);
		$el.find(".ib-bp-metric-row").on("click", (e) => {
			const $row = $(e.currentTarget);
			const dom = domains[$row.data("domain")];
			const metric = dom.metrics[$row.data("metric")];
			metric.route();
		});
		$el.find(".ib-bp-domain-footer").on("click", (e) => {
			frappe.set_route($(e.currentTarget).data("route"));
		});
	}

	_render_trend(trend) {
		const $el = this.$el.find("#ib-bp-trend")[0];
		if (!$el) return;
		if (!trend.length) {
			$($el).html(ibUI.empty("No trend data", "trending-up"));
			return;
		}
		if (this._trend_chart) { this._trend_chart.destroy && this._trend_chart.destroy(); this._trend_chart = null; }
		$($el).empty();
		this._trend_chart = new frappe.Chart($el, {
			type: "line",
			data: {
				labels: trend.map((r) => r.label),
				datasets: [{ name: "Revenue", values: trend.map((r) => parseFloat(r.amount || 0)) }],
			},
			colors: ["#d97757"],
			height: 165,
			lineOptions: { regionFill: 1, hideDots: 1, spline: 1 },
			axisOptions: { xIsSeries: 1 },
			tooltipOptions: {
				formatTooltipY: (v) => "₹" + Number(v).toLocaleString("en-IN", { maximumFractionDigits: 0 }),
			},
		});
	}
}
