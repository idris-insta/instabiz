frappe.pages["ib-main-dashboard"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({ parent: wrapper, title: "Dashboard", single_column: true });
	wrapper._ib_dash = new IBMainDashboard(wrapper);
};

frappe.pages["ib-main-dashboard"].on_page_show = function (wrapper) {
	if (!wrapper._ib_dash) return;
	wrapper._ib_dash.refresh();
	if (!wrapper._ib_dash._timer) {
		wrapper._ib_dash._timer = setInterval(() => wrapper._ib_dash.refresh(), 5 * 60 * 1000);
	}
};

frappe.pages["ib-main-dashboard"].on_page_hide = function (wrapper) {
	if (wrapper._ib_dash) {
		clearInterval(wrapper._ib_dash._timer);
		wrapper._ib_dash._timer = null;
	}
};

// ─────────────────────────────────────────────────────────────────────────────
// Rebuilt on the IB Design System (window.ibUI + .ib-ui-* components), 2026-09-11.
// Backend get_dashboard_data() unchanged.

class IBMainDashboard {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.page = wrapper.page;
		this._chart = null;
		this._data = null;
		this._tab = "revenue";
		this._fetching = false;

		this.$el = ibUI.mount(this.page);
		ibUI.wireRoutes(this.$el);
		this.page.add_button(__("Business Pulse"), () => frappe.set_route("ib-business-pulse"));
		this.page.add_button(__("Analytics Hub"), () => frappe.set_route("ib-analytics-hub"));
		this._skeleton();
	}

	_skeleton() {
		this.$el.html(`<div class="ib-ui-stat-grid">${ibUI.skeleton(4)}</div>${ibUI.skeleton(4)}`);
	}

	refresh() {
		const opts = ib_guarded_call(this, {
			method: "instabiz.instabiz.page.ib_main_dashboard.ib_main_dashboard.get_dashboard_data",
			callback: (r) => {
				if (r.message) { this._data = r.message; this._render(); }
			},
			error: () => this.$ts && this.$ts.text("Error — click Refresh"),
		});
		if (opts) frappe.call(opts);
	}

	_render() {
		const d = this._data;
		this.$el.html(`
			<div class="ib-ui-toolbar" style="justify-content:flex-end">
				${ibUI.btn("Refresh", { variant: "ghost", icon: "refresh-cw", attrs: 'id="ib-md-rf"' })}
				<span id="ib-md-ts">${ibUI.refreshTime()}</span>
			</div>
			<div id="ib-md-kpis"></div>
			<div class="ib-ui-grid ib-ui-grid--2" style="grid-template-columns:2fr 1fr;margin-top:var(--ib-space-3)">
				${ibUI.card({ kind: "TREND", title: "Revenue / Top Customers", body:
					`<div id="ib-md-tabs"></div><div id="ib-md-chart" style="height:200px;margin-top:8px"></div>` })}
				${ibUI.card({ kind: "QUICK", title: "Quick Actions", body:
					`<div class="ib-ui-grid ib-ui-grid--2" style="gap:8px">
						${ibUI.btn("New Quotation", { icon: "file-text", attrs: 'data-new="Quotation"' })}
						${ibUI.btn("New Invoice", { icon: "file-text", attrs: 'data-new="Sales Invoice"' })}
						${ibUI.btn("New Delivery Note", { icon: "truck", attrs: 'data-new="Delivery Note"' })}
						${ibUI.btn("Customer Board", { icon: "users", attrs: 'data-route="ib-customer-board"' })}
						${ibUI.btn("Production", { icon: "factory", attrs: 'data-route="ib-production-dashboard"' })}
						${ibUI.btn("Business Pulse", { icon: "trending-up", attrs: 'data-route="ib-business-pulse"' })}
					</div>` })}
			</div>
			${ibUI.section("Recent Invoices", `<div id="ib-md-recent"></div>`)}
		`);
		this.$ts = this.$el.find("#ib-md-ts");
		this.$el.find("#ib-md-rf").on("click", () => this.refresh());
		this.$el.find("[data-new]").on("click", (e) => frappe.new_doc($(e.currentTarget).data("new")));
		ibUI.wireRoutes(this.$el);

		this._renderKpis(d);
		this._renderTabs();
		this._renderChart();
		this._renderRecent(d.recent_si || [], d.sales_dt);
	}

	_renderKpis(d) {
		const today = frappe.datetime.get_today();
		const ms = today.slice(0, 7) + "-01";
		this._kpis = [
			{
				v: ibUI.money(d.rev_mtd), l: "Revenue MTD", sub: ib_delta_text(d.rev_delta),
				go: () => { frappe.route_options = { docstatus: 1, [d.sales_date_field]: ["between", [ms, today]] };
					frappe.set_route("List", d.sales_dt); },
			},
			{
				v: ibUI.money(d.ar), l: "Outstanding AR", sub: `${d.open_so} open orders`,
				go: () => { frappe.route_options = { docstatus: 1, outstanding_amount: [">", 0] };
					frappe.set_route("List", d.sales_dt); },
			},
			{
				v: d.quotes, l: "Open Quotations", sub: `${d.pending_dn} pending DC`,
				go: () => { frappe.route_options = { docstatus: 1, status: ["not in", ["Ordered", "Lost", "Cancelled", "Expired"]] };
					frappe.set_route("List", "Quotation"); },
			},
			{
				v: d.low_stock, l: "Low / Zero Stock", sub: "SKUs need restock",
				go: () => frappe.set_route("ib-stock-dashboard"),
			},
		];
		this.$el.find("#ib-md-kpis").html(
			`<div class="ib-ui-stat-grid">${this._kpis
				.map((k, i) => ibUI.stat({ v: k.v, l: k.l, sub: k.sub, route: `#kpi-${i}` }))
				.join("")}</div>`,
		).find(".ib-ui-stat--link").on("click", (e) => {
			// KPI cards use data-route="#kpi-N" only to get ibUI.stat()'s
			// clickable styling — it's not a real route. Without stopping
			// propagation here, the click also bubbles to ibUI.wireRoutes'
			// delegated [data-route] listener (bound on this.$el, see
			// render() above), which calls frappe.set_route("#kpi-N")
			// literally and throws "Resource not found" right after the
			// correct navigation below — same bug on all 4 cards, since
			// they all share this pattern.
			e.stopPropagation();
			const i = parseInt($(e.currentTarget).data("route").replace("#kpi-", ""), 10);
			this._kpis[i].go();
		});
	}

	_renderTabs() {
		const t = ibUI.tabs(
			[{ id: "revenue", label: "Revenue" }, { id: "customers", label: "Top Customers" }],
			this._tab,
			(id) => { this._tab = id; this._renderChart(); },
		);
		this.$el.find("#ib-md-tabs").empty().append(t.el);
	}

	_renderChart() {
		const d = this._data, $c = this.$el.find("#ib-md-chart")[0];
		if (!$c) return;
		if (this._chart && this._chart.destroy) this._chart.destroy();
		this._chart = null;
		$($c).empty();

		if (this._tab === "revenue") {
			const trend = d.trend || [];
			if (!trend.length) return $($c).html(ibUI.empty("No revenue data", "trending-up"));
			this._chart = new frappe.Chart($c, {
				type: "line", height: 190, colors: ["#d97757"],
				data: { labels: trend.map((r) => r.label),
					datasets: [{ name: "Revenue", values: trend.map((r) => parseFloat(r.amount || 0)) }] },
				lineOptions: { regionFill: 1, spline: 1 },
				tooltipOptions: { formatTooltipY: (v) => frappe.format(v, { fieldtype: "Currency" }) },
				axisOptions: { xIsSeries: 1 },
			});
		} else {
			const cs = d.top_customers || [];
			if (!cs.length) return $($c).html(ibUI.empty("No customer data", "users"));
			const max = Math.max(...cs.map((c) => parseFloat(c.total || 0))) || 1;
			$($c).html(cs.map((c) => `
				<div class="ib-ui-row" style="padding:5px 0">
					<span style="width:130px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
						class="ib-ui-hint" title="${ibUI.esc(c.customer_name)}">${ibUI.esc(c.customer_name)}</span>
					${ibUI.bar(parseFloat(c.total || 0) / max * 100, { showLabel: false })}
					<span style="width:96px;text-align:right;font-weight:600">${ibUI.money(c.total)}</span>
				</div>`).join(""));
		}
	}

	_renderRecent(rows, doctype) {
		doctype = doctype || "Sales Invoice";
		const $el = this.$el.find("#ib-md-recent");
		if (!rows.length) return $el.html(ibUI.empty("No recent invoices", "file-text"));
		const badge = (si) => {
			if (si.outstanding_amount <= 0) return ibUI.pill("Paid", "ok");
			if (si.due_date && frappe.datetime.get_diff(frappe.datetime.get_today(), si.due_date) > 0)
				return ibUI.pill("Overdue", "danger");
			return ibUI.pill("Unpaid", "warn");
		};
		$el.html(ibUI.table({
			head: ["Invoice", "Customer", "Date", "Amount", "Status"],
			rows: rows.map((si) => [
				`<a data-name="${ibUI.esc(si.name)}" style="color:var(--ib-primary);cursor:pointer">${ibUI.esc(si.name)}</a>`,
				ibUI.esc(si.customer_name),
				frappe.datetime.str_to_user(si.posting_date) || si.posting_date,
				`<span style="font-weight:600">${ibUI.money(si.grand_total)}</span>`,
				badge(si),
			]),
		}));
		$el.find("a[data-name]").on("click", function () {
			frappe.set_route("Form", doctype, $(this).data("name"));
		});
	}
}

// small delta phrase for the KPI sub-line
function ib_delta_text(v) {
	const n = parseFloat(v || 0);
	if (!n) return "flat vs last month";
	return `${n > 0 ? "▲" : "▼"} ${Math.abs(Math.round(n))}% vs last month`;
}
