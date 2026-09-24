frappe.pages["ib-stock-dashboard"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Stock"),
		single_column: true,
	});
	wrapper.stock_shell = new IBStockShell(wrapper);
	frappe.pages["ib-stock-dashboard"]._shell = wrapper.stock_shell;
};

frappe.pages["ib-stock-dashboard"].on_page_show = function (wrapper) {
	if (wrapper.stock_shell) wrapper.stock_shell._on_show();
};

frappe.pages["ib-stock-dashboard"].on_page_hide = function (wrapper) {
	if (wrapper.stock_shell) wrapper.stock_shell._cleanup();
};

/* ─── Outer shell — tabs between Balance and Ledger ──────────────────────── */
// Merged 2026-08-05: this page used to be two separate routes (ib-stock-dashboard
// / ib-stock-ledger), already one-way-linked (Dashboard's warehouse-breakdown
// popover had a "View Stock Ledger" link into the Ledger page). Route name kept
// as "ib-stock-dashboard" (not renamed) so every existing frappe.set_route(
// "ib-stock-dashboard") call elsewhere in the app — ib_main_dashboard.js,
// ib_business_pulse.js, ib_analytics_hub.js, several workspace shortcuts —
// keeps working with zero changes; only the standalone "ib-stock-ledger" route
// was retired (its .py RPC module stays put, only .json/.js removed).
class IBStockShell {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.page = wrapper.page;
		// page.main (== page.body, ".layout-main-section") is Frappe's own
		// container — page.page_form is prepended inside it at construction
		// time. Never wholesale-replace this node's HTML (see the identical
		// gotcha documented in ib_item_pricing.js) — mount the tab bar and a
		// dedicated body div as siblings instead.
		this.$main = $(this.page.main);
		this._active = null;
		this._active_tab = null;
		this._build_shell();
		this._activate(this._route_tab());
	}

	_route_tab() {
		const route = frappe.get_route();
		return route[1] === "ledger" ? "ledger" : "balance";
	}

	_build_shell() {
		if (!document.getElementById("ib-stock-shell-styles")) {
			const s = document.createElement("style");
			s.id = "ib-stock-shell-styles";
			s.textContent = `
				.ib-stock-tabs { display:flex; gap:4px; padding:10px 0 0; border-bottom:2px solid var(--border-color); margin-bottom:14px; }
				button.ib-stock-tab {
					-webkit-appearance:none; appearance:none;
					padding:8px 28px; border:1.5px solid transparent !important; border-bottom:none !important;
					border-radius:8px 8px 0 0; font-size:13px; font-weight:600; cursor:pointer;
					color:var(--text-muted); background:transparent !important; box-shadow:none !important;
					transition:all .15s; margin-bottom:-2px; line-height:1.4;
				}
				button.ib-stock-tab:hover { background:var(--bg-color) !important; color:var(--text-color); }
				button.ib-stock-tab.ib-stock-tab--active {
					background:var(--card-bg) !important; color:var(--ib-primary,#d97757);
					border-color:var(--border-color) !important; border-bottom-color:var(--card-bg) !important;
				}
			`;
			document.head.appendChild(s);
		}
		this.$main.prepend(`<div class="ib-stock-tabs" id="ib-stock-tabs">
			<button class="ib-stock-tab" data-tab="balance">Balance</button>
			<button class="ib-stock-tab" data-tab="ledger">Ledger</button>
		</div>`);
		this.$main.append(`<div id="ib-stock-body"></div>`);
		this.$main.on("click", ".ib-stock-tab", (e) => {
			const tab = $(e.currentTarget).data("tab");
			if (tab === this._active_tab) return;
			frappe.set_route("ib-stock-dashboard", tab === "balance" ? "" : tab);
			this._activate(tab);
		});
	}

	_on_show() {
		const tab = this._route_tab();
		if (tab !== this._active_tab) {
			this._activate(tab);
		} else if (tab === "balance" && this._active) {
			this._active._live && this._active._live.start();
		}
	}

	// prefill_item: only meaningful for the ledger tab — threaded straight
	// into IbStockLedger's constructor so the ONE natural construction-time
	// refresh() call picks it up. Setting it via a second post-construction
	// refresh() call instead (the first version of this code did) races: if
	// the constructor's own refresh() is still in flight when the second
	// call lands, refresh()'s own `if (this._loading) return;` guard drops
	// it silently, and the stale first response then overwrites the table —
	// confirmed live, the item filter chip showed the right item but the
	// table kept showing the previous item's rows.
	_activate(tab, prefill_item) {
		this._teardown_active();
		this.$main.find(".ib-stock-tab").removeClass("ib-stock-tab--active");
		this.$main.find(`[data-tab="${tab}"]`).addClass("ib-stock-tab--active");

		this.page.clear_primary_action();
		this.page.clear_secondary_action();
		this.page.clear_inner_toolbar();
		this.page.clear_menu();
		this.page.clear_fields();
		this.page.hide_form();

		const $body = this.$main.find("#ib-stock-body").empty();
		this._active_tab = tab;

		if (tab === "balance") {
			this._active = new IBStockDashboard(this.page, $body);
		} else {
			const opts = frappe.route_options || {};
			if (opts.item_code) {
				prefill_item = opts.item_code;
				frappe.route_options = null;
			}
			this._active = new IbStockLedger(this.page, $body, prefill_item);
		}
	}

	// Used by the Balance tab's warehouse-breakdown popover ("View Stock
	// Ledger →") to jump tabs and prefill the Item filter in one step.
	_open_ledger(item_code) {
		frappe.set_route("ib-stock-dashboard", "ledger");
		this._activate("ledger", item_code);
	}

	_teardown_active() {
		if (this._active && this._active._cleanup) this._active._cleanup();
		this._active = null;
	}

	_cleanup() {
		this._teardown_active();
		this._active_tab = null;
	}
}


/* ─── Balance tab (ex ib_stock_dashboard.js's IBStockDashboard) ─────────── */
class IBStockDashboard {
	constructor(page, $container) {
		this.page            = page;
		this.$body           = $container;
		this._data          = [];
		this._filtered_data = [];
		this._summary       = {};
		this._sort          = { col: null, asc: true };
		this._active_card   = null;
		this._page          = 1;
		this._page_size     = 20;
		this._ncols         = 6;
		this._restoring     = false;
		this._last_refresh  = null;
		this._search_debounce = null;
		this._search_tokens = [];
		this._search_chips  = [];
		this._STORAGE_KEY   = "ib_sd_v1";

		this._live = IBStock.make_live("ib-stock-dashboard", () => {
			this.refresh({ soft: true });
			this._flash_live();
		});
		this._auto = IBStock.make_auto_refresh(900, "ib-stock-dashboard", () => this.refresh());

		this._setup_filters();
		this._setup_content();
		this._setup_keyboard();
		this._restore_filters();
		this.refresh();
		this._live.start();
	}

	// ── Filters ──────────────────────────────────────────────────────────────

	_setup_filters() {
		$(this.page.page_form).addClass("ib-page-form");
		this.f_uom = this.page.add_field({
			fieldname: "uom",
			label:     __("UOM"),
			fieldtype: "Select",
			options:   "\nSQMT\nPCS\nKG",
			change:    () => { if (!this._restoring) this.refresh(); },
		});

		this.f_warehouse = this.page.add_field({
			fieldname: "warehouse",
			label:     __("Warehouse"),
			fieldtype: "Select",
			options:   "\nMAHARASHTRA - IB\nCHENNAI - IB\nGUJARAT - IB",
			change:    () => { if (!this._restoring) this.refresh(); },
		});

		this.f_search = this.page.add_field({
			fieldname:   "search",
			label:       __("Search"),
			fieldtype:   "Data",
			placeholder: __("name, code, colour, size…"),
		});

		const $pf    = $(this.f_search.wrapper).parent();
		const $group = $('<div class="ib-sl-search-group" style="margin-left:auto"></div>').appendTo($pf);
		$(this.f_search.wrapper).appendTo($group);

		this.$clear_btn = $(`<button class="btn btn-sm btn-primary ib-sl-clear-btn" title="${__("Clear all filters")}">${__("Clear")}</button>`)
			.on("click", () => this._clear_all())
			.appendTo($group);

		const $inp = $(this.f_search.wrapper).find("input");

		$inp.on("input", () => {
			if (this._restoring) return;
			clearTimeout(this._search_debounce);
			this._search_debounce = setTimeout(() => this._apply_search(), 160);
		});

		$inp.on("keydown", (e) => {
			if (this._restoring) return;
			if (e.key === "Enter") {
				const val = $inp.val().trim();
				if (!val) return;
				e.preventDefault();
				clearTimeout(this._search_debounce);
				this._search_chips.push(val);
				$inp.val("");
				this._apply_search();
			} else if (e.key === "Backspace" && $inp.val() === "") {
				if (this._search_chips.length) {
					this._search_chips.pop();
					this._apply_search();
				}
			}
		});
	}

