frappe.pages["ib-finance-dashboard"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({ parent: wrapper, title: "Finance", single_column: true });
	wrapper._ib_fin = new IBFinanceDashboard(wrapper);
};

frappe.pages["ib-finance-dashboard"].on_page_show = function (wrapper) {
	if (!wrapper._ib_fin) return;
	wrapper._ib_fin.refresh();
	if (!wrapper._ib_fin._auto_refresh) {
		wrapper._ib_fin._auto_refresh = setInterval(() => wrapper._ib_fin.refresh(), 5 * 60 * 1000);
	}
};

frappe.pages["ib-finance-dashboard"].on_page_hide = function (wrapper) {
	if (wrapper._ib_fin) {
		clearInterval(wrapper._ib_fin._auto_refresh);
		wrapper._ib_fin._auto_refresh = null;
	}
};

// Shared accent palette — keeps KPI card colors and their matching chart series in sync
const IB_FIN_COLOR_REVENUE  = "#d97757";
const IB_FIN_COLOR_PROFIT   = "#10b981";
const IB_FIN_COLOR_DANGER   = "#ef4444";
const IB_FIN_COLOR_WARNING  = "#f59e0b";
const IB_FIN_COLOR_CASH     = "#3b82f6";
const IB_FIN_COLOR_EXPENSE  = "#8b5cf6";
const IB_FIN_COLOR_YTD      = "#06b6d4";

class IBFinanceDashboard {
	constructor(wrapper) {
		this.page = wrapper.page;
		this.$wrap = $(wrapper).find(".layout-main-section");
		this._pl_chart  = null;
		this._fetching  = false;
		this._inject_styles();
		this._build_layout();
		this._build_controls();
	}

	_build_controls() {
		this.page.set_secondary_action(__("Refresh"), () => this.refresh(), "refresh");
		this.page.add_menu_item(__("Sales documents"), () => {
			frappe.route_options = this._ar_route_options();
			frappe.set_route("List", this.sales_dt || "Sales Invoice");
		});
		this.page.add_menu_item(__("Purchase documents"), () => frappe.set_route("List", this.purch_dt || "Purchase Invoice"));
		this.page.add_menu_item(__("Payment Entries"), () => frappe.set_route("List", "Payment Entry"));
		this.filters = ibDash.filters(this.page, {
			key: "finance-dash",
			fields: [ibDash.F.period(), ibDash.F.location()],
			onChange: () => this.refresh(),
		});
		this.cards = ibDash.personalise(this.page, {
			key: "finance-dash",
			cards: [
				{ id: "kpis", label: __("Headline numbers"), locked: 1 },
				{ id: "pl", label: __("Profit trend") },
				{ id: "cash", label: __("Cash & bank") },
				{ id: "vendors", label: __("Top vendors") },
				{ id: "gst", label: __("GST summary") },
				{ id: "overdue", label: __("Overdue receivables") },
			],
			container: () => this.$wrap.find("[data-cards]"),
		});
		this.cards.apply();
	}

