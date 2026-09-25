frappe.pages["ib-customer-board"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Customer Board",
		single_column: true,
	});
	wrapper.cb_shell = new IBCustomerBoardShell(page, wrapper);
	frappe.pages["ib-customer-board"]._shell = wrapper.cb_shell;
};

frappe.pages["ib-customer-board"].on_page_show = function (wrapper) {
	if (wrapper.cb_shell) wrapper.cb_shell._on_show();
};

frappe.pages["ib-customer-board"].on_page_hide = function (wrapper) {
	if (wrapper.cb_shell) wrapper.cb_shell._cleanup();
};

/* ─── Outer shell — tabs between My Board and Team ───────────────────────── */
// Merged 2026-08-05: this page used to be two separate routes (ib-customer-board
// / ib-assignment-admin), each with its own independently-coded rendering —
// IBCustomerBoard (every Sales User's own My Accounts/Today/Tomorrow kanban)
// and IBAssignmentAdmin (manager-only team roster + a "view as" mode with its
// own separate _render_board_view renderer — visually similar to
// IBCustomerBoard's board but NOT literally reusing its code, confirmed via
// grep before this merge). Route kept as "ib-customer-board" (not renamed) —
// it already carried 4 external call sites (ib_main_dashboard.js,
// ib_business_pulse.js, list_utils.js, a workspace shortcut) vs
// ib-assignment-admin's 1 (ib_sales_incentives.js's "goto admin" button,
// repointed to frappe.set_route("ib-customer-board", "team")).
//
// Access boundary does NOT widen: every admin-facing RPC in
// instabiz.overrides.customer_assignment (get_admin_overview, get_manager_queue,
// get_team_details, get_active_sales_users_detail, etc.) already carries its
// own server-side _require_manager()/_require_manager_or_leader() guard,
// independent of this page-level tab gate — re-confirmed via grep before this
// merge. Page-level Page.roles is the union: Sales User + Sales Manager +
// System Manager + Team Leader. The "Team" tab button itself is only ever
// built into the DOM (not just hidden) when the current user has one of
// Sales Manager / System Manager / Team Leader — a Sales User never sees a
// Team tab at all, and a direct /ib-customer-board/team route hit from a
// Sales User silently falls back to the My Board tab.
class IBCustomerBoardShell {
	constructor(page, wrapper) {
		this.wrapper = wrapper;
		this.page = page;
		// page.main (== page.body, ".layout-main-section") is Frappe's own
		// container — page.page_form is prepended inside it at construction
		// time. Never wholesale-replace this node's HTML (see the identical
		// gotcha documented in ib_item_pricing.js / ib_stock_dashboard.js) —
		// mount the tab bar and a dedicated body div as siblings instead.
		this.$main = $(this.page.main);
		this._active = null;
		this._active_tab = null;
		this._team_visible = frappe.user.has_role("Sales Manager")
			|| frappe.user.has_role("System Manager")
			|| frappe.user.has_role("Team Leader");
		this._build_shell();
		this._activate(this._route_tab());
	}

	_route_tab() {
		const route = frappe.get_route();
		if (route[1] === "team" && this._team_visible) return "team";
		return "board";
	}

	_build_shell() {
		if (!document.getElementById("ib-cbx-shell-styles")) {
			const s = document.createElement("style");
			s.id = "ib-cbx-shell-styles";
			s.textContent = `
				.ib-cbx-tabs { display:flex; gap:4px; padding:10px 0 0; border-bottom:2px solid var(--border-color); margin-bottom:14px; }
				button.ib-cbx-tab {
					-webkit-appearance:none; appearance:none;
					padding:8px 28px; border:1.5px solid transparent !important; border-bottom:none !important;
					border-radius:8px 8px 0 0; font-size:13px; font-weight:600; cursor:pointer;
					color:var(--text-muted); background:transparent !important; box-shadow:none !important;
					transition:all .15s; margin-bottom:-2px; line-height:1.4;
				}
				button.ib-cbx-tab:hover { background:var(--bg-color) !important; color:var(--text-color); }
				button.ib-cbx-tab.ib-cbx-tab--active {
					background:var(--card-bg) !important; color:var(--ib-primary,#d97757);
					border-color:var(--border-color) !important; border-bottom-color:var(--card-bg) !important;
				}
			`;
			document.head.appendChild(s);
		}
		// Sales User: no Team tab exists at all — a single-item tab bar would
		// just be dead chrome, so skip the tab strip entirely and mount the
		// board straight into the body div.
		if (this._team_visible) {
			this.$main.prepend(`<div class="ib-cbx-tabs" id="ib-cbx-tabs">
				<button class="ib-cbx-tab" data-tab="board">My Board</button>
				<button class="ib-cbx-tab" data-tab="team">Team</button>
			</div>`);
		}
		this.$main.append(`<div id="ib-cbx-body"></div>`);
		this.$main.on("click", ".ib-cbx-tab", (e) => {
			const tab = $(e.currentTarget).data("tab");
			if (tab === this._active_tab) return;
			frappe.set_route("ib-customer-board", tab === "board" ? "" : tab);
			this._activate(tab);
		});
	}

	_on_show() {
		const tab = this._route_tab();
		if (tab !== this._active_tab) this._activate(tab);
	}

