frappe.pages["ib-sales-incentives"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({ parent: wrapper, title: "Sales Incentives", single_column: true });
	wrapper._ib_si = new IBSalesIncentives(wrapper);
};

frappe.pages["ib-sales-incentives"].on_page_show = function (wrapper) {
	if (wrapper._ib_si) wrapper._ib_si.load();
};

const ALL_REPS = "__all__";

class IBSalesIncentives {
	constructor(wrapper) {
		this.$wrap = $(wrapper).find(".layout-main-section");
		this._month = frappe.datetime.get_today().slice(0, 7) + "-01";
		this._is_manager = frappe.user.has_role("Sales Manager") || frappe.user.has_role("System Manager");
		this._me = frappe.session.user;
		// Incentive calc only ever runs once something is chosen — managers pick
		// either one rep (separately) or "All Sales Reps" (collectively) from the
		// dropdown, starting blank; non-managers are locked to themselves.
		this._sales_person = this._is_manager ? null : this._me;
		this._inject_styles();
		this._build_layout();
	}

	_inject_styles() {
		if (document.getElementById("ib-si-css")) return;
		const s = document.createElement("style");
		s.id = "ib-si-css";
		s.textContent = `
/* ── tokens ── */
.ib-si { --p:#d97757; --p-light:#fff4ef; --p-mid:#f5c4a8;
  --g:#10b981; --g-light:#d1fae5; --r:#ef4444; --r-light:#fee2e2;
  --y:#f59e0b; --y-light:#fef3c7;
  --ink:#111827; --ink2:#374151; --muted:#6b7280; --border:#e5e7eb;
  --bg:#f9fafb; --card:#ffffff; --radius:10px; }

/* ── page shell ── */
.ib-si { padding:20px; max-width:1220px; font-size:13px; color:var(--ink); }

/* ── header ── */
.ib-si-header { display:flex; align-items:center; gap:10px; margin-bottom:20px; flex-wrap:wrap; }
.ib-si-title { font-size:1.15rem; font-weight:700; color:var(--ink); margin:0; flex:1; min-width:160px; }
.ib-si-month { padding:5px 10px; border:1px solid var(--border); border-radius:7px;
  font-size:12px; background:var(--card); color:var(--ink); cursor:pointer; }
.ib-si-month:focus { outline:none; border-color:var(--p); }
.ib-si-action-group { display:flex; gap:6px; }
.ib-si-pill-btn { display:inline-flex; align-items:center; gap:5px; padding:5px 12px;
  border:1px solid var(--border); border-radius:20px; font-size:11.5px; font-weight:500;
  background:var(--card); color:var(--muted); cursor:pointer; transition:all .14s; white-space:nowrap; }
.ib-si-pill-btn:hover { border-color:var(--p); color:var(--p); background:var(--p-light); }
.ib-si-pill-btn.primary { background:var(--p); color:#fff; border-color:var(--p); }
.ib-si-pill-btn.primary:hover { background:#c4693f; border-color:#c4693f; }
.ib-si-pill-btn svg { width:12px; height:12px; }

/* ── KPI bar ── */
.ib-si-kpis { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:18px; }
@media(max-width:900px){ .ib-si-kpis { grid-template-columns:1fr 1fr; } }
.ib-si-kpi { background:var(--card); border:1px solid var(--border); border-radius:var(--radius);
  padding:14px 16px; position:relative; overflow:hidden; }
.ib-si-kpi::before { content:''; position:absolute; top:0; left:0; width:3px; height:100%;
  background:var(--border); border-radius:2px 0 0 2px; }
.ib-si-kpi.c-rev::before  { background:var(--p); }
.ib-si-kpi.c-col::before  { background:var(--g); }
.ib-si-kpi.c-tgt::before  { background:var(--y); }
.ib-si-kpi.c-com::before  { background:#8b5cf6; }
.ib-si-kpi-label { font-size:10.5px; font-weight:600; color:var(--muted); text-transform:uppercase;
  letter-spacing:.06em; margin-bottom:6px; }
.ib-si-kpi-value { font-size:1.35rem; font-weight:700; color:var(--ink); line-height:1.2; }
.ib-si-kpi-sub { margin-top:6px; }
.ib-si-prog-track { width:100%; height:5px; background:var(--bg); border-radius:3px; }
.ib-si-prog-fill  { height:5px; border-radius:3px; transition:width .5s; }
.ib-si-prog-label { font-size:10px; color:var(--muted); margin-top:3px; }

/* ── main grid ── */
.ib-si-grid { display:grid; grid-template-columns:1fr 1.5fr; gap:14px; }
@media(max-width:860px){ .ib-si-grid { grid-template-columns:1fr; } }
.ib-si-card { background:var(--card); border:1px solid var(--border); border-radius:var(--radius); overflow:hidden; }
.ib-si-card-hdr { display:flex; align-items:center; justify-content:space-between;
  padding:12px 16px; border-bottom:1px solid var(--border); }
.ib-si-card-hdr-title { font-size:12.5px; font-weight:600; color:var(--ink); }
.ib-si-card-body { padding:14px 16px; }
.ib-si-chart-wrap { height:190px; }

/* ── leaderboard ── */
.ib-si-lb { width:100%; border-collapse:collapse; }
.ib-si-lb th { font-size:10.5px; font-weight:600; color:var(--muted); text-transform:uppercase;
  letter-spacing:.05em; padding:8px 10px; border-bottom:1px solid var(--border);
  white-space:nowrap; }
.ib-si-lb th:not(:first-child) { text-align:right; }
.ib-si-lb th:nth-child(2) { text-align:left; }
.ib-si-lb td { padding:10px; border-bottom:1px solid #f3f4f6; vertical-align:middle; }
.ib-si-lb tr:last-child td { border-bottom:none; }
.ib-si-lb tr:hover td { background:#fafafa; }

/* team section header */
.ib-si-lb .ib-team-row td { background:#f9fafb; padding:6px 10px 6px 13px;
  font-size:10px; font-weight:700; color:var(--muted); text-transform:uppercase;
  letter-spacing:.08em; border-bottom:1px solid var(--border);
  border-left:3px solid var(--p); }

/* rank badge */
.ib-rank { display:inline-flex; align-items:center; justify-content:center;
  width:22px; height:22px; border-radius:50%; font-size:10px; font-weight:700; flex-shrink:0; }
.ib-rank-1 { background:#fef9c3; color:#92400e; }
.ib-rank-2 { background:#f1f5f9; color:#475569; }
.ib-rank-3 { background:#fce7d6; color:#c2410c; }
.ib-rank-n { background:#f3f4f6; color:#9ca3af; }

/* avatar */
.ib-avatar { width:28px; height:28px; border-radius:50%; display:inline-flex; align-items:center;
  justify-content:center; font-size:10px; font-weight:700; color:#fff; flex-shrink:0; }

/* rep cell */
.ib-rep-cell { display:flex; align-items:center; gap:8px; }
.ib-rep-name { font-weight:500; color:var(--ink); font-size:12.5px; }
.ib-rep-name.clickable { cursor:pointer; }
.ib-rep-name.clickable:hover { color:var(--p); }
.ib-set-tgt { background:none; border:1px solid var(--border); border-radius:4px;
  padding:1px 5px; font-size:10px; color:var(--muted); cursor:pointer; margin-left:2px;
  line-height:1.4; transition:all .12s; }
.ib-set-tgt:hover { border-color:var(--p); color:var(--p); background:var(--p-light); }

/* progress cell */
.ib-prog-cell { display:flex; align-items:center; gap:6px; }
.ib-prog-bar { flex:1; min-width:60px; max-width:90px; height:5px; background:#f3f4f6; border-radius:3px; }
.ib-prog-bar-fill { height:5px; border-radius:3px; transition:width .4s; }
.ib-pct-chip { display:inline-flex; align-items:center; font-size:10px; font-weight:600;
  padding:1px 6px; border-radius:99px; white-space:nowrap; }
.ib-pct-chip.hi  { background:var(--g-light); color:#065f46; }
.ib-pct-chip.mid { background:var(--y-light); color:#92400e; }
.ib-pct-chip.lo  { background:var(--r-light); color:#991b1b; }

/* generic chips */
.ib-chip { display:inline-flex; align-items:center; padding:2px 8px; border-radius:99px;
  font-size:10.5px; font-weight:600; white-space:nowrap; }
.ib-chip-gray   { background:#f3f4f6; color:#6b7280; }
.ib-chip-green  { background:var(--g-light); color:#065f46; }
.ib-chip-amber  { background:var(--y-light); color:#92400e; }
.ib-chip-purple { background:#ede9fe; color:#5b21b6; }
.ib-chip-orange { background:var(--p-light); color:#c2410c; }
.ib-chip-ghost  { background:transparent; color:#d1d5db; font-size:10px; }

/* amount */
.ib-amount { font-weight:600; color:var(--ink2); font-size:12px; }
.ib-amount.accent { color:var(--p); }
.ib-amount.muted  { color:var(--muted); font-weight:400; }

/* empty state */
.ib-si-empty { padding:36px; text-align:center; color:var(--muted); font-size:12.5px; }
`;
		document.head.appendChild(s);
	}