	_inject_styles() {
		if (document.getElementById("ib-fin-css")) return;
		const s = document.createElement("style");
		s.id = "ib-fin-css";
		s.textContent = `
:root { --ib-p:#d97757; --ib-bg:var(--card-bg,#fff); --ib-br:var(--border-color,#e2e8f0); }
.ib-fin-wrap { padding:16px; max-width:1400px; }
.ib-fin-toolbar { display:flex; align-items:center; gap:10px; margin-bottom:18px; flex-wrap:wrap; }
.ib-fin-toolbar h2 { font-size:1.15rem; font-weight:700; color:var(--heading-color); margin:0; flex:1; }
.ib-fin-ts { font-size:11px; color:var(--text-muted); }
.ib-fin-btn { padding:5px 13px; border:1px solid var(--ib-br); border-radius:6px;
  background:var(--ib-bg); color:var(--text-color); cursor:pointer; font-size:12px;
  transition:all .15s; }
.ib-fin-btn:hover { border-color:var(--ib-p); color:var(--ib-p); }
.ib-fin-kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:12px; margin-bottom:20px; }
.ib-fin-kpi { background:var(--ib-bg); border:1px solid var(--ib-br); border-radius:10px;
  padding:16px 18px; position:relative; cursor:pointer; transition:box-shadow .15s,transform .15s; overflow:hidden; }
.ib-fin-kpi:hover { box-shadow:0 4px 18px rgba(0,0,0,.09); transform:translateY(-2px); }
.ib-fin-kpi-bar { position:absolute; left:0; top:0; bottom:0; width:4px; border-radius:10px 0 0 10px; }
.ib-fin-kpi-lbl { font-size:11px; color:var(--text-muted); text-transform:uppercase; letter-spacing:.06em; margin-bottom:6px; }
.ib-fin-kpi-val { font-size:1.5rem; font-weight:700; color:var(--heading-color); line-height:1.1; min-height:1.6rem; }
.ib-fin-kpi-delta { font-size:11px; margin-top:6px; }
.ib-fin-arrow { position:absolute; bottom:8px; right:10px; font-size:10px; opacity:.35; }
.ib-fin-grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:20px; }
@media(max-width:900px) { .ib-fin-grid { grid-template-columns:1fr; } }
.ib-fin-card { background:var(--ib-bg); border:1px solid var(--ib-br); border-radius:10px; padding:18px 20px; }
.ib-fin-card-title { font-size:12px; font-weight:700; color:var(--text-muted); text-transform:uppercase;
  letter-spacing:.06em; margin-bottom:14px; }
.ib-fin-tbl { width:100%; border-collapse:collapse; font-size:12px; }
.ib-fin-tbl th { text-align:left; padding:7px 8px; color:var(--text-muted); font-weight:600;
  font-size:10px; text-transform:uppercase; letter-spacing:.04em;
  border-bottom:2px solid var(--ib-br); background:var(--bg-color); }
.ib-fin-tbl td { padding:8px; border-bottom:1px solid var(--ib-br); vertical-align:middle; }
.ib-fin-tbl tr:last-child td { border-bottom:none; }
.ib-fin-tbl tbody tr { cursor:pointer; }
.ib-fin-tbl tbody tr:hover td { background:var(--control-bg,#f8fafc); }
.ib-fin-badge { display:inline-block; padding:2px 8px; border-radius:99px; font-size:10px; font-weight:600; }
.ib-fin-badge.red   { background:#fee2e2; color:#dc2626; }
.ib-fin-badge.amber { background:#fef3c7; color:#d97706; }
.ib-fin-badge.green { background:#d1fae5; color:#059669; }
.ib-fin-bar-row { display:flex; align-items:center; gap:8px; margin-bottom:10px; font-size:12px; }
.ib-fin-bar-lbl { width:140px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; color:var(--text-color); }
.ib-fin-bar-track { flex:1; background:var(--control-bg,#f1f5f9); border-radius:3px; height:8px; overflow:hidden; }
.ib-fin-bar-fill { height:8px; border-radius:3px; background:var(--ib-p); transition:width .5s; }
.ib-fin-bar-amt { min-width:80px; text-align:right; color:var(--text-muted); }
.ib-fin-chart-wrap { height:180px; }
.ib-fin-gst-row { display:flex; gap:12px; }
.ib-fin-gst-box { flex:1; background:var(--control-bg,#f8fafc); border-radius:8px; padding:12px; text-align:center; }
.ib-fin-gst-v { font-size:1.1rem; font-weight:700; color:var(--heading-color); }
.ib-fin-gst-l { font-size:10px; color:var(--text-muted); margin-top:4px; }
.ib-fin-cash-item { display:flex; align-items:center; justify-content:space-between;
  padding:8px 0; border-bottom:1px solid var(--ib-br); font-size:12px; }
.ib-fin-cash-item:last-child { border-bottom:none; }
.ib-fin-kpi-row-skel { display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:12px; margin-bottom:20px; }
`;
		document.head.appendChild(s);
	}