	// ── Layout ───────────────────────────────────────────────────────────────

	_setup_content() {
		this.$body.addClass("ib-sd-page");

		this.$content = $(`
			<div class="ib-sd-wrap">
				<div class="ib-sd-cards"></div>
				<div class="ib-sd-chips" style="display:none"></div>
				<div class="ib-sd-table-wrap">
					<div class="ib-sd-table-scroll">
						<table class="ib-sd-table">
							<thead></thead>
							<tbody></tbody>
						</table>
					</div>
					<div class="ib-sd-empty" style="display:none"></div>
					<div class="ib-sd-pagination"></div>
				</div>
			</div>
		`).appendTo(this.$body);
	}

	// ── Keyboard shortcuts ───────────────────────────────────────────────────

	_setup_keyboard() {
		$(document).on("keydown.ib-stock-dashboard", (e) => {
			if (frappe.get_route()[0] !== "ib-stock-dashboard") return;

			if (e.key === "Escape" && this._$breakdown) {
				this._close_breakdown();
				return;
			}

			const tag = (e.target.tagName || "").toLowerCase();
			if (tag === "input" || tag === "textarea" || tag === "select") return;
			if (e.metaKey || e.ctrlKey || e.altKey) return;
			if (e.key.length !== 1) return;

			$(this.f_search.wrapper).find("input").first().focus();
		});
	}

	// ── Clear all filters ────────────────────────────────────────────────────

	_clear_all() {
		this._restoring = true;
		this.f_uom.set_value("");
		this.f_warehouse.set_value("");
		this._restoring    = false;
		this._search_chips = [];
		this._sort         = { col: null, asc: true };
		this._page         = 1;
		$(this.f_search.wrapper).find("input").val("");
		try { localStorage.removeItem(this._STORAGE_KEY); } catch (_) {}
		this.refresh();
	}

	// ── Filter persistence ────────────────────────────────────────────────────

	_save_filters() {
		try {
			localStorage.setItem(this._STORAGE_KEY, JSON.stringify({
				uom:          this.f_uom.get_value()          || "",
				warehouse:    this.f_warehouse.get_value()    || "",
					search:       $(this.f_search.wrapper).find("input").val() || "",
				search_chips: this._search_chips,
				sort_col:     this._sort.col  || "",
				sort_asc:     this._sort.asc  ? 1 : 0,
				page_size:    this._page_size,
			}));
		} catch (_) {}
	}

	_restore_filters() {
		try {
			const saved = JSON.parse(localStorage.getItem(this._STORAGE_KEY) || "null");
			if (!saved) return;
			this._restoring = true;
			if (saved.uom)         this.f_uom.set_value(saved.uom);
			if (saved.warehouse)   this.f_warehouse.set_value(saved.warehouse);
			if (saved.search)      $(this.f_search.wrapper).find("input").val(saved.search);
			if (Array.isArray(saved.search_chips)) this._search_chips = saved.search_chips;
			if (saved.sort_col) {
				this._sort.col = saved.sort_col;
				this._sort.asc = !!saved.sort_asc;
			}
			if (saved.page_size) this._page_size = saved.page_size;
			this._restoring = false;
		} catch (_) {
			this._restoring = false;
		}
	}

	// ── Live badge ────────────────────────────────────────────────────────────

	_flash_live() {
		const $badge = this.$content.find(".ib-sd-live-badge");
		$badge.addClass("ib-sd-live-badge--flash");
		setTimeout(() => $badge.removeClass("ib-sd-live-badge--flash"), 1200);
	}

	// ── Data fetch ────────────────────────────────────────────────────────────

	refresh({ soft = false } = {}) {
		this._page = 1;
		this._auto.stop();
		this._auto.start();
		this._close_breakdown();
		this._save_filters();
		this._set_loading(soft);

		frappe.call({
			method: "instabiz.instabiz.page.ib_stock_dashboard.ib_stock_dashboard.get_stock_data",
			args: {
				uom:       this.f_uom.get_value()       || null,
				warehouse: this.f_warehouse.get_value() || null,
			},
			callback: (r) => {
				this.$content.find("tbody").removeClass("ib-tbody-dimmed");
				if (!r.message) return;
				this._last_refresh = new Date();
				this._data         = r.message.data;
				this._summary      = r.message.summary;
				this._render_cards(r.message.summary);
				this._apply_search();
			},
			error: () => {
				this.$content.find("tbody").removeClass("ib-tbody-dimmed");
				this.$content.find("tbody").html(
					`<tr><td colspan="${this._ncols}" class="ib-sd-loading" style="color:var(--red-500)">
						${__("Failed to load. Open console for details.")}
					</td></tr>`
				);
			},
		});
	}

	_set_loading(soft = false) {
		this.$content.find(".ib-sd-empty").hide();
		this.$content.find(".ib-sd-table-scroll").show();
		this.$content.find(".ib-sd-pagination").empty();

		if (soft) {
			this.$content.find("tbody").addClass("ib-tbody-dimmed");
		} else {
			this.$content.find("tbody").html(`
				<tr>
					<td colspan="${this._ncols}" class="ib-sd-loading">
						<span class="ib-sd-spinner">
							<span></span><span></span><span></span>
						</span>
					</td>
				</tr>
			`);
		}
	}

	// ── Stat cards ────────────────────────────────────────────────────────────

	_icon(name) {
		const icons = {
			download: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v10m0 0-4-4m4 4 4-4"/><path d="M4 18v2h16v-2"/></svg>`,
			live: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/></svg>`,
			clock: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>`,
		};
		return `<span class="ib-sd-svg-icon ib-sd-svg-icon--${name}">${icons[name] || ""}</span>`;
	}

	_render_cards(s) {
		const cards = [
			{ id: "all",      label: __("Total Items"),   value: s.total,     accent: true  },
			{ id: "stock",    label: __("In Stock"),      value: s.in_stock                 },
			{ id: "low",      label: __("Low Stock"),     value: s.low_stock, warn: true    },
			{ id: "zero",     label: __("Zero Stock"),    value: s.zero                     },
			{ id: "negative", label: __("Over-reserved"), value: s.negative,  danger: true  },
		];

		const ts = this._last_refresh
			? this._last_refresh.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
			: "";

		const $cards = this.$content.find(".ib-sd-cards");
		$cards.html(cards.map(c => {
			const is_active  = this._active_card === c.id;
			const is_warn    = c.warn   && c.value > 0;
			const is_danger  = c.danger && c.value > 0;
			let cls = "ib-sd-card";
			if (c.accent)   cls += " ib-sd-card--accent";
			if (is_warn)    cls += " ib-sd-card--warn";
			if (is_danger)  cls += " ib-sd-card--danger";
			if (is_active)  cls += " ib-sd-card--active";
			return `
				<div class="${cls}" data-card="${c.id}" style="cursor:pointer">
					<div class="ib-sd-card-value">${c.value}</div>
					<div class="ib-sd-card-label">${c.label}</div>
				</div>
			`;
		}).join(""));

		$cards.append(`
			<div class="ib-sd-actions">
				<button class="ib-sd-action-btn ib-sd-export-btn" title="${__("Export current view as CSV")}">
					${this._icon("download")}
					${__("Export CSV")}
				</button>
				<button class="ib-sd-action-btn ib-sd-live-badge" title="${__("Click to Refresh Data")}">
					${this._icon("live")}
					${__("Live")}
				</button>
				${ts ? `<span class="ib-sd-refresh-time">${this._icon("clock")} ${__("Updated")} ${ts}</span>` : ""}
			</div>
		`);

		$cards.find(".ib-sd-card").on("click", (e) => {
			this._on_card_click($(e.currentTarget).data("card"));
		});
		$cards.find(".ib-sd-export-btn").on("click", () => this._export_csv());
		$cards.find(".ib-sd-live-badge").on("click", () => this.refresh());
	}

	_sync_cards() {
		this.$content.find(".ib-sd-card").each((_, el) => {
			$(el).toggleClass("ib-sd-card--active", this._active_card === $(el).data("card"));
		});
	}

	_on_card_click(id) {
		if (id === "all") {
			this._active_card  = null;
			this._search_chips = [];
			this._restoring    = true;
			this.f_uom.set_value("");
			this.f_warehouse.set_value("");
			this.f_search.set_value("");
			$(this.f_search.wrapper).find("input").val("");
			this._restoring = false;
			this._filtered_data = [];
			this._sync_cards();
			this.refresh();
		} else {
			this._active_card = (this._active_card === id) ? null : id;
			this._sync_cards();
			this._apply_search();
		}
	}