	// ── avatar color from string hash ──────────────────────────────────────────
	_avatar_color(str) {
		const palette = ["#d97757","#3b82f6","#10b981","#8b5cf6","#f59e0b","#ec4899","#14b8a6","#f97316"];
		let h = 0;
		for (let i = 0; i < (str || "").length; i++) h = (h * 31 + str.charCodeAt(i)) >>> 0;
		return palette[h % palette.length];
	}

	_initials(name) {
		return (name || "?").split(" ").slice(0, 2).map(w => w[0]).join("").toUpperCase();
	}

	_fmt(v) { return "₹" + Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 }); }

	// KPI-card version — crore/lakh scale with the exact amount as a hover
	// title, same fix as the other dashboards' KPI cards. Table amounts
	// (_fmt) stay full precision.
	_fmtC(v) {
		return `<span title="${this._fmt(v)}">${window.ib_fmt_inr_compact ? window.ib_fmt_inr_compact(v) : this._fmt(v)}</span>`;
	}

	_month_label(full) {
		return new Date(this._month + "T00:00:00").toLocaleDateString("en-IN", {
			month: full ? "long" : "short", year: "numeric",
		});
	}

	// ── layout ─────────────────────────────────────────────────────────────────
	_build_layout() {
		const month_val = frappe.datetime.get_today().slice(0, 7);
		const mgr_actions = this._is_manager ? `
			<button class="ib-si-pill-btn" id="ib-si-slabs">
				<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8">
					<rect x="2" y="2" width="5" height="5" rx="1"/><rect x="9" y="2" width="5" height="5" rx="1"/>
					<rect x="2" y="9" width="5" height="5" rx="1"/><rect x="9" y="9" width="5" height="5" rx="1"/>
				</svg>Slabs
			</button>
			<button class="ib-si-pill-btn primary" id="ib-si-target">Set Targets</button>
			<button class="ib-si-pill-btn" id="ib-si-goto-admin">Admin ↗</button>
		` : "";

		// Managers must pick something before anything calculates — either one
		// rep (separately) or "All Sales Reps" (collectively); non-managers are
		// locked to themselves, no dropdown, nothing to pick.
		const person_picker = this._is_manager
			? `<select class="ib-si-month" id="ib-si-sp" style="min-width:190px">
					<option value="">Select sales person…</option>
					<option value="${ALL_REPS}">— All Sales Reps (Team) —</option>
				</select>`
			: "";

		this.$wrap.html(`<div class="ib-si">
			<div class="ib-si-header">
				<h2 class="ib-si-title">Sales Incentives</h2>
				<input type="month" class="ib-si-month" id="ib-si-month" value="${month_val}" />
				${person_picker}
				<div class="ib-si-action-group">
					<button class="ib-si-pill-btn" id="ib-si-refresh">↻ Refresh</button>
					${mgr_actions}
				</div>
			</div>
			<div id="ib-si-empty-state" class="ib-si-empty" style="display:none;padding:60px 20px">
				${this._is_manager
					? "Select a sales person above — or “All Sales Reps” — to calculate incentives for the month."
					: "Loading your incentive…"}
			</div>
			<div id="ib-si-body-wrap">
				<div id="ib-si-kpis" class="ib-si-kpis" style="display:none"></div>
				<div class="ib-si-grid">
					<div class="ib-si-card">
						<div class="ib-si-card-hdr">
							<span class="ib-si-card-hdr-title">6-Month Trend</span>
							<span id="ib-si-trend-label" style="font-size:11px;color:#6b7280"></span>
						</div>
						<div class="ib-si-card-body">
							<div class="ib-si-chart-wrap" id="ib-si-chart"></div>
						</div>
					</div>
					<div class="ib-si-card">
						<div class="ib-si-card-hdr">
							<span class="ib-si-card-hdr-title" id="ib-si-panel2-title">Top Customers</span>
							<span id="ib-si-lb-meta" style="font-size:11px;color:#6b7280"></span>
						</div>
						<div style="overflow-x:auto" id="ib-si-panel2-body">
							<table class="ib-si-lb">
								<thead id="ib-si-thead"><tr>
									<th style="text-align:left">Customer</th>
									<th>Collected</th>
								</tr></thead>
								<tbody id="ib-si-body"></tbody>
							</table>
						</div>
					</div>
				</div>
			</div>
		</div>`);

		this.$wrap.find("#ib-si-month").on("change", e => {
			this._month = e.target.value + "-01";
			this.load();
		});
		this.$wrap.find("#ib-si-refresh").on("click", () => this.load());
		if (this._is_manager) {
			this.$wrap.find("#ib-si-target").on("click", () => this._show_bulk_target_dialog());
			this.$wrap.find("#ib-si-slabs").on("click", () => this._show_slab_dialog());
			this.$wrap.find("#ib-si-goto-admin").on("click", () => frappe.set_route("ib-customer-board", "team"));
			this.$wrap.find("#ib-si-sp").on("change", e => {
				this._sales_person = e.target.value || null;
				this.load();
			});
			this._load_sales_person_options();
		}
		this.load();
	}

	_load_sales_person_options() {
		frappe.call({
			method: "instabiz.instabiz.page.ib_sales_incentives.ib_sales_incentives.get_sales_person_options",
			callback: r => {
				const reps = r.message || [];
				const $sel = this.$wrap.find("#ib-si-sp");
				let last_team;
				reps.forEach(rep => {
					if (rep.team_name !== last_team) {
						last_team = rep.team_name;
						$sel.append(`<optgroup label="${frappe.utils.escape_html(rep.team_name || "No Team")}"></optgroup>`);
					}
					$sel.find("optgroup").last().append(
						`<option value="${frappe.utils.escape_html(rep.user)}">${frappe.utils.escape_html(rep.name)}</option>`
					);
				});
			},
		});
	}

	load() {
		const req_month = this._month;
		const req_sp = this._sales_person;
		frappe.call({
			method: "instabiz.instabiz.page.ib_sales_incentives.ib_sales_incentives.get_incentives_data",
			args: { month: req_month, sales_person: req_sp },
			callback: r => {
				if (r.message && this._month === req_month && this._sales_person === req_sp) {
					this._data = r.message;
					this._render(r.message);
				}
			},
		});
	}

	_render(d) {
		const has_selection = !!d.selected;
		this.$wrap.find("#ib-si-empty-state").toggle(!has_selection);
		this.$wrap.find("#ib-si-body-wrap").toggle(has_selection);
		if (!has_selection) return;

		if (d.mode === "team") this._render_team(d);
		else this._render_individual(d);
	}

	// ── individual rep view ─────────────────────────────────────────────────────
	_render_individual(d) {
		const rep = d.rep;
		this.$wrap.find("#ib-si-panel2-title").text("Top Customers");
		this.$wrap.find("#ib-si-thead").html(`<tr>
			<th style="text-align:left">Customer</th>
			<th>Collected</th>
		</tr>`);

		this._render_kpis(rep);

		const $body = this.$wrap.find("#ib-si-body");
		this.$wrap.find("#ib-si-lb-meta").text(`${rep.sp_name} · ${this._month_label(false)}`);
		const rows = d.top_customers || [];
		if (!rows.length) {
			$body.html(`<tr><td colspan="2"><div class="ib-si-empty">No billed customers for ${this._month_label(true)}</div></td></tr>`);
		} else {
			$body.html(rows.map(r => `
				<tr>
					<td>${frappe.utils.escape_html(r.customer_name || "")}</td>
					<td style="text-align:right"><span class="ib-amount">${this._fmt(r.collected)}</span></td>
				</tr>
			`).join(""));
		}

		this._render_chart_single(d.trend || [], rep.sp_name);
	}

	// ── KPI cards (single rep) ──────────────────────────────────────────────────
	_render_kpis(rep) {
		const $kpis = this.$wrap.find("#ib-si-kpis").show();
		const pct = rep.pct || 0;
		const bar_c = pct >= 100 ? "#10b981" : pct >= 70 ? "#d97757" : "#ef4444";
		const slab_html = rep.slab_earned
			? `<span class="ib-chip ib-chip-green">${frappe.utils.escape_html(rep.slab_earned)}</span>`
			: `<span class="ib-chip ib-chip-ghost">No slab earned</span>`;

		$kpis.html(`
			<div class="ib-si-kpi c-rev">
				<div class="ib-si-kpi-label">Revenue</div>
				<div class="ib-si-kpi-value">${this._fmtC(rep.revenue)}</div>
			</div>
			<div class="ib-si-kpi c-col">
				<div class="ib-si-kpi-label">Collected</div>
				<div class="ib-si-kpi-value">${this._fmtC(rep.collected)}</div>
				${rep.target ? `
				<div class="ib-si-kpi-sub">
					<div class="ib-si-prog-track"><div class="ib-si-prog-fill" style="width:${Math.min(100,pct)}%;background:${bar_c}"></div></div>
					<div class="ib-si-prog-label">${pct}% of target</div>
				</div>` : ""}
			</div>
			<div class="ib-si-kpi c-tgt">
				<div class="ib-si-kpi-label">Target</div>
				<div class="ib-si-kpi-value">
					${rep.target ? this._fmtC(rep.target) : `<span style="color:#d1d5db;font-size:1rem">Not set</span>`}
					${this._is_manager ? `<button class="ib-set-tgt" id="ib-si-set-tgt-btn" title="Set target">✎</button>` : ""}
				</div>
			</div>
			<div class="ib-si-kpi c-com">
				<div class="ib-si-kpi-label">Commission</div>
				<div class="ib-si-kpi-value" style="color:#8b5cf6">${this._fmtC(rep.commission)}</div>
				<div class="ib-si-kpi-sub">${slab_html}</div>
			</div>
		`);

		if (this._is_manager) {
			const self = this;
			$kpis.find("#ib-si-set-tgt-btn").on("click", () => {
				self._show_set_target_dialog(rep.sp_user, rep.sp_name, parseFloat(rep.target || 0), parseFloat(rep.revenue || 0), parseFloat(rep.pct || 0));
			});
		}
	}

	// ── chart: single rep, 1 line ───────────────────────────────────────────────
	_render_chart_single(trend, rep_name) {
		const el = this.$wrap.find("#ib-si-chart")[0];
		if (!el) return;
		if (this._chart) { this._chart.destroy && this._chart.destroy(); this._chart = null; $(el).empty(); }
		if (!trend.length) {
			$(el).html(`<div class="ib-si-empty" style="padding:60px 0">No trend data</div>`);
			return;
		}

		this.$wrap.find("#ib-si-trend-label").text(rep_name || "");

		this._chart = new frappe.Chart(el, {
			type: "line",
			height: 190,
			colors: ["#d97757"],
			data: {
				labels: trend.map(r => r.label),
				datasets: [{ name: "Collected", values: trend.map(r => Number(r.collected || 0)) }],
			},
			lineOptions: { spline: 1, hideDots: 0, regionFill: 1 },
			axisOptions: { xIsSeries: true },
			tooltipOptions: { formatTooltipY: v => "₹" + Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 }) },
		});
	}

	// ── team / collective view (manager only) ───────────────────────────────────
	_render_team(d) {
		this.$wrap.find("#ib-si-panel2-title").text("Leaderboard");
		this.$wrap.find("#ib-si-thead").html(`<tr>
			<th style="width:28px"></th>
			<th style="text-align:left">Rep</th>
			<th>Collected</th>
			<th>vs Target</th>
			<th>Slab</th>
			<th>Commission</th>
		</tr>`);

		this._render_team_kpis(d);
		this._render_leaderboard(d.by_sp || []);
		this._render_chart_team(d.trend || []);
	}

	_render_team_kpis(d) {
		const $kpis = this.$wrap.find("#ib-si-kpis").show();
		const tp = d.team_pct || 0;
		const bar_c = tp >= 100 ? "#10b981" : tp >= 70 ? "#d97757" : "#ef4444";
		$kpis.html(`
			<div class="ib-si-kpi c-rev">
				<div class="ib-si-kpi-label">Revenue</div>
				<div class="ib-si-kpi-value">${this._fmt(d.total_revenue)}</div>
			</div>
			<div class="ib-si-kpi c-col">
				<div class="ib-si-kpi-label">Collected</div>
				<div class="ib-si-kpi-value">${this._fmt(d.total_collected)}</div>
				${d.total_target ? `
				<div class="ib-si-kpi-sub">
					<div class="ib-si-prog-track"><div class="ib-si-prog-fill" style="width:${Math.min(100,tp)}%;background:${bar_c}"></div></div>
					<div class="ib-si-prog-label">${tp}% of target</div>
				</div>` : ""}
			</div>
			<div class="ib-si-kpi c-tgt">
				<div class="ib-si-kpi-label">Team Target</div>
				<div class="ib-si-kpi-value">${d.total_target ? this._fmt(d.total_target) : `<span style="color:#d1d5db;font-size:1rem">Not set</span>`}</div>
			</div>
			<div class="ib-si-kpi c-com">
				<div class="ib-si-kpi-label">Commission</div>
				<div class="ib-si-kpi-value" style="color:#8b5cf6">${this._fmt(d.total_commission)}</div>
			</div>
		`);
	}

	// ── leaderboard (team mode) ──────────────────────────────────────────────────
	_render_leaderboard(rows) {
		const $body = this.$wrap.find("#ib-si-body");
		this.$wrap.find("#ib-si-lb-meta").text(`${rows.length} rep${rows.length !== 1 ? "s" : ""} · ${this._month_label(false)}`);
		if (!rows.length) {
			$body.html(`<tr><td colspan="6"><div class="ib-si-empty">No data for ${this._month_label(true)}</div></td></tr>`);
			return;
		}

		const html = [];
		let last_team, rank = 0;

		rows.forEach(r => {
			if (r.team_name !== last_team) {
				last_team = r.team_name;
				html.push(`<tr class="ib-team-row"><td colspan="6">${frappe.utils.escape_html(r.team_name || "No Team")}</td></tr>`);
			}

			rank++;
			const rank_cls = rank === 1 ? "ib-rank-1" : rank === 2 ? "ib-rank-2" : rank === 3 ? "ib-rank-3" : "ib-rank-n";
			const av_color = this._avatar_color(r.team_name || r.sp_user);
			const initials = this._initials(r.sp_name || r.sp_user);

			const pct = r.pct;
			let target_cell;
			if (!r.target) {
				target_cell = `<span class="ib-chip ib-chip-ghost">No target</span>`;
			} else {
				const pct_cls = pct >= 100 ? "hi" : pct >= 70 ? "mid" : "lo";
				const fill_c  = pct >= 100 ? "#10b981" : pct >= 70 ? "#f59e0b" : "#ef4444";
				target_cell = `<div class="ib-prog-cell">
					<div class="ib-prog-bar"><div class="ib-prog-bar-fill" style="width:${Math.min(100,pct||0)}%;background:${fill_c}"></div></div>
					<span class="ib-pct-chip ${pct_cls}">${pct != null ? pct + "%" : "0%"}</span>
				</div>`;
			}

			let slab_cell;
			if (!r.slab_earned) {
				slab_cell = `<span class="ib-chip ib-chip-ghost">None</span>`;
			} else {
				const sn = parseInt((r.slab_earned || "").replace(/\D/g, ""), 10);
				const cls = sn >= 4 ? "ib-chip-green" : sn >= 3 ? "ib-chip-amber" : "ib-chip-gray";
				slab_cell = `<span class="ib-chip ${cls}">${frappe.utils.escape_html(r.slab_earned)}</span>`;
			}

			const comm_cell = r.commission > 0
				? `<span class="ib-amount accent">${this._fmt(r.commission)}</span>`
				: `<span class="ib-chip ib-chip-ghost">None</span>`;

			const rep_name_html = `
				<span class="ib-rep-name clickable ib-rep-link"
					data-user="${frappe.utils.escape_html(r.sp_user)}"
				>${frappe.utils.escape_html(r.sp_name || r.sp_user)}</span>
				<button class="ib-set-tgt"
					data-user="${frappe.utils.escape_html(r.sp_user)}"
					data-name="${frappe.utils.escape_html(r.sp_name || r.sp_user)}"
					data-target="${r.target || 0}" data-actual="${r.revenue || 0}" data-pct="${r.pct || 0}"
					title="Set target">✎</button>`;

			html.push(`<tr>
				<td><span class="ib-rank ${rank_cls}">${rank}</span></td>
				<td>
					<div class="ib-rep-cell">
						<span class="ib-avatar" style="background:${av_color}">${initials}</span>
						<div>${rep_name_html}</div>
					</div>
				</td>
				<td style="text-align:right"><span class="ib-amount">${this._fmt(r.collected)}</span></td>
				<td>${target_cell}</td>
				<td>${slab_cell}</td>
				<td style="text-align:right">${comm_cell}</td>
			</tr>`);
		});

		$body.html(html.join(""));

		const self = this;
		$body.find(".ib-rep-link").on("click", function () {
			// Drill into that rep's own separate view instead of the team table.
			self._sales_person = $(this).data("user");
			self.$wrap.find("#ib-si-sp").val(self._sales_person);
			self.load();
		});
		$body.find(".ib-set-tgt").on("click", function () {
			const u = $(this).data();
			self._show_set_target_dialog(u.user, u.name, parseFloat(u.target || 0), parseFloat(u.actual || 0), parseFloat(u.pct || 0));
		});
	}

	// ── chart: team mode, top-3 reps ────────────────────────────────────────────
	_render_chart_team(trend) {
		const el = this.$wrap.find("#ib-si-chart")[0];
		if (!el) return;
		if (this._chart) { this._chart.destroy && this._chart.destroy(); this._chart = null; $(el).empty(); }
		if (!trend.length) {
			$(el).html(`<div class="ib-si-empty" style="padding:60px 0">No trend data</div>`);
			return;
		}

		const ym_set = [...new Set(trend.map(r => r.ym))].sort();
		const sp_set = [...new Set(trend.map(r => r.sp_user))];
		const colors = ["#d97757","#3b82f6","#10b981","#8b5cf6","#f59e0b","#ec4899"];

		this.$wrap.find("#ib-si-trend-label").text(`Top ${Math.min(sp_set.length, 3)} reps`);

		this._chart = new frappe.Chart(el, {
			type: "line",
			height: 190,
			colors,
			data: {
				labels: ym_set.map(ym => {
					const row = trend.find(r => r.ym === ym);
					return row ? row.label : ym;
				}),
				datasets: sp_set.map(sp => ({
					name: (trend.find(r => r.sp_user === sp) || {}).sp_name || sp,
					values: ym_set.map(ym => {
						const row = trend.find(r => r.sp_user === sp && r.ym === ym);
						return row ? Number(row.collected || 0) : 0;
					}),
				})),
			},
			lineOptions: { spline: 1, hideDots: 0 },
			axisOptions: { xIsSeries: true },
			tooltipOptions: { formatTooltipY: v => "₹" + Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 }) },
		});
	}

	// ── per-rep target dialog ──────────────────────────────────────────────────
	_show_set_target_dialog(sp_user, sp_name, cur_target, actual, pct) {
		const self = this;
		const month_first = this._month;
		const ml = this._month_label(true);
		const fmt = v => v ? "₹" + Number(v).toLocaleString("en-IN", { maximumFractionDigits: 0 }) : "₹0";

		const d = new frappe.ui.Dialog({
			title: `Target · ${frappe.utils.escape_html(sp_name)}`,
			fields: [
				{
					fieldtype: "HTML",
					options: `<div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:12px;padding:10px 12px;
						background:#f9fafb;border-radius:8px;font-size:12px">
						<div><div style="font-size:10px;color:#6b7280;text-transform:uppercase;letter-spacing:.06em;margin-bottom:2px">Month</div>
							<strong>${ml}</strong></div>
						${actual ? `<div><div style="font-size:10px;color:#6b7280;text-transform:uppercase;letter-spacing:.06em;margin-bottom:2px">Collected</div>
							<strong style="color:#10b981">${fmt(actual)}</strong></div>` : ""}
						${pct ? `<div><div style="font-size:10px;color:#6b7280;text-transform:uppercase;letter-spacing:.06em;margin-bottom:2px">Achieved</div>
							<strong>${pct}%</strong></div>` : ""}
					</div>`,
				},
				{
					fieldname: "target_amount",
					fieldtype: "Currency",
					label: "Target Amount",
					default: cur_target || 0,
					reqd: 1,
				},
			],
			primary_action_label: cur_target ? "Update" : "Set Target",
			primary_action(values) {
				frappe.call({
					method: "instabiz.overrides.sales_target.set_user_target",
					args: { sales_user: sp_user, month: month_first, target_amount: values.target_amount },
					callback(r) {
						if (r.message && r.message.status === "ok") {
							d.hide();
							frappe.show_alert({ message: `Target set · ${sp_name}`, indicator: "green" });
							self.load();
						}
					},
				});
			},
		});
		d.show();
	}

	// ── bulk set targets ───────────────────────────────────────────────────────
	_show_bulk_target_dialog() {
		const self = this;
		const month_first = this._month;
		const ml = this._month_label(true);
		const prev_ml = (() => {
			const dt = new Date(month_first + "T00:00:00");
			dt.setMonth(dt.getMonth() - 1);
			return dt.toLocaleDateString("en-IN", { month: "short", year: "numeric" });
		})();
		const fmt = v => v ? "₹" + Number(v).toLocaleString("en-IN", { maximumFractionDigits: 0 }) : "";

		if (!document.getElementById("ib-si-bulk-css")) {
			const s = document.createElement("style");
			s.id = "ib-si-bulk-css";
			s.textContent = `
#ib-si-bulk-body { font-family:inherit; }
.ib-bulk-toolbar { display:flex; align-items:center; gap:8px; margin-bottom:14px; flex-wrap:wrap; }
.ib-bulk-tbtn { padding:4px 12px; font-size:11px; border:1px solid #d1d5db; border-radius:20px;
  background:#fff; color:#6b7280; cursor:pointer; line-height:1.6; transition:all .12s; }
.ib-bulk-tbtn:hover { border-color:#d97757; color:#d97757; }
.ib-bulk-summary { font-size:11px; color:#6b7280; margin-left:auto; white-space:nowrap; }
.ib-bulk-tbl { width:100%; border-collapse:collapse; font-size:12.5px; }
.ib-bulk-tbl thead th { padding:7px 10px; font-size:10.5px; font-weight:600; color:#6b7280;
  border-bottom:2px solid #e5e7eb; white-space:nowrap; }
.ib-bulk-tbl thead th:not(:first-child) { text-align:right; }
.ib-bulk-thdr td { background:#f9fafb; border-bottom:1px solid #e5e7eb; padding:5px 10px 5px 13px;
  font-size:10px; font-weight:700; color:#9ca3af; letter-spacing:.06em; text-transform:uppercase;
  border-left:2px solid #d97757; }
.ib-bulk-row td { padding:9px 10px; border-bottom:1px solid #f3f4f6; vertical-align:middle; }
.ib-bulk-row:last-child td { border-bottom:none; }
.ib-bulk-row:hover td { background:#fafafa; }
.ib-bulk-row.ib-dirty td:first-child { border-left:2px solid #10b981; padding-left:8px; }
.ib-bulk-name { font-weight:500; color:#111827; }
.ib-bulk-prev-val { display:inline-flex; align-items:center; padding:2px 8px; font-size:11px;
  color:#6b7280; border:1px dashed #d1d5db; border-radius:5px; cursor:pointer; transition:all .12s; }
.ib-bulk-prev-val:hover { border-color:#d97757; color:#d97757; background:#fff4ef; }
.ib-bulk-prev-val.ib-none { border-style:solid; cursor:default; pointer-events:none; color:#d1d5db; }
.ib-bulk-input { width:150px; padding:5px 10px; font-size:12px; border:1px solid #d1d5db;
  border-radius:6px; background:#fff; color:#111827; text-align:right; transition:border-color .12s; }
.ib-bulk-input:focus { border-color:#d97757; outline:none; box-shadow:0 0 0 2px rgba(217,119,87,.12); }
.ib-bulk-input.ib-changed { border-color:#10b981; background:#f0fdf4; }
`;
			document.head.appendChild(s);
		}

		const d = new frappe.ui.Dialog({
			title: `Set Targets · ${ml}`,
			fields: [{ fieldtype: "HTML", options: `<div id="ib-si-bulk-body" style="min-height:80px;display:flex;align-items:center;justify-content:center"><span style="color:#6b7280;font-size:12px">Loading…</span></div>` }],
			size: "large",
			primary_action_label: "Save Targets",
			primary_action() {
				const calls = [];
				d.$wrapper.find(".ib-bulk-input").each(function () {
					const val = parseFloat($(this).val());
					if (!isNaN(val) && val >= 0) calls.push({ user: $(this).data("user"), name: $(this).data("name"), amount: val });
				});
				if (!calls.length) { frappe.show_alert({ message: "No targets entered", indicator: "orange" }); return; }
				let done = 0;
				calls.forEach(c => frappe.call({
					method: "instabiz.overrides.sales_target.set_user_target",
					args: { sales_user: c.user, month: month_first, target_amount: c.amount },
					callback() { if (++done === calls.length) { d.hide(); frappe.show_alert({ message: `${done} targets saved`, indicator: "green" }); self.load(); } },
				}));
			},
		});
		d.show();

		frappe.call({
			method: "instabiz.instabiz.page.ib_sales_incentives.ib_sales_incentives.get_sales_reps_for_targets",
			args: { month: month_first },
			callback(r) {
				const rows = r.message || [];
				const $body = d.$wrapper.find("#ib-si-bulk-body");
				if (!rows.length) {
					$body.html(`<div style="padding:30px;text-align:center;color:#6b7280">No active Sales Users found.</div>`);
					return;
				}
				const has_prev = rows.some(r => r.prev_target > 0);
				const calc = () => {
					let s = 0, cnt = 0;
					$body.find(".ib-bulk-input").each(function () { const v = parseFloat($(this).val()) || 0; if (v > 0) { s += v; cnt++; } });
					$body.find("#ib-bulk-sum").text(`${cnt} of ${rows.length} set · Total ${fmt(s) || "₹0"}`);
				};

				let html = `<div class="ib-bulk-toolbar">
					${has_prev ? `<button class="ib-bulk-tbtn" id="ib-bulk-copy-all">↙ Copy ${prev_ml} for all</button>` : ""}
					<button class="ib-bulk-tbtn" id="ib-bulk-clear">✕ Clear all</button>
					<span class="ib-bulk-summary" id="ib-bulk-sum"></span>
				</div>
				<table class="ib-bulk-tbl"><thead><tr>
					<th style="text-align:left">Rep</th>
					<th>${prev_ml}</th>
					<th>${ml} Target</th>
				</tr></thead><tbody>`;

				let last = undefined;
				rows.forEach(r => {
					if (r.team_name !== last) {
						last = r.team_name;
						html += `<tr class="ib-bulk-thdr"><td colspan="3">${frappe.utils.escape_html(r.team_name || "No Team")}</td></tr>`;
					}
					const prev = r.prev_target
						? `<span class="ib-bulk-prev-val" data-val="${r.prev_target}" title="Click to copy">${fmt(r.prev_target)}</span>`
						: `<span class="ib-bulk-prev-val ib-none">None</span>`;
					html += `<tr class="ib-bulk-row">
						<td><span class="ib-bulk-name">${frappe.utils.escape_html(r.sp_name)}</span></td>
						<td style="text-align:right">${prev}</td>
						<td style="text-align:right">
							<input type="number" class="ib-bulk-input"
								data-user="${frappe.utils.escape_html(r.sp_user)}"
								data-name="${frappe.utils.escape_html(r.sp_name)}"
								data-orig="${r.target || 0}" data-prev="${r.prev_target || 0}"
								value="${r.target || ""}" placeholder="0" />
						</td>
					</tr>`;
				});
				html += `</tbody></table>`;
				$body.html(html);
				calc();

				$body.find(".ib-bulk-input").on("input", function () {
					const orig = parseFloat($(this).data("orig")) || 0;
					const cur  = parseFloat($(this).val()) || 0;
					$(this).toggleClass("ib-changed", cur > 0 && cur !== orig);
					$(this).closest("tr").toggleClass("ib-dirty", cur > 0 && cur !== orig);
					calc();
				});
				$body.find(".ib-bulk-prev-val:not(.ib-none)").on("click", function () {
					$(this).closest("tr").find(".ib-bulk-input").val($(this).data("val")).trigger("input").focus();
				});
				$body.find("#ib-bulk-copy-all").on("click", () => {
					$body.find(".ib-bulk-input").each(function () {
						const p = parseFloat($(this).data("prev")) || 0;
						if (p > 0) $(this).val(p).trigger("input");
					});
				});
				$body.find("#ib-bulk-clear").on("click", () => $body.find(".ib-bulk-input").val("").trigger("input"));
				$body.find(".ib-bulk-input").first().focus();
			},
		});
	}

	// ── slab management ────────────────────────────────────────────────────────
	_show_slab_dialog() {
		const self = this;
		this._slab_designation = this._slab_designation || "Sales User";

		const render = (d, $b) => {
			frappe.call({
				method: "instabiz.overrides.sales_target.get_incentive_slabs",
				args: { designation: self._slab_designation },
				callback(r) {
					const slabs = r.message || [];
					const tabs = `
						<div style="display:flex;gap:6px;margin-bottom:14px">
							${["Sales User", "Sales Manager"].map(desig => `
								<button class="btn btn-sm ib-slab-desig-tab ${self._slab_designation === desig ? "btn-primary" : "btn-default"}"
									data-desig="${desig}">${desig}</button>
							`).join("")}
						</div>
						<div style="font-size:11px;color:#6b7280;margin-bottom:10px">
							Showing slabs for <b>${self._slab_designation}</b> — this is the designation
							used to pick which slab table a rep's commission is calculated against
							(see <code>_get_slab_designation()</code>: anyone with the Sales Manager role
							uses the Sales Manager slabs, everyone else uses Sales User).
						</div>`;
					let html = tabs + (slabs.length
						? `<table style="width:100%;border-collapse:collapse;font-size:12px;margin-bottom:14px">
							<thead><tr style="background:#f9fafb">
								<th style="padding:7px 10px;text-align:left;border-bottom:1px solid #e5e7eb;color:#6b7280;font-size:10.5px">Label</th>
								<th style="padding:7px 10px;text-align:right;border-bottom:1px solid #e5e7eb;color:#6b7280;font-size:10.5px">From %</th>
								<th style="padding:7px 10px;text-align:right;border-bottom:1px solid #e5e7eb;color:#6b7280;font-size:10.5px">To %</th>
								<th style="padding:7px 10px;text-align:right;border-bottom:1px solid #e5e7eb;color:#6b7280;font-size:10.5px">Commission %</th>
								<th style="padding:7px 10px;text-align:center;border-bottom:1px solid #e5e7eb;color:#6b7280;font-size:10.5px">Active</th>
								<th style="padding:7px 10px;border-bottom:1px solid #e5e7eb"></th>
							</tr></thead><tbody>
							${slabs.map(sl => `<tr>
								<td style="padding:8px 10px;border-bottom:1px solid #f3f4f6;font-weight:500">
									<input class="form-control form-control-sm ib-sn-edit-lbl" data-name="${frappe.utils.escape_html(sl.name)}" value="${frappe.utils.escape_html(sl.slab_label || "")}"></td>
								<td style="padding:8px 10px;border-bottom:1px solid #f3f4f6;text-align:right">
									<input type="number" class="form-control form-control-sm ib-sn-edit-from" data-name="${frappe.utils.escape_html(sl.name)}" value="${sl.from_pct}" style="width:70px;margin-left:auto"></td>
								<td style="padding:8px 10px;border-bottom:1px solid #f3f4f6;text-align:right">
									<input type="number" class="form-control form-control-sm ib-sn-edit-to" data-name="${frappe.utils.escape_html(sl.name)}" value="${sl.to_pct}" style="width:70px;margin-left:auto"></td>
								<td style="padding:8px 10px;border-bottom:1px solid #f3f4f6;text-align:right">
									<input type="number" class="form-control form-control-sm ib-sn-edit-comm" data-name="${frappe.utils.escape_html(sl.name)}" value="${sl.commission_pct}" style="width:70px;margin-left:auto;font-weight:600;color:#d97757"></td>
								<td style="padding:8px 10px;border-bottom:1px solid #f3f4f6;text-align:center">${sl.is_active ? `<span style="color:#10b981;font-weight:700">✓</span>` : ""}</td>
								<td style="padding:8px 10px;border-bottom:1px solid #f3f4f6;white-space:nowrap">
									<button class="btn btn-xs btn-default ib-slab-save" data-name="${frappe.utils.escape_html(sl.name)}">Save</button>
									<button class="btn btn-xs btn-danger ib-slab-del" data-name="${frappe.utils.escape_html(sl.name)}">Delete</button>
								</td>
							</tr>`).join("")}
							</tbody></table>`
						: `<div style="padding:16px;text-align:center;color:#9ca3af;font-size:12px;margin-bottom:12px">No slabs configured for ${self._slab_designation}</div>`);

					html += `<hr style="margin:10px 0 12px;border:none;border-top:1px solid #e5e7eb"/>
					<div style="font-size:12px;font-weight:600;color:#374151;margin-bottom:8px">Add Slab (${self._slab_designation})</div>
					<div style="display:grid;grid-template-columns:2fr 1fr 1fr 1fr auto;gap:8px;align-items:end">
						<div><label style="font-size:10.5px;color:#6b7280;display:block;margin-bottom:3px">Label</label>
							<input class="form-control form-control-sm ib-sn-lbl" placeholder="e.g. Slab 3"/></div>
						<div><label style="font-size:10.5px;color:#6b7280;display:block;margin-bottom:3px">From %</label>
							<input type="number" class="form-control form-control-sm ib-sn-from" placeholder="75"/></div>
						<div><label style="font-size:10.5px;color:#6b7280;display:block;margin-bottom:3px">To % (0=∞)</label>
							<input type="number" class="form-control form-control-sm ib-sn-to" placeholder="0"/></div>
						<div><label style="font-size:10.5px;color:#6b7280;display:block;margin-bottom:3px">Commission %</label>
							<input type="number" class="form-control form-control-sm ib-sn-comm" placeholder="3"/></div>
						<button class="btn btn-sm btn-primary ib-sn-add-btn" style="padding:4px 14px">Add</button>
					</div>`;

					$b.html(html);

					$b.find(".ib-slab-desig-tab").on("click", function () {
						self._slab_designation = $(this).data("desig");
						render(d, $b);
					});
					$b.find(".ib-slab-save").on("click", function () {
						const name = $(this).data("name");
						const lbl      = $b.find(`.ib-sn-edit-lbl[data-name="${name}"]`).val().trim();
						const from_pct = parseFloat($b.find(`.ib-sn-edit-from[data-name="${name}"]`).val()) || 0;
						const to_pct   = parseFloat($b.find(`.ib-sn-edit-to[data-name="${name}"]`).val()) || 0;
						const comm_pct = parseFloat($b.find(`.ib-sn-edit-comm[data-name="${name}"]`).val()) || 0;
						frappe.call({ method: "instabiz.overrides.sales_target.save_incentive_slab",
							args: { name, slab_label: lbl, from_pct, to_pct, commission_pct: comm_pct, designation: self._slab_designation, is_active: 1 },
							callback() { frappe.show_alert({ message: "Slab updated", indicator: "green" }); render(d, $b); self.load(); } });
					});
					$b.find(".ib-slab-del").on("click", function () {
						frappe.call({ method: "instabiz.overrides.sales_target.delete_incentive_slab",
							args: { name: $(this).data("name") }, callback() { render(d, $b); self.load(); } });
					});
					$b.find(".ib-sn-add-btn").on("click", function () {
						const lbl = $b.find(".ib-sn-lbl").val().trim();
						const from_pct = parseFloat($b.find(".ib-sn-from").val()) || 0;
						const to_pct   = parseFloat($b.find(".ib-sn-to").val()) || 0;
						const comm_pct = parseFloat($b.find(".ib-sn-comm").val()) || 0;
						if (!lbl || !comm_pct) { frappe.show_alert({ message: "Label and Commission % required", indicator: "orange" }); return; }
						frappe.call({ method: "instabiz.overrides.sales_target.save_incentive_slab",
							args: { slab_label: lbl, from_pct, to_pct, commission_pct: comm_pct, designation: self._slab_designation, is_active: 1 },
							callback() { render(d, $b); self.load(); } });
					});
				},
			});
		};
		const d = new frappe.ui.Dialog({ title: "Incentive Slabs", size: "large" });
		render(d, d.$wrapper.find(".modal-body"));
		d.show();
	}
}