	_build_layout() {
		this.$wrap.html(`
		<div class="ib-fin-wrap ib-ui-page">
			<div class="ib-ui-filter-note" id="ib-fin-note"><span id="ib-fin-ts"></span></div>
			<div class="ib-dash-cards" data-cards>
				<div data-card="kpis" class="ib-dash-c--12">
					<div id="ib-fin-kpis" class="ib-fin-kpis">${window.ib_skel_kpis ? ib_skel_kpis(6) : ""}</div>
				</div>
				<div data-card="pl" class="ib-dash-c--8">
					<div class="ib-fin-card">
						<div class="ib-fin-card-title">${__("Revenue vs expenses — 6 months")}</div>
						<div class="ib-fin-chart-wrap ib-ui-chart" id="ib-fin-pl-chart"></div>
					</div>
				</div>
				<div data-card="cash" class="ib-dash-c--4">
					<div class="ib-fin-card">
						<div class="ib-fin-card-title">${__("Cash &amp; bank balances")}</div>
						<div id="ib-fin-cash"></div>
					</div>
				</div>
				<div data-card="vendors" class="ib-dash-c--6">
					<div class="ib-fin-card">
						<div class="ib-fin-card-title">${__("Top vendors")}</div>
						<div id="ib-fin-vendors"></div>
					</div>
				</div>
				<div data-card="gst" class="ib-dash-c--6">
					<div class="ib-fin-card">
						<div class="ib-fin-card-title">${__("GST summary")}</div>
						<div id="ib-fin-gst"></div>
					</div>
				</div>
				<div data-card="overdue" class="ib-dash-c--12">
					<div class="ib-fin-card">
						<div class="ib-fin-card-title">${__("Overdue receivables")}</div>
						<table class="ib-fin-tbl">
							<thead><tr>
								<th>${__("Document")}</th><th>${__("Customer")}</th><th>${__("Date")}</th>
								<th>${__("Due")}</th><th>${__("Overdue")}</th><th style="text-align:right">${__("Outstanding")}</th>
							</tr></thead>
							<tbody id="ib-fin-overdue"></tbody>
						</table>
					</div>
				</div>
			</div>
		</div>`);

		this.$wrap.find("#ib-fin-btn-si").on("click", () => {
			// Sales Order (dev billing mode) has no outstanding_amount column —
			// a filter built for Sales Invoice's own field would break the list
			// view. See _ar_route_options() for the shared fix.
			frappe.route_options = this._ar_route_options();
			frappe.set_route("List", this.sales_dt || "Sales Invoice");
		});

	}

	_args() {
		const f = (this.filters && this.filters.get()) || {};
		this.$wrap.find("#ib-fin-note").html(
			`${ibUI.icon("calendar", 13)}<b>${ibUI.esc((this.filters && this.filters.label()) || "")}</b>` +
			`<span style="margin-left:auto" id="ib-fin-ts"></span>`);
		return { from_date: f.from_date, to_date: f.to_date, location: f.location };
	}

	refresh() {
		const opts = ib_guarded_call(this, {
			method: "instabiz.instabiz.page.ib_finance_dashboard.ib_finance_dashboard.get_finance_data",
			args: this._args(),
			callback: (r) => {
				if (r.message) {
					this._render(r.message);
					this.cards && this.cards.apply();
					this.$wrap.find("#ib-fin-ts").text("Updated " + frappe.datetime.now_time());
				}
			},
			error: () => this.$wrap.find("#ib-fin-ts").text("Error — click Refresh"),
		});
		if (opts) {
			this.$wrap.find("#ib-fin-ts").text("Loading…");
			frappe.call(opts);
		}
	}

