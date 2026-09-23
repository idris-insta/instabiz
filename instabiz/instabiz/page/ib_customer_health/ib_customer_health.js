frappe.pages["ib-customer-health"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({ parent: wrapper, title: "Customer Health", single_column: true });
	wrapper._ib_ch = new IBCustomerHealth(wrapper.page);
};

frappe.pages["ib-customer-health"].on_page_show = function (wrapper) {
	if (wrapper._ib_ch) wrapper._ib_ch.load();
};

// Rebuilt on the IB Design System (window.ibUI + .ib-ui-* components), 2026-09-21.
class IBCustomerHealth {
	constructor(page) {
		this.page = page;
		this._pg = 0;
		this._limit = 50;
		this._search = "";
		this._territory = "";
		this.$el = ibUI.mount(page);
		this._inject_styles();
		this._build_layout();
		// load() started by on_page_show — no double call on first visit
	}

	// Small, page-specific additions ib-ui's base table doesn't cover
	// (score badge circle, row-click affordance, sticky header) — layered
	// on top, never redefining a color ib-ui already owns.
	_inject_styles() {
		if (document.getElementById("ib-ch-css")) return;
		const s = document.createElement("style");
		s.id = "ib-ch-css";
		s.textContent = `
.ib-ch-tbl-wrap .ib-ui-table-wrap { max-height: 65vh; }
.ib-ch-tbl-wrap .ib-ui-table thead th { position: sticky; top: 0; background: var(--card-bg); z-index: 1; }
.ib-ch-tbl-wrap .ib-ui-table tbody tr { cursor: pointer; }
.ib-ch-tbl-wrap .ib-ui-table th:nth-child(n+6) { text-align: right; }
.ib-ch-score { display: inline-flex; align-items: center; justify-content: center;
  width: 32px; height: 32px; border-radius: 50%; font-size: 11px; font-weight: 700; }
.ib-ch-score.hi { background: var(--ib-ok-bg); color: var(--ib-ok-fg); }
.ib-ch-score.md { background: var(--ib-warn-bg); color: var(--ib-warn-fg); }
.ib-ch-score.lo { background: var(--ib-danger-bg); color: var(--ib-danger-fg); }
`;
		document.head.appendChild(s);
	}

	_build_layout() {
		const search = ibUI.search("Search customer…");
		this._$search = search.$input;

		this.$el.html(`
			${ibUI.toolbar([
				`<span style="flex:1;font-size:1.15rem;font-weight:700;color:var(--heading-color)">Customer Health</span>`,
				`<span id="ib-ch-search-slot"></span>`,
				`<select class="ib-ui-btn" id="ib-ch-territory" style="cursor:pointer"><option value="">All Territories</option></select>`,
				ibUI.btn("Refresh", { variant: "ghost", icon: "refresh-cw", attrs: 'id="ib-ch-refresh"' }),
			])}
			<div id="ib-ch-kpis"></div>
			<div class="ib-ch-tbl-wrap" style="margin-top:var(--ib-space-3)">
				<div id="ib-ch-tbl"></div>
				<div id="ib-ch-pagination" class="ib-ui-row" style="justify-content:space-between;padding:var(--ib-space-2) 0"></div>
			</div>
		`);
		this.$el.find("#ib-ch-search-slot").replaceWith(search.el);

		let searchTimeout;
		this._$search.on("input", (e) => {
			clearTimeout(searchTimeout);
			searchTimeout = setTimeout(() => { this._search = e.target.value; this._pg = 0; this.load(); }, 350);
		});
		this.$el.find("#ib-ch-territory").on("change", (e) => { this._territory = e.target.value; this._pg = 0; this.load(); });
		this.$el.find("#ib-ch-refresh").on("click", () => this.load());
	}

	load() {
		this.$el.find("#ib-ch-tbl").html(ibUI.skeleton(4));
		frappe.call({
			method: "instabiz.instabiz.page.ib_customer_health.ib_customer_health.get_customer_health",
			args: { search: this._search, territory: this._territory, limit: this._limit, offset: this._pg * this._limit },
			callback: (r) => {
				if (!r.message) return;
				this._render(r.message);
				this._populate_territories(r.message.territories);
			},
		});
	}