	// ── Active filter chips ───────────────────────────────────────────────────

	_render_chips() {
		const $chips = this.$content.find(".ib-sd-chips");
		const esc    = frappe.utils.escape_html;
		const chips  = [];

		const _clear_server = (fn) => () => {
			this._restoring = true;
			Promise.resolve(fn()).finally(() => {
				this._restoring = false;
				this.refresh();
			});
		};

		const uom = this.f_uom.get_value();
		if (uom) chips.push({ label: uom, type: `uom-${uom.toLowerCase()}`, clear: _clear_server(() => this.f_uom.set_value("")) });

		const wh = this.f_warehouse.get_value();
		if (wh) chips.push({ label: wh.split(" - ")[0], type: "wh", clear: _clear_server(() => this.f_warehouse.set_value("")) });

		this._search_chips.forEach((chip, idx) => {
			chips.push({
				label: `"${chip}"`,
				type:  "search",
				clear: () => {
					this._search_chips.splice(idx, 1);
					this._apply_search();
				},
			});
		});

		const card_labels = {
			stock:    __("In Stock"),
			low:      __("Low Stock"),
			zero:     __("Zero Stock"),
			negative: __("Over-reserved"),
		};
		if (this._active_card && card_labels[this._active_card]) {
			chips.push({
				label: card_labels[this._active_card],
				type:  this._active_card,
				clear: () => { this._active_card = null; this._sync_cards(); this._apply_search(); },
			});
		}

		if (!chips.length) { $chips.empty().hide(); return; }

		$chips.html(
			chips.map((c, i) => `
				<span class="ib-chip ib-chip--${c.type}" data-idx="${i}">${esc(c.label)}<button class="ib-chip-x" aria-label="${__("Remove")}">×</button></span>
			`).join("")
		).show();

		$chips.find(".ib-chip").each((i, el) => {
			$(el).find(".ib-chip-x").on("click", (ev) => { ev.stopPropagation(); chips[i].clear(); });
		});

		if (chips.length > 1) {
			$chips.append(`<button class="ib-chip-clear-all">${__("Clear all")}</button>`);
			$chips.find(".ib-chip-clear-all").on("click", () => this._on_card_click("all"));
		}
	}

	// ── Table ─────────────────────────────────────────────────────────────────

	_columns() {
		const wh          = this.f_warehouse.get_value();
		const stock_label = wh ? wh.split(" - ")[0] : __("SQM / Qty");
		return [
			{ id: "item_name",       label: __("Item Name"),     cls: "ib-col-name"             },
			{ id: "item_code",       label: __("Item Code"),     cls: "ib-col-code"             },
			{ id: "specification",   label: __("Specification"), cls: "ib-col-spec"             },
			{ id: "uom",             label: __("UOM"),           cls: "ib-col-uom"              },
			{ id: "rolls",           label: __("Rolls"),         cls: "ib-col-qty"              },
			{ id: "total_stock",     label: stock_label,         cls: "ib-col-qty ib-col-total" },
			{ id: "total_available", label: __("Available"),     cls: "ib-col-qty",
			  tip: __("Total Stock minus reserved quantity. Negative means more is committed to open orders than is physically in stock (over-reserved).") },
		];
	}

	_render_table(data) {
		const cols   = this._columns();
		this._ncols  = cols.length;
		const $thead = this.$content.find("thead");
		const $tbody = this.$content.find("tbody");
		const $empty = this.$content.find(".ib-sd-empty");
		const $scroll = this.$content.find(".ib-sd-table-scroll");

		$thead.html(`<tr>${
			cols.map(c => `
				<th class="${c.cls}" data-col="${c.id}">
					${c.label}${c.tip ? `<span class="ib-sd-th-tip" title="${frappe.utils.escape_html(c.tip)}">?</span>` : ""}<span class="ib-sort-icon"></span>
				</th>
			`).join("")
		}</tr>`);

		$thead.find("th").on("click", (e) => {
			const col = $(e.currentTarget).data("col");
			this._sort.asc = (this._sort.col === col) ? !this._sort.asc : true;
			this._sort.col = col;
			this._save_filters();
			this._render_table(this._filtered_data);
		});

		$thead.find("th").each((_, th) => {
			$(th).find(".ib-sort-icon").text(
				this._sort.col === $(th).data("col") ? (this._sort.asc ? " ↑" : " ↓") : ""
			);
		});

		if (!data || data.length === 0) {
			$scroll.hide();
			const has_search = this._search_tokens.length > 0;
			let msg;
			if (this._active_card === "zero" && !has_search) {
				msg = __("All items have stock");
			} else if (this._active_card === "negative" && !has_search) {
				msg = __("No over-reserved items");
			} else if (this._active_card === "low" && !has_search) {
				msg = __("No low stock items");
			} else if (has_search) {
				const terms = [
					...this._search_chips,
					($(this.f_search.wrapper).find("input").val() || "").trim(),
				].filter(Boolean);
				msg = terms.length
					? `${__("No matches for")} "${terms.join('", "')}"`
					: __("No items match your search");
			} else {
				msg = __("No items found for these filters");
			}
			$empty.text(msg).show();
			this.$content.find(".ib-sd-pagination").empty();
			return;
		}

		$empty.hide();
		$scroll.show();

		const rows = IBStock.sort_rows(data, this._sort.col, this._sort.asc);

		const total     = rows.length;
		const ps        = this._page_size;
		const max_pages = Math.ceil(total / ps);
		if (this._page > max_pages) this._page = max_pages || 1;
		const start   = (this._page - 1) * ps;
		const end     = Math.min(start + ps, total);
		const page_rows = rows.slice(start, end);
		this._render_pagination(total, start, end, max_pages);

		const esc = frappe.utils.escape_html;

		$tbody.html(page_rows.map(row => {
			const low_cls = row.low_stock ? " ib-row-low-stock" : "";
			return `
				<tr class="ib-sd-row${low_cls}" data-item-code="${esc(row.item_code || "")}"
					title="${__("Click to see warehouse breakdown")}">
					<td class="ib-col-name">${IBStock.highlight(row.item_name, this._search_tokens)}</td>
					<td class="ib-col-code">
						<a href="/app/item/${encodeURIComponent(row.item_code)}" target="_blank">
							${IBStock.highlight(row.item_code, this._search_tokens)}
						</a>
					</td>
					<td class="ib-col-spec">${this._spec_cell(row)}</td>
					<td class="ib-col-uom">${esc(row.uom || "")}</td>
					<td class="ib-col-qty">${row.rolls != null && row.rolls !== "" ? this._qty(row.rolls) : "—"}</td>
					<td class="ib-col-qty ib-col-total">${this._qty(row.total_stock)}</td>
					<td class="ib-col-qty">${this._qty(row.total_available, true)}</td>
				</tr>
			`;
		}).join(""));

		$tbody.off("click.breakdown").on("click.breakdown", "tr.ib-sd-row", (e) => {
			if ($(e.target).is("a, button")) return;
			const $tr       = $(e.currentTarget);
			const item_code = $tr.data("item-code");
			if (this._$breakdown && $tr.hasClass("ib-row-active")) {
				this._close_breakdown();
				return;
			}
			const row = this._data.find(r => r.item_code === item_code);
			if (row) this._show_breakdown(row, e);
		});
	}

	_apply_search() {
		this._save_filters();
		const live        = ($(this.f_search.wrapper).find("input").val() || "").trim();
		const live_tokens = live.toLowerCase().split(/\s+/).filter(Boolean);
		const chip_tokens = this._search_chips.map(c => c.toLowerCase());
		const all_tokens  = [...chip_tokens, ...live_tokens];
		this._search_tokens = all_tokens;

		let base = this._data;
		if      (this._active_card === "stock")    base = base.filter(r => Number(r.total_stock) > 0);
		else if (this._active_card === "zero")     base = base.filter(r => Number(r.total_stock) === 0);
		else if (this._active_card === "negative") base = base.filter(r => Number(r.total_available) < 0);
		else if (this._active_card === "low")      base = base.filter(r => r.low_stock);


		this._filtered_data = all_tokens.length
			? base.filter(row => {
				const hay = [
					row.item_name      || "",
					row.item_code      || "",
					row.specification  || "",
					row.spec_color     || "",
					row.spec_liner     || "",
					row.spec_thickness || "",
					row.spec_adhesive  || "",
					row.spec_sqmt ? String(row.spec_sqmt) : "",
				].join(" ").toLowerCase();
				return all_tokens.every(t => hay.includes(t));
			})
			: base;

		this._page = 1;
		this._render_chips();
		this._render_table(this._filtered_data);
	}

