frappe.pages["ib-dpr"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({
		parent: wrapper,
		title: "Daily Production Report",
		single_column: true,
	});

	const page = new IBDPRPage(wrapper);
	wrapper.ib_dpr = page;
};

frappe.pages["ib-dpr"].on_page_show = function (wrapper) {
	if (wrapper.ib_dpr) {
		wrapper.ib_dpr.refresh();
	}
};

// ── Stage colour palette ──────────────────────────────────────────────────────
const DPR_STAGE_COLORS = {
	coating:          "#7c3aed",
	slitting:         "#2563eb",
	rewinding:        "#0891b2",
	cutting:          "#059669",
	packing:          "#d97706",
	ready_to_deliver: "#ea580c",
	delivered:        "#10b981",
};

class IBDPRPage {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.page    = wrapper.page;
		this._mode   = "daily";   // "daily" | "weekly"
		this._date   = frappe.datetime.get_today();
		this._inject_styles();
		this._build_toolbar();
		this._build_layout();
		this.refresh();
	}

	// ── Public ────────────────────────────────────────────────────────────────
	refresh() {
		if (this._mode === "daily") {
			this._load_daily();
		} else {
			this._load_weekly();
		}
	}

	// ── Toolbar ───────────────────────────────────────────────────────────────
	_build_toolbar() {
		this._date_control = this.page.add_field({
			fieldtype: "Date",
			fieldname: "dpr_date",
			label: "Date",
			default: this._date,
			change: () => {
				const val = this.page.fields_dict.dpr_date.get_value();
				if (val) {
					this._date = val;
					this.refresh();
				}
			},
		});

		this.$btn_daily  = this.page.add_button("Daily",  () => this._set_mode("daily"),  { btn_class: "btn-default ib-dpr-toggle" });
		this.$btn_weekly = this.page.add_button("Weekly", () => this._set_mode("weekly"), { btn_class: "btn-default ib-dpr-toggle" });
		this._highlight_mode_btn();

		this.$refresh_label = this.page.add_inner_message("").addClass("ib-dpr-refresh-time");
		this.page.add_button("Refresh", () => this.refresh(), { icon: "refresh" });
	}

	_set_mode(mode) {
		this._mode = mode;
		this._highlight_mode_btn();
		this.refresh();
	}

	_highlight_mode_btn() {
		if (this.$btn_daily)  this.$btn_daily.toggleClass("btn-primary",  this._mode === "daily").toggleClass("btn-default", this._mode !== "daily");
		if (this.$btn_weekly) this.$btn_weekly.toggleClass("btn-primary", this._mode === "weekly").toggleClass("btn-default", this._mode !== "weekly");
	}

	// DPR's date picker can be set to any past day — flag it clearly so a
	// stale/old report isn't mistaken for today's production numbers.
	_is_historical() {
		return this._date !== frappe.datetime.get_today();
	}

	_set_refresh_label(text) {
		if (!this.$refresh_label) return;
		const hist = this._is_historical();
		const label = hist
			? `Viewing historical data for ${frappe.datetime.str_to_user(this._date)} — ${text}`
			: text;
		this.$refresh_label.text(label).toggleClass("ib-dpr-refresh-time--hist", hist);
	}

	// ── Layout ────────────────────────────────────────────────────────────────
	_build_layout() {
		this.$container = $(`<div class="ib-dpr-page container"></div>`)
			.appendTo($(this.wrapper).find(".layout-main-section"));
	}

	// ── Skeleton ─────────────────────────────────────────────────────────────
	_show_skeleton(cols = 5) {
		const cards = Array(cols).fill(0).map(() => `
			<div class="ib-dpr-kpi-card ib-dpr-skeleton">
				<div class="ib-dpr-sk-val"></div>
				<div class="ib-dpr-sk-lbl"></div>
			</div>`).join("");
		const rows  = Array(4).fill(0).map(() => `
			<tr>${Array(8).fill(0).map(() => `<td><div class="ib-dpr-sk-cell"></div></td>`).join("")}</tr>`).join("");
		this.$container.html(`
			<div class="ib-dpr-kpi-row">${cards}</div>
			<div class="ib-dpr-section-title ib-dpr-sk-title"></div>
			<div class="ib-dpr-table-wrap">
				<table class="ib-dpr-table"><tbody>${rows}</tbody></table>
			</div>`);
	}

	// ── Data loaders ─────────────────────────────────────────────────────────
	_load_daily() {
		this._set_refresh_label("Loading…");
		this._show_skeleton(5);
		// Self-bumped request-generation token — date change, Daily/Weekly
		// toggle, and the Refresh button all call back into refresh(), so a
		// slower response for a date/mode the user has already changed away
		// from could otherwise land after a newer one and render the wrong
		// date's numbers under the currently-selected date (same bug class
		// fixed on the Production Stages page's loaders).
		const gen = (this._load_gen = (this._load_gen || 0) + 1);
		frappe.call({
			method: "instabiz.overrides.production.get_dpr",
			args:   { date: this._date },
			callback: (r) => {
				if (gen !== this._load_gen) return; // stale — a newer refresh() already superseded this
				if (r.message) {
					this._render_daily(r.message);
					this._set_refresh_label("Updated " + frappe.datetime.now_time());
				}
			},
			error: () => { if (gen === this._load_gen) this._set_refresh_label("Error loading data"); },
		});
	}

	_load_weekly() {
		this._set_refresh_label("Loading…");
		this._show_skeleton(3);
		const gen = (this._load_gen = (this._load_gen || 0) + 1);
		frappe.call({
			method: "instabiz.overrides.production.get_weekly_dpr",
			args:   { date: this._date },
			callback: (r) => {
				if (gen !== this._load_gen) return; // stale — a newer refresh() already superseded this
				if (r.message) {
					this._render_weekly(r.message);
					this._set_refresh_label("Updated " + frappe.datetime.now_time());
				}
			},
			error: () => { if (gen === this._load_gen) this._set_refresh_label("Error loading data"); },
		});
	}

	// ── UOM-aware formatting helpers ─────────────────────────────────────────
	// Output is never a single blended number — a Work Order's target_uom
	// varies by item (PCS/SQMT/ROLL/KG all occur in real data), and summing
	// across them (e.g. "288 PCS + 2148 SQMT") isn't a real quantity of
	// anything. Every render below keeps qty split by its own uom.
	_fmt_qty(n) {
		return frappe.format(n, { fieldtype: "Float" });
	}
	// Stacked badges for a table cell: one line per uom
	_fmt_uom_stack(list, qtyKey = "qty", extra = null) {
		if (!list || !list.length) return "—";
		return list.map(o => `<div class="ib-dpr-uom-line">
			<span class="ib-dpr-uom-qty">${this._fmt_qty(o[qtyKey])}</span>
			<span class="ib-dpr-uom-tag">${frappe.utils.escape_html(o.uom)}</span>
			${extra ? extra(o) : ""}
		</div>`).join("");
	}

	// ── KPI card helper ───────────────────────────────────────────────────────
	_kpi_card(label, value, accent, icon_name, sub = "") {
		const icon = `<iconify-icon icon="lucide:${icon_name}" width="18" height="18"></iconify-icon>`;
		return `<div class="ib-dpr-kpi-card" style="--dpr-kc:${accent}">
			<div class="ib-dpr-kpi-icon-wrap" style="background:${accent}18;color:${accent}">${icon}</div>
			<div class="ib-dpr-kpi-value">${value}</div>
			<div class="ib-dpr-kpi-label">${label}</div>
			${sub ? `<div class="ib-dpr-kpi-sub">${sub}</div>` : ""}
		</div>`;
	}

	// ── Daily render ─────────────────────────────────────────────────────────
	// Sourced entirely from Work Order completions (see get_dpr()'s own
	// docstring) — no wastage/efficiency figures shown here, since nothing in
	// this system currently records real per-stage wastage (IB Production
	// Entry, the only path that ever wrote it, has zero rows system-wide).
	_render_daily(data) {
		const s = data.summary || {};
		const woCompleted = s.wo_completed || 0;
		const outputByUom = s.output_by_uom || [];

		// One KPI card per UOM actually produced today — "Output (PCS)" /
		// "Output (SQMT)" etc, never one blended "Total Output" number.
		const output_cards = outputByUom.length
			? outputByUom.map(o => this._kpi_card(`Output (${o.uom})`, this._fmt_qty(o.qty), "#059669", "trending-up")).join("")
			: this._kpi_card("Output", 0, "#059669", "trending-up");
		const kpi_html = [
			this._kpi_card("WOs Completed", woCompleted, "#7c3aed", "check-circle"),
			output_cards,
			this._kpi_card("Total Hours",   s.total_hours  ?? 0,   "#d97706", "clock"),
		].join("");

		const stage_rows = (data.stages || []).map(st => {
			const color = DPR_STAGE_COLORS[st.stage] || "#888";
			const label = (st.stage || "").replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
			const machine_rows = (st.machines || []).map(m => `
				<tr class="ib-dpr-machine-row">
					<td><span class="ib-dpr-machine-pill">${frappe.utils.escape_html(m.machine || "—")}</span></td>
					<td>${m.wo_completed ?? "—"}</td>
					<td>${this._fmt_uom_stack(m.output, "output_qty")}</td>
				</tr>
			`).join("");
			const sub_table = st.machines && st.machines.length ? `
				<tr class="ib-dpr-machine-subtable-row">
					<td colspan="5">
						<div class="ib-dpr-machine-subtable">
							<table class="ib-dpr-sub-table">
								<thead><tr><th>Machine</th><th>WOs Completed</th><th>Output</th></tr></thead>
								<tbody>${machine_rows}</tbody>
							</table>
						</div>
					</td>
				</tr>
			` : "";
			const hourlyAvgCell = st.output && st.output.length
				? this._fmt_uom_stack(st.output, "hourly_avg", o => `<span class="ib-dpr-uom-suffix">/hr</span>`)
				: "—";
			return `
				<tr class="ib-dpr-stage-row" data-stage="${st.stage}">
					<td>
						<div class="ib-dpr-stage-cell">
							<span class="ib-dpr-stage-dot" style="background:${color}"></span>
							<span class="ib-dpr-stage-name" style="color:${color}">${label}</span>
							${st.machines && st.machines.length ? `<span class="ib-dpr-chevron">▾</span>` : ""}
						</div>
					</td>
					<td>${st.wo_completed ?? 0}</td>
					<td>${this._fmt_uom_stack(st.output, "output_qty")}</td>
					<td>${st.hours ?? "—"}</td>
					<td>${hourlyAvgCell}</td>
				</tr>
				${sub_table}
			`;
		}).join("");

		const empty_row = `<tr><td colspan="5" class="ib-dpr-empty">
			<iconify-icon icon="lucide:file-x" width="14" height="14"></iconify-icon> No Work Orders completed on this date.
		</td></tr>`;

		this.$container.html(`
			<div class="ib-dpr-kpi-row">${kpi_html}</div>
			<div class="ib-dpr-section-title">Stage Breakdown</div>
			<div class="ib-dpr-table-wrap">
				<table class="ib-dpr-table">
					<thead>
						<tr>
							<th>Stage</th>
							<th>WOs Completed</th>
							<th>Output</th>
							<th>Hours</th>
							<th>Hourly Avg</th>
						</tr>
					</thead>
					<tbody>${stage_rows || empty_row}</tbody>
				</table>
			</div>
		`);

		// Collapsible machine subtables — click stage row to toggle
		this.$container.find(".ib-dpr-stage-row").on("click", function () {
			$(this).next(".ib-dpr-machine-subtable-row").toggle();
		});
	}

	// ── Weekly render ─────────────────────────────────────────────────────────
	_render_weekly(data) {
		const s = data.summary || {};
		const outputByUom = s.output_by_uom || [];
		const avgByUom = s.avg_daily_by_uom || [];

		const output_cards = outputByUom.length
			? outputByUom.map(o => this._kpi_card(`Output — Week (${o.uom})`, this._fmt_qty(o.qty), "#059669", "box")).join("")
			: this._kpi_card("Output — Week", 0, "#059669", "box");
		const avg_cards = avgByUom.length
			? avgByUom.map(o => this._kpi_card(`Avg Daily (${o.uom})`, this._fmt_qty(o.qty), "#2563eb", "bar-chart-2")).join("")
			: this._kpi_card("Avg Daily", 0, "#2563eb", "bar-chart-2");
		const kpi_html = output_cards + avg_cards;

		// Bar is sized by WOs completed — the one number that's always
		// comparable across days regardless of which UOMs were produced.
		// Output itself is shown as text, split by uom, next to the bar.
		const maxWo = Math.max(1, ...(data.days || []).map(d => d.wo_completed || 0));

		const day_rows = (data.days || []).map(d => {
			const barPct = Math.round(((d.wo_completed || 0) / maxWo) * 100);
			const output_bar = `<div class="ib-dpr-week-cell">
				<div>${this._fmt_uom_stack(d.output_by_uom)}</div>
				<div class="ib-dpr-eff-wrap" style="margin-top:3px" title="${d.wo_completed || 0} WOs completed">
					<div class="ib-dpr-eff-bar" style="width:${barPct}%;background:#059669"></div>
				</div>
			</div>`;
			return `
				<tr>
					<td><strong>${frappe.datetime.str_to_user(d.date) || d.date || "—"}</strong></td>
					<td>${d.wo_completed ?? 0}</td>
					<td>${output_bar}</td>
					<td>${d.hours ?? "—"}</td>
				</tr>
			`;
		}).join("");

		this.$container.html(`
			<div class="ib-dpr-kpi-row">${kpi_html}</div>
			<div class="ib-dpr-section-title">Daily Breakdown</div>
			<div class="ib-dpr-table-wrap">
				<table class="ib-dpr-table">
					<thead>
						<tr>
							<th>Date</th>
							<th>WOs Completed</th>
							<th>Output</th>
							<th>Hours</th>
						</tr>
					</thead>
					<tbody>${day_rows || '<tr><td colspan="4" class="ib-dpr-empty">No data for this week.</td></tr>'}</tbody>
				</table>
			</div>
		`);
	}

	// ── Styles ────────────────────────────────────────────────────────────────
	_inject_styles() {
		if (document.getElementById("ib-dpr-styles")) return;
		const style = document.createElement("style");
		style.id = "ib-dpr-styles";
		style.textContent = `
			.ib-dpr-page { padding: 20px 0; font-family: inherit; }

			/* ── KPI cards ── */
			.ib-dpr-kpi-row { display: flex; gap: 14px; margin-bottom: 24px; flex-wrap: wrap; }
			.ib-dpr-kpi-card {
				flex: 1; min-width: 140px; position: relative; overflow: hidden;
				background: var(--card-bg, #fff);
				border: 1px solid var(--border-color, #e2e8f0);
				border-left: 4px solid var(--dpr-kc, #d97757);
				border-radius: 10px; padding: 16px 18px;
				box-shadow: 0 1px 4px rgba(0,0,0,.06);
				transition: transform .15s, box-shadow .15s;
			}
			.ib-dpr-kpi-card:hover { transform: translateY(-2px); box-shadow: 0 4px 14px rgba(0,0,0,.10); }
			.ib-dpr-kpi-icon-wrap {
				display: inline-flex; align-items: center; justify-content: center;
				width: 32px; height: 32px; border-radius: 8px;
				margin-bottom: 8px;
			}
			.ib-dpr-kpi-value {
				font-size: 28px; font-weight: 700;
				color: var(--dpr-kc, #d97757); line-height: 1.1;
			}
			.ib-dpr-kpi-label {
				font-size: 12px; color: var(--text-muted, #6b7280);
				margin-top: 4px; font-weight: 500;
			}
			.ib-dpr-kpi-sub {
				font-size: 10px; color: var(--text-muted, #6b7280);
				margin-top: 2px;
			}
			/* ── Section title ── */
			.ib-dpr-section-title {
				font-size: 11px; font-weight: 700; text-transform: uppercase;
				letter-spacing: .07em; color: var(--text-muted, #6b7280);
				margin: 20px 0 10px; display: flex; align-items: center; gap: 8px;
			}
			.ib-dpr-section-title::after {
				content: ''; flex: 1; height: 1px; background: var(--border-color, #e2e8f0);
			}

			/* ── Table ── */
			.ib-dpr-table-wrap { overflow-x: auto; margin-bottom: 20px; border-radius: 10px; border: 1px solid var(--border-color, #e2e8f0); }
			.ib-dpr-table { width: 100%; border-collapse: collapse; background: var(--card-bg, #fff); font-size: 13px; }
			.ib-dpr-table th {
				background: var(--subtle-fg, #f8fafc); font-size: 11px; font-weight: 700;
				text-transform: uppercase; letter-spacing: .05em; color: var(--text-muted, #6b7280);
				padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border-color, #e2e8f0); white-space: nowrap;
			}
			.ib-dpr-table td { padding: 9px 12px; border-bottom: 1px solid var(--border-color, #f1f5f9); color: var(--text-color, #1e293b); }
			.ib-dpr-table tr:last-child td { border-bottom: none; }
			.ib-dpr-stage-row { cursor: pointer; transition: background .1s; }
			.ib-dpr-stage-row:hover td { background: rgba(217,119,87,.05) !important; }
			.ib-dpr-machine-subtable-row { display: none; }
			.ib-dpr-machine-subtable { padding: 8px 16px 8px 32px; background: var(--subtle-fg, #f8fafc); }
			.ib-dpr-sub-table { width: 100%; border-collapse: collapse; font-size: 12px; }
			.ib-dpr-sub-table th {
				background: #f1f5f9; font-size: 11px; font-weight: 700;
				text-transform: uppercase; letter-spacing: .04em; color: var(--text-muted, #6b7280);
				padding: 6px 10px; text-align: left;
			}
			.ib-dpr-sub-table td { padding: 7px 10px; border-bottom: 1px solid #e2e8f0; }
			.ib-dpr-sub-table tr:last-child td { border-bottom: none; }

			/* ── Stage cell ── */
			.ib-dpr-stage-cell { display: flex; align-items: center; gap: 7px; }
			.ib-dpr-stage-dot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }
			.ib-dpr-stage-name { font-weight: 600; font-size: 13px; }
			.ib-dpr-chevron { font-size: 11px; color: var(--text-muted); margin-left: 2px; }

			/* ── Machine pill ── */
			.ib-dpr-machine-pill {
				background: #f1f5f9; border-radius: 4px; padding: 2px 7px;
				font-size: 11px; font-weight: 600; color: var(--text-color);
			}

			/* ── Efficiency bar ── */
			.ib-dpr-eff-wrap { height: 3px; background: var(--border-color, #e2e8f0); border-radius: 2px; overflow: hidden; margin-top: 4px; width: 100%; min-width: 48px; max-width: 96px; }
			.ib-dpr-eff-bar { height: 100%; border-radius: 2px; transition: width .5s cubic-bezier(.4,0,.2,1); }
			.ib-dpr-week-cell { display: flex; flex-direction: column; }

			/* ── Per-UOM output stack (never blend units into one number) ── */
			.ib-dpr-uom-line { display: flex; align-items: baseline; gap: 4px; white-space: nowrap; }
			.ib-dpr-uom-line + .ib-dpr-uom-line { margin-top: 2px; }
			.ib-dpr-uom-qty { font-weight: 600; font-variant-numeric: tabular-nums; }
			.ib-dpr-uom-tag {
				font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .03em;
				color: var(--text-muted, #6b7280);
			}
			.ib-dpr-uom-suffix { font-size: 10px; color: var(--text-muted, #6b7280); }

			.ib-dpr-empty { text-align: center; padding: 32px; color: var(--text-muted, #6b7280); font-size: 13px; }
			.ib-dpr-refresh-time { font-size: 11px; color: var(--text-muted, #6b7280); margin-right: 8px; }
			.ib-dpr-refresh-time--hist { color: #b45309; font-weight: 600; }
			.btn-primary.ib-dpr-toggle  { background: #d97757; border-color: #d97757; color: #fff; }
			.btn-default.ib-dpr-toggle  { background: var(--card-bg, #fff); color: var(--text-color, #333); }

			/* ── Skeleton ── */
			@keyframes ib-dpr-shimmer { 0%{opacity:.5} 50%{opacity:1} 100%{opacity:.5} }
			.ib-dpr-skeleton { animation: ib-dpr-shimmer 1.3s ease-in-out infinite; }
			.ib-dpr-sk-val { height: 28px; background: var(--border-color, #e2e8f0); border-radius: 5px; width: 60%; margin-bottom: 8px; }
			.ib-dpr-sk-lbl { height: 12px; background: var(--border-color, #e2e8f0); border-radius: 4px; width: 80%; }
			.ib-dpr-sk-cell { height: 14px; background: var(--border-color, #e2e8f0); border-radius: 3px; animation: ib-dpr-shimmer 1.3s ease-in-out infinite; }
			.ib-dpr-sk-title { height: 12px; background: var(--border-color, #e2e8f0); border-radius: 3px; width: 120px; animation: ib-dpr-shimmer 1.3s ease-in-out infinite; }
		`;
		document.head.appendChild(style);
	}
}