	_populate_territories(list) {
		const $sel = this.$el.find("#ib-ch-territory");
		const cur = $sel.val();
		$sel.html('<option value="">All Territories</option>' + (list || [])
			.map((t) => `<option value="${ibUI.esc(t)}">${ibUI.esc(t)}</option>`).join(""));
		$sel.val(cur);
	}

	_render(d) {
		const customers = d.customers || [];

		this.$el.find("#ib-ch-kpis").html(ibUI.statGrid([
			{ v: d.total, l: "Total Customers" },
			{ v: d.agg_healthy || 0, l: "Healthy (≥80)" },
			{ v: d.agg_at_risk || 0, l: "At Risk (<50)" },
			{ v: ibUI.money(d.agg_mtd || 0, { compact: true }), l: "MTD Revenue" },
			{ v: ibUI.money(d.agg_ytd || 0, { compact: true }), l: "YTD Revenue" },
			{ v: ibUI.money(d.agg_outstanding || 0, { compact: true }), l: "Total Outstanding" },
		]));

		const rows = customers.map((c) => {
			const score = c.health_score || 0;
			const cls = score >= 80 ? "hi" : score >= 50 ? "md" : "lo";
			const daysLbl = c.days_since_order != null
				? (c.days_since_order > 90 ? ibUI.pill(`${c.days_since_order}d ago`, "warn") : `${c.days_since_order}d ago`)
				: ibUI.pill("Never", "warn");
			return [
				`<span class="ib-ch-score ${cls}">${score}</span>`,
				`<a data-customer="${ibUI.esc(c.customer)}" style="font-weight:600;color:var(--text-color)">${ibUI.esc(c.customer_name || c.customer)}</a>`,
				ibUI.esc(c.territory || ""),
				ibUI.esc(c.sales_person || "—"),
				daysLbl,
				`<span class="num">${ibUI.money(c.mtd_revenue)}</span>`,
				`<span class="num">${ibUI.money(c.ytd_revenue)}</span>`,
				`<span class="num"${Number(c.outstanding) > 0 ? ' style="color:var(--ib-warn-fg);font-weight:600"' : ""}>${ibUI.money(c.outstanding)}</span>`,
				`<span class="num">${c.open_quotes > 0 ? ibUI.pill(c.open_quotes, "warn") : "—"}</span>`,
			];
		});

		const $tbl = this.$el.find("#ib-ch-tbl");
		if (!rows.length) {
			$tbl.html(ibUI.empty("No customers", "users"));
		} else {
			$tbl.html(ibUI.table({
				head: ["Health", "Customer", "Territory", "Sales Person", "Last Order",
					"MTD Revenue", "YTD Revenue", "Outstanding", "Open Quotes"],
				rows,
			}));
			$tbl.find("tbody tr").each((i, tr) => {
				$(tr).on("click", () => frappe.set_route("Form", "Customer", customers[i].customer));
			});
		}

		const total = d.total || 0;
		const pages = Math.ceil(total / this._limit);
		const pg = this._pg;
		const from = total === 0 ? 0 : pg * this._limit + 1;
		const to = Math.min((pg + 1) * this._limit, total);
		this.$el.find("#ib-ch-pagination").html(`
			<span class="ib-ui-hint">${total === 0 ? "No customers" : `Showing ${from}–${to} of ${total}`}</span>
			<div class="ib-ui-row">
				${ibUI.btn("← Prev", { variant: "ghost", attrs: `id="ib-ch-prev" ${pg === 0 || total === 0 ? "disabled" : ""}` })}
				${ibUI.btn("Next →", { variant: "ghost", attrs: `id="ib-ch-next" ${pg >= pages - 1 || total === 0 ? "disabled" : ""}` })}
			</div>
		`);
		this.$el.find("#ib-ch-prev").on("click", () => { if (this._pg > 0) { this._pg--; this.load(); } });
		this.$el.find("#ib-ch-next").on("click", () => { if ((this._pg + 1) * this._limit < total) { this._pg++; this.load(); } });
	}
}