	_activate(tab) {
		// Hard guard in addition to _route_tab()'s own check — belt and
		// braces against a stale in-page frappe.set_route() call reaching
		// here for a role that never got the Team tab button built.
		if (tab === "team" && !this._team_visible) tab = "board";

		this._teardown_active();
		this.$main.find(".ib-cbx-tab").removeClass("ib-cbx-tab--active");
		this.$main.find(`[data-tab="${tab}"]`).addClass("ib-cbx-tab--active");

		this.page.clear_primary_action();
		this.page.clear_secondary_action();
		this.page.clear_inner_toolbar();
		this.page.clear_menu();
		this.page.clear_fields();
		this.page.hide_form();

		const $body = this.$main.find("#ib-cbx-body").empty();
		this._active_tab = tab;

		if (tab === "board") {
			this._active = new IBCustomerBoard(this.page, $body);
		} else {
			this._active = new IBAssignmentAdmin(this.page, $body);
		}
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


/* ─── My Board tab (ex ib_customer_board.js's IBCustomerBoard) ──────────── */
const IB_CB_COLOR_SUCCESS = "#22c55e"; // green — positive/new highlight
const IB_CB_COLOR_SUCCESS_RGB = "34,197,94";
const IB_CB_COLOR_DANGER  = "#ef4444"; // red — skipped/urgent highlight
const IB_CB_COLOR_DANGER_RGB  = "239,68,68";
const IB_CB_COLOR_ACTIVITY = "#25d366"; // activity-logged highlight
const IB_CB_COLOR_WARNING = "#f59e0b"; // amber — mid-progress bar

class IBCustomerBoard {
	constructor(page, $container) {
		this.page = page;
		this.$main = $container;
		this._selected_date = frappe.datetime.get_today();
		this._tomorrow_date = null;
		this._undo_timer = null;
		this._sortables = [];
		this._highlight_customer = null;
		this._highlight_color = IB_CB_COLOR_SUCCESS;
		this._pending_on_timeout = null;
		this._is_manager = frappe.user.has_role("Sales Manager") || frappe.user.has_role("System Manager");
		this._last_data = null;
		this._search_timers = {};

		this._init();
	}

	_init() {
		this._gsap_ready = new Promise((resolve) => {
			if (window.gsap) { resolve(); return; }
			const s = document.createElement("script");
			s.src = "https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.5/gsap.min.js";
			s.onload = resolve;
			document.head.appendChild(s);
		});
		this._sortable_ready = new Promise((resolve) => {
			if (window.Sortable) { resolve(); return; }
			const s = document.createElement("script");
			s.src = "https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js";
			s.onload = resolve;
			document.head.appendChild(s);
		});
		this._build_toolbar();
		this._build_skeleton();
		this.refresh();
		this._start_live();
	}

	_start_live() {
		// Territory column removed — no live handler needed
	}

	// Called by IBCustomerBoardShell._teardown_active() on every tab switch
	// (and by on_page_hide via the shell) — this class gets torn down and
	// freshly reconstructed on every "My Board" tab activation now that it
	// lives inside a shell, so any listener bound outside its own $main
	// scope (this one included) must be explicitly released here or it
	// leaks a duplicate on the next activation.
	_cleanup() {
		if (this._live_handler) {
			frappe.realtime.off("ib_territory_taken", this._live_handler);
			this._live_handler = null;
		}
		if (this._undo_timer) {
			clearInterval(this._undo_timer);
			this._undo_timer = null;
		}
		Object.values(this._search_timers || {}).forEach((t) => clearTimeout(t));
	}

	// ── Toolbar ──────────────────────────────────────────────────────────────

	_build_toolbar() {
		const self = this;
		this.page.add_field({
			fieldname: "board_date",
			fieldtype: "Date",
			label: "Date",
			default: frappe.datetime.get_today(),
			change() {
				self._selected_date = this.get_value() || frappe.datetime.get_today();
				self.refresh();
			},
		});
		this.page.add_inner_button("Refresh", () => this.refresh());
	}

	// ── Skeleton ─────────────────────────────────────────────────────────────

	_build_skeleton() {
		// The old admin banner ("Managing the team? Open Master Control...")
		// was removed as part of the 2026-08-05 merge — it existed only to
		// point managers at a second, otherwise-hidden route. Now that the
		// same page carries a permanently visible "Team" tab in its own tab
		// bar (see IBCustomerBoardShell), the banner is redundant chrome.
		this.$main.html(`
			<div class="ib-cb-board">
				<div class="ib-cb-stats-row">
					<div class="ib-cb-stat-card ib-cb-stat-card--completed">
						<span class="ib-cb-stat-num" id="ib-cb-stat-completed-val">0</span>
						<span class="ib-cb-stat-lbl">Completed</span>
					</div>
					<div class="ib-cb-stat-card ib-cb-stat-card--skipped">
						<span class="ib-cb-stat-num" id="ib-cb-stat-skipped-val">0</span>
						<span class="ib-cb-stat-lbl">Skipped</span>
					</div>
					<div class="ib-cb-target-card" id="ib-cb-target-card" style="display:none">
						<div class="ib-cb-target-hdr">
							<span class="ib-cb-target-lbl">Monthly Target</span>
							<span class="ib-cb-target-month" id="ib-cb-target-month"></span>
						</div>
						<div class="ib-cb-target-amounts">
							<span class="ib-cb-target-actual" id="ib-cb-target-actual">₹0</span>
							<span class="ib-cb-target-sep">/</span>
							<span class="ib-cb-target-goal" id="ib-cb-target-goal">₹0</span>
						</div>
						<div class="ib-cb-target-bar-wrap">
							<div class="ib-cb-target-bar-track">
								<div class="ib-cb-target-bar-fill" id="ib-cb-target-bar-fill"></div>
							</div>
							<span class="ib-cb-target-pct" id="ib-cb-target-pct">0%</span>
						</div>
						<div class="ib-cb-target-source" id="ib-cb-target-source"></div>
					</div>
				</div>
				<span class="ib-refresh-time" id="ib-cb-refresh-time" style="display:none;justify-content:flex-end;margin:-8px 0 8px;width:100%">
					<iconify-icon icon="lucide:clock" width="12" height="12"></iconify-icon>
					Updated <span id="ib-cb-refresh-time-val"></span>
				</span>
				<div class="ib-cb-dormant-tip">
					<div class="ib-cb-dormant-tip-icon">
						<iconify-icon icon="lucide:clock-alert" width="16" height="16"></iconify-icon>
					</div>
					<div class="ib-cb-dormant-tip-body">
						<div class="ib-cb-dormant-tip-title">Account Follow-Up Policy</div>
						<div class="ib-cb-dormant-tip-desc">If an account has not placed an order in 30 days, you will receive a gentle reminder. After 60 days, a second, more considerate notice will follow. Should 90 days pass without an order, the account will be reassigned to the next representative on your territory team, so it continues to receive proper attention.</div>
					</div>
				</div>
				<div class="ib-cb-columns">
					<div class="ib-cb-col" id="ib-cb-dormant">
						<div class="ib-cb-col-header">
							${IB_ICONS.svg("user", 13)}<span class="ib-cb-col-title">My Accounts</span>
							<span class="ib-cb-col-badge" id="ib-cb-dormant-count">0</span>
						</div>
						<div class="ib-cb-col-search">
							<input class="ib-cb-pool-search form-control" id="ib-cb-dormant-search" placeholder="Search…" autocomplete="off">
						</div>
						<div class="ib-cb-cards" id="ib-cb-dormant-cards"></div>
						<button class="btn btn-xs btn-default" id="ib-cb-dormant-more" style="display:none;width:calc(100% - 20px);margin:8px 10px">Load more</button>
					</div>
					<div class="ib-cb-col ib-cb-col--today" id="ib-cb-today">
						<div class="ib-cb-col-header">
							${IB_ICONS.svg("calendar", 13)}<span class="ib-cb-col-title">Today</span>
							<span class="ib-cb-col-date" id="ib-cb-today-date"></span>
							<span class="ib-cb-col-badge ib-cb-col-badge--today" id="ib-cb-today-count">0</span>
						</div>

						<div class="ib-cb-today-prog-wrap">
							<div class="ib-cb-today-prog-fill" id="ib-cb-today-prog-fill"></div>
						</div>
						<div class="ib-cb-col-search">
							<input class="ib-cb-pool-search form-control" id="ib-cb-today-search" placeholder="Search…" autocomplete="off">
						</div>
						<div class="ib-cb-cards" id="ib-cb-today-cards"></div>
					</div>
					<div class="ib-cb-col ib-cb-col--tomorrow" id="ib-cb-tomorrow">
						<div class="ib-cb-col-header">
							${IB_ICONS.svg("sunrise", 13)}<span class="ib-cb-col-title">Tomorrow</span>
							<span class="ib-cb-col-date" id="ib-cb-tomorrow-date"></span>
							<span class="ib-cb-col-badge" id="ib-cb-tomorrow-count">0</span>
						</div>
						<div class="ib-cb-col-search">
							<input class="ib-cb-pool-search form-control" id="ib-cb-tomorrow-search" placeholder="Search…" autocomplete="off">
						</div>
						<div class="ib-cb-cards" id="ib-cb-tomorrow-cards"></div>
					</div>
				</div>
			</div>
			<div id="ib-cb-undo-toast" class="ib-cb-undo-toast">
				<div class="ib-cb-undo-toast-row">
					<span class="ib-cb-undo-msg" id="ib-cb-undo-msg"></span>
					<button class="ib-cb-undo-btn" id="ib-cb-undo-btn">Undo</button>
				</div>
				<div class="ib-cb-undo-bar"><div class="ib-cb-undo-bar-fill" id="ib-cb-undo-bar-fill"></div></div>
			</div>
		`);
		$("#ib-cb-dormant-more").off("click").on("click", () => this._load_more_my_accounts());
	}

	// ── Data load ─────────────────────────────────────────────────────────────

	refresh() {
		const self = this;
		$(".ib-cb-board").css("opacity", "0.6");
		frappe.call({
			method: "instabiz.overrides.customer_assignment.get_customer_board_data",
			args: { date: this._selected_date },
			callback(r) {
				$(".ib-cb-board").css("opacity", "");
				if (r.message) self._render(r.message);
				const now = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
				$("#ib-cb-refresh-time").show().find("#ib-cb-refresh-time-val").text(now);
			},
			error() {
				$(".ib-cb-board").css("opacity", "");
				frappe.show_alert({ message: "Failed to load board data", indicator: "red" });
			},
		});
		frappe.call({
			method: "instabiz.overrides.sales_target.get_my_target",
			args: { month: this._selected_date },
			callback(r) { if (r.message) self._render_target(r.message); },
		});
	}

	_render_target(t) {
		if (!t.has_target) { $("#ib-cb-target-card").hide(); return; }
		const fmt = (v) => "₹" + Number(v).toLocaleString("en-IN", { maximumFractionDigits: 0 });
		// Compact crore/lakh display for this headline card, same convention
		// as the other dashboards' KPI cards — exact amount lives in title.
		const fmtC = (v) => window.ib_fmt_inr_compact ? window.ib_fmt_inr_compact(v) : fmt(v);
		const pct = t.pct || 0;
		const bar_color = pct >= 100 ? IB_CB_COLOR_SUCCESS : pct >= 60 ? "var(--ib-primary)" : IB_CB_COLOR_WARNING;
		const d = frappe.datetime.str_to_user(t.month);
		const month_label = d ? d.slice(3) : t.month;  // "May 2026" from "01-05-2026"
		$("#ib-cb-target-month").text(month_label);
		$("#ib-cb-target-actual").text(fmtC(t.actual)).attr("title", fmt(t.actual));
		$("#ib-cb-target-goal").text(fmtC(t.target)).attr("title", fmt(t.target));
		$("#ib-cb-target-pct").text(pct + "%");
		$("#ib-cb-target-bar-fill").css({ width: pct + "%", background: bar_color });
		const cnt = t.order_count || 0;
		const src_text = cnt === 1 ? "1 sales order" : `${cnt} sales orders`;
		// Month date range for SO filter deep-link (must match _get_actuals basis: creation,
		// per user decision 2026-07-25 — same field the SO list view defaults to)
		const _mp = (t.month || "").split("-").map(Number);
		const _last_day = _mp.length === 3 ? new Date(_mp[0], _mp[1], 0).getDate() : 28;
		const month_end = t.month ? `${t.month.slice(0, 7)}-${String(_last_day).padStart(2, "0")}` : "";
		const view_user = frappe.session.user;
		$("#ib-cb-target-source").html(
			`From <a class="ib-cb-inv-link" href="#" title="View these sales orders">${src_text}</a> · ${frappe.utils.escape_html(month_label)}`
		);
		$("#ib-cb-target-source .ib-cb-inv-link").off("click").on("click", function (e) {
			e.preventDefault();
			frappe.route_options = {
				docstatus: 1,
				custom_sales_person_user: view_user,
				creation: ["between", [t.month, month_end]],
			};
			frappe.set_route("List", "Sales Order");
		});
		$("#ib-cb-target-card").show();
	}

	// ── Render ────────────────────────────────────────────────────────────────

	_render(data) {
		this._last_data = data;
		this._tomorrow_date = data.tomorrow_date;
		if (data.is_manager !== undefined) this._is_manager = data.is_manager;
		// Track which customers already have active assignments so pool cards show status badges
		this._today_customer_set    = new Set((data.today    || []).map(r => r.customer));
		this._tomorrow_customer_set = new Set((data.tomorrow || []).map(r => r.customer));
		$("#ib-cb-today-date").text(frappe.datetime.str_to_user(data.date));
		$("#ib-cb-tomorrow-date").text(frappe.datetime.str_to_user(data.tomorrow_date));
		this._render_pool("dormant", data.dormant, data.dormant_total);
		this._render_today(data.today);
		this._render_tomorrow(data.tomorrow);
		this._init_sortable();
		if (this._highlight_customer) {
			this._flash_new_card(this._highlight_customer, this._highlight_color);
			this._highlight_customer = null;
			this._highlight_color = IB_CB_COLOR_SUCCESS;
		}
	}

	_render_pool(col, rows, total) {
		$(`#ib-cb-${col}-search`).val("");
		const $cards = $(`#ib-cb-${col}-cards`).empty();
		const badge = total !== undefined && total > rows.length ? `${rows.length} / ${total}` : rows.length;
		$(`#ib-cb-${col}-count`).text(badge);
		if (!rows.length) {
			const empty_msg = col === "dormant"
				? "No accounts assigned to you yet"
				: "No unassigned customers in your territory";
			const empty_sub = col === "dormant"
				? (this._is_manager
					? "Assign accounts via the Team tab, or claim one from a rep's pool."
					: "Your Sales Manager assigns accounts — check back soon or ask them directly.")
				: "";
			$cards.append(
				`<div class="ib-cb-empty">${empty_msg}${empty_sub ? `<span class="ib-cb-empty-sub">${empty_sub}</span>` : ""}</div>`
			);
		} else {
			rows.forEach((r) => $cards.append(this._make_card(r, "pool")));
		}
		this._bind_search(col, "backend");

		// "My Accounts" pages past its initial batch instead of hard-capping.
		if (col === "dormant") {
			this._my_accounts_total = total;
			this._my_accounts_loaded = rows.length;
			const $more = $("#ib-cb-dormant-more");
			$more.toggle(total > rows.length);
		}
	}

	_load_more_my_accounts() {
		const $more = $("#ib-cb-dormant-more");
		$more.prop("disabled", true).text("Loading…");
		frappe.call({
			method: "instabiz.overrides.customer_assignment.load_more_my_accounts",
			args: { offset: this._my_accounts_loaded, limit: 50 },
			callback: (r) => {
				const { rows, total } = r.message || { rows: [], total: this._my_accounts_total };
				const $cards = $("#ib-cb-dormant-cards");
				rows.forEach((row) => $cards.append(this._make_card(row, "pool")));
				this._my_accounts_loaded += rows.length;
				this._my_accounts_total = total;
				$("#ib-cb-dormant-count").text(
					this._my_accounts_total > this._my_accounts_loaded
						? `${this._my_accounts_loaded} / ${this._my_accounts_total}`
						: this._my_accounts_loaded
				);
				$more.prop("disabled", false).text("Load more")
					.toggle(this._my_accounts_total > this._my_accounts_loaded);
			},
		});
	}

	// ── Unified search binding ────────────────────────────────────────────────

	_bind_search(col, mode) {
		// mode: "backend" → hits search_customer_pool API
		//       "local"   → filters this._last_data[col] client-side
		const self = this;
		$(`#ib-cb-${col}-search`).off("input").on("input", function () {
			const q = $(this).val().trim();
			clearTimeout(self._search_timers[col]);
			if (!q) {
				self._restore_col(col);
				return;
			}
			self._search_timers[col] = setTimeout(() => {
				if (mode === "backend") {
					frappe.call({
						method: "instabiz.overrides.customer_assignment.search_customer_pool",
						args: { pool_type: col, search: q },
						callback(r) { self._apply_search_results(col, r.message || [], "pool"); },
					});
				} else {
					const tokens = q.toLowerCase().split(/\s+/).filter(Boolean);
					const rows = (self._last_data?.[col] || []).filter((r) => {
						const hay = [r.customer_name, r.customer, r.territory, r.custom_contact_person_name]
							.join(" ").toLowerCase();
						return tokens.every((t) => hay.includes(t));
					});
					const ctx = col === "today" ? "today"
						: col === "claimed" ? "claimed"
						: "tomorrow";
					self._apply_search_results(col, rows, ctx);
				}
			}, 250);
		});
	}

	_restore_col(col) {
		const data = this._last_data;
		if (!data) return;
		if (col === "dormant") this._render_pool("dormant", data.dormant, data.dormant_total);
		else if (col === "today") this._render_today(data.today);
		else if (col === "tomorrow") this._render_tomorrow(data.tomorrow);
	}

	_apply_search_results(col, rows, ctx) {
		const $cards = $(`#ib-cb-${col}-cards`).empty();
		$(`#ib-cb-${col}-count`).text(rows.length);
		if (!rows.length) {
			$cards.append(`<div class="ib-cb-empty">No results</div>`);
			return;
		}
		if (col === "today") {
			rows.filter((r) => r.status === "Pending").forEach((r) => $cards.prepend(this._make_card(r, "today")));
			rows.filter((r) => r.status !== "Pending").forEach((r) => $cards.append(this._make_card(r, "today_done")));
		} else {
			rows.forEach((r) => $cards.append(this._make_card(r, ctx)));
		}
	}

	_render_today(rows) {
		const self = this;
		$("#ib-cb-today-search").val("");
		const $cards = $("#ib-cb-today-cards").empty();
		const pending = rows.filter((r) => r.status === "Pending");
		const done    = rows.filter((r) => r.status !== "Pending");
		const total   = rows.length;
		const done_ct = done.length;

		// Badge: done / total
		$("#ib-cb-today-count").text(total ? `${done_ct}/${total}` : "0");

		// Stat counters
		$("#ib-cb-stat-completed-val").text(done.filter((r) => r.status !== "Skipped").length);
		$("#ib-cb-stat-skipped-val").text(done.filter((r) => r.status === "Skipped").length);

		// Progress bar via GSAP
		const pct = total ? Math.round((done_ct / total) * 100) : 0;
		this._gsap_ready.then(() => {
			gsap.to("#ib-cb-today-prog-fill", {
				width: pct + "%",
				duration: 0.55,
				ease: "power2.out",
			});
		});

		if (!total) {
			$cards.append(
				`<div class="ib-cb-empty">No assignments today<span class="ib-cb-empty-sub">Today's batch is auto-assigned overnight from your My Accounts pool.</span></div>`
			);
		} else {
			// Build cards with opacity:0 so GSAP animates them in without flash
			const make_hidden = (r, ctx) => {
				const $c = self._make_card(r, ctx);
				$c.css("opacity", "0");
				return $c;
			};
			// Most-recent assignment first so drag-dropped cards surface at top
			[...pending].reverse().forEach((r) => $cards.prepend(make_hidden(r, "today")));
			done.forEach((r) => $cards.append(make_hidden(r, "today_done")));
		}

		// Stagger cards in — opacity already 0, no flash
		this._gsap_ready.then(() => {
			gsap.to("#ib-cb-today-cards .ib-cb-card",
				{ opacity: 1, y: 0, stagger: 0.035, duration: 0.22, ease: "power2.out", clearProps: "transform" }
			);
		});
		this._bind_search("today", "local");
	}

	_render_tomorrow(rows) {
		$("#ib-cb-tomorrow-search").val("");
		const $cards = $("#ib-cb-tomorrow-cards").empty();
		$("#ib-cb-tomorrow-count").text(rows.length);
		if (!rows.length) {
			$cards.append(
				`<div class="ib-cb-empty">No assignments yet<span class="ib-cb-empty-sub">Scheduler runs at midnight to build tomorrow's batch.</span></div>`
			);
		} else {
			[...rows].reverse().forEach((r) => $cards.prepend(this._make_card(r, "tomorrow")));
		}
		this._bind_search("tomorrow", "local");
	}

	// ── Unified card builder ──────────────────────────────────────────────────

	_make_card(r, ctx) {
		const self = this;
		const name_html = frappe.utils.escape_html(r.customer_name || r.customer);
		const phone = r.mobile_no || r.custom_primary_contact_person;
		const is_done = ctx === "today_done";

		// Meta lines
		const territory_line = r.territory
			? `<div class="ib-cb-card-meta">${IB_ICONS.svg("map_pin", 10)} ${frappe.utils.escape_html(r.territory)}</div>`
			: "";
		const contact_line = r.custom_contact_person_name
			? `<div class="ib-cb-card-contact">${IB_ICONS.svg("user", 10)} ${frappe.utils.escape_html(r.custom_contact_person_name)}</div>`
			: "";
		const last_label = r.last_so_date
			? frappe.datetime.str_to_user(r.last_so_date)
			: "No orders yet";
		const last_line = `<div class="ib-cb-card-last">${IB_ICONS.svg("clock", 10)} ${last_label}</div>`;

		// Prior contact context (done today cards only)
		const prior_line = (is_done && r.last_outcome)
			? `<div class="ib-cb-card-prior">
				<span class="ib-cb-prior-chip ib-cb-prior--${r.last_outcome.toLowerCase().replace(/ /g, "-")}">
					${frappe.utils.escape_html(r.last_outcome)}
				</span>
				<span class="ib-cb-prior-date">${IB_ICONS.svg("clock", 9)} ${frappe.datetime.str_to_user(r.last_contacted_at)}</span>
			   </div>`
			: "";

		let inner_html = "";

		if (ctx === "pool") {
			const esc_cust = frappe.utils.escape_html(r.customer);
			const in_today    = !!(this._today_customer_set    && this._today_customer_set.has(r.customer));
			const in_tomorrow = !!(this._tomorrow_customer_set && this._tomorrow_customer_set.has(r.customer));
			const today_btn = in_today
				? `<span class="ib-cb-pill ib-cb-pill--in-today">${IB_ICONS.svg("check", 10)} In Today</span>`
				: `<button class="ib-cb-pill ib-cb-pill--add ib-cb-btn-add-today" data-customer="${esc_cust}">${IB_ICONS.svg("plus", 10)} Add to Today</button>`;
			const tmrw_btn = in_tomorrow
				? `<span class="ib-cb-pill ib-cb-pill--in-tomorrow">${IB_ICONS.svg("check", 10)} Tomorrow</span>`
				: `<button class="ib-cb-pill ib-cb-pill--tomorrow ib-cb-btn-add-tomorrow" data-customer="${esc_cust}">${IB_ICONS.svg("plus", 10)} Tomorrow</button>`;

			// Share controls — only on Currently Handling column
			// Owned customers show Share button; shared ones show "Shared" badge + self-unshare
			const is_owned = r.share_relation === "owned" || !r.share_relation;
			const is_shared_with_me = r.share_relation === "shared";
			const shared_badge = is_shared_with_me
				? `<span class="ib-cb-pill ib-cb-pill--shared-badge" title="Shared with you">${IB_ICONS.svg("users", 10)} Shared</span>`
				: "";
			const share_btn = is_owned && !this._is_manager
				? `<button class="ib-cb-pill ib-cb-pill--share ib-cb-btn-share" data-customer="${esc_cust}" title="Share with another user">${IB_ICONS.svg("users", 10)} Share</button>`
				: (this._is_manager && is_owned)
					? `<button class="ib-cb-pill ib-cb-pill--share ib-cb-btn-share" data-customer="${esc_cust}" title="Manage sharing">${IB_ICONS.svg("users", 10)} Share</button>`
					: "";
			const unshare_btn = is_shared_with_me
				? `<button class="ib-cb-pill ib-cb-pill--unshare ib-cb-btn-unshare" data-customer="${esc_cust}" title="Remove from my board">✕ Unshare</button>`
				: "";

			inner_html = `
				<div class="ib-cb-card-top">
					<div class="ib-cb-card-name">${name_html}</div>
					${shared_badge}
				</div>
				${territory_line}
				${contact_line}
				${last_line}
				<div class="ib-cb-card-actions">
					${today_btn}
					${tmrw_btn}
					${share_btn}
					${unshare_btn}
				</div>
			`;
		} else if (ctx === "today" || ctx === "today_done") {
			const skip_btn = !is_done
				? `<button class="ib-cb-skip-btn ib-cb-btn-skip" title="Skip">&#x2715;</button>`
				: "";

			// Done label (replaces status badge on completed/skipped cards)
			let done_label_text = "";
			if (is_done) {
				done_label_text = r.status === "Skipped" ? "Skipped"
					: r.status === "Order Placed" ? "Order Placed"
					: r.outcome ? `Contacted · ${r.outcome}` : "Contacted";
			}
			const done_label = is_done
				? `<div class="ib-cb-done-label">${frappe.utils.escape_html(done_label_text)}</div>`
				: "";

			// Small done/skip badge for completed cards
			const done_badge = is_done
				? `<span class="ib-cb-done-badge ib-cb-done-badge--${r.status === "Skipped" ? "skip" : "done"}">${r.status === "Skipped" ? "SKIP" : "DONE"}</span>`
				: `<span class="ib-cb-status ib-cb-status--pending">${r.status}</span>`;

			// Claim button: show when customer has no owner or is owned by someone else
			// (source_pool indicates this came from territory, not from My Accounts)
			const is_unowned = !r.custom_sales_person_user || r.custom_sales_person_user !== frappe.session.user;
			const from_territory = r.source_pool === "Dormant" || r.source_pool === "Regular";
			const claim_btn = (!is_done && is_unowned && from_territory && this._is_manager)
				? `<button class="ib-cb-pill ib-cb-pill--claim ib-cb-btn-claim" data-customer="${frappe.utils.escape_html(r.customer)}" title="Add to My Accounts">
						${IB_ICONS.svg("user", 10)} Claim Account
					</button>`
				: "";

			let actions = "";
			if (!is_done) {
				actions = `
					<div class="ib-cb-card-actions">
						<button class="ib-cb-pill ib-cb-pill--log ib-cb-btn-log">
							${IB_ICONS.svg("clock", 10)} Log Activity
						</button>
						<button class="ib-cb-pill ib-cb-pill--quote ib-cb-btn-q" data-customer="${frappe.utils.escape_html(r.customer)}">
							${IB_ICONS.svg("file", 10)} Quote
						</button>
						${claim_btn}
					</div>`;
			}

			inner_html = `
				<div class="ib-cb-card-top">
					<div class="ib-cb-card-name">${name_html}</div>
					${done_badge}
					${skip_btn}
				</div>
				${done_label}
				${territory_line}
				${contact_line}
				${last_line}
				${prior_line}
				${actions}
			`;
		} else if (ctx === "tomorrow") {
			inner_html = `
				<div class="ib-cb-card-top">
					<div class="ib-cb-card-name">${name_html}</div>
				</div>
				${territory_line}
				${contact_line}
				${last_line}
				<span class="ib-cb-pool-badge">${r.source_pool || ""}</span>
			`;
		}

		// Outcome-based border color for done cards
		const outcome_cls = is_done && r.outcome
			? `ib-cb-card--outcome-${r.outcome.toLowerCase().replace(/ /g, "-")}`
			: "";

		const card_cls = ctx === "pool" ? "ib-cb-card--pool"
			: (ctx === "today" || ctx === "today_done")
				? `ib-cb-card--today${is_done ? " ib-cb-card--done" : ""} ${outcome_cls}`.trim()
			: "ib-cb-card--tomorrow";

		const data_attr = `data-customer="${frappe.utils.escape_html(r.customer)}"${r.name && ctx !== "pool" ? ` data-assignment="${frappe.utils.escape_html(r.name)}"` : ""}`;

		const $card = $(`<div class="ib-cb-card ${card_cls}" ${data_attr}>${inner_html}</div>`);

		// Deep-link: card name always opens the real Customer record (was a
		// dead end before — no navigation existed from board cards at all).
		$card.find(".ib-cb-card-name").addClass("ib-cb-card-name--link").on("click", (e) => {
			e.stopPropagation();
			frappe.set_route("Form", "Customer", r.customer);
		});

		// Event bindings
		if (ctx === "pool") {
			$card.find(".ib-cb-btn-add-today").on("click", function () {
				self._add_to_today($(this).data("customer"), $(this));
			});
			$card.find(".ib-cb-btn-add-tomorrow").on("click", function () {
				self._add_to_tomorrow($(this).data("customer"), $(this));
			});
			$card.find(".ib-cb-btn-share").on("click", function () {
				self._show_share_dialog(r.customer, r.customer_name || r.customer);
			});
			$card.find(".ib-cb-btn-unshare").on("click", function () {
				frappe.confirm(
					`Remove ${frappe.utils.escape_html(r.customer_name || r.customer)} from your board?`,
					() => {
						frappe.call({
							method: "instabiz.overrides.customer_assignment.unshare_customer",
							args: { customer: r.customer, share_with: frappe.session.user },
							callback(res) {
								if (!res.exc) {
									frappe.show_alert({ message: "Removed from your board", indicator: "orange" });
									self.refresh();
								}
							},
						});
					}
				);
			});
		} else if (ctx === "today") {
			$card.find(".ib-cb-btn-q").on("click", () =>
				frappe.new_doc("Quotation", { party_name: r.customer, quotation_to: "Customer" })
			);
			$card.find(".ib-cb-btn-log").on("click", () => self._show_log_activity_dialog(r.customer, r.customer_name, r.name));
			$card.find(".ib-cb-btn-skip").on("click", () => self._skip_with_undo(r.name, r.customer_name || r.customer, $card));
			$card.find(".ib-cb-btn-claim").on("click", function () {
				const cust = $(this).data("customer");
				const cust_name = r.customer_name || cust;
				frappe.confirm(
					`Add <b>${frappe.utils.escape_html(cust_name)}</b> to your My Accounts?<br>` +
					`This permanently assigns the customer to you.`,
					() => {
						frappe.call({
							method: "instabiz.overrides.customer_assignment.self_assign_customer",
							args: { customer: cust },
							callback(res) {
								if (res.exc) return;
								frappe.show_alert({ message: `${cust_name} added to My Accounts`, indicator: "green" });
								self.refresh();
							},
						});
					}
				);
			});
		}

		return $card;
	}

	// ── Drag & Drop (SortableJS) ──────────────────────────────────────────────

	_init_sortable() {
		const self = this;

		// Destroy previous instances to avoid duplicate listeners after re-render
		this._sortables.forEach((s) => s.destroy());
		this._sortables = [];

		this._sortable_ready.then(() => {
			const pool_opts = {
				group: { name: "ib-pool", pull: "clone", put: false },
				sort: false,
				animation: 0,
				ghostClass: "ib-cb-drag-ghost",
				chosenClass: "ib-cb-drag-chosen",
				forceFallback: false,
			};

			const dormantEl = document.getElementById("ib-cb-dormant-cards");
			if (dormantEl) self._sortables.push(new Sortable(dormantEl, pool_opts));

			const make_board_opts = (date, col_id, accept_group) => ({
				group: { name: col_id, pull: true, put: ["ib-pool", accept_group] },
				sort: false,
				animation: 150,
				ghostClass: "ib-cb-drag-ghost",
				filter: ".ib-cb-card--done",
				onAdd(evt) {
					const customer = evt.item.dataset.customer;
					const assignment = evt.item.dataset.assignment;
					evt.item.remove();
					if (!customer) return;
					if (assignment) {
						self._move_assignment(assignment, customer, date, col_id);
					} else {
						self._drop_to_date(customer, date, col_id);
					}
				},
			});

			const today_el = document.getElementById("ib-cb-today-cards");
			if (today_el) self._sortables.push(new Sortable(today_el, make_board_opts(self._selected_date, "ib-cb-today", "ib-cb-tomorrow")));

			const tmrw_el = document.getElementById("ib-cb-tomorrow-cards");
			if (tmrw_el) self._sortables.push(new Sortable(tmrw_el, make_board_opts(self._tomorrow_date, "ib-cb-tomorrow", "ib-cb-today")));
		});
	}

	_drop_to_date(customer, date, col_id) {
		const self = this;
		const is_today = date === self._selected_date;
		frappe.call({
			method: "instabiz.overrides.customer_assignment.add_customer_to_today",
			args: { customer, date },
			callback(r) {
				if (r.message && r.message.status === "ok") {
					self._gsap_ready.then(() => {
						gsap.fromTo(`#${col_id}`,
							{ boxShadow: `inset 0 0 0 2px ${IB_CB_COLOR_SUCCESS}` },
							{ boxShadow: `inset 0 0 0 0px ${IB_CB_COLOR_SUCCESS}`, duration: 0.7, ease: "power2.out", clearProps: "boxShadow" }
						);
					});
					if (is_today) {
						self._show_undo_toast(customer, r.message.assignment);
					} else {
						frappe.show_alert({ message: `${customer} added to Tomorrow`, indicator: "blue" });
					}
					self._highlight_customer = customer;
					self.refresh();
				} else {
					frappe.show_alert({ message: `Could not add ${customer}`, indicator: "red" });
				}
			},
			error() {
				frappe.show_alert({ message: `Error adding ${customer}`, indicator: "red" });
			},
		});
	}

	_move_assignment(assignment_id, customer, date, col_id) {
		const self = this;
		frappe.call({
			method: "instabiz.overrides.customer_assignment.move_assignment",
			args: { assignment_id, new_date: date },
			callback(r) {
				if (r.message && r.message.status === "ok") {
					self._flush_pending();
					self._gsap_ready.then(() => {
						gsap.fromTo(`#${col_id}`,
							{ boxShadow: `inset 0 0 0 2px ${IB_CB_COLOR_SUCCESS}` },
							{ boxShadow: `inset 0 0 0 0px ${IB_CB_COLOR_SUCCESS}`, duration: 0.7, ease: "power2.out", clearProps: "boxShadow" }
						);
					});
					self._highlight_customer = customer;
					self.refresh();
				} else {
					frappe.show_alert({ message: `Could not move ${customer}`, indicator: "red" });
					self.refresh();
				}
			},
			error() {
				frappe.show_alert({ message: `Error moving ${customer}`, indicator: "red" });
				self.refresh();
			},
		});
	}

	// ── Add to Today / Tomorrow (button path) ────────────────────────────────

	_add_to_today(customer, $btn) {
		const self = this;
		const $card = $btn.closest(".ib-cb-card");
		$btn.prop("disabled", true);

		this._gsap_ready.then(() => {
			const srcRect = $card[0].getBoundingClientRect();
			const $todayCards = $("#ib-cb-today-cards");
			const targetRect = $todayCards[0].getBoundingClientRect();

			const clone = document.createElement("div");
			clone.className = "ib-cb-card ib-cb-card--today";
			clone.innerHTML = $card.html();
			clone.querySelector(".ib-cb-btn-add-today")?.remove();
			Object.assign(clone.style, {
				position: "fixed",
				top: srcRect.top + "px",
				left: srcRect.left + "px",
				width: srcRect.width + "px",
				margin: "0",
				zIndex: "9000",
				pointerEvents: "none",
			});
			document.body.appendChild(clone);

			gsap.set($card[0], { opacity: 0.35 });

			gsap.to(clone, {
				top: targetRect.top + 8,
				left: targetRect.left + 8,
				width: targetRect.width - 16,
				opacity: 0,
				scale: 0.94,
				duration: 0.52,
				ease: "power3.inOut",
				onComplete: () => clone.remove(),
			});

			frappe.call({
				method: "instabiz.overrides.customer_assignment.add_customer_to_today",
				args: { customer, date: self._selected_date },
				callback(r) {
					if (r.message && r.message.status === "ok") {
						gsap.to($card[0], {
							opacity: 0, scale: 0.92, duration: 0.22, ease: "power2.in",
							onComplete: () => { self._show_undo_toast(customer, r.message.assignment); self._highlight_customer = customer; self.refresh(); },
						});
					} else {
						gsap.to($card[0], { opacity: 1, duration: 0.2 });
						$btn.prop("disabled", false);
					}
				},
				error() {
					gsap.to($card[0], { opacity: 1, duration: 0.2 });
					$btn.prop("disabled", false);
				},
			});
		});
	}

	_add_to_tomorrow(customer, $btn) {
		const self = this;
		$btn.prop("disabled", true);
		frappe.call({
			method: "instabiz.overrides.customer_assignment.add_customer_to_today",
			args: { customer, date: self._tomorrow_date },
			callback(r) {
				if (r.message && r.message.status === "ok") {
					self._flush_pending();
					self._highlight_customer = customer;
					self.refresh();
				} else {
					$btn.prop("disabled", false);
				}
			},
			error() { $btn.prop("disabled", false); },
		});
	}

	// ── Timed toast (generic) ─────────────────────────────────────────────────

	_show_timed_toast(msg, on_timeout, on_undo) {
		const self = this;

		// Previous toast still pending — commit it immediately before showing new one
		if (this._undo_timer) {
			clearInterval(this._undo_timer);
			this._undo_timer = null;
			if (this._pending_on_timeout) {
				this._pending_on_timeout();
				this._pending_on_timeout = null;
			}
		}

		this._pending_on_timeout = on_timeout;

		const $toast = $("#ib-cb-undo-toast");
		const $fill  = $("#ib-cb-undo-bar-fill");
		const $btn   = $("#ib-cb-undo-btn");

		$("#ib-cb-undo-msg").text(msg);
		$fill.css({ width: "100%", transition: "none" });
		$toast.addClass("ib-cb-undo-toast--visible");

		requestAnimationFrame(() => {
			$fill.css({ transition: "width 5s linear", width: "0%" });
		});

		let elapsed = 0;
		this._undo_timer = setInterval(() => {
			elapsed += 100;
			if (elapsed >= 5000) {
				clearInterval(self._undo_timer);
				self._undo_timer = null;
				self._pending_on_timeout = null;
				$toast.removeClass("ib-cb-undo-toast--visible");
				if (on_timeout) on_timeout();
			}
		}, 100);

		$btn.off("click").on("click", () => {
			clearInterval(self._undo_timer);
			self._undo_timer = null;
			self._pending_on_timeout = null;
			$toast.removeClass("ib-cb-undo-toast--visible");
			if (on_undo) on_undo();
		});
	}

	_show_undo_toast(customer, assignment_id) {
		const self = this;
		this._show_timed_toast(
			`${customer} added to Today`,
			null,
			() => {
				frappe.call({
					method: "instabiz.overrides.customer_assignment.remove_assignment",
					args: { assignment_id },
					callback(r) {
						if (r.message && r.message.status === "ok") {
							frappe.show_alert({ message: `${customer} removed from Today`, indicator: "orange" });
							self.refresh();
						}
					},
				});
			}
		);
	}

	// ── Actions ───────────────────────────────────────────────────────────────

	_flush_pending() {
		if (this._undo_timer) {
			clearInterval(this._undo_timer);
			this._undo_timer = null;
		}
		if (this._pending_on_timeout) {
			const cb = this._pending_on_timeout;
			this._pending_on_timeout = null;
			$("#ib-cb-undo-toast").removeClass("ib-cb-undo-toast--visible");
			cb();
		}
	}

	_show_log_activity_dialog(customer, customer_name, assignment_id) {
		const self = this;
		const d = new frappe.ui.Dialog({
			title: `Log Activity — ${frappe.utils.escape_html(customer_name || customer)}`,
			fields: [
				{
					fieldname: "activity_type",
					label: "Activity Type",
					fieldtype: "Select",
					options: "Call\nMeeting\nWhatsApp\nEmail\nVisit",
					reqd: 1,
				},
				{
					fieldname: "outcome",
					label: "Outcome",
					fieldtype: "Select",
					options: "Interested\nNot Interested\nFollow Up\nNo Response",
					reqd: 1,
				},
				{
					fieldname: "notes",
					label: "Notes",
					fieldtype: "Small Text",
					reqd: 1,
				},
			],
			primary_action_label: "Log",
			primary_action(values) {
				// Log comment on Customer timeline
				frappe.call({
					method: "instabiz.overrides.customer.log_customer_activity",
					args: {
						customer,
						activity_type: values.activity_type,
						outcome: values.outcome,
						notes: values.notes,
					},
					callback(r) {
						if (r.exc) return;
						d.hide();
						// If called from a Today assignment card, also mark it done
						if (assignment_id) {
							frappe.call({
								method: "instabiz.overrides.customer_assignment.mark_customer_contacted",
								args: {
									assignment_id,
									notes: values.notes,
									outcome: values.outcome,
								},
								callback(r2) {
									if (!r2.exc) {
										frappe.show_alert({ message: "Activity logged", indicator: "green" });
										self._flush_pending();
										self._highlight_customer = customer;
										self._highlight_color = IB_CB_COLOR_ACTIVITY;
										self.refresh();
									}
								},
							});
						} else {
							frappe.show_alert({ message: "Activity logged", indicator: "green" });
						}
					},
				});
			},
		});
		d.show();
	}

	_skip_with_undo(assignment_id, customer_name, $card) {
		const self = this;
		const customer_id = $card.data("customer");
		const safe_name = frappe.utils.escape_html(customer_name);
		frappe.confirm(`Skip ${safe_name} for today?`, () => {
			// Optimistic: visually mark skipped
			$card.addClass("ib-cb-card--done ib-cb-card--outcome-skipped");
			$card.find(".ib-cb-skip-btn").remove();
			$card.find(".ib-cb-card-actions").remove();
			$card.find(".ib-cb-status").remove();
			const $top = $card.find(".ib-cb-card-top");
			if (!$top.find(".ib-cb-done-badge").length) {
				$top.find(".ib-cb-status").remove();
				$top.find(".ib-cb-card-name").after(`<span class="ib-cb-done-badge ib-cb-done-badge--skip">SKIP</span>`);
			}

			self._show_timed_toast(
				`${safe_name} skipped`,
				() => {
					frappe.call({
						method: "instabiz.overrides.customer_assignment.skip_assignment",
						args: { assignment_id },
						callback(r) {
							if (r.message && r.message.status === "ok") {
								self._highlight_customer = customer_id;
								self._highlight_color = IB_CB_COLOR_DANGER;
								self.refresh();
							} else {
								frappe.show_alert({ message: "Skip failed", indicator: "red" });
								self.refresh();
							}
						},
					});
				},
				() => {
					frappe.show_alert({ message: `${safe_name} restored`, indicator: "blue" });
					self.refresh();
				}
			);
		});
	}

	_flash_new_card(customer, color = IB_CB_COLOR_SUCCESS) {
		const self = this;
		const esc = customer.replace(/["\\]/g, "\\$&");
		const $card = $(`.ib-cb-card[data-customer="${esc}"]`).first();
		if (!$card.length) return;
		$card[0].scrollIntoView({ behavior: "smooth", block: "nearest" });
		const rgb = color === IB_CB_COLOR_DANGER ? IB_CB_COLOR_DANGER_RGB : IB_CB_COLOR_SUCCESS_RGB;
		self._gsap_ready.then(() => {
			gsap.fromTo($card[0],
				{ boxShadow: `0 0 0 2px ${color}, 0 0 18px rgba(${rgb},0.45)` },
				{ boxShadow: `0 0 0 0px ${color}, 0 0 0px rgba(${rgb},0)`, duration: 1.6, ease: "power3.out", clearProps: "boxShadow" }
			);
		});
	}

	// ── Customer Sharing ─────────────────────────────────────────────────────

	_show_share_dialog(customer, customer_name) {
		const self = this;

		frappe.call({
			method: "instabiz.overrides.customer_assignment.get_customer_shares",
			args: { customer },
			callback(r) {
				if (r.exc) return;
				const current_shares = r.message || [];

				frappe.call({
					method: "frappe.client.get_list",
					args: {
						doctype: "User",
						filters: [
							["Has Role", "role", "=", "Sales User"],
							["enabled", "=", 1],
							["name", "!=", frappe.session.user],
						],
						fields: ["name", "full_name"],
						limit: 200,
					},
					callback(r2) {
						if (r2.exc) return;
						const all_users = r2.message || [];
						const shared_with_set = new Set(current_shares.map((s) => s.shared_with));

						// Build current shares table HTML
						const shares_html = current_shares.length
							? `<div class="ib-share-current">
								<div class="ib-share-section-lbl">Currently shared with:</div>
								${current_shares.map((s) => `
									<div class="ib-share-row" data-user="${frappe.utils.escape_html(s.shared_with)}">
										<span class="ib-share-user">${frappe.utils.escape_html(s.shared_with_name || s.shared_with)}</span>
										<button class="ib-share-remove btn btn-xs btn-danger" data-user="${frappe.utils.escape_html(s.shared_with)}">Remove</button>
									</div>
								`).join("")}
							</div>`
							: `<div class="ib-share-empty">Not shared with anyone yet.</div>`;

						// Available users to share with (exclude already-shared + owner)
						const owner = frappe.session.user;
						const available = all_users.filter((u) => !shared_with_set.has(u.name) && u.name !== owner);

						const d = new frappe.ui.Dialog({
							title: `Share — ${frappe.utils.escape_html(customer_name)}`,
							fields: [
								{
									fieldname: "current_shares_html",
									fieldtype: "HTML",
									options: shares_html,
								},
								{
									fieldname: "share_with_section",
									fieldtype: "Section Break",
									label: available.length ? "Add Share" : "",
								},
								...(available.length ? [{
									fieldname: "share_with",
									label: "Share With",
									fieldtype: "Select",
									options: available.map((u) => `${u.name}|${u.full_name || u.name}`).join("\n"),
									reqd: 0,
								}] : [{
									fieldname: "_no_users_html",
									fieldtype: "HTML",
									options: `<div class="text-muted">All available users already have access.</div>`,
								}]),
							],
							primary_action_label: available.length ? "Share" : "Close",
							primary_action(values) {
								if (!available.length) { d.hide(); return; }
								const target = (values.share_with || "").split("|")[0];
								if (!target) { frappe.show_alert({ message: "Select a user", indicator: "orange" }); return; }
								frappe.call({
									method: "instabiz.overrides.customer_assignment.share_customer",
									args: { customer, share_with: target },
									callback(res) {
										if (!res.exc) {
											const uname = available.find((u) => u.name === target);
											frappe.show_alert({ message: `Shared with ${uname ? uname.full_name : target}`, indicator: "green" });
											d.hide();
											self.refresh();
										}
									},
								});
							},
						});

						d.show();

						// Bind remove buttons in the current-shares section
						d.$wrapper.find(".ib-share-remove").on("click", function () {
							const target = $(this).data("user");
							const $row = $(this).closest(".ib-share-row");
							frappe.call({
								method: "instabiz.overrides.customer_assignment.unshare_customer",
								args: { customer, share_with: target },
								callback(res) {
									if (!res.exc) {
										$row.fadeOut(200, function () { $(this).remove(); });
										frappe.show_alert({ message: "Access removed", indicator: "orange" });
										self.refresh();
									}
								},
							});
						});
					},
				});
			},
		});
	}

}

/* ─── Team tab (ex ib_assignment_admin.js's IBAssignmentAdmin) ───────────── */
class IBAssignmentAdmin {
	constructor(page, $container) {
		this.page = page;
		this.$main = $container;
		this._date = frappe.datetime.get_today();
		this._territory = null;
		this._view_as_user = null;
		this._dropdown_users_cache = [];
		this._excluded_users = new Set(JSON.parse(localStorage.getItem("ib_aa_excluded_users") || "[]"));
		this._collapsed_teams = new Set(JSON.parse(localStorage.getItem("ib_aa_collapsed_teams") || "[]"));
		this._roster_search = "";
		this._init();
	}

	_next_working_day(dateStr) {
		const d = new Date(dateStr + "T00:00:00");
		do { d.setDate(d.getDate() + 1); } while (d.getDay() === 0 || d.getDay() === 6);
		return d.toISOString().split("T")[0];
	}

	_terr_abbr(name) {
		const words = name.split(/\s+/).filter(w => w !== "&" && w !== "and");
		if (words.length === 1) return words[0].slice(0, 3).toUpperCase();
		return words.map(w => w[0]).join("").slice(0, 3).toUpperCase();
	}

	_avatar_color(_user, team) {
		// Same team → same color; no team → primary brand color
		if (!team) return "var(--ib-primary)";
		const palette = [
			"#2563eb","#7c3aed","#059669","#dc2626",
			"#d97706","#0891b2","#be185d","#4f46e5","#65a30d","#0f766e",
		];
		let h = 0;
		for (let i = 0; i < team.length; i++) h = (h * 31 + team.charCodeAt(i)) >>> 0;
		return palette[h % palette.length];
	}

	_init() {
		this._build_toolbar();
		this._build_layout();
		this._inject_styles();
		this._init_kebab();
		this.refresh();
	}

	// ── Toolbar ──────────────────────────────────────────────────────────────

	_build_toolbar() {
		const self = this;
		this.page.add_field({
			fieldname: "admin_date",
			fieldtype: "Date",
			label: "Date",
			default: frappe.datetime.get_today(),
			change() {
				self._date = this.get_value() || frappe.datetime.get_today();
				self._view_as_user = null;
				self.refresh();
			},
		});
		this.page.add_field({
			fieldname: "admin_territory",
			fieldtype: "Link",
			label: "State",
			options: "Territory",
			change() {
				self._territory = this.get_value() || null;
				self.refresh();
			},
		});
		const _is_full_manager = frappe.user.has_role("Sales Manager") || frappe.user.has_role("System Manager");
		if (_is_full_manager) {
			this.page.add_inner_button("+ Create New Team", () => self._show_create_team_modal());
			this.page.add_inner_button("Incentive Slabs", () => self._show_slab_dialog());
			this.page.add_inner_button("View Incentives ↗", () => frappe.set_route("ib-sales-incentives"));
		}
		this.page.add_inner_button("Refresh", () => self.refresh());
	}

	// ── Layout ────────────────────────────────────────────────────────────────

	_build_layout() {
		this.$main.html(`
			<div class="ib-aa-root">

				<!-- ── Team Overview ── -->
				<section class="ib-aa-section">
					<div class="ib-aa-section-head">
						<span class="ib-aa-section-title">Team Overview</span>
						<input class="ib-aa-roster-search form-control" id="ib-aa-roster-search" type="text" placeholder="Search users…">
						<span class="ib-aa-section-date" id="ib-aa-date-label"></span>
					</div>
					<div id="ib-aa-hidden-strip" style="display:none;" class="ib-aa-hidden-strip"></div>
					<div class="ib-aa-roster" id="ib-aa-roster"></div>
				</section>

				<!-- ── View As Banner ── -->
				<div id="ib-aa-view-as-bar" class="ib-aa-view-as-bar" style="display:none;">
					<div class="ib-aa-view-as-inner">
						${IB_ICONS.svg("eye", 14)}
						<span id="ib-aa-view-as-label"></span>
					</div>
					<button class="ib-aa-exit-view-btn" id="ib-aa-exit-view">✕ Exit</button>
				</div>

				<!-- ── Board View (view-as) ── -->
				<div id="ib-aa-board-wrap"></div>

				</div>
		`);
		this._bind_events();
	}

	_bind_events() {
		const self = this;

		// Roster search
		let _rst;
		this.$main.on("input", "#ib-aa-roster-search", function () {
			clearTimeout(_rst);
			_rst = setTimeout(() => {
				self._roster_search = this.value.trim();
				self._refilter_roster();
			}, 150);
		});

		this.$main.on("click", "#ib-aa-exit-view", () => {
			self._view_as_user = null;
			$("#ib-aa-view-as-bar").hide();
			$("#ib-aa-board-wrap").empty();
		});
	}

	// ── Data ─────────────────────────────────────────────────────────────────

	refresh() {
		const self = this;
		const is_hist = this._date !== frappe.datetime.get_today();
		$("#ib-aa-date-label")
			.text(frappe.datetime.str_to_user(this._date) + (is_hist ? " · Historical" : ""))
			.toggleClass("ib-aa-section-date--hist", is_hist);
		frappe.call({
			method: "instabiz.overrides.customer_assignment.get_admin_overview",
			args: { date: this._date, territory: this._territory },
			callback(r) {
				if (!r.message) return;
				const { roster, team_territories, is_manager, leader_team } = r.message;
				self._is_manager = !!is_manager;
				self._leader_team = leader_team || null;
				self._apply_role_visibility();
				self._render_roster(roster, team_territories || {});
			},
		});
		this._fetch_users_cache();
		if (this._view_as_user) this._reload_va_board();
	}

	_apply_role_visibility() {
		const isLeader = !this._is_manager && !!this._leader_team;
		// Hide manager-only controls for team leaders
		this.page.inner_toolbar.find("button").filter((_, el) =>
			["+ Create New Team"].includes($(el).text().trim())
		).toggle(!isLeader);
		this.page.fields_dict?.admin_territory?.$wrapper?.toggle(!isLeader);
	}

	_fetch_users_cache() {
		const self = this;
		frappe.call({
			method: "frappe.client.get_list",
			args: {
				doctype: "User",
				filters: [["Has Role", "role", "=", "Sales User"], ["enabled", "=", 1]],
				fields: ["name", "full_name"],
				limit: 100,
			},
			callback(r) {
				if (!r.message) return;
				self._dropdown_users_cache = r.message;
			},
		});
	}
	// ── Roster ────────────────────────────────────────────────────────────────

	_save_excluded() {
		localStorage.setItem("ib_aa_excluded_users", JSON.stringify([...this._excluded_users]));
	}

	_refilter_roster() {
		if (this._last_roster) this._render_roster(this._last_roster, this._last_team_territories);
	}

	_reload_roster() {
		const self = this;
		frappe.call({
			method: "instabiz.overrides.customer_assignment.get_admin_overview",
			args: { date: self._date, territory: self._territory },
			callback(r) {
				if (r.message) self._render_roster(r.message.roster, r.message.team_territories || {});
			},
		});
	}

	_render_roster(roster, team_territories) {
		this._last_roster = roster;
		this._last_team_territories = team_territories || this._last_team_territories || {};
		const self = this;
		const $g = $("#ib-aa-roster").empty();
		if (!roster || !roster.length) {
			$g.html('<p class="ib-aa-empty">No sales users found</p>');
			return;
		}

		const tokens = this._roster_search.toLowerCase().split(/\s+/).filter(Boolean);
		const after_exclude = roster.filter(u => !self._excluded_users.has(u.user));
		const visible = tokens.length
			? after_exclude.filter(u => {
				const hay = `${u.full_name || ""} ${u.user} ${u.team || ""}`.toLowerCase();
				return tokens.every(t => hay.includes(t));
			})
			: after_exclude;
		const hidden_count = roster.length - after_exclude.length;

		const $strip = $("#ib-aa-hidden-strip");
		if (hidden_count > 0) {
			$strip.html(`${IB_ICONS.svg("eye_off", 13)} ${hidden_count} user${hidden_count > 1 ? "s" : ""} hidden &mdash; <a href="#" class="ib-aa-show-all-link">Show all</a>`).show();
			$strip.find(".ib-aa-show-all-link").on("click", (e) => {
				e.preventDefault();
				self._excluded_users.clear();
				self._save_excluded();
				self._render_roster(roster, team_territories);
			});
		} else {
			$strip.hide();
		}

		if (!visible.length) {
			if (tokens.length) {
				$g.html(`<p class="ib-aa-empty">No users match "<strong>${frappe.utils.escape_html(this._roster_search)}</strong>"</p>`);
			} else {
				$g.html('<p class="ib-aa-empty">All users hidden — <a href="#" class="ib-aa-show-all-link">show all</a></p>');
				$g.find(".ib-aa-show-all-link").on("click", (e) => {
					e.preventDefault();
					self._excluded_users.clear();
					self._save_excluded();
					self._render_roster(roster, team_territories);
				});
			}
			return;
		}

		// Group by team; no team → "Unassigned"
		const groups = {};
		visible.forEach(u => {
			const key = u.team || "__none__";
			if (!groups[key]) groups[key] = [];
			groups[key].push(u);
		});

		// Column header row
		$g.append(`
			<div class="ib-aa-roster-thead">
				<div class="ib-aa-rth ib-aa-rth--name"></div>
				<div class="ib-aa-rth ib-aa-rth--stat">Done</div>
				<div class="ib-aa-rth ib-aa-rth--stat">Pending</div>
				<div class="ib-aa-rth ib-aa-rth--stat">Tomorrow</div>
				<div class="ib-aa-rth ib-aa-rth--target">Sales Target</div>
				<div class="ib-aa-rth ib-aa-rth--actions"></div>
			</div>
		`);

		const render_group = (team_key, users) => {
			const av_color = self._avatar_color(users[0].user, users[0].team);
			const team_label = team_key === "__none__" ? "Unassigned" : team_key;
			const avg_pct = Math.round(users.reduce((s, u) => s + (u.target_pct || 0), 0) / users.length);
			const is_collapsed = self._collapsed_teams.has(team_key);

			const terr_list = (team_territories || {})[team_key] || [];
			const terr_chips = terr_list.length
				? terr_list.map(t => `<span class="ib-aa-terr-chip">${frappe.utils.escape_html(self._terr_abbr(t))}</span>`).join("")
				: "";

			const $group = $(`
				<div class="ib-aa-team-group">
					<div class="ib-aa-team-hdr" style="--team-color:${av_color}">
						<svg class="ib-aa-team-chevron${is_collapsed ? " ib-aa-team-chevron--collapsed" : ""}" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
						<span class="ib-aa-team-dot"></span>
						<span class="ib-aa-team-label">${frappe.utils.escape_html(team_label)}</span>
						${terr_chips ? `<span class="ib-aa-terr-chips">${terr_chips}</span>` : ""}
						<span class="ib-aa-team-meta">${users.length} member${users.length > 1 ? "s" : ""} &middot; avg ${avg_pct}%</span>
						${team_key !== "__none__" && this._is_manager ? `<button class="ib-aa-btn-team-kebab" title="Manage team">⋮</button>` : ""}
					</div>
					<div class="ib-aa-team-body${is_collapsed ? " ib-aa-team-body--collapsed" : ""}"></div>
				</div>
			`);

			$group.find(".ib-aa-team-hdr").on("click", (e) => {
				if ($(e.target).closest(".ib-aa-btn-team-kebab").length) return;
				const collapsed = !self._collapsed_teams.has(team_key);
				collapsed ? self._collapsed_teams.add(team_key) : self._collapsed_teams.delete(team_key);
				localStorage.setItem("ib_aa_collapsed_teams", JSON.stringify([...self._collapsed_teams]));
				$group.find(".ib-aa-team-body").toggleClass("ib-aa-team-body--collapsed", collapsed);
				$group.find(".ib-aa-team-chevron").toggleClass("ib-aa-team-chevron--collapsed", collapsed);
			});

			if (team_key !== "__none__") {
				$group.find(".ib-aa-btn-team-kebab").on("click", function(e) {
					e.stopPropagation();
					self._show_team_kebab(this, team_key, team_label);
				});
			}

			users.forEach(u => {
				const initials = (u.full_name || u.user).split(" ").map(w => w[0]).slice(0, 2).join("").toUpperCase();
				const av = self._avatar_color(u.user, u.team);
				const is_today = self._date === frappe.datetime.get_today();
				const no_tmrw = is_today && (u.tomorrow_count || 0) === 0;

				const fmt_short = (v) => {
					if (!v) return "₹0";
					if (v >= 1e7) return "₹" + (v / 1e7).toFixed(1) + "Cr";
					if (v >= 1e5) return "₹" + (v / 1e5).toFixed(1) + "L";
					return "₹" + Math.round(v).toLocaleString("en-IN");
				};
				const fmt_full = (v) => "₹" + Math.round(v || 0).toLocaleString("en-IN");
				const tpct = u.target_pct || 0;
				const tpct_cls = tpct >= 80 ? "good" : tpct >= 40 ? "mid" : "low";
				const tbar_color = tpct >= 80 ? "#22c55e" : tpct >= 40 ? "var(--ib-primary)" : "#cbd5e1";
				const incentive_html = u.incentive_earned
					? `<span class="ib-aa-incentive-chip" title="Commission ${u.commission_pct || 0}%">
						<iconify-icon icon="lucide:trophy" width="11" height="11" style="vertical-align:middle;margin-right:3px"></iconify-icon>${fmt_short(u.incentive_earned)}
					</span>` : "";
				const target_html = u.target ? `<div class="ib-aa-row-target-wrap">
					<div class="ib-aa-row-target-text">
						<span class="ib-aa-target-actual ib-aa-pct--${tpct_cls}" title="${fmt_full(u.actual)}">${fmt_short(u.actual || 0)}</span>
						<span class="ib-aa-target-sep">/</span>
						<span class="ib-aa-target-goal" title="${fmt_full(u.target)}">${fmt_short(u.target || 0)}</span>
						<span class="ib-aa-target-pct ib-aa-pct--${tpct_cls}">${tpct}%</span>
						${incentive_html}
					</div>
					<div class="ib-aa-target-bar-track">
						<div class="ib-aa-target-bar-fill" style="width:${Math.min(tpct,100)}%;background:${tbar_color}"></div>
					</div>
				</div>` : `<div class="ib-aa-row-target-wrap"><span class="ib-aa-target-goal" style="padding-left:8px">—</span></div>`;

				const $row = $(`
					<div class="ib-aa-user-row">
						<div class="ib-aa-row-identity">
							<div class="ib-aa-row-avatar" style="background:${av}">${initials}</div>
							<div class="ib-aa-row-name-wrap">
								<span class="ib-aa-row-name">${frappe.utils.escape_html(u.full_name || u.user)}</span>
								${u.is_leader ? `<svg class="ib-aa-tl-badge" viewBox="0 0 24 24" width="26" height="26" title="Team Leader" xmlns="http://www.w3.org/2000/svg"><polygon points="12,1 13.6,6.2 17.5,2.5 16.2,7.8 21.5,6.5 17.8,10.5 23,12 17.8,13.6 21.5,17.5 16.2,16.2 17.5,21.5 13.6,17.8 12,23 10.4,17.8 6.5,21.5 7.8,16.2 2.5,17.5 6.2,13.6 1,12 6.2,10.4 2.5,6.5 7.8,7.8 6.5,2.5 10.4,6.2" fill="#f59e0b"/><text x="12" y="14.5" text-anchor="middle" font-size="6.5" font-weight="900" fill="white" font-family="Inter,sans-serif">TL</text></svg>` : ""}
								${no_tmrw ? `<iconify-icon icon="lucide:alert-triangle" width="12" height="12" class="ib-aa-no-tmrw-dot" title="No assignments queued for tomorrow" style="color:#f59e0b;vertical-align:middle"></iconify-icon>` : ""}
							</div>
						</div>
						<div class="ib-aa-row-stat ib-aa-row-stat--done">${u.done}</div>
						<div class="ib-aa-row-stat ib-aa-row-stat--pending">${u.pending}</div>
						<div class="ib-aa-row-stat ib-aa-row-stat--tmrw">${u.tomorrow_count}</div>
						${target_html}
						<div class="ib-aa-row-actions">
							<button class="ib-aa-btn-kebab" title="Actions">⋮</button>
						</div>
					</div>
				`);

				$row.find(".ib-aa-btn-kebab").on("click", function(e) {
					e.stopPropagation();
					self._show_kebab(this, u);
				});
				$group.find(".ib-aa-team-body").append($row);
			});

			$g.append($group);
		};

		// Named teams first, then unassigned
		Object.keys(groups).filter(k => k !== "__none__").sort().forEach(k => render_group(k, groups[k]));
		if (groups["__none__"]) render_group("__none__", groups["__none__"]);
	}

	// ── Kebab menu ───────────────────────────────────────────────────────────

	_init_kebab() {
		this._$kdrop = $('<div class="ib-aa-kdrop" style="display:none"></div>').appendTo("body");
		$(document).on("click.ib_aa_kebab", (e) => {
			if (!$(e.target).closest(".ib-aa-kdrop, .ib-aa-btn-kebab, .ib-aa-btn-team-kebab").length) {
				this._$kdrop.hide();
			}
		});
	}

	// Called by IBCustomerBoardShell._teardown_active() on every tab switch
	// (Team → My Board, date/territory change re-entry, or on_page_hide).
	// This class gets freshly reconstructed on every "Team" tab activation
	// now that it lives inside a shell, so the two pieces of state that
	// escape this instance's own $main scope — the document-level kebab
	// click listener and the kebab dropdown appended straight to <body> —
	// must be explicitly released here, or the next activation stacks a
	// second listener/element on top of the first (namespaced with
	// ".ib_aa_kebab" specifically so this .off() can't clobber unrelated
	// document click handlers elsewhere on the page). The view-as undo
	// toast's setInterval is the other piece of state that outlives a
	// single render pass — same class of bug item 125 fixed for
	// IBStockDashboard's _live/_auto timers.
	_cleanup() {
		$(document).off("click.ib_aa_kebab");
		if (this._$kdrop) {
			this._$kdrop.remove();
			this._$kdrop = null;
		}
		if (this._va_undo_timer) {
			clearInterval(this._va_undo_timer);
			this._va_undo_timer = null;
		}
	}

	_show_kebab(btn, u) {
		const self = this;
		const $d = this._$kdrop;
		const rect = btn.getBoundingClientRect();
		const fmt_inr = v => v ? "₹" + Number(v).toLocaleString("en-IN", { maximumFractionDigits: 0 }) : "—";

		const _mgr_only = this._is_manager;
		$d.html(`
			<div class="ib-aa-kdrop-header">
				<div class="ib-aa-kdrop-name">${frappe.utils.escape_html(u.full_name || u.user)}</div>
				${u.target ? `<div class="ib-aa-kdrop-target">${fmt_inr(u.actual)} / ${fmt_inr(u.target)} &mdash; ${u.target_pct || 0}%</div>` : ""}
			</div>
			<button class="ib-aa-kdrop-item ib-aa-kdrop-view">View board</button>
			${_mgr_only ? `
			<button class="ib-aa-kdrop-item ib-aa-kdrop-auto">Auto-fill</button>
			<button class="ib-aa-kdrop-item ib-aa-kdrop-transfer">Transfer</button>
			<button class="ib-aa-kdrop-item ib-aa-kdrop-set-target">Set target</button>
			<div class="ib-aa-kdrop-sep"></div>
			<button class="ib-aa-kdrop-item ib-aa-kdrop-hide">Hide user</button>
			` : ""}
		`);

		const dropW = 210;
		let left = rect.right - dropW + window.scrollX;
		if (left < 8) left = 8;
		$d.css({ top: rect.bottom + window.scrollY + 6, left, width: dropW, display: "block" });

		$d.find(".ib-aa-kdrop-view").on("click", () => { $d.hide(); self._view_as(u.user, u.full_name, u); });
		$d.find(".ib-aa-kdrop-auto").on("click", () => { $d.hide(); self._bulk_auto_assign(u.user, u.full_name); });
		$d.find(".ib-aa-kdrop-transfer").on("click", () => { $d.hide(); self._transfer_assignments(u.user, u.full_name, u.pending); });
		$d.find(".ib-aa-kdrop-set-target").on("click", () => { $d.hide(); self._show_set_target_dialog(u); });
		$d.find(".ib-aa-kdrop-hide").on("click", () => {
			$d.hide();
			self._excluded_users.add(u.user);
			self._save_excluded();
			self._render_roster(self._last_roster, self._last_team_territories);
		});
	}

	// ── Team kebab + manage modal ─────────────────────────────────────────────

	_show_team_kebab(btn, team_key, team_label) {
		const self = this;
		const $d = this._$kdrop;
		const rect = btn.getBoundingClientRect();

		$d.html(`
			<div class="ib-aa-kdrop-header">
				<div class="ib-aa-kdrop-name">${frappe.utils.escape_html(team_label)}</div>
			</div>
			<button class="ib-aa-kdrop-item ib-aa-kdrop-manage-team">Manage Team</button>
		`);

		const dropW = 180;
		let left = rect.right - dropW + window.scrollX;
		if (left < 8) left = 8;
		$d.css({ top: rect.bottom + window.scrollY + 6, left, width: dropW, display: "block" });

		$d.find(".ib-aa-kdrop-manage-team").on("click", () => {
			$d.hide();
			self._show_team_manage_modal(team_key);
		});
	}

	_show_set_target_dialog(u) {
		const self = this;
		const month_first = this._date.slice(0, 7) + "-01";
		const month_label = frappe.datetime.str_to_user(month_first).slice(3); // "MMM YYYY"
		const fmt_inr = v => v ? "₹" + Number(v).toLocaleString("en-IN", { maximumFractionDigits: 0 }) : "₹0";

		const d = new frappe.ui.Dialog({
			title: `Sales Target — ${frappe.utils.escape_html(u.full_name || u.user)}`,
			fields: [
				{
					fieldtype: "HTML",
					options: `<div class="ib-st-meta">
						<span class="ib-st-month">${frappe.utils.escape_html(month_label)}</span>
						${u.actual ? `<span class="ib-st-actual">Actual so far: <strong>${fmt_inr(u.actual)}</strong></span>` : ""}
					</div>`,
				},
				{
					fieldname: "target_amount",
					fieldtype: "Currency",
					label: "Target Amount",
					default: u.target || 0,
					reqd: 1,
				},
			],
			primary_action_label: u.target ? "Update" : "Set Target",
			primary_action(values) {
				frappe.call({
					method: "instabiz.overrides.sales_target.set_user_target",
					args: {
						sales_user: u.user,
						month: month_first,
						target_amount: values.target_amount,
					},
					callback(r) {
						if (r.message && r.message.status === "ok") {
							d.hide();
							frappe.show_alert({
								message: `Target set for ${u.full_name || u.user}`,
								indicator: "green",
							});
							// Patch the roster row in-place for instant feedback
							u.target = r.message.target;
							u.actual = r.message.actual;
							u.target_pct = r.message.pct;
							self._reload_roster();
						}
					},
				});
			},
		});
		d.show();
	}

	// ── Incentive Slab Management ─────────────────────────────────────────────

	_show_slab_dialog() {
		const self = this;

		const render_slabs_html = (slabs) => {
			if (!slabs.length) return `<div style="padding:20px;text-align:center;color:var(--text-muted);font-size:13px">
				No slabs configured. Add tiers below.
			</div>`;
			return `<table class="table table-bordered" style="font-size:12px;margin-bottom:12px">
				<thead>
					<tr style="background:var(--bg-color)">
						<th style="padding:7px 10px;text-align:left;border-bottom:1px solid var(--border-color);font-size:11px;color:var(--text-muted)">Label</th>
						<th style="padding:7px 10px;text-align:right;border-bottom:1px solid var(--border-color);font-size:11px;color:var(--text-muted)">From %</th>
						<th style="padding:7px 10px;text-align:right;border-bottom:1px solid var(--border-color);font-size:11px;color:var(--text-muted)">To % (0=no cap)</th>
						<th style="padding:7px 10px;text-align:right;border-bottom:1px solid var(--border-color);font-size:11px;color:var(--text-muted)">Commission %</th>
						<th style="padding:7px 10px;text-align:center;border-bottom:1px solid var(--border-color);font-size:11px;color:var(--text-muted)">Active</th>
						<th style="padding:7px 10px;border-bottom:1px solid var(--border-color)"></th>
					</tr>
				</thead>
				<tbody>
					${slabs.map(s => `
						<tr data-slab="${frappe.utils.escape_html(s.name)}">
							<td style="padding:7px 10px;border-bottom:1px solid var(--border-color)">${frappe.utils.escape_html(s.slab_label || "")}</td>
							<td style="padding:7px 10px;border-bottom:1px solid var(--border-color);text-align:right">${s.from_pct}%</td>
							<td style="padding:7px 10px;border-bottom:1px solid var(--border-color);text-align:right">${s.to_pct || "∞"}%</td>
							<td style="padding:7px 10px;border-bottom:1px solid var(--border-color);text-align:right;font-weight:600;color:var(--ib-primary)">${s.commission_pct}%</td>
							<td style="padding:7px 10px;border-bottom:1px solid var(--border-color);text-align:center">
								${s.is_active ? `<span style="color:#16a34a">✓</span>` : `<span style="color:var(--text-muted)">—</span>`}
							</td>
							<td style="padding:7px 10px;border-bottom:1px solid var(--border-color);text-align:center">
								<button class="ib-slab-edit-btn btn btn-xs btn-default" data-slab="${frappe.utils.escape_html(s.name)}">Edit</button>
								<button class="ib-slab-del-btn btn btn-xs btn-danger" data-slab="${frappe.utils.escape_html(s.name)}" style="margin-left:4px">✕</button>
							</td>
						</tr>
					`).join("")}
				</tbody>
			</table>`;
		};

		const d = new frappe.ui.Dialog({
			title: "Incentive Slabs",
			size: "large",
			fields: [
				{
					fieldtype: "HTML",
					fieldname: "slab_list_html",
					options: `<div id="ib-slab-list"><div style="padding:20px;text-align:center">Loading…</div></div>`,
				},
				{ fieldtype: "Section Break", label: "Add / Edit Slab" },
				{
					fieldname: "slab_name_hidden",
					fieldtype: "Data",
					hidden: 1,
				},
				{
					fieldname: "slab_label",
					fieldtype: "Data",
					label: "Tier Label",
					placeholder: "e.g. Bronze, Silver, Gold, Platinum",
				},
				{ fieldtype: "Column Break" },
				{
					fieldname: "from_pct",
					fieldtype: "Float",
					label: "From % of Target",
					default: 0,
				},
				{ fieldtype: "Column Break" },
				{
					fieldname: "to_pct",
					fieldtype: "Float",
					label: "To % (0 = No Cap)",
					default: 100,
				},
				{ fieldtype: "Column Break" },
				{
					fieldname: "commission_pct",
					fieldtype: "Float",
					label: "Commission %",
					default: 5,
				},
				{ fieldtype: "Column Break" },
				{
					fieldname: "is_active",
					fieldtype: "Check",
					label: "Active",
					default: 1,
				},
			],
			primary_action_label: "Save Slab",
			primary_action(values) {
				frappe.call({
					method: "instabiz.overrides.sales_target.save_incentive_slab",
					args: {
						name: values.slab_name_hidden || null,
						slab_label: values.slab_label,
						from_pct: values.from_pct || 0,
						to_pct: values.to_pct || 0,
						commission_pct: values.commission_pct || 0,
						is_active: values.is_active ? 1 : 0,
					},
					callback(r) {
						if (r.message && r.message.status === "ok") {
							frappe.show_alert({ message: "Slab saved", indicator: "green" });
							d.set_value("slab_name_hidden", "");
							d.set_value("slab_label", "");
							d.set_value("from_pct", 0);
							d.set_value("to_pct", 100);
							d.set_value("commission_pct", 5);
							d.set_value("is_active", 1);
							reload_list();
						}
					},
				});
			},
		});

		const reload_list = () => {
			frappe.call({
				method: "instabiz.overrides.sales_target.get_incentive_slabs",
				callback(r) {
					const slabs = r.message || [];
					d.$wrapper.find("#ib-slab-list").html(render_slabs_html(slabs));
					// Edit button
					d.$wrapper.on("click", ".ib-slab-edit-btn", function() {
						const slab_name = $(this).data("slab");
						const slab = slabs.find(s => s.name === slab_name);
						if (!slab) return;
						d.set_value("slab_name_hidden", slab.name);
						d.set_value("slab_label", slab.slab_label);
						d.set_value("from_pct", slab.from_pct);
						d.set_value("to_pct", slab.to_pct);
						d.set_value("commission_pct", slab.commission_pct);
						d.set_value("is_active", slab.is_active);
					});
					// Delete button
					d.$wrapper.on("click", ".ib-slab-del-btn", function() {
						const slab_name = $(this).data("slab");
						frappe.confirm(
							`Delete slab "${slab_name}"?`,
							() => {
								frappe.call({
									method: "instabiz.overrides.sales_target.delete_incentive_slab",
									args: { name: slab_name },
									callback() { reload_list(); },
								});
							}
						);
					});
				},
			});
		};

		d.show();
		reload_list();
	}

	_show_team_manage_modal(team_name) {
		const self = this;
		const d = new frappe.ui.Dialog({
			title: `Manage Team: ${frappe.utils.escape_html(team_name)}`,
			size: "large",
			fields: [{
				fieldtype: "HTML",
				fieldname: "body",
				options: `<div class="ib-tm-body"><div class="ib-tm-loading">Loading…</div></div>`,
			}],
			primary_action_label: "Close",
			primary_action() { d.hide(); },
		});
		d.show();
		const $body = d.get_field("body").$wrapper.find(".ib-tm-body");
		self._load_team_modal(d, $body, team_name);
	}

	// Every mutation inside the Manage Team dialog (member/territory add or
	// remove, team leader change) needs BOTH: the dialog's own body re-drawn
	// (so the person editing sees their change), AND the Team Overview
	// section behind the dialog re-fetched + re-rendered (so the team card's
	// member avatars, territory badges, and TL crown all reflect it too,
	// without needing a full page reload). The dialog reload alone was the
	// only thing every mutation guaranteed before this fix — Team Overview
	// only got refreshed by the member handlers, never the territory ones,
	// which read as "the change didn't save" even though it always had.
	_refresh_roster_and_reload_modal(d, $body, team_name) {
		const self = this;
		frappe.call({
			method: "instabiz.overrides.customer_assignment.get_admin_overview",
			args: { date: self._date, territory: self._territory },
			callback(rr) {
				if (rr.message) self._render_roster(rr.message.roster, rr.message.team_territories || {});
				self._load_team_modal(d, $body, team_name);
			},
			error(r) { self._load_team_modal(d, $body, team_name); self._show_team_modal_error(r); },
		});
	}

	// Every save/remove action in this dialog previously reverted its button
	// silently on failure (frappe.throw'd errors — e.g. "already a member of
	// another team" race, or a permission error) with no visible feedback at
	// all, which is exactly what "the feature doesn't work" looks like from
	// the outside even when the only real problem was a transient/expected
	// rejection. Surface it.
	_show_team_modal_error(r) {
		const msg = (r && r._server_messages && (() => {
			try { return JSON.parse(JSON.parse(r._server_messages)[0]).message; } catch (e) { return null; }
		})()) || (r && r.message) || __("Something went wrong. Please try again.");
		frappe.msgprint({ title: __("Couldn't save"), message: msg, indicator: "red" });
	}

	_load_team_modal(d, $body, team_name) {
		const self = this;
		$body.html('<div class="ib-tm-loading">Loading…</div>');

		const render_with_team = (team) => {
			if (d._all_territories !== undefined) {
				self._render_team_modal(d, $body, team_name, team, d._all_territories);
				return;
			}
			frappe.call({
				method: "frappe.client.get_list",
				args: { doctype: "Territory", fields: ["name"], limit: 500 },
				callback(r) {
					d._all_territories = (r.message || []).map(t => t.name).sort();
					self._render_team_modal(d, $body, team_name, team, d._all_territories);
				},
			});
		};

		frappe.call({
			method: "instabiz.overrides.customer_assignment.get_team_details",
			args: { team_name },
			callback(r) {
				render_with_team(r.message || { members: [], territories: [] });
			},
		});
	}

	_render_team_modal(d, $body, team_name, team, all_territories) {
		const self = this;
		const existing_users = new Set(team.members.map(m => m.user));
		const existing_territories = new Set(team.territories.map(t => t.territory));

		// Build user→team map from last roster (all sales users' team assignments)
		const user_team_map = {};
		(self._last_roster || []).forEach(u => { if (u.team) user_team_map[u.user] = u.team; });

		// Build territory → team map from _last_team_territories (team → [territories])
		const territory_team_map = {};
		Object.entries(self._last_team_territories || {}).forEach(([team, territories]) => {
			territories.forEach(t => { if (team !== team_name) territory_team_map[t] = team; });
		});

		const available_users = (self._dropdown_users_cache || []).filter(u => !existing_users.has(u.name));
		const available_territories = all_territories.filter(t => !existing_territories.has(t));

		// Existing member rows (read-only + remove)
		const member_rows = team.members.length
			? team.members.map(m => {
				const color = self._avatar_color(m.user, user_team_map[m.user] || team_name);
				const initials = (m.full_name || m.user).split(" ").map(w => w[0]).slice(0, 2).join("").toUpperCase();
				return `
				<div class="ib-tm-row">
					<div class="ib-tm-row-av" style="background:${color}">${initials}</div>
					<div class="ib-tm-row-info">
						<span class="ib-tm-row-name">${frappe.utils.escape_html(m.full_name || m.user)}</span>
						<span class="ib-tm-row-sub">${frappe.utils.escape_html(m.user)}</span>
					</div>
					<button class="ib-tm-remove-btn" data-user="${frappe.utils.escape_html(m.user)}">Remove</button>
				</div>`;
			}).join("")
			: `<div class="ib-tm-empty">No members yet</div>`;

		// Available user picker rows with team badge
		const picker_rows = available_users.map(u => {
			const other_team = user_team_map[u.name];
			const color = self._avatar_color(u.name, other_team || "");
			const initials = (u.full_name || u.name).split(" ").map(w => w[0]).slice(0, 2).join("").toUpperCase();
			const team_badge = other_team
				? `<span class="ib-tm-team-badge" style="--badge-color:${color}">${frappe.utils.escape_html(other_team)}</span>`
				: `<span class="ib-tm-team-badge ib-tm-team-badge--none">No team</span>`;
			return `
			<div class="ib-tm-picker-row" data-user="${frappe.utils.escape_html(u.name)}" data-search="${frappe.utils.escape_html((u.full_name || "") + " " + u.name).toLowerCase()}"${other_team ? ` data-other-team="${frappe.utils.escape_html(other_team)}"` : ""}>
				<div class="ib-tm-row-av" style="background:${color}">${initials}</div>
				<div class="ib-tm-row-info">
					<span class="ib-tm-row-name">${frappe.utils.escape_html(u.full_name || u.name)}</span>
					<span class="ib-tm-row-sub">${frappe.utils.escape_html(u.name)} ${team_badge}</span>
				</div>
				<button class="ib-tm-picker-add-btn${other_team ? " ib-tm-picker-add-btn--blocked" : ""}" data-user="${frappe.utils.escape_html(u.name)}"${other_team ? ' title="Already in another team"' : ""}>+ Add</button>
			</div>`;
		}).join("") || `<div class="ib-tm-empty">All users already in this team</div>`;

		const PIN_SVG = `<svg width="13" height="13" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M8 1C5.24 1 3 3.24 3 6c0 3.75 5 9 5 9s5-5.25 5-9c0-2.76-2.24-5-5-5zm0 6.5A1.5 1.5 0 1 1 8 4a1.5 1.5 0 0 1 0 3.5z" fill="currentColor"/></svg>`;

		// Territory rows — assigned (with Remove)
		const territory_rows = team.territories.length
			? team.territories.map(t => `
				<div class="ib-tm-row">
					<div class="ib-tm-territory-icon">${PIN_SVG}</div>
					<div class="ib-tm-row-info">
						<span class="ib-tm-row-name">${frappe.utils.escape_html(t.territory)}</span>
					</div>
					<button class="ib-tm-remove-btn" data-territory="${frappe.utils.escape_html(t.territory)}">Remove</button>
				</div>`).join("")
			: `<div class="ib-tm-empty">No territories assigned yet</div>`;

		// Territory picker rows — available to add (with + Add), filtered by search
		const territory_picker_rows = available_territories.map(t => {
			const other_team_t = territory_team_map[t] || null;
			return `
			<div class="ib-tm-picker-row" data-territory="${frappe.utils.escape_html(t)}" data-tsearch="${frappe.utils.escape_html(t).toLowerCase()}"${other_team_t ? ` data-other-team="${frappe.utils.escape_html(other_team_t)}"` : ""}>
				<div class="ib-tm-territory-icon">${PIN_SVG}</div>
				<div class="ib-tm-row-info">
					<span class="ib-tm-row-name">${frappe.utils.escape_html(t)}</span>
					${other_team_t ? `<span class="ib-tm-row-sub"><span class="ib-tm-team-badge" style="--badge-color:${self._avatar_color("", other_team_t)}">${frappe.utils.escape_html(other_team_t)}</span></span>` : ""}
				</div>
				<button class="ib-tm-picker-add-btn ib-tm-territory-picker-add-btn${other_team_t ? " ib-tm-picker-add-btn--blocked" : ""}" data-territory="${frappe.utils.escape_html(t)}"${other_team_t ? ` title="Already in ${frappe.utils.escape_html(other_team_t)}"` : ""}>+ Add</button>
			</div>`;
		}).join("") || `<div class="ib-tm-empty">All territories already assigned</div>`;

		// Team Leader — must be a current member (backend enforces this too);
		// options list is built fresh from team.members every render, so a
		// member removed a moment ago can't linger as a selectable leader.
		const TL_SVG = `<svg width="15" height="15" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><polygon points="12,1 13.6,6.2 17.5,2.5 16.2,7.8 21.5,6.5 17.8,10.5 23,12 17.8,13.6 21.5,17.5 16.2,16.2 17.5,21.5 13.6,17.8 12,23 10.4,17.8 6.5,21.5 7.8,16.2 2.5,17.5 6.2,13.6 1,12 6.2,10.4 2.5,6.5 7.8,7.8 6.5,2.5 10.4,6.2" fill="#f59e0b"/></svg>`;
		const leader_options = [`<option value="">— No leader —</option>`]
			.concat(team.members.map(m =>
				`<option value="${frappe.utils.escape_html(m.user)}"${m.user === team.team_leader ? " selected" : ""}>${frappe.utils.escape_html(m.full_name || m.user)}</option>`
			)).join("");
		const leader_html = `
			<div class="ib-tm-leader-row">
				<div class="ib-tm-leader-label">${TL_SVG} <span>Team Leader</span></div>
				<select class="ib-tm-leader-select form-control" id="ib-tm-leader-select" ${team.members.length ? "" : "disabled"}>
					${leader_options}
				</select>
				<button class="btn btn-default btn-xs" id="ib-tm-leader-save" disabled>Save</button>
				${!team.members.length ? `<span class="ib-tm-leader-hint">Add a member first</span>` : ""}
			</div>`;

		$body.html(`
			${leader_html}
			<div class="ib-tm-cols">

				<!-- ── Members column ── -->
				<div class="ib-tm-col">
					<div class="ib-tm-section">
						<div class="ib-tm-section-label">Add Member</div>
						<div class="ib-tm-picker-head">
							<input class="ib-tm-picker-search form-control" id="ib-tm-member-search" placeholder="Search users…" autocomplete="off">
						</div>
						<div class="ib-tm-picker-list" id="ib-tm-picker-list">${picker_rows}</div>
						<div class="ib-tm-section-label ib-tm-section-label--sub">In Team <span class="ib-tm-count">${team.members.length}</span></div>
						<div class="ib-tm-list">${member_rows}</div>
					</div>
				</div>

				<!-- ── States column ── -->
				<div class="ib-tm-col">
					<div class="ib-tm-section">
						<div class="ib-tm-section-label">Add State</div>
						<div class="ib-tm-picker-head">
							<input class="ib-tm-picker-search form-control" id="ib-tm-territory-search" placeholder="Search states…" autocomplete="off">
						</div>
						<div class="ib-tm-picker-list" id="ib-tm-territory-picker-list">${territory_picker_rows}</div>
						<div class="ib-tm-section-label ib-tm-section-label--sub">Assigned <span class="ib-tm-count">${team.territories.length}</span></div>
						<div class="ib-tm-list">${territory_rows}</div>
					</div>
				</div>

			</div>
		`);

		// Team Leader — enable Save only once the picker actually differs
		// from what's saved, so a no-op click can't fire a pointless request.
		const $leaderSelect = $body.find("#ib-tm-leader-select");
		const $leaderSave = $body.find("#ib-tm-leader-save");
		$leaderSelect.on("change", function() {
			$leaderSave.prop("disabled", this.value === (team.team_leader || ""));
		});
		$leaderSave.on("click", function() {
			const team_leader = $leaderSelect.val() || null;
			const $btn = $(this).prop("disabled", true).text("Saving…");
			frappe.call({
				method: "instabiz.overrides.customer_assignment.update_team_leader",
				args: { team_name, team_leader },
				callback(r) {
					if (r.message && r.message.status === "ok") {
						frappe.show_alert({
							message: team_leader ? `Team leader set` : `Team leader cleared`,
							indicator: "green",
						});
						self._refresh_roster_and_reload_modal(d, $body, team_name);
					} else {
						$btn.prop("disabled", false).text("Save");
					}
				},
				error(r) { $btn.prop("disabled", false).text("Save"); self._show_team_modal_error(r); },
			});
		});

		// Member search filter (multi-token: every word must match)
		$body.find("#ib-tm-member-search").on("input", function() {
			const q = this.value;
			$body.find("#ib-tm-picker-list .ib-tm-picker-row").each(function() {
				const hay = $(this).data("search") || "";
				$(this).toggle(window.ib_multi_token_match({ hay }, ["hay"], q));
			});
		});

		// Territory search filter (multi-token: every word must match)
		$body.find("#ib-tm-territory-search").on("input", function() {
			const q = this.value;
			$body.find("#ib-tm-territory-picker-list .ib-tm-picker-row").each(function() {
				const hay = $(this).data("tsearch") || "";
				$(this).toggle(window.ib_multi_token_match({ hay }, ["hay"], q));
			});
		});

		// Per-row add member — exclude territory add buttons which share the base class
		$body.find(".ib-tm-picker-row .ib-tm-picker-add-btn:not(.ib-tm-territory-picker-add-btn)").on("click", function() {
			const other_team = $(this).closest(".ib-tm-picker-row").data("other-team");
			if (other_team) {
				frappe.show_alert({
					message: __("User is already in team \"{0}\". Remove them from that team first.", [other_team]),
					indicator: "red",
				});
				return;
			}
			const user = $(this).data("user");
			const $btn = $(this).prop("disabled", true).text("…");
			frappe.call({
				method: "instabiz.overrides.customer_assignment.add_team_member",
				args: { team_name, user },
				freeze: true,
				freeze_message: "Saving…",
				callback(r) {
					if (r.message && r.message.status === "ok") {
						frappe.show_alert({ message: `Added to ${team_name}`, indicator: "green" });
						self._refresh_roster_and_reload_modal(d, $body, team_name);
					} else {
						$btn.prop("disabled", false).text("+ Add");
					}
				},
				error(r) { $btn.prop("disabled", false).text("+ Add"); self._show_team_modal_error(r); },
			});
		});

		// Remove member
		$body.find(".ib-tm-remove-btn[data-user]").on("click", function() {
			const user = $(this).data("user");
			const $btn = $(this).prop("disabled", true).text("…");
			frappe.call({
				method: "instabiz.overrides.customer_assignment.remove_team_member",
				args: { team_name, user },
				freeze: true,
				freeze_message: "Saving…",
				callback(r) {
					if (r.message && r.message.status === "ok") {
						frappe.show_alert({ message: `Removed from ${team_name}`, indicator: "orange" });
						self._refresh_roster_and_reload_modal(d, $body, team_name);
					} else {
						$btn.prop("disabled", false).text("Remove");
					}
				},
				error(r) { $btn.prop("disabled", false).text("Remove"); self._show_team_modal_error(r); },
			});
		});

		// Remove territory
		$body.find(".ib-tm-remove-btn[data-territory]").on("click", function() {
			const territory = $(this).data("territory");
			const $btn = $(this).prop("disabled", true).text("…");
			frappe.call({
				method: "instabiz.overrides.customer_assignment.remove_team_territory",
				args: { team_name, territory },
				callback(r) {
					if (r.message && r.message.status === "ok") {
						frappe.show_alert({ message: `${territory} removed`, indicator: "orange" });
						// Was only reloading the dialog itself — the Team Overview
						// section behind it (territory badges on the team card)
						// kept showing the pre-change state until a full page
						// reload. Member add/remove already refreshed both; this
						// was the one real gap causing "looks reverted after
						// refresh" (it wasn't actually reverted — the roster
						// view just never re-rendered with the new data).
						self._refresh_roster_and_reload_modal(d, $body, team_name);
					} else {
						$btn.prop("disabled", false).text("Remove");
					}
				},
				error(r) { $btn.prop("disabled", false).text("Remove"); self._show_team_modal_error(r); },
			});
		});

		// Add territory (per-row)
		$body.find(".ib-tm-territory-picker-add-btn").on("click", function() {
			const other_team_t = $(this).closest(".ib-tm-picker-row").data("other-team");
			if (other_team_t) {
				frappe.show_alert({
					message: __("State is already assigned to team \"{0}\". Remove it from that team first.", [other_team_t]),
					indicator: "red",
				});
				return;
			}
			const territory = $(this).data("territory");
			const $btn = $(this).prop("disabled", true).text("…");
			frappe.call({
				method: "instabiz.overrides.customer_assignment.add_team_territory",
				args: { team_name, territory },
				callback(r) {
					if (r.message && r.message.status === "ok") {
						frappe.show_alert({ message: `${territory} added`, indicator: "green" });
						self._refresh_roster_and_reload_modal(d, $body, team_name);
					} else {
						$btn.prop("disabled", false).text("+ Add");
					}
				},
				error(r) { $btn.prop("disabled", false).text("+ Add"); self._show_team_modal_error(r); },
			});
		});
	}

	// ── View As ──────────────────────────────────────────────────────────────

	_view_as(user, full_name, user_data = null) {
		this._view_as_user = user;
		this._view_as_user_data = user_data;
		this._va_undo_timer = null;
		$("#ib-aa-view-as-label").text(`Viewing board as ${full_name || user}`);
		$("#ib-aa-view-as-bar").show();
		this._reload_va_board();

		// Scroll to the board section smoothly
		setTimeout(() => {
			const el = document.getElementById("ib-aa-board-wrap");
			if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
		}, 100);
	}

	_reload_va_board() {
		const self = this;
		const user = this._view_as_user;
		if (!user) return;

		const $wrap = $("#ib-aa-board-wrap");
		$wrap.html(`<div class="ib-va-loading">Loading…</div>`);

		frappe.call({
			method: "instabiz.overrides.customer_assignment.get_admin_overview",
			args: { date: this._date, view_as_user: user },
			callback(r) {
				if (!r.message || !r.message.board) {
					$wrap.html(`<div class="ib-va-loading">Failed to load board. <a href="#" id="ib-va-retry-link">Retry</a></div>`);
					$("#ib-va-retry-link").on("click", (e) => { e.preventDefault(); self._reload_va_board(); });
					return;
				}
				self._render_board_view(r.message.board);
			},
			error() {
				$wrap.html(`<div class="ib-va-loading">Error loading board. <a href="#" id="ib-va-retry-link">Retry</a></div>`);
				$("#ib-va-retry-link").on("click", (e) => { e.preventDefault(); self._reload_va_board(); });
			},
		});
	}

	// Render a va column and bind multi-token local search to it.
	// card_fn(row) → jQuery element. empty_msg shown when no data (not when search has no results).
	_va_render_col(col, rows, card_fn, empty_msg, total) {
		const $cards = $(`#ib-va-${col}-cards`).empty();
		$(`#ib-va-${col}-search`).val("");
		let real_total = total !== undefined ? total : rows.length;
		$(`#ib-va-${col}-count`).text(real_total > rows.length ? `${rows.length} / ${real_total}` : rows.length);

		const render = (filtered, is_search) => {
			$cards.empty();
			$(`#ib-va-${col}-count`).text(
				is_search ? `${filtered.length}/${rows.length}`
					: (real_total > rows.length ? `${rows.length} / ${real_total}` : rows.length)
			);
			if (!filtered.length) {
				$cards.html(`<div class="ib-va-empty">${is_search ? "No results" : empty_msg}</div>`);
			} else {
				filtered.forEach(r => $cards.append(card_fn(r)));
			}
			// "My Accounts" pages past its initial 50 instead of hard-capping —
			// only relevant on the unfiltered view (search already narrows client-side).
			if (col === "dormant" && !is_search && real_total > rows.length) {
				appendLoadMore();
			}
		};

		const appendLoadMore = () => {
			const $more = $(`<div class="ib-va-more" style="text-align:center;padding:6px;font-size:11px;color:var(--ib-primary,#d97757);cursor:pointer;border:1px dashed var(--border-color);border-radius:6px">Load more (${real_total - rows.length})</div>`);
			$more.on("click", () => {
				$more.text("Loading…");
				frappe.call({
					method: "instabiz.overrides.customer_assignment.load_more_my_accounts_admin",
					args: { user: this._view_as_user, offset: rows.length, limit: 50 },
					callback: (r) => {
						const { rows: more_rows, total: new_total } = r.message || { rows: [], total: real_total };
						$more.remove();
						more_rows.forEach(row => { rows.push(row); $cards.append(card_fn(row)); });
						real_total = new_total;
						$(`#ib-va-${col}-count`).text(real_total > rows.length ? `${rows.length} / ${real_total}` : rows.length);
						if (real_total > rows.length) appendLoadMore();
					},
				});
			});
			$cards.append($more);
		};

		render(rows, false);

		let _t;
		$(`#ib-va-${col}-search`).off("input").on("input", function () {
			const q = $(this).val().trim();
			clearTimeout(_t);
			if (!q) { render(rows, false); return; }
			_t = setTimeout(() => {
				const tokens = q.toLowerCase().split(/\s+/).filter(Boolean);
				const filtered = rows.filter(r => {
					const hay = [r.customer_name, r.customer, r.territory].join(" ").toLowerCase();
					return tokens.every(t => hay.includes(t));
				});
				render(filtered, true);
			}, 200);
		});
	}

	_va_tmrw_card(r) {
		const last = r.last_so_date ? frappe.datetime.str_to_user(r.last_so_date) : "No orders";
		const $card = $(`
			<div class="ib-va-card ib-va-card--tmrw">
				<div class="ib-va-card-name">${frappe.utils.escape_html(r.customer_name || r.customer)}</div>
				<div class="ib-va-card-meta">${frappe.utils.escape_html(r.territory || "")}</div>
				<div class="ib-va-card-last">${last}</div>
			</div>
		`);
		$card.find(".ib-va-card-name").addClass("ib-va-card-name--link").on("click", (e) => {
			e.stopPropagation();
			frappe.set_route("Form", "Customer", r.customer);
		});
		return $card;
	}

	_render_board_view(data) {
		const self = this;
		const user = this._view_as_user;
		const $wrap = $("#ib-aa-board-wrap");
		const ud = this._view_as_user_data;
		const fmt_inr = v => v ? "₹" + Number(v).toLocaleString("en-IN", { maximumFractionDigits: 0 }) : "—";
		const target_strip = ud && ud.target ? (() => {
			const tpct = Math.min(ud.target_pct || 0, 100);
			const bar_color = tpct >= 100 ? "#22c55e" : tpct >= 60 ? "var(--ib-primary)" : "#f59e0b";
			return `<div class="ib-va-target-strip">
				<span class="ib-va-ts-label">Sales Target</span>
				<div class="ib-va-ts-track">
					<div class="ib-va-ts-fill" style="width:${tpct}%;background:${bar_color}"></div>
				</div>
				<span class="ib-va-ts-amt">${fmt_inr(ud.actual)} <span class="ib-va-ts-sep">/</span> ${fmt_inr(ud.target)}</span>
				<span class="ib-va-ts-pct" style="color:${bar_color}">${ud.target_pct || 0}%</span>
			</div>`;
		})() : "";

		$wrap.html(`
			<div class="ib-va-board">
				${target_strip}
				<div class="ib-va-columns">
					<div class="ib-va-col">
						<div class="ib-va-col-header">
							${IB_ICONS.svg("user", 13)}<span class="ib-va-col-title">My Accounts</span>
							<span class="ib-va-badge" id="ib-va-dormant-count">0</span>
						</div>
						<input class="ib-va-col-search form-control" id="ib-va-dormant-search" placeholder="Search…" autocomplete="off">
						<div class="ib-va-cards" id="ib-va-dormant-cards"></div>
					</div>
					<div class="ib-va-col">
						<div class="ib-va-col-header">
							${IB_ICONS.svg("map_pin", 13)}<span class="ib-va-col-title">State</span>
							<span class="ib-va-badge" id="ib-va-regular-count">0</span>
						</div>
						<input class="ib-va-col-search form-control" id="ib-va-regular-search" placeholder="Search…" autocomplete="off">
						<div class="ib-va-cards" id="ib-va-regular-cards"></div>
					</div>
					<div class="ib-va-col ib-va-col--today">
						<div class="ib-va-col-header">
							${IB_ICONS.svg("calendar", 13)}<span class="ib-va-col-title">Today</span>
							<span class="ib-va-col-date">${frappe.datetime.str_to_user(data.date)}</span>
							<span class="ib-va-badge ib-va-badge--today" id="ib-va-today-count">0</span>
							${this._is_manager ? `<button class="ib-va-remove-all-btn" id="ib-va-remove-all" title="Remove all pending">${IB_ICONS.svg("trash", 11)}</button>` : ""}
						</div>
						<input class="ib-va-col-search form-control" id="ib-va-today-search" placeholder="Search…" autocomplete="off">
						<div class="ib-va-cards" id="ib-va-today-cards"></div>
					</div>
					<div class="ib-va-col ib-va-col--tomorrow">
						<div class="ib-va-col-header">
							${IB_ICONS.svg("sunrise", 13)}<span class="ib-va-col-title">Tomorrow</span>
							<span class="ib-va-col-date">${frappe.datetime.str_to_user(data.tomorrow_date)}</span>
							<span class="ib-va-badge ib-va-badge--tmrw" id="ib-va-tomorrow-count">0</span>
						</div>
						<input class="ib-va-col-search form-control" id="ib-va-tomorrow-search" placeholder="Search…" autocomplete="off">
						<div class="ib-va-cards" id="ib-va-tomorrow-cards"></div>
					</div>
				</div>
				<div id="ib-va-undo-toast" class="ib-va-undo-toast" style="display:none;">
					<div class="ib-va-undo-row">
						<span id="ib-va-undo-msg"></span>
						<button id="ib-va-undo-btn" class="ib-va-undo-btn">Undo</button>
					</div>
					<div class="ib-va-undo-bar"><div id="ib-va-undo-fill" class="ib-va-undo-fill"></div></div>
				</div>
			</div>
		`);

		this._va_render_col("dormant", data.dormant || [], r => self._va_pool_card(r, user), "Empty", data.dormant_total);
		this._va_render_col("regular", data.regular || [], r => self._va_pool_card(r, user), "Empty");
		this._va_render_col("today",   data.today   || [], r => self._va_today_card(r),       "No assignments");
		this._va_render_col("tomorrow",data.tomorrow|| [], r => self._va_tmrw_card(r),        "Scheduler runs at midnight");

		// Remove-all button for today pending
		const pending_count = (data.today || []).filter(r => r.status === "Pending").length;
		const $removeAll = $("#ib-va-remove-all");
		if (!pending_count) {
			$removeAll.hide();
		} else {
			$removeAll.show().off("click").on("click", () => {
				frappe.confirm(
					`Remove all ${pending_count} pending assignment${pending_count > 1 ? "s" : ""} for ${self._view_as_user}?`,
					() => {
						frappe.call({
							method: "instabiz.overrides.customer_assignment.remove_all_pending",
							args: { user: self._view_as_user, date: self._date },
							callback(r) {
								if (r.message != null) {
									frappe.show_alert({
										message: `${r.message.removed} assignment${r.message.removed !== 1 ? "s" : ""} removed`,
										indicator: "orange",
									});
									self._reload_va_board();
									self._reload_roster();
								}
							},
						});
					}
				);
			});
		}
	}

	_va_pool_card(r, target_user) {
		const self = this;
		const last = r.last_so_date ? frappe.datetime.str_to_user(r.last_so_date) : "No orders";
		const $card = $(`
			<div class="ib-va-card ib-va-card--pool">
				<div class="ib-va-card-name">${frappe.utils.escape_html(r.customer_name || r.customer)}</div>
				<div class="ib-va-card-code">${frappe.utils.escape_html(r.customer)}</div>
				<div class="ib-va-card-meta">${frappe.utils.escape_html(r.territory || "")}</div>
				<div class="ib-va-card-last">${last}</div>
				${this._is_manager ? `<div class="ib-va-card-btns">
					<button class="ib-va-add-btn" data-customer="${frappe.utils.escape_html(r.customer)}">${IB_ICONS.svg("plus", 11)} Today</button>
					<button class="ib-va-tmrw-btn" data-customer="${frappe.utils.escape_html(r.customer)}">${IB_ICONS.svg("plus", 11)} Tomorrow</button>
				</div>` : ""}
			</div>
		`);
		// Deep-link: was a dead end before — no navigation existed from this
		// board's cards at all, only in-place action buttons.
		$card.find(".ib-va-card-name, .ib-va-card-code").addClass("ib-va-card-name--link").on("click", (e) => {
			e.stopPropagation();
			frappe.set_route("Form", "Customer", r.customer);
		});
		$card.find(".ib-va-add-btn").on("click", function () {
			const customer = $(this).data("customer");
			const $btn = $(this);
			$btn.prop("disabled", true).text("Adding…");
			frappe.call({
				method: "instabiz.overrides.customer_assignment.add_customer_to_today",
				args: { customer, date: self._date, target_user },
				callback(r) {
					if (r.message && r.message.status === "ok") {
						self._va_show_undo(customer, r.message.assignment);
						self._reload_va_board();
					} else {
						$btn.prop("disabled", false).text("Today");
					}
				},
				error() { $btn.prop("disabled", false).text("Today"); },
			});
		});
		$card.find(".ib-va-tmrw-btn").on("click", function () {
			const customer = $(this).data("customer");
			const $btn = $(this);
			const tomorrow = self._next_working_day(self._date);
			$btn.prop("disabled", true).text("Adding…");
			frappe.call({
				method: "instabiz.overrides.customer_assignment.add_customer_to_today",
				args: { customer, date: tomorrow, target_user },
				callback(r) {
					if (r.message && r.message.status === "ok") {
						frappe.show_alert({ message: `${customer} added to Tomorrow`, indicator: "blue" });
						self._reload_va_board();
					} else {
						$btn.prop("disabled", false).text("Tomorrow");
					}
				},
				error() { $btn.prop("disabled", false).text("Tomorrow"); },
			});
		});
		return $card;
	}

	_va_today_card(r) {
		const self = this;
		const is_pending = r.status === "Pending";
		const status_cls = {
			"Pending": "pending", "Contacted": "contacted",
			"Order Placed": "ordered", "Skipped": "skipped",
		}[r.status] || "";
		const last = r.last_so_date ? frappe.datetime.str_to_user(r.last_so_date) : "No orders";

		const $card = $(`
			<div class="ib-va-card ib-va-card--today ${!is_pending ? "ib-va-card--done" : ""}">
				<div class="ib-va-card-top">
					<div class="ib-va-card-name">${frappe.utils.escape_html(r.customer_name || r.customer)}</div>
					<span class="ib-va-status ib-va-status--${status_cls}">${r.status}</span>
				</div>
				<div class="ib-va-card-meta">${frappe.utils.escape_html(r.territory || "")}</div>
				<div class="ib-va-card-last">${last}</div>
				${is_pending && this._is_manager ? `<button class="ib-va-remove-btn" data-id="${frappe.utils.escape_html(r.name)}">${IB_ICONS.svg("trash", 11)} Remove</button>` : ""}
			</div>
		`);
		$card.find(".ib-va-card-name").addClass("ib-va-card-name--link").on("click", (e) => {
			e.stopPropagation();
			frappe.set_route("Form", "Customer", r.customer);
		});

		if (is_pending) {
			$card.find(".ib-va-remove-btn").on("click", function () {
				const id = $(this).data("id");
				frappe.call({
					method: "instabiz.overrides.customer_assignment.remove_assignment",
					args: { assignment_id: id, force: 1 },
					callback(res) {
						if (res.message && res.message.status === "ok") {
							frappe.show_alert({ message: "Assignment removed", indicator: "orange" });
							self._reload_va_board();
							self._reload_roster();
						}
					},
				});
			});
		}
		return $card;
	}

	_va_show_undo(customer, assignment_id) {
		const self = this;
		if (this._va_undo_timer) {
			clearInterval(this._va_undo_timer);
			this._va_undo_timer = null;
		}
		const $toast = $("#ib-va-undo-toast");
		const $fill  = $("#ib-va-undo-fill");
		const $btn   = $("#ib-va-undo-btn");

		$("#ib-va-undo-msg").text(`${customer} added to Today`);
		$fill.css({ transition: "none", width: "100%" });
		$toast.show();

		requestAnimationFrame(() => {
			$fill.css({ transition: "width 5s linear", width: "0%" });
		});

		let elapsed = 0;
		this._va_undo_timer = setInterval(() => {
			elapsed += 100;
			if (elapsed >= 5000) {
				clearInterval(self._va_undo_timer);
				self._va_undo_timer = null;
				$toast.hide();
			}
		}, 100);

		$btn.off("click").on("click", () => {
			clearInterval(self._va_undo_timer);
			self._va_undo_timer = null;
			$toast.hide();
			frappe.call({
				method: "instabiz.overrides.customer_assignment.remove_assignment",
				args: { assignment_id, force: 1 },
				callback(r) {
					if (r.message && r.message.status === "ok") {
						frappe.show_alert({ message: `${customer} removed from Today`, indicator: "orange" });
						self._reload_va_board();
					}
				},
			});
		});
	}

	_bulk_auto_assign(user, full_name) {
		frappe.call({
			method: "instabiz.overrides.customer_assignment.bulk_auto_assign",
			args: { user, date: this._date },
			callback: (r) => {
				if (r.message != null) {
					frappe.show_alert({
						message: `${r.message.created} customers assigned to ${full_name || user}`,
						indicator: r.message.created > 0 ? "green" : "orange",
					});
					this.refresh();
					if (this._view_as_user === user) this._reload_va_board();
				}
			},
		});
	}

	_transfer_assignments(from_user, from_name, pending_count) {
		const self = this;
		if (!pending_count) {
			frappe.show_alert({ message: `${from_name || from_user} has no Pending assignments to transfer`, indicator: "orange" });
			return;
		}
		const d = new frappe.ui.Dialog({
			title: `Transfer ${from_name || from_user}'s assignments`,
			fields: [
				{
					fieldname: "to_user",
					fieldtype: "Link",
					label: "Transfer to",
					options: "User",
					reqd: 1,
					get_query: () => {
						const base = { query: "frappe.core.doctype.user.user.user_query", filters: { ignore_user_type: 1 } };
						if (!this._is_manager && this._leader_team) {
							const members = (this._dropdown_users_cache || []).map(u => u.name);
							if (members.length) base.filters.name = ["in", members];
						}
						return base;
					},
				},
			],
			primary_action_label: "Transfer",
			primary_action(values) {
				if (values.to_user === from_user) {
					frappe.show_alert({ message: "Cannot transfer to the same user", indicator: "red" });
					return;
				}
				frappe.call({
					method: "instabiz.overrides.customer_assignment.transfer_assignments",
					args: { from_user, to_user: values.to_user, date: self._date },
					callback(r) {
						if (r.message != null) {
							d.hide();
							frappe.show_alert({
								message: `${r.message.transferred} assignments transferred to ${values.to_user}`,
								indicator: r.message.transferred > 0 ? "green" : "orange",
							});
							self.refresh();
							if (self._view_as_user === from_user || self._view_as_user === values.to_user) {
								self._reload_va_board();
							}
						}
					},
				});
			},
		});
		d.show();
	}

	// ── Create Team ───────────────────────────────────────────────────────────

	_show_create_team_modal() {
		frappe.new_doc("Lead Sales Team");
	}

	// ── Styles ────────────────────────────────────────────────────────────────

	_inject_styles() {
		if (document.getElementById("ib-aa-styles")) return;
		const s = document.createElement("style");
		s.id = "ib-aa-styles";
		s.textContent = `
			.ib-aa-root { display: flex; flex-direction: column; gap: 24px; padding: 20px 0 60px; }

			/* ── Section shell ── */
			.ib-aa-section {
				background: var(--card-bg);
				border: 1px solid var(--border-color);
				border-radius: 10px;
				overflow: hidden;
				box-shadow: 0 1px 4px rgba(0,0,0,0.05);
			}
			.ib-aa-section-head {
				display: flex; align-items: center; gap: 10px;
				padding: 14px 20px;
				border-bottom: 1px solid var(--border-color);
				background: var(--subtle-bg);
			}
			.ib-aa-section-title { font-weight: 700; font-size: 13px; flex: 1; letter-spacing: 0.1px; }
			.ib-aa-roster-search {
				padding: 5px 10px; border: 1px solid var(--border-color);
				border-radius: 6px; font-size: 12px;
				background: var(--card-bg); color: var(--text-color);
				width: 180px; transition: border-color 0.15s;
			}
			.ib-aa-roster-search:focus { outline: none; border-color: var(--ib-primary); box-shadow: 0 0 0 2px rgba(217,119,87,0.12); }
			.ib-aa-section-date {
				font-size: 11px; font-weight: 600;
				background: var(--ib-primary); color: #fff;
				padding: 2px 10px; border-radius: 20px;
			}
			.ib-aa-section-date--hist {
				background: #b45309;
			}
			.ib-aa-hidden-strip {
				display: flex; align-items: center; gap: 6px;
				padding: 7px 20px;
				font-size: 12px; color: var(--text-muted);
				background: var(--subtle-bg);
				border-bottom: 1px solid var(--border-color);
			}
			.ib-aa-show-all-link {
				color: var(--ib-primary); text-decoration: none; font-weight: 600;
			}
			.ib-aa-show-all-link:hover { text-decoration: underline; }
			.ib-aa-empty { color: var(--text-muted); font-size: 13px; padding: 32px; margin: 0; text-align: center; }

			/* ── Roster grouped table ── */
			.ib-aa-roster { overflow: hidden; }

			.ib-aa-roster-thead {
				display: flex; align-items: center;
				padding: 6px 20px;
				background: var(--subtle-bg);
				border-bottom: 1px solid var(--border-color);
				position: sticky; top: 0; z-index: 2;
			}
			.ib-aa-rth {
				font-size: 10px; font-weight: 700; text-transform: uppercase;
				letter-spacing: 0.5px; color: var(--text-muted);
			}
			.ib-aa-rth--name    { flex: 1; min-width: 0; }
			.ib-aa-rth--stat    { width: 72px; text-align: center; border-left: 1px solid var(--border-color); }
			.ib-aa-rth--target  { width: 220px; padding-left: 8px; border-left: 1px solid var(--border-color); }

			/* Team group */
			.ib-aa-team-group { border-bottom: 2px solid var(--border-color); }
			.ib-aa-team-group:last-child { border-bottom: none; }

			.ib-aa-team-hdr {
				display: flex; align-items: center; gap: 8px;
				padding: 7px 20px;
				background: var(--subtle-bg);
				border-bottom: 1px solid var(--border-color);
				border-left: 3px solid var(--team-color, var(--ib-primary));
				cursor: pointer; user-select: none;
			}
			.ib-aa-team-hdr:hover { filter: brightness(0.97); }
			.ib-aa-team-chevron {
				color: var(--text-muted); flex-shrink: 0;
				transition: transform 0.2s ease;
			}
			.ib-aa-team-chevron--collapsed { transform: rotate(-90deg); }
			.ib-aa-team-dot {
				width: 8px; height: 8px; border-radius: 50%;
				background: var(--team-color, var(--ib-primary));
				flex-shrink: 0;
			}
			.ib-aa-team-label { font-size: 12px; font-weight: 700; }
			.ib-aa-team-meta  { font-size: 11px; color: var(--text-muted); }
			.ib-aa-terr-chips { display: flex; align-items: center; gap: 3px; flex-wrap: wrap; }
			.ib-aa-terr-chip {
				font-size: 9px; font-weight: 700; letter-spacing: 0.3px;
				padding: 1px 5px; border-radius: 3px;
				background: color-mix(in srgb, var(--team-color) 15%, transparent);
				color: var(--team-color);
				border: 1px solid color-mix(in srgb, var(--team-color) 35%, transparent);
				white-space: nowrap;
			}
			.ib-aa-team-body--collapsed { display: none; }

			/* User row */
			.ib-aa-user-row {
				display: flex; align-items: center;
				padding: 9px 20px;
				border-bottom: 1px solid var(--border-color);
				transition: background 0.12s;
				border-left: 3px solid transparent;
			}
			.ib-aa-user-row:last-child { border-bottom: none; }
			.ib-aa-user-row:hover { background: var(--subtle-bg); border-left-color: var(--border-color); }

			/* Identity cell */
			.ib-aa-row-identity {
				flex: 1; min-width: 0;
				display: flex; align-items: center; gap: 10px;
			}
			.ib-aa-row-avatar {
				width: 30px; height: 30px; border-radius: 50%;
				color: #fff; font-size: 11px; font-weight: 700;
				display: flex; align-items: center; justify-content: center;
				flex-shrink: 0; letter-spacing: 0.3px;
			}
			.ib-aa-row-name-wrap { display: flex; align-items: center; gap: 6px; min-width: 0; }
			.ib-aa-row-name {
				font-size: 13px; font-weight: 600;
				white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
			}
			.ib-aa-no-tmrw-dot { font-size: 13px; color: #d97706; flex-shrink: 0; line-height: 1; }
			.ib-aa-tl-badge { flex-shrink: 0; display: inline-block; vertical-align: middle; }

			/* Stat cells */
			.ib-aa-row-stat {
				width: 72px; text-align: center;
				font-size: 15px; font-weight: 700;
				border-left: 1px solid var(--border-color);
			}
			.ib-aa-row-stat--done    { color: #15803d; }
			.ib-aa-row-stat--pending { color: #b45309; }
			.ib-aa-row-stat--tmrw    { color: #1d4ed8; }

			.ib-aa-row-target-wrap {
				width: 220px; flex-shrink: 0;
				display: flex; flex-direction: column; gap: 3px; padding-left: 8px;
				border-left: 1px solid var(--border-color);
				justify-content: center;
			}
			.ib-aa-row-target-text {
				display: flex; align-items: center; gap: 4px;
				font-size: 12px; font-variant-numeric: tabular-nums;
			}
			.ib-aa-target-actual { font-weight: 700; }
			.ib-aa-target-sep { color: var(--text-muted); font-size: 11px; }
			.ib-aa-target-goal { color: var(--text-muted); }
			.ib-aa-target-pct { font-size: 10px; font-weight: 700; margin-left: auto; }
			.ib-aa-incentive-chip {
				display: inline-flex; align-items: center; gap: 3px;
				background: #fef3c7; color: #92400e;
				border: 1px solid #fde68a; border-radius: 10px;
				font-size: 10px; font-weight: 700;
				padding: 1px 6px; margin-left: 6px;
			}
			.ib-aa-target-bar-track {
				height: 4px; background: var(--border-color);
				border-radius: 3px; overflow: hidden;
			}
			.ib-aa-target-bar-fill {
				height: 100%; border-radius: 3px;
				transition: width 0.5s cubic-bezier(0.4,0,0.2,1);
			}
			.ib-aa-row-bar-track {
				flex: 1; height: 6px; background: var(--border-color);
				border-radius: 4px; overflow: hidden;
			}
			.ib-aa-row-bar-fill {
				height: 100%; border-radius: 4px;
				transition: width 0.5s cubic-bezier(0.4,0,0.2,1);
			}
			.ib-aa-pct--good { color: #16a34a; }
			.ib-aa-pct--mid  { color: var(--ib-primary); }
			.ib-aa-pct--low  { color: #94a3b8; }

			/* Actions — absolutely positioned at row right edge, out of flex flow */
			.ib-aa-user-row { position: relative; }
			.ib-aa-row-actions {
				position: absolute; right: 20px; top: 50%; transform: translateY(-50%);
				display: flex; align-items: center; gap: 5px;
				opacity: 0; pointer-events: none; transition: opacity 0.15s;
			}
			.ib-aa-user-row:hover .ib-aa-row-actions { opacity: 1; pointer-events: auto; }
			/* Kebab trigger */
			.ib-aa-btn-kebab {
				width: 28px; height: 28px; border-radius: 6px;
				border: 1px solid var(--border-color); background: var(--card-bg);
				font-size: 16px; line-height: 1; cursor: pointer; color: var(--text-muted);
				display: flex; align-items: center; justify-content: center; padding: 0;
				transition: all 0.15s; letter-spacing: -1px;
			}
			.ib-aa-btn-kebab:hover { border-color: var(--ib-primary); color: var(--ib-primary); background: #fdf6f3; }

			/* Team header kebab button */
			.ib-aa-btn-team-kebab {
				margin-left: auto; flex-shrink: 0;
				width: 22px; height: 22px; border-radius: 4px;
				border: 1px solid transparent; background: transparent;
				font-size: 14px; cursor: pointer; color: var(--text-muted);
				display: flex; align-items: center; justify-content: center; padding: 0;
				transition: all 0.15s; letter-spacing: -1px;
			}
			.ib-aa-btn-team-kebab:hover { border-color: var(--ib-primary); color: var(--ib-primary); background: rgba(217,119,87,0.08); }

			/* Team manage modal */
			.ib-tm-body { padding: 4px 0; }
			.ib-tm-loading { text-align: center; color: var(--text-muted); padding: 20px; font-size: 13px; }
			.ib-tm-leader-row {
				display: flex; align-items: center; gap: 10px;
				padding: 10px 14px; margin-bottom: 14px;
				border: 1px solid var(--border-color); border-radius: 7px;
				background: var(--subtle-bg);
			}
			.ib-tm-leader-label {
				display: flex; align-items: center; gap: 6px;
				font-size: 12px; font-weight: 700; color: var(--text-color);
				white-space: nowrap;
			}
			.ib-tm-leader-select { max-width: 260px; font-size: 12px; }
			.ib-tm-leader-hint { font-size: 11px; color: var(--text-muted); }
			.ib-tm-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: start; }
			.ib-tm-col { display: flex; flex-direction: column; min-width: 0; }
			.ib-tm-col .ib-tm-section { display: flex; flex-direction: column; }
			.ib-tm-section { border: 1px solid var(--border-color); border-radius: 7px; overflow: hidden; }
			.ib-tm-section-label {
				display: flex; align-items: center; gap: 6px;
				padding: 7px 14px;
				font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.6px;
				color: var(--text-muted); background: var(--subtle-bg);
				border-bottom: 1px solid var(--border-color);
			}
			.ib-tm-count {
				background: var(--border-color); color: var(--text-muted);
				border-radius: 10px; padding: 0 6px; font-size: 10px; font-weight: 700;
			}
			.ib-tm-list { display: flex; flex-direction: column; max-height: 200px; overflow-y: auto; }
			.ib-tm-section-label--sub {
				border-top: 2px solid var(--border-color);
				background: var(--bg-color);
				font-size: 9px; letter-spacing: 0.8px;
			}
			.ib-tm-row {
				display: flex; align-items: center; gap: 10px;
				padding: 8px 14px; border-bottom: 1px solid var(--border-color);
			}
			.ib-tm-row:last-child { border-bottom: none; }
			.ib-tm-row-av {
				width: 28px; height: 28px; border-radius: 50%; flex-shrink: 0;
				color: #fff; font-size: 10px; font-weight: 700;
				display: flex; align-items: center; justify-content: center; letter-spacing: 0.3px;
			}
			.ib-tm-row-info { flex: 1; display: flex; flex-direction: column; gap: 1px; min-width: 0; }
			.ib-tm-row-name { font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
			.ib-tm-row-sub { font-size: 11px; color: var(--text-muted); }
			.ib-tm-empty { padding: 10px 14px; font-size: 12px; color: var(--text-muted); }
			.ib-tm-remove-btn {
				padding: 3px 10px; border-radius: 4px;
				border: 1px solid #fca5a5; background: #fff1f2; color: #b91c1c;
				font-size: 11px; font-weight: 600; cursor: pointer;
				transition: all 0.15s; white-space: nowrap; flex-shrink: 0;
			}
			.ib-tm-remove-btn:hover { background: #b91c1c; color: #fff; border-color: #b91c1c; }
			.ib-tm-remove-btn:disabled { opacity: 0.5; cursor: not-allowed; }

			/* User picker */
			.ib-tm-picker-head {
				display: flex; align-items: center; gap: 8px;
				padding: 8px 14px; border-top: 1px solid var(--border-color);
				background: var(--subtle-bg);
			}
			.ib-tm-picker-title { font-size: 11px; font-weight: 600; color: var(--text-muted); white-space: nowrap; }
			.ib-tm-picker-search {
				flex: 1; padding: 5px 9px;
				border: 1px solid var(--border-color); border-radius: 5px;
				font-size: 12px; background: var(--card-bg); color: var(--text-color);
				transition: border-color 0.15s;
			}
			.ib-tm-picker-search:focus { outline: none; border-color: var(--ib-primary); }
			.ib-tm-picker-list {
				display: flex; flex-direction: column;
				max-height: 200px; overflow-y: auto;
				border-top: 1px solid var(--border-color);
			}
			.ib-tm-picker-row {
				display: flex; align-items: center; gap: 9px;
				padding: 7px 14px; border-bottom: 1px solid var(--border-color);
				transition: background 0.1s;
			}
			.ib-tm-picker-row:last-child { border-bottom: none; }
			.ib-tm-picker-row:hover { background: var(--subtle-bg); }
			.ib-tm-team-badge {
				display: inline-flex; align-items: center; gap: 3px;
				padding: 1px 5px; border-radius: 10px;
				font-size: 9px; font-weight: 700; white-space: nowrap;
				background: color-mix(in srgb, var(--badge-color) 12%, transparent);
				color: var(--badge-color);
				border: 1px solid color-mix(in srgb, var(--badge-color) 25%, transparent);
				vertical-align: middle; line-height: 1.4;
			}
			.ib-tm-team-badge::before { content: "●"; font-size: 6px; }
			.ib-tm-team-badge--none {
				background: var(--subtle-bg); color: var(--text-muted);
				border: 1px solid var(--border-color);
				--badge-color: transparent;
			}
			.ib-tm-team-badge--none::before { content: none; }
			.ib-tm-picker-add-btn {
				padding: 3px 10px; border-radius: 4px;
				border: 1px solid var(--ib-primary); background: #fdf6f3; color: var(--ib-primary);
				font-size: 11px; font-weight: 700; cursor: pointer;
				transition: all 0.15s; white-space: nowrap; flex-shrink: 0;
			}
			.ib-tm-picker-add-btn:hover { background: var(--ib-primary); color: #fff; }
			.ib-tm-picker-add-btn:disabled { opacity: 0.5; cursor: not-allowed; }
			.ib-tm-picker-add-btn--blocked {
				border-color: var(--border-color); background: var(--subtle-bg);
				color: var(--text-muted); cursor: not-allowed;
			}
			.ib-tm-picker-add-btn--blocked:hover { background: var(--subtle-bg); color: var(--text-muted); }

			/* Territory icon — mirrors member avatar circle */
			.ib-tm-territory-icon {
				width: 28px; height: 28px; border-radius: 50%;
				border: 1px solid var(--border-color);
				display: flex; align-items: center; justify-content: center;
				flex-shrink: 0; color: var(--text-muted); background: var(--subtle-bg);
			}

			/* Kebab dropdown */
			.ib-aa-kdrop {
				position: absolute; z-index: 9999;
				background: var(--card-bg); border: 1px solid var(--border-color);
				border-radius: 8px; box-shadow: 0 4px 20px rgba(0,0,0,0.12);
				padding: 4px; min-width: 200px; overflow: hidden;
			}
			.ib-aa-kdrop-header {
				padding: 8px 10px 6px;
				border-bottom: 1px solid var(--border-color);
				margin-bottom: 4px;
			}
			.ib-aa-kdrop-name { font-size: 12px; font-weight: 700; color: var(--text-color); }
			.ib-aa-kdrop-target { font-size: 11px; color: var(--text-muted); margin-top: 2px; font-variant-numeric: tabular-nums; }
			.ib-aa-kdrop-item {
				display: block; width: 100%; text-align: left;
				padding: 7px 10px; border: none; background: transparent;
				font-size: 12px; font-weight: 500; cursor: pointer; border-radius: 5px;
				color: var(--text-color); transition: background 0.1s;
			}
			.ib-aa-kdrop-item:hover { background: var(--subtle-bg); }
			.ib-aa-kdrop-view:hover         { color: #1d4ed8; background: #eff6ff; }
			.ib-aa-kdrop-auto:hover         { color: var(--ib-primary); background: #fdf6f3; }
			.ib-aa-kdrop-transfer:hover     { color: #059669; background: #ecfdf5; }
			.ib-aa-kdrop-hide:hover         { color: #b91c1c; background: #fff1f2; }
			.ib-aa-kdrop-manage-team:hover  { color: #7c3aed; background: #f5f3ff; }
			.ib-aa-kdrop-set-target:hover   { color: #0891b2; background: #ecfeff; }

			/* Set target dialog */
			.ib-st-meta {
				display: flex; align-items: center; gap: 14px;
				padding: 6px 0 10px; font-size: 12px;
			}
			.ib-st-month {
				font-weight: 700; font-size: 13px;
				background: var(--ib-primary); color: #fff;
				padding: 2px 10px; border-radius: 20px;
			}
			.ib-st-actual { color: var(--text-muted); }
			.ib-aa-kdrop-sep {
				height: 1px; background: var(--border-color); margin: 4px 0;
			}


			/* ── View as banner ── */
			.ib-aa-view-as-bar {
				display: flex; align-items: center; justify-content: space-between;
				padding: 12px 20px;
				background: linear-gradient(135deg, #fefce8 0%, #fef9c3 100%);
				border: 1px solid #fde047; border-radius: 10px;
				font-size: 13px; font-weight: 600; color: #713f12;
				box-shadow: 0 1px 4px rgba(0,0,0,0.06);
			}
			.ib-aa-view-as-inner { display: flex; align-items: center; gap: 8px; }
			.ib-aa-exit-view-btn {
				padding: 6px 16px; border-radius: 6px;
				border: 1px solid #fcd34d; background: #fff;
				font-size: 12px; font-weight: 700; cursor: pointer; color: #92400e;
				transition: all 0.15s;
			}
			.ib-aa-exit-view-btn:hover { background: #fcd34d; border-color: #fcd34d; }

			/* ── View-as kanban ── */
			.ib-va-loading { padding: 24px; text-align: center; color: var(--text-muted); font-size: 13px; }
			.ib-va-board { padding: 4px 0 20px; }

			/* Target strip */
			.ib-va-target-strip {
				display: flex; align-items: center; gap: 12px;
				padding: 10px 16px; margin-bottom: 12px;
				background: var(--card-bg); border: 1px solid var(--border-color);
				border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.04);
			}
			.ib-va-ts-label {
				font-size: 11px; font-weight: 700; text-transform: uppercase;
				letter-spacing: 0.5px; color: var(--text-muted); flex-shrink: 0; width: 90px;
			}
			.ib-va-ts-track {
				flex: 1; height: 6px; background: var(--border-color);
				border-radius: 4px; overflow: hidden;
			}
			.ib-va-ts-fill { height: 100%; border-radius: 4px; transition: width 0.5s cubic-bezier(0.4,0,0.2,1); }
			.ib-va-ts-amt { font-size: 12px; color: var(--text-muted); white-space: nowrap; font-variant-numeric: tabular-nums; }
			.ib-va-ts-sep { color: var(--border-color); }
			.ib-va-ts-pct { font-size: 13px; font-weight: 700; white-space: nowrap; flex-shrink: 0; width: 42px; text-align: right; }
			.ib-va-columns {
				display: grid; grid-template-columns: repeat(4, 1fr);
				gap: 14px; align-items: start;
			}
			.ib-va-col {
				background: var(--card-bg);
				border: 1px solid var(--border-color); border-radius: 8px;
				overflow: hidden; display: flex; flex-direction: column;
				max-height: 520px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);
			}
			.ib-va-col-header {
				display: flex; align-items: center; gap: 8px;
				padding: 10px 14px;
				border-bottom: 1px solid var(--border-color);
				background: var(--subtle-bg); flex-shrink: 0;
			}
			.ib-va-col--today    .ib-va-col-header { border-bottom: 2px solid var(--ib-primary); }
			.ib-va-remove-all-btn {
				margin-left: auto; padding: 3px 7px; border-radius: 5px;
				border: 1px solid #fca5a5; background: #fff1f2; color: #b91c1c;
				font-size: 11px; cursor: pointer; display: flex; align-items: center;
				transition: all 0.15s;
			}
			.ib-va-remove-all-btn:hover { background: #b91c1c; color: #fff; border-color: #b91c1c; }
			.ib-va-col--tomorrow .ib-va-col-header { border-bottom: 2px solid #60a5fa; }
			.ib-va-col-icon { opacity: 0.55; flex-shrink: 0; }
			.ib-va-col-title { font-weight: 600; font-size: 13px; flex: 1; }
			.ib-va-col-date { font-size: 10px; color: var(--text-muted); }
			.ib-va-badge {
				background: var(--ib-primary); color: #fff;
				border-radius: 10px; padding: 1px 8px;
				font-size: 11px; font-weight: 600;
			}
			.ib-va-badge--today { background: var(--ib-primary); }
			.ib-va-badge--tmrw  { background: #3b82f6; }
			.ib-va-col-search {
				margin: 8px 8px 4px; padding: 5px 8px; font-size: 12px; width: calc(100% - 16px);
				border: 1px solid var(--border-color); border-radius: 4px;
				background: var(--fg-color, #fff); color: var(--text-color); outline: none; box-sizing: border-box;
			}
			.ib-va-col-search:focus { border-color: var(--ib-primary); }
			.ib-va-cards {
				padding: 10px; display: flex; flex-direction: column; gap: 8px;
				overflow-y: auto; flex: 1;
			}
			.ib-va-card {
				background: var(--fg-color, #fff);
				border: 1px solid var(--border-color); border-radius: 6px;
				padding: 10px 12px; font-size: 12px; flex-shrink: 0;
			}
			.ib-va-card--pool  { border-left: 3px solid var(--border-color); }
			.ib-va-card--today { border-left: 3px solid var(--ib-primary); }
			.ib-va-card--tmrw  { border-left: 3px solid #60a5fa; opacity: 0.85; }
			.ib-va-card--done  { opacity: 0.5; }
			.ib-va-card-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 6px; }
			.ib-va-card-name { font-weight: 600; font-size: 12.5px; line-height: 1.3; }
			.ib-va-card-name--link, .ib-va-card-code.ib-va-card-name--link { cursor: pointer; }
			.ib-va-card-name--link:hover { color: var(--ib-primary, #d97757); text-decoration: underline; }
			.ib-va-card-code { font-size: 10px; color: var(--text-muted); font-family: monospace; margin-top: 1px; }
			.ib-va-card-meta { font-size: 11px; color: var(--text-muted); margin-top: 3px; }
			.ib-va-card-last { font-size: 11px; color: var(--text-muted); margin-top: 2px; }
			.ib-va-status {
				font-size: 10px; font-weight: 700; border-radius: 4px;
				padding: 2px 6px; text-transform: uppercase; white-space: nowrap;
			}
			.ib-va-status--pending   { background: #fef3c7; color: #92400e; }
			.ib-va-status--contacted { background: #d1fae5; color: #065f46; }
			.ib-va-status--ordered   { background: #dbeafe; color: #1e40af; }
			.ib-va-status--skipped   { background: #f3f4f6; color: #6b7280; }
			.ib-va-card-btns { margin-top: 8px; display: flex; gap: 6px; }
			.ib-va-add-btn, .ib-va-tmrw-btn {
				flex: 1; padding: 5px 0; border-radius: 5px;
				font-size: 11px; font-weight: 600; cursor: pointer; transition: all 0.15s;
				display: inline-flex; align-items: center; justify-content: center; gap: 4px;
			}
			.ib-va-add-btn {
				border: 1px solid var(--ib-primary); background: #fdf6f3; color: var(--ib-primary);
			}
			.ib-va-add-btn:hover { background: var(--ib-primary); color: #fff; }
			.ib-va-tmrw-btn {
				border: 1px solid #93c5fd; background: #eff6ff; color: #1d4ed8;
			}
			.ib-va-tmrw-btn:hover { background: #3b82f6; border-color: #3b82f6; color: #fff; }
			.ib-va-add-btn:disabled, .ib-va-tmrw-btn:disabled { opacity: 0.5; cursor: not-allowed; }
			.ib-va-remove-btn {
				margin-top: 8px; width: 100%; padding: 5px 0; border-radius: 5px;
				border: 1px solid #fca5a5; background: #fff1f2; color: #b91c1c;
				font-size: 11px; font-weight: 600; cursor: pointer; transition: all 0.15s;
				display: inline-flex; align-items: center; justify-content: center; gap: 4px;
			}
			.ib-va-remove-btn:hover { background: #b91c1c; color: #fff; border-color: #b91c1c; }
			.ib-va-empty { color: var(--text-muted); font-size: 12px; padding: 16px; text-align: center; }

			/* view-as undo toast */
			.ib-va-undo-toast {
				position: fixed; bottom: 28px; left: 50%; transform: translateX(-50%);
				background: var(--card-bg); border: 1px solid var(--border-color);
				border-radius: 10px; box-shadow: 0 4px 20px rgba(0,0,0,0.12);
				padding: 12px 16px 0; min-width: 300px; max-width: 420px;
				z-index: 9999; overflow: hidden;
			}
			.ib-va-undo-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-bottom: 10px; font-size: 13px; font-weight: 500; }
			.ib-va-undo-btn {
				padding: 4px 14px; border-radius: 5px;
				background: var(--ib-primary); color: #fff;
				border: none; font-size: 12px; font-weight: 700; cursor: pointer; white-space: nowrap;
			}
			.ib-va-undo-bar  { height: 3px; background: var(--border-color); margin: 0 -16px; }
			.ib-va-undo-fill { height: 100%; background: var(--ib-primary); }

			/* ── Manager Queue table ── */
			.ib-aa-queue-thead {
				display: flex; align-items: center;
				padding: 6px 20px;
				background: var(--subtle-bg);
				border-bottom: 1px solid var(--border-color);
			}
			.ib-aa-qth {
				font-size: 10px; font-weight: 700; text-transform: uppercase;
				letter-spacing: 0.5px; color: var(--text-muted);
			}
			.ib-aa-qth--customer { flex: 1; min-width: 0; }
			.ib-aa-qth--territory, .ib-aa-qth--last, .ib-aa-qth--claimed, .ib-aa-qth--action {
				flex-shrink: 0; border-left: 1px solid var(--border-color); padding-left: 12px;
			}
			.ib-aa-qth--territory { width: 140px; }
			.ib-aa-qth--last      { width: 110px; }
			.ib-aa-qth--claimed   { width: 160px; }
			.ib-aa-qth--action    { width: 52px; }

			.ib-aa-queue-row {
				display: flex; align-items: center;
				padding: 10px 20px;
				border-bottom: 1px solid var(--border-color);
				border-left: 3px solid transparent;
				transition: background 0.12s, border-left-color 0.12s;
			}
			.ib-aa-queue-row:last-child { border-bottom: none; }
			.ib-aa-queue-row:hover { background: var(--subtle-bg); border-left-color: var(--ib-primary); }

			.ib-aa-qcol--customer { flex: 1; min-width: 0; }
			.ib-aa-qcol-name {
				font-size: 13px; font-weight: 600;
				white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
			}
			.ib-aa-qcol-code {
				font-size: 11px; color: var(--text-muted); margin-top: 1px;
				white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
			}
			.ib-aa-qcol--territory {
				width: 140px; flex-shrink: 0;
				border-left: 1px solid var(--border-color); padding-left: 12px;
				font-size: 12px; color: var(--text-muted);
				white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
			}
			.ib-aa-qcol--last {
				width: 110px; flex-shrink: 0;
				border-left: 1px solid var(--border-color); padding-left: 12px;
				font-size: 12px; color: var(--text-muted); white-space: nowrap;
			}
			.ib-aa-qcol--claimed {
				width: 160px; flex-shrink: 0;
				border-left: 1px solid var(--border-color); padding-left: 12px;
			}
			.ib-aa-qcol--action {
				width: 52px; flex-shrink: 0;
				border-left: 1px solid var(--border-color); padding-left: 12px;
				display: flex; align-items: center; justify-content: center;
			}
			.ib-aa-queue-claimer-filter {
				padding: 5px 8px; border: 1px solid var(--border-color);
				border-radius: 6px; font-size: 12px;
				background: var(--card-bg); color: var(--text-color);
				cursor: pointer; transition: border-color 0.15s;
			}
			.ib-aa-queue-claimer-filter:focus { outline: none; border-color: var(--ib-primary); }
			.ib-aa-queue-dot-btn {
				width: 28px; height: 28px; border-radius: 6px;
				border: 1px solid var(--border-color); background: var(--card-bg);
				cursor: pointer; color: var(--text-muted);
				display: flex; align-items: center; justify-content: center; padding: 0;
				transition: all 0.15s;
			}
			.ib-aa-queue-dot-btn:hover { border-color: var(--ib-primary); color: var(--ib-primary); background: #fdf6f3; }
			.ib-aa-queue-dot-btn:disabled { opacity: 0.4; cursor: not-allowed; }

			@media (max-width: 900px) {
				.ib-va-columns { grid-template-columns: repeat(2, 1fr); }
				.ib-aa-rth--target { width: 140px; }
				.ib-aa-row-target-wrap { width: 140px; }
				.ib-aa-btn-transfer { display: none; }
				.ib-aa-qth--territory, .ib-aa-qcol--territory { display: none; }
				.ib-aa-qth--last, .ib-aa-qcol--last { display: none; }
			}
		`;
		document.head.appendChild(s);
	}
}