	_render_pagination(total, start, end, max_pages) {
		const $pg   = this.$content.find(".ib-sd-pagination");
		const sizes = [20, 50, 100, 500];

		const is_filtered = this._filtered_data.length !== this._data.length;
		const count_label = is_filtered
			? `${start + 1}–${end} of <strong>${total}</strong> matches <span class="ib-sd-pg-total">(${this._data.length} total)</span>`
			: `${start + 1}–${end} of ${total}`;

		$pg.html(`
			<div class="ib-sd-pg-left">
				<span class="ib-sd-pg-info">${count_label}</span>
				<div class="ib-sd-pg-nav">
					<button class="ib-sd-pg-btn" data-action="prev" ${this._page <= 1 ? "disabled" : ""}>&#8249;</button>
					<span class="ib-sd-pg-num">${this._page} / ${max_pages}</span>
					<button class="ib-sd-pg-btn" data-action="next" ${this._page >= max_pages ? "disabled" : ""}>&#8250;</button>
				</div>
			</div>
			<div class="ib-sd-pg-right">
				<span class="ib-sd-pg-label">${__("Per page")}</span>
				${sizes.map(s => `
					<button class="ib-sd-pg-size ${this._page_size === s ? "active" : ""}" data-size="${s}">${s}</button>
				`).join("")}
			</div>
		`);

		$pg.find("[data-action='prev']").on("click", () => {
			this._page--;
			this._render_table(this._filtered_data);
		});
		$pg.find("[data-action='next']").on("click", () => {
			this._page++;
			this._render_table(this._filtered_data);
		});
		$pg.find(".ib-sd-pg-size").on("click", (e) => {
			this._page_size = parseInt($(e.currentTarget).data("size"));
			this._page      = 1;
			this._save_filters();
			this._render_table(this._filtered_data);
		});
	}

	// ── Warehouse breakdown popover ───────────────────────────────────────────

	_show_breakdown(row, e) {
		this._close_breakdown();

		const esc         = frappe.utils.escape_html;
		const total_stock = Number(row.total_stock   || 0);
		const total_avail = Number(row.total_available || 0);

		const whs = [
			{ label: "Maharashtra", stock: Number(row.maharashtra || 0), res: Number(row.mh_reserved || 0), reorder: Number(row.mh_reorder_level || 0) },
			{ label: "Chennai",     stock: Number(row.chennai     || 0), res: Number(row.cn_reserved  || 0), reorder: Number(row.cn_reorder_level || 0) },
			{ label: "Gujarat",     stock: Number(row.gujarat     || 0), res: Number(row.gj_reserved  || 0), reorder: Number(row.gj_reorder_level || 0) },
		];
		const total_res     = whs.reduce((s, w) => s + w.res, 0);
		const total_reorder = whs.reduce((s, w) => s + w.reorder, 0);
		const max_stock     = Math.max(...whs.map(w => w.stock), 1);

		let status, status_cls;
		if (total_stock === 0)    { status = __("No Stock");      status_cls = "ib-status--none";   }
		else if (total_avail < 0) { status = __("Over-reserved"); status_cls = "ib-status--danger"; }
		else if (row.low_stock)   { status = __("Low Stock");     status_cls = "ib-status--warn";   }
		else                      { status = __("Healthy");        status_cls = "ib-status--good";   }

		const rows_html = whs.map(w => {
			const avail      = w.stock - w.res;
			const avail_cls  = avail < 0 ? "ib-qty-negative" : avail > 0 ? "ib-qty-positive" : "ib-qty-zero";
			const stock_cls  = w.stock > 0 ? "ib-qty-positive" : "ib-qty-zero";
			const bar_pct    = Math.round(w.stock / max_stock * 100);
			const res_pct    = w.stock > 0 ? Math.round(w.res / w.stock * 100) : 0;
			const res_label  = w.res > 0
				? `<span class="ib-bd-warn">${w.res.toLocaleString()}</span> <span class="ib-bd-pct">(${res_pct}%)</span>`
				: `<span class="ib-bd-zero">—</span>`;
			const reorder_label = w.reorder > 0
				? w.reorder.toLocaleString()
				: `<span class="ib-bd-zero">—</span>`;
			return `<tr>
				<td class="ib-bd-loc">${w.label}</td>
				<td class="ib-bd-num">
					<span class="${stock_cls}">${w.stock.toLocaleString()}</span>
					<div class="ib-bd-bar">
						<div class="ib-bd-bar-stock" style="width:${bar_pct}%">
							<div class="ib-bd-bar-res" style="width:${res_pct}%"></div>
						</div>
					</div>
				</td>
				<td class="ib-bd-num">${res_label}</td>
				<td class="ib-bd-num ib-bd-reorder">${reorder_label}</td>
				<td class="ib-bd-num"><span class="${avail_cls}">${avail.toLocaleString()}</span></td>
			</tr>`;
		}).join("");

		const avail_cls         = total_avail < 0 ? "ib-qty-negative" : total_avail > 0 ? "ib-qty-positive" : "ib-qty-zero";
		const total_stock_cls   = total_stock > 0 ? "ib-qty-positive" : "ib-qty-zero";
		const tot_res_pct       = total_stock > 0 ? Math.round(total_res / total_stock * 100) : 0;
		const tot_res_label     = total_res > 0
			? `<span class="ib-bd-warn">${total_res.toLocaleString()}</span> <span class="ib-bd-pct">(${tot_res_pct}%)</span>`
			: `<span class="ib-bd-zero">—</span>`;
		const tot_reorder_label = total_reorder > 0
			? total_reorder.toLocaleString()
			: `<span class="ib-bd-zero">—</span>`;

		const saved_tokens  = this._search_tokens;
		this._search_tokens = [];
		const spec_html     = this._spec_cell(row);
		this._search_tokens = saved_tokens;
		const has_spec      = row.spec_dimension || row.spec_thickness || row.spec_color || row.spec_liner;

		const $pop = $(`
			<div class="ib-sd-breakdown">
				<div class="ib-breakdown-hdr">
					<div class="ib-breakdown-meta">
						<div class="ib-breakdown-name">${esc(row.item_name || "")}</div>
						<a class="ib-breakdown-code" href="/app/item/${encodeURIComponent(row.item_code || "")}" target="_blank">${esc(row.item_code || "")}</a>
						${has_spec ? `<div class="ib-breakdown-tags">${spec_html}</div>` : ""}
						<span class="ib-breakdown-uom">${esc(row.uom || "")}</span>
					</div>
					<button class="ib-breakdown-close" title="${__("Close")}">×</button>
				</div>
				<div class="ib-breakdown-status ${status_cls}">${status}</div>
				<table class="ib-breakdown-table">
					<thead>
						<tr>
							<th>${__("Warehouse")}</th>
							<th>${__("Stock")}</th>
							<th>${__("Reserved")}</th>
							<th>${__("Reorder")}</th>
							<th>${__("Available")}</th>
						</tr>
					</thead>
					<tbody>${rows_html}</tbody>
					<tfoot>
						<tr>
							<td>${__("Total")}</td>
							<td class="ib-bd-num"><span class="${total_stock_cls}">${total_stock.toLocaleString()}</span></td>
							<td class="ib-bd-num">${tot_res_label}</td>
							<td class="ib-bd-num ib-bd-reorder">${tot_reorder_label}</td>
							<td class="ib-bd-num"><span class="${avail_cls}">${total_avail.toLocaleString()}</span></td>
						</tr>
					</tfoot>
				</table>
				<div class="ib-breakdown-footer">
					<a class="ib-breakdown-report-link" href="#"
						data-item="${frappe.utils.escape_html(row.item_code || "")}">
						${__("View Stock Ledger")} →
					</a>
				</div>
			</div>
		`).css({ visibility: "hidden", position: "fixed", left: 0, top: 0 })
			.appendTo("body");

		const $backdrop = $('<div class="ib-breakdown-backdrop"></div>').appendTo("body");
		$backdrop.on("click", () => this._close_breakdown());

		const pw   = $pop.outerWidth();
		const ph   = $pop.outerHeight();
		const left = (window.innerWidth - e.clientX) >= pw + 20
			? e.clientX + 14
			: e.clientX - pw - 14;
		const top  = Math.max(8, Math.min(e.clientY + 14, window.innerHeight - ph - 12));
		$pop.css({ visibility: "visible", left, top });

		this.$content.find("tbody tr").removeClass("ib-row-active");
		this.$content.find(`tbody tr[data-item-code="${esc(row.item_code)}"]`).addClass("ib-row-active");

		$pop.find(".ib-breakdown-close").on("click", () => this._close_breakdown());

		$pop.find(".ib-breakdown-report-link").on("click", (ev) => {
			ev.preventDefault();
			const item_code = $(ev.currentTarget).data("item");
			this._close_breakdown();
			const shell = frappe.pages["ib-stock-dashboard"]._shell;
			if (shell) shell._open_ledger(item_code);
		});

		this._$backdrop  = $backdrop;
		this._$breakdown = $pop;
	}

