frappe.pages["ib-analytics-hub"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({
		parent: wrapper,
		title: "Analytics Hub",
		single_column: true,
	});
	wrapper._ib_hub = new IBAnalyticsHub(wrapper);
};

frappe.pages["ib-analytics-hub"].on_page_show = function (wrapper) {
	if (!wrapper._ib_hub) return;
	wrapper._ib_hub._cache = {};
	wrapper._ib_hub.refresh();
};

// ─────────────────────────────────────────────────────────────────────────────

const IB_HUB_TABS = [
	{ key: "me",         label: "My Work",    icon: "lucide:user-check",   color: "#d97757" },
	{ key: "sales",      label: "Sales",      icon: "lucide:receipt",      color: "#d97757" },
	{ key: "inventory",  label: "Inventory",  icon: "lucide:package",      color: "#8b5cf6" },
	{ key: "production", label: "Production", icon: "lucide:factory",      color: "#10b981" },
	{ key: "hr",         label: "HR",         icon: "lucide:users",        color: "#06b6d4" },
	{ key: "finance",    label: "Finance",    icon: "lucide:landmark",     color: "#f59e0b" },
	{ key: "procurement",label: "Procurement",icon: "lucide:truck",        color: "#f97316" },
	{ key: "docs",       label: "Docs",       icon: "lucide:git-branch",   color: "#0ea5e9" },
];

const IB_HUB_PERIODS = [
	{ key: "daily",   label: "Daily" },
	{ key: "weekly",  label: "Weekly" },
	{ key: "monthly", label: "Monthly" },
];

