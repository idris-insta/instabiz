frappe.pages["ib-main-dashboard"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({ parent: wrapper, title: __("Dashboard"), single_column: true });
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
// Built on the shared dashboard kit — window.ibUI (kpi / chartCard / table) and
// window.ibDash (theme-aware charts, filter bar, card personalisation), so the
// theme, the chart styling and the filters match every other IB dashboard.

const IB_MD_CARDS = [
	{ id: "kpis", label: __("Headline numbers"), locked: 1 },
	{ id: "trend", label: __("Sales trend") },
	{ id: "mix", label: __("Location split") },
	{ id: "customers", label: __("Top customers") },
	{ id: "people", label: __("Sales people") },
	{ id: "recent", label: __("Recent orders") },
	{ id: "actions", label: __("Quick actions") },
];

class IBMainDashboard {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.page = wrapper.page;
		this._data = null;
		this._series = "amount";
		this._fetching = false;

		this.$el = ibUI.mount(this.page);
		ibUI.wireRoutes(this.$el);

		this.page.set_secondary_action(__("Refresh"), () => this.refresh(), "refresh");
		this.page.add_menu_item(__("Business Pulse"), () => frappe.set_route("ib-business-pulse"));
		this.page.add_menu_item(__("Analytics Hub"), () => frappe.set_route("ib-analytics-hub"));

		this.filters = ibDash.filters(this.page, {
			key: "main-dash",
			fields: [ibDash.F.period(), ibDash.F.location(), ibDash.F.salesPerson()],
			onChange: () => this.refresh(),
		});
		this.cards = ibDash.personalise(this.page, {
			key: "main-dash",
			cards: IB_MD_CARDS,
			container: () => this.$el.find("[data-cards]"),
		});

		this._shell();
		this._skeleton();
	}

	// One stable shell — refreshes fill the card bodies instead of rebuilding
	// the page, so the filter bar, scroll position and card order survive.
	_shell() {
		this.$el.html(
			`<div class="ib-ui-filter-note" id="md-note"></div>
			<div class="ib-dash-cards" data-cards>
				<div data-card="kpis" class="ib-dash-c--12" id="md-kpis"></div>
				<div data-card="trend" class="ib-dash-c--8">
					${ibUI.chartCard({ id: "md-trend", kind: "TREND", title: __("Sales trend"), height: 230,
						right: `<span class="ib-ui-tabs ib-ui-tabs--mini" id="md-series">
							<button class="ib-ui-tab is-active" data-tab="amount">${__("Value")}</button>
							<button class="ib-ui-tab" data-tab="cnt">${__("Count")}</button></span>` })}
				</div>
				<div data-card="mix" class="ib-dash-c--4">
					${ibUI.chartCard({ id: "md-mix", kind: "SPLIT", title: __("By location"), height: 230 })}
				</div>
				<div data-card="customers" class="ib-dash-c--6">
					<div class="ib-ui-card"><div class="ib-ui-card-h"><span class="k">TOP</span>
						<span class="t">${__("Customers")}</span></div>
						<div id="md-customers"></div></div>
				</div>
				<div data-card="people" class="ib-dash-c--6">
					<div class="ib-ui-card"><div class="ib-ui-card-h"><span class="k">TEAM</span>
						<span class="t">${__("Sales people")}</span></div>
						<div id="md-people"></div></div>
				</div>
				<div data-card="recent" class="ib-dash-c--12">
					<div class="ib-ui-card"><div class="ib-ui-card-h"><span class="k">LATEST</span>
						<span class="t" id="md-recent-title">${__("Recent orders")}</span></div>
						<div id="md-recent"></div></div>
				</div>
				<div data-card="actions" class="ib-dash-c--12">
					<div class="ib-ui-card"><div class="ib-ui-card-h"><span class="k">GO TO</span>
						<span class="t">${__("Quick actions")}</span></div>
						<div class="ib-dash-actions">
							${ibUI.btn(__("New Quotation"), { icon: "file-text", attrs: 'data-new="Quotation"' })}
							${ibUI.btn(__("New Sales Order"), { icon: "shopping-cart", attrs: 'data-new="Sales Order"' })}
							${ibUI.btn(__("New Delivery Note"), { icon: "truck", attrs: 'data-new="Delivery Note"' })}
							${ibUI.btn(__("Customer Board"), { icon: "users", attrs: 'data-route="ib-customer-board"' })}
							${ibUI.btn(__("Production"), { icon: "factory", attrs: 'data-route="ib-production-dashboard"' })}
							${ibUI.btn(__("Live Stock"), { icon: "package", attrs: 'data-route="ib-stock-dashboard"' })}
							${ibUI.btn(__("Collections"), { icon: "wallet", attrs: 'data-route="ib-collections-dashboard"' })}
							${ibUI.btn(__("Analytics Hub"), { icon: "trending-up", attrs: 'data-route="ib-analytics-hub"' })}
						</div></div>
				</div>
			</div>`,
		);
		this.$el.find("[data-new]").on("click", (e) => frappe.new_doc($(e.currentTarget).data("new")));
		this.$el.find("#md-series").on("click", ".ib-ui-tab", (e) => {
			const $t = $(e.currentTarget);
			this.$el.find("#md-series .ib-ui-tab").removeClass("is-active");
			$t.addClass("is-active");
			this._series = $t.data("tab");
			this._renderTrend();
		});
		ibUI.wireRoutes(this.$el);
		this.cards.apply();
	}

	_skeleton() {
		this.$el.find("#md-kpis").html(
			`<div class="ib-ui-kpi-grid">${('<div class="ib-ui-kpi"><div class="ib-ui-skeleton"></div>' +
				'<div class="ib-ui-skeleton"></div></div>').repeat(6)}</div>`,
		);
	}

	refresh() {
		const f = this.filters.get();
		const opts = ib_guarded_call(this, {
			method: "instabiz.instabiz.page.ib_main_dashboard.ib_main_dashboard.get_dashboard_data",
			args: { from_date: f.from_date, to_date: f.to_date, location: f.location, sales_person: f.sales_person },
			callback: (r) => {
				if (!r.message) return;
				this._data = r.message;
				this._render();
			},
			error: () => this.$el.find("#md-note").html(`<span class="ib-ui-pill ib-ui-pill--danger">${__("Could not load")}</span>`),
		});
		if (opts) frappe.call(opts);
	}

	_render() {
		const d = this._data, m = d && d.meta;
		if (!m) {
			// An older server answering the new page — say so instead of leaving
			// the skeletons spinning forever.
			this.$el.find("#md-kpis").html(ibUI.empty(
				__("This dashboard needs the latest server code — ask an administrator to restart the app."),
				"alert-triangle"));
			return;
		}
		this.$el.find("#md-note").html(
			`${ibUI.icon("calendar", 13)}<b>${ibUI.esc(this.filters.label() || __("This Month"))}</b>` +
			`<span>·</span><span>${__("compared with")} ${frappe.datetime.str_to_user(m.prev_from)} – ${frappe.datetime.str_to_user(m.prev_to)}</span>` +
			`${m.locked ? `<span class="ib-ui-pill ib-ui-pill--info">${__("Your own figures")}</span>` : ""}` +
			`<span style="margin-left:auto">${ibUI.refreshTime()}</span>`,
		);
		this.$el.find("#md-recent-title").text(m.sales_dt === "Sales Order" ? __("Recent orders") : __("Recent invoices"));
		this._renderKpis();
		this._renderTrend();
		this._renderMix();
		this._renderCustomers();
		this._renderPeople();
		this._renderRecent();
		this.cards.apply();
	}

	_renderKpis() {
		const d = this._data, m = d.meta;
		const kpis = [
			{
				key: "revenue", l: m.dev_mode ? __("Order value") : __("Revenue"), icon: "trending-up",
				v: ibUI.moneyShort(d.revenue), title: ibUI.moneyFull(d.revenue),
				delta: d.rev_delta, deltaSuffix: __("vs prev"), spark: d.spark, tone: "brand",
				sub: `${d.orders} ${__("orders")}`,
			},
			{
				key: "ar", l: __("Outstanding"), icon: "wallet", tone: d.ar_overdue > 0 ? "warn" : "ok",
				v: ibUI.moneyShort(d.ar), title: ibUI.moneyFull(d.ar),
				sub: d.ar_overdue ? `${ibUI.shortNum(d.ar_overdue)} ${__("over 30 days")}` : __("nothing past 30 days"),
			},
			{
				key: "collections", l: __("Collected"), icon: "check-circle", tone: "ok",
				v: ibUI.moneyShort(d.collections), title: ibUI.moneyFull(d.collections),
				sub: m.collections_all_locations ? __("all locations") : __("in this period"),
			},
			{
				key: "open_so", l: __("Open orders"), icon: "shopping-cart", tone: "info",
				v: d.open_so, sub: `${ibUI.shortNum(d.open_so_value)} ${__("to deliver")}`,
			},
			{
				key: "quotes", l: __("Open quotations"), icon: "file-text", tone: "info",
				v: d.quotes, sub: `${ibUI.shortNum(d.quote_value)} ${__("in play")}`,
			},
			{
				key: "dispatch", l: __("Dispatched"), icon: "truck", tone: "brand",
				v: d.dispatch_count, sub: `${d.pending_dn} ${__("draft challans")}`,
			},
			{
				key: "low_stock", l: __("Low / zero stock"), icon: "alert-triangle",
				tone: d.low_stock ? "danger" : "ok", v: d.low_stock, sub: __("SKUs at reorder level"),
			},
		];
		this._kpis = kpis;
		this.$el.find("#md-kpis").html(ibUI.kpiGrid(kpis)).find("[data-kpi]").on("click", (e) => {
			e.stopPropagation();
			this._drill($(e.currentTarget).attr("data-kpi"));
		});
	}

	_drill(key) {
		const d = this._data, m = d.meta, range = [m.from_date, m.to_date];
		const base = {};
		if (m.location) base.custom_location = m.location;
		if (m.sales_person) base.custom_sales_person_user = m.sales_person;
		const go = (dt, filters) => {
			frappe.route_options = Object.assign({}, base, filters);
			frappe.set_route("List", dt);
		};
		switch (key) {
			case "revenue":
				return go(m.sales_dt, { docstatus: 1, [m.date_field]: ["between", range] });
			case "ar":
				return frappe.set_route("query-report", "IB AR Aging");
			case "collections":
				return frappe.set_route("query-report", "IB Payment Register");
			case "open_so":
				return go("Sales Order", { docstatus: 1, status: ["not in", ["Completed", "Cancelled", "Closed", "Confirmed"]] });
			case "quotes":
				return go("Quotation", { docstatus: 1, status: ["not in", ["Ordered", "Lost", "Cancelled", "Expired", "Confirmed"]] });
			case "dispatch":
				return go("Delivery Note", { docstatus: 1, posting_date: ["between", range] });
			case "low_stock":
				return frappe.set_route("ib-stock-dashboard");
		}
	}

	_renderTrend() {
		if (!this._data) return;
		const t = this._data.trend || [], money = this._series === "amount";
		ibDash.chart(this.$el.find("#md-trend"), {
			type: money ? "line" : "bar",
			labels: t.map((r) => r.label),
			datasets: [{ name: money ? __("Value") : __("Orders"), values: t.map((r) => parseFloat(r[this._series] || 0)) }],
			height: 230, currency: money, dp: 0,
			empty: __("No orders in this period"), emptyIcon: "trending-up",
		});
	}

	_renderMix() {
		const rows = (this._data.by_location || []).filter((r) => parseFloat(r.total) > 0);
		ibDash.chart(this.$el.find("#md-mix"), {
			type: "donut", height: 230,
			labels: rows.map((r) => r.label),
			datasets: [{ name: __("Value"), values: rows.map((r) => parseFloat(r.total || 0)) }],
			xIsSeries: 0, empty: __("Nothing to split"), emptyIcon: "layers",
		});
	}

	_renderCustomers() {
		const cs = this._data.top_customers || [], $el = this.$el.find("#md-customers");
		if (!cs.length) return $el.html(ibUI.empty(__("No customer activity"), "users"));
		const max = Math.max(...cs.map((c) => parseFloat(c.total || 0))) || 1;
		$el.html(
			`<div class="ib-dash-rank">${cs
				.map(
					(c) => `<div class="row" data-route="app/customer/${encodeURIComponent(c.customer || "")}">
						<span class="nm" title="${ibUI.esc(c.customer_name)}">${ibUI.esc(c.customer_name)}</span>
						${ibUI.bar((parseFloat(c.total || 0) / max) * 100, { showLabel: false })}
						<span class="amt">${ibUI.moneyShort(c.total)}</span></div>`,
				)
				.join("")}</div>`,
		);
		ibUI.wireRoutes($el);
	}

	_renderPeople() {
		const rows = this._data.by_person || [], $el = this.$el.find("#md-people");
		if (!rows.length) {
			return $el.html(ibUI.empty(this._data.meta.locked ? __("Only your own figures are shown") : __("No sales-person data"), "users"));
		}
		const max = Math.max(...rows.map((r) => parseFloat(r.total || 0))) || 1;
		$el.html(
			`<div class="ib-dash-rank">${rows
				.map(
					(r) => `<div class="row">
						<span class="nm" title="${ibUI.esc(r.label)}">${ibUI.esc(r.label)}</span>
						${ibUI.bar((parseFloat(r.total || 0) / max) * 100, { showLabel: false })}
						<span class="amt">${ibUI.moneyShort(r.total)}</span>
						<span class="ib-ui-hint" style="width:52px;text-align:right">${r.cnt} ${__("ord")}</span></div>`,
				)
				.join("")}</div>`,
		);
	}

	_renderRecent() {
		const rows = this._data.recent || [], dt = this._data.meta.sales_dt;
		const $el = this.$el.find("#md-recent");
		if (!rows.length) return $el.html(ibUI.empty(__("Nothing recent"), "file-text"));
		const badge = (r) => {
			if (flt(r.outstanding_amount) <= 0) return ibUI.pill(__("Settled"), "ok");
			if (flt(r.outstanding_amount) < flt(r.grand_total)) return ibUI.pill(__("Part paid"), "warn");
			return ibUI.pill(__("Unpaid"), "muted");
		};
		$el.html(
			ibUI.table({
				head: [__("Document"), __("Customer"), __("Location"), __("Date"), __("Amount"), __("Outstanding"), __("Payment")],
				rows: rows.map((r) => [
					ibUI.link(dt, r.name),
					ibUI.esc(r.customer_name),
					r.custom_location ? ibUI.pill(r.custom_location, "muted") : "",
					frappe.datetime.str_to_user(r.posting_date) || r.posting_date,
					`<span class="ib-ui-num" style="font-weight:600">${ibUI.moneyFull(r.grand_total)}</span>`,
					`<span class="ib-ui-num">${flt(r.outstanding_amount) ? ibUI.moneyFull(r.outstanding_amount) : "—"}</span>`,
					badge(r),
				]),
			}),
		);
	}
}