	_close_breakdown() {
		if (this._$backdrop)  { this._$backdrop.remove();  this._$backdrop  = null; }
		if (this._$breakdown) { this._$breakdown.remove(); this._$breakdown = null; }
		this.$content && this.$content.find("tbody tr").removeClass("ib-row-active");
	}

	// ── Spec cell ─────────────────────────────────────────────────────────────

	_spec_cell(row) {
		const hl         = (v) => IBStock.highlight(v, this._search_tokens);
		const color_html = row.spec_color
			? `${IBStock.color_dots(row.spec_color)}${hl(row.spec_color)}`
			: null;
		const dim_text = row.spec_dimension
			? hl(row.spec_dimension) + (row.spec_sqmt
				? ` <span class="ib-spec-sqmt">${hl(String(row.spec_sqmt))} SQMT</span>`
				: "")
			: null;
		const parts = [
			row.spec_dimension ? { cls: "ib-spec-dim",   text: dim_text              } : null,
			row.spec_thickness ? { cls: "ib-spec-thick", text: hl(row.spec_thickness) } : null,
			row.spec_color     ? { cls: "ib-spec-color", text: color_html              } : null,
			row.spec_liner     ? { cls: "ib-spec-liner", text: hl(row.spec_liner)      } : null,
		].filter(Boolean);

		if (!parts.length) return `<span class="text-muted">—</span>`;

		return parts.map((p, i) => `
			${i > 0 ? `<span class="ib-spec-sep"></span>` : ""}
			<span class="ib-spec-tag ${p.cls}">${p.text}</span>
		`).join("");
	}

	_qty(val, color = false) {
		const n = Number(val);
		if (!n) return `<span class="ib-qty-zero">0</span>`;
		if (color) {
			return `<span class="${n < 0 ? "ib-qty-negative" : "ib-qty-positive"}">${n.toLocaleString()}</span>`;
		}
		return `<span>${n.toLocaleString()}</span>`;
	}

	// ── Export CSV ────────────────────────────────────────────────────────────

	_export_csv() {
		if (!this._filtered_data || !this._filtered_data.length) {
			frappe.msgprint(__("Nothing to export."));
			return;
		}

		const wh = this.f_warehouse.get_value();

		const headers = [
			__("Item Name"), __("Item Code"), __("UOM"),
			__("Width (mm)"), __("Length (mtr)"), __("Thickness"), __("Color"), __("Liner"),
		];
		if (!wh) {
			headers.push(
				__("MH Stock"), __("MH Reserved"),
				__("CN Stock"), __("CN Reserved"),
				__("GJ Stock"), __("GJ Reserved"),
			);
		}
		headers.push(__("Total Stock"), __("Total Reserved"), __("Available"));

		IBStock.csv_download(
			`stock_balance_${frappe.datetime.now_date()}.csv`,
			headers,
			IBStock.sort_rows(this._filtered_data, this._sort.col, this._sort.asc),
			row => {
				const total_res = Number(row.mh_reserved || 0) + Number(row.cn_reserved || 0) + Number(row.gj_reserved || 0);
				const vals = [
					row.item_name      || "",
					row.item_code      || "",
					row.uom            || "",
					row.spec_width     || "",
					row.spec_length    || "",
					row.spec_thickness || "",
					row.spec_color     || "",
					row.spec_liner     || "",
				];
				if (!wh) {
					vals.push(
						row.maharashtra  ?? 0, row.mh_reserved ?? 0,
						row.chennai      ?? 0, row.cn_reserved ?? 0,
						row.gujarat      ?? 0, row.gj_reserved ?? 0,
					);
				}
				vals.push(row.total_stock ?? 0, total_res, row.total_available ?? 0);
				return vals;
			}
		);
	}

	_cleanup() {
		this._live && this._live.stop();
		this._auto && this._auto.stop();
		$(document).off("keydown.ib-stock-dashboard");
		this._close_breakdown();
	}
}


/* ─── Ledger tab (ex ib_stock_ledger.js's IbStockLedger) ─────────────────── */
const _STOCK_LEDGER_COLS = [
	{ key: "posting_datetime",      label: "Date",    sortable: true  },
	{ key: "item_code",             label: "Item",    sortable: true  },
	{ key: null,                    label: "WH",      sortable: false },
	{ key: "qty_in",                label: "In",      sortable: true,  num: true },
	{ key: "qty_out",               label: "Out",     sortable: true,  num: true },
	{ key: "qty_after_transaction", label: "Balance", sortable: true,  num: true },
	{ key: "party",                 label: "Party",   sortable: true  },
	{ key: "voucher_no",            label: "Voucher", sortable: false },
	{ key: "rate",                  label: "Rate",    sortable: true,  num: true },
];

class IbStockLedger {
	constructor(page, $container, prefill_item_code) {
		this.page              = page;
		this.$body             = $container;
		this._data            = [];
		this._filtered_data   = [];
		this._total           = 0;
		this._summary         = {};
		this._page            = 1;
		this._page_size       = 50;
		this._loading         = false;
		this._restoring       = false;
		// Set before _restore_filters()/refresh() so both the localStorage
		// restore (which no-ops when this is set, see its own guard) and the
		// single construction-time refresh() below pick this up naturally —
		// no second post-construction refresh() call, which would race
		// against this one if it's still in flight (see the shell's
		// _activate() comment for how that bit us live).
		this._prefill_item    = prefill_item_code || null;
		this._last_refresh    = null;
		this._sort            = { col: null, asc: true };
		this._search_tokens   = [];
		this._search_chips    = [];
		this._search_debounce = null;
		this._STORAGE_KEY     = "ib_sl_v4";

		this._setup_filters();
		this._setup_content();
		this._setup_presets();
		this._setup_keyboard();
		this._restore_filters();
		this.refresh();
	}

	// ── Filters ──────────────────────────────────────────────────────────────

	_setup_filters() {
		$(this.page.page_form).addClass("ib-page-form");
		this.f_item = this.page.add_field({
			fieldname: "item_code",
			label:     __("Item"),
			fieldtype: "Link",
			options:   "Item",
			change:    () => { if (!this._restoring) this._reset_and_refresh(); },
		});

		this.f_warehouse = this.page.add_field({
			fieldname: "warehouse",
			label:     __("Warehouse"),
			fieldtype: "Select",
			options:   "\nMAHARASHTRA - IB\nCHENNAI - IB\nGUJARAT - IB",
			change:    () => { if (!this._restoring) this._reset_and_refresh(); },
		});

		this.f_customer = this.page.add_field({
			fieldname: "customer",
			label:     __("Customer"),
			fieldtype: "Link",
			options:   "Customer",
			change:    () => { if (!this._restoring) this._reset_and_refresh(); },
		});

		this.f_from = this.page.add_field({
			fieldname: "from_date",
			label:     __("From"),
			fieldtype: "Date",
			default:   frappe.datetime.add_days(frappe.datetime.get_today(), -30),
			change:    () => { if (!this._restoring) this._reset_and_refresh(); },
		});

		this.f_to = this.page.add_field({
			fieldname: "to_date",
			label:     __("To"),
			fieldtype: "Date",
			default:   frappe.datetime.get_today(),
			change:    () => { if (!this._restoring) this._reset_and_refresh(); },
		});

		this.f_vtype = this.page.add_field({
			fieldname: "voucher_type",
			label:     __("Voucher Type"),
			fieldtype: "Select",
			options:   "\nDelivery Note\nSales Invoice\nSales Order\nPurchase Receipt\nPurchase Invoice\nPurchase Order\nStock Entry\nStock Reconciliation",
			change:    () => { if (!this._restoring) this._reset_and_refresh(); },
		});

		this.f_search = this.page.add_field({
			fieldname:   "search",
			label:       __("Search"),
			fieldtype:   "Data",
			placeholder: __("item, party, voucher…"),
		});
		const $pf    = $(this.f_search.wrapper).parent();
		const $group = $('<div class="ib-sl-search-group"></div>').appendTo($pf);
		$(this.f_search.wrapper).appendTo($group);

		this.$clear_btn = $(`<button class="btn btn-sm btn-primary ib-sl-clear-btn" title="${__("Clear all filters")}">${__("Clear")}</button>`)
			.on("click", () => this._clear_all())
			.appendTo($group);

		const $inp = $(this.f_search.wrapper).find("input");
		$inp.on("input", () => {
			clearTimeout(this._search_debounce);
			this._search_debounce = setTimeout(() => this._apply_client_filter(), 160);
		});
		$inp.on("keydown", (e) => {
			if (e.key === "Enter") {
				const val = $inp.val().trim();
				if (!val) return;
				e.preventDefault();
				clearTimeout(this._search_debounce);
				this._search_chips.push(val);
				$inp.val("");
				this._apply_client_filter();
			} else if (e.key === "Backspace" && $inp.val() === "") {
				if (this._search_chips.length) {
					this._search_chips.pop();
					this._apply_client_filter();
				}
			}
		});
	}