class IBAnalyticsHub {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.page = wrapper.page;
		this._roles = (frappe.boot && frappe.boot.user && frappe.boot.user.roles) || [];
		// Default to "My Work" for Sales Users who aren't also managers
		const _mgr_roles = ["System Manager", "Sales Manager", "HR Manager", "Accounts Manager", "Factory Management", "Purchase Manager"];
		const _is_sales_only = this._roles.includes("Sales User") && !this._roles.some(r => _mgr_roles.includes(r));
		this._active_tab = _is_sales_only ? "me" : "sales";
		this._period = "monthly";
		this._chart = null;
		this._cache = {};
		this._load_key = null;
		this._me_stab = "outstanding";
		this._docs_search = "";
		this._docs_filter = "all";
		this._docs_sp = "";
		this._docs_page = 0;
		this._docs_page_size = 10;
		this._inject_styles();
		this._build_layout();
		this._bind_toolbar();
	}

	// ── Styles ────────────────────────────────────────────────────────────────
	_inject_styles() {
		if (document.getElementById("ib-hub-styles")) return;
		const s = document.createElement("style");
		s.id = "ib-hub-styles";
		s.textContent = `
/* Wrapper */
.ib-hub-wrap { padding: 20px; max-width: 1440px; }

/* Top bar */
.ib-hub-topbar {
  display: flex; align-items: center; gap: 8px;
  margin-bottom: 20px; flex-wrap: wrap;
}
.ib-hub-topbar-right { margin-left: auto; display: flex; align-items: center; gap: 8px; }
.ib-hub-ts {
  font-size: 11px; color: var(--text-muted);
  background: var(--bg-color); border: 1px solid var(--border-color);
  padding: 3px 8px; border-radius: 20px;
}

/* Tab navigation */
.ib-hub-nav {
  display: flex; gap: 4px;
  background: var(--bg-color);
  border: 1px solid var(--border-color);
  border-radius: 10px; padding: 4px;
  flex-wrap: wrap;
}
.ib-hub-tab {
  padding: 7px 18px; border-radius: 7px;
  font-size: 13px; font-weight: 500;
  cursor: pointer; border: none;
  background: transparent; color: var(--text-muted);
  transition: all .18s; white-space: nowrap;
  display: flex; align-items: center; gap: 6px;
}
.ib-hub-tab:hover { color: var(--heading-color); background: var(--card-bg); }
.ib-hub-tab.active {
  background: var(--card-bg);
  color: var(--ib-hub-color, var(--ib-primary));
  box-shadow: 0 1px 4px rgba(0,0,0,.1);
  font-weight: 600;
}
.ib-hub-tab-icon {
  font-style: normal;
  width: 20px; display: inline-flex; align-items: center; justify-content: center;
}

/* Period pills */
.ib-hub-periods { display: flex; gap: 4px; }
.ib-hub-period {
  padding: 6px 14px; border-radius: 20px; font-size: 12px;
  font-weight: 500; cursor: pointer;
  border: 1px solid var(--border-color);
  background: var(--card-bg); color: var(--text-muted);
  transition: all .15s;
}
.ib-hub-period:hover { border-color: var(--ib-hub-color, var(--ib-primary)); color: var(--heading-color); }
.ib-hub-period.active {
  background: var(--ib-hub-color, var(--ib-primary));
  border-color: var(--ib-hub-color, var(--ib-primary));
  color: #fff;
}

/* Export button */
.ib-hub-export-btn {
  padding: 6px 14px; border-radius: 7px; font-size: 12px;
  font-weight: 500; cursor: pointer;
  border: 1px solid var(--border-color);
  background: var(--card-bg); color: var(--text-muted);
  transition: all .15s;
}
.ib-hub-export-btn:hover { border-color: var(--ib-primary); color: var(--ib-primary); }

/* KPI grid */
.ib-hub-kpi-row {
  display: grid; grid-template-columns: repeat(4, 1fr);
  gap: 12px; margin-bottom: 20px;
}

/* KPI card — modern left-border accent */
.ib-hub-kpi {
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-left: 4px solid var(--ib-hub-color, var(--ib-primary));
  border-radius: 10px; padding: 18px 20px;
  cursor: pointer; position: relative; overflow: hidden;
  transition: box-shadow .2s, transform .2s;
}
.ib-hub-kpi:hover {
  box-shadow: 0 6px 24px rgba(0,0,0,.09);
  transform: translateY(-2px);
}
.ib-hub-kpi-badge {
  position: absolute; top: 14px; right: 14px;
  opacity: .15; font-style: normal;
  display: flex; align-items: center;
}
.ib-hub-kpi-val {
  font-size: 26px; font-weight: 700;
  color: var(--heading-color); line-height: 1.1;
  margin-bottom: 5px;
}
.ib-hub-kpi-lbl {
  font-size: 11px; color: var(--text-muted);
  text-transform: uppercase; letter-spacing: .5px; font-weight: 500;
}
.ib-hub-kpi-delta { font-size: 11px; margin-top: 6px; font-weight: 500; }
.ib-hub-kpi-delta.pos { color: #16a34a; }
.ib-hub-kpi-delta.neg { color: #dc2626; }
.ib-hub-kpi-delta.neu { color: var(--text-muted); }
.ib-hub-kpi-link-hint {
  font-size: 10px; color: var(--ib-hub-color, var(--ib-primary));
  margin-top: 6px; opacity: 0; transition: opacity .15s;
  font-weight: 600; letter-spacing: .3px;
}
.ib-hub-kpi:hover .ib-hub-kpi-link-hint { opacity: 1; }

/* Charts row */
.ib-hub-charts-row {
  display: grid; grid-template-columns: 1.8fr 1fr;
  gap: 12px; margin-bottom: 16px;
}

/* Cards */
.ib-hub-card {
  background: var(--card-bg); border: 1px solid var(--border-color);
  border-radius: 10px; padding: 18px 20px;
}
.ib-hub-card-title {
  font-size: 11px; font-weight: 700; color: var(--text-muted);
  text-transform: uppercase; letter-spacing: .6px; margin-bottom: 14px;
  display: flex; align-items: center; justify-content: space-between;
}
.ib-hub-chart-wrap { height: 220px; }

/* Bar breakdown */
.ib-hub-bar-row {
  display: flex; align-items: center; gap: 10px;
  padding: 5px 0; font-size: 12px;
}
.ib-hub-bar-lbl {
  width: 130px; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; font-size: 11px; color: var(--text-muted);
  flex-shrink: 0;
}
.ib-hub-bar-track {
  flex: 1; height: 7px; background: var(--bg-color);
  border-radius: 4px; overflow: hidden;
  border: 1px solid var(--border-color);
}
.ib-hub-bar-fill {
  height: 100%; border-radius: 4px;
  background: var(--ib-hub-color, var(--ib-primary));
  transition: width .5s cubic-bezier(.4,0,.2,1);
}
.ib-hub-bar-val {
  width: 90px; text-align: right; font-size: 11px;
  font-weight: 600; color: var(--heading-color); flex-shrink: 0;
}

/* Table */
.ib-hub-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.ib-hub-table th {
  text-align: left; padding: 8px 10px; font-size: 10px;
  font-weight: 700; color: var(--text-muted);
  text-transform: uppercase; letter-spacing: .5px;
  border-bottom: 2px solid var(--border-color);
  background: var(--bg-color);
}
.ib-hub-table td {
  padding: 8px 10px; border-bottom: 1px solid var(--border-color);
  color: var(--text-color);
}
.ib-hub-table tr:last-child td { border-bottom: none; }
.ib-hub-table tbody tr:hover td { background: var(--bg-color); }

/* Docs tab — chain pipeline */
.ib-hub-chain-row { display: flex; align-items: center; gap: 4px; flex-wrap: nowrap; }
.ib-hub-chain-badge {
  font-size: 10px; font-weight: 600; padding: 2px 7px; border-radius: 20px;
  white-space: nowrap; border: 1px solid transparent;
}
.ib-hub-chain-arrow { color: var(--text-muted); font-size: 11px; flex-shrink: 0; }
.ib-hub-chain-badge.done   { background: rgba(22,163,74,.12); color: #16a34a; }
.ib-hub-chain-badge.pending{ background: rgba(217,119,87,.12); color: #d97757; }
.ib-hub-chain-badge.none   { background: var(--bg-color); color: var(--text-muted); border-color: var(--border-color); }
.ib-hub-chain-badge.risk   { background: rgba(220,38,38,.12); color: #dc2626; }
.ib-hub-chain-link { cursor: pointer; }
.ib-hub-chain-link:hover { text-decoration: underline; }
.ib-hub-chain-badge-link { cursor: pointer; text-decoration: none; }
.ib-hub-chain-badge-link:hover { text-decoration: underline; filter: brightness(0.9); }
.ib-hub-docs-empty {
  padding: 40px 20px; text-align: center; color: var(--text-muted); font-size: 12px;
}
.ib-hub-docs-empty iconify-icon { opacity: .5; margin-bottom: 8px; display: block; margin-left: auto; margin-right: auto; }

/* Docs tab — toolbar (search / filter / pager), reuses period-pill look */
.ib-hub-docs-toolbar {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  margin-bottom: 12px; padding-bottom: 12px; border-bottom: 1px solid var(--border-color);
}
.ib-hub-docs-search {
  flex: 1 1 200px; min-width: 160px; padding: 6px 10px; border-radius: 7px;
  border: 1px solid var(--border-color); background: var(--card-bg);
  color: var(--text-color); font-size: 12px;
}
.ib-hub-docs-filter {
  padding: 6px 12px; border-radius: 20px; font-size: 12px; font-weight: 500;
  cursor: pointer; border: 1px solid var(--border-color);
  background: var(--card-bg); color: var(--text-muted); transition: all .15s; white-space: nowrap;
}
.ib-hub-docs-filter:hover { border-color: var(--ib-hub-color, var(--ib-primary)); color: var(--heading-color); }
.ib-hub-docs-filter.active {
  background: var(--ib-hub-color, var(--ib-primary));
  border-color: var(--ib-hub-color, var(--ib-primary)); color: #fff;
}
.ib-hub-docs-count { font-size: 11px; color: var(--text-muted); margin-left: auto; white-space: nowrap; }
.ib-hub-docs-pager {
  display: flex; align-items: center; justify-content: center; gap: 12px;
  padding-top: 12px; margin-top: 4px; border-top: 1px solid var(--border-color); font-size: 12px;
}
.ib-hub-docs-pager button {
  padding: 4px 12px; border-radius: 6px; border: 1px solid var(--border-color);
  background: var(--card-bg); color: var(--text-color); cursor: pointer; font-size: 12px;
}
.ib-hub-docs-pager button:disabled { opacity: .4; cursor: not-allowed; }
.ib-hub-docs-pager span { color: var(--text-muted); }

/* Skeleton loading */
.ib-skel {
  background: linear-gradient(90deg,
    var(--bg-color) 25%, var(--border-color) 50%, var(--bg-color) 75%);
  background-size: 200% 100%;
  animation: ib-skel-anim 1.4s ease-in-out infinite;
  border-radius: 6px;
}
@keyframes ib-skel-anim {
  0% { background-position: 200% 0 }
  100% { background-position: -200% 0 }
}
.ib-skel-kpi {
  height: 90px; border-radius: 10px;
  border-left: 4px solid var(--border-color);
}
.ib-skel-chart { height: 220px; border-radius: 10px; }
.ib-skel-row { height: 32px; margin-bottom: 8px; }

/* Me-tab target banner */
.ib-hub-me-target {
  background: var(--bg-color); border: 1px solid var(--border-color);
  border-radius: 8px; padding: 12px 16px; margin-bottom: 14px;
  display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
}
.ib-hub-me-tgt-label { font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: .5px; }
.ib-hub-me-tgt-val { font-size: 18px; font-weight: 700; color: var(--heading-color); }
.ib-hub-me-tgt-progress {
  flex: 1; min-width: 120px; height: 8px;
  background: var(--border-color); border-radius: 4px; overflow: hidden;
}
.ib-hub-me-tgt-fill { height: 100%; border-radius: 4px; transition: width .6s ease; }
.ib-hub-me-tgt-pct { font-size: 13px; font-weight: 700; white-space: nowrap; }
.ib-hub-me-slab {
  font-size: 11px; padding: 2px 8px; border-radius: 10px;
  background: #fef3c7; color: #92400e; font-weight: 600;
}

/* Me-tab pending sub-tabs */
.ib-hub-me-stabs {
  display: flex; gap: 4px; flex-wrap: wrap;
}
.ib-hub-me-stab {
  padding: 4px 12px; border-radius: 12px; font-size: 11px; font-weight: 600;
  cursor: pointer; border: 1px solid var(--border-color);
  background: var(--bg-color); color: var(--text-muted); white-space: nowrap;
  transition: all .15s;
}
.ib-hub-me-stab:hover { border-color: var(--ib-hub-color, var(--ib-primary)); color: var(--heading-color); }
.ib-hub-me-stab.active {
  background: var(--ib-hub-color, var(--ib-primary));
  border-color: var(--ib-hub-color, var(--ib-primary));
  color: #fff;
}
.ib-hub-me-badge {
  display: inline-block; background: rgba(255,255,255,.3);
  border-radius: 10px; padding: 0 5px; margin-left: 4px;
  font-size: 10px; font-weight: 700;
}
.ib-hub-me-stab:not(.active) .ib-hub-me-badge {
  background: var(--border-color); color: var(--text-muted);
}

/* Responsive */
@media (max-width: 1100px) {
  .ib-hub-kpi-row { grid-template-columns: repeat(2, 1fr); }
  .ib-hub-charts-row { grid-template-columns: 1fr; }
}
@media (max-width: 600px) {
  .ib-hub-kpi-row { grid-template-columns: 1fr; }
  .ib-hub-tab { padding: 6px 12px; font-size: 12px; }
}
		`;
		document.head.appendChild(s);
	}

	// ── Layout ────────────────────────────────────────────────────────────────
	_build_layout() {
		const $pc = $(this.wrapper).find(".layout-main-section, .page-content").first();
		this.$wrap = $(`<div class="ib-hub-wrap"></div>`).appendTo($pc);

		const tabs_html = IB_HUB_TABS
			.filter(t => this._can_see_tab(t.key))
			.map(t =>
				`<button class="ib-hub-tab${t.key === this._active_tab ? " active" : ""}"
				  data-tab="${t.key}" data-color="${t.color}"
				  style="${t.key === this._active_tab ? `--ib-hub-color:${t.color}` : ""}">
				  <iconify-icon icon="${t.icon}" width="14" height="14" class="ib-hub-tab-icon"></iconify-icon>${t.label}
				</button>`
			).join("");

		const periods_html = IB_HUB_PERIODS.map(p =>
			`<button class="ib-hub-period${p.key === this._period ? " active" : ""}" data-period="${p.key}">
			  ${p.label}
			</button>`
		).join("");

		this.$wrap.html(`
			<div class="ib-hub-topbar">
				<div class="ib-hub-nav" id="ib-hub-tabs">${tabs_html}</div>
				<div class="ib-hub-topbar-right">
					<div class="ib-hub-periods" id="ib-hub-periods">${periods_html}</div>
					<button class="ib-hub-export-btn btn btn-xs btn-default" id="ib-hub-export">↓ CSV</button>
					<span class="ib-hub-ts" id="ib-hub-ts">—</span>
				</div>
			</div>
			<div class="ib-hub-kpi-row" id="ib-hub-kpis">${this._skeleton_kpis()}</div>
			<div class="ib-hub-charts-row">
				<div class="ib-hub-card">
					<div class="ib-hub-card-title">
						<span id="ib-hub-trend-title">Trend</span>
					</div>
					<div class="ib-hub-chart-wrap" id="ib-hub-trend">
						<div class="ib-skel ib-skel-chart"></div>
					</div>
				</div>
				<div class="ib-hub-card">
					<div class="ib-hub-card-title" id="ib-hub-break-title">Breakdown</div>
					<div id="ib-hub-breakdown">
						${[1,2,3,4,5].map(() => `<div class="ib-skel ib-skel-row"></div>`).join("")}
					</div>
				</div>
			</div>
			<div class="ib-hub-card" id="ib-hub-table-card" style="display:none">
				<div class="ib-hub-card-title" id="ib-hub-table-title">Detail</div>
				<div id="ib-hub-table"></div>
			</div>
		`);

		// Tab clicks
		this.$wrap.on("click", ".ib-hub-tab", (e) => {
			const $btn = $(e.currentTarget);
			const tab = $btn.data("tab");
			const color = $btn.data("color");
			this.$wrap.find(".ib-hub-tab").removeClass("active").css("--ib-hub-color", "");
			$btn.addClass("active").css("--ib-hub-color", color);
			this.$wrap.css("--ib-hub-color", color);
			this._active_tab = tab;
			this._docs_search = "";
			this._docs_filter = "all";
			this._docs_sp = "";
			this._docs_page = 0;
			this._load();
		});

		// Period clicks
		this.$wrap.on("click", ".ib-hub-period", (e) => {
			const period = $(e.currentTarget).data("period");
			this.$wrap.find(".ib-hub-period").removeClass("active");
			$(e.currentTarget).addClass("active");
			this._period = period;
			this._cache = {};
			this._load();
		});

		// Export
		this.$wrap.find("#ib-hub-export").on("click", () => this._export_csv());

		// Set initial color
		const first = IB_HUB_TABS.find(t => t.key === this._active_tab);
		if (first) this.$wrap.css("--ib-hub-color", first.color);
	}

	_can_see_tab() {
		// Every tab is visible to every role now — the backend scopes the data
		// (company-wide for privileged roles, the user's own work for everyone
		// else) instead of hiding tabs outright.
		return true;
	}

	_skeleton_kpis() {
		return `<div class="ib-skel ib-skel-kpi"></div>`.repeat(4);
	}

	// ── Toolbar ───────────────────────────────────────────────────────────────
	_bind_toolbar() {
		this.page.add_button(__("Main Dashboard"), () => frappe.set_route("ib-main-dashboard"));
		this.page.add_inner_button(__("Refresh"), () => { this._cache = {}; this._load(); });
	}

	refresh() { this._load(); }

	// ── Data loading ──────────────────────────────────────────────────────────
	_load() {
		const key = `${this._active_tab}_${this._period}`;
		this._load_key = key;
		if (this._cache[key]) {
			this._render(this._cache[key]);
			return;
		}
		this._show_skeleton();
		this.$wrap.find("#ib-hub-ts").text("Loading…");
		frappe.call({
			method: "instabiz.instabiz.page.ib_analytics_hub.ib_analytics_hub.get_analytics_data",
			args: { tab: this._active_tab, period: this._period },
			callback: (r) => {
				if (r.message && this._load_key === key) {
					this._cache[key] = r.message;
					this._render(r.message);
					this.$wrap.find("#ib-hub-ts").text("Updated " + frappe.datetime.now_time());
				}
			},
			error: () => {
				if (this._load_key === key)
					this.$wrap.find("#ib-hub-ts").text("Error loading");
			},
		});
	}

	_show_skeleton() {
		this.$wrap.find("#ib-hub-kpis").html(this._skeleton_kpis());
		this.$wrap.find("#ib-hub-trend").html(`<div class="ib-skel ib-skel-chart"></div>`);
		this.$wrap.find("#ib-hub-breakdown").html(
			[1,2,3,4,5].map(() => `<div class="ib-skel ib-skel-row"></div>`).join("")
		);
		this.$wrap.find("#ib-hub-table-card").hide();
	}

	// ── Render ────────────────────────────────────────────────────────────────
	_render(d) {
		// Store user_type for "me" tab so icon/title helpers can read it
		if (this._active_tab === "me") {
			this._me_usertype = (d.meta || {}).user_type || "sales";
		}
		// Non-privileged viewers get scoped data on every tab now (not just
		// "me") — titles/labels read this to say "My ..." instead of the
		// company-wide title.
		this._scoped = !!(d.meta || {}).scoped;
		// Docs tab has two shapes (order chain vs HR request pipeline) — the
		// KPI-card click behaviour differs per shape, so stash it for
		// _docs_kpi_action().
		this._docs_chain_type = (d.meta || {}).chain_type || "order";
		this._render_kpis(d.kpis || []);
		this._render_trend(d.trend || []);
		this._render_breakdown(d.breakdown || []);
		this._render_table(d);
	}

	// ── KPI deep-link map ────────────────────────────────────────────────────
	// KNOWN GAP (flagged, not fixed, 2026-08-11): every "sales"/"finance"/
	// "procurement" link below is hardcoded to Sales Invoice/Purchase
	// Invoice, but ib_analytics_hub.py's 6 data functions (_sales_data,
	// _my_work_sales, _my_work_finance, _finance_data, _procurement_data,
	// _my_finance_data) are ALL billing_mode-aware (import is_dev_billing_mode/
	// sales_doctype/purchase_doctype from instabiz.overrides.billing_mode) and
	// currently compute every KPI number from Sales Order/Purchase Order (dev
	// mode, the site's current ib_billing_mode). So today, clicking any KPI
	// card on Sales/Finance/Procurement/"Me" opens an empty Sales/Purchase
	// Invoice list — the number matches Sales Order/Purchase Order, the link
	// doesn't. Same bug class already found+fixed 2026-08-11 in
	// ib_finance_dashboard.js/ib_procurement_dashboard.js/
	// ib_collections_dashboard.js/ib_main_dashboard.js (backend already
	// exposes sales_dt/purch_dt in its response, frontend reads it instead of
	// a literal string). Not applied here yet — would need `sales_dt`/
	// `purch_dt` added to all 6 return dicts above, threaded into this
	// function's `d` parameter, and every "Sales Invoice"/"Purchase Invoice"
	// literal below swapped for it. See memory "billing-mode-so-si-toggle-map"
	// for the full file inventory.
	_kpi_link(tab, idx) {
		const today = frappe.datetime.get_today();
		const m0 = today.slice(0, 7) + "-01";
		const links = {
			me: [
				() => frappe.set_route("List", "Sales Invoice", {docstatus: 1, is_return: 0, "posting_date,Between": [m0, today], custom_sales_person_user: frappe.session.user}),
				() => frappe.set_route("List", "Sales Order", {docstatus: 1, "transaction_date,Between": [m0, today], custom_sales_person_user: frappe.session.user}),
				() => frappe.set_route("List", "Lead", {lead_owner: frappe.session.user}),
				() => frappe.set_route("ib-sales-incentives"),
			],
			sales: [
				() => frappe.set_route("List", "Sales Invoice", {docstatus: 1, is_return: 0, "posting_date,Between": [m0, today]}),
				() => frappe.set_route("List", "Sales Invoice", {docstatus: 1, is_return: 0, "posting_date,Between": [m0, today]}),
				() => frappe.set_route("List", "Sales Invoice", {docstatus: 1, is_return: 0, "posting_date,Between": [m0, today]}),
				() => frappe.set_route("List", "Sales Invoice", {docstatus: 1, outstanding_amount: [">", 0]}),
			],
			inventory: [
				() => frappe.set_route("ib-stock-dashboard"),
				() => frappe.set_route("ib-stock-dashboard"),
				() => frappe.set_route("ib-stock-dashboard"),
				() => frappe.set_route("ib-stock-dashboard"),
			],
			production: [
				() => frappe.set_route("List", "IB Work Order", {status: ["In", "Pending,In Progress,On Hold"]}),
				() => frappe.set_route("List", "IB Work Order", {status: "Completed"}),
				() => frappe.set_route("List", "IB Machine", {status: "Active"}),
				() => frappe.set_route("ib-dpr"),
			],
			hr: [
				() => frappe.set_route("List", "Employee", {status: "Active"}),
				() => frappe.set_route("List", "Attendance", {attendance_date: today, status: "Present", docstatus: 1}),
				() => frappe.set_route("List", "Leave Application", {status: "Open", docstatus: 1}),
				() => frappe.set_route("List", "Salary Slip", {docstatus: 1, "start_date,>=": m0}),
			],
			finance: [
				() => frappe.set_route("List", "Sales Invoice", {docstatus: 1, is_return: 0, "posting_date,Between": [m0, today]}),
				() => frappe.set_route("List", "Sales Invoice", {docstatus: 1, outstanding_amount: [">", 0]}),
				() => frappe.set_route("List", "Purchase Invoice", {docstatus: 1, outstanding_amount: [">", 0]}),
				() => frappe.set_route("gstr-1-beta"),
			],
			procurement: [
				() => frappe.set_route("ib-procurement-dashboard"),
				() => frappe.set_route("List", "Purchase Order", {docstatus: 1, status: ["not in", ["Completed", "Cancelled", "Closed"]]}),
				() => frappe.set_route("List", "Purchase Order", {docstatus: 1, status: ["in", ["To Receive and Bill", "To Receive"]]}),
				() => frappe.set_route("List", "Purchase Invoice", {docstatus: 1, outstanding_amount: [">", 0]}),
			],
		};
		return (links[tab] || [])[idx] || null;
	}

	_render_kpis(kpis) {
		const me_icons_by_type = {
			sales:      ["lucide:indian-rupee","lucide:shopping-cart","lucide:users","lucide:gift"],
			hr:         ["lucide:users","lucide:check-circle","lucide:clock","lucide:wallet"],
			production: ["lucide:factory","lucide:alert-circle","lucide:check-circle","lucide:cpu"],
			finance:    ["lucide:alert-circle","lucide:trending-down","lucide:landmark","lucide:trending-up"],
		};
		const icons = {
			me:         me_icons_by_type[this._me_usertype || "sales"] || me_icons_by_type.sales,
			sales:      ["lucide:indian-rupee","lucide:file-text","lucide:activity","lucide:alert-circle"],
			inventory:  ["lucide:package","lucide:check-circle","lucide:x-circle","lucide:wallet"],
			production: ["lucide:factory","lucide:check-circle","lucide:loader","lucide:clock"],
			hr:         ["lucide:users","lucide:check-circle","lucide:mail","lucide:wallet"],
			finance:    ["lucide:landmark","lucide:trending-up","lucide:trending-down","lucide:pie-chart"],
			procurement:["lucide:indian-rupee","lucide:shopping-bag","lucide:truck","lucide:landmark"],
			docs:       ["lucide:list-ordered","lucide:truck","lucide:credit-card","lucide:check-circle"],
		};
		const icon_set = icons[this._active_tab] || Array(4).fill("lucide:circle");

		// Crore/lakh-scale for currency KPI cards (same overflow fix as
		// Customer Health / Finance Dashboard) — the exact amount lives in
		// the returned title, not the outer card's own "Click to view
		// detail" title below.
		const fmt_val = (k) => {
			const v = k.value;
			if (k.type === "currency") {
				const compact = window.ib_fmt_inr_compact
					? window.ib_fmt_inr_compact(v)
					: "₹" + Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 });
				const full = "₹" + Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 });
				return { text: compact, title: full };
			}
			if (k.type === "pct")
				return { text: (parseFloat(v) || 0).toFixed(1) + "%", title: "" };
			return { text: Number(v || 0).toLocaleString("en-IN"), title: "" };
		};
		const delta_html = (k) => {
			if (!k.delta) return "";
			const cls = k.delta > 0 ? "pos" : k.delta < 0 ? "neg" : "neu";
			const sign = k.delta > 0 ? "▲" : "▼";
			return `<div class="ib-hub-kpi-delta ${cls}">${sign} ${Math.abs(k.delta)}% ${k.delta_label || "vs last period"}</div>`;
		};

		const $kpis = this.$wrap.find("#ib-hub-kpis");
		$kpis.html(kpis.map((k, i) => {
			const fv = fmt_val(k);
			return `
			<div class="ib-hub-kpi" data-kpi-idx="${i}" style="cursor:pointer" title="Click to view detail">
				<span class="ib-hub-kpi-badge"><iconify-icon icon="${icon_set[i]}" width="18" height="18"></iconify-icon></span>
				<div class="ib-hub-kpi-val" ${fv.title ? `title="${fv.title}"` : ""}>${fv.text}</div>
				<div class="ib-hub-kpi-lbl">${k.label}</div>
				${delta_html(k)}
				<div class="ib-hub-kpi-link-hint">↗ View</div>
			</div>
		`;
		}).join(""));

		// Bind deep-link clicks
		$kpis.find(".ib-hub-kpi").each((i, el) => {
			const fn = this._active_tab === "docs"
				? this._docs_kpi_action(i)
				: this._kpi_link(this._active_tab, i);
			if (fn) {
				$(el).on("click", fn).css("cursor", "pointer");
			} else {
				$(el).css("cursor", "default").removeAttr("title");
			}
		});
	}

	// Docs-tab KPI cards. Order-chain KPIs (Orders / Awaiting Dispatch /
	// Awaiting Payment / Fully Paid) filter the chain table in place, matching
	// the tab's own filter chips. HR-chain KPIs open the relevant list view.
	_docs_kpi_action(idx) {
		if (this._docs_chain_type === "hr") {
			const today = frappe.datetime.get_today();
			const m0 = today.slice(0, 7) + "-01";
			return [
				() => frappe.set_route("List", "Leave Application", { status: "Open", docstatus: 1 }),
				() => frappe.set_route("List", "IB Overtime Request", { status: ["in", ["Draft", "Pending Approval"]] }),
				() => frappe.set_route("List", "IB Full Final Settlement", { status: ["in", ["Draft", "In Review", "Approved"]] }),
				() => frappe.set_route("List", "Salary Slip", { "start_date,>=": m0 }),
			][idx] || null;
		}
		const key = ["all", "dispatch", "payment", "paid"][idx];
		if (!key) return null;
		return () => {
			this._docs_filter = key;
			this._docs_page = 0;
			this.$wrap.find(".ib-hub-docs-filter").removeClass("active");
			this.$wrap.find(`.ib-hub-docs-filter[data-filter="${key}"]`).addClass("active");
			this._docs_draw_order_table();
			const t = this.$wrap.find("#ib-hub-table-card")[0];
			if (t) t.scrollIntoView({ behavior: "smooth", block: "start" });
		};
	}

	_render_trend(trend) {
		const $el = this.$wrap.find("#ib-hub-trend")[0];
		if (!$el) return;

		const me_trend_titles = {
			sales: "My Revenue Over Time",
			hr: "Attendance Trend",
			production: "WOs Completed Over Time",
			finance: "Revenue Trend",
		};
		const titles = {
			me: me_trend_titles[this._me_usertype || "sales"] || "My Performance Over Time",
			sales: "Revenue Over Time",
			inventory: "Goods Received Over Time",
			production: "WOs Completed Over Time",
			hr: "Attendance Trend",
			finance: "Revenue Trend",
			procurement: "Spend Over Time",
			docs: "Chain Activity",
		};
		this.$wrap.find("#ib-hub-trend-title").text(titles[this._active_tab] || "Trend");

		if (!trend || !trend.length) {
			$($el).html(`
				<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-muted);font-size:13px">
					No trend data for this period
				</div>`);
			return;
		}

		if (this._chart) { try { this._chart.destroy(); } catch(e) {} this._chart = null; }
		$($el).empty();

		const colors = {
			me: "#d97757", sales: "#d97757", inventory: "#8b5cf6",
			production: "#10b981", hr: "#06b6d4", finance: "#f59e0b",
			procurement: "#f97316", docs: "#0ea5e9",
		};
		const isCurrency = ["me", "sales", "finance", "procurement"].includes(this._active_tab);
		const chartColor = colors[this._active_tab] || "#d97757";

		// Use bar for inventory/production, line for others
		const chartType = ["inventory", "production"].includes(this._active_tab) ? "bar" : "line";

		const initChart = () => {
			try {
				this._chart = new frappe.Chart($el, {
					type: chartType,
					data: {
						labels: trend.map(r => r.label),
						datasets: [{ name: "Value", values: trend.map(r => parseFloat(r.amount || 0)) }],
					},
					colors: [chartColor],
					height: 200,
					lineOptions: chartType === "line" ? { regionFill: 1, spline: 1 } : {},
					axisOptions: { xIsSeries: 1, shortenYAxisNumbers: 1 },
					tooltipOptions: isCurrency
						? { formatTooltipY: (v) => "₹" + Number(v).toLocaleString("en-IN", { maximumFractionDigits: 0 }) }
						: {},
				});
			} catch (e) {
				$($el).html(`
					<div style="padding:20px;color:var(--text-muted);font-size:12px;text-align:center">
						Chart unavailable — ${trend.length} data points loaded
					</div>`);
			}
		};

		// RAF ensures DOM has settled before chart init
		requestAnimationFrame(() => requestAnimationFrame(initChart));
	}

	_render_breakdown(rows) {
		const me_break_titles = {
			sales: "My Top Customers (MTD)",
			hr: "Headcount by Department",
			production: "Active WOs by Stage",
			finance: "Overdue AR by Customer",
		};
		const titles = this._scoped ? {
			sales: "My Top Customers (MTD)",
			inventory: "Stock Status (In/Out)",
			production: "My Orders — Production Progress",
			hr: "My Leave Balance",
			finance: "My Overdue AR by Customer",
			procurement: "Open POs by Status",
			docs: "Requests by Type",
		} : {
			me: me_break_titles[this._me_usertype || "sales"] || "My Top Customers (MTD)",
			sales: "Top Customers (MTD)",
			inventory: "Current Stock by Warehouse",
			production: "Active WOs by Stage",
			hr: "Headcount by Department",
			finance: "Overdue AR by Customer",
			procurement: "Spend by Vendor",
			docs: "Requests by Type",
		};
		this.$wrap.find("#ib-hub-break-title").text(titles[this._active_tab] || "Breakdown");

		if (!rows.length) {
			this.$wrap.find("#ib-hub-breakdown").html(
				`<div style="padding:30px;text-align:center;color:var(--text-muted);font-size:12px">No data</div>`
			);
			return;
		}

		// Scoped inventory view: rows carry a green/red status flag instead of
		// a numeric amount — no real stock figures for non-privileged users,
		// so render a status-dot list instead of proportional bars.
		if (rows[0].status !== undefined) {
			this.$wrap.find("#ib-hub-breakdown").html(rows.map(r => {
				const color = r.status === "green" ? "#16a34a" : "#dc2626";
				return `<div class="ib-hub-bar-row" style="align-items:center">
					<span style="display:inline-block;width:8px;height:8px;border-radius:50%;
						background:${color};margin-right:8px;flex-shrink:0"></span>
					<div class="ib-hub-bar-lbl" style="flex:1" title="${frappe.utils.escape_html(r.label || "")}">${frappe.utils.escape_html(r.label || "")}</div>
					<div class="ib-hub-bar-val" style="color:${color};font-weight:600">${r.status === "green" ? "In Stock" : "Out of Stock"}</div>
				</div>`;
			}).join(""));
			return;
		}

		// Procurement's breakdown is currency (spend by vendor) when privileged,
		// but plain PO counts by status for the scoped fallback (no spend figures
		// for non-procurement roles) — can't key off tab name alone like the others.
		const isCurrency = (["me", "sales", "inventory", "finance"].includes(this._active_tab)
			&& !["hr", "production"].includes(this._active_tab))
			|| (this._active_tab === "procurement" && !this._scoped);
		const fmt = isCurrency
			? (v) => "₹" + Number(v).toLocaleString("en-IN", { maximumFractionDigits: 0 })
			: (v) => Number(v).toLocaleString("en-IN");

		const max_val = Math.max(...rows.map(r => parseFloat(r.amount || 0)));

		this.$wrap.find("#ib-hub-breakdown").html(rows.map(r => {
			const pct = max_val ? Math.round(parseFloat(r.amount || 0) / max_val * 100) : 0;
			return `<div class="ib-hub-bar-row">
				<div class="ib-hub-bar-lbl" title="${frappe.utils.escape_html(r.label || "")}">${frappe.utils.escape_html(r.label || "")}</div>
				<div class="ib-hub-bar-track">
					<div class="ib-hub-bar-fill" style="width:0%" data-pct="${pct}"></div>
				</div>
				<div class="ib-hub-bar-val">${fmt(r.amount)}</div>
			</div>`;
		}).join(""));

		// Animate bars
		requestAnimationFrame(() => {
			this.$wrap.find(".ib-hub-bar-fill").each(function () {
				$(this).css("width", $(this).data("pct") + "%");
			});
		});
	}

	_render_table(d) {
		if (this._active_tab === "me") {
			this._render_me_section(d);
		} else if (this._active_tab === "sales" && (d.secondary || []).length) {
			const rows = d.secondary;
			this.$wrap.find("#ib-hub-table-card").show();
			this.$wrap.find("#ib-hub-table-title").text("Revenue by Item Group");
			const fmt = (v) => "₹" + Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 });
			const total = rows.reduce((s, r) => s + parseFloat(r.amount || 0), 0);
			this.$wrap.find("#ib-hub-table").html(`
				<table class="ib-hub-table">
					<thead><tr><th>Item Group</th><th>Revenue</th><th>Share</th><th></th></tr></thead>
					<tbody>${rows.map(r => `
						<tr>
							<td>${frappe.utils.escape_html(r.label || "")}</td>
							<td>${fmt(r.amount)}</td>
							<td>
								<span style="background:var(--bg-color);border:1px solid var(--border-color);
								border-radius:4px;padding:2px 7px;font-size:11px;font-weight:600">
									${total ? Math.round(parseFloat(r.amount || 0) / total * 100) : 0}%
								</span>
							</td>
							<td class="ib-hub-itemgroup-link" data-group="${frappe.utils.escape_html(r.label || "")}" style="cursor:pointer;font-size:11px;color:var(--ib-primary)">Items →</td>
						</tr>
					`).join("")}</tbody>
				</table>
			`);
			this.$wrap.find(".ib-hub-itemgroup-link").off("click").on("click", (e) => {
				frappe.route_options = { item_group: $(e.currentTarget).data("group") };
				frappe.set_route("List", "Item");
			});
		} else if (this._active_tab === "inventory" && (d.recent || []).length) {
			this.$wrap.find("#ib-hub-table-card").show();
			this.$wrap.find("#ib-hub-table-title").text("Recent Stock Movements");
			this.$wrap.find("#ib-hub-table").html(`
				<table class="ib-hub-table">
					<thead><tr><th>Item</th><th>Warehouse</th><th>Qty After</th><th>Type</th><th>Date</th><th></th></tr></thead>
					<tbody>${(d.recent || []).map(r => `
						<tr>
							<td style="font-weight:500">${frappe.utils.escape_html(r.item_code || "")}</td>
							<td>${frappe.utils.escape_html((r.warehouse || "").replace(" - IB",""))}</td>
							<td style="text-align:right">${Number(r.qty || 0).toFixed(2)}</td>
							<td>${frappe.utils.escape_html(r.voucher_type || "")}</td>
							<td>${frappe.datetime.str_to_user(r.posting_date) || r.posting_date}</td>
							<td><a href="/app/item/${encodeURIComponent(r.item_code || "")}" style="font-size:11px;color:var(--ib-primary)">View →</a></td>
						</tr>
					`).join("")}</tbody>
				</table>
			`);
		} else if (this._active_tab === "docs") {
			const meta = d.meta || {};
			const chain = ((d.pending || {}).chain) || [];
			this.$wrap.find("#ib-hub-table-card").show();
			if (meta.chain_type === "hr") {
				this._render_docs_hr_table(chain);
			} else {
				this._render_docs_order_table(chain, meta);
			}
		} else {
			this.$wrap.find("#ib-hub-table-card").hide();
		}
	}

	// ── Docs tab shared toolbar (search / status filter / pager) ─────────────
	_docs_badge(label, cls) { return `<span class="ib-hub-chain-badge ${cls}">${frappe.utils.escape_html(label)}</span>`; }

	_docs_toolbar_html(filters, sales_persons) {
		const chips = filters.map(f => `
			<div class="ib-hub-docs-filter${this._docs_filter === f.key ? " active" : ""}" data-filter="${f.key}">${f.label}</div>
		`).join("");
		const sp_select = (sales_persons && sales_persons.length) ? `
			<select class="ib-hub-docs-search" id="ib-hub-docs-sp" style="flex:0 0 160px;min-width:120px">
				<option value="">${__("All Sales Persons")}</option>
				${sales_persons.map(sp => `<option value="${frappe.utils.escape_html(sp)}" ${this._docs_sp === sp ? "selected" : ""}>${frappe.utils.escape_html(sp)}</option>`).join("")}
			</select>` : "";
		return `
			<div class="ib-hub-docs-toolbar">
				<input type="text" class="ib-hub-docs-search" id="ib-hub-docs-search"
					placeholder="${__("Search…")}" value="${frappe.utils.escape_html(this._docs_search || "")}">
				${sp_select}
				${chips}
				<span class="ib-hub-docs-count" id="ib-hub-docs-count"></span>
			</div>
			<div id="ib-hub-docs-body"></div>
			<div class="ib-hub-docs-pager" id="ib-hub-docs-pager"></div>
		`;
	}

	_docs_bind_toolbar(on_change) {
		this.$wrap.find("#ib-hub-docs-search").off("input").on("input", (e) => {
			this._docs_search = e.currentTarget.value;
			this._docs_page = 0;
			on_change();
		});
		this.$wrap.find("#ib-hub-docs-sp").off("change").on("change", (e) => {
			this._docs_sp = e.currentTarget.value;
			this._docs_page = 0;
			on_change();
		});
		this.$wrap.find(".ib-hub-docs-filter").off("click").on("click", (e) => {
			this._docs_filter = $(e.currentTarget).data("filter");
			this._docs_page = 0;
			this.$wrap.find(".ib-hub-docs-filter").removeClass("active");
			$(e.currentTarget).addClass("active");
			on_change();
		});
	}

	_docs_render_pager(total) {
		const pages = Math.max(1, Math.ceil(total / this._docs_page_size));
		if (this._docs_page >= pages) this._docs_page = pages - 1;
		const $pager = this.$wrap.find("#ib-hub-docs-pager");
		if (pages <= 1) { $pager.empty(); return; }
		$pager.html(`
			<button id="ib-hub-docs-prev" ${this._docs_page === 0 ? "disabled" : ""}>← Prev</button>
			<span>Page ${this._docs_page + 1} of ${pages}</span>
			<button id="ib-hub-docs-next" ${this._docs_page >= pages - 1 ? "disabled" : ""}>Next →</button>
		`);
	}

	// ── Docs tab: order-chain (Q→SO→DN→SI→Payment→Production→AR) ────────────
	_render_docs_order_table(chain, meta) {
		this.$wrap.find("#ib-hub-table-title").text("Order Chain");
		this._docs_order_chain = chain;
		this._docs_sales_persons = (meta || {}).sales_persons || [];

		if (!chain.length) {
			this.$wrap.find("#ib-hub-table").html(
				`<div class="ib-hub-docs-empty"><iconify-icon icon="lucide:inbox" width="22" height="22"></iconify-icon><div>No orders to track yet.</div></div>`
			);
			return;
		}

		const filters = [
			{ key: "all", label: "All" },
			{ key: "dispatch", label: "Awaiting Dispatch" },
			{ key: "payment", label: "Awaiting Payment" },
			{ key: "paid", label: "Fully Paid" },
			{ key: "risk", label: "At Risk" },
		];
		this.$wrap.find("#ib-hub-table").html(this._docs_toolbar_html(filters, this._docs_sales_persons));
		this._docs_bind_toolbar(() => this._docs_draw_order_table());
		this.$wrap.find("#ib-hub-docs-pager").off("click", "button").on("click", "button", (e) => {
			this._docs_page += e.currentTarget.id === "ib-hub-docs-next" ? 1 : -1;
			this._docs_draw_order_table();
		});
		this._docs_draw_order_table();
	}

	_docs_stage_of(r) {
		if (r.dn_status !== "Dispatched") return "dispatch";
		if (r.si_status !== "Invoiced") return "payment";
		if (r.payment_status !== "Paid") return "payment";
		return "paid";
	}

	_docs_draw_order_table() {
		const fmt = (v) => "₹" + Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 });
		const badge = (l, c) => this._docs_badge(l, c);
		// Only badges backed by a real, unambiguous document (one Quotation
		// per SO; latest DN/SI when one exists) are clickable — a badge with
		// no doc behind it (Not Created/Not Dispatched) stays plain text so it
		// never looks like a dead link.
		const link_badge = (l, c, doctype, name) => name
			? `<a href="/app/${frappe.router.slug(doctype)}/${encodeURIComponent(name)}" target="_blank" class="ib-hub-chain-badge ib-hub-chain-badge-link ${c}" title="${__("Open {0}", [name])}">${frappe.utils.escape_html(l)}</a>`
			: badge(l, c);
		const arrow = `<span class="ib-hub-chain-arrow">→</span>`;
		const q_badge = (r) => r.quotation ? link_badge("Quoted", "done", "Quotation", r.quotation) : badge("No Quote", "none");
		const dn_badge = (r) => r.dn_status === "Dispatched" ? link_badge("Dispatched", "done", "Delivery Note", r.dn_name)
			: r.dn_status === "Pending" ? link_badge("DN Pending", "pending", "Delivery Note", r.dn_name)
			: badge("Not Dispatched", "none");
		const si_badge = (r) => r.si_status === "Invoiced" ? link_badge("Invoiced", "done", "Sales Invoice", r.si_name)
			: r.si_status === "Pending" ? link_badge("SI Pending", "pending", "Sales Invoice", r.si_name)
			: badge("Not Invoiced", "none");
		const pay_badge = (r) => r.payment_status === "Paid" ? badge("Paid", "done")
			: r.payment_status === "Partial" ? badge("Partial", "pending")
			: badge("Unpaid", "risk");
		const prod_badge = (r) => {
			if (!r.production_stage) return badge("No Production", "none");
			const cls = r.risk === "overdue" ? "risk" : r.risk === "at-risk" ? "pending" : "done";
			return badge(`${r.production_stage} (${r.production_pct || 0}%)`, cls);
		};

		const q = (this._docs_search || "").trim().toLowerCase();
		let rows = this._docs_order_chain.filter(r => {
			if (q && !`${r.sales_order} ${r.customer} ${r.quotation || ""}`.toLowerCase().includes(q)) return false;
			if (this._docs_sp && r.sales_person !== this._docs_sp) return false;
			if (this._docs_filter === "risk") return r.risk === "overdue" || r.risk === "at-risk";
			if (this._docs_filter !== "all") return this._docs_stage_of(r) === this._docs_filter;
			return true;
		});

		this.$wrap.find("#ib-hub-docs-count").text(`${rows.length} order${rows.length === 1 ? "" : "s"}`);

		const start = this._docs_page * this._docs_page_size;
		const page_rows = rows.slice(start, start + this._docs_page_size);

		const $body = this.$wrap.find("#ib-hub-docs-body");
		if (!page_rows.length) {
			$body.html(`<div style="padding:30px;text-align:center;color:var(--text-muted);font-size:12px">No matching orders</div>`);
			this.$wrap.find("#ib-hub-docs-pager").empty();
			return;
		}

		$body.html(`
			<table class="ib-hub-table">
				<thead><tr>
					<th>Order</th><th>Customer</th><th>Chain</th><th>Outstanding</th><th></th>
				</tr></thead>
				<tbody>${page_rows.map(r => `
					<tr>
						<td>
							<div class="ib-hub-chain-link" data-so="${frappe.utils.escape_html(r.sales_order)}" style="font-weight:600;color:var(--ib-primary)">${frappe.utils.escape_html(r.sales_order)}</div>
							<div style="font-size:10px;color:var(--text-muted)">${r.date ? frappe.datetime.str_to_user(r.date) : ""} · ${fmt(r.grand_total)}</div>
						</td>
						<td>${frappe.utils.escape_html(r.customer || "")}</td>
						<td>
							<div class="ib-hub-chain-row">
								${q_badge(r)}
								${arrow}${dn_badge(r)}${arrow}${si_badge(r)}${arrow}${pay_badge(r)}${arrow}${prod_badge(r)}
							</div>
						</td>
						<td style="text-align:right;font-weight:600;${r.outstanding > 0 ? "color:#dc2626" : ""}">${r.outstanding > 0 ? fmt(r.outstanding) : "—"}</td>
						<td><a href="/app/sales-order/${encodeURIComponent(r.sales_order)}" style="font-size:11px;color:var(--ib-primary)">Open →</a></td>
					</tr>
				`).join("")}</tbody>
			</table>
		`);
		this.$wrap.find(".ib-hub-chain-link").off("click").on("click", (e) => {
			frappe.set_route("Form", "Sales Order", $(e.currentTarget).data("so"));
		});
		this._docs_render_pager(rows.length);
	}

	// ── Docs tab: HR request pipeline (Leave/Overtime/F&F/Salary Slip) ───────
	_render_docs_hr_table(chain) {
		this.$wrap.find("#ib-hub-table-title").text("HR Request Pipeline");
		this._docs_hr_chain = chain;

		if (!chain.length) {
			this.$wrap.find("#ib-hub-table").html(
				`<div style="padding:30px;text-align:center;color:var(--text-muted);font-size:12px">No pending requests</div>`
			);
			return;
		}

		const types = [...new Set(chain.map(r => r.doctype))];
		const filters = [{ key: "all", label: "All" }].concat(types.map(t => ({ key: t, label: t })));
		this.$wrap.find("#ib-hub-table").html(this._docs_toolbar_html(filters));
		this._docs_bind_toolbar(() => this._docs_draw_hr_table());
		this.$wrap.find("#ib-hub-docs-pager").off("click", "button").on("click", "button", (e) => {
			this._docs_page += e.currentTarget.id === "ib-hub-docs-next" ? 1 : -1;
			this._docs_draw_hr_table();
		});
		this._docs_draw_hr_table();
	}

	_docs_draw_hr_table() {
		const dt_route = { "Leave Application": "Leave Application", "Overtime Request": "IB Overtime Request",
			"Full & Final Settlement": "IB Full Final Settlement", "Salary Slip": "Salary Slip" };
		const status_cls = (s) => ["Approved","Paid","Submitted"].includes(s) ? "done"
			: ["Rejected"].includes(s) ? "risk" : "pending";

		const q = (this._docs_search || "").trim().toLowerCase();
		let rows = this._docs_hr_chain.filter(r => {
			if (q && !`${r.employee_name || ""} ${r.detail || ""}`.toLowerCase().includes(q)) return false;
			if (this._docs_filter !== "all") return r.doctype === this._docs_filter;
			return true;
		});

		this.$wrap.find("#ib-hub-docs-count").text(`${rows.length} request${rows.length === 1 ? "" : "s"}`);

		const start = this._docs_page * this._docs_page_size;
		const page_rows = rows.slice(start, start + this._docs_page_size);

		const $body = this.$wrap.find("#ib-hub-docs-body");
		if (!page_rows.length) {
			$body.html(`<div style="padding:30px;text-align:center;color:var(--text-muted);font-size:12px">No matching requests</div>`);
			this.$wrap.find("#ib-hub-docs-pager").empty();
			return;
		}

		$body.html(`
			<table class="ib-hub-table">
				<thead><tr><th>Employee</th><th>Request</th><th>Detail</th><th>Status</th><th></th></tr></thead>
				<tbody>${page_rows.map(r => `
					<tr>
						<td style="font-weight:500">${frappe.utils.escape_html(r.employee_name || "")}</td>
						<td>${frappe.utils.escape_html(r.doctype || "")}</td>
						<td>${frappe.utils.escape_html(r.detail || "")}</td>
						<td><span class="ib-hub-chain-badge ${status_cls(r.status)}">${frappe.utils.escape_html(r.status || "")}</span></td>
						<td><a href="/app/${encodeURIComponent((dt_route[r.doctype] || r.doctype).toLowerCase().replace(/ /g,"-"))}/${encodeURIComponent(r.name)}" style="font-size:11px;color:var(--ib-primary)">Open →</a></td>
					</tr>
				`).join("")}</tbody>
			</table>
		`);
		this._docs_render_pager(rows.length);
	}

	_render_me_section(d) {
		const meta = d.meta || {};
		const pending = d.pending || {};
		const user_type = meta.user_type || "sales";
		const fmt = (v) => "₹" + Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 });

		this.$wrap.find("#ib-hub-table-card").show();

		// Build banner depending on user type
		let banner_html = "";
		if (user_type === "sales") {
			// Commission breakdown banner — always show for sales users
			const inv_count = meta.invoice_count || 0;
			const orders_count = meta.orders_mtd || 0;
			const avg_inv = meta.avg_invoice || 0;
			const commission = (meta.commission_per_inv || 0) * inv_count;
			const per_inv = meta.commission_per_inv || 0;

			let target_block = "";
			if (meta.target) {
				const pct_num = meta.tgt_pct != null ? meta.tgt_pct : 0;
				const fill_color = pct_num >= 100 ? "#16a34a" : pct_num >= 75 ? "#d97757" : "#dc2626";
				const slab_badge = meta.slab
					? `<span class="ib-hub-me-slab">🎯 ${frappe.utils.escape_html(meta.slab)}</span>` : "";
				target_block = `
					<div>
						<div class="ib-hub-me-tgt-label">Target</div>
						<div class="ib-hub-me-tgt-val">${fmt(meta.target)}</div>
					</div>
					<div>
						<div class="ib-hub-me-tgt-label">Collected</div>
						<div class="ib-hub-me-tgt-val">${fmt(meta.collected)}</div>
					</div>
					<div style="min-width:140px">
						<div style="display:flex;justify-content:space-between;margin-bottom:4px">
							<span class="ib-hub-me-tgt-label">Achievement</span>
							<span class="ib-hub-me-tgt-pct" style="color:${fill_color}">${pct_num}%</span>
						</div>
						<div class="ib-hub-me-tgt-progress">
							<div class="ib-hub-me-tgt-fill" style="width:0%;background:${fill_color}" data-pct="${Math.min(pct_num, 100)}"></div>
						</div>
					</div>
					${slab_badge}`;
			}

			banner_html = `
				<div class="ib-hub-me-target">
					<div>
						<div class="ib-hub-me-tgt-label">Orders Done</div>
						<div class="ib-hub-me-tgt-val" style="color:#d97757">${orders_count}</div>
					</div>
					<div>
						<div class="ib-hub-me-tgt-label">Invoices Created</div>
						<div class="ib-hub-me-tgt-val" style="color:#d97757">${inv_count}</div>
					</div>
					<div>
						<div class="ib-hub-me-tgt-label">Avg Invoice</div>
						<div class="ib-hub-me-tgt-val">${fmt(avg_inv)}</div>
					</div>
					${target_block}
					<div style="border-left:1px solid var(--border-color);padding-left:16px">
						<div class="ib-hub-me-tgt-label">Commission (${inv_count} inv × ${fmt(per_inv)})</div>
						<div class="ib-hub-me-tgt-val" style="color:#16a34a">${fmt(commission)}</div>
					</div>
					<a href="#" class="btn btn-xs btn-default" onclick="frappe.set_route('ib-sales-incentives');return false">Incentives →</a>
				</div>`;
		}

		// Sub-tabs per user type
		const stab_configs = {
			sales: [
				{ key: "outstanding", label: "Customer Outstanding", count: (pending.outstanding || []).length },
				{ key: "orders",  label: "Open Orders",  count: (pending.orders || []).length },
				{ key: "quotes",  label: "Open Quotes",  count: (pending.quotes || []).length },
				{ key: "leads",   label: "Open Leads",   count: (pending.leads || []).length },
				{ key: "overdue", label: "Overdue SI",   count: (pending.overdue || []).length },
			],
			hr: [
				{ key: "leaves",  label: "Pending Leaves", count: (pending.leaves || []).length },
				{ key: "joiners", label: "New Joiners",    count: (pending.joiners || []).length },
				{ key: "exiting", label: "Exiting (30d)",  count: (pending.exiting || []).length },
				{ key: "absent",  label: "Absent Today",   count: (pending.absent || []).length },
			],
			production: [
				{ key: "active",  label: "Active WOs", count: (pending.active || []).length },
				{ key: "on_hold", label: "On Hold",    count: (pending.on_hold || []).length },
			],
			finance: [
				{ key: "overdue_si", label: "Overdue AR",    count: (pending.overdue_si || []).length },
				{ key: "overdue_pi", label: "Overdue AP",    count: (pending.overdue_pi || []).length },
				{ key: "payments",   label: "Payments MTD",  count: (pending.payments || []).length },
			],
		};

		const stabs = stab_configs[user_type] || stab_configs.sales;

		// Default to first stab if current stab not in this user_type
		if (!stabs.find(s => s.key === this._me_stab)) {
			this._me_stab = stabs[0]?.key || "leads";
		}

		const stabs_html = stabs.map(t => `
			<button class="ib-hub-me-stab${this._me_stab === t.key ? " active" : ""}" data-stab="${t.key}">
				${t.label}<span class="ib-hub-me-badge">${t.count}</span>
			</button>
		`).join("");

		const section_title = {
			sales: "My Pending Work",
			hr: "HR Action Items",
			production: "Production Queue",
			finance: "Finance Pending",
		}[user_type] || "My Pending Work";

		this.$wrap.find("#ib-hub-table-title").html(
			`<span>${section_title}</span><div class="ib-hub-me-stabs">${stabs_html}</div>`
		);
		this.$wrap.find("#ib-hub-table").html(banner_html + `<div id="ib-hub-me-stab-content"></div>`);

		requestAnimationFrame(() => {
			this.$wrap.find(".ib-hub-me-tgt-fill").each(function () {
				$(this).css("width", $(this).data("pct") + "%");
			});
		});

		this._me_pending  = pending;
		this._me_usertype = user_type;
		this._render_me_stab();

		this.$wrap.find(".ib-hub-me-stab").on("click", (e) => {
			this._me_stab = $(e.currentTarget).data("stab");
			this.$wrap.find(".ib-hub-me-stab").removeClass("active");
			$(e.currentTarget).addClass("active");
			this._render_me_stab();
		});
	}

	_render_me_stab() {
		const fmt   = (v) => "₹" + Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 });
		const badge = (txt, cls) => `<span style="background:var(--bg-color);border:1px solid var(--border-color);border-radius:10px;padding:2px 8px;font-size:10px;font-weight:600;${cls}">${frappe.utils.escape_html(txt || "")}</span>`;
		const link  = (url, label) => `<a href="${url}" style="font-size:11px;color:var(--ib-primary)">${label} →</a>`;
		const today = frappe.datetime.get_today();
		const pending = this._me_pending || {};
		const $el = this.$wrap.find("#ib-hub-me-stab-content");
		let html = "";

		const empty = (msg) => `<div style="padding:20px;text-align:center;color:var(--text-muted);font-size:12px">${msg}</div>`;

		// ── SALES stabs ─────────────────────────────────────────────────────────
		if (this._me_stab === "outstanding") {
			const rows = pending.outstanding || [];
			html = !rows.length ? empty("No outstanding amounts — all collected!") : `<table class="ib-hub-table">
				<thead><tr>
					<th>Customer</th>
					<th style="text-align:right">Invoices</th>
					<th style="text-align:right">Total Invoiced</th>
					<th style="text-align:right">Collected</th>
					<th style="text-align:right">Outstanding</th>
					<th style="text-align:right">Collection %</th>
					<th></th>
				</tr></thead>
				<tbody>${rows.map(r => {
					const pct = parseFloat(r.collection_pct || 0);
					const pct_color = pct >= 80 ? "#16a34a" : pct >= 50 ? "#d97757" : "#dc2626";
					const out_color = parseFloat(r.outstanding || 0) > 0 ? "#dc2626" : "inherit";
					return `<tr>
						<td style="font-weight:500">${frappe.utils.escape_html(r.customer || "")}</td>
						<td style="text-align:right">${r.invoice_count || 0}</td>
						<td style="text-align:right">${fmt(r.total_invoiced)}</td>
						<td style="text-align:right;color:#16a34a">${fmt(r.total_collected)}</td>
						<td style="text-align:right;font-weight:700;color:${out_color}">${fmt(r.outstanding)}</td>
						<td style="text-align:right">
							<span style="background:${pct >= 80 ? "#d1fae5" : pct >= 50 ? "#fef3c7" : "#fee2e2"};
								color:${pct_color};border-radius:10px;padding:2px 8px;font-size:10px;font-weight:700">
								${pct}%
							</span>
						</td>
						<td class="ib-hub-outstanding-link" data-customer="${frappe.utils.escape_html(r.customer || "")}" style="cursor:pointer;font-size:11px;color:var(--ib-primary)">Invoices →</td>
					</tr>`;
				}).join("")}</tbody>
			</table>`;

		} else if (this._me_stab === "leads") {
			const rows = pending.leads || [];
			html = !rows.length ? empty("No open leads") : `<table class="ib-hub-table">
				<thead><tr><th>Lead Name</th><th>Status</th><th>Next Follow-up</th><th>Created</th><th></th></tr></thead>
				<tbody>${rows.map(r => {
					const od = r.next_date && r.next_date < today ? "color:#dc2626;font-weight:600" : "";
					return `<tr>
						<td style="font-weight:500">${frappe.utils.escape_html(r.lead_name || r.name || "")}</td>
						<td>${badge(r.status || "Open", "")}</td>
						<td style="${od}">${r.next_date ? frappe.datetime.str_to_user(r.next_date) : "—"}</td>
						<td>${r.created ? frappe.datetime.str_to_user(r.created) : "—"}</td>
						<td>${link("/app/lead/" + frappe.utils.escape_html(r.name), "Open")}</td>
					</tr>`;
				}).join("")}</tbody>
			</table>`;

		} else if (this._me_stab === "quotes") {
			const rows = pending.quotes || [];
			html = !rows.length ? empty("No open quotations") : `<table class="ib-hub-table">
				<thead><tr><th>Quotation</th><th>Customer</th><th>Value</th><th>Status</th><th>Valid Till</th><th></th></tr></thead>
				<tbody>${rows.map(r => {
					const exp = r.valid_till && r.valid_till <= today ? "color:#dc2626" : "";
					return `<tr>
						<td style="font-weight:500">${frappe.utils.escape_html(r.name || "")}</td>
						<td>${frappe.utils.escape_html(r.customer || "")}</td>
						<td>${fmt(r.grand_total)}</td>
						<td>${badge(r.status || "", "")}</td>
						<td style="${exp}">${r.valid_till ? frappe.datetime.str_to_user(r.valid_till) : "—"}</td>
						<td>${link("/app/quotation/" + frappe.utils.escape_html(r.name), "Open")}</td>
					</tr>`;
				}).join("")}</tbody>
			</table>`;

		} else if (this._me_stab === "orders") {
			const rows = pending.orders || [];
			html = !rows.length ? empty("No open sales orders") : `<table class="ib-hub-table">
				<thead><tr><th>Order</th><th>Customer</th><th>Value</th><th>Advance Paid</th><th>Status</th><th>Date</th><th></th></tr></thead>
				<tbody>${rows.map(r => {
					const adv = parseFloat(r.advance_paid || 0);
					return `<tr>
						<td style="font-weight:500">${frappe.utils.escape_html(r.name || "")}</td>
						<td>${frappe.utils.escape_html(r.customer || "")}</td>
						<td>${fmt(r.grand_total)}</td>
						<td style="${adv > 0 ? "color:#16a34a;font-weight:600" : "color:var(--text-muted)"}">${adv > 0 ? fmt(adv) : "—"}</td>
						<td>${badge(r.status || "", "")}</td>
						<td>${r.transaction_date ? frappe.datetime.str_to_user(r.transaction_date) : "—"}</td>
						<td>${link("/app/sales-order/" + frappe.utils.escape_html(r.name), "Open")}</td>
					</tr>`;
				}).join("")}</tbody>
			</table>`;

		} else if (this._me_stab === "overdue") {
			const rows = pending.overdue || [];
			html = !rows.length ? empty("No overdue invoices 🎉") : `<table class="ib-hub-table">
				<thead><tr><th>Invoice</th><th>Customer</th><th>Outstanding</th><th>Due Date</th><th>Days</th><th></th></tr></thead>
				<tbody>${rows.map(r => `<tr>
					<td style="font-weight:500">${frappe.utils.escape_html(r.name || "")}</td>
					<td>${frappe.utils.escape_html(r.customer || "")}</td>
					<td style="color:#dc2626;font-weight:600">${fmt(r.outstanding_amount)}</td>
					<td style="color:#dc2626">${r.due_date ? frappe.datetime.str_to_user(r.due_date) : "—"}</td>
					<td><span style="background:#fee2e2;color:#991b1b;border-radius:10px;padding:2px 8px;font-size:10px;font-weight:700">${r.days_overdue || 0}d</span></td>
					<td>${link("/app/sales-invoice/" + frappe.utils.escape_html(r.name), "Open")}</td>
				</tr>`).join("")}</tbody>
			</table>`;

		// ── HR stabs ─────────────────────────────────────────────────────────────
		} else if (this._me_stab === "leaves") {
			const rows = pending.leaves || [];
			html = !rows.length ? empty("No pending leave applications") : `<table class="ib-hub-table">
				<thead><tr><th>Employee</th><th>Leave Type</th><th>From</th><th>To</th><th>Days</th><th></th></tr></thead>
				<tbody>${rows.map(r => `<tr>
					<td style="font-weight:500">${frappe.utils.escape_html(r.employee_name || "")}</td>
					<td>${frappe.utils.escape_html(r.leave_type || "")}</td>
					<td>${r.from_date ? frappe.datetime.str_to_user(r.from_date) : "—"}</td>
					<td>${r.to_date ? frappe.datetime.str_to_user(r.to_date) : "—"}</td>
					<td>${r.total_leave_days || ""}</td>
					<td>${link("/app/leave-application/" + frappe.utils.escape_html(r.name), "Review")}</td>
				</tr>`).join("")}</tbody>
			</table>`;

		} else if (this._me_stab === "joiners") {
			const rows = pending.joiners || [];
			html = !rows.length ? empty("No new joiners this month") : `<table class="ib-hub-table">
				<thead><tr><th>Employee</th><th>Designation</th><th>Department</th><th>Joining Date</th><th></th></tr></thead>
				<tbody>${rows.map(r => `<tr>
					<td style="font-weight:500">${frappe.utils.escape_html(r.employee_name || "")}</td>
					<td>${frappe.utils.escape_html(r.designation || "")}</td>
					<td>${frappe.utils.escape_html(r.department || "")}</td>
					<td>${r.date_of_joining ? frappe.datetime.str_to_user(r.date_of_joining) : "—"}</td>
					<td>${link("/app/employee/" + frappe.utils.escape_html(r.name), "View")}</td>
				</tr>`).join("")}</tbody>
			</table>`;

		} else if (this._me_stab === "exiting") {
			const rows = pending.exiting || [];
			html = !rows.length ? empty("No employees exiting in next 30 days") : `<table class="ib-hub-table">
				<thead><tr><th>Employee</th><th>Designation</th><th>Department</th><th>Relieving Date</th><th></th></tr></thead>
				<tbody>${rows.map(r => `<tr>
					<td style="font-weight:500">${frappe.utils.escape_html(r.employee_name || "")}</td>
					<td>${frappe.utils.escape_html(r.designation || "")}</td>
					<td>${frappe.utils.escape_html(r.department || "")}</td>
					<td style="color:#dc2626;font-weight:600">${r.relieving_date ? frappe.datetime.str_to_user(r.relieving_date) : "—"}</td>
					<td>${link("/app/employee/" + frappe.utils.escape_html(r.name), "View")}</td>
				</tr>`).join("")}</tbody>
			</table>`;

		} else if (this._me_stab === "absent") {
			const rows = pending.absent || [];
			html = !rows.length ? empty("No absences today") : `<table class="ib-hub-table">
				<thead><tr><th>Employee</th><th>Name</th><th>Department</th><th></th></tr></thead>
				<tbody>${rows.map(r => `<tr>
					<td style="font-weight:500">${frappe.utils.escape_html(r.employee || "")}</td>
					<td>${frappe.utils.escape_html(r.employee_name || "")}</td>
					<td>${frappe.utils.escape_html(r.department || "")}</td>
					<td>${link("/app/employee/" + frappe.utils.escape_html(r.employee), "View")}</td>
				</tr>`).join("")}</tbody>
			</table>`;

		// ── PRODUCTION stabs ──────────────────────────────────────────────────────
		} else if (this._me_stab === "active") {
			const rows = pending.active || [];
			html = !rows.length ? empty("No active work orders") : `<table class="ib-hub-table">
				<thead><tr><th>WO</th><th>Item</th><th>Stage</th><th>Priority</th><th>Target</th><th>Done</th><th></th></tr></thead>
				<tbody>${rows.map(r => `<tr>
					<td style="font-weight:500">${frappe.utils.escape_html(r.name || "")}</td>
					<td>${frappe.utils.escape_html(r.item_code || "")}</td>
					<td>${badge(r.stage || "—", "")}</td>
					<td>${badge(r.priority || "—", r.priority === "High" ? "background:#fee2e2;color:#991b1b" : "")}</td>
					<td>${Number(r.target_qty || 0).toLocaleString()}</td>
					<td>${Number(r.completed_qty || 0).toLocaleString()}</td>
					<td>${link("/app/ib-work-order/" + frappe.utils.escape_html(r.name), "Open")}</td>
				</tr>`).join("")}</tbody>
			</table>`;

		} else if (this._me_stab === "on_hold") {
			const rows = pending.on_hold || [];
			html = !rows.length ? empty("No work orders on hold") : `<table class="ib-hub-table">
				<thead><tr><th>WO</th><th>Item</th><th>Stage</th><th>Priority</th><th>Machine</th><th></th></tr></thead>
				<tbody>${rows.map(r => `<tr>
					<td style="font-weight:500">${frappe.utils.escape_html(r.name || "")}</td>
					<td>${frappe.utils.escape_html(r.item_code || "")}</td>
					<td>${badge(r.stage || "—", "")}</td>
					<td>${badge(r.priority || "—", "")}</td>
					<td>${frappe.utils.escape_html(r.machine || "—")}</td>
					<td>${link("/app/ib-work-order/" + frappe.utils.escape_html(r.name), "Open")}</td>
				</tr>`).join("")}</tbody>
			</table>`;

		// ── FINANCE stabs ─────────────────────────────────────────────────────────
		} else if (this._me_stab === "overdue_si") {
			const rows = pending.overdue_si || [];
			html = !rows.length ? empty("No overdue customer invoices 🎉") : `<table class="ib-hub-table">
				<thead><tr><th>Invoice</th><th>Customer</th><th>Outstanding</th><th>Due Date</th><th>Days</th><th></th></tr></thead>
				<tbody>${rows.map(r => `<tr>
					<td style="font-weight:500">${frappe.utils.escape_html(r.name || "")}</td>
					<td>${frappe.utils.escape_html(r.customer || "")}</td>
					<td style="color:#dc2626;font-weight:600">${fmt(r.outstanding_amount)}</td>
					<td style="color:#dc2626">${r.due_date ? frappe.datetime.str_to_user(r.due_date) : "—"}</td>
					<td><span style="background:#fee2e2;color:#991b1b;border-radius:10px;padding:2px 8px;font-size:10px;font-weight:700">${r.days_overdue || 0}d</span></td>
					<td>${link("/app/sales-invoice/" + frappe.utils.escape_html(r.name), "Open")}</td>
				</tr>`).join("")}</tbody>
			</table>`;

		} else if (this._me_stab === "overdue_pi") {
			const rows = pending.overdue_pi || [];
			html = !rows.length ? empty("No overdue supplier invoices") : `<table class="ib-hub-table">
				<thead><tr><th>PI</th><th>Supplier</th><th>Outstanding</th><th>Due Date</th><th>Days</th><th></th></tr></thead>
				<tbody>${rows.map(r => `<tr>
					<td style="font-weight:500">${frappe.utils.escape_html(r.name || "")}</td>
					<td>${frappe.utils.escape_html(r.supplier || "")}</td>
					<td style="color:#dc2626;font-weight:600">${fmt(r.outstanding_amount)}</td>
					<td style="color:#dc2626">${r.due_date ? frappe.datetime.str_to_user(r.due_date) : "—"}</td>
					<td><span style="background:#fee2e2;color:#991b1b;border-radius:10px;padding:2px 8px;font-size:10px;font-weight:700">${r.days_overdue || 0}d</span></td>
					<td>${link("/app/purchase-invoice/" + frappe.utils.escape_html(r.name), "Open")}</td>
				</tr>`).join("")}</tbody>
			</table>`;

		} else if (this._me_stab === "payments") {
			const rows = pending.payments || [];
			html = !rows.length ? empty("No payment entries this month") : `<table class="ib-hub-table">
				<thead><tr><th>PE</th><th>Type</th><th>Party</th><th>Amount</th><th>Ref</th><th>Date</th><th></th></tr></thead>
				<tbody>${rows.map(r => `<tr>
					<td style="font-weight:500">${frappe.utils.escape_html(r.name || "")}</td>
					<td>${badge(r.payment_type || "", r.payment_type === "Receive" ? "background:#d1fae5;color:#065f46" : "background:#fef3c7;color:#92400e")}</td>
					<td>${frappe.utils.escape_html(r.party || "")}</td>
					<td style="font-weight:600">${fmt(r.paid_amount)}</td>
					<td style="font-size:11px;color:var(--text-muted)">${frappe.utils.escape_html(r.reference_no || "—")}</td>
					<td>${r.posting_date ? frappe.datetime.str_to_user(r.posting_date) : "—"}</td>
					<td>${link("/app/payment-entry/" + frappe.utils.escape_html(r.name), "Open")}</td>
				</tr>`).join("")}</tbody>
			</table>`;
		}

		$el.html(html);
		$el.off("click", ".ib-hub-outstanding-link").on("click", ".ib-hub-outstanding-link", (e) => {
			frappe.route_options = { customer_name: $(e.currentTarget).data("customer"), outstanding_amount: [">", 0] };
			frappe.set_route("List", "Sales Invoice");
		});
	}

	// ── CSV Export ────────────────────────────────────────────────────────────
	_export_csv() {
		const key = `${this._active_tab}_${this._period}`;
		const d = this._cache[key];
		if (!d) { frappe.show_alert({ message: "Load data first", indicator: "orange" }); return; }
		const breakdown = d.breakdown || [];
		if (!breakdown.length) { frappe.show_alert({ message: "No data to export", indicator: "orange" }); return; }
		const rows = [["Label", "Value"], ...breakdown.map(r => [r.label, r.amount])];
		const csv = rows.map(r => r.map(v => `"${String(v).replace(/"/g,'""')}"`).join(",")).join("\n");
		const blob = new Blob([csv], { type: "text/csv" });
		const url = URL.createObjectURL(blob);
		const a = document.createElement("a");
		a.href = url;
		a.download = `ib_analytics_${this._active_tab}_${frappe.datetime.get_today()}.csv`;
		a.click();
		URL.revokeObjectURL(url);
	}
}