	_fmt(v) {
		return "₹" + Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 });
	}

	// Sales Invoice has a real outstanding_amount column; Sales Order (dev
	// billing mode, the app's current default) doesn't — billing_mode.py's
	// own sales_outstanding_expr() comment says so explicitly. A list-view
	// route_options filter can only match a real column, so dev mode drops
	// the outstanding-only filter (shows all confirmed orders) rather than
	// building a filter against a field that isn't there.
	_ar_route_options() {
		return this.dev_mode
			? { docstatus: 1 }
			: { docstatus: 1, outstanding_amount: [">", 0] };
	}

	_render(d) {
		this.sales_dt = d.sales_dt;
		this.purch_dt = d.purch_dt;
		this.dev_mode = d.dev_mode;
		this._render_kpis(d);
		this._render_pl_chart(d.pl_trend);
		this._render_vendors(d.top_vendors);
		this._render_gst(d);
		this._render_cash(d.cash_bank_accounts, d.total_cash_bank);
		this._render_overdue(d.overdue);
		ib_countup_all && ib_countup_all(this.$wrap);
	}

	_render_kpis(d) {
		// The range comes from the filter bar, so the labels cannot say "MTD".
		const f = (this.filters && this.filters.get()) || {};
		const today = f.to_date || frappe.datetime.get_today();
		const ms = f.from_date || today.slice(0, 7) + "-01";
		const kpis = [
			{
				label: __("Revenue"), raw: d.rev_mtd, color: IB_FIN_COLOR_REVENUE,
				delta: ib_delta_html(d.rev_delta),
				click: () => { frappe.route_options = { docstatus: 1, [d.sales_date_field]: ["between", [ms, today]] }; frappe.set_route("List", d.sales_dt); },
			},
			{
				label: __("Gross profit"), raw: d.gross_profit, color: d.gross_margin > 20 ? IB_FIN_COLOR_PROFIT : IB_FIN_COLOR_DANGER,
				delta: `<span class="ib-delta ${d.gross_margin > 20 ? "pos" : "neg"}">${d.gross_margin}% margin</span>`,
				click: () => frappe.set_route("query-report", "IB Gross Margin"),
			},
			{
				label: __("Outstanding AR"), raw: d.ar, color: IB_FIN_COLOR_WARNING,
				delta: `<span class="ib-delta neu">AP: ${this._fmt(d.ap)}</span>`,
				click: () => { frappe.route_options = this._ar_route_options(); frappe.set_route("List", d.sales_dt); },
			},
			{
				label: __("Cash & bank"), raw: d.total_cash_bank, color: IB_FIN_COLOR_CASH,
				delta: `<span class="ib-delta neu">${(d.cash_bank_accounts || []).length} accounts</span>`,
				click: () => frappe.set_route("List", "Payment Entry"),
			},
			{
				label: __("Expenses"), raw: d.exp_mtd, color: IB_FIN_COLOR_EXPENSE,
				delta: ib_delta_html(d.exp_delta),
				click: () => { frappe.route_options = { docstatus: 1, [d.purch_date_field]: ["between", [ms, today]] }; frappe.set_route("List", d.purch_dt); },
			},
			{
				label: __("Revenue YTD"), raw: d.rev_ytd, color: IB_FIN_COLOR_YTD,
				delta: `<span class="ib-delta neu">fiscal year to date</span>`,
				click: () => { frappe.route_options = { docstatus: 1 }; frappe.set_route("List", d.sales_dt); },
			},
		];

		const html = kpis.map((k, i) => `
			<div class="ib-fin-kpi" data-kpi="${i}">
				<div class="ib-fin-kpi-bar" style="background:${k.color}"></div>
				<div class="ib-fin-kpi-lbl">${k.label}</div>
				<div class="ib-fin-kpi-val" data-countup="${k.raw}" data-cu-inr="1" data-cu-compact="1" title="${this._fmt(k.raw)}">${window.ib_fmt_inr_compact ? window.ib_fmt_inr_compact(k.raw) : this._fmt(k.raw)}</div>
				<div class="ib-fin-kpi-delta">${k.delta}</div>
				<span class="ib-fin-arrow">→</span>
			</div>`).join("");

		const $c = this.$wrap.find("#ib-fin-kpis").html(html);
		$c.find(".ib-fin-kpi").on("click", (e) => {
			kpis[parseInt($(e.currentTarget).data("kpi"), 10)].click();
		});
	}

	_render_pl_chart(trend) {
		ibDash.chart(this.$wrap.find("#ib-fin-pl-chart"), {
			type: "bar", height: 200, currency: true,
			labels: (trend || []).map((r) => r.label),
			datasets: [
				{ name: __("Revenue"), values: (trend || []).map((r) => flt(r.revenue)) },
				{ name: __("Expenses"), values: (trend || []).map((r) => flt(r.expenses)) },
				{ name: __("Profit"), values: (trend || []).map((r) => flt(r.profit)), chartType: "line" },
			],
			colors: [IB_FIN_COLOR_REVENUE, IB_FIN_COLOR_EXPENSE, IB_FIN_COLOR_PROFIT],
			empty: __("No revenue or expenses in this window"), emptyIcon: "trending-up",
		});
	}

	_render_vendors(vendors) {
		const $el = this.$wrap.find("#ib-fin-vendors");
		if (!vendors || !vendors.length) { $el.html('<p style="color:var(--text-muted);font-size:12px">No data</p>'); return; }
		const max = Math.max(...vendors.map(v => Number(v.amount)));
		$el.html(vendors.map(v => `
			<div class="ib-fin-bar-row">
				<div class="ib-fin-bar-lbl" title="${frappe.utils.escape_html(v.label)}">${frappe.utils.escape_html(v.label)}</div>
				<div class="ib-fin-bar-track"><div class="ib-fin-bar-fill" style="width:${max ? Math.round(Number(v.amount)/max*100) : 0}%"></div></div>
				<div class="ib-fin-bar-amt">${this._fmt(v.amount)}</div>
			</div>`).join(""));
	}

	_render_gst(d) {
		const net_cls = d.gst_net >= 0 ? "red" : "green";
		const net_lbl = d.gst_net >= 0 ? "Payable (Output > Input)" : "Credit (Input > Output)";
		this.$wrap.find("#ib-fin-gst").html(`
			<div class="ib-fin-gst-row">
				<div class="ib-fin-gst-box">
					<div class="ib-fin-gst-v">${this._fmt(d.gst_collected)}</div>
					<div class="ib-fin-gst-l">Output GST</div>
				</div>
				<div class="ib-fin-gst-box">
					<div class="ib-fin-gst-v">${this._fmt(d.gst_paid)}</div>
					<div class="ib-fin-gst-l">Input GST</div>
				</div>
				<div class="ib-fin-gst-box">
					<div class="ib-fin-gst-v" style="color:${d.gst_net >= 0 ? '#dc2626' : '#059669'}">${this._fmt(Math.abs(d.gst_net))}</div>
					<div class="ib-fin-gst-l">${net_lbl}</div>
				</div>
			</div>`);
	}

	_render_cash(accounts, total) {
		const rows = (accounts || []).map(a => `
			<div class="ib-fin-cash-item">
				<span>${frappe.utils.escape_html(a.name)}</span>
				<span style="font-weight:600">${this._fmt(a.balance)}</span>
			</div>`).join("");
		this.$wrap.find("#ib-fin-cash").html(`
			<div>${rows}</div>
			<div style="display:flex;justify-content:space-between;margin-top:10px;padding-top:10px;
				border-top:2px solid var(--ib-br);font-size:13px;font-weight:700">
				<span>Total</span><span>${this._fmt(total)}</span>
			</div>`);
	}

	_render_overdue(rows) {
		const $el = this.$wrap.find("#ib-fin-overdue");
		if (!rows || !rows.length) {
			$el.html('<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:20px">No overdue invoices</td></tr>');
			return;
		}
		$el.html(rows.map(r => {
			const cls = r.days_overdue > 60 ? "red" : r.days_overdue > 30 ? "amber" : "green";
			return `<tr data-name="${frappe.utils.escape_html(r.name)}">
				<td><a style="color:var(--ib-p)">${frappe.utils.escape_html(r.name)}</a></td>
				<td>${frappe.utils.escape_html(r.customer_name || "")}</td>
				<td>${frappe.datetime.str_to_user(r.posting_date) || ""}</td>
				<td>${frappe.datetime.str_to_user(r.due_date) || ""}</td>
				<td><span class="ib-fin-badge ${cls}">${r.days_overdue}d</span></td>
				<td style="text-align:right;font-weight:600">${this._fmt(r.outstanding_amount)}</td>
			</tr>`;
		}).join(""));
		// r.name here is a doc of whatever sales_doctype() resolved to (Sales
		// Order in dev billing mode) — hardcoding "Sales Invoice" opened a
		// dead Form route for a name in the wrong doctype's naming series.
		const sales_dt = this.sales_dt || "Sales Invoice";
		$el.find("tr[data-name]").on("click", (e) => {
			frappe.set_route("Form", sales_dt, $(e.currentTarget).data("name"));
		});
	}
}