	// ── Layout ───────────────────────────────────────────────────────────────

	_setup_content() {
		this.$body.addClass("ib-sl-page");

		const thead_html = _STOCK_LEDGER_COLS.map(c => {
			const cls   = [c.sortable ? "ib-sl-th-sortable" : "", c.num ? "ib-sl-th-num" : ""].filter(Boolean).join(" ");
			const attrs = [cls ? `class="${cls}"` : "", c.sortable ? `data-col="${c.key}"` : ""].filter(Boolean).join(" ");
			return `<th${attrs ? " " + attrs : ""}>${__(c.label)}<span class="ib-sort-icon"></span></th>`;
		}).join("");

		this.$content = $(`
			<div class="ib-sl-wrap">
				<div class="ib-sl-cards"></div>
				<div class="ib-sl-presets"></div>
				<div class="ib-sl-chips" style="display:none"></div>
				<div class="ib-sl-table-wrap">
					<table class="ib-sl-table">
						<thead class="ib-sl-thead"><tr>${thead_html}</tr></thead>
						<tbody class="ib-sl-tbody"></tbody>
						<tfoot class="ib-sl-tfoot"></tfoot>
					</table>
					<div class="ib-sl-empty" style="display:none"></div>
				</div>
				<div class="ib-sl-pagination"></div>
			</div>
		`).appendTo(this.$body);

		this.$cards    = this.$content.find(".ib-sl-cards");
		this.$presets  = this.$content.find(".ib-sl-presets");
		this.$chips    = this.$content.find(".ib-sl-chips");
		this.$tbody    = this.$content.find(".ib-sl-tbody");
		this.$tfoot    = this.$content.find(".ib-sl-tfoot");
		this.$empty    = this.$content.find(".ib-sl-empty");
		this.$pg       = this.$content.find(".ib-sl-pagination");

		this.$content.find(".ib-sl-th-sortable").on("click", (e) => {
			const col = $(e.currentTarget).data("col");
			this._sort.asc = (this._sort.col === col) ? !this._sort.asc : true;
			this._sort.col = col;
			this._update_sort_icons();
			this._apply_client_filter();
		});
	}

	_setup_presets() {
		const today = frappe.datetime.get_today;
		const add   = frappe.datetime.add_days;
		const presets = [
			{ label: __("Today"),      fn: () => [today(), today()] },
			{ label: __("This week"),  fn: () => [frappe.datetime.week_start(), today()] },
			{ label: __("This month"), fn: () => [frappe.datetime.month_start(), today()] },
			{ label: __("Last 7d"),    fn: () => [add(today(), -6), today()] },
			{ label: __("Last 30d"),   fn: () => [add(today(), -29), today()] },
		];

		this.$presets.html(
			`<div class="ib-sl-preset-bar">` +
			presets.map((p, i) => `<button class="ib-sl-preset-btn" data-idx="${i}">${p.label}</button>`).join("") +
			`</div>`
		);

		this.$presets.find(".ib-sl-preset-btn").on("click", (e) => {
			const idx = parseInt($(e.currentTarget).data("idx"), 10);
			const [from, to] = presets[idx].fn();
			this._restoring = true;
			this.f_from.set_value(from);
			this.f_to.set_value(to);
			this._restoring = false;
			this._reset_and_refresh();
		});
	}

	_setup_keyboard() {
		$(document).on("keydown.ib-stock-ledger", (e) => {
			if (frappe.get_route()[0] !== "ib-stock-dashboard") return;
			const tag = (e.target.tagName || "").toLowerCase();
			if (tag === "input" || tag === "textarea" || tag === "select") return;
			if (e.metaKey || e.ctrlKey || e.altKey) return;
			if (e.key.length !== 1) return;
			$(this.f_search.wrapper).find("input").first().focus();
		});
	}

	// ── Data fetch ────────────────────────────────────────────────────────────

	_reset_and_refresh() {
		this._data          = [];
		this._filtered_data = [];
		this._page          = 1;
		this._search_chips  = [];
		$(this.f_search.wrapper).find("input").val("");
		this.$tbody.empty();
		this._save_filters();
		this.refresh();
	}

	refresh() {
		if (this._loading) return;

		if (this._prefill_item) {
			this._restoring = true;
			this.f_item.set_value(this._prefill_item);
			this._prefill_item = null;
			this._restoring    = false;
		}

		const from_date = this.f_from.get_value();
		const to_date   = this.f_to.get_value();

		if (!from_date && !to_date) {
			this._show_idle();
			return;
		}

		this._save_filters();
		this._loading = true;

		const offset = (this._page - 1) * this._page_size;

		this.$tbody.empty();
		this.$cards.html(`<span class="ib-sl-spinner"><div class="ib-sl-spin"></div>${__("Loading…")}</span>`);

		frappe.call({
			method: "instabiz.instabiz.page.ib_stock_ledger.ib_stock_ledger.get_ledger",
			args: {
				item_code:    this.f_item.get_value()      || null,
				warehouse:    this.f_warehouse.get_value() || null,
				from_date:    from_date                    || null,
				to_date:      to_date                      || null,
				voucher_type: this.f_vtype.get_value()     || null,
				customer:     this.f_customer.get_value()  || null,
				limit:        this._page_size,
				offset,
			},
			callback: (r) => {
				this._loading      = false;
				if (!r.message) return;
				const { data, total, summary } = r.message;
				this._total        = total;
				this._summary      = summary || {};
				this._data         = data;
				this._last_refresh = new Date();
				this._render_cards();
				this._apply_client_filter();
			},
			error: () => { this._loading = false; },
		});
	}

	// ── Stat cards ────────────────────────────────────────────────────────────

	_icon(name) {
		const icons = {
			activity: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 12h4l3-7 4 14 3-7h4"/></svg>`,
			arrow_up: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V5m0 0-5 5m5-5 5 5"/></svg>`,
			arrow_down: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14m0 0-5-5m5 5 5-5"/></svg>`,
			clock: `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>`,
			calendar: `<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="17" rx="2"/><path d="M8 2v4m8-4v4M3 10h18"/></svg>`,
			inbox: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4h16l-2 10h-4l-2 3-2-3H6z"/><path d="M9 14h6"/></svg>`,
			download: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v10m0 0-4-4m4 4 4-4"/><path d="M4 18v2h16v-2"/></svg>`,
		};
		return `<span class="ib-sl-svg-icon ib-sl-svg-icon--${name}">${icons[name] || ""}</span>`;
	}

	_render_cards() {
		const fmt = n => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
		const ts  = this._last_refresh
			? this._last_refresh.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
			: "";

		this.$cards.html(`
			<div class="ib-sl-summary">
				<span class="ib-sl-stat">
					<span class="ib-sl-stat-icon">${this._icon("activity")}</span>
					<span class="ib-sl-stat-value">${(this._total || 0).toLocaleString()}</span>
					<span class="ib-sl-stat-label">${__("movements")}</span>
				</span>
				<span class="ib-sl-stat-sep">·</span>
				<span class="ib-sl-stat ib-sl-stat--in">
					<span class="ib-sl-stat-icon">${this._icon("arrow_up")}</span>
					<span class="ib-sl-stat-value">${fmt(this._summary.qty_in)}</span>
					<span class="ib-sl-stat-label">${__("stock received")}</span>
				</span>
				<span class="ib-sl-stat-sep">·</span>
				<span class="ib-sl-stat ib-sl-stat--out">
					<span class="ib-sl-stat-icon">${this._icon("arrow_down")}</span>
					<span class="ib-sl-stat-value">${fmt(this._summary.qty_out)}</span>
					<span class="ib-sl-stat-label">${__("stock issued")}</span>
				</span>
			</div>
			<div class="ib-sl-actions">
				<button class="ib-sl-action-btn ib-sl-export-btn" title="${__("Export current view as CSV")}">
					${this._icon("download")}
					${__("Export CSV")}
				</button>
				${ts ? `<span class="ib-sl-refresh-time">${this._icon("clock")} ${__("Updated")} ${ts}</span>` : ""}
			</div>
		`);

		this.$cards.find(".ib-sl-export-btn").on("click", () => this._export_csv());
	}

