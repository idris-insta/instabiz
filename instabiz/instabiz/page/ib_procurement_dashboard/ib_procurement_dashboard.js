frappe.pages["ib-procurement-dashboard"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({ parent: wrapper, title: "Procurement", single_column: true });
	wrapper._ib_proc = new IBProcurementDashboard(wrapper);
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

class IBProcurementDashboard {
	constructor(wrapper) {
		this.page      = wrapper.page;
		this.$wrap     = $(wrapper).find(".layout-main-section");
		this._chart    = null;
		this._fetching = false;
		this._inject_styles();
		this._build_layout();
		this._build_controls();
		// refresh + timer started by on_page_show to avoid double call on first load
	}

	_build_controls() {
		this.page.set_secondary_action(__("Refresh"), () => this.refresh(), "refresh");
		this.page.add_menu_item(__("Purchase Orders"), () => { frappe.route_options = { docstatus: 1 }; frappe.set_route("List", "Purchase Order"); });
		this.page.add_menu_item(__("Purchase Invoices"), () => frappe.set_route("List", "Purchase Invoice"));
		this.page.add_menu_item(__("Receipts (GRN)"), () => frappe.set_route("List", "Purchase Receipt"));
		this.filters = ibDash.filters(this.page, {
			key: "procurement-dash",
			fields: [ibDash.F.period(), ibDash.F.location()],
			onChange: () => this.refresh(),
		});
		this.cards = ibDash.personalise(this.page, {
			key: "procurement-dash",
			cards: [
				{ id: "kpis", label: __("Headline numbers"), locked: 1 },
				{ id: "trend", label: __("Spend trend") },
				{ id: "vendors", label: __("Vendor spend") },
				{ id: "items", label: __("Top purchased items") },
				{ id: "po", label: __("Open purchase orders") },
			],
			container: () => this.$wrap.find("[data-cards]"),
		});
		this.cards.apply();
	}

	_inject_styles() {
		if (document.getElementById("ib-proc-css")) return;
		const s = document.createElement("style");
		s.id = "ib-proc-css";
		s.textContent = `
:root { --ib-p:#d97757; }
.ib-proc-wrap { padding:16px; max-width:1400px; }
.ib-proc-toolbar { display:flex; align-items:center; gap:10px; margin-bottom:16px; flex-wrap:wrap; }
.ib-proc-toolbar h2 { font-size:1.2rem; font-weight:700; color:var(--heading-color); margin:0; flex:1; }
.ib-proc-btn { padding:6px 14px; border:1px solid var(--border-color); border-radius:6px;
  background:var(--card-bg,#fff); color:var(--text-color); cursor:pointer; font-size:12px; transition:all .15s; }
.ib-proc-btn:hover { border-color:var(--ib-p); color:var(--ib-p); }
.ib-proc-kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; margin-bottom:16px; }
.ib-proc-kpi { background:var(--card-bg,#fff); border:1px solid var(--border-color); border-radius:8px;
  padding:14px 16px; cursor:pointer; transition:box-shadow .15s; position:relative; overflow:hidden; }
.ib-proc-kpi:hover { box-shadow:0 3px 12px rgba(0,0,0,.08); }
.ib-proc-kpi-bar { position:absolute; left:0; top:0; bottom:0; width:4px; border-radius:8px 0 0 8px; }
.ib-proc-kpi-l { font-size:10px; color:var(--text-muted); text-transform:uppercase; letter-spacing:.06em; }
.ib-proc-kpi-v { font-size:1.35rem; font-weight:700; color:var(--heading-color); margin-top:4px; }
.ib-proc-kpi-d { font-size:11px; margin-top:4px; color:var(--text-muted); }
.ib-proc-kpi-d.pos { color:#10b981; } .ib-proc-kpi-d.neg { color:#ef4444; }
.ib-proc-grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:16px; }
@media(max-width:900px) { .ib-proc-grid { grid-template-columns:1fr; } }
.ib-proc-card { background:var(--card-bg,#fff); border:1px solid var(--border-color); border-radius:10px; padding:18px; }
.ib-proc-card-title { font-size:13px; font-weight:600; color:var(--heading-color); margin-bottom:14px; }
.ib-proc-chart-wrap { height:175px; }
.ib-proc-bar-row { display:flex; align-items:center; gap:8px; margin-bottom:8px; font-size:12px; }
.ib-proc-bar-row .lbl { width:130px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.ib-proc-bar-track { flex:1; background:var(--control-bg,#f1f5f9); border-radius:3px; height:7px; }
.ib-proc-bar-fill { height:7px; border-radius:3px; background:var(--ib-p); transition:width .4s; }
.ib-proc-bar-amt { min-width:80px; text-align:right; color:var(--text-muted); }
.ib-proc-tbl { width:100%; border-collapse:collapse; font-size:12px; }
.ib-proc-tbl th { text-align:left; padding:8px; color:var(--text-muted); font-weight:500; border-bottom:1px solid var(--border-color); }
.ib-proc-tbl td { padding:8px; border-bottom:1px solid var(--border-color); }
.ib-proc-tbl tr:last-child td { border-bottom:none; }
.ib-proc-tbl tbody tr { cursor:pointer; }
.ib-proc-tbl tbody tr:hover td { background:var(--control-bg,#f8fafc); }
.ib-proc-badge { display:inline-block; padding:2px 7px; border-radius:99px; font-size:10px; font-weight:600; }
.ib-proc-badge.red { background:#fee2e2; color:#dc2626; }
.ib-proc-badge.amber { background:#fef3c7; color:#b45309; }
.ib-proc-badge.green { background:#d1fae5; color:#059669; }
`;
		document.head.appendChild(s);
	}

	_build_layout() {
		this.$wrap.html(`
		<div class="ib-proc-wrap ib-ui-page">
			<div class="ib-ui-filter-note" id="ib-proc-note"></div>
			<div class="ib-dash-cards" data-cards>
			<div data-card="kpis" class="ib-dash-c--12"><div id="ib-proc-kpis" class="ib-proc-kpis"></div></div>
				<div data-card="trend" class="ib-dash-c--8"><div class="ib-proc-card">
					<div class="ib-proc-card-title">${__("Spend trend — 6 months")}</div>
					<div class="ib-proc-chart-wrap ib-ui-chart" id="ib-proc-chart"></div>
				</div></div>
				<div data-card="vendors" class="ib-dash-c--4"><div class="ib-proc-card">
					<div class="ib-proc-card-title">${__("Vendor spend")}</div>
					<div id="ib-proc-vendors"></div>
				</div></div>
				<div data-card="items" class="ib-dash-c--6"><div class="ib-proc-card">
					<div class="ib-proc-card-title">${__("Top purchased items")}</div>
					<div id="ib-proc-items"></div>
				</div></div>
				<div data-card="po" class="ib-dash-c--6"><div class="ib-proc-card">
					<div class="ib-proc-card-title">${__("Open purchase orders")}</div>
					<table class="ib-proc-tbl">
						<thead><tr>
							<th>PO</th><th>Vendor</th><th>Schedule</th><th>Status</th><th style="text-align:right">Value</th>
						</tr></thead>
						<tbody id="ib-proc-po-body"></tbody>
					</table>
				</div></div>
			</div>
		</div>`);


	}

	_args() {
		const f = (this.filters && this.filters.get()) || {};
		this.$wrap.find("#ib-proc-note").html(
			`${ibUI.icon("calendar", 13)}<b>${ibUI.esc((this.filters && this.filters.label()) || "")}</b>`);
		return { from_date: f.from_date, to_date: f.to_date, location: f.location };
	}

	refresh() {
		const opts = ib_guarded_call(this, {
			method: "instabiz.instabiz.page.ib_procurement_dashboard.ib_procurement_dashboard.get_procurement_data",
			args: this._args(),
			callback: (r) => {
				if (r.message) {
					this._render(r.message);
					this.cards && this.cards.apply();
					ib_countup_all && ib_countup_all(this.$wrap);
				}
			},
		});
		if (opts) {
			this.$wrap.find("#ib-proc-kpis").html(window.ib_skel_kpis ? ib_skel_kpis(5) : "");
			frappe.call(opts);
		}
	}

	_fmt(v) { return "₹" + Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 }); }

	_render(d) {
		this._render_kpis(d);
		this._render_chart(d.spend_trend);
		this._render_vendors(d.by_vendor);
		this._render_items(d.top_items);
		this._render_po(d.open_po_list);
	}

	_render_kpis(d) {
		const delta = d.spend_delta;
		const delta_cls = delta > 0 ? "neg" : "pos";
		const delta_lbl = delta !== 0 ? `${delta > 0 ? "▲" : "▼"} ${Math.abs(delta)}% vs last month` : "= vs last month";
		const kpis = [
			{ label: "Open POs",    value: d.open_po_count,          raw: d.open_po_count,  isInr: false,
			  sub: this._fmt(d.open_po_value), color: "#3b82f6",
			  click: () => { frappe.route_options = { docstatus: 1 }; frappe.set_route("List", "Purchase Order"); } },
			{ label: "Pending GRN", value: d.pending_grn,            raw: d.pending_grn,    isInr: false,
			  sub: "orders to receive", color: "#f59e0b",
			  click: () => { frappe.route_options = { docstatus: 1, status: ["in", ["To Receive and Bill", "To Receive"]] }; frappe.set_route("List", "Purchase Order"); } },
			{ label: __("Spend"),   value: this._fmt(d.spend_mtd),   raw: d.spend_mtd,      isInr: true,
			  sub: `<span class="${delta_cls}">${delta_lbl}</span>`, color: "#d97757",
			  click: () => { frappe.route_options = { docstatus: 1 }; frappe.set_route("List", d.spend_doctype); } },
			{ label: "Overdue AP",  value: this._fmt(d.overdue_ap),  raw: d.overdue_ap,     isInr: true,
			  sub: "past due date", color: d.overdue_ap > 0 ? "#ef4444" : "#10b981",
			  click: () => { frappe.route_options = { docstatus: 1, outstanding_amount: [">", 0] }; frappe.set_route("List", "Purchase Invoice"); } },
			{ label: "Draft Bills", value: d.pending_pi,             raw: d.pending_pi,     isInr: false,
			  sub: "not submitted", color: "#8b5cf6",
			  click: () => { frappe.route_options = { docstatus: 0 }; frappe.set_route("List", "Purchase Invoice"); } },
		];

		const html = kpis.map((k, i) => {
			const cuAttr = k.raw != null
				? (k.isInr ? `data-countup="${k.raw}" data-cu-inr="1"` : `data-countup="${k.raw}"`)
				: "";
			return `
			<div class="ib-proc-kpi" data-kpi="${i}">
				<div class="ib-proc-kpi-bar" style="background:${k.color}"></div>
				<div class="ib-proc-kpi-l">${k.label}</div>
				<div class="ib-proc-kpi-v" ${cuAttr}>${k.value}</div>
				<div class="ib-proc-kpi-d">${k.sub}</div>
			</div>`;
		}).join("");

		const $c = this.$wrap.find("#ib-proc-kpis").html(html);
		$c.find(".ib-proc-kpi").on("click", (e) => {
			kpis[parseInt($(e.currentTarget).data("kpi"), 10)].click();
		});
	}

	_render_chart(trend) {
		this._chart = ibDash.chart(this.$wrap.find("#ib-proc-chart"), {
			type: "line", height: 200, currency: true, tone: "brand",
			labels: (trend || []).map((r) => r.label),
			datasets: [{ name: __("Spend"), values: (trend || []).map((r) => Number(r.amount || 0)) }],
			empty: __("No spend recorded"), emptyIcon: "shopping-cart",
		});
	}

	_render_vendors(vendors) {
		if (!vendors || !vendors.length) { this.$wrap.find("#ib-proc-vendors").html('<p style="color:var(--text-muted);font-size:12px">No data</p>'); return; }
		const max = Math.max(...vendors.map(v => Number(v.amount)));
		const html = vendors.map(v => `
			<div class="ib-proc-bar-row">
				<div class="lbl" title="${frappe.utils.escape_html(v.label)}">${frappe.utils.escape_html(v.label)}</div>
				<div class="ib-proc-bar-track"><div class="ib-proc-bar-fill" style="width:${max ? Math.round(Number(v.amount)/max*100) : 0}%"></div></div>
				<div class="ib-proc-bar-amt">${this._fmt(v.amount)}</div>
			</div>`).join("");
		this.$wrap.find("#ib-proc-vendors").html(html);
	}

	_render_items(items) {
		if (!items || !items.length) { this.$wrap.find("#ib-proc-items").html('<p style="color:var(--text-muted);font-size:12px">No data</p>'); return; }
		const max = Math.max(...items.map(v => Number(v.amount)));
		const html = items.map(v => `
			<div class="ib-proc-bar-row">
				<div class="lbl" title="${frappe.utils.escape_html(v.label)}">${frappe.utils.escape_html(v.label)}</div>
				<div class="ib-proc-bar-track"><div class="ib-proc-bar-fill" style="width:${max ? Math.round(Number(v.amount)/max*100) : 0}%;background:#8b5cf6"></div></div>
				<div class="ib-proc-bar-amt">${this._fmt(v.amount)}</div>
			</div>`).join("");
		this.$wrap.find("#ib-proc-items").html(html);
	}

	_render_po(rows) {
		if (!rows || !rows.length) {
			this.$wrap.find("#ib-proc-po-body").html('<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:16px">No open POs</td></tr>');
			return;
		}
		const html = rows.map(r => {
			const overdue = r.days_overdue > 0;
			const cls = r.days_overdue > 14 ? "red" : r.days_overdue > 0 ? "amber" : "green";
			return `<tr style="cursor:pointer" data-name="${frappe.utils.escape_html(r.name)}">
				<td><a style="color:var(--ib-p)">${frappe.utils.escape_html(r.name)}</a></td>
				<td>${frappe.utils.escape_html(r.supplier_name || r.supplier || "")}</td>
				<td>${r.schedule_date ? frappe.datetime.str_to_user(r.schedule_date) : "—"}
					${overdue ? `<span class="ib-proc-badge ${cls}" style="margin-left:4px">+${r.days_overdue}d</span>` : ""}</td>
				<td><span class="ib-proc-badge ${r.status === 'To Receive' ? 'amber' : 'green'}">${r.status}</span></td>
				<td style="text-align:right;font-weight:600">${this._fmt(r.grand_total)}</td>
			</tr>`;
		}).join("");
		this.$wrap.find("#ib-proc-po-body").html(html);
		this.$wrap.find("#ib-proc-po-body tr[data-name]").on("click", function () {
			frappe.set_route("Form", "Purchase Order", $(this).data("name"));
		});
	}
}