	// ── Client-side filter + sort + render ────────────────────────────────────

	_apply_client_filter() {
		const live        = ($(this.f_search.wrapper).find("input").val() || "").trim();
		const live_tokens = live.toLowerCase().split(/\s+/).filter(Boolean);
		const chip_tokens = this._search_chips.map(c => c.toLowerCase());
		this._search_tokens = [...chip_tokens, ...live_tokens];

		let rows = [...this._data];

		if (this._search_tokens.length) {
			rows = rows.filter(r => {
				const hay = [
					r.item_code, r.item_name, r.party, r.voucher_no,
					r.wh_short, r.vtype_short, r.color, r.custom_thickness, r.custom_adhesive_type,
				].join(" ").toLowerCase();
				return this._search_tokens.every(t => hay.includes(t));
			});
		}

		rows = IBStock.sort_rows(rows, this._sort.col, this._sort.asc);

		this._filtered_data = rows;
		this.$tbody.empty();
		this.$empty.hide();

		if (rows.length) {
			this._render_rows(rows);
		} else {
			this._show_empty();
		}

		this._render_chips();
		this._render_tfoot();
		this._update_sort_icons();
		this._render_pagination();
	}

	// ── Rendering ─────────────────────────────────────────────────────────────

	_render_rows(data) {
		const esc  = frappe.utils.escape_html;
		const hl   = (v) => IBStock.highlight(v, this._search_tokens);
		const frag = document.createDocumentFragment();

		data.forEach(r => {
			const direction = r.actual_qty > 0 ? "in" : r.actual_qty < 0 ? "out" : "zero";
			const spec_html = this._spec_html(r);

			const item_link = `/app/item/${encodeURIComponent(r.item_code)}`;
			const doc_link  = r.voucher_no
				? `/app/${(r.voucher_type || "").toLowerCase().replace(/ /g, "-")}/${encodeURIComponent(r.voucher_no)}`
				: "#";

			const wh_cls = { MH: "ib-sl-wh--mh", CN: "ib-sl-wh--cn", GJ: "ib-sl-wh--gj" }[r.wh_short] || "";
			const vt_cls = {
				DN: "ib-sl-vt--dn", SI: "ib-sl-vt--si", SO: "ib-sl-vt--so",
				PR: "ib-sl-vt--pr", PI: "ib-sl-vt--pi", PO: "ib-sl-vt--po",
				SE: "ib-sl-vt--se", SR: "ib-sl-vt--sr",
			}[r.vtype_short] || "";

			const in_html   = r.qty_in  ? `<span class="ib-sl-qty-in">+${frappe.format(r.qty_in,  { fieldtype: "Float" })}</span>` : `<span class="ib-sl-nil">—</span>`;
			const out_html  = r.qty_out ? `<span class="ib-sl-qty-out">−${frappe.format(r.qty_out, { fieldtype: "Float" })}</span>` : `<span class="ib-sl-nil">—</span>`;
			const rate_html = r.rate    ? frappe.format(r.rate, { fieldtype: "Float" }) : `<span class="ib-sl-nil">—</span>`;

			const tr = document.createElement("tr");
			tr.className = `ib-sl-row ib-sl-row--${direction}`;
			tr.innerHTML = `
				<td class="ib-sl-td-date">${esc(r.posting_dt_str)}</td>
				<td class="ib-sl-td-item">
					${r.item_name && r.item_name !== r.item_code ? `<div class="ib-sl-item-name">${hl(r.item_name)}</div>` : ""}
					<a href="${item_link}" class="ib-sl-item-code">${hl(r.item_code)}</a>
					${spec_html ? `<div class="ib-sl-spec">${spec_html}</div>` : ""}
				</td>
				<td><span class="ib-sl-wh-badge ${wh_cls}">${esc(r.wh_short)}</span></td>
				<td class="ib-sl-td-num">${in_html}</td>
				<td class="ib-sl-td-num">${out_html}</td>
				<td class="ib-sl-td-num">
					<span class="ib-sl-balance">${frappe.format(r.qty_after_transaction, { fieldtype: "Float" })}</span>
					<span class="ib-sl-uom">${esc(r.stock_uom || "")}</span>
				</td>
				<td class="ib-sl-td-party"><span class="ib-sl-party">${hl(r.party || "—")}</span></td>
				<td class="ib-sl-td-voucher">
					<span class="ib-sl-vtype-badge ${vt_cls}">${esc(r.vtype_short)}</span>
					<a href="${doc_link}" class="ib-sl-voucher-no" target="_blank">${hl(r.voucher_no || "")}</a>
				</td>
				<td class="ib-sl-td-num">${rate_html}</td>
			`;
			frag.appendChild(tr);
		});

		this.$tbody[0].appendChild(frag);
	}

	_render_tfoot() {
		if (!this._filtered_data.length) { this.$tfoot.empty(); return; }
		const fmt      = n => Number(n || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
		const in_total = this._filtered_data.reduce((s, r) => s + (r.qty_in  || 0), 0);
		const out_total= this._filtered_data.reduce((s, r) => s + (r.qty_out || 0), 0);
		this.$tfoot.html(`
			<tr class="ib-sl-tfoot-row">
				<td colspan="3" class="ib-sl-tfoot-label">${__("Page total")}</td>
				<td class="ib-sl-td-num ib-sl-tfoot-in">+${fmt(in_total)}</td>
				<td class="ib-sl-td-num ib-sl-tfoot-out">−${fmt(out_total)}</td>
				<td colspan="4"></td>
			</tr>
		`);
	}

	_spec_html(r) {
		const esc   = frappe.utils.escape_html;
		const parts = [];
		const uom   = r.stock_uom;

		if (uom === "SQMT") {
			if (r.width_mm)             parts.push(esc(String(r.width_mm)));
			if (r.length_mtr)           parts.push(esc(String(r.length_mtr)));
			if (r.custom_thickness)     parts.push(esc(r.custom_thickness));
			if (r.color)                parts.push(IBStock.color_dots(r.color) + esc(r.color));
			if (r.custom_liner)         parts.push(esc(r.custom_liner));
		} else if (uom === "PCS") {
			if (r.color)                parts.push(IBStock.color_dots(r.color) + esc(r.color));
		} else if (uom === "KG") {
			if (r.custom_adhesive_type) parts.push(esc(r.custom_adhesive_type));
		}
		return parts.join(' <span class="ib-sl-spec-sep">·</span> ');
	}

	// ── Filter chips ─────────────────────────────────────────────────────────

	_render_chips() {
		const esc   = frappe.utils.escape_html;
		const chips = [];

		const _server_clear = (fn) => () => {
			this._restoring = true;
			Promise.resolve(fn()).finally(() => { this._restoring = false; this._reset_and_refresh(); });
		};

		const item = this.f_item.get_value();
		if (item) chips.push({ label: item, type: "item",
			clear: _server_clear(() => this.f_item.set_value("")) });

		const wh = this.f_warehouse.get_value();
		if (wh) chips.push({ label: wh.split(" - ")[0], type: "wh",
			clear: _server_clear(() => this.f_warehouse.set_value("")) });

		const customer = this.f_customer.get_value();
		if (customer) chips.push({ label: customer, type: "customer",
			clear: _server_clear(() => this.f_customer.set_value("")) });

		const vtype = this.f_vtype.get_value();
		if (vtype) chips.push({ label: vtype, type: "vtype",
			clear: _server_clear(() => this.f_vtype.set_value("")) });

		const from = this.f_from.get_value();
		const to   = this.f_to.get_value();
		if (from || to) {
			chips.push({
				label: `${from || "…"} → ${to || "…"}`,
				type:  "date",
				clear: _server_clear(() => {
					this.f_from.set_value("");
					this.f_to.set_value("");
				}),
			});
		}

		this._search_chips.forEach((chip, idx) => {
			chips.push({
				label: `"${chip}"`,
				type:  "search",
				clear: () => { this._search_chips.splice(idx, 1); this._apply_client_filter(); },
			});
		});

		if (!chips.length) { this.$chips.empty().hide(); return; }

		this.$chips.html(
			chips.map((c, i) =>
				`<span class="ib-chip ib-chip--${c.type}" data-idx="${i}">${esc(c.label)}<button class="ib-chip-x" aria-label="${__("Remove")}">×</button></span>`
			).join("")
		).show();

		this.$chips.find(".ib-chip").each((i, el) => {
			$(el).find(".ib-chip-x").on("click", (ev) => { ev.stopPropagation(); chips[i].clear(); });
		});

		if (chips.length > 1) {
			this.$chips.append(`<button class="ib-chip-clear-all">${__("Clear all")}</button>`);
			this.$chips.find(".ib-chip-clear-all").on("click", () => this._clear_all());
		}
	}

	// ── Pagination ────────────────────────────────────────────────────────────

	_render_pagination() {
		const total     = this._total;
		const ps        = this._page_size;
		const max_pages = Math.max(Math.ceil(total / ps), 1);
		const start     = (this._page - 1) * ps + 1;
		const end       = Math.min(this._page * ps, total);
		const sizes     = [50, 100, 250];

		if (total === 0) { this.$pg.empty(); return; }

		const count_label = `${start}–${end} ${__("of")} <strong>${total}</strong>`;

		this.$pg.html(`
			<div class="ib-sl-pg-left">
				<span class="ib-sl-pg-info">${count_label}</span>
				<div class="ib-sl-pg-nav">
					<button class="ib-sl-pg-btn" data-action="prev" ${this._page <= 1 ? "disabled" : ""}>&#8249;</button>
					<span class="ib-sl-pg-num">${this._page} / ${max_pages}</span>
					<button class="ib-sl-pg-btn" data-action="next" ${this._page >= max_pages ? "disabled" : ""}>&#8250;</button>
				</div>
			</div>
			<div class="ib-sl-pg-right">
				<span>${__("Per page")}</span>
				${sizes.map(s => `
					<button class="ib-sl-pg-size ${this._page_size === s ? "active" : ""}" data-size="${s}">${s}</button>
				`).join("")}
			</div>
		`);

		this.$pg.find("[data-action='prev']").on("click", () => {
			if (this._page <= 1) return;
			this._page--;
			this._save_filters();
			this.refresh();
		});
		this.$pg.find("[data-action='next']").on("click", () => {
			if (this._page >= max_pages) return;
			this._page++;
			this._save_filters();
			this.refresh();
		});
		this.$pg.find(".ib-sl-pg-size").on("click", (e) => {
			this._page_size = parseInt($(e.currentTarget).data("size"), 10);
			this._page      = 1;
			this._save_filters();
			this.refresh();
		});
	}

	// ── Sort icons ────────────────────────────────────────────────────────────

	_update_sort_icons() {
		this.$content.find(".ib-sl-th-sortable").each((_, th) => {
			const col = $(th).data("col");
			$(th).find(".ib-sort-icon").text(
				this._sort.col === col ? (this._sort.asc ? " ↑" : " ↓") : ""
			);
			$(th).toggleClass("ib-sl-th-active", this._sort.col === col);
		});
	}

	// ── Empty / idle states ───────────────────────────────────────────────────

	_show_idle() {
		this.$tbody.empty();
		this.$pg.empty();
		this._render_chips();
		this.$empty.html(`
			<div class="ib-sl-empty-msg">
				<div class="ib-sl-empty-icon">${this._icon("calendar")}</div>
				${__("Select a date range to view stock movements")}
			</div>
		`).show();
	}

	_show_empty() {
		const item = this.f_item.get_value();
		const msg  = this._search_tokens.length
			? __("No entries match your search")
			: item
				? __("No stock movements for {0} in this period", [item])
				: __("No entries found — try adjusting your filters");
		this.$empty.html(`<div class="ib-sl-empty-msg"><div class="ib-sl-empty-icon">${this._icon("inbox")}</div>${msg}</div>`).show();
	}

	// ── CSV export ────────────────────────────────────────────────────────────

	_export_csv() {
		const from_date = this.f_from.get_value();
		const to_date   = this.f_to.get_value();
		if (!from_date && !to_date) { frappe.msgprint(__("Select a date range first.")); return; }

		const $btn = this.$cards.find(".ib-sl-export-btn");
		$btn.prop("disabled", true).text(__("Fetching…"));

		frappe.call({
			method: "instabiz.instabiz.page.ib_stock_ledger.ib_stock_ledger.get_ledger",
			args: {
				item_code:    this.f_item.get_value()      || null,
				warehouse:    this.f_warehouse.get_value() || null,
				from_date:    from_date                    || null,
				to_date:      to_date                      || null,
				voucher_type: this.f_vtype.get_value()     || null,
				customer:     this.f_customer.get_value()  || null,
				limit:        100000,
				offset:       0,
			},
			callback: (r) => {
				$btn.prop("disabled", false).html(`<svg class="icon icon-sm"><use href="#es-line-down"></use></svg> ${__("Export CSV")}`);
				if (!r.message || !r.message.data.length) { frappe.msgprint(__("Nothing to export.")); return; }

				const all = r.message.data;
				const tokens = this._search_tokens;
				const filtered = tokens.length ? all.filter(row => {
					const hay = [
						row.item_code, row.item_name, row.party, row.voucher_no,
						row.wh_short, row.vtype_short, row.color, row.custom_thickness, row.custom_adhesive_type,
					].join(" ").toLowerCase();
					return tokens.every(t => hay.includes(t));
				}) : all;

				IBStock.csv_download(
					`IB_Stock_Ledger_${frappe.datetime.get_today()}.csv`,
					[
						__("Date"), __("Item Code"), __("Item Name"),
						__("Width"), __("Length"), __("Thickness"), __("Color"), __("Liner"),
						__("Warehouse"), __("In Qty"), __("Out Qty"), __("Balance"),
						__("UOM"), __("Party"), __("Voucher Type"), __("Voucher No"), __("Rate"),
					],
					IBStock.sort_rows(filtered, this._sort.col, this._sort.asc),
					row => [
						row.posting_dt_str, row.item_code, row.item_name,
						row.width_mm || "", row.length_mtr || "", row.custom_thickness || "",
						row.color || "", row.custom_liner || "",
						row.warehouse, row.qty_in || 0, row.qty_out || 0, row.qty_after_transaction,
						row.stock_uom, row.party || "", row.voucher_type, row.voucher_no, row.rate || 0,
					]
				);
			},
			error: () => {
				$btn.prop("disabled", false).html(`<svg class="icon icon-sm"><use href="#es-line-down"></use></svg> ${__("Export CSV")}`);
			},
		});
	}

	// ── Filter persistence ────────────────────────────────────────────────────

	_save_filters() {
		try {
			localStorage.setItem(this._STORAGE_KEY, JSON.stringify({
				item_code:    this.f_item.get_value()      || "",
				warehouse:    this.f_warehouse.get_value() || "",
				customer:     this.f_customer.get_value()  || "",
				from_date:    this.f_from.get_value()      || "",
				to_date:      this.f_to.get_value()        || "",
				voucher_type: this.f_vtype.get_value()     || "",
				sort_col:     this._sort.col  || "",
				sort_asc:     this._sort.asc  ? 1 : 0,
				page_size:    this._page_size,
				search_chips: this._search_chips || [],
			}));
		} catch (_) {}
	}

	_restore_filters() {
		if (this._prefill_item) return;
		try {
			const saved = JSON.parse(localStorage.getItem(this._STORAGE_KEY) || "null");
			if (!saved) return;
			this._restoring = true;
			if (saved.item_code)    this.f_item.set_value(saved.item_code);
			if (saved.warehouse)    this.f_warehouse.set_value(saved.warehouse);
			if (saved.customer)     this.f_customer.set_value(saved.customer);
			if (saved.from_date)    this.f_from.set_value(saved.from_date);
			if (saved.to_date)      this.f_to.set_value(saved.to_date);
			if (saved.voucher_type) this.f_vtype.set_value(saved.voucher_type);
			if (saved.sort_col)     { this._sort.col = saved.sort_col; this._sort.asc = !!saved.sort_asc; }
			if (saved.page_size)    this._page_size = saved.page_size;
			if (Array.isArray(saved.search_chips)) this._search_chips = saved.search_chips;
			this._restoring = false;
		} catch (_) { this._restoring = false; }
	}

	_clear_all() {
		this._restoring = true;
		this.f_item.set_value("");
		this.f_warehouse.set_value("");
		this.f_customer.set_value("");
		this.f_from.set_value("");
		this.f_to.set_value("");
		this.f_vtype.set_value("");
		this._restoring    = false;
		this._search_chips = [];
		this._sort         = { col: null, asc: true };
		this._page         = 1;
		$(this.f_search.wrapper).find("input").val("");
		try { localStorage.removeItem(this._STORAGE_KEY); } catch (_) {}
		this._reset_and_refresh();
	}

	_cleanup() {
		clearTimeout(this._search_debounce);
		$(document).off("keydown.ib-stock-ledger");
	}
}
