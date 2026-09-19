frappe.pages["ib-production-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Production",
		single_column: true,
	});
	wrapper.production_shell = new IBProductionShell(page, wrapper);
	frappe.pages["ib-production-dashboard"]._shell = wrapper.production_shell;
};

frappe.pages["ib-production-dashboard"].on_page_show = function (wrapper) {
	if (wrapper.production_shell) wrapper.production_shell._on_show();
};

frappe.pages["ib-production-dashboard"].on_page_hide = function (wrapper) {
	if (wrapper.production_shell) wrapper.production_shell._cleanup();
};

// Cross-nav from Dashboard KPI/pipeline-card/quick-action deep-links into the
// Stages tab of this same merged page. Sets frappe.route_options exactly as
// the old cross-PAGE navigation did (IBProductionStages._consume_route_options()
// in its own constructor already knows how to read this shape — unchanged by
// the merge), then activates the tab directly through the shell instead of a
// page-external frappe.set_route() round-trip through on_page_show — mirrors
// the frappe.pages["<route>"]._shell cross-nav convention already established
// in ib_item_pricing.js / ib_customer_board.js.
function _go_to_production_stages(route_options) {
	const shell = frappe.pages["ib-production-dashboard"]._shell;
	if (!shell) return;
	frappe.route_options = route_options || null;
	frappe.set_route("ib-production-dashboard", "stages");
	shell._activate("stages");
}

/* ─── Outer shell — tabs between Dashboard and Stages ────────────────────── */
class IBProductionShell {
	constructor(page, wrapper) {
		this.page = page;
		this.wrapper = wrapper;
		// page.main (== page.body, ".layout-main-section") is Frappe's own
		// container — page.page_form is prepended inside it at construction
		// time. Never wholesale-replace this node's HTML (see the identical
		// gotcha documented in ib_item_pricing.js / ib_customer_board.js /
		// ib_stock_dashboard.js) — mount the tab bar and a dedicated body div
		// as siblings instead.
		this.$main = $(page.main);
		this._active = null;
		this._active_tab = null;
		this._build_shell();
		this._activate(this._route_tab());
	}

	_route_tab() {
		const route = frappe.get_route();
		return route[1] === "stages" ? "stages" : "dashboard";
	}

	_build_shell() {
		if (!document.getElementById("ib-phx-shell-styles")) {
			const s = document.createElement("style");
			s.id = "ib-phx-shell-styles";
			s.textContent = `
				.ib-phx-tabs { display:flex; gap:4px; padding:10px 0 0; border-bottom:2px solid var(--border-color); margin-bottom:14px; }
				button.ib-phx-tab {
					-webkit-appearance:none; appearance:none;
					padding:8px 28px; border:1.5px solid transparent !important; border-bottom:none !important;
					border-radius:8px 8px 0 0; font-size:13px; font-weight:600; cursor:pointer;
					color:var(--text-muted); background:transparent !important; box-shadow:none !important;
					transition:all .15s; margin-bottom:-2px; line-height:1.4;
				}
				button.ib-phx-tab:hover { background:var(--bg-color) !important; color:var(--text-color); }
				button.ib-phx-tab.ib-phx-tab--active {
					background:var(--card-bg) !important; color:var(--ib-primary,#d97757);
					border-color:var(--border-color) !important; border-bottom-color:var(--card-bg) !important;
				}
				/* Density override for Frappe's own .indicator-pill (rendered via
				   _ib_status_pill()) — the default pill is roomy (20px tall) for
				   a table/list row packed with several per row. Lives in the
				   shell's own always-injected style block (not IBProductionStages'
				   own #ib-ps-styles, which only exists once that tab has been
				   constructed at least once) so it works correctly even if a user
				   only ever visits the Dashboard tab and never opens Stages.
				   Harmless if Stages' own copy of this same rule also loads later. */
				.ib-ps-pill-sm {
					height: auto; padding: 1px 7px 1px 5px; font-size: 10px; font-weight: 600;
				}
				.ib-ps-pill-sm::before { height: 5px; width: 5px; margin-right: 4px; }

				/* ETD pill (_etd_badge()) — used by both Dashboard's Active
				   Production Plan and Stages' Item-wise SO-groups, so it lives
				   here (always-injected) rather than either tab's own
				   #ib-pd-styles/#ib-ps-styles, same reasoning as .ib-ps-pill-sm
				   above. Monotone by design: risk (overdue/at-risk/on-track) is
				   a small dot only, not a full-color badge. */
				.ib-pd-etd-pill {
					display: inline-flex; align-items: center; gap: 5px;
					font-size: 11px; font-weight: 500; color: var(--text-muted);
					background: var(--fg-color, #f9fafb); border: 1px solid var(--border-color);
					border-radius: 999px; padding: 2px 9px 2px 7px; white-space: nowrap;
				}
				.ib-pd-etd-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
			`;
			document.head.appendChild(s);
		}
		this.$main.prepend(`<div class="ib-phx-tabs" id="ib-phx-tabs">
			<button class="ib-phx-tab" data-tab="dashboard">Dashboard</button>
			<button class="ib-phx-tab" data-tab="stages">Stages</button>
		</div>`);
		this.$main.append(`<div id="ib-phx-body"></div>`);
		this.$main.on("click", ".ib-phx-tab", (e) => {
			const tab = $(e.currentTarget).data("tab");
			if (tab === this._active_tab) return;
			frappe.set_route("ib-production-dashboard", tab === "dashboard" ? "" : tab);
			this._activate(tab);
		});
	}

	_on_show() {
		const tab = this._route_tab();
		if (tab !== this._active_tab) {
			this._activate(tab);
			return;
		}
		// Revisiting the same tab (e.g. browser back into this page, or a
		// Desk sidebar click while already here) — no teardown/rebuild needed,
		// just refresh data in place. Matches the old standalone Dashboard's
		// on_page_show, which force-refreshed on every revisit (including
		// clearing _plan_keep_open so a stale expanded-card state doesn't
		// persist across visits); Stages' own refresh() was already this
		// cheap/idempotent on every prior on_page_show too.
		if (this._active_tab === "dashboard" && this._active) this._active._plan_keep_open = null;
		if (this._active && this._active.refresh) this._active.refresh();
	}

	// Called both by the shell's own tab clicks and by _go_to_production_stages()
	// (Dashboard's KPI/pipeline-card/quick-action deep-links) — kept as one
	// entry point so both paths tear down/rebuild the shared Frappe page chrome
	// (toolbar) identically.
	_activate(tab) {
		this._teardown_active();
		this.$main.find(".ib-phx-tab").removeClass("ib-phx-tab--active");
		this.$main.find(`[data-tab="${tab}"]`).addClass("ib-phx-tab--active");

		this.page.clear_primary_action();
		this.page.clear_secondary_action();
		this.page.clear_inner_toolbar();
		this.page.clear_menu();
		this.page.clear_fields();
		this.page.hide_form();

		const $body = this.$main.find("#ib-phx-body").empty();
		this._active_tab = tab;

		if (tab === "dashboard") {
			this._active = new IBProductionDashboard(this.page, $body);
		} else {
			this._active = new IBProductionStages(this.page, $body);
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

// ── Stage colour palette ──────────────────────────────────────────────────────
const STAGE_COLORS = {
	coating:   "#7c3aed",
	slitting:  "#2563eb",
	rewinding: "#0891b2",
	cutting:   "#059669",
	packing:   "#d97706",
};

// Shared by the ETD badge's color and the Active Production Plan's "Overdue" /
// "Overdue + At risk" filter, so the filter and the badge a user is actually
// looking at can never disagree about what counts as overdue/at-risk.
function _etd_risk(dateStr) {
	if (!dateStr) return null;
	const days = frappe.datetime.get_diff(dateStr, frappe.datetime.get_today());
	if (days < 0) return "overdue";
	if (days <= 2) return "at_risk";
	return "on_track";
}

const _ETD_RISK_COLOR = { overdue: "#dc2626", at_risk: "#ea580c", on_track: "#059669" };

// Monotone pill — neutral background/text always (matches the app's
// existing indicator-pill language instead of a loud full-color badge);
// risk (overdue/at-risk/on-track) is conveyed by a small dot only, not by
// recoloring the whole pill. Kept as its own dot rather than folding into
// _ib_status_pill() — ETD isn't a status enum, it's a computed date risk.
function _etd_badge(dateStr) {
	if (!dateStr) return "";
	const risk = _etd_risk(dateStr);
	const dotColor = _ETD_RISK_COLOR[risk] || "#059669";
	return `<span class="ib-pd-etd-pill" title="${risk === "overdue" ? "Overdue" : risk === "at_risk" ? "Due soon" : "On track"}">
		<span class="ib-pd-etd-dot" style="background:${dotColor}"></span>
		${frappe.datetime.str_to_user(dateStr)}
	</span>`;
}

// Every "Start Production" / "start next stage" trigger on this page routes
// through the single grid dialog (ibBulkStartDialog, defined just below). One
// item opens a one-row grid — identical interaction to bulk, no separate modal.
// The old single-item MultiCheck stage picker (_show_start_stage_dialog) and the
// standalone packing-details dialog (_show_packing_details_dialog) were removed
// 2026-09-11 (user: the grid dialog is the bullseye — make it the default).
// `suggestion` is a stage LABEL (matches _get_stage_route's return shape in
// production.py); ibBulkStartDialog falls back to the first stage if blank.
function _start_production_flow(order_sheet_item, item_code, suggestion, onDone) {
	// server helper — the client can't read IB Order Sheet Item (istable) directly
	frappe.call({
		method: "instabiz.overrides.production_run.get_osi_context",
		args: { order_sheet_item },
		callback: (r) => {
			const c = r.message;
			if (!c) { frappe.show_alert({ message: "Could not load the item.", indicator: "red" }); return; }
			_ibStartRunDialog(c.order_sheet, [{
				name: c.order_sheet_item,
				sales_order_item: c.sales_order_item,
				item_code: c.item_code || item_code,
				qty: c.qty || 0,
				uom: c.uom || "",
				width_mm: c.width_mm, length_mtr: c.length_mtr, gsm: c.gsm,
				route: c.route || [],
				next_stage_suggestion: suggestion || (c.route || [])[0] || "",
			}], onDone);
		},
	});
}

// Start Production — WO-per-run model (2026-09-11). ONE run = one RM source
// batch -> one or more finished outputs, produced together through a route.
// `items` — [{ name(osi), item_code, qty, uom, next_stage_suggestion }]. Multiple
// items become multiple outputs on ONE run (the common "N dimension-variants of
// one SKU from one jumbo" case). onDone() fires after create_run succeeds.
function ibBulkStartDialog(items, onDone) {
	items = (items || []).filter(Boolean);
	if (!items.length) {
		frappe.show_alert({ message: "Nothing to start.", indicator: "orange" });
		return;
	}
	// resolve the parent Order Sheet server-side (istable — client get_value is blocked)
	frappe.call({
		method: "instabiz.overrides.production_run.get_osi_context",
		args: { order_sheet_item: items[0].name },
		callback: (r) => {
			const c = r.message;
			if (!c || !c.order_sheet) {
				frappe.show_alert({ message: "Could not resolve the Order Sheet.", indicator: "red" });
				return;
			}
			// carry the server's suggestion/dims onto the first row if the caller didn't
			items[0] = Object.assign({
				sales_order_item: c.sales_order_item,
				width_mm: c.width_mm, length_mtr: c.length_mtr, gsm: c.gsm,
				route: c.route || [],
			}, items[0]);
			if (!items[0].route || !items[0].route.length) items[0].route = c.route || [];
			if (!items[0].next_stage_suggestion) items[0].next_stage_suggestion = (c.route || [])[0] || "";
			_ibStartRunDialog(c.order_sheet, items, onDone);
		},
	});
}

// Real bug, confirmed on live data (IB-WO-2026-25500 — 7 outputs, every
// stage genuinely Completed, only 1 of 7 IB WO Output rows had
// sales_order_item set): every caller of this dialog except the single-
// item path (_start_production_flow) hands over items whose per-row
// sales_order_item was never resolved — _plan_item_row/_find_plan_item's
// source data doesn't carry it. A missing sales_order_item reaches
// create_run as "", and _settle_order_sheet's completion check filters out
// falsy sales_order_item entirely, so that item's Order Sheet Item row can
// never flip to Completed — permanently blocking the whole order's Create
// Delivery Note gate even after production is genuinely finished. Fixed at
// this one choke point (every caller funnels through here) rather than
// patching each call site's own local data shape: resolve whatever's
// missing via one batched server call before ever building the dialog.
function _ibStartRunDialog(order_sheet, items, onDone) {
	const missing = items.filter((it) => !it.sales_order_item).map((it) => it.name);
	if (missing.length) {
		frappe.call({
			method: "instabiz.overrides.production_run.get_osi_context_batch",
			args: { order_sheet_items: JSON.stringify(missing) },
			callback: (r) => {
				const ctx = r.message || {};
				items = items.map((it) => (ctx[it.name] ? Object.assign({}, ctx[it.name], it, {
					sales_order_item: it.sales_order_item || ctx[it.name].sales_order_item,
					width_mm: it.width_mm || ctx[it.name].width_mm,
					length_mtr: it.length_mtr || ctx[it.name].length_mtr,
					gsm: it.gsm || ctx[it.name].gsm,
					route: (it.route && it.route.length) ? it.route : ctx[it.name].route,
				}) : it));
				_ibStartRunDialogBuild(order_sheet, items, onDone);
			},
		});
		return;
	}
	_ibStartRunDialogBuild(order_sheet, items, onDone);
}

function _ibStartRunDialogBuild(order_sheet, items, onDone) {
	const ALL_LABELS = IB_STAGES.map((s) => s.label);
	// A run's own route = the first item's route (every output of ONE run
	// shares one physical pass through the machines, so they necessarily
	// share one route) — fall back to all canonical stages only if the
	// server sent none.
	const route = (items[0] && items[0].route && items[0].route.length) ? items[0].route.slice() : ALL_LABELS.slice();
	const firstSuggestion = items.map((it) => it.next_stage_suggestion).find((s) => route.includes(s)) || route[0];
	const item_codes = new Set(items.map((it) => it.item_code));
	const subtitle = item_codes.size === 1
		? `${items.length} output(s) of ${Array.from(item_codes)[0]}`
		: `${items.length} outputs across ${item_codes.size} SKUs`;

	// Per-row Stage picker — direct ask: "the user prompt where we choose
	// the stages with the multi selection, give this ability." A run's
	// outputs must all share ONE route/start_stage (they're produced
	// together in one physical pass — see the route comment above), but
	// selected items in a bulk start are very often NOT all sitting at the
	// same real point in their own route (one fresh, one already past
	// Coating/Slitting). Forcing everyone onto one dialog-level Start Stage
	// field would silently mis-start whichever items don't match it. Each
	// row defaults to ITS OWN next_stage_suggestion (independently
	// checkable/changeable); on submit, rows are grouped by their selected
	// stage and one run is created per group — a genuinely different-stage
	// selection produces genuinely separate runs, not one run lying about
	// where some of its outputs actually are.
	const rowOptions = (it) => {
		const r = (it.route && it.route.length) ? it.route : route;
		const def = r.includes(it.next_stage_suggestion) ? it.next_stage_suggestion : r[0];
		return r.map((s) => `<option value="${s}" ${s === def ? "selected" : ""}>${s}</option>`).join("");
	};
	const rows = items.map((it, i) => `
		<tr data-i="${i}">
			<td style="white-space:nowrap"><strong>${frappe.utils.escape_html(it.item_code || "")}</strong>
				<div class="text-muted" style="font-size:11px">${it.uom || ""}</div></td>
			<td><select class="form-control input-sm ib-sr-stage" style="width:120px">${rowOptions(it)}</select></td>
			<td><input type="number" class="form-control input-sm ib-sr-qty" value="${flt(it.qty) || 0}" step="any" style="width:100px"></td>
			<td><input type="number" class="form-control input-sm ib-sr-pack" placeholder="boxes/rolls" step="1" style="width:100px"></td>
			<td>
				<input type="text" class="form-control input-sm ib-sr-brand" placeholder="Brand" style="width:90px;display:inline-block">
				<input type="text" class="form-control input-sm ib-sr-core" placeholder="Core" style="width:80px;display:inline-block">
			</td>
		</tr>`).join("");

	const d = new frappe.ui.Dialog({
		title: `Start Production — ${subtitle}`,
		size: "large",
		fields: [
			{ fieldname: "source_batch", fieldtype: "Link", options: "IB Batch", label: "Source RM Batch", reqd: 1,
				get_query: () => ({ filters: { kind: "Raw Material", status: "Active" } }),
				description: "The one raw-material / jumbo batch each run below consumes from." },
			{ fieldname: "source_qty", fieldtype: "Float", label: "RM Qty Consumed",
				description: "Only used when every row below ends up in ONE run (all on the same stage). Leave blank to use each run's own summed output quantity — the only option once rows span more than one stage." },
			{ fieldname: "set_all_stage", fieldtype: "Select", label: "Set Stage For All Rows",
				options: [""].concat(route).join("\n"),
				description: "Quick-fill: applies the picked stage to every row's own selector below. Leave blank to keep each row's own default." },
			{ fieldname: "grid", fieldtype: "HTML", options: `
				<div style="overflow-x:auto"><table class="table table-bordered" style="margin-bottom:0">
					<thead><tr><th>Output Item</th><th>Stage</th><th>Planned Qty</th><th>Pack Count</th><th>Packing (optional)</th></tr></thead>
					<tbody>${rows}</tbody>
				</table></div>` },
		],
		primary_action_label: "Start Run(s)",
		primary_action: (v) => {
			if (!v.source_batch) { frappe.show_alert({ message: "Pick a source RM batch.", indicator: "orange" }); return; }
			const rowData = items.map((it, i) => {
				const $r = d.$wrapper.find(`tr[data-i="${i}"]`);
				return {
					stage: $r.find(".ib-sr-stage").val() || firstSuggestion,
					output: {
						order_sheet_item: it.name,
						sales_order_item: it.sales_order_item || undefined,
						item_code: it.item_code,
						planned_qty: flt($r.find(".ib-sr-qty").val()) || flt(it.qty) || 0,
						uom: it.uom,
						pack_count: cint($r.find(".ib-sr-pack").val()) || 0,
						brand: String($r.find(".ib-sr-brand").val() || "").trim() || undefined,
						core: String($r.find(".ib-sr-core").val() || "").trim() || undefined,
					},
				};
			});
			const groups = new Map();
			for (const { stage, output } of rowData) {
				if (!groups.has(stage)) groups.set(stage, []);
				groups.get(stage).push(output);
			}
			const stages = Array.from(groups.keys());
			d.get_primary_btn().prop("disabled", true).text("Starting…");
			let created = 0, failed = 0;
			const runNext = () => {
				if (!stages.length) {
					d.hide();
					if (failed) {
						frappe.show_alert({ message: `${created} run(s) started, ${failed} failed.`, indicator: created ? "orange" : "red" }, 5);
					} else {
						frappe.show_alert({ message: groups.size > 1
							? `${created} runs started (grouped by stage).` : "Run started.", indicator: "green" }, 4);
					}
					if (onDone) onDone();
					return;
				}
				const stage = stages.shift();
				const outputs = groups.get(stage);
				frappe.call({
					method: "instabiz.overrides.production_run.create_run",
					args: {
						order_sheet, source_batch: v.source_batch,
						// A shared explicit RM-qty override only makes sense when
						// everything collapsed into one run — split across several
						// stage-groups it's ambiguous, so each group falls back to
						// its own summed output quantity instead of guessing a split.
						source_qty: (groups.size === 1 && v.source_qty) ? v.source_qty : null,
						outputs: JSON.stringify(outputs),
						start_stage: stage,
					},
					callback: (r) => {
						if (r.exc || !r.message) failed += 1; else created += 1;
						runNext();
					},
					error: () => { failed += 1; runNext(); },
				});
			};
			runNext();
		},
	});
	// Quick-fill wiring — applies the picked stage to every row's own select.
	d.fields_dict.set_all_stage.$input.on("change", () => {
		const val = d.get_value("set_all_stage");
		if (!val) return;
		d.$wrapper.find(".ib-sr-stage").each((_, el) => { if ($(el).find(`option[value="${val}"]`).length) $(el).val(val); });
	});
	d.show();
}


function ibBulkStartResults(result) {
	const lines = [`<strong>${result.started}</strong> started`];
	if (result.skipped) lines.push(`<strong>${result.skipped}</strong> skipped (packing details not captured)`);
	if (result.failed) lines.push(`<strong>${result.failed}</strong> failed`);
	const fail = (result.details || []).filter((r) => r.status === "error");
	const skip = (result.details || []).filter((r) => r.status === "skipped");
	let dh = "";
	if (skip.length) dh += `<div style="margin-top:8px"><strong>Skipped:</strong><ul style="margin:4px 0 0 18px">` +
		skip.map((r) => `<li>${frappe.utils.escape_html(r.item_code)}</li>`).join("") + `</ul></div>`;
	if (fail.length) dh += `<div style="margin-top:8px"><strong>Failed:</strong><ul style="margin:4px 0 0 18px">` +
		fail.map((r) => `<li>${frappe.utils.escape_html(r.item_code)} — ${frappe.utils.escape_html(r.stage)}: ${frappe.utils.escape_html(r.message || "")}</li>`).join("") + `</ul></div>`;
	frappe.msgprint({
		title: "Bulk Start Results",
		indicator: result.failed ? "orange" : "green",
		message: `<div>${lines.join(" · ")}</div>${dh}`,
	});
}

// Actual-output-vs-target prompt shown before completing a stage — the
// only real wastage capture path in the system (IB Production Entry, the
// sole other thing that ever wrote wastage, has zero rows by design — see
// complete_work_order()'s own docstring in production.py). Defaults to
// target_qty so a click-through-without-changing-anything still completes
// cleanly with zero wastage, same as before this existed. Top-level (not a
// class method) since both IBProductionDashboard's Active Production Plan
// row buttons and IBProductionStages' WO side panel need it — same pattern
// as _start_production_flow above.
function _prompt_actual_output(wo, onConfirm) {
	const target = Number(wo.target_qty) || 0;
	const uom = wo.target_uom || "";
	const d = new frappe.ui.Dialog({
		title: "Complete Stage",
		fields: [
			{
				fieldname: "actual_qty",
				fieldtype: "Float",
				label: `Actual Output${uom ? ` (${uom})` : ""}`,
				default: target,
				reqd: 1,
				description: `Target: ${target}${uom ? " " + uom : ""}. Wastage is the difference.`,
			},
		],
		primary_action_label: "Complete",
		primary_action: (vals) => {
			d.hide();
			onConfirm(vals.actual_qty);
		},
	});
	d.show();
}

// Shared by both places a run gets advanced (Active Production Plan row +
// WO side panel) — checks whether the NEXT stage is Cutting and the run's
// finished length exceeds every real cutter's max_length_m before even
// trying the normal advance. If so, offers to split into N shorter batches
// (production_run.advance_with_length_split) instead of just throwing "no
// machine can run this job" with no way forward. onOk/onFail get the same
// {status, message, next_stage} shape either way so callers don't need to
// know which path actually ran.
function _advance_with_split_check(wo_name, actual_qty, onOk, onFail) {
	frappe.call({
		method: "instabiz.overrides.production_run.get_length_split_plan",
		args: { work_order: wo_name },
		callback: (r) => {
			const plan = r.message || {};
			if (!plan.needed) {
				return _do_plain_advance(wo_name, actual_qty, onOk, onFail);
			}
			frappe.confirm(
				__(
					"This run's finished length ({0}m) is longer than any {1} machine can cut in one pass (best: {2}m). Split it into {3} batches of ~{4}m each and continue?",
					[plan.total_length_m, plan.next_stage, plan.best_machine_capacity_m, plan.batches, plan.batch_length_m]
				),
				() => {
					frappe.call({
						method: "instabiz.overrides.production_run.advance_with_length_split",
						args: { work_order: wo_name, batches: plan.batches, output_qty: actual_qty },
						freeze: true,
						freeze_message: __("Splitting into {0} batches…", [plan.batches]),
						callback: (r2) => {
							if (r2.exc || !r2.message || !r2.message.ok) {
								onFail(r2.message?.message || __("Failed to split."));
								return;
							}
							onOk({
								status: "ok",
								message: __("Split into {0} batches — each now assigned and running.", [plan.batches]),
								next_stage: null,
							});
						},
					});
				},
				() => onFail(__("Not advanced — length still exceeds machine capacity.")),
			);
		},
		error: () => _do_plain_advance(wo_name, actual_qty, onOk, onFail),
	});
}

function _do_plain_advance(wo_name, actual_qty, onOk, onFail) {
	const args = { work_order: wo_name };
	if (actual_qty !== undefined) args.actual_qty = actual_qty;
	frappe.call({
		method: "instabiz.overrides.production.advance_to_next_stage",
		args,
		callback: (r) => {
			if (r.exc || !r.message || r.message.status !== "ok") {
				onFail(r.message?.message || __("Failed to advance."));
				return;
			}
			onOk(r.message);
		},
	});
}

const PLAN_PAGE_SIZE = 25;

// Small animated "actively running" indicator — a soft pulsing ring around a
// solid dot, shown next to a stage label only when a real Work Order there
// is genuinely In Progress right now (not Pending/On Hold/Completed). CSS
// keyframes, not SMIL, so it stays crisp and cheap across many rows at once.
function _live_pulse_svg(title) {
	return `<svg class="ib-pd-live-pulse" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
		${title ? `<title>${frappe.utils.escape_html(title)}</title>` : ""}
		<circle class="ib-pd-live-pulse-ring" cx="6" cy="6" r="5" />
		<circle class="ib-pd-live-pulse-dot" cx="6" cy="6" r="2.5" />
	</svg>`;
}

// Server-computed (get_production_plan, production.py) against the item's
// real route length — NOT a count of however many stage_map entries happen
// to have a status. Under JIT, stage_map only ever has an entry per stage
// that's had a Work Order created (most of a fresh item's stages have none
// at all), so counting "stages with a status" as "total stages" read a
// freshly-finished first stage as 100% done. Real bug, fixed 2026-08-30 —
// see get_production_plan's own comment for the full story.
function _item_is_done(item) {
	return item.is_fully_done === true;
}

class IBProductionDashboard {
	constructor(page, $mount) {
		this.page      = page;
		this.$mount    = $mount;
		this._fetching = false;
		// Shared with Production Stages (same localStorage key) so picking a
		// location on either page carries over to the other.
		this.location_filter = localStorage.getItem("ib_prod_location") || "";
		this.plan_search = "";
		this.plan_priority = "";
		// Stage filter is purely client-side — every order sheet's
		// items/stage_map already arrives in the get_production_plan response,
		// no server round-trip needed to re-slice what's already on screen.
		this.plan_stage = "";
		// Item rows that have finished every stage are always hidden from the
		// Active Production Plan (same criterion as the "✓ Done" badge in the
		// Actions column) — no user-facing toggle, always on.
		this.hide_completed_items = true;
		// Current page's Order Sheets — kept so the stage filter/hide-completed
		// re-filter can re-render the visible page instantly without a re-fetch.
		this._plan_all_rows = [];
		// 1-indexed. Server-side paginated (not accumulated) — Prev/Next, not
		// infinite scroll. _plan_has_more reflects whether the last fetch
		// returned a full page (so there's likely a next page), same signal
		// the old infinite-scroll sentinel used, just driving a button now.
		this._plan_page = 1;
		this._plan_has_more = true;
		// Order Sheet name (os.name) to force-expand on the next _render_plan()
		// call — set right before a row action (Start/Next Stage/Move) or a
		// manual chevron-open triggers a reload, so the card the user was just
		// looking at doesn't snap back to collapsed. Cleared on any explicit
		// reload (Refresh button, location/search/priority filter change).
		this._plan_keep_open = null;
		// Order Sheet Item names checked for bulk-start (2026-08-30) — cleared on
		// every fresh fetch (_load_plan_page), since paging/filtering changes
		// which rows are even visible; survives a plain re-render otherwise.
		this._plan_bulk_selected = new Set();
		this._inject_styles();
		this._build_layout();
		this._add_toolbar_buttons();
		this.refresh();
	}

	// ── Public ────────────────────────────────────────────────────────────────
	refresh() {
		if (this._fetching) return;
		this._fetching = true;
		this._set_refresh_label("Loading…");
		this.$container.find("#ib-pd-kpis").html(window.ib_skel_kpis ? ib_skel_kpis(4) : "");
		this._plan_page = 1;

		let _done = 0;
		const _total = 2;
		const _check_done = () => {
			if (++_done >= _total) {
				this._fetching = false;
				this._set_refresh_label("Updated " + frappe.datetime.now_time());
				ib_countup_all && ib_countup_all(this.$container);
			}
		};

		frappe.call({
			method: "instabiz.overrides.production.get_production_dashboard",
			args: { location: this.location_filter || "" },
			callback: (r) => {
				if (r.message) this._render(r.message);
				else this._set_refresh_label("No data");
				_check_done();
			},
			error: () => { this._set_refresh_label("Error loading data"); _check_done(); },
		});
		this._load_plan_page(1, _check_done);
	}

	// Pagination (not infinite scroll — replaced 2026-08-11): fetches exactly
	// one page, replaces the visible list. `page` is 1-indexed; `on_done` is
	// an optional callback wired only by refresh()'s parallel-fetch tracker.
	_load_plan_page(page, on_done) {
		if (this._plan_loading) return;
		this._plan_loading = true;
		this.$container.find("#ib-pd-plan-pager").html("Loading…");
		frappe.call({
			method: "instabiz.overrides.production.get_production_plan",
			args: {
				limit: PLAN_PAGE_SIZE, start: (page - 1) * PLAN_PAGE_SIZE,
				location: this.location_filter || "",
				search: this.plan_search || "",
				priority: this.plan_priority || "",
			},
			callback: (r) => {
				const rows = (r.message && r.message.order_wise) || [];
				this._plan_page = page;
				this._plan_has_more = rows.length === PLAN_PAGE_SIZE;
				this._plan_loading = false;
				this._plan_all_rows = rows;
				this._plan_bulk_selected.clear();
				this._update_bulk_start_toolbar();
				this._render_plan(rows);
				if (on_done) on_done();
			},
			error: () => {
				this._plan_loading = false;
				if (on_done) on_done();
			},
		});
	}

	// ── Layout ────────────────────────────────────────────────────────────────
	_build_layout() {
		this.$container = $(`
			<div class="ib-pd-page container">
				<div class="ib-pd-top-bar">
					<div class="ib-pd-loc-group">
						<iconify-icon icon="lucide:map-pin" width="13" height="13" style="color:var(--text-muted)"></iconify-icon>
						<select id="ib-pd-location" class="ib-pd-select">
							<option value="">All Locations</option>
							<option value="gujarat">Gujarat (Factory)</option>
							<option value="maharashtra">Maharashtra (Warehouse)</option>
							<option value="chennai">Chennai (Warehouse)</option>
						</select>
					</div>
					<span id="ib-pd-refresh-ts" class="ib-pd-refresh-time"></span>
				</div>
				<div class="ib-pd-kpi-row" id="ib-pd-kpis"></div>
				<div id="ib-pd-pipeline-section" style="display:none">
					<div class="ib-pd-section-title">Pipeline</div>
					<div class="ib-pd-pipeline" id="ib-pd-pipeline"></div>
				</div>
				<div id="ib-pd-pipeline-hint" class="ib-pd-empty" style="display:none">
					<iconify-icon icon="lucide:map-pin" width="15" height="15" style="vertical-align:middle;margin-right:5px;opacity:.6"></iconify-icon>
					Pick a location above to see its stage pipeline — Maharashtra and Chennai are
					warehouse-only (Packing only), Gujarat runs the full factory chain.
				</div>
				<div class="ib-pd-section-title" id="ib-pd-bundles-title" style="display:none">
					<iconify-icon icon="lucide:layers" width="13" height="13" style="vertical-align:middle;margin-right:5px"></iconify-icon>
					Job Bundles
				</div>
				<div id="ib-pd-bundles"></div>
				<div class="ib-pd-section-title">Active Production Plan</div>
				<div class="ib-pd-plan-toolbar">
					<div class="ib-pd-filter-group ib-pd-filter-group--search">
						<iconify-icon icon="lucide:search" width="13" height="13" style="color:var(--text-muted)"></iconify-icon>
						<input type="text" id="ib-pd-plan-search" class="ib-pd-search-input" placeholder="Search Sales Order, customer, or item code…">
					</div>
					<div id="ib-pd-plan-priority-wrap" class="ib-pd-native-filter"></div>
					<div id="ib-pd-plan-stage-wrap" class="ib-pd-native-filter"></div>
				</div>
				<div id="ib-pd-plan"></div>
				<div id="ib-pd-plan-pager" class="ib-pd-pager"></div>
				<div class="ib-pd-bulk-bar" id="ib-pd-bulk-bar" style="display:none">
					<span class="ib-pd-bulk-bar-count"><span id="ib-pd-bulk-start-count">0</span> selected</span>
					<button type="button" class="btn btn-default btn-sm" id="ib-pd-bulk-clear-btn">Clear</button>
					<button type="button" class="btn btn-primary btn-sm" id="ib-pd-bulk-start-btn">
						<iconify-icon icon="lucide:play" width="12" height="12" style="vertical-align:middle;margin-right:4px"></iconify-icon>
						Bulk Start
					</button>
				</div>
				<div class="ib-pd-quick-actions" id="ib-pd-actions"></div>
			</div>
		`).appendTo(this.$mount);

		this.$container.find("#ib-pd-location").val(this.location_filter);
		this.$container.find("#ib-pd-location").on("change", (e) => {
			this.location_filter = $(e.target).val();
			localStorage.setItem("ib_prod_location", this.location_filter);
			this._plan_keep_open = null;
			this.refresh();
		});

		let plan_search_timer = null;
		this.$container.find("#ib-pd-plan-search").on("input", (e) => {
			clearTimeout(plan_search_timer);
			const val = $(e.target).val();
			plan_search_timer = setTimeout(() => {
				this.plan_search = val;
				this._plan_keep_open = null;
				this.refresh();
			}, 300);
		});

		// Native Frappe Select controls (same frappe.ui.form.make_control +
		// only_input pattern list_utils.js uses for list-view filter rows) —
		// gives these two filters standard Frappe control markup/styling
		// instead of a bespoke <select>.
		const priorityCtrl = frappe.ui.form.make_control({
			df: {
				label: "",
				fieldtype: "Select",
				options: ["", "Urgent", "High", "Normal", "Low"],
				placeholder: __("All Priorities"),
				onchange: () => {
					this.plan_priority = priorityCtrl.get_value() || "";
					this._plan_keep_open = null;
					this.refresh();
				},
			},
			parent: this.$container.find("#ib-pd-plan-priority-wrap"),
			only_input: true,
			render_input: 1,
		});
		priorityCtrl.$wrapper.css("margin-bottom", 0);
		priorityCtrl.set_value(this.plan_priority);

		const stageCtrl = frappe.ui.form.make_control({
			df: {
				label: "",
				fieldtype: "Select",
				options: ["", "Coating", "Slitting", "Rewinding", "Cutting", "Packing"],
				placeholder: __("All Stages"),
				onchange: () => {
					this.plan_stage = stageCtrl.get_value() || "";
					this._render_plan(this._plan_all_rows);
				},
			},
			parent: this.$container.find("#ib-pd-plan-stage-wrap"),
			only_input: true,
			render_input: 1,
		});
		stageCtrl.$wrapper.css("margin-bottom", 0);
		stageCtrl.set_value(this.plan_stage);
		// Select's rendered <option value=""> label is blank by default —
		// swap it for the same "All Stages"/"All Priorities" wording the
		// old plain <select> used, purely cosmetic.
		priorityCtrl.$input.find(`option[value=""]`).text(__("All Priorities"));
		stageCtrl.$input.find(`option[value=""]`).text(__("All Stages"));

		this.$container.find("#ib-pd-bulk-start-btn").on("click", () => {
			if (!this._plan_bulk_selected.size) return;
			this._show_bulk_start_dialog(Array.from(this._plan_bulk_selected));
		});
		this.$container.find("#ib-pd-bulk-clear-btn").on("click", () => {
			this._plan_bulk_selected.clear();
			this._update_bulk_start_toolbar();
			this._render_plan(this._plan_all_rows);
		});
	}

	_add_toolbar_buttons() {
		// Cross-nav to the Stages tab used to be a page-level primary action
		// here ("Production Stages" button, routed via frappe.set_route) —
		// retired 2026-08-05 when the two pages merged into tabs of one page;
		// the tab bar itself is now the obvious way to get there. Only Refresh
		// remains as page-level chrome.
		this.page.add_button(__("Refresh"), () => {
			this._plan_keep_open = null;
			this.refresh();
		}, { icon: "refresh" });
	}

	// Called by IBProductionShell._teardown_active() whenever the outer tab
	// switches away from Dashboard (and on page hide) — this class is torn
	// down and freshly reconstructed on every "Dashboard" tab activation now
	// that it lives inside a shell (destroy-and-rebuild lifecycle, same as
	// Item Pricing / Stock / Customer Board), so any listener bound outside
	// its own $container scope must be explicitly released here or it leaks a
	// duplicate on the next activation. The comment popover in particular is
	// appended to document.body (outside $container entirely, see
	// _show_comment_popover) — without this it would keep floating over the
	// Stages tab after switching away.
	_cleanup() {
		this._close_comment_popover();
	}

	_set_refresh_label(text) {
		this.$container.find("#ib-pd-refresh-ts").text(text);
	}

	// ── Render ────────────────────────────────────────────────────────────────
	_render(data) {
		this._render_kpis(data.summary || {});
		if (this.location_filter) {
			this.$container.find("#ib-pd-pipeline-section").show();
			this.$container.find("#ib-pd-pipeline-hint").hide();
			this._render_pipeline(data.pipeline || []);
		} else {
			this.$container.find("#ib-pd-pipeline-section").hide();
			this.$container.find("#ib-pd-pipeline-hint").show();
		}
		this._render_actions();
	}

	_render_kpis(s) {
		const today = frappe.datetime.get_today();
		// Routes into Production Stages (its polished Item-wise/Machine-wise
		// views) instead of the raw IB Work Order doctype list. These 4 KPIs
		// are computed from IB Work Order.status directly (see
		// get_production_dashboard in production.py) — a different grain from
		// IB Order Sheet.status (Draft/In Progress/Completed), which is one
		// row per Sales Order and stays "In Progress" for the order's entire
		// multi-week run regardless of how many of its Work Orders are done.
		// Routing these into Order-wise's status filter (as an earlier version
		// of this code did) showed the wrong list — an Order-Sheet-grain count
		// that has nothing to do with the WO-grain number on the card.
		// "Active Work Orders" / "Pending" now route into Item-wise instead —
		// grouped by item_code across ALL Order Sheets (see get_item_wise_view),
		// already WO-grain and already spans everything, same shape as these
		// KPIs. Item-wise's `status` route option (consumed in
		// IBProductionStages._consume_route_options/_render_item_wise below —
		// merged into this same file 2026-08-05, formerly its own ib_production_stages.js)
		// keeps only items with at least one Work Order matching the given
		// status — exact-value match for "Pending", any-of match for "Active"
		// (mirrors the backend's own `status NOT IN ('Completed','Cancelled')`).
		// "Completed Today" is a date-scoped historical count (status=Completed
		// AND completed *today* specifically), not a "what's active right now"
		// view — none of the Stages tab's 5 sub-tabs are built for that. The DPR (Daily
		// Production Report) page already computes and renders this exact same
		// value (`wo_completed` in get_dpr(), shown as its "WOs Completed" KPI
		// card) via an identical WHERE clause, defaulting to today on load — a
		// genuine exact grain+date match, so route there instead.
		const kpis = [
			{
				label: "Active Work Orders", value: s.active_work_orders ?? 0, color: "#2563eb", icon: "layers",
				sub: "Pending + In Progress",
				click: () => {
					_go_to_production_stages({ tab: "item_wise", status: ["Pending", "In Progress", "On Hold"] });
				},
			},
			{
				label: "Pending", value: s.pending ?? 0, color: "#d97706", icon: "clock",
				sub: "Awaiting start",
				// Only metric that gets a colour cue — an amber status dot when
				// there's a real backlog. Everything else stays monochrome.
				attention: (s.pending ?? 0) > 0,
				click: () => {
					_go_to_production_stages({ tab: "item_wise", status: "Pending" });
				},
			},
			{
				label: "Completed Today", value: s.completed_today ?? 0, color: "#059669", icon: "check-circle",
				sub: frappe.datetime.str_to_user(today),
				click: () => frappe.set_route("ib-dpr"),
			},
			{
				label: "Machines Active", value: s.machines_active ?? 0, color: "#0891b2", icon: "settings-2",
				sub: "Production floor",
				click: () => _go_to_production_stages({ tab: "machine_wise" }),
			},
		];
		const $kpis = this.$container.find("#ib-pd-kpis").html(kpis.map((k, i) => `
			<div class="ib-pd-kpi-card ib-pd-kpi--link" data-kpi="${i}">
				<div class="ib-pd-kpi-head">
					<span class="ib-pd-kpi-label">${k.label}</span>
					${k.attention
						? `<span class="ib-pd-kpi-dot" style="background:${k.color}"></span>`
						: `<span class="ib-pd-kpi-icon"><iconify-icon icon="lucide:${k.icon}" width="14" height="14"></iconify-icon></span>`}
				</div>
				<div class="ib-pd-kpi-value">${k.value}</div>
				<div class="ib-pd-kpi-sub">${k.sub || ""}</div>
			</div>
		`).join(""));
		$kpis.find(".ib-pd-kpi--link").on("click", (e) => {
			kpis[parseInt($(e.currentTarget).data("kpi"), 10)].click();
		});
	}

	_render_pipeline(stages) {
		if (!stages.length) {
			stages = Object.keys(STAGE_COLORS).map(s => ({
				stage: s, pending: 0, in_progress: 0, completed: 0,
			}));
		}
		const STAGE_ICONS = {
			coating: "layers", slitting: "scissors", rewinding: "refresh-cw",
			cutting: "crop", packing: "package",
		};
		const html = stages.map(s => {
			const color = STAGE_COLORS[s.stage] || "#888";
			const label = s.stage.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
			const total = (s.pending ?? 0) + (s.in_progress ?? 0) + (s.completed ?? 0);
			const active_pct = total > 0 ? Math.round(((s.in_progress ?? 0) / total) * 100) : 0;
			const done_pct = total > 0 ? Math.round(((s.completed ?? 0) / total) * 100) : 0;
			const icon_name = STAGE_ICONS[s.stage] || "circle";
			return `
				<div class="ib-pd-pipeline-card" style="border-top:3px solid ${color}"
					data-stage="${s.stage}" title="Go to ${label} in the Stages tab">
					<div class="ib-pd-pipe-head">
						<span class="ib-pd-pipe-icon" style="background:${color}15;color:${color}">
						<iconify-icon icon="lucide:${icon_name}" width="14" height="14"></iconify-icon>
					</span>
						<span class="ib-pd-pipeline-name" style="color:${color}">${label}</span>
					</div>
					<div class="ib-pd-pipe-total" style="color:${color}">${total}</div>
					<div class="ib-pd-pipe-sublabel">total WOs</div>
					<div class="ib-pd-pipe-bar-stack">
						<div title="In Progress: ${s.in_progress}" style="width:${active_pct}%;background:${color};opacity:.85"></div>
						<div title="Completed: ${s.completed}" style="width:${done_pct}%;background:${color}40"></div>
					</div>
					<div class="ib-pd-pipe-counts">
						<span class="ib-pd-ps-badge pending">${s.pending ?? 0}</span>
						<span class="ib-pd-ps-badge inprog">${s.in_progress ?? 0}</span>
						<span class="ib-pd-ps-badge done">${s.completed ?? 0}</span>
					</div>
				</div>
			`;
		}).join("");
		// Exact real stage labels, keyed by the lowercase_underscore key the
		// backend sends — the naive "capitalize every word" transform used for
		// the card's display text is fine now every stage is a single word,
		// but kept explicit for the same reason list filters need the exact
		// stored label (IB Work Order.stage stores the exact-cased label).
		const STAGE_KEY_TO_LABEL = {
			coating: "Coating", slitting: "Slitting", rewinding: "Rewinding",
			cutting: "Cutting", packing: "Packing",
		};
		const $pipeline = this.$container.find("#ib-pd-pipeline").html(html);
		$pipeline.find(".ib-pd-pipeline-card").on("click", (e) => {
			const stageKey = $(e.currentTarget).data("stage");
			const stageLabel = STAGE_KEY_TO_LABEL[stageKey] || String(stageKey);
			// Item-wise is the polished view for "what's at this stage right
			// now" — the Stages tab reads the stage filter client-side
			// (IB Work Order.stage stores this exact label already).
			_go_to_production_stages({ tab: "item_wise", stage: stageLabel, location: this.location_filter || undefined });
		});
	}

	_render_actions() {
		this.$container.find("#ib-pd-actions").html(`
			<button class="ib-pd-quick-btn" id="ib-pd-goto-stages">
				Stages tab →
			</button>
			<button class="ib-pd-quick-btn ib-pd-quick-btn--minor" id="ib-pd-goto-stages-orderwise"
				title="Work Orders grouped by order, in the Stages tab's Order-wise view.">
				Work Orders →
			</button>
			<button class="ib-pd-quick-btn" id="ib-pd-goto-dpr">
				DPR Report →
			</button>
		`);
		const $actions = this.$container.find("#ib-pd-actions");
		$actions.off("click", "#ib-pd-goto-stages").on("click", "#ib-pd-goto-stages", () => _go_to_production_stages());
		$actions.off("click", "#ib-pd-goto-stages-orderwise").on("click", "#ib-pd-goto-stages-orderwise", () => _go_to_production_stages({ tab: "order_wise" }));
		$actions.off("click", "#ib-pd-goto-dpr").on("click", "#ib-pd-goto-dpr", () => frappe.set_route("ib-dpr"));
	}

	_render_plan(order_sheets) {
		const $el = this.$container.find("#ib-pd-plan");
		const $pager = this.$container.find("#ib-pd-plan-pager");
		if (!order_sheets.length) {
			$el.html(this._plan_page > 1
				? `<div class="ib-pd-empty">No orders on this page.</div>`
				: `<div class="ib-pd-empty">No active production orders. Submit a Sales Order to auto-generate production.</div>`);
			this._render_plan_pager($pager);
			return;
		}

		// Stage filter is client-side, applied on top of whatever
		// this._plan_all_rows already has loaded — same reasoning as
		// hide_completed_items above (every item's current_stage already
		// arrived in the get_production_plan response).
		let filteredSheets = order_sheets;
		if (this.plan_stage) {
			filteredSheets = filteredSheets.filter(os =>
				(os.items || []).some(item => (item.current_stage || "") === this.plan_stage)
			);
		}
		if (!filteredSheets.length) {
			$el.html(`<div class="ib-pd-empty">No orders match the current filters.</div>`);
			this._render_plan_pager($pager);
			return;
		}

		const stageStatusCls = { "Completed": "ib-pd-stg--done", "In Progress": "ib-pd-stg--inprog", "Pending": "ib-pd-stg--pending" };

		const rows = filteredSheets.map(os => {
			const allItems = os.items || [];
			// "Do not show done WO" toggle — filters out item rows with nothing
			// left to advance (same criterion as the "✓ Done" badge below).
			// Filtering happens on the item list itself, not just visually
			// hiding rendered rows, so a fully-done card can fall through to
			// the "all items complete" empty state below instead of an empty
			// <table>. Stage filter narrows further to just the items currently
			// sitting at the picked stage — the order itself already passed the
			// "has at least one matching item" check above, but a multi-item
			// order should only show that matching item here, not every item.
			let visibleItems = this.hide_completed_items
				? allItems.filter(item => !_item_is_done(item))
				: allItems;
			if (this.plan_stage) {
				visibleItems = visibleItems.filter(item => (item.current_stage || "") === this.plan_stage);
			}
			const itemRows = visibleItems.map(item => {
				const currentStage = item.current_stage || "";
				const stageMap = item.stage_map || {};
				const stagePills = Object.entries(stageMap).map(([stage, info]) => {
					if (!info.status) return "";
					const cls = stageStatusCls[info.status] || "ib-pd-stg--pending";
					const title = `${stage}: ${info.status} (${info.completed_qty}/${info.target_qty})`;
					// Full stage name (not an abbreviation) + its own icon, and a
					// pulse while genuinely In Progress — direct ask: "make sure
					// user knows which stage they are looking at," "use icons with
					// stages," "animate the stage in progress badge."
					const liveCls = info.status === "In Progress" ? " ib-pd-stg--live" : "";
					return `<span class="ib-pd-stg-chip ${cls}${liveCls}" title="${title}">${_stage_chip_icon(stage)}${frappe.utils.escape_html(stage)}</span>`;
				}).join("");

				// route_length/route_completed_count (get_production_plan,
				// production.py) are against the item's real route — NOT a count
				// of however many stage_map entries happen to have a WO. Under
				// JIT, stage_map only gets an entry per stage that's actually
				// been started, so a fresh item finishing stage 1 of a real
				// 5-stage route used to read as "1 of 1 done" here — 100% and
				// falsely "fully done". Real bug, fixed 2026-08-30.
				const totalStages = item.route_length || 0;
				const completedStages = item.route_completed_count || 0;
				const pct = totalStages ? Math.round(completedStages / totalStages * 100) : 0;

				// Primary action acts on the Work Order behind the item's current
				// stage — Start when Pending, Next Stage when In Progress. This is
				// the everyday action and gets full visual weight. The stage-picker
				// + Move button is a rare escape hatch (manually jumping a WO out
				// of normal sequence, e.g. correcting a mis-routed item) — tucked
				// behind a small toggle icon so it never competes visually with the
				// primary action. Items with nothing left to do (100% complete) get
				// an explicit done indicator instead of an empty cell.
				const curInfo = stageMap[currentStage] || {};
				const woName = curInfo.wo_name || "";
				const isFullyDone = item.is_fully_done === true;

				// Packing is always the last stage in every item route now (RTD/
				// Delivered collapsed out of the stage model 2026-08-13 — see
				// _get_stage_route in production.py, every route ends at Packing) —
				// the same "In Progress" click there calls advance_to_next_stage(),
				// which the backend already special-cases to just complete the WO
				// with no next stage. Label it accordingly instead of the
				// misleading "Next Stage →".
				const isLastStage = currentStage === "Packing";
				let primaryBtn = "";
				if (woName && (curInfo.status === "Pending" || curInfo.status === "On Hold")) {
					primaryBtn = `<button class="ib-pd-row-btn ib-pd-row-btn--primary ib-pd-row-start" data-wo="${frappe.utils.escape_html(woName)}" title="${curInfo.status === "On Hold" ? "Resume work on this stage" : "Begin work on this stage"}">${curInfo.status === "On Hold" ? "Resume" : "Start"}</button>`;
				} else if (woName && curInfo.status === "In Progress" && isLastStage) {
					primaryBtn = `<button class="ib-pd-row-btn ib-pd-row-btn--primary ib-pd-row-advance" data-wo="${frappe.utils.escape_html(woName)}" data-target-qty="${item.qty || 0}" data-target-uom="${frappe.utils.escape_html(item.uom || "")}" title="Mark this item as fully produced">Finish</button>`;
				} else if (woName && curInfo.status === "In Progress") {
					primaryBtn = `<button class="ib-pd-row-btn ib-pd-row-btn--primary ib-pd-row-advance" data-wo="${frappe.utils.escape_html(woName)}" data-target-qty="${item.qty || 0}" data-target-uom="${frappe.utils.escape_html(item.uom || "")}" title="Complete this stage and move to the next">Next Stage →</button>`;
				} else if (!woName && !isFullyDone) {
					// JIT stage model (2026-08-13): the normal resting state now —
					// nothing active/pending for this item (never started, or its
					// last-started stage just completed). No WO exists to act on
					// yet; picking one is the action itself.
					// Checkbox alongside it (2026-08-30) is purely for bulk-start —
					// one SKU sold as several line items at different dimensions
					// (width/color/etc) is common, and clicking Start Production
					// once per row is slow; ticking several and using the toolbar's
					// "Bulk Start" button applies the same picked stage(s) to all
					// of them in one go, still via this exact per-item flow under
					// the hood (bulk_start_item_stages just loops start_item_stage).
					primaryBtn = `<label class="ib-pd-row-select" title="Select for bulk start">
						<input type="checkbox" class="ib-pd-row-bulk-check" data-osi="${frappe.utils.escape_html(item.name)}" ${this._plan_bulk_selected.has(item.name) ? "checked" : ""}>
					</label>
					<button class="ib-pd-row-btn ib-pd-row-btn--primary ib-pd-row-start-stage"
						data-osi="${frappe.utils.escape_html(item.name)}"
						data-item="${frappe.utils.escape_html(item.item_code || "")}"
						data-suggestion="${frappe.utils.escape_html(item.next_stage_suggestion || "")}"
						title="Pick a stage and begin work">Start Production</button>`;
				}

				const doneBadge = (!primaryBtn && isFullyDone)
					? `<span class="ib-pd-row-done" title="All stages complete for this item">
							<iconify-icon icon="lucide:check-circle-2" width="12" height="12"></iconify-icon> Done
						</span>`
					: "";

				// Adjust Qty (pcs_to_make/logs_to_make) is per-WO/per-stage — flag
				// it on the item row the same way the Order-wise table does, so
				// an adjustment isn't invisible on the Dashboard tab.
				const adjustments = Object.entries(stageMap)
					.map(([stage, info]) => {
						const adjusted = info.target_uom === "PCS" ? info.pcs_to_make
							: info.target_uom === "SQMT" ? info.logs_to_make
							: null;
						return (adjusted && adjusted != info.target_qty)
							? { stage, from: info.target_qty, to: adjusted, uom: info.target_uom }
							: null;
					})
					.filter(Boolean);
				const adjBadge = adjustments.length
					? `<div class="ib-pd-plan-row-adj" title="${frappe.utils.escape_html(
							adjustments.map(a => `${a.stage}: ${a.from} → ${a.to} ${a.uom}`).join(" | ")
						)}">adj → ${adjustments[0].to}${adjustments.length > 1 ? ` (+${adjustments.length - 1})` : ""}</div>`
					: "";

				return `
					<div class="ib-pd-plan-row">
						<div class="ib-pd-plan-row-cell ib-pd-plan-row-item">
							<div class="ib-pd-plan-item">${frappe.utils.escape_html(item.item_code || "")}</div>
							${item.item_name ? `<div class="ib-pd-plan-item-name">${frappe.utils.escape_html(item.item_name)}</div>` : ""}
						</div>
						<div class="ib-pd-plan-row-cell ib-pd-plan-row-qty">${item.qty || 0} <span class="ib-pd-plan-row-uom">${item.uom || ""}</span>${adjBadge}</div>
						<div class="ib-pd-plan-row-cell ib-pd-plan-row-stage">
							<div class="ib-pd-plan-row-stage-label">${currentStage || "—"}${curInfo.status === "In Progress" ? _live_pulse_svg() : ""}</div>
							<div class="ib-pd-stg-pills">${stagePills}</div>
						</div>
						<div class="ib-pd-plan-row-cell ib-pd-plan-row-progress">
							<div class="ib-pd-prog-bar-wrap">
								<div class="ib-pd-prog-bar" style="width:${pct}%"></div>
							</div>
							<span class="ib-pd-prog-pct">${pct}%</span>
						</div>
						<div class="ib-pd-plan-row-cell ib-pd-row-actions">${primaryBtn}${doneBadge}</div>
					</div>`;
			}).join("");

			// Subline still reports the order's real item count regardless of
			// the toggle — it describes the order, not the current filtered
			// view.
			const itemCount = allItems.length;
			// Collapse threshold is based on what's actually rendered
			// (visibleItems), not the order's total item count — a 3-item
			// order with 2 already hidden as done shouldn't collapse just
			// because it "has 3 items" on paper. Overridden open for whichever
			// card was in view when an in-card action (Start/Next Stage/Move)
			// or a manual expand triggered this re-render — see
			// this._plan_keep_open.
			const collapsedByDefault = visibleItems.length > 2 && os.name !== this._plan_keep_open;
			const customerName = os.customer_name || os.customer || "—";
			const commentCount = os.comment_count || 0;
			// Independent of the "hide completed items" toggle (which only
			// controls what's visible, not what's true) — this order's Order
			// Sheet is about to flip to Completed status server-side the moment
			// this page next refreshes, but the DN option shouldn't have to
			// wait for that refresh when every item is already provably done
			// right now from the same data this card is already rendering.
			const orderFullyDone = allItems.length > 0 && allItems.every(_item_is_done);
			const dnBtn = (orderFullyDone && os.sales_order)
				? `<button class="btn btn-primary btn-xs ib-pd-plan-create-dn" data-so="${frappe.utils.escape_html(os.sales_order)}">
						<iconify-icon icon="lucide:truck" width="11" height="11" style="vertical-align:middle;margin-right:3px"></iconify-icon>
						Create Delivery Note
					</button>`
				: "";
			const bodyHtml = visibleItems.length
				? itemRows
				: `<div class="ib-pd-plan-all-done">
						<span class="ib-pd-plan-all-done-label">
							<iconify-icon icon="lucide:check-circle-2" width="14" height="14"></iconify-icon>
							All items in this order are complete
						</span>
						${dnBtn}
					</div>`;

			return `
				<div class="ib-pd-plan-card">
					<div class="ib-pd-plan-header ib-pd-plan-toggle" data-os="${os.name}">
						<div class="ib-pd-plan-start">
							<iconify-icon icon="lucide:chevron-right" width="14" height="14" class="ib-pd-plan-chevron"
								style="${collapsedByDefault ? "" : "transform:rotate(90deg)"}"></iconify-icon>
							<div class="ib-pd-plan-main">
								<div class="ib-pd-plan-title">
									<span class="ib-pd-tag ib-pd-tag--so" title="Sales Order">SO</span>
									<a class="ib-pd-plan-so-link" href="/app/sales-order/${os.sales_order || ""}" target="_blank" onclick="event.stopPropagation()">${os.sales_order || os.name}</a>
									<span class="ib-pd-plan-customer">${frappe.utils.escape_html(customerName)}</span>
									${os.status === "In Progress" ? _live_pulse_svg("In Progress — production active") : ""}
								</div>
								<div class="ib-pd-plan-subline">${itemCount} item${itemCount !== 1 ? "s" : ""}${os.creation ? ` · Created ${frappe.datetime.str_to_user(os.creation)}` : ""}</div>
							</div>
						</div>
						<div class="ib-pd-plan-meta">
							${_ib_status_pill(os.priority || "Normal", "sm")}
							${_etd_badge(os.delivery_date)}
							<span class="ib-pd-plan-comment-wrap">
								<button class="ib-pd-plan-comment-btn" data-so="${frappe.utils.escape_html(os.sales_order || "")}"
									title="${os.sales_order ? "Add comment" : "No linked Sales Order"}"
									${os.sales_order ? "" : "disabled"}>
									<iconify-icon icon="lucide:message-square" width="12" height="12"></iconify-icon>
								</button>
								${commentCount > 0 ? `<span class="ib-pd-plan-comment-count">${commentCount}</span>` : ""}
							</span>
						</div>
					</div>
					<div class="ib-pd-plan-body" data-os-body="${os.name}" style="${collapsedByDefault ? "display:none" : ""}">
						${bodyHtml}
					</div>
				</div>`;
		}).join("");

		// One shared column header for the whole list, rendered once — not
		// per-card. Every item row (across every order) shares the exact same
		// .ib-pd-plan-columns/.ib-pd-plan-row grid-template-columns, so columns
		// stay pixel-aligned down the whole page regardless of how long an
		// item code or customer name runs in any one card.
		const columnsHtml = `
			<div class="ib-pd-plan-columns">
				<span>Item</span><span>Qty</span><span>Stage</span><span>Progress</span><span>Actions</span>
			</div>`;
		$el.html(columnsHtml + rows);
		this._render_plan_pager($pager);
		$el.off("click", ".ib-pd-plan-toggle").on("click", ".ib-pd-plan-toggle", (e) => {
			const os = $(e.currentTarget).data("os");
			const $body = $el.find(`[data-os-body="${os}"]`);
			const $chevron = $(e.currentTarget).find(".ib-pd-plan-chevron");
			const opening = $body.css("display") === "none";
			$body.css("display", opening ? "" : "none");
			$chevron.css("transform", opening ? "rotate(90deg)" : "");
			// Manually opening a card marks it as the one to keep open through
			// the next automatic (row-action-triggered) refresh; manually
			// closing it clears that if it was the one being tracked.
			if (opening) this._plan_keep_open = os;
			else if (this._plan_keep_open === os) this._plan_keep_open = null;
		});

		$el.off("click", ".ib-pd-row-start").on("click", ".ib-pd-row-start", (e) => {
			e.stopPropagation();
			// Disable immediately — refresh() re-renders everything with fresh
			// buttons on success, but the RPC round-trip leaves a window where
			// this exact button would otherwise still be sitting there
			// clickable, showing "Start" on a WO that's already In Progress.
			const $btn = $(e.currentTarget);
			if ($btn.prop("disabled")) return;
			$btn.prop("disabled", true);
			this._plan_keep_open = $btn.closest("[data-os-body]").data("osBody") || null;
			this._plan_row_call("instabiz.overrides.production.start_work_order",
				{ work_order: $btn.data("wo") }, "Started", $btn);
		});
		$el.off("click", ".ib-pd-row-advance").on("click", ".ib-pd-row-advance", (e) => {
			e.stopPropagation();
			const $btn = $(e.currentTarget);
			if ($btn.prop("disabled")) return;
			const wo = $btn.data("wo");
			this._plan_keep_open = $btn.closest("[data-os-body]").data("osBody") || null;
			// Asks actual output vs target first (wastage capture) — same dialog
			// the WO side panel's Advance/Complete buttons use. Not disabled
			// until Confirm, same reasoning as the panel's guarded()-exclusion
			// comment: nothing to re-enable this button with if the dialog is
			// cancelled.
			_prompt_actual_output(
				{ target_qty: $btn.data("targetQty"), target_uom: $btn.data("targetUom") },
				(actual_qty) => {
					$btn.prop("disabled", true);
					_advance_with_split_check(
						wo, actual_qty,
						(msg) => {
							frappe.show_alert({ message: msg.message || "Advanced.", indicator: "green" }, 3);
							this.refresh();
						},
						(err) => {
							frappe.show_alert({ message: err, indicator: "red" });
							$btn.prop("disabled", false);
						},
					);
				},
			);
		});
		$el.off("click", ".ib-pd-row-start-stage").on("click", ".ib-pd-row-start-stage", (e) => {
			e.stopPropagation();
			const $btn = $(e.currentTarget);
			this._plan_keep_open = $btn.closest("[data-os-body]").data("osBody") || null;
			_start_production_flow(
				$btn.data("osi"), $btn.data("item"), $btn.data("suggestion"),
				() => this.refresh(),
			);
		});

		$el.off("click", ".ib-pd-row-bulk-check").on("click", ".ib-pd-row-bulk-check", (e) => {
			e.stopPropagation();
		});
		$el.off("change", ".ib-pd-row-bulk-check").on("change", ".ib-pd-row-bulk-check", (e) => {
			const osi = $(e.currentTarget).data("osi");
			if ($(e.currentTarget).is(":checked")) this._plan_bulk_selected.add(osi);
			else this._plan_bulk_selected.delete(osi);
			this._update_bulk_start_toolbar();
		});
		$el.off("click", ".ib-pd-plan-comment-btn").on("click", ".ib-pd-plan-comment-btn", (e) => {
			e.stopPropagation();
			const sales_order = $(e.currentTarget).data("so");
			if (!sales_order) return;
			this._show_comment_popover(sales_order, $(e.currentTarget));
		});

		$el.off("click", ".ib-pd-plan-create-dn").on("click", ".ib-pd-plan-create-dn", (e) => {
			e.stopPropagation();
			const $btn = $(e.currentTarget);
			if ($btn.prop("disabled")) return;
			$btn.prop("disabled", true);
			frappe.call({
				method: "instabiz.overrides.sales_order.custom_make_delivery_note",
				args: { source_name: $btn.data("so") },
				callback: (r) => {
					if (!r.message) {
						frappe.show_alert({ message: "Failed to create Delivery Note.", indicator: "red" });
						$btn.prop("disabled", false);
						return;
					}
					frappe.model.sync(r.message);
					frappe.set_route("Form", r.message.doctype, r.message.name);
				},
				error: () => $btn.prop("disabled", false),
			});
		});
	}

	// Shows/hides the floating bottom bulk bar and keeps its count current —
	// called on every checkbox toggle instead of a full re-render (selection
	// state itself doesn't change what any row looks like beyond its own
	// checkbox, which is already correct from the click that got us here).
	_update_bulk_start_toolbar() {
		const n = this._plan_bulk_selected.size;
		this.$container.find("#ib-pd-bulk-start-count").text(n);
		this.$container.find("#ib-pd-bulk-bar").css("display", n ? "" : "none");
	}

	// Bulk-start dialog — one shared stage picker (same MultiCheck control as
	// the single-item Start Production dialog) applied to every selected
	// Order Sheet Item at once. Defaults to whichever stage most of the
	// selected items themselves suggest next, since the common real case is
	// several dimension-variants of one SKU all sitting at the same stage.
	// Per-item stage grid, not one shared picker — two selected items can
	// each be resting at a genuinely different point in their own route
	// (one brand new needing Coating first, another already past
	// Coating/Slitting and just resting between stages needing Rewinding
	// next) even though both show the same "Start Production" button.
	// Each row defaults to that item's own next_stage_suggestion, checkable
	// independently — a shared "Same stage for all" toggle covers the
	// common case (one order's dimension-variants all starting together)
	// without forcing it.
	// opts.items — pre-resolved item objects ({name, item_code, qty, uom,
	//   next_stage_suggestion}) when the caller isn't the Dashboard plan
	//   (e.g. the Order-wise "Start All Items" button). Falls back to
	//   _find_plan_item() lookup when omitted.
	// opts.onDone — called after a successful bulk start instead of the
	//   plan-bulk-selected cleanup + full refresh.
	_show_bulk_start_dialog(osiList, opts = {}) {
		const items = (opts.items && opts.items.length)
			? opts.items
			: osiList.map((osi) => this._find_plan_item(osi)).filter(Boolean);
		ibBulkStartDialog(items, opts.onDone || (() => {
			this._plan_bulk_selected.clear();
			this._update_bulk_start_toolbar();
			this.refresh();
		}));
	}

	// Finds a selected item's own row data (item_code, next_stage_suggestion)
	// out of the currently-loaded plan page — used only to build the bulk
	// dialog's subtitle/default stage, never sent back to the server.
	_find_plan_item(osi) {
		for (const os of this._plan_all_rows || []) {
			const hit = (os.items || []).find((it) => it.name === osi);
			if (hit) return hit;
		}
		return null;
	}

	// Prev/Next pager for the Active Production Plan list — replaced the old
	// scroll-to-bottom infinite scroll (2026-08-11). No total-page count from
	// the server (would need an extra COUNT query the old scroll version never
	// needed either) — Next just stays enabled whenever the last fetch
	// returned a full page, same "is there more" signal the scroll sentinel
	// used, just driving a button instead of a scroll listener.
	_render_plan_pager($pager) {
		$pager.html(`
			<button type="button" class="btn btn-default btn-xs ib-pd-plan-prev" ${this._plan_page <= 1 ? "disabled" : ""}>
				<iconify-icon icon="lucide:chevron-left" width="12" height="12"></iconify-icon> Prev
			</button>
			<span class="ib-pd-plan-page-label">Page ${this._plan_page}</span>
			<button type="button" class="btn btn-default btn-xs ib-pd-plan-next" ${this._plan_has_more ? "" : "disabled"}>
				Next <iconify-icon icon="lucide:chevron-right" width="12" height="12"></iconify-icon>
			</button>`);
		$pager.off("click", ".ib-pd-plan-prev").on("click", ".ib-pd-plan-prev", () => {
			if (this._plan_page > 1) { this._plan_keep_open = null; this._load_plan_page(this._plan_page - 1); }
		});
		$pager.off("click", ".ib-pd-plan-next").on("click", ".ib-pd-plan-next", () => {
			if (this._plan_has_more) { this._plan_keep_open = null; this._load_plan_page(this._plan_page + 1); }
		});
	}

	// ── Comment popover ──────────────────────────────────────────────────────
	// Reuses the app's existing floating comment popover (public/js/comment_popover.js,
	// loaded globally on every page via app_include_js) rather than a fresh
	// frappe.ui.Dialog modal — same markup/CSS classes (.ib-cp-*, already in
	// instabiz.bundle.css), same anchor-positioned/backdrop-closed mechanics,
	// same posting call (frappe.desk.form.utils.add_comment). That file's own
	// click handler only fires for list-view ".comment-count" badges, so it
	// can't be called directly from this page — replicated here instead of
	// editing that shared file, since this page is scoped to a single file.
	_close_comment_popover() {
		if (this._cp_backdrop) { this._cp_backdrop.remove(); this._cp_backdrop = null; }
		if (this._cp_popover) { this._cp_popover.remove(); this._cp_popover = null; }
		$(document).off("keydown.ib-pd-cp");
	}

	_show_comment_popover(sales_order, $anchor) {
		this._close_comment_popover();
		// Kept so _submit_comment can bump the count badge next to this exact
		// button after a successful post, without a full plan refresh.
		this._cp_anchor = $anchor;

		this._cp_backdrop = $('<div class="ib-cp-backdrop"></div>').appendTo("body");
		this._cp_backdrop.on("click", () => this._close_comment_popover());

		this._cp_popover = $(`
			<div class="ib-cp-popover">
				<div class="ib-cp-header">
					<div class="ib-cp-title">
						<iconify-icon icon="mdi:comment-text-outline" width="14"></iconify-icon>
						<span>Comments</span>
						<span class="ib-cp-docref">${frappe.utils.escape_html(sales_order)}</span>
					</div>
					<button class="ib-cp-close" title="${__("Close")}">×</button>
				</div>
				<div class="ib-cp-list">
					<div class="ib-cp-loading">${__("Loading…")}</div>
				</div>
				<div class="ib-cp-footer">
					<textarea class="ib-cp-input" placeholder="${__("Write a comment… (Ctrl+Enter to post)")}" rows="2"></textarea>
					<button class="btn btn-primary btn-sm ib-cp-submit">${__("Post")}</button>
				</div>
			</div>
		`).appendTo("body");

		this._position_comment_popover($anchor);

		this._cp_popover.find(".ib-cp-close").on("click", () => this._close_comment_popover());
		this._cp_popover.find(".ib-cp-submit").on("click", () => this._submit_comment(sales_order));
		this._cp_popover.find(".ib-cp-input").on("keydown", (e) => {
			if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) this._submit_comment(sales_order);
		});
		$(document).on("keydown.ib-pd-cp", (e) => {
			if (e.key === "Escape") this._close_comment_popover();
		});

		this._fetch_comments(sales_order);
	}

	// Same absolute-position-relative-to-document approach as comment_popover.js's
	// position() — flips to the left edge of the anchor if it would overflow the
	// viewport's right edge. Absolute positioning (not fixed) means the popover
	// naturally scrolls with the page alongside its anchor, no scroll listener needed.
	_position_comment_popover($anchor) {
		const rect = $anchor[0].getBoundingClientRect();
		const pw = 340;
		const gap = 6;
		const scrollY = window.scrollY || document.documentElement.scrollTop;
		const scrollX = window.scrollX || document.documentElement.scrollLeft;

		let left = rect.left + scrollX;
		let top = rect.bottom + scrollY + gap;
		if (left + pw > window.innerWidth - 12) left = rect.right + scrollX - pw;

		this._cp_popover.css({ top, left, width: pw });
	}

	_fetch_comments(sales_order) {
		frappe.call({
			method: "frappe.client.get_list",
			args: {
				doctype: "Comment",
				filters: {
					reference_doctype: "Sales Order",
					reference_name: sales_order,
					comment_type: "Comment",
				},
				fields: ["name", "comment_by", "comment_email", "content", "creation"],
				order_by: "creation asc",
				limit: 50,
			},
			callback: (r) => {
				if (!this._cp_popover) return;
				const comments = (r && r.message) || [];
				const $list = this._cp_popover.find(".ib-cp-list");
				if (!comments.length) {
					$list.html(`<div class="ib-cp-empty">${__("No comments yet.")}</div>`);
				} else {
					$list.html(comments.map(this._render_comment_row).join(""));
					$list.scrollTop($list[0].scrollHeight);
				}
			},
		});
	}

	_render_comment_row(c) {
		const initials = (c.comment_by || c.comment_email || "?")
			.split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase();
		const when = frappe.datetime.comment_when
			? frappe.datetime.comment_when(c.creation)
			: c.creation;
		return `
			<div class="ib-cp-comment">
				<div class="ib-cp-avatar">${initials}</div>
				<div class="ib-cp-body">
					<div class="ib-cp-meta">
						<span class="ib-cp-author">${frappe.utils.escape_html(c.comment_by || c.comment_email || "")}</span>
						<span class="ib-cp-time">${when}</span>
					</div>
					<div class="ib-cp-content">${c.content || ""}</div>
				</div>
			</div>`;
	}

	_submit_comment(sales_order) {
		if (!this._cp_popover) return;
		const $input = this._cp_popover.find(".ib-cp-input");
		const text = $input.val().trim();
		if (!text) return;

		const $btn = this._cp_popover.find(".ib-cp-submit").prop("disabled", true).text(__("Posting…"));
		frappe.call({
			method: "frappe.desk.form.utils.add_comment",
			args: {
				reference_doctype: "Sales Order",
				reference_name: sales_order,
				content: `<p>${frappe.utils.escape_html(text).replace(/\n/g, "<br>")}</p>`,
				comment_email: frappe.session.user,
				comment_by: frappe.boot.user.full_name || frappe.session.user,
			},
			callback: (r) => {
				if (!this._cp_popover) return;
				$btn.prop("disabled", false).text(__("Post"));
				if (!r || !r.message) return;

				$input.val("");
				const $list = this._cp_popover.find(".ib-cp-list");
				$list.find(".ib-cp-empty").remove();
				$list.append(this._render_comment_row(r.message));
				$list.scrollTop($list[0].scrollHeight);
				frappe.show_alert({ message: __("Comment posted"), indicator: "green" }, 3);
				this._bump_comment_count(sales_order);
			},
		});
	}

	// Increments the count badge next to the comment icon for this Sales
	// Order's card, without a full plan refresh. Also updates the in-memory
	// _plan_all_rows so a later toggle-triggered re-render doesn't revert it.
	_bump_comment_count(sales_order) {
		if (this._cp_anchor && this._cp_anchor.length) {
			const $wrap = this._cp_anchor.closest(".ib-pd-plan-comment-wrap");
			let $badge = $wrap.find(".ib-pd-plan-comment-count");
			const next = (parseInt($badge.text(), 10) || 0) + 1;
			if (!$badge.length) {
				$badge = $(`<span class="ib-pd-plan-comment-count"></span>`).appendTo($wrap);
			}
			$badge.text(next);
		}
		(this._plan_all_rows || []).forEach(os => {
			if (os.sales_order === sales_order) os.comment_count = (os.comment_count || 0) + 1;
		});
	}

	_plan_row_call(method, args, successLabel, $btn) {
		frappe.call({
			method,
			args,
			callback: (r) => {
				if (r.exc || (r.message && r.message.status && r.message.status !== "ok")) {
					frappe.show_alert({ message: `Failed — ${successLabel.toLowerCase()} did not apply.`, indicator: "red" });
					if ($btn) $btn.prop("disabled", false);
					return;
				}
				frappe.show_alert({ message: successLabel, indicator: "green" }, 2);
				this.refresh();
			},
		});
	}

	// ── AI prod actions panel ─────────────────────────────────────────────────
	// ── Styles ────────────────────────────────────────────────────────────────
	_inject_styles() {
		if (document.getElementById("ib-pd-styles")) return;
		const style = document.createElement("style");
		style.id = "ib-pd-styles";
		style.textContent = `
			.ib-pd-page {
				padding: 20px 0;
				font-family: inherit;
			}
			.ib-pd-top-bar {
				display: flex;
				align-items: center;
				justify-content: space-between;
				margin-bottom: 14px;
				flex-wrap: wrap;
				gap: 8px;
			}
			.ib-pd-loc-group {
				display: flex;
				align-items: center;
				gap: 7px;
			}
			.ib-pd-select {
				padding: 6px 12px;
				border: 1px solid var(--border-color, #e2e8f0);
				border-radius: 7px;
				background: var(--card-bg, #fff);
				color: var(--text-color, #1e293b);
				font-size: 12.5px;
				font-weight: 600;
				min-width: 190px;
				cursor: pointer;
			}
			.ib-pd-select:focus { outline: none; border-color: var(--ib-primary, #d97757); }
			.ib-pd-plan-toolbar {
				display: flex;
				align-items: center;
				gap: 10px;
				flex-wrap: wrap;
				margin-bottom: 12px;
			}
			.ib-pd-bulk-bar {
				position: fixed;
				left: 50%;
				bottom: 20px;
				transform: translateX(-50%);
				z-index: 100;
				display: flex;
				align-items: center;
				gap: 12px;
				background: var(--text-color, #1e293b);
				color: #fff;
				padding: 10px 14px 10px 18px;
				border-radius: 10px;
				box-shadow: 0 8px 24px rgba(0,0,0,.22), 0 2px 6px rgba(0,0,0,.12);
			}
			.ib-pd-bulk-bar-count {
				font-size: 13px;
				font-weight: 600;
				white-space: nowrap;
			}
			.ib-pd-bulk-bar #ib-pd-bulk-clear-btn {
				background: transparent;
				border: 1px solid rgba(255,255,255,.3);
				color: #fff;
			}
			.ib-pd-bulk-bar #ib-pd-bulk-clear-btn:hover { background: rgba(255,255,255,.1); }
			.ib-pd-filter-group--search {
				display: flex;
				align-items: center;
				gap: 8px;
				background: var(--control-bg, var(--card-bg, #fff));
				border: 1px solid var(--border-color, #d1d8dd);
				border-radius: var(--border-radius-sm, 6px);
				padding: 0 10px;
				height: var(--input-height, 28px);
				flex: 1 1 280px;
				max-width: 360px;
				margin-bottom: 0;
			}
			.ib-pd-search-input {
				border: none;
				outline: none;
				background: none;
				flex: 1;
				font-size: 12.5px;
				color: var(--text-color, #1e293b);
				padding: 0;
				height: 100%;
			}
			.ib-pd-search-input::placeholder { color: var(--text-muted, #6b7280); }
			/* Native frappe.ui.form.make_control Select filters (Priority/Stage) —
			   markup + styling come straight from Frappe's own control system;
			   this only constrains width so they sit compactly in the toolbar
			   row instead of stretching full-width. */
			.ib-pd-native-filter {
				flex: 0 0 150px;
				max-width: 150px;
			}
			.ib-pd-native-filter .form-control {
				font-size: 12.5px;
			}
			.ib-pd-kpi-row {
				display: grid;
				grid-template-columns: repeat(4, 1fr);
				gap: 12px;
				margin-bottom: 24px;
			}
			.ib-pd-kpi-card {
				background: var(--card-bg, #fff);
				border: 1px solid var(--border-color, #e5e7eb);
				border-radius: 12px;
				padding: 16px;
				display: flex;
				flex-direction: column;
				gap: 6px;
				transition: background .12s, border-color .12s;
			}
			.ib-pd-kpi--link { cursor: pointer; }
			.ib-pd-kpi-card:hover {
				background: var(--subtle-fg, #f8fafc);
				border-color: var(--border-color, #d1d5db);
			}
			.ib-pd-kpi-head {
				display: flex;
				align-items: center;
				justify-content: space-between;
			}
			.ib-pd-kpi-label {
				font-size: 11px;
				font-weight: 600;
				letter-spacing: .06em;
				text-transform: uppercase;
				color: var(--text-muted, #6b7280);
			}
			.ib-pd-kpi-icon { color: var(--text-muted, #9ca3af); display: inline-flex; }
			.ib-pd-kpi-dot { width: 6px; height: 6px; border-radius: 50%; flex: 0 0 auto; }
			.ib-pd-kpi-value {
				font-size: 28px;
				font-weight: 650;
				line-height: 1;
				color: var(--text-color, #111827);
				font-variant-numeric: tabular-nums;
				letter-spacing: -.01em;
			}
			.ib-pd-kpi-sub {
				font-size: 11px;
				color: var(--text-muted, #6b7280);
			}
			@media (max-width: 720px) {
				.ib-pd-kpi-row { grid-template-columns: repeat(2, 1fr); }
			}
			.ib-pd-section-title {
				font-size: 13px;
				font-weight: 700;
				text-transform: uppercase;
				letter-spacing: .06em;
				color: var(--text-muted, #6b7280);
				margin: 20px 0 10px;
			}
			.ib-pd-pipeline {
				display: flex;
				gap: 12px;
				overflow-x: auto;
				padding-bottom: 6px;
				margin-bottom: 20px;
			}
			.ib-pd-pipeline-card {
				flex: 0 0 145px;
				background: var(--card-bg, #fff);
				border: 1px solid var(--border-color, #e2e8f0);
				border-radius: 10px;
				padding: 14px 13px;
				cursor: pointer;
				transition: box-shadow .15s, transform .15s;
				box-shadow: 0 1px 3px rgba(0,0,0,.05);
			}
			.ib-pd-pipeline-card:hover {
				box-shadow: 0 6px 18px rgba(0,0,0,.12);
				transform: translateY(-3px);
			}
			.ib-pd-pipe-head { display: flex; align-items: center; gap: 6px; margin-bottom: 10px; }
			.ib-pd-pipe-icon { display: inline-flex; align-items: center; justify-content: center; width: 26px; height: 26px; border-radius: 6px; flex-shrink: 0; }
			.ib-pd-pipeline-name {
				font-size: 11px;
				font-weight: 700;
				text-transform: uppercase;
				letter-spacing: .04em;
			}
			.ib-pd-pipe-total { font-size: 26px; font-weight: 700; line-height: 1; margin-bottom: 2px; }
			.ib-pd-pipe-sublabel { font-size: 10px; color: var(--text-muted, #6b7280); margin-bottom: 8px; }
			.ib-pd-pipe-bar-stack {
				height: 4px; border-radius: 2px;
				background: var(--border-color, #e2e8f0);
				overflow: hidden; display: flex;
				margin-bottom: 8px;
			}
			.ib-pd-pipe-bar-stack > div { height: 100%; }
			.ib-pd-pipe-counts { display: flex; gap: 4px; }
			.ib-pd-ps-badge {
				font-size: 11px;
				font-weight: 700;
				min-width: 20px;
				text-align: center;
				border-radius: 4px;
				padding: 1px 5px;
			}
			.ib-pd-ps-badge.pending { background: #fef3c7; color: #92400e; }
			.ib-pd-ps-badge.inprog  { background: #dbeafe; color: #1e3a8a; }
			.ib-pd-ps-badge.done    { background: #d1fae5; color: #064e3b; }
			.ib-pd-ps-label {
				font-size: 11px;
				color: var(--text-muted, #6b7280);
			}
			.ib-pd-table {
				width: 100%;
				border-collapse: collapse;
				background: var(--card-bg, #fff);
				border: 1px solid var(--border-color, #e2e8f0);
				border-radius: 10px;
				overflow: hidden;
				font-size: 13px;
				margin-bottom: 20px;
			}
			.ib-pd-table th {
				background: var(--subtle-fg, #f8fafc);
				font-size: 11px;
				font-weight: 700;
				text-transform: uppercase;
				letter-spacing: .05em;
				color: var(--text-muted, #6b7280);
				padding: 10px 12px;
				text-align: left;
				border-bottom: 1px solid var(--border-color, #e2e8f0);
			}
			.ib-pd-table td {
				padding: 9px 12px;
				border-bottom: 1px solid var(--border-color, #f1f5f9);
				color: var(--text-color, #1e293b);
			}
			.ib-pd-table tr:last-child td { border-bottom: none; }
			.ib-pd-table tr:nth-child(even) td { background: var(--subtle-fg, #f8fafc); }
			.ib-pd-quick-actions {
				display: flex;
				gap: 12px;
				flex-wrap: wrap;
				margin-top: 8px;
			}
			.ib-pd-quick-btn {
				background: #d97757;
				color: #fff;
				border: none;
				border-radius: 8px;
				padding: 9px 20px;
				font-size: 13px;
				font-weight: 600;
				cursor: pointer;
				transition: background .15s;
			}
			.ib-pd-quick-btn:hover { background: #c4623e; }
			/* Power-user/export escape hatch (raw doctype list), not the
			   everyday path — visually secondary next to the primary orange
			   quick actions. */
			.ib-pd-quick-btn--minor {
				background: var(--card-bg, #fff);
				color: var(--text-muted, #6b7280);
				border: 1px solid var(--border-color, #e2e8f0);
				font-weight: 500;
				padding: 8px 16px;
			}
			.ib-pd-quick-btn--minor:hover {
				background: var(--subtle-fg, #f8fafc);
				color: var(--text-color, #1e293b);
			}
			.ib-pd-empty {
				padding: 24px;
				color: var(--text-muted, #6b7280);
				font-size: 13px;
				text-align: center;
			}
			.ib-pd-pager {
				display: flex; align-items: center; justify-content: center; gap: 12px;
				padding: 16px 0; font-size: 12px;
			}
			.ib-pd-pager .btn {
				display: inline-flex; align-items: center; gap: 4px;
				border-radius: 6px; font-size: 12px; font-weight: 600;
				transition: background .12s, opacity .12s;
			}
			.ib-pd-pager .btn:disabled { opacity: .4; cursor: not-allowed; }
			.ib-pd-plan-page-label { color: var(--text-muted, #6b7280); font-weight: 600; min-width: 50px; text-align: center; }
			.ib-pd-refresh-time {
				font-size: 11px;
				color: var(--text-muted, #6b7280);
				margin-right: 8px;
			}
			.ib-pd-plan-card {
				background: var(--card-bg, #fff);
				border: 1px solid var(--border-color, #eef1f5);
				border-radius: 14px;
				margin-bottom: 12px;
				overflow: hidden;
				box-shadow: 0 1px 2px rgba(15,23,42,.04);
				transition: box-shadow .18s, border-color .18s;
			}
			.ib-pd-plan-card:hover { box-shadow: 0 8px 20px rgba(15,23,42,.07); border-color: var(--border-color, #e2e8f0); }
			.ib-pd-plan-header {
				display: flex;
				align-items: flex-start;
				padding: 15px 18px;
				background: var(--card-bg, #fff);
				border-bottom: 1px solid var(--border-color, #f1f5f9);
				flex-wrap: wrap;
				row-gap: 8px;
				column-gap: 12px;
				cursor: pointer;
				transition: background .12s;
			}
			.ib-pd-plan-header:hover { background: var(--subtle-fg, #fafbfc); }
			.ib-pd-plan-start {
				display: flex;
				align-items: flex-start;
				gap: 10px;
				flex: 1 1 260px;
				min-width: 0;
				text-align: left;
			}
			.ib-pd-plan-chevron {
				flex-shrink: 0;
				margin-top: 2px;
				color: var(--text-muted, #6b7280);
				transition: transform .15s;
			}
			.ib-pd-plan-main {
				flex: 1 1 auto;
				min-width: 0;
				text-align: left;
			}
			.ib-pd-plan-title {
				display: flex;
				align-items: baseline;
				flex-wrap: wrap;
				gap: 6px;
				font-size: 13.5px;
				line-height: 1.4;
			}
			.ib-pd-plan-so-link {
				font-weight: 700;
				color: var(--ib-primary, #d97757);
				text-decoration: none;
				white-space: nowrap;
			}
			.ib-pd-plan-so-link:hover { text-decoration: underline; }
			.ib-pd-plan-customer {
				font-weight: 600;
				color: var(--text-color, #1e293b);
				overflow-wrap: anywhere;
			}
			.ib-pd-plan-subline {
				font-size: 11px;
				color: var(--text-muted, #6b7280);
				margin-top: 3px;
			}
			.ib-pd-plan-meta {
				display: flex;
				align-items: center;
				gap: 8px;
				flex-shrink: 0;
				margin-left: auto;
				padding-top: 1px;
			}
			.ib-pd-tag {
				display: inline-block;
				font-size: 9.5px;
				font-weight: 800;
				letter-spacing: .03em;
				border-radius: 4px;
				padding: 1px 5px;
				margin-right: 4px;
				vertical-align: middle;
			}
			.ib-pd-tag--so { background: #dbeafe; color: #1e3a8a; }
			.ib-pd-plan-comment-btn {
				display: inline-flex;
				align-items: center;
				justify-content: center;
				width: 22px;
				height: 22px;
				background: var(--card-bg, #fff);
				border: 1px solid var(--border-color, #e2e8f0);
				border-radius: 999px;
				color: var(--text-muted, #6b7280);
				cursor: pointer;
				transition: background .12s, border-color .12s, color .12s;
			}
			.ib-pd-plan-comment-btn:hover {
				background: var(--subtle-fg, #f8fafc);
				border-color: var(--ib-primary, #d97757);
				color: var(--ib-primary, #d97757);
			}
			.ib-pd-plan-comment-btn:disabled {
				opacity: .4;
				cursor: not-allowed;
			}
			.ib-pd-plan-comment-wrap {
				position: relative;
				display: inline-flex;
			}
			.ib-pd-plan-comment-count {
				position: absolute;
				top: -5px;
				right: -5px;
				min-width: 15px;
				height: 15px;
				line-height: 15px;
				padding: 0 3px;
				border-radius: 999px;
				background: var(--ib-primary, #d97757);
				color: #fff;
				font-size: 9.5px;
				font-weight: 700;
				text-align: center;
			}
			.ib-pd-plan-item { font-size: 12px; font-family: monospace; color: #1e293b; }
			.ib-pd-plan-item-name { font-size: 11px; color: var(--text-muted, #6b7280); margin-top: 2px; }
			.ib-pd-plan-all-done {
				display: flex;
				align-items: center;
				justify-content: space-between;
				gap: 10px;
				padding: 14px 16px;
				font-size: 12.5px;
				font-weight: 600;
				color: #059669;
				background: var(--card-bg, #fff);
			}
			.ib-pd-plan-all-done-label { display: flex; align-items: center; gap: 6px; }
			.ib-pd-plan-create-dn { flex-shrink: 0; }
			/* Shared item-row grid. .ib-pd-plan-columns (rendered once above the
			   whole list) and every .ib-pd-plan-row (one per item, across every
			   order card) use the exact same grid-template-columns — this is what
			   keeps columns pixel-aligned down the whole page, instead of each
			   order's own <table> auto-sizing its columns independently against
			   its own item codes/names. */
			.ib-pd-plan-columns,
			.ib-pd-plan-row {
				display: grid;
				grid-template-columns: minmax(200px, 2.4fr) 90px minmax(170px, 1.6fr) minmax(140px, 1.1fr) minmax(160px, auto);
				gap: 14px;
				align-items: center;
			}
			.ib-pd-plan-columns {
				padding: 6px 18px;
				margin-bottom: 8px;
				font-size: 10px;
				font-weight: 700;
				text-transform: uppercase;
				letter-spacing: .07em;
				color: var(--text-muted, #94a3b8);
			}
			/* Below ~760px the 5-column grid (min combined width ~850px) simply
			   ran off the right edge with no way back — Start/Next Stage/Finish,
			   the entire reason this list exists, were unreachable on any phone.
			   Confirmed live at 390px: only Item + a sliver of Stage stayed
			   visible, Progress/Actions entirely off-screen, no scroll affordance.
			   Stack every cell full-width instead; the header row (meaningless
			   once nothing lines up in columns any more) is hidden in favor of
			   small inline labels on the cells that aren't self-evident alone. */
			@media (max-width: 760px) {
				.ib-pd-plan-columns { display: none; }
				.ib-pd-plan-row {
					grid-template-columns: 1fr;
					gap: 8px;
					padding: 14px 16px;
				}
				.ib-pd-plan-row-qty::before {
					display: block;
					font-size: 9.5px;
					font-weight: 700;
					text-transform: uppercase;
					letter-spacing: .06em;
					color: var(--text-muted, #94a3b8);
					margin-bottom: 2px;
					content: "Qty";
				}
				.ib-pd-plan-row-progress { margin: 2px 0; }
				.ib-pd-row-actions { justify-content: flex-start; }
				.ib-pd-row-actions .ib-pd-row-btn { flex: 1 1 auto; min-width: 120px; }
			}
			.ib-pd-plan-row {
				padding: 13px 18px;
				background: var(--card-bg, #fff);
				border-top: 1px solid var(--border-color, #f4f6f8);
				transition: background .12s;
			}
			.ib-pd-plan-row:first-child { border-top: none; }
			.ib-pd-plan-row:hover { background: color-mix(in srgb, var(--ib-primary, #d97757) 4%, var(--card-bg, #fff)); }
			.ib-pd-plan-row-cell { min-width: 0; }
			.ib-pd-plan-row-qty { font-size: 12.5px; font-weight: 600; color: var(--text-color, #1e293b); font-variant-numeric: tabular-nums; }
			.ib-pd-plan-row-uom {
				font-size: 10px; font-weight: 600; text-transform: uppercase;
				color: var(--text-muted, #94a3b8); margin-left: 2px;
			}
			.ib-pd-plan-row-adj {
				font-size: 9.5px; font-weight: 700; white-space: nowrap;
				color: #c2410c; margin-top: 3px; letter-spacing: .02em;
			}
			.ib-pd-plan-row-stage-label {
				font-size: 12px; font-weight: 600; color: var(--text-color, #1e293b);
				margin-bottom: 6px;
			}
			.ib-pd-live-pulse {
				vertical-align: middle;
				margin-left: 5px;
				overflow: visible;
			}
			.ib-pd-live-pulse-dot {
				fill: #10b981;
			}
			.ib-pd-live-pulse-ring {
				fill: none;
				stroke: #10b981;
				stroke-width: 1.5;
				transform-origin: 6px 6px;
				animation: ib-pd-pulse-ring 1.8s ease-out infinite;
			}
			@keyframes ib-pd-pulse-ring {
				0%   { transform: scale(.45); opacity: .9; }
				70%  { transform: scale(1.4); opacity: 0; }
				100% { transform: scale(1.4); opacity: 0; }
			}
			@media (prefers-reduced-motion: reduce) {
				.ib-pd-live-pulse-ring { animation: none; opacity: .35; }
			}
			.ib-pd-stg-pills { display: flex; gap: 4px; flex-wrap: wrap; }
			.ib-pd-stg-chip {
				font-size: 9.5px;
				font-weight: 700;
				border-radius: 20px;
				padding: 2.5px 8px;
				letter-spacing: .03em;
				cursor: default;
			}
			.ib-pd-stg--done    { background: #dcfce7; color: #15803d; }
			.ib-pd-stg--inprog  { background: #dbeafe; color: #1d4ed8; }
			.ib-pd-stg--pending { background: var(--subtle-fg, #f1f5f9); color: #94a3b8; }
			/* Genuinely running right now — a soft pulse so "In Progress" reads
			   as actively moving, not just a static blue label sitting next to
			   a green "done" one. */
			.ib-pd-stg--live { animation: ib-pd-stg-pulse 1.6s ease-in-out infinite; }
			@keyframes ib-pd-stg-pulse {
				0%, 100% { box-shadow: 0 0 0 0 rgba(29, 78, 216, 0.35); }
				50%      { box-shadow: 0 0 0 4px rgba(29, 78, 216, 0); }
			}
			@media (prefers-reduced-motion: reduce) {
				.ib-pd-stg--live { animation: none; }
			}
			.ib-pd-plan-row-progress { display: flex; align-items: center; gap: 9px; }
			.ib-pd-prog-bar-wrap {
				height: 6px;
				background: var(--subtle-fg, #eef1f5);
				border-radius: 20px;
				overflow: hidden;
				flex: 1 1 auto;
				min-width: 40px;
			}
			.ib-pd-prog-bar {
				height: 100%;
				background: linear-gradient(90deg, #059669, #10b981);
				border-radius: 20px;
				transition: width .3s;
			}
			.ib-pd-prog-pct {
				font-size: 11px; font-weight: 600; color: var(--text-muted, #64748b);
				flex-shrink: 0; min-width: 30px; text-align: right; font-variant-numeric: tabular-nums;
			}
			.ib-pd-row-actions {
				display: flex;
				align-items: center;
				gap: 5px;
				flex-wrap: wrap;
			}
			.ib-pd-row-select {
				display: inline-flex;
				align-items: center;
				margin: 0;
				cursor: pointer;
			}
			.ib-pd-row-select input { cursor: pointer; margin: 0; }
			.ib-pd-row-btn {
				background: var(--card-bg, #fff);
				border: 1px solid var(--border-color, #e2e8f0);
				border-radius: 20px;
				padding: 4px 12px;
				font-size: 11px;
				font-weight: 600;
				color: var(--text-color, #1e293b);
				cursor: pointer;
				transition: background .12s, border-color .12s, box-shadow .12s;
			}
			.ib-pd-row-btn:hover { background: var(--subtle-fg, #f8fafc); border-color: var(--ib-primary, #d97757); }
			.ib-pd-row-btn--primary {
				background: var(--ib-primary, #d97757);
				border-color: var(--ib-primary, #d97757);
				color: #fff;
				box-shadow: 0 1px 2px rgba(217,119,87,.25);
			}
			.ib-pd-row-btn--primary:hover { background: #c4623e; border-color: #c4623e; box-shadow: 0 2px 6px rgba(217,119,87,.35); }
			.ib-pd-row-done {
				display: inline-flex;
				align-items: center;
				gap: 4px;
				font-size: 11px;
				font-weight: 600;
				color: #15803d;
				background: #dcfce7;
				border-radius: 20px;
				padding: 4px 10px;
			}
			@media (max-width: 640px) {
				.ib-pd-plan-header { flex-direction: column; align-items: stretch; }
				/* .ib-pd-plan-start's "flex: 1 1 260px" sets a 260px flex-BASIS —
				   fine as a min WIDTH in the normal row layout, but once
				   flex-direction flips to column that same 260px basis applies
				   to HEIGHT instead, forcing a ~260px-tall box regardless of the
				   real (much shorter) content and leaving a dead gap before the
				   priority/date badges below it. Confirmed live at 390px on 2
				   real order cards. Reset to auto so it sizes to its content. */
				.ib-pd-plan-start { flex-basis: auto; }
				.ib-pd-plan-meta { margin-left: 0; }
				.ib-pd-filter-group--search { max-width: none; flex-basis: 100%; }
			}
		`;
		document.head.appendChild(style);
	}
}


/* ─── Stages tab (ex ib_production_stages.js's IBProductionStages) ──────── */
// ---------------------------------------------------------------------------
// Stage definitions
// ---------------------------------------------------------------------------
// RTD/Delivered collapsed out of the stage model entirely (2026-08-13, user's
// explicit decision) — Packing is the real last Work Order stage now; nothing
// is physically manufactured at "Ready to Deliver", it was a manual click
// with no work behind it. "Ready to Deliver" is now just what a
// Completed-through-Packing item IS (Create Delivery Note becomes
// available); "Delivered" is derived from the Delivery Note being submitted
// (mark_wos_delivered/_get_dispatch_info in production.py) rather than a
// stage anyone starts/completes.
const IB_STAGES = [
	{ key: "coating",   label: "Coating",   icon: "layers",     color: "#7c3aed" },
	{ key: "slitting",  label: "Slitting",  icon: "scissors",   color: "#2563eb" },
	{ key: "rewinding", label: "Rewinding", icon: "refresh-cw", color: "#0891b2" },
	{ key: "cutting",   label: "Cutting",   icon: "crop",       color: "#059669" },
	{ key: "packing",   label: "Packing",   icon: "package",    color: "#d97706" },
];
const STAGE_ICON_BY_LABEL = Object.fromEntries(IB_STAGES.map((s) => [s.label, s.icon]));

// Small inline icon for a stage-chip label — direct ask: "use icons with
// stages to indicate the stages." Reuses IB_STAGES' own icon (already
// defined for the stage picker) rather than inventing a second icon set.
function _stage_chip_icon(stageLabel) {
	const icon = STAGE_ICON_BY_LABEL[stageLabel];
	if (!icon) return "";
	return `<iconify-icon icon="lucide:${icon}" width="10" height="10" style="vertical-align:-1px;margin-right:3px"></iconify-icon>`;
}

// Mirrors production.py's _STAGE_MACHINE_TYPE exactly.
const STAGE_MACHINE_TYPE = {
	"Coating": "Coating", "Slitting": "Slitting", "Rewinding": "Rewinding",
	"Cutting": "Cutting", "Packing": "Packing",
};

// Frappe's own indicator-pill color words (frappe/public/scss/common/indicator.scss)
// — theme-aware via --bg-{color}/--text-on-{color} CSS vars, unlike the hardcoded
// hex this page used to carry in 3 separate places (JS meta, a dead :root block,
// and ~15 CSS blocks). Priority and Work Order status both reuse this single
// mapping so the same word always means the same color everywhere on this page.
const IB_PRIORITY_META = {
	Urgent: { color: "red", label: "Urgent" },
	High: { color: "orange", label: "High" },
	Normal: { color: "blue", label: "Normal" },
	Low: { color: "gray", label: "Low" },
};

const IB_STATUS_COLOR = {
	"Pending": "gray",
	"In Progress": "blue",
	"Completed": "green",
	"On Hold": "orange",
	"Cancelled": "red",
};

function _ib_status_color(text) {
	return IB_STATUS_COLOR[text] || IB_PRIORITY_META[text]?.color || "gray";
}

/* Renders a Frappe-native indicator-pill for any status/priority word above.
   `size` "sm" applies this page's own compact density override (Frappe's
   default pill is roomy — 20px tall — too large for a table cell packed with
   several per row); omit for the default Frappe size. */
function _ib_status_pill(text, size) {
	const cls = size === "sm" ? "indicator-pill ib-ps-pill-sm" : "indicator-pill";
	return `<span class="${cls} ${_ib_status_color(text)}">${frappe.utils.escape_html(text || "")}</span>`;
}

// ---------------------------------------------------------------------------
// Main class
// ---------------------------------------------------------------------------
class IBProductionStages {
	constructor(page, $container) {
		this.page = page;
		this.$body = $container;

		// State
		this.active_tab = "order_wise";
		this.os_status_filter = "All";
		this.os_priority_filter = "All";
		this.os_search = "";
		this.location_filter = localStorage.getItem("ib_prod_location") || "";
		// Floor only exists on Machine-wise — IB Machine carries `floor`
		// directly (no join needed), and Gujarat is the only location with
		// real floors configured today (item 145). Cleared whenever location
		// isn't gujarat so a stale floor value can't silently scope a tab
		// that has no floor concept.
		this.floor_filter = this.location_filter === "gujarat"
			? (localStorage.getItem("ib_prod_floor") || "") : "";
		this.current_os = null;
		this.active_wo = null;
		this.machines_cache = null;
		this.item_wise_search = "";
		this.stage_wise_search = "";
		// Selected stage pill for the Stage-wise tab — defaults to Coating,
		// overridden by a route deep-link's ?stage= (see _route_stage_filter
		// below, shared with Item-wise's existing stage highlight).
		this.stage_wise_pill = "coating";
		this.stage_wise_cache = null;
		// Selected machine pill + search for the redesigned Machine-wise tab —
		// same picker+search+full-table shape as Stage-wise, chosen so the two
		// "pick one thing, see everything queued for it" tabs behave the same
		// way instead of Machine-wise's previous card-grid-with-4-WO-preview.
		this.machine_wise_pill = null;
		this.machine_wise_search = "";
		// Client-side stage highlight for the Item-wise tab, set via
		// frappe.route_options.stage (e.g. a Dashboard pipeline card deep-link).
		this._route_stage_filter = null;
		// Client-side WO-status filter for the Item-wise tab, set via
		// frappe.route_options.status when landing here from a Dashboard KPI
		// card (Active Work Orders / Pending) — Item-wise is WO-grain and spans
		// every Order Sheet, unlike Order-wise's Order-Sheet-grain status. Value
		// is either a single status string ("Pending") or an array of statuses
		// to match any-of (["Pending","In Progress","On Hold"] for "Active").
		this._route_status_filter = null;

		// Data stores — avoids JSON.stringify in data attributes
		this._wo_data = new Map();
		this._machine_data = new Map();
		this._sortables = [];

		// Consume frappe.route_options (standard Frappe convention — a caller
		// sets it right before frappe.set_route(), we read + clear it here so a
		// later plain navigation to this page doesn't replay stale filters).
		this._consume_route_options();

		this._inject_styles();
		this._build_shell();
		// _build_shell() hardcodes "Order-wise" as the active toolbar tab and
		// sets the location select from whatever _consume_route_options() just
		// applied — re-sync here in case route options picked something else.
		this._sync_route_ui();
		this.refresh();
		this._start_live_updates();
	}

	// Re-applies active_tab/location_filter to the toolbar DOM. Needed both
	// right after the constructor's _build_shell() and on every later
	// on_page_show — the page instance persists across navigations (only the
	// constructor calls _build_shell()), so a second/third click on a
	// Dashboard KPI/Pipeline card was setting frappe.route_options correctly
	// but the already-existing page silently ignored it: _consume_route_options()
	// only ran once, in the constructor, so it never fired again on repeat visits.
	_sync_route_ui() {
		this.$body.find(".ib-ps-tab").removeClass("active");
		this.$body.find(`.ib-ps-tab[data-tab="${this.active_tab}"]`).addClass("active");
		this.$body.find("#ib-ps-location").val(this.location_filter);
		this._sync_floor_ui();
	}

	_consume_route_options() {
		const ro = frappe.route_options;
		if (!ro) return;

		const VALID_TABS = ["order_wise", "item_wise", "machine_wise", "stage_wise"];
		if (ro.tab && VALID_TABS.includes(ro.tab)) {
			this.active_tab = ro.tab;
			delete ro.tab;
		}
		if (ro.location !== undefined) {
			this.location_filter = ro.location || "";
			localStorage.setItem("ib_prod_location", this.location_filter);
			delete ro.location;
		}
		if (ro.status !== undefined && this.active_tab === "order_wise") {
			this.os_status_filter = ro.status;
			delete ro.status;
		} else if (ro.status !== undefined && this.active_tab === "item_wise") {
			// WO-grain status filter — see this._route_status_filter above.
			this._route_status_filter = ro.status;
			delete ro.status;
		}
		if (ro.stage) {
			this._route_stage_filter = ro.stage;
			delete ro.stage;
		}

		// Anything left unconsumed here isn't ours — leave it for whoever set
		// it. Only null out the whole object once we've taken everything.
		if (Object.keys(ro).length === 0) frappe.route_options = null;
	}

	// Server already publishes "ib_floor_update" (production.py _notify_floor_update)
	// on every Start/Advance/Hold/Complete — nothing client-side was listening,
	// so multi-terminal floor use required a manual Refresh click to see any
	// other station's progress. Debounced (1.5s) + route-checked, matching the
	// established pattern in ib_stock_common.js's make_live().
	_start_live_updates() {
		frappe.realtime.off("ib_floor_update");
		let timer = null;
		frappe.realtime.on("ib_floor_update", () => {
			// No route/tab check needed here (unlike the old standalone-page
			// version of this guard, which checked frappe.get_route()[0] ===
			// "ib-production-stages" — a route that no longer exists post-merge
			// and would have made this handler silently dead forever). This
			// instance only exists at all while the Stages tab is the active
			// one; IBProductionShell tears it down (see _cleanup(), which also
			// unbinds this exact handler) the moment the outer tab switches
			// away, so there's no "wrong tab" state in which this callback
			// could fire against a hidden view.
			if (this.active_wo) return;
			clearTimeout(timer);
			timer = setTimeout(() => this.refresh(), 1500);
		});
	}

	// Called by IBProductionShell._teardown_active() whenever the outer tab
	// switches away from Stages (and on page hide) — this class is torn down
	// and freshly reconstructed on every "Stages" tab activation now that it
	// lives inside a shell (destroy-and-rebuild lifecycle, same as Item
	// Pricing / Stock / Customer Board), so any listener bound outside its own
	// $body scope must be explicitly released here or it leaks a duplicate on
	// the next activation — this exact bug class (leaked realtime subscription
	// on repeated tab-switching) is why this method exists.
	_cleanup() {
		frappe.realtime.off("ib_floor_update");
		if (this._key_handler) {
			document.removeEventListener("keydown", this._key_handler);
			this._key_handler = null;
		}
		if (this._sortables) {
			this._sortables.forEach((s) => s.destroy && s.destroy());
			this._sortables = [];
		}
		this._close_side_panel();
	}

	// -----------------------------------------------------------------------
	// Shell / toolbar
	// -----------------------------------------------------------------------
	// The page-level "Production Dashboard" cross-nav primary action that used
	// to live here was retired 2026-08-05 when the two pages merged into tabs
	// of one page (IBProductionShell) — the outer tab bar is now the obvious
	// way back, so this class no longer touches page-level toolbar chrome at
	// all.
	_build_shell() {
		// Toolbar tabs
		const tabs_html = `
			<div class="ib-ps-tabs">
				<button class="ib-ps-tab active" data-tab="order_wise">
					<iconify-icon icon="lucide:clipboard-list" width="12" height="12" style="vertical-align:middle;margin-right:4px"></iconify-icon>
					Order-wise
				</button>
				<button class="ib-ps-tab" data-tab="item_wise">
					<iconify-icon icon="lucide:box" width="12" height="12" style="vertical-align:middle;margin-right:4px"></iconify-icon>
					Item-wise
				</button>
				<button class="ib-ps-tab" data-tab="stage_wise">
					<iconify-icon icon="lucide:git-branch" width="12" height="12" style="vertical-align:middle;margin-right:4px"></iconify-icon>
					Stage-wise
				</button>
				<button class="ib-ps-tab" data-tab="machine_wise">
					<iconify-icon icon="lucide:settings-2" width="12" height="12" style="vertical-align:middle;margin-right:4px"></iconify-icon>
					Machine-wise
				</button>
				<span style="flex:1"></span>
				<div class="ib-ps-loc-group">
					<iconify-icon icon="lucide:map-pin" width="12" height="12" style="color:var(--text-muted)"></iconify-icon>
					<select id="ib-ps-location" class="ib-ps-select form-control">
						<option value="">All Locations</option>
						<option value="gujarat">Gujarat (Factory)</option>
						<option value="maharashtra">Maharashtra (Warehouse)</option>
						<option value="chennai">Chennai (Warehouse)</option>
					</select>
				</div>
				<div class="ib-ps-loc-group" id="ib-ps-floor-group" style="display:none">
					<iconify-icon icon="lucide:layers" width="12" height="12" style="color:var(--text-muted)"></iconify-icon>
					<select id="ib-ps-floor" class="ib-ps-select form-control">
						<option value="">All Floors</option>
					</select>
				</div>
				<button class="ib-ps-refresh-btn" id="ib-ps-refresh">
					<iconify-icon icon="lucide:refresh-cw" width="13" height="13" style="vertical-align:middle;margin-right:4px"></iconify-icon>
					Refresh
				</button>
			</div>`;

		this.$body.html(`
			${tabs_html}
			<div class="ib-ps-content" id="ib-ps-content"></div>
		`);

		this.$body.find("#ib-ps-location").val(this.location_filter);
		this._sync_floor_ui();

		// Tab clicks
		this.$body.on("click", ".ib-ps-tab", (e) => {
			const tab = $(e.currentTarget).data("tab");
			this._switch_tab(tab);
		});

		this.$body.on("change", "#ib-ps-location", (e) => {
			this.location_filter = $(e.target).val();
			localStorage.setItem("ib_prod_location", this.location_filter);
			// A floor picked for one location makes no sense once location
			// changes away from gujarat (the only location with real floors).
			this.floor_filter = "";
			localStorage.removeItem("ib_prod_floor");
			this.current_os = null;
			this._sync_floor_ui();
			this.refresh();
		});

		this.$body.on("change", "#ib-ps-floor", (e) => {
			this.floor_filter = $(e.target).val();
			localStorage.setItem("ib_prod_floor", this.floor_filter);
			this.refresh();
		});

		this.$body.on("click", "#ib-ps-refresh", () => this.refresh());

		// WO panel close/Escape are handled natively by frappe.ui.Dialog now
		// (backdrop click, Escape key, and the header's own close button all
		// come from Dialog itself). Only the "R = refresh" shortcut is still
		// ours to wire.
		this._key_handler = (e) => {
			const tag = (e.target || {}).tagName || "";
			if (e.key === "r" && !e.ctrlKey && !e.metaKey && !["INPUT","TEXTAREA","SELECT"].includes(tag)) {
				this.refresh();
			}
		};
		document.addEventListener("keydown", this._key_handler);
	}

	_switch_tab(tab) {
		this.active_tab = tab;
		this.current_os = null;
		// A stage/status deep-link only makes sense on the tab it landed on — a
		// manual switch away means the user is done with that scoped view.
		if (tab !== "item_wise") {
			this._route_stage_filter = null;
			this._route_status_filter = null;
		}
		this.$body.find(".ib-ps-tab").removeClass("active");
		this.$body.find(`.ib-ps-tab[data-tab="${tab}"]`).addClass("active");
		this._close_side_panel();
		this._sync_floor_ui();
		this.refresh();
	}

	// Floor is only a meaningful filter on Machine-wise (IB Machine carries
	// `floor` directly, no join needed) at Gujarat (the only location with
	// real floors configured — item 145). Hidden everywhere else rather than
	// shown-but-inert, so it never implies scoping a tab it doesn't affect.
	_sync_floor_ui() {
		const $group = this.$body.find("#ib-ps-floor-group");
		const show = this.active_tab === "machine_wise" && this.location_filter === "gujarat";
		$group.toggle(show);
		if (!show) return;
		const $sel = this.$body.find("#ib-ps-floor");
		if ($sel.data("ib-loaded")) {
			$sel.val(this.floor_filter);
			return;
		}
		frappe.call({
			method: "frappe.client.get_list",
			args: {
				doctype: "IB Production Floor",
				filters: { location: "gujarat", is_active: 1 },
				fields: ["name", "floor_name"],
				order_by: "floor_name asc",
				limit_page_length: 0,
			},
			callback: (r) => {
				const floors = r.message || [];
				$sel.find("option:not(:first)").remove();
				floors.forEach((f) => {
					$sel.append(`<option value="${frappe.utils.escape_html(f.name)}">${frappe.utils.escape_html(f.floor_name || f.name)}</option>`);
				});
				$sel.data("ib-loaded", true);
				$sel.val(this.floor_filter);
			},
		});
	}

	refresh() {
		if (this.active_tab === "item_wise") {
			this._load_item_wise();
		} else if (this.active_tab === "order_wise") {
			if (this.current_os) {
				this._load_os_detail(this.current_os);
			} else {
				this._load_order_sheets();
			}
		} else if (this.active_tab === "machine_wise") {
			this._load_machine_wise();
		} else if (this.active_tab === "stage_wise") {
			this._load_stage_wise();
		}
	}

	_content() {
		return this.$body.find("#ib-ps-content");
	}

	// -----------------------------------------------------------------------
	// TAB 2 — Item-wise view
	// -----------------------------------------------------------------------
	_load_item_wise() {
		const $c = this._content();
		$c.html('<div class="ib-ps-loading">Loading item view…</div>');
		// Bumped here, not only in refresh() — this loader is also called
		// directly (pagination, filter changes) bypassing refresh(), so it
		// must be able to invalidate its own in-flight predecessor too.
		const gen = (this._load_gen = (this._load_gen || 0) + 1);
		frappe.call({
			method: "instabiz.overrides.production.get_item_wise_view",
			args: { location: this.location_filter || null },
			callback: (r) => {
				if (gen !== this._load_gen) return; // stale — a newer refresh() already superseded this
				if (r.exc) {
					$c.html('<div class="ib-ps-empty">Failed to load item view.</div>');
					return;
				}
				this._render_item_wise(r.message || []);
			},
		});
	}

	_render_item_wise(items, page) {
		const $c = this._content();
		this._item_wise_all = items = items || this._item_wise_all || [];
		this._item_wise_expanded = this._item_wise_expanded || new Set();
		if (!items.length) {
			$c.html('<div class="ib-ps-empty">No active production items found.</div>');
			return;
		}

		// Deep-link stage highlight (e.g. from a Dashboard pipeline card) — an
		// item matches if it has a not-yet-completed Work Order at that stage.
		let stage_scoped = items;
		if (this._route_stage_filter) {
			stage_scoped = items.filter((it) => (it.work_orders || []).some(
				(wo) => wo.stage === this._route_stage_filter && wo.status !== "Completed" && wo.status !== "Cancelled"
			));
		}

		// Deep-link WO-status filter (e.g. Dashboard "Active Work Orders" /
		// "Pending" KPI cards) — an item matches if it has at least one Work
		// Order whose status is in the requested set. This is the WO-grain
		// counterpart to the stage filter above; unlike Order-wise's status
		// filter (which is Order-Sheet-grain), this reads IB Work Order.status
		// directly, matching what the KPI cards themselves count.
		if (this._route_status_filter) {
			const wanted = this._route_status_filter;
			const matches_status = (s) => Array.isArray(wanted) ? wanted.includes(s) : s === wanted;
			stage_scoped = stage_scoped.filter((it) => (it.work_orders || []).some((wo) => matches_status(wo.status)));
		}

		// Search matches item code/name AND any customer this item is currently
		// being produced for — a plain item_code-only search couldn't answer
		// "which of my orders has item X" when the same item appears on
		// several unrelated Sales Orders. _customer_blob is computed once per
		// item (cached on the object) since it doesn't change between
		// re-renders of the same underlying data.
		stage_scoped.forEach((it) => {
			if (it._customer_blob === undefined) {
				it._customer_blob = [...new Set((it.work_orders || []).map((w) => w.customer_name).filter(Boolean))].join(" ");
			}
		});
		const filtered = window.ib_multi_token_filter(stage_scoped, ["item_code", "item_name", "_customer_blob"], this.item_wise_search);

		const PAGE_SIZE = 25;
		const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
		this._item_wise_page = page || this._item_wise_page || 1;
		if (this._item_wise_page > totalPages) this._item_wise_page = totalPages;
		const start = (this._item_wise_page - 1) * PAGE_SIZE;
		const pageItems = filtered.slice(start, start + PAGE_SIZE);

		// Multi-value status filter (e.g. ["Pending","In Progress","On Hold"] for
		// a Dashboard "Active Work Orders" KPI deep-link) can't be represented
		// as one <select> value — keep it as a clear-only badge; a plain single
		// status is fully representable, so it drives the dropdown below like
		// the stage filter does.
		const status_is_multi = Array.isArray(this._route_status_filter);
		const status_multi_pill = status_is_multi ? `
			<span class="ib-ps-stat-pill ib-ps-stage-filter-pill">
				Status: ${frappe.utils.escape_html(this._route_status_filter.join(" / "))}
				<button type="button" class="ib-ps-status-filter-clear" title="Clear status filter">×</button>
			</span>` : "";

		const toolbar = `
			<div class="ib-ps-os-toolbar" style="margin-bottom:12px">
				<input class="ib-ps-search-input form-control" id="ib-iw-search" placeholder="Search item code, item name, or customer…" value="${frappe.utils.escape_html(this.item_wise_search || "")}">
				<select id="ib-iw-stage-filter" class="ib-ps-select">
					<option value="">All Stages</option>
					${IB_STAGES.map((s) => `<option value="${s.label}" ${this._route_stage_filter === s.label ? "selected" : ""}>${s.label}</option>`).join("")}
				</select>
				${!status_is_multi ? `
				<select id="ib-iw-status-filter" class="ib-ps-select">
					<option value="">All Statuses</option>
					${["Pending", "In Progress", "Completed", "On Hold", "Cancelled"].map((s) => `<option value="${s}" ${this._route_status_filter === s ? "selected" : ""}>${s}</option>`).join("")}
				</select>` : ""}
				<span class="ib-ps-stat-pill">${filtered.length} items</span>
				${status_multi_pill}
			</div>`;

		const rows = pageItems.map((item) => this._item_wise_row(item)).join("");
		const pager = totalPages > 1 ? `
			<div style="display:flex;align-items:center;justify-content:center;gap:10px;margin-top:16px">
				<button class="btn btn-default btn-xs ib-iw-prev" ${this._item_wise_page <= 1 ? "disabled" : ""}>Prev</button>
				<span style="font-size:12px;color:var(--text-muted)">Page ${this._item_wise_page} of ${totalPages}</span>
				<button class="btn btn-default btn-xs ib-iw-next" ${this._item_wise_page >= totalPages ? "disabled" : ""}>Next</button>
			</div>` : "";
		$c.html(toolbar + `<div class="ib-iw-list" id="ib-iw-list">${rows}</div>${pager}`);
		$c.off();

		$c.on("change", "#ib-iw-stage-filter", (e) => {
			this._route_stage_filter = e.target.value || null;
			this._render_item_wise(this._item_wise_all, 1);
		});

		$c.on("change", "#ib-iw-status-filter", (e) => {
			this._route_status_filter = e.target.value || null;
			this._render_item_wise(this._item_wise_all, 1);
		});

		$c.on("click", ".ib-ps-status-filter-clear", () => {
			this._route_status_filter = null;
			this._render_item_wise(this._item_wise_all, 1);
		});

		$c.on("input", "#ib-iw-search", (e) => {
			this.item_wise_search = $(e.target).val();
			const cursorPos = e.target.selectionStart;
			this._render_item_wise(this._item_wise_all, 1);
			const $input = $c.find("#ib-iw-search").get(0);
			if ($input) {
				$input.focus();
				$input.setSelectionRange(cursorPos, cursorPos);
			}
		});

		$c.on("click", ".ib-iw-prev", () => this._render_item_wise(this._item_wise_all, this._item_wise_page - 1));
		$c.on("click", ".ib-iw-next", () => this._render_item_wise(this._item_wise_all, this._item_wise_page + 1));

		// Collapse/expand toggle — click anywhere on the row header. Tracked in
		// a Set (not just a DOM class) so the expanded state survives a
		// re-render (search/filter/page change), matching the Active
		// Production Plan card's own "stay open across refresh" pattern.
		$c.on("click", ".ib-iw-row-header", (e) => {
			const ic = $(e.currentTarget).closest(".ib-iw-row").data("item");
			if (this._item_wise_expanded.has(ic)) this._item_wise_expanded.delete(ic);
			else this._item_wise_expanded.add(ic);
			this._render_item_wise(this._item_wise_all, this._item_wise_page);
		});

		// Clicking a WO chip inside an expanded row's customer breakdown opens
		// the same WO detail dialog every other tab on this page uses.
		$c.off("click", ".ib-ps-wo-chip").on("click", ".ib-ps-wo-chip", (e) => {
			const woid = $(e.currentTarget).data("woid");
			const wo = this._wo_data.get(woid);
			if (wo) this._open_wo_panel(wo, IB_STAGES.find((s) => s.label === wo.stage)?.key || "");
		});
	}

	// One collapsible row per item. Collapsed: item identity + how many
	// orders/customers it's currently spread across + overall stage/progress.
	// Expanded: every order carrying this item, grouped by Sales Order, with
	// that order's customer name and per-stage Work Order chips — answers
	// "which of my orders has item X, and where is each one" in one place,
	// instead of the old flat cross-order stage table that mixed every
	// order's Work Orders for this item into one undifferentiated list.
	_item_wise_row(item) {
		const ic = item.item_code;
		const expanded = this._item_wise_expanded.has(ic);
		const pct = item.completion_pct || 0;

		const by_so = {};
		(item.work_orders || []).forEach((wo) => {
			this._wo_data.set(wo.name, wo);
			const key = wo.order_sheet || wo.sales_order || "unknown";
			if (!by_so[key]) {
				by_so[key] = {
					order_sheet: wo.order_sheet, sales_order: wo.sales_order,
					customer_name: wo.customer_name, delivery_date: wo.delivery_date,
					wos: [],
				};
			}
			by_so[key].wos.push(wo);
		});
		const so_groups = Object.values(by_so).sort((a, b) => (a.delivery_date || "9999") < (b.delivery_date || "9999") ? -1 : 1);
		const order_count = so_groups.length;
		const customer_count = new Set(so_groups.map((g) => g.customer_name).filter(Boolean)).size;
		const order_label = order_count === 1 ? "1 order" : `${order_count} orders`;
		const customer_label = customer_count && customer_count !== order_count ? ` · ${customer_count} customers` : "";

		// Total quantity across every order carrying this item, grouped by UOM
		// (almost always one UOM in practice, but an item can theoretically be
		// sold in more than one unit across different orders — summed
		// separately per UOM rather than adding incompatible units together).
		// Each SO-group's qty/uom come from its first WO — every WO in a group
		// is the same order line at a different stage, so they share one qty.
		const totals_by_uom = {};
		so_groups.forEach((g) => {
			const first = g.wos[0] || {};
			const q = first.target_qty || 0;
			const u = first.target_uom || "";
			if (!q) return;
			totals_by_uom[u] = (totals_by_uom[u] || 0) + q;
		});
		const totals_label = Object.entries(totals_by_uom)
			.map(([u, q]) => `${q % 1 === 0 ? q : q.toFixed(2)}${u ? ` ${u}` : ""}`)
			.join(" + ");

		let body = "";
		if (expanded) {
			body = so_groups.map((g) => {
				const chips = g.wos.map((wo) => {
					// Full stage name, not the CT/SL/RW/CU/PK abbreviation — direct
					// ask: "make sure user knows which stage they are looking at"
					// without having to hover for the tooltip.
					const stageLabel = frappe.utils.escape_html(wo.stage || "—");
					const cancelled_cls = wo.status === "Cancelled" ? " ib-ps-wo-chip--cancelled" : "";
					// Pulses while genuinely running — direct ask: "animate the
					// stage in progress badge (blue) to indicate progression."
					const live_cls = wo.status === "In Progress" ? " ib-ps-wo-chip--live" : "";
					const title = `${wo.stage}: ${wo.name} — ${wo.status} (${wo.completed_qty || 0}/${wo.target_qty || 0})`;
					return `<span class="ib-ps-wo-chip indicator-pill ib-ps-pill-sm ${_ib_status_color(wo.status)}${cancelled_cls}${live_cls}" data-woid="${frappe.utils.escape_html(wo.name)}" title="${frappe.utils.escape_html(title)}">${_stage_chip_icon(wo.stage)}${stageLabel}</span>`;
				}).join("");
				const so_link = g.sales_order
					? `<a href="/app/sales-order/${encodeURIComponent(g.sales_order)}" target="_blank" class="ib-iw-so-link">${frappe.utils.escape_html(g.sales_order)}</a>`
					: `<span class="ib-iw-so-link">—</span>`;
				// Every WO in this group is a different stage of the SAME item on
				// the SAME order — qty is identical across all of them, and the
				// earliest creation timestamp is effectively "when this line was
				// put into production" (the first stage WO created for it).
				const qty = g.wos.reduce((v, wo) => v || wo.target_qty, 0) || 0;
				const qtyUom = (g.wos.find((wo) => wo.target_uom) || {}).target_uom || "";
				const earliest = g.wos.reduce((min, wo) => (!min || (wo.creation && wo.creation < min)) ? wo.creation : min, null);
				return `
					<div class="ib-iw-so-group">
						<div class="ib-iw-so-head">
							<div class="ib-iw-so-main">
								<div class="ib-iw-so-title">
									<span class="ib-ps-tag ib-ps-tag--so">SO</span>
									${so_link}
									<span class="ib-iw-so-customer">${frappe.utils.escape_html(g.customer_name || "—")}</span>
								</div>
								<div class="ib-iw-so-sub">${qty ? `Qty ${qty}${qtyUom ? ` ${qtyUom}` : ""}` : ""}${earliest ? `${qty ? " · " : ""}Created ${frappe.datetime.str_to_user(earliest)}` : ""}</div>
							</div>
							<div class="ib-iw-so-side">${_etd_badge(g.delivery_date)}</div>
						</div>
						<div class="ib-iw-so-chips">${chips}</div>
					</div>`;
			}).join("");
		}

		return `
			<div class="ib-iw-row" data-item="${frappe.utils.escape_html(ic)}">
				<div class="ib-iw-row-header">
					<iconify-icon icon="lucide:chevron-right" width="14" height="14" class="ib-iw-row-chevron" style="${expanded ? "transform:rotate(90deg)" : ""}"></iconify-icon>
					<div class="ib-iw-row-main">
						<div class="ib-iw-row-title">
							<strong class="ib-ps-item-code">${frappe.utils.escape_html(ic)}</strong>
							<span class="ib-iw-row-name">${frappe.utils.escape_html(item.item_name || "")}</span>
						</div>
						<div class="ib-iw-row-sub">${totals_label ? `${totals_label} · ` : ""}${order_label}${customer_label} · ${item.completed_wos}/${item.total_wos} stages complete</div>
					</div>
					<div class="ib-iw-row-progress">
						<div class="ib-ps-progress-wrap" style="width:90px"><div class="ib-ps-progress-bar" style="width:${pct}%;background:var(--ib-primary)"></div></div>
						<span class="ib-iw-row-pct">${pct}%</span>
					</div>
				</div>
				${expanded ? `<div class="ib-iw-row-body">${body}</div>` : ""}
			</div>`;
	}

	// -----------------------------------------------------------------------
	// TAB — Stage-wise view (stage picker + flat WO table, not the old
	// drag-and-drop Kanban removed 2026-07-30 — see get_stage_pipeline()'s
	// own docstring). "What's sitting at MY station right now, across every
	// order" — the one question Order-wise/Item-wise/Machine-wise don't
	// answer directly.
	// -----------------------------------------------------------------------
	_load_stage_wise() {
		const $c = this._content();
		$c.html('<div class="ib-ps-loading">Loading stage view…</div>');
		// Deep-link stage (Dashboard pipeline card etc.) picks which pill opens
		// first — consumed once, same pattern Item-wise's _route_stage_filter
		// already uses, then cleared so a later manual pill click isn't
		// fighting a stale route value on every re-render.
		if (this._route_stage_filter) {
			const key = IB_STAGES.find((s) => s.label === this._route_stage_filter)?.key;
			if (key) this.stage_wise_pill = key;
			this._route_stage_filter = null;
		}
		const gen = (this._load_gen = (this._load_gen || 0) + 1);
		frappe.call({
			method: "instabiz.overrides.production.get_stage_pipeline",
			args: { location: this.location_filter || null },
			callback: (r) => {
				if (gen !== this._load_gen) return; // stale — a newer refresh() already superseded this
				if (r.exc) {
					$c.html('<div class="ib-ps-empty">Failed to load stage view.</div>');
					return;
				}
				this.stage_wise_cache = r.message || {};
				this._render_stage_wise();
			},
		});
	}

	_render_stage_wise() {
		const $c = this._content();
		const pipeline = this.stage_wise_cache || {};
		// Server-computed, location-aware stage-key order (get_stage_pipeline's
		// "_stage_order") — a warehouse-only location only ever gets ["packing"],
		// so the pill row doesn't show 4 permanently-dead Coating/Slitting/
		// Rewinding/Cutting pills there. Falls back to all 5 if the server
		// didn't send it (defensive only — it always does).
		const stageOrder = pipeline._stage_order && pipeline._stage_order.length
			? pipeline._stage_order : IB_STAGES.map((s) => s.key);
		const visibleStages = IB_STAGES.filter((s) => stageOrder.includes(s.key));
		if (!visibleStages.some((s) => s.key === this.stage_wise_pill)) {
			this.stage_wise_pill = visibleStages[0]?.key || "packing";
		}

		const pills = visibleStages.map((s) => {
			const count = (pipeline[s.key] || []).length;
			const active = s.key === this.stage_wise_pill;
			return `<button type="button" class="ib-ps-tab ib-sw-pill${active ? " active" : ""}" data-stage="${s.key}"
					style="${active ? `background:${s.color};border-color:${s.color}` : ""}">
					${frappe.utils.escape_html(s.label)} <span class="ib-ps-tab-badge">${count}</span>
				</button>`;
		}).join("");

		// ib_multi_token_filter/ib_multi_token_match only read flat row[field]
		// properties — "item_code"/"item_name"/"customer_name" never existed on
		// this row shape (item data is nested under row.outputs[], customer is
		// "customer" not "customer_name"), so typing an item code or customer
		// name into the search box silently matched nothing, ever. Attach a
		// flat searchable blob first, same pattern Item-wise already uses
		// (_customer_blob) for the same reason.
		const rows = (pipeline[this.stage_wise_pill] || []).map((row) => ({
			...row,
			_item_blob: (row.outputs || []).map((o) => `${o.item_code || ""} ${o.item_name || ""}`).join(" "),
		}));
		const filtered = window.ib_multi_token_filter(rows, ["_item_blob", "sales_order", "customer", "machine"], this.stage_wise_search);

		const toolbar = `
			<div class="ib-ps-os-toolbar" style="margin:14px 0 12px">
				<input class="ib-ps-search-input form-control" id="ib-sw-search" placeholder="Search item, order, customer, machine…" value="${frappe.utils.escape_html(this.stage_wise_search || "")}">
				<span class="ib-ps-stat-pill">${filtered.length} of ${rows.length}</span>
			</div>`;

		// Stage-wise's rows are IB Work Order run rows (production_run._run_row),
		// NOT the old item/target_qty-per-stage shape this template was written
		// against — item_code/customer_name/target_qty/completed_qty/target_uom
		// never existed on that shape, so Item Code/Customer were always blank
		// and Progress always showed a dead "0/0" for every row, on every
		// location, since this table was built. Fixed to read the real fields:
		// item_code(s) come from the run's outputs table (one run can have
		// multiple outputs — show the first + a "+N more" badge, same pattern
		// Machine-wise already uses), customer is `row.customer`, and
		// progress is planned vs. total_output_qty summed across outputs.
		const table_rows = filtered.length
			? filtered.map((row) => {
				// _run_row() names this field "work_order", not "name" — row.name
				// was always undefined, so every row's data-woid attribute was
				// blank and _wo_data was keyed entirely on the literal value
				// `undefined` (last row wins) — clicking any row to open its WO
				// panel silently did nothing, on every load, since this table
				// existed. Same field-name-mismatch bug class as item_code/
				// customer_name/target_qty above, just not visible until you
				// actually tried to click a row. Also: _render_wo_panel's shared
				// contract (used by every other tab) expects a differently-named
				// pseudo-WO shape (wo.name/target_qty/target_uom/item_code/
				// customer_name, not _run_row's work_order/outputs[]/customer) —
				// store the adapted shape so the panel's own buttons (Start/
				// Hold/Complete/Adjust Qty — all keyed off wo.name) actually work.
				this._wo_data.set(row.work_order, this._stage_row_to_wo(row));
				const outs = row.outputs || [];
				const itemLabel = outs.length
					? frappe.utils.escape_html(outs[0].item_code || "") +
					  (outs.length > 1 ? ` <span class="text-muted">+${outs.length - 1} more</span>` : "")
					: "—";
				const targetQty = outs.reduce((s, o) => s + (flt(o.planned_qty) || 0), 0);
				const completedQty = flt(row.total_output_qty) || 0;
				const uom = outs[0]?.uom || "";
				const pct = targetQty > 0 ? Math.min(100, Math.round((completedQty / targetQty) * 100)) : 0;
				return `<tr class="ib-ps-wo-sub-item--clickable" data-woid="${frappe.utils.escape_html(row.work_order)}">
					<td>${itemLabel}</td>
					<td>${row.sales_order ? `<a class="ib-ps-os-link" data-so-nav="${frappe.utils.escape_html(row.sales_order)}">${frappe.utils.escape_html(row.sales_order)}</a>` : "—"}</td>
					<td>${frappe.utils.escape_html(row.customer || "")}</td>
					<td>${row.machine ? frappe.utils.escape_html(row.machine) : `<span style="color:var(--text-muted)">Unassigned</span>`}</td>
					<td>${_ib_status_pill(row.priority || "Normal", "sm")}</td>
					<td>${_ib_status_pill(row.status, "sm")}</td>
					<td>
						<div class="ib-ps-progress-wrap" style="min-width:70px">
							<div class="ib-ps-progress-bar" style="width:${pct}%;background:var(--ib-primary)"></div>
						</div>
						<small>${completedQty}/${targetQty} ${frappe.utils.escape_html(uom)}</small>
					</td>
					<td>${row.delivery_date ? frappe.datetime.str_to_user(row.delivery_date) : "—"}</td>
				</tr>`;
			}).join("")
			: `<tr><td colspan="8"><div class="ib-ps-empty">Nothing at this stage${this.stage_wise_search ? " matching your search" : ""}.</div></td></tr>`;

		$c.html(`
			<div class="ib-sw-pills">${pills}</div>
			${toolbar}
			<div class="ib-ps-table-wrap">
				<table class="ib-ps-table">
					<thead><tr>
						<th>Item Code</th><th>Sales Order</th><th>Customer</th><th>Machine</th>
						<th>Priority</th><th>Status</th><th>Progress</th><th>ETD</th>
					</tr></thead>
					<tbody>${table_rows}</tbody>
				</table>
			</div>`);

		$c.off();
		$c.on("click", ".ib-sw-pill", (e) => {
			this.stage_wise_pill = $(e.currentTarget).data("stage");
			this._render_stage_wise();
		});
		$c.on("input", "#ib-sw-search", (e) => {
			this.stage_wise_search = e.target.value;
			this._render_stage_wise();
		});
		$c.on("click", "[data-so-nav]", (e) => {
			e.stopPropagation();
			frappe.set_route("Form", "Sales Order", $(e.currentTarget).data("so-nav"));
		});
		$c.on("click", "tr[data-woid]", (e) => {
			const wo = this._wo_data.get($(e.currentTarget).data("woid"));
			if (wo) this._open_wo_panel(wo, IB_STAGES.find((s) => s.label === wo.stage)?.key || this.stage_wise_pill);
		});
	}

	// -----------------------------------------------------------------------
	// TAB 3 — Order-wise (Order Sheets list + detail)
	// -----------------------------------------------------------------------
	_load_order_sheets() {
		const $c = this._content();
		$c.html('<div class="ib-ps-loading">Loading orders…</div>');
		// Self-bumped, not just in refresh() — this loader is also called
		// directly (pagination, search, filter changes), so a rapid second
		// call here must invalidate its own in-flight predecessor too.
		const gen = (this._load_gen = (this._load_gen || 0) + 1);
		frappe.call({
			method: "instabiz.overrides.production.get_order_sheets",
			args: {
				status: this.os_status_filter === "All" ? "" : this.os_status_filter,
				priority: this.os_priority_filter === "All" ? "" : this.os_priority_filter,
				location: this.location_filter || "",
				search: this.os_search || "",
			},
			callback: (r) => {
				if (gen !== this._load_gen) return; // stale — a newer refresh() already superseded this
				if (r.exc) {
					$c.html('<div class="ib-ps-empty">Failed to load orders.</div>');
					return;
				}
				this._render_os_list(r.message || []);
			},
		});
	}

	_render_os_list(rows, page) {
		const $c = this._content();
		this._os_list_all = rows = rows || this._os_list_all || [];

		const PAGE_SIZE = 20;
		const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
		this._os_list_page = page || this._os_list_page || 1;
		if (this._os_list_page > totalPages) this._os_list_page = totalPages;
		const start = (this._os_list_page - 1) * PAGE_SIZE;
		const pageRows = rows.slice(start, start + PAGE_SIZE);

		const toolbar = `
			<div class="ib-ps-os-toolbar">
				<div class="ib-ps-filter-group ib-ps-filter-group--search">
					<iconify-icon icon="lucide:search" width="13" height="13" style="color:var(--text-muted)"></iconify-icon>
					<input type="text" id="ib-os-search" class="ib-ps-search-input form-control"
						placeholder="Search Sales Order or customer…" value="${frappe.utils.escape_html(this.os_search || "")}">
				</div>
				<div class="ib-ps-filter-group">
					<label>Status</label>
					<select id="ib-os-status-filter" class="ib-ps-select form-control">
						${["All", "Draft", "In Progress", "Completed"].map((s) => `<option value="${s}" ${s === this.os_status_filter ? "selected" : ""}>${s}</option>`).join("")}
					</select>
				</div>
				<div class="ib-ps-filter-group">
					<label>Priority</label>
					<select id="ib-os-priority-filter" class="ib-ps-select form-control">
						${["All", "Urgent", "High", "Normal", "Low"].map((p) => `<option value="${p}" ${p === this.os_priority_filter ? "selected" : ""}>${p}</option>`).join("")}
					</select>
				</div>
				<button class="ib-ps-btn-primary btn btn-primary btn-sm" id="ib-new-os-btn">+ Start Production</button>
			</div>`;

		let table_html = "";
		let pager_html = "";
		if (!rows.length) {
			table_html = '<div class="ib-ps-empty">No production started yet.</div>';
		} else {
			const rows_html = pageRows.map((os) => {
				const pct = os.progress_pct || 0;
				// Sales Order is the only identifier shown — the underlying Order
				// Sheet id (os.name) still drives the detail-view click via the row
				// and View button's data-os, it's just never displayed as its own
				// column so it can't be confused with a Work Order number.
				const so_cell = os.sales_order
					? `<a class="ib-ps-os-link" data-so="${frappe.utils.escape_html(os.sales_order)}">${frappe.utils.escape_html(os.sales_order)}</a>`
					: `<span style="color:var(--text-muted)">—</span>`;
				return `
					<tr class="ib-ps-os-row" data-os="${frappe.utils.escape_html(os.name)}">
						<td>${so_cell}</td>
						<td>${frappe.utils.escape_html(os.customer_name || os.customer || "")}</td>
						<td style="text-align:center">${os.item_count || 0}</td>
						<td>
							<div class="ib-ps-progress-wrap" style="min-width:80px">
								<div class="ib-ps-progress-bar" style="width:${pct}%;background:var(--ib-primary)"></div>
							</div>
							<small>${pct}%</small>
						</td>
						<td>${_ib_status_pill(os.priority || "Normal", "sm")}</td>
						<td>${_ib_status_pill(os.status, "sm")}</td>
						<td>
							<div style="display:flex;gap:6px">
								<button class="ib-ps-btn-sm ib-ps-os-view-btn" data-os="${frappe.utils.escape_html(os.name)}" title="Open this order's item/stage detail">
									<iconify-icon icon="lucide:eye" width="12" height="12" style="vertical-align:middle;margin-right:3px"></iconify-icon>View
								</button>
								<button class="ib-ps-btn-sm ib-ps-os-print-btn" data-os="${frappe.utils.escape_html(os.name)}" title="Print Job Order for every item on this order">
									<iconify-icon icon="lucide:printer" width="12" height="12" style="vertical-align:middle"></iconify-icon>
								</button>
							</div>
						</td>
					</tr>`;
			}).join("");

			table_html = `
				<div class="ib-ps-table-wrap">
					<table class="ib-ps-table">
						<thead>
							<tr>
								<th>Sales Order</th><th>Customer</th><th style="text-align:center">Items</th><th>Progress</th><th>Priority</th><th>Status</th><th>Actions</th>
							</tr>
						</thead>
						<tbody>${rows_html}</tbody>
					</table>
				</div>`;

			pager_html = totalPages > 1 ? `
				<div style="display:flex;align-items:center;justify-content:center;gap:10px;margin-top:12px">
					<button class="btn btn-default btn-xs ib-os-prev" ${this._os_list_page <= 1 ? "disabled" : ""}>Prev</button>
					<span style="font-size:12px;color:var(--text-muted)">Page ${this._os_list_page} of ${totalPages} (${rows.length} orders)</span>
					<button class="btn btn-default btn-xs ib-os-next" ${this._os_list_page >= totalPages ? "disabled" : ""}>Next</button>
				</div>` : "";
		}

		$c.html(toolbar + table_html + pager_html);
		$c.off();

		$c.on("click", ".ib-os-prev", () => this._render_os_list(this._os_list_all, this._os_list_page - 1));
		$c.on("click", ".ib-os-next", () => this._render_os_list(this._os_list_all, this._os_list_page + 1));

		// Filter changes
		$c.on("change", "#ib-os-status-filter", (e) => {
			this.os_status_filter = $(e.target).val();
			this._os_list_page = 1;
			this._load_order_sheets();
		});
		$c.on("change", "#ib-os-priority-filter", (e) => {
			this.os_priority_filter = $(e.target).val();
			this._os_list_page = 1;
			this._load_order_sheets();
		});
		let os_search_timer = null;
		$c.on("input", "#ib-os-search", (e) => {
			clearTimeout(os_search_timer);
			const val = $(e.target).val();
			os_search_timer = setTimeout(() => {
				this.os_search = val;
				this._os_list_page = 1;
				this._load_order_sheets();
			}, 300);
		});

		// Sales Order link → open SO form
		$c.on("click", "[data-so]", (e) => {
			e.stopPropagation();
			const so = $(e.currentTarget).data("so");
			if (so) frappe.set_route("Form", "Sales Order", so);
		});

		// View / row click
		$c.on("click", ".ib-ps-os-view-btn, .ib-ps-os-link", (e) => {
			e.stopPropagation();
			const os_name = $(e.currentTarget).data("os");
			if (!os_name) return;
			this.current_os = os_name;
			this._load_os_detail(os_name);
		});

		// Print Job Order — every active Work Order under this order, one PDF
		$c.on("click", ".ib-ps-os-print-btn", (e) => {
			e.stopPropagation();
			const os_name = $(e.currentTarget).data("os");
			if (os_name) this._print_job_orders_for_os(os_name);
		});
		$c.on("click", ".ib-ps-os-row", (e) => {
			const os_name = $(e.currentTarget).data("os");
			this.current_os = os_name;
			this._load_os_detail(os_name);
		});

		// New Order Sheet
		$c.on("click", "#ib-new-os-btn", () => this._show_new_os_dialog());
	}

	// -----------------------------------------------------------------------
	// Order Sheet Detail
	// -----------------------------------------------------------------------
	_load_os_detail(os_name) {
		const $c = this._content();
		$c.html('<div class="ib-ps-loading">Loading order…</div>');
		// Self-bumped — called directly from many places (click into an
		// order, bulk-start dialog completion), not only via refresh().
		const gen = (this._load_gen = (this._load_gen || 0) + 1);
		frappe.call({
			method: "instabiz.overrides.production.get_order_sheet_detail",
			args: { order_sheet: os_name },
			callback: (r) => {
				if (gen !== this._load_gen) return; // stale — a newer refresh() already superseded this
				if (r.exc) {
					$c.html('<div class="ib-ps-empty">Failed to load order.</div>');
					return;
				}
				this._render_os_detail(r.message || {});
			},
		});
	}

	_render_os_detail(detail) {
		const $c = this._content();
		const os = detail.order_sheet || {};

		const so_link = os.sales_order
			? `<a class="ib-ps-os-link" style="cursor:pointer" data-so-nav="${frappe.utils.escape_html(os.sales_order)}">${frappe.utils.escape_html(os.sales_order)}</a>`
			: `<span style="color:var(--text-muted)">No SO</span>`;
		const date_fmt = (d) => d ? frappe.datetime.str_to_user(d) : "—";
		// IB Order Sheet.status is only ever "Completed" once every item's every
		// stage is Completed (_update_order_sheet_progress) — the exact same
		// source of truth get_order_dn_readiness() reads for the WO side
		// panel's own Create Delivery Note gate, so no extra RPC needed here:
		// it's already sitting on the detail payload this header renders from.
		const dn_btn = (os.status === "Completed" && os.sales_order)
			? `<button class="btn btn-primary btn-sm ib-os-create-dn" data-so="${frappe.utils.escape_html(os.sales_order)}" style="margin-left:auto">
					<iconify-icon icon="lucide:truck" width="12" height="12" style="vertical-align:middle;margin-right:4px"></iconify-icon>
					Create Delivery Note
				</button>`
			: "";
		const header = `
			<div class="ib-ps-detail-header">
				<button class="ib-ps-back-btn" id="ib-os-back">← Back</button>
				<div class="ib-ps-detail-meta">
					<span class="ib-ps-detail-name">${so_link}</span>
					<span class="ib-ps-detail-customer">${frappe.utils.escape_html(os.customer || "")}</span>
					<span style="font-size:11px;color:var(--text-muted)">Order: ${date_fmt(os.order_date)}</span>
					${os.delivery_date ? `<span style="font-size:11px;color:#dc2626">Deliver: ${date_fmt(os.delivery_date)}</span>` : ""}
					${_ib_status_pill(os.priority || "Normal", "sm")}
					${_ib_status_pill(os.status, "sm")}
					${dn_btn}
				</div>
			</div>`;

		// Product-wise and Machine-wise sub-tabs removed 2026-08-13 — Order-wise
		// is the only view of an order's items now, so there's nothing left to
		// switch between.
		$c.html(header + '<div class="ib-ps-detail-body" id="ib-ps-detail-body"></div>');

		this._render_os_subtab(detail);

		// $c (#ib-ps-content) is a persistent node — this function re-runs on
		// every refresh() while an order is open (realtime floor updates,
		// Refresh button, on_page_show) without going through _render_os_list's
		// own $c.off(), so unbind first or repeated refreshes stack duplicate
		// nav/back handlers (same bug class as the WO side panel fix).
		$c.off();

		// Sales Order nav link in detail header
		$c.on("click", "[data-so-nav]", (e) => {
			e.stopPropagation();
			const so = $(e.currentTarget).data("so-nav");
			if (so) frappe.set_route("Form", "Sales Order", so);
		});

		// Back button
		$c.on("click", "#ib-os-back", () => {
			this.current_os = null;
			this._load_order_sheets();
		});

		$c.on("click", ".ib-os-create-dn", (e) => {
			const $btn = $(e.currentTarget);
			if ($btn.prop("disabled")) return;
			$btn.prop("disabled", true);
			this._create_dn_for_order($btn.data("so"), $btn);
		});
	}

	// Whole-order Delivery Note — no item_code/order_sheet_item passed, which
	// custom_make_delivery_note() documents as "keeps the existing whole-order
	// behavior used by the SO form's own Create > Delivery Note button". Only
	// reachable once IB Order Sheet.status is Completed (every item, every
	// stage), so there's nothing left to scope out — unlike the WO panel's
	// per-item button, which exists to let one item ship before its siblings
	// finish, this one only appears once there's no siblings left to wait on.
	_create_dn_for_order(sales_order, $btn) {
		if (!sales_order) {
			frappe.show_alert({ message: "No Sales Order linked to this order.", indicator: "red" });
			return;
		}
		frappe.call({
			method: "instabiz.overrides.sales_order.custom_make_delivery_note",
			args: { source_name: sales_order },
			callback: (r) => {
				if (!r.message) {
					frappe.show_alert({ message: "Failed to create Delivery Note.", indicator: "red" });
					if ($btn) $btn.prop("disabled", false);
					return;
				}
				frappe.model.sync(r.message);
				frappe.set_route("Form", r.message.doctype, r.message.name);
			},
			error: () => { if ($btn) $btn.prop("disabled", false); },
		});
	}

	// Product-wise and Machine-wise sub-tabs removed 2026-08-13 (user request)
	// — Order-wise is now the only view of an order's items, and already has
	// its own Start Production entry point (added same session) so nothing
	// was lost by dropping the other two.
	_render_os_subtab(detail) {
		const $body = this.$body.find("#ib-ps-detail-body");
		this._render_os_order_wise($body, detail);
	}

	_render_os_order_wise($body, detail) {
		const items = detail.order_wise_view || [];
		if (!items.length) {
			$body.html('<div class="ib-ps-empty">No items found.</div>');
			return;
		}

		// Left-to-right chip order: grouped by run first (oldest run's 5
		// stages, then the next run's 5, in the order the backend already
		// emits them — get_order_sheet_detail walks _all_runs_for_osi
		// oldest-first), stage-route order within each run (Move/manual
		// stage jumps can otherwise reorder a single run's own chips). A
		// plain global sort-by-stage-order (the old logic, from back when
		// an item could only ever have one run) would interleave two runs'
		// chips by stage label instead — e.g. both runs' Coating chips
		// adjacent, then both Slitting chips — reading as one garbled
		// route instead of "run 1's full route, then run 2's".
		const stageOrder = IB_STAGES.map((s) => s.label);

		const rows = items.map((item) => {
			const runOrder = [];
			(item.work_orders || []).forEach((wo) => { if (!runOrder.includes(wo.name)) runOrder.push(wo.name); });
			const wos = [...(item.work_orders || [])].sort((a, b) => {
				const runDiff = runOrder.indexOf(a.name) - runOrder.indexOf(b.name);
				return runDiff !== 0 ? runDiff : stageOrder.indexOf(a.stage) - stageOrder.indexOf(b.stage);
			});
			const doneCount = wos.filter((wo) => wo.status === "Completed").length;
			const stagePct = wos.length ? Math.round((doneCount / wos.length) * 100) : 0;
			// Progress column uses the same stage-completion fraction as the Work
			// Orders column below it, not item.completed_qty/item.qty. Order Sheet
			// Item.completed_qty is set to the item's full target_qty the moment
			// ANY single stage completes (IB Production Entry — the only thing that
			// could track real partial per-stage output — is unused by design, see
			// _update_order_sheet_item()) — so a qty-based ratio reads 100% after
			// just the first of N stages finishes. Confirmed live: a 2-stage
			// Packing->RTD item showed "Progress: 100%" right next to its own
			// "Work Orders: 1/2 stages (50%)" on the same row, immediately after
			// Packing alone completed. Using stagePct for both keeps the row
			// internally consistent and not misleading.
			const pct = stagePct;

			// Compact stage-pill row — same visual language as the Production
			// Dashboard's per-item stagePills (_render_plan in
			// ib_production_dashboard.js): one small colored chip per Work
			// Order, full stage name + colored by status (was abbreviated —
			// see the chip-render code below for why that changed). Full WO
			// name/qty/date (previously always-visible as a wall of <li> text)
			// now lives in the hover tooltip; clicking a chip still opens the
			// same WO side panel a click on the old list row used to.
			// Every chip within ONE run describes the SAME real Work Order (a
			// run expanded per route stage just for this pill row) — chips
			// used to be keyed only by item.current_wo, which is just the
			// (at most one) LIVE run's data; an item with 2+ runs (a partial
			// run held then finished by a second run, or a length-split —
			// see _all_runs_for_osi's own comment) had its earlier run(s)'
			// chips render but silently do nothing on click, since their
			// name was never in _wo_data at all. Fixed: populate _wo_data
			// from item.wo_data, which the backend now builds one entry per
			// run, not just the current one.
			Object.entries(item.wo_data || {}).forEach(([name, wo]) => {
				this._wo_data.set(name, { ...wo, delivery_date: wo.delivery_date || (detail.order_sheet || {}).delivery_date });
			});
			const chips = wos.map((wo, i) => {
				// Full stage name, not the CT/SL/RW/CU/PK abbreviation — direct
				// ask: "make sure user knows which stage they are looking at"
				// without having to hover for the tooltip.
				const stageLabel = frappe.utils.escape_html(wo.stage || "—");
				const created = wo.creation ? frappe.datetime.str_to_user(wo.creation) : "—";
				const title = `${wo.stage || ""}: ${wo.name || ""} — ${wo.status || ""} `
					+ `(${wo.completed_qty || 0}/${wo.target_qty || 0}) — Created: ${created}`;
				const cancelled_cls = wo.status === "Cancelled" ? " ib-ps-wo-chip--cancelled" : "";
				// Pulses while genuinely running — direct ask: "animate the
				// stage in progress badge (blue) to indicate progression."
				const live_cls = wo.status === "In Progress" ? " ib-ps-wo-chip--live" : "";
				// A visible gap where the run changes — without it, two runs'
				// worth of chips read as one confusing 10-chip blob with no
				// indication where the first run's route ends and the
				// second's begins.
				const newRun = i > 0 && wos[i - 1].name !== wo.name;
				return `<span class="ib-ps-wo-chip indicator-pill ib-ps-pill-sm ${_ib_status_color(wo.status)}${cancelled_cls}${live_cls}"
					style="${newRun ? "margin-left:8px" : ""}"
					data-woid="${frappe.utils.escape_html(wo.name)}"
					title="${frappe.utils.escape_html(title)}">${_stage_chip_icon(wo.stage)}${stageLabel}</span>`;
			}).join("");

			// JIT stage model (2026-08-13): an item with nothing active/pending
			// is the normal resting state now (never started, or its
			// last-started stage just completed) — not a dead end. Backend's
			// next_stage_suggestion (get_order_sheet_detail) is only set when
			// there's genuinely nothing active, so it doubles as the trigger
			// for showing the Start button here, same one used everywhere
			// else on this page (Active Production Plan, Order-wise's own
			// "+" stage grid, the WO panel's post-complete prompt).
			const startBtn = item.next_stage_suggestion
				? `<button class="btn btn-primary btn-sm ib-ps-owise-start" data-osi="${frappe.utils.escape_html(item.name)}"
						data-item="${frappe.utils.escape_html(item.item_code || "")}"
						data-suggestion="${frappe.utils.escape_html(item.next_stage_suggestion)}">
						<iconify-icon icon="lucide:play" width="12" height="12" style="vertical-align:middle;margin-right:4px"></iconify-icon>
						Start Production
					</button>`
				: "";
			const wo_cell = wos.length
				? `<div class="ib-ps-wo-chip-row">${chips}</div>
					<div class="ib-ps-wo-chip-progress">
						<div class="ib-ps-wo-chip-progress-wrap">
							<div class="ib-ps-progress-bar" style="width:${stagePct}%;background:var(--ib-primary)"></div>
						</div>
						<small>${doneCount}/${wos.length} stages (${stagePct}%)</small>
					</div>
					${startBtn}`
				: (startBtn || `<span style="color:var(--text-muted);font-size:11px">No Work Orders</span>`);

			// Adjust Qty (pcs_to_make/logs_to_make) is per-WO, set independently
			// of the item's ordered qty above — flag it here so an adjustment
			// made on one stage's WO isn't invisible on the item row.
			const adjustments = wos
				.map((wo) => {
					const adjusted = wo.target_uom === "PCS" ? wo.pcs_to_make
						: wo.target_uom === "SQMT" ? wo.logs_to_make
						: null;
					return (adjusted && adjusted != wo.target_qty)
						? { stage: wo.stage, from: wo.target_qty, to: adjusted, uom: wo.target_uom }
						: null;
				})
				.filter(Boolean);
			const adj_badge = adjustments.length
				? ` <span class="indicator-pill orange ib-ps-pill-sm" title="${frappe.utils.escape_html(
						adjustments.map((a) => `${a.stage}: ${a.from} → ${a.to} ${a.uom}`).join(" | ")
					)}">${adjustments[0].from} → ${adjustments[0].to}${adjustments.length > 1 ? ` (+${adjustments.length - 1})` : ""}</span>`
				: "";

			return `
				<tr>
					<td>${frappe.utils.escape_html(item.item_code || "")}</td>
					<td>${frappe.utils.escape_html(item.item_name || "")}</td>
					<td>${item.qty || 0} ${frappe.utils.escape_html(item.uom || "")}${adj_badge}</td>
					<td>
						<div class="ib-ps-progress-wrap">
							<div class="ib-ps-progress-bar" style="width:${pct}%;background:var(--ib-primary)"></div>
						</div>
						<small>${pct}%</small>
					</td>
					<td>${wo_cell}</td>
				</tr>`;
		}).join("");

		// Items that can be started right now (nothing active/pending on them —
		// same trigger the per-row Start Production button uses).
		const startable = items.filter((it) => it.next_stage_suggestion);
		const startAllBtn = startable.length
			? `<div style="margin-bottom:10px">
					<button class="btn btn-primary btn-sm ib-ps-owise-start-all">
						<iconify-icon icon="lucide:play" width="12" height="12" style="vertical-align:middle;margin-right:4px"></iconify-icon>
						Start Production — All Items (${startable.length})
					</button>
				</div>`
			: "";

		$body.html(`
			${startAllBtn}
			<div class="ib-ps-table-wrap">
				<table class="ib-ps-table">
					<thead><tr><th>Item Code</th><th>Item Name</th><th>Qty</th><th>Progress</th><th>Work Orders</th></tr></thead>
					<tbody>${rows}</tbody>
				</table>
			</div>`);

		$body.off("click", ".ib-ps-owise-start-all").on("click", ".ib-ps-owise-start-all", () => {
			ibBulkStartDialog(startable, () => this._load_os_detail(this.current_os));
		});
		$body.off("click", ".ib-ps-wo-chip").on("click", ".ib-ps-wo-chip", (e) => {
			const woid = $(e.currentTarget).data("woid");
			const wo = this._wo_data.get(woid);
			if (wo) this._open_wo_panel(wo, IB_STAGES.find(s => s.label === wo.stage)?.key || "");
		});
		$body.off("click", ".ib-ps-owise-start").on("click", ".ib-ps-owise-start", (e) => {
			const $btn = $(e.currentTarget);
			_start_production_flow(
				$btn.data("osi"), $btn.data("item"), $btn.data("suggestion"),
				() => this._load_os_detail(this.current_os),
			);
		});
	}


	// -----------------------------------------------------------------------
	// Start Production dialog
	// -----------------------------------------------------------------------
	_show_new_os_dialog() {
		const d = new frappe.ui.Dialog({
			title: "Start Production",
			fields: [
				{
					fieldname: "sales_order",
					label: "Sales Order",
					fieldtype: "Link",
					options: "Sales Order",
					get_query: () => ({ filters: { docstatus: 1 } }),
					reqd: 1,
				},
				{
					fieldname: "priority",
					label: "Priority",
					fieldtype: "Select",
					options: ["Normal", "High", "Urgent", "Low"],
					default: "Normal",
				},
				{ fieldname: "notes", label: "Notes", fieldtype: "Small Text" },
			],
			primary_action_label: "Create",
			primary_action: (values) => {
				frappe.call({
					method: "instabiz.overrides.production.create_order_sheet",
					args: values,
					callback: (r) => {
						if (r.exc) {
							frappe.show_alert({ message: "Failed to start production.", indicator: "red" });
							return;
						}
						frappe.show_alert({ message: `Production started for ${values.sales_order}.`, indicator: "green" });
						d.hide();
						this._load_order_sheets();
					},
				});
			},
		});
		d.show();
	}

	// -----------------------------------------------------------------------
	// TAB 4 — Machine-wise dashboard
	// -----------------------------------------------------------------------
	_load_machine_wise() {
		const $c = this._content();
		$c.html('<div class="ib-ps-loading">Loading machine dashboard…</div>');
		// Self-bumped — also called directly from the realtime floor-update
		// handler, not only via refresh().
		const gen = (this._load_gen = (this._load_gen || 0) + 1);
		frappe.call({
			method: "instabiz.overrides.production.get_machine_wise_dashboard",
			args: { location: this.location_filter || "", floor: this.floor_filter || "" },
			callback: (r) => {
				if (gen !== this._load_gen) return; // stale — a newer refresh() already superseded this
				if (r.exc) {
					$c.html('<div class="ib-ps-empty">Failed to load machine dashboard.</div>');
					return;
				}
				this.machines_cache = r.message || [];
				this._render_machine_wise(this.machines_cache);
			},
		});
	}

	// Redesigned to match Stage-wise's shape (user's explicit ask: "machine
	// wise view needs to be like how stages wise view is") — a picker (pills,
	// one per machine, count-badged) instead of a card grid, a stats strip for
	// whichever machine is currently selected, then one full searchable table
	// instead of the old per-card "first 4 WOs + N more" cap (that cap wasn't
	// a design choice, it was a fit-in-a-300px-card constraint — a real limit
	// on how many queued jobs a supervisor could actually see for a busy
	// machine like CM-01, which alone has queued 50+ WOs on real data).
	_render_machine_wise(machines) {
		const $c = this._content();
		this._machine_data = new Map();
		machines.forEach(m => this._machine_data.set(m.name || m.machine_code, m));

		const TYPE_COLOR = {
			Coating: "#7c3aed", Slitting: "#2563eb", Rewinding: "#0891b2",
			Cutting: "#059669", Packing: "#d97706",
		};

		const top_toolbar = `
			<div class="ib-ps-os-toolbar" style="margin-bottom:12px">
				<div style="display:flex;align-items:center;gap:8px">
					<iconify-icon icon="lucide:settings-2" width="14" height="14"></iconify-icon>
					<span class="ib-ps-stat-pill">${machines.length} active machine${machines.length !== 1 ? "s" : ""}</span>
				</div>
				<button class="ib-ps-btn-primary btn btn-primary btn-sm" id="ib-new-machine-btn" style="margin-left:auto;display:flex;align-items:center;gap:5px">
					<iconify-icon icon="lucide:plus" width="11" height="11"></iconify-icon> New Machine
				</button>
			</div>`;

		if (!machines.length) {
			$c.html(top_toolbar + '<div class="ib-ps-empty">No active machines configured.</div>');
			$c.off();
			$c.on("click", "#ib-new-machine-btn", () => this._show_machine_dialog(null));
			return;
		}

		// Keep the previously-selected machine across refreshes if it still
		// exists; otherwise default to the first (busiest-first ordering
		// already comes from the backend).
		if (!this.machine_wise_pill || !this._machine_data.has(this.machine_wise_pill)) {
			this.machine_wise_pill = machines[0].name || machines[0].machine_code;
		}
		const selected = this._machine_data.get(this.machine_wise_pill);

		const pills = machines.map((m) => {
			const key = m.name || m.machine_code;
			const type_color = TYPE_COLOR[m.machine_type] || "#888";
			const active = key === this.machine_wise_pill;
			const count = (m.current_wos || []).length;
			return `<button type="button" class="ib-ps-tab ib-sw-pill${active ? " active" : ""}" data-machine="${frappe.utils.escape_html(key)}"
					style="${active ? `background:${type_color};border-color:${type_color}` : ""}" title="${frappe.utils.escape_html(m.machine_name || "")}">
					${frappe.utils.escape_html(m.machine_code || "")} <span class="ib-ps-tab-badge">${count}</span>
				</button>`;
		}).join("");

		const type_color = TYPE_COLOR[selected.machine_type] || "#888";
		const load_pct = selected.load_pct || 0;
		const load_color = load_pct > 90 ? "#dc2626" : load_pct > 60 ? "#d97706" : "#16a34a";
		const waste_norm = selected.wastage_norm_pct || 3;
		const waste_color = selected.today_avg_wastage > waste_norm ? "#dc2626" : "#16a34a";
		const yield_pct = selected.today_yield_pct != null ? selected.today_yield_pct : (100 - waste_norm);
		const yield_color = (100 - yield_pct) > waste_norm ? "#dc2626" : "#16a34a";

		const STAT_ICON = { Output: "lucide:package", Wastage: "lucide:trash-2", Yield: "lucide:gauge-circle", Capacity: "lucide:zap" };
		const stat_tile = (label, val, color) => `
			<div class="ib-mw-stat">
				<iconify-icon icon="${STAT_ICON[label] || "lucide:circle"}" width="14" height="14" class="ib-mw-stat-icon"></iconify-icon>
				<div class="ib-mw-stat-body">
					<div class="ib-mw-stat-val"${color ? ` style="color:${color}"` : ""}>${val}</div>
					<div class="ib-mw-stat-label">${label}</div>
				</div>
			</div>`;

		const machine_header = `
			<div class="ib-mw-selected-header">
				<div>
					<div class="ib-mw-code-row">
						<code class="ib-ps-machine-code" style="color:${type_color}">${frappe.utils.escape_html(selected.machine_code || "")}</code>
						<span class="ib-ps-type-chip" style="background:${type_color}18;color:${type_color};border:1px solid ${type_color}30">${frappe.utils.escape_html(selected.machine_type || "")}</span>
						${(selected.active_load || 0) > 0
							? _live_pulse_svg((selected.active_load || 0) + " job(s) running right now")
							: `<span class="indicator green" title="Active, idle"></span>`}
					</div>
					<div class="ib-mw-name-row">
						<span class="ib-ps-machine-name">${frappe.utils.escape_html(selected.machine_name || "")}</span>
						<span class="ib-ps-location-badge">${frappe.utils.escape_html((selected.location || "").charAt(0).toUpperCase() + (selected.location || "").slice(1))}</span>
						${selected.floor ? `<span class="ib-ps-location-badge" style="opacity:.75">${frappe.utils.escape_html(selected.floor)}</span>` : ""}
					</div>
				</div>
				<button class="ib-mw-edit-btn ib-ps-machine-edit-btn" data-machineid="${frappe.utils.escape_html(this.machine_wise_pill)}" title="Edit Machine">
					<iconify-icon icon="lucide:settings" width="11" height="11"></iconify-icon> Edit
				</button>
			</div>
			<div class="ib-mw-body-row">
				<div class="ib-mw-load-block">
					<div class="ib-mw-load-header">
						<span style="font-size:11px;color:var(--text-muted)">Machine Load</span>
						<span style="font-size:12px;font-weight:700;color:${load_color}">${load_pct}%</span>
					</div>
					<div class="ib-mw-load-bar-wrap${(selected.active_load || 0) > 0 ? " ib-ps-progress-wrap--running" : ""}">
						<div class="ib-mw-load-bar ib-ps-progress-bar" style="width:${Math.min(100, load_pct)}%;background:${load_color}"></div>
					</div>
					<div style="font-size:10px;color:var(--text-muted);margin-top:4px">
						${selected.active_load || 0} active · ${(selected.current_wos || []).length} queued
					</div>
				</div>
				<div class="ib-mw-stats-row">
					${stat_tile("Output", selected.today_output || 0)}
					${stat_tile("Wastage", (selected.today_avg_wastage || 0) + "%", waste_color)}
					${stat_tile("Yield", yield_pct + "%", yield_color)}
					${stat_tile("Capacity", selected.capacity ? `${selected.capacity} <span class="ib-mw-stat-uom">${frappe.utils.escape_html(selected.capacity_uom || "")}</span>` : "—")}
				</div>
			</div>`;

		const all_wos = selected.current_wos || [];
		all_wos.forEach((wo) => this._wo_data.set(wo.name, wo));
		const filtered = window.ib_multi_token_filter(all_wos, ["item_code", "item_name", "sales_order", "customer_name"], this.machine_wise_search);

		const search_toolbar = `
			<div class="ib-ps-os-toolbar" style="margin:14px 0 12px">
				<input class="ib-ps-search-input form-control" id="ib-mw-search" placeholder="Search item, order, customer…" value="${frappe.utils.escape_html(this.machine_wise_search || "")}">
				<span class="ib-ps-stat-pill">${filtered.length} of ${all_wos.length}</span>
			</div>`;

		const table_rows = filtered.length
			? filtered.map((wo) => {
				const pct = wo.target_qty > 0 ? Math.min(100, Math.round((wo.completed_qty / wo.target_qty) * 100)) : 0;
				return `<tr class="ib-ps-wo-sub-item--clickable" data-woid="${frappe.utils.escape_html(wo.name)}">
					<td>
						<div>${frappe.utils.escape_html(wo.item_name || wo.item_code || "")}</div>
						${wo.item_name ? `<div class="ib-ps-item-code-sub">${frappe.utils.escape_html(wo.item_code || "")}</div>` : ""}
					</td>
					<td>${wo.sales_order ? `<a class="ib-ps-os-link" data-so-nav="${frappe.utils.escape_html(wo.sales_order)}">${frappe.utils.escape_html(wo.sales_order)}</a>` : "—"}</td>
					<td>${frappe.utils.escape_html(wo.customer_name || "")}</td>
					<td>${_ib_status_pill(wo.priority || "Normal", "sm")}</td>
					<td>${_ib_status_pill(wo.status, "sm")}${wo.status === "In Progress" ? _live_pulse_svg("Running now") : ""}</td>
					<td>
						<div class="ib-ps-progress-wrap${wo.status === "In Progress" ? " ib-ps-progress-wrap--running" : ""}" style="min-width:70px">
							<div class="ib-ps-progress-bar" style="width:${pct}%;background:var(--ib-primary)"></div>
						</div>
						<small>${wo.completed_qty || 0}/${wo.target_qty || 0} ${frappe.utils.escape_html(wo.target_uom || "")}</small>
					</td>
					<td>${wo.delivery_date ? frappe.datetime.str_to_user(wo.delivery_date) : "—"}</td>
				</tr>`;
			}).join("")
			: `<tr><td colspan="7"><div class="ib-ps-empty">No queued Work Orders on this machine${this.machine_wise_search ? " matching your search" : ""}.</div></td></tr>`;

		$c.html(`
			${top_toolbar}
			<div class="ib-sw-pills">${pills}</div>
			<div class="ib-mw-selected-card">${machine_header}</div>
			<div id="ib-mw-bundle-hint"></div>
			${search_toolbar}
			<div class="ib-ps-table-wrap">
				<table class="ib-ps-table">
					<thead><tr>
						<th>Item</th><th>Sales Order</th><th>Customer</th>
						<th>Priority</th><th>Status</th><th>Progress</th><th>ETD</th>
					</tr></thead>
					<tbody>${table_rows}</tbody>
				</table>
			</div>`);

		// $c (#ib-ps-content) persists across refresh() calls (realtime floor
		// updates, tab re-switch, Refresh button) — unbind before rebinding,
		// same bug class as the WO side panel fix.
		$c.off();
		$c.on("click", "#ib-new-machine-btn", () => this._show_machine_dialog(null));
		$c.on("click", ".ib-ps-machine-edit-btn", (e) => {
			const mid = $(e.currentTarget).data("machineid");
			const machine = this._machine_data.get(mid);
			this._show_machine_dialog(machine || null);
		});
		$c.on("click", ".ib-sw-pill", (e) => {
			this.machine_wise_pill = $(e.currentTarget).data("machine");
			this.machine_wise_search = "";
			this._render_machine_wise(machines);
		});
		$c.on("input", "#ib-mw-search", (e) => {
			this.machine_wise_search = e.target.value;
			this._render_machine_wise(machines);
		});
		$c.on("click", "[data-so-nav]", (e) => {
			e.stopPropagation();
			frappe.set_route("Form", "Sales Order", $(e.currentTarget).data("so-nav"));
		});
		$c.on("click", "tr[data-woid]", (e) => {
			const wo = this._wo_data.get($(e.currentTarget).data("woid"));
			if (wo) this._open_wo_panel(wo, IB_STAGES.find((s) => s.label === wo.stage)?.key || "");
		});

		this._load_setup_bundle_hint(selected);
	}

	// "Efficiently with similar orders" — get_setup_batches() (production_run.py)
	// already groups every run currently sitting at this machine's stage by
	// exact setup signature (width/length/core), across ALL sales orders, not
	// just this machine's own queue — built alongside the run model but never
	// actually surfaced anywhere until now. A run always belongs to exactly
	// one order (IB Work Order.sales_order is a single Link, can't span
	// customers) — this is how cross-order efficiency actually happens: same
	// setup, sequenced back-to-back, one changeover instead of several.
	_load_setup_bundle_hint(selected) {
		const $hint = this._content().find("#ib-mw-bundle-hint");
		if (!selected.machine_type) return;
		frappe.call({
			method: "instabiz.overrides.production_run.get_setup_batches",
			args: { stage: selected.machine_type, location: selected.location || "" },
			callback: (r) => {
				const groups = r.message || [];
				if (!groups.length) return;
				$hint.html(groups.map((g) => {
					const on_this_machine = g.machines.includes(this.machine_wise_pill);
					const widths = (g.runs[0]?.output_widths_mm || []).map((w) => Math.round(w)).join("×") || "—";
					const length = g.runs[0]?.output_length_m ? `, ${Math.round(g.runs[0].output_length_m)}m` : "";
					return `
						<div class="ib-mw-bundle-hint${on_this_machine ? " ib-mw-bundle-hint--here" : ""}">
							<iconify-icon icon="lucide:link-2" width="13" height="13"></iconify-icon>
							<span><strong>${g.run_count} runs</strong> share this setup (${widths}mm${length}) across
							${g.machines.length > 1 ? g.machines.join(", ") : g.machines[0] || "—"} —
							sequence them together for one changeover instead of ${g.run_count}.</span>
						</div>`;
				}).join(""));
			},
		});
	}

	_show_machine_dialog(machine) {
		const is_edit = !!machine;
		const d = new frappe.ui.Dialog({
			title: is_edit ? "Edit Machine" : "New Machine",
			fields: [
				{ fieldname: "machine_code", label: "Machine Code", fieldtype: "Data", reqd: 1, default: machine?.machine_code },
				{ fieldname: "machine_name", label: "Machine Name", fieldtype: "Data", reqd: 1, default: machine?.machine_name },
				{
					fieldname: "machine_type",
					label: "Machine Type",
					fieldtype: "Select",
					// Matches IB Machine.machine_type's real Select options exactly
					// (instabiz/instabiz/doctype/ib_machine/ib_machine.json) — this
					// dialog previously hardcoded only 5 of the 7 real values,
					// missing Despatch and Quality Control entirely. Root cause of
					// a live bug: DS-01 ("Despatch Station 1") could never actually
					// be typed Despatch through this dialog, so it was mislabeled
					// Packing — batch-assign to any Ready-to-Deliver/Delivered WO
					// then correctly rejected it server-side, since 0 machines
					// system-wide had machine_type="Despatch" until fixed 2026-08-05.
					options: ["Coating", "Slitting", "Rewinding", "Cutting", "Packing", "Quality Control", "Despatch"],
					default: machine?.machine_type || "Coating",
				},
				{
					fieldname: "location",
					label: "Location",
					fieldtype: "Select",
					options: ["maharashtra", "gujarat", "chennai"],
					default: machine?.location || "maharashtra",
					onchange: () => {
						// Floor list is location-scoped — a floor picked for one
						// location makes no sense once location changes.
						d.set_value("floor", "");
						d.refresh_field("floor");
					},
				},
				{
					fieldname: "floor",
					label: "Floor",
					fieldtype: "Link",
					options: "IB Production Floor",
					default: machine?.floor || "",
					description: "Optional — leave blank to keep location-only auto-assignment.",
					get_query: () => ({
						filters: { location: d.get_value("location") || "" },
					}),
				},
				{ fieldname: "capacity", label: "Capacity", fieldtype: "Float", default: machine?.capacity || 0 },
				{
					fieldname: "capacity_uom",
					label: "Capacity UOM",
					fieldtype: "Select",
					options: ["", "sqm/hour", "rolls/hour", "pcs/hour", "kg/hour", "ctn/shift"],
					default: machine?.capacity_uom || "",
				},
				{ fieldname: "wastage_norm_pct", label: "Wastage Norm %", fieldtype: "Float", default: machine?.wastage_norm_pct || 2.0 },
				{
					fieldname: "status",
					label: "Status",
					fieldtype: "Select",
					options: ["Active", "Inactive", "Under Maintenance"],
					default: machine?.status || "Active",
				},
			],
			primary_action_label: "Save",
			primary_action: (values) => {
				frappe.call({
					method: "instabiz.overrides.production.save_machine",
					args: values,
					callback: (r) => {
						if (r.exc) {
							frappe.show_alert({ message: "Failed to save machine.", indicator: "red" });
							return;
						}
						frappe.show_alert({ message: "Machine saved.", indicator: "green" });
						d.hide();
						this._load_machine_wise();
					},
				});
			},
		});
		d.show();
	}


	// -----------------------------------------------------------------------
	// WO Side Panel
	// -----------------------------------------------------------------------
	_open_wo_panel(wo, stage_key) {
		this.active_wo = wo;
		this._render_wo_panel(wo, stage_key);
	}

	// Stage-wise reads raw production_run._run_row() objects — this maps one
	// onto the pseudo-WO shape _render_wo_panel/its button handlers actually
	// expect (see the note where this is called). produced_serials/pcs_to_make
	// aren't in _run_row's field list at all — left undefined, which the
	// panel already treats as "0"/falsy (Print Serial Labels just doesn't
	// show; matches what those tabs do for a WO with none anyway).
	_stage_row_to_wo(row) {
		const outs = row.outputs || [];
		return {
			...row,
			name: row.work_order,
			stage: row.current_stage,
			customer_name: row.customer,
			item_code: outs[0]?.item_code || "",
			target_qty: outs.reduce((s, o) => s + (flt(o.planned_qty) || 0), 0),
			target_uom: outs[0]?.uom || "",
		};
	}

	_close_side_panel() {
		if (this._wo_dialog) this._wo_dialog.hide();
		this.active_wo = null;
	}

	_render_wo_panel(wo, stage_key) {
		const stage = IB_STAGES.find((s) => s.key === stage_key) || { label: stage_key, color: "#888" };

		// One primary action per state — the single next thing a floor worker
		// actually needs to do, instead of the old row of 5+ equal-weight
		// buttons. "Resume" (On Hold -> In Progress) is new: start_work_order()
		// has handled this transition correctly since the native-workflow
		// migration (picks "Resume" vs "Start" based on current status — see
		// its own docstring) but no button ever called it for an On Hold WO,
		// a real dead-end this redesign also fixes.
		let primary_btn = "";
		if (!wo.machine && wo.status === "Pending") {
			primary_btn = `<button class="ib-ps-btn-primary ib-ps-panel-primary btn btn-primary" id="ib-wo-assign-machine">Assign Machine</button>`;
		} else if (wo.status === "Pending") {
			primary_btn = `<button class="ib-ps-btn-success ib-ps-panel-primary btn btn-success" id="ib-wo-start">
					<iconify-icon icon="lucide:play" width="13" height="13" style="vertical-align:middle;margin-right:4px"></iconify-icon>Start</button>`;
		} else if (wo.status === "On Hold") {
			primary_btn = `<button class="ib-ps-btn-success ib-ps-panel-primary btn btn-success" id="ib-wo-start">
					<iconify-icon icon="lucide:play" width="13" height="13" style="vertical-align:middle;margin-right:4px"></iconify-icon>Resume</button>`;
		} else if (wo.status === "In Progress" && stage_key === "packing") {
			primary_btn = `<button class="ib-ps-btn-success ib-ps-panel-primary btn btn-success" id="ib-wo-complete">Complete</button>`;
		} else if (wo.status === "In Progress") {
			primary_btn = `<button class="ib-ps-btn-success ib-ps-panel-primary btn btn-success" id="ib-wo-advance">Next Stage →</button>`;
		}
		// Completed-at-Packing items get no action button here — Delivery
		// Note creation is a whole-Sales-Order action (a DN normally ships
		// every ready item on the order together, not one item at a time),
		// so it lives on the order itself: the Active Production Plan's
		// order card shows "Create Delivery Note" once every item on that
		// order is ready. This panel used to offer its own per-item version
		// of the same action (gated on the whole order being ready, but
		// only ever creating a DN for this one item) — confusing in
		// practice (the gate and the action operated at different
		// granularities) and removed.
		const doneNote = (wo.status === "Completed" && stage_key === "packing")
			? `<div class="ib-ps-panel-done-note">
					<iconify-icon icon="lucide:check-circle-2" width="13" height="13" style="vertical-align:middle;margin-right:4px;color:#059669"></iconify-icon>
					This item is ready. Create the Delivery Note from the order's card in Active Production Plan once every item on the order is ready.
				</div>`
			: "";

		// Everything else lives behind one "More actions" menu instead of
		// competing with the primary button for attention. Print is always
		// offered; Hold matches the real workflow (valid from Pending AND In
		// Progress, not just In Progress as the old single hold_btn assumed);
		// Adjust Qty / Move Stage keep their existing conditions.
		const can_hold = wo.status === "Pending" || wo.status === "In Progress";
		// Adjust Qty is wastage/efficiency planning for work not yet done —
		// meaningless (and, backend-enforced as of 2026-08-11, blocked) once
		// the WO is Completed/Cancelled, which also covers Delivered (a
		// Delivered WO is always status=Completed — see mark_wos_delivered).
		// Was previously gated only on target_uom, letting the option appear
		// for a WO that had already shipped.
		const can_adjust_qty = wo.status !== "Completed" && wo.status !== "Cancelled";
		// Cancel Run — cancel_run() (production_run.py) has always existed,
		// fully built (locking, batch-qty restore, genealogy reversal,
		// Order Sheet Item rollup), but no UI ever called it. Same valid-from
		// set as Hold — a run that's already Completed/Cancelled/Delivered
		// has nothing left to cancel.
		const can_cancel = wo.status === "Pending" || wo.status === "In Progress" || wo.status === "On Hold";
		// Skip Stage — skip_stage() (production_run.py) has always existed,
		// fully built (real skipped=1 stage_log entry, distinct from Move to
		// Different Stage's blunt "put it anywhere" — reassigns the next
		// stage's machine, correctly finishes the run if it was the last
		// stage), but no UI ever called it. Same bug class as Cancel Run.
		// Only valid from In Progress — matches skip_stage's own guard.
		const can_skip = wo.status === "In Progress";
		const menu_items = [
			can_hold ? `<a class="dropdown-item" href="#" id="ib-wo-hold"><iconify-icon icon="lucide:pause" width="12" height="12" style="vertical-align:middle;margin-right:6px"></iconify-icon>Put On Hold</a>` : "",
			(can_adjust_qty && (wo.target_uom === "PCS" || wo.target_uom === "SQMT"))
				? `<a class="dropdown-item" href="#" id="ib-wo-adjust-qty"><iconify-icon icon="lucide:sliders-horizontal" width="12" height="12" style="vertical-align:middle;margin-right:6px"></iconify-icon>Adjust Qty</a>`
				: "",
			can_skip
				? `<a class="dropdown-item" href="#" id="ib-wo-skip-stage"><iconify-icon icon="lucide:skip-forward" width="12" height="12" style="vertical-align:middle;margin-right:6px"></iconify-icon>Skip This Stage</a>`
				: "",
			cint(wo.produced_serials) > 0
				? `<a class="dropdown-item" href="/printview?doctype=IB Work Order&name=${encodeURIComponent(wo.name)}&format=IB Serial Label" target="_blank" id="ib-wo-serial-labels"><iconify-icon icon="lucide:qr-code" width="12" height="12" style="vertical-align:middle;margin-right:6px"></iconify-icon>Print Serial Labels (${cint(wo.produced_serials)})</a>`
				: "",
			can_cancel
				? `<a class="dropdown-item text-danger" href="#" id="ib-wo-cancel"><iconify-icon icon="lucide:x-circle" width="12" height="12" style="vertical-align:middle;margin-right:6px"></iconify-icon>Cancel Run</a>`
				: "",
		].filter(Boolean).join("");
		const more_menu = menu_items
			? `<div class="dropdown ib-ps-panel-more">
					<button class="btn btn-default btn-sm dropdown-toggle" data-toggle="dropdown" aria-expanded="false" title="More actions">
						<iconify-icon icon="lucide:more-vertical" width="14" height="14"></iconify-icon>
					</button>
					<div class="dropdown-menu dropdown-menu-right">${menu_items}</div>
				</div>`
			: "";

		// Which Sales Order/customer this WO belongs to — every other WO
		// listing on this page (Order-wise, Item-wise, Stage-wise, Job
		// Bundles) already shows this; the panel itself didn't, so a WO
		// opened from Machine-wise (the one tab with no order context in its
		// own table) had no way to tell which order it was actually for.
		const soLine = wo.sales_order
			? `<div class="ib-ps-panel-so-line">
					<span class="ib-ps-tag ib-ps-tag--so" title="Sales Order">SO</span>
					<a href="/app/sales-order/${encodeURIComponent(wo.sales_order)}" target="_blank">${frappe.utils.escape_html(wo.sales_order)}</a>
					${wo.customer_name ? `<span class="ib-ps-panel-customer">${frappe.utils.escape_html(wo.customer_name)}</span>` : ""}
				</div>`
			: "";

		const bodyHtml = `
			<div class="ib-ps-panel-inner">
				<div class="ib-ps-panel-header">
					${soLine}
					<div class="ib-ps-panel-meta">
						<span class="ib-ps-item-code">${frappe.utils.escape_html(wo.item_code || "")}</span>
						<span class="ib-ps-stage-chip" style="background:${stage.color};color:#fff">${stage.label}</span>
						${_ib_status_pill(wo.priority || "Normal", "sm")}
						${_ib_status_pill(wo.status, "sm")}
					</div>
					<div class="ib-ps-panel-meta" style="margin-top:4px">
						<span style="font-size:10px;color:var(--text-muted)">Target: <strong>${wo.target_qty || 0} ${frappe.utils.escape_html(wo.target_uom || "—")}</strong></span>
					</div>
					<div class="ib-ps-panel-meta" style="margin-top:4px">
						<span style="font-size:10px;color:var(--text-muted)">Created: ${wo.creation ? frappe.datetime.str_to_user(wo.creation) : "—"}</span>
						<span style="font-size:10px;color:var(--text-muted)">ETD: ${wo.delivery_date ? frappe.datetime.str_to_user(wo.delivery_date) : "—"}</span>
					</div>
					${wo.machine ? `<div class="ib-ps-panel-machine">Machine: <strong>${frappe.utils.escape_html(wo.machine)}</strong></div>` : ""}
				</div>

				<div class="ib-ps-panel-actions">
					${primary_btn}${more_menu}
				</div>
				${doneNote}
				${(wo.pcs_to_make || wo.logs_to_make) ? `<div class="ib-ps-panel-machine" style="padding:0 0 8px">
					${wo.target_uom === "PCS" ? `Pieces to Make: <strong>${wo.pcs_to_make || 0}</strong>` : ""}
					${wo.target_uom === "SQMT" ? `Logs to Make: <strong>${wo.logs_to_make || 0}</strong>` : ""}
				</div>` : ""}
				${wo.jumbo_roll ? `<div class="ib-ps-panel-machine" style="padding:0 0 8px">Jumbo Roll: <strong>${frappe.utils.escape_html(wo.jumbo_roll)}</strong></div>` : ""}
			</div>`;

		// A modal dialog (Frappe's own native component) instead of the
		// previous custom slide-in-from-right drawer — same content, less
		// custom chrome to maintain (backdrop click-outside, Escape-to-close,
		// and open/close animation all come from Dialog for free instead of
		// hand-rolled CSS), and it reads as "modern" because it's the exact
		// same modal shell every other dialog in this app already uses.
		// Reused in place across re-renders within one open "session" (Start,
		// Assign Machine, etc. all re-render the same dialog rather than
		// closing and reopening) — closing it (onhide) drops the reference so
		// the next _open_wo_panel starts fresh.
		if (!this._wo_dialog) {
			this._wo_dialog = new frappe.ui.Dialog({});
			this._wo_dialog.onhide = () => {
				this.active_wo = null;
				this._wo_dialog = null;
			};
		}
		const d = this._wo_dialog;
		d.set_title(wo.name || "Work Order");
		d.$body.html(bodyHtml);
		// Bootstrap's modal("show") is safe to call even if already shown (a
		// harmless no-op on the already-open case) — simpler and more
		// reliable than trying to track open/closed state ourselves.
		d.show();
		const $panel = d.$body;

		// $panel's content is fully replaced by .html() on every re-render, but
		// delegated listeners bound to the (persistent) $body node itself stack
		// up across re-renders unless cleared first — .off("click") before every
		// .on() below is what prevents that (this was the historical cause of
		// "Create Delivery Note" firing multiple times and creating duplicate
		// DNs, back when the equivalent bug hit the old slide-in panel).
		$panel.off("click");
		// Every state-transition button below shares one guard: disable
		// immediately on click, before the RPC round-trip, so a fast
		// double-click (or a slow network) can't fire the same transition
		// twice while the panel is still showing the pre-click state. The
		// panel re-renders with a fresh button (a different id, since the
		// primary button changes per status — see _render_wo_panel) once the
		// call lands, so there's nothing to explicitly re-enable on success;
		// only re-enable on failure, same as the Create Delivery Note guard
		// this pattern was lifted from.
		const guarded = (selector, fn) => {
			$panel.on("click", selector, (e) => {
				const $btn = $(e.currentTarget);
				if ($btn.prop("disabled")) return;
				$btn.prop("disabled", true);
				fn($btn);
			});
		};
		// Assign Machine only opens a picker dialog here — the real RPC (and
		// its own guard) fires later from the dialog's primary action, so this
		// one is deliberately NOT wrapped: disabling it now with nothing to
		// re-enable it if the dialog is cancelled would strand the button.
		$panel.on("click", "#ib-wo-assign-machine", () => this._assign_machine_to_wo(wo, stage_key));
		guarded("#ib-wo-start", () => this._update_wo_status(wo, "In Progress", stage_key));
		guarded("#ib-wo-hold", () => this._update_wo_status(wo, "On Hold", stage_key));
		// Advance/Complete open a dialog first (asks actual output → wastage),
		// same reasoning as Assign Machine just above for staying unwrapped by
		// guarded() — the real RPC (and its own disabled-state handling) only
		// fires from the dialog's primary action; wrapping the opening click
		// would strand the button disabled forever if the dialog is cancelled.
		$panel.on("click", "#ib-wo-advance", () => _prompt_actual_output(wo, (qty) => this._advance_wo(wo, stage_key, qty)));
		$panel.on("click", "#ib-wo-complete", () => _prompt_actual_output(wo, (qty) => this._update_wo_status(wo, "Completed", stage_key, qty)));
		$panel.on("click", "#ib-wo-adjust-qty", (e) => { e.preventDefault(); this._show_adjust_qty_dialog(wo, stage_key); });
		// Not wrapped in guarded() — opens a confirm prompt first; the real
		// RPC (and its own disabled-state handling) only fires once the
		// operator actually confirms, same reasoning as Assign Machine/
		// Advance/Complete above.
		$panel.on("click", "#ib-wo-cancel", (e) => { e.preventDefault(); this._cancel_wo(wo, stage_key); });
		// Not wrapped in guarded() — same reasoning as Cancel Run just above.
		$panel.on("click", "#ib-wo-skip-stage", (e) => { e.preventDefault(); this._skip_stage(wo, stage_key); });
	}

	// Marks the current stage skipped (no work done) in the run's real
	// stage_log, then moves on to the next stage — distinct from Move to
	// Different Stage's blunt escape hatch, which doesn't record a skip.
	_skip_stage(wo, stage_key) {
		const stage = IB_STAGES.find((s) => s.key === stage_key) || { label: stage_key };
		frappe.confirm(
			`Skip <strong>${stage.label}</strong> for this run without recording any work done, and move on to the next stage?`,
			() => {
				frappe.call({
					method: "instabiz.overrides.production.skip_work_order_stage",
					args: { work_order: wo.name },
					callback: (r) => {
						if (r.exc) {
							frappe.show_alert({ message: "Failed to skip stage.", indicator: "red" });
							return;
						}
						frappe.show_alert({ message: (r.message && r.message.message) || "Stage skipped.", indicator: "green" }, 3);
						this._close_side_panel();
						this.refresh();
					},
				});
			},
		);
	}

	// Destructive — asks for a reason and a real confirmation before calling
	// cancel_work_order(). Reverses any genealogy already produced (FG batch/
	// serials) and restores the source batch's reserved qty; see
	// production_run.cancel_run's own docstring for the full effect.
	_cancel_wo(wo, stage_key) {
		const d = new frappe.ui.Dialog({
			title: `Cancel Run — ${wo.item_code || wo.name}`,
			fields: [
				{
					fieldtype: "HTML",
					options: `<div style="font-size:12px;color:var(--text-muted);margin-bottom:8px">
						This cancels the whole production run for this item, not just the
						current stage. Any material reserved from its source batch is
						restored; any Finished Goods batch/serials already generated by
						this run are reversed.
					</div>`,
				},
				{ fieldtype: "Small Text", fieldname: "reason", label: "Reason (optional)" },
			],
			primary_action_label: "Cancel Run",
			primary_action: (values) => {
				d.hide();
				frappe.call({
					method: "instabiz.overrides.production.cancel_work_order",
					args: { work_order: wo.name, reason: values.reason || null },
					callback: (r) => {
						if (r.exc) {
							frappe.show_alert({ message: "Failed to cancel run.", indicator: "red" });
							return;
						}
						frappe.show_alert({ message: "Run cancelled.", indicator: "green" }, 3);
						this._close_side_panel();
						this.refresh();
					},
				});
			},
		});
		d.show();
		d.$wrapper.find(".btn-primary").removeClass("btn-primary").addClass("btn-danger");
	}

	// Dormant, not deleted — same precedent as this file's other removed-from-
	// UI-but-kept-working functions (Seat Map/Live Floor, Link Jumbo Roll).
	// Used to power a per-item "Create Delivery Note" slot in the WO panel;
	// removed because the gate (get_order_dn_readiness, whole-order-level) and
	// the action (custom_make_delivery_note scoped to just this WO's item)
	// operated at different granularities — confusing, since the button only
	// appeared once the WHOLE order was ready but only ever shipped ONE item.
	// The Active Production Plan's own order-level "Create Delivery Note"
	// (correctly SO-scoped, no per-item restriction) is the real one.
	_hydrate_dn_slot($panel, wo) {
		frappe.call({
			method: "instabiz.overrides.production.get_order_dn_readiness",
			args: { order_sheet: wo.order_sheet },
			callback: (r) => {
				const $slot = $panel.find("#ib-wo-dn-slot");
				if (!$slot.length) return; // panel moved on to a different WO meanwhile
				if (r.message && r.message.ready) {
					$slot.replaceWith(
						`<button class="ib-ps-btn-primary ib-ps-panel-btn btn btn-primary btn-sm" id="ib-wo-create-dn">
							<iconify-icon icon="lucide:truck" width="11" height="11" style="vertical-align:middle;margin-right:3px"></iconify-icon>
							Create Delivery Note
						</button>`
					);
				} else {
					$slot.replaceWith(
						`<span style="font-size:11px;color:var(--text-muted);display:inline-flex;align-items:center"
							title="Every item on this Sales Order needs to finish production before a Delivery Note can be created">
							<iconify-icon icon="lucide:clock" width="11" height="11" style="vertical-align:middle;margin-right:3px"></iconify-icon>
							Waiting for other items
						</span>`
					);
				}
			},
		});
	}

	// Bulk Print Job Order — from the Order-wise list's Actions column.
	// Was previously N separate full Job Order pages concatenated via
	// Frappe's core multi-doc endpoint (download_multi_pdf) — structurally
	// can never produce one page, it just loops print() per doc and glues
	// the PDFs together. Replaced with a single-doc print of the Order
	// Sheet itself using the dedicated "IB Job Order Summary" print format
	// (instabiz/instabiz/print_format/ib_job_order_summary/), which renders
	// every item's current actionable Work Order as one compact table on
	// one page. Still checks get_order_sheet_wo_names() first so a fully
	// Completed order shows the same "nothing to print" alert as before,
	// instead of opening a print view with an empty table.
	_print_job_orders_for_os(os_name) {
		// Was checking get_order_sheet_wo_names() — the "one currently-
		// actionable WO per item" list, which is empty by design once every
		// item is fully Completed (nothing left to hand a floor worker) — so
		// printing the summary for a 100%-done order was silently blocked
		// with "no active Work Orders", even though the actual print format
		// (IB Job Order Summary) is driven by get_order_sheet_stage_workflow()
		// and renders a full historical stage x machine x operator grid
		// regardless of completion status. Check the real data source instead.
		frappe.call({
			method: "instabiz.overrides.production.get_order_sheet_stage_workflow",
			args: { order_sheet: os_name },
			callback: (r) => {
				const rows = (r.message && r.message.rows) || [];
				if (!rows.length) {
					frappe.show_alert({
						message: "No items to print for this order.",
						indicator: "orange",
					});
					return;
				}
				const w = window.open(
					"/api/method/frappe.utils.print_format.download_pdf?" +
						"doctype=" + encodeURIComponent("IB Order Sheet") +
						"&name=" + encodeURIComponent(os_name) +
						"&format=" + encodeURIComponent("IB Job Order Summary") +
						"&no_letterhead=0"
				);
				if (!w) {
					frappe.show_alert({ message: "Please enable pop-ups.", indicator: "orange" });
				}
			},
		});
	}

	// Factory-manager qty reconciliation dialog — lets them set pcs_to_make
	// (UOM=PCS) or logs_to_make (UOM=SQMT) to account for wastage/efficiency.
	// Pre-fills the current value via frappe.client.get_value since the `wo`
	// object here comes from whichever tab's list query opened the panel, and
	// none of those queries select these two new fields.
	_show_adjust_qty_dialog(wo, stage_key) {
		const is_pcs = wo.target_uom === "PCS";
		const fieldname = is_pcs ? "pcs_to_make" : "logs_to_make";
		const label = is_pcs ? "Pieces to Make" : "Logs to Make";
		frappe.call({
			method: "frappe.client.get_value",
			args: { doctype: "IB Work Order", filters: wo.name, fieldname },
			callback: (r) => {
				const current = (r.message && r.message[fieldname]) || 0;
				const d = new frappe.ui.Dialog({
					title: `Adjust ${label}`,
					fields: [
						{
							fieldname: "item_uom_note",
							fieldtype: "HTML",
							options: `<div style="margin-bottom:8px;color:var(--text-muted);font-size:12px">Item UOM: <strong>${frappe.utils.escape_html(wo.target_uom || "—")}</strong> — target qty <strong>${wo.target_qty || 0} ${frappe.utils.escape_html(wo.target_uom || "")}</strong></div>`,
						},
						{
							fieldname,
							label,
							fieldtype: "Int",
							reqd: 1,
							default: current,
							description: "Reconcile for wastage — set the actual quantity to produce from this Work Order's target qty.",
						},
					],
					primary_action_label: "Save",
					primary_action: (vals) => {
						const args = { work_order: wo.name };
						args[fieldname] = vals[fieldname];
						frappe.call({
							method: "instabiz.overrides.production.update_production_qty",
							args,
							callback: (r2) => {
								if (r2.exc) {
									frappe.show_alert({ message: `Failed to update ${label}.`, indicator: "red" });
									return;
								}
								frappe.show_alert({ message: `${label} updated.`, indicator: "green" });
								wo[fieldname] = vals[fieldname];
								d.hide();
								this._render_wo_panel(wo, stage_key);
								// Refresh whichever list is behind the panel so the
								// adjusted-qty badge shows without a manual reload.
								this.refresh();
							},
						});
					},
				});
				d.show();
			},
		});
	}

	_assign_machine_to_wo(wo, stage_key) {
		const stage_label = IB_STAGES.find((s) => s.key === stage_key)?.label || "";
		const machine_type = STAGE_MACHINE_TYPE[stage_label] || stage_label;
		frappe.call({
			method: "instabiz.overrides.production.get_machines",
			args: { machine_type, status: "Active" },
			callback: (r) => {
				const machines = (r.message || []).map((m) => ({ label: `${m.machine_code} — ${m.machine_name}`, value: m.name || m.machine_code }));
				if (!machines.length) {
					frappe.show_alert({ message: "No active machines available.", indicator: "orange" });
					return;
				}
				const d = new frappe.ui.Dialog({
					title: "Assign Machine",
					fields: [
						{
							fieldname: "machine",
							label: "Machine",
							fieldtype: "Select",
							options: machines.map((m) => m.value),
							reqd: 1,
						},
					],
					primary_action_label: "Assign",
					primary_action: (vals) => {
						frappe.call({
							method: "instabiz.overrides.production.assign_machine_to_wo",
							args: { work_order: wo.name, machine: vals.machine },
							callback: (r2) => {
								if (r2.exc) {
									frappe.show_alert({ message: "Failed to assign machine.", indicator: "red" });
									return;
								}
								frappe.show_alert({ message: "Machine assigned.", indicator: "green" });
								d.hide();
								wo.machine = vals.machine;
								this._render_wo_panel(wo, stage_key);
							},
						});
					},
				});
				d.show();
			},
		});
	}

	// Undoes the click-guard's disable when an RPC fails and the panel isn't
	// re-rendering (so there's no fresh, enabled button coming to replace it).
	_reenable_panel_buttons() {
		if (!this._wo_dialog) return;
		this._wo_dialog.$body.find(".ib-ps-panel-primary, #ib-wo-hold").prop("disabled", false);
	}

	_update_wo_status(wo, new_status, stage_key, actual_qty) {
		const method_map = {
			"In Progress": "instabiz.overrides.production.start_work_order",
			"On Hold": "instabiz.overrides.production.hold_work_order",
			"Completed": "instabiz.overrides.production.complete_work_order",
		};
		const method = method_map[new_status];
		if (!method) return;
		const args = { work_order: wo.name };
		if (new_status === "Completed" && actual_qty !== undefined) args.actual_qty = actual_qty;
		frappe.call({
			method,
			args,
			callback: (r) => {
				if (r.exc) {
					frappe.show_alert({ message: `Failed to set status to ${new_status}.`, indicator: "red" });
					// Panel isn't re-rendering on failure (still showing the
					// pre-click state), so the click guard's disabled button
					// has to be explicitly freed here or it'd be stuck forever.
					this._reenable_panel_buttons();
					return;
				}
				frappe.show_alert({ message: `Status updated to ${new_status}.`, indicator: "green" });
				wo.status = new_status;
				this._render_wo_panel(wo, stage_key);
				// Refresh whichever list is behind the panel so counts/rows update
				this.refresh();
			},
		});
	}

	// Advance the run's CURRENT stage forward. WO-per-run model (2026-09-10
	// onward): this is the SAME IB Work Order moving to its next
	// current_stage in place — no new run is created or needed. Real
	// regression, found live: this function still carried the pre-rewrite
	// JIT-per-stage-WO behavior (stale comment: "no next Work Order is
	// auto-created... the Start Production picker opens immediately"),
	// which under the OLD model was correct (each stage really was its own
	// separate WO that had to be freshly started) but under the run model
	// means every single "advance to next stage" click — except the very
	// last stage — immediately popped open a SECOND "Start Production"
	// dialog offering to create a brand-new, duplicate run for the item at
	// the stage the backend had just already advanced the real run to.
	// Confirmed via advance_run()'s own return shape (production_run.py):
	// `next_stage` is truthy on every non-final advance, so this fired on
	// nearly every click. Fixed: a normal advance just refreshes — the run
	// object updates itself, there's nothing further to prompt for. Only
	// exception (already correctly handled by advance_with_length_split)
	// is a length-split response, which returns next_stage: null and
	// already just refreshes as several new runs replace this one.
	_advance_wo(wo, stage_key, actual_qty) {
		_advance_with_split_check(
			wo.name, actual_qty,
			(msg) => {
				frappe.show_alert({ message: msg.message || "Advanced.", indicator: "green" }, 3);
				this._close_side_panel();
				this.refresh();
			},
			(err) => {
				frappe.show_alert({ message: err, indicator: "red" });
				this._reenable_panel_buttons();
			},
		);
	}

	// Reached Completed at Packing for this item — jump straight to
	// creating the Delivery Note off the underlying Sales Order.
	_create_dn_for_wo(wo) {
		if (!wo.sales_order) {
			frappe.show_alert({ message: "No Sales Order linked to this Work Order.", indicator: "red" });
			return;
		}
		frappe.call({
			method: "instabiz.overrides.sales_order.custom_make_delivery_note",
			// order_sheet_item scopes the DN to the exact Sales Order Item row
			// this WO is for (resolved server-side via IB Order Sheet Item's
			// sales_order_item field) — item_code alone would incorrectly pull
			// every line sharing that item_code if the SO has the same item on
			// multiple separate rows with different quantities. item_code kept
			// as a fallback for legacy WOs from before this field existed.
			args: { source_name: wo.sales_order, order_sheet_item: wo.order_sheet_item, item_code: wo.item_code },
			callback: (r) => {
				if (!r.message) {
					frappe.show_alert({ message: "Failed to create Delivery Note.", indicator: "red" });
					return;
				}
				frappe.model.sync(r.message);
				frappe.set_route("Form", r.message.doctype, r.message.name);
			},
		});
	}

	// -----------------------------------------------------------------------
	// Helpers
	// -----------------------------------------------------------------------
	_stage_color(stage_key) {
		const s = IB_STAGES.find((x) => x.label === stage_key || x.key === (stage_key || "").toLowerCase().replace(/ /g, "_"));
		return s ? s.color : "#888";
	}

	// -----------------------------------------------------------------------
	// CSS injection
	// -----------------------------------------------------------------------
	_inject_styles() {
		if (document.getElementById("ib-ps-styles")) return;
		const css = `
/* ============================================================
   IB Production Stages — Page Styles
   ============================================================ */
/* Tabs toolbar */
.ib-ps-tabs {
	display: flex;
	align-items: center;
	gap: 6px;
	padding: 12px 16px 8px;
	border-bottom: 1px solid var(--border-color);
	flex-wrap: wrap;
}
.ib-ps-tab {
	padding: 5px 16px;
	border-radius: 20px;
	border: 1px solid var(--border-color);
	background: var(--card-bg);
	color: var(--text-color);
	font-size: 13px;
	font-family: inherit;
	cursor: pointer;
	transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.ib-ps-tab:hover { border-color: var(--ib-primary); color: var(--ib-primary); }
.ib-ps-tab.active {
	background: var(--ib-primary);
	border-color: var(--ib-primary);
	color: #fff;
	font-weight: 600;
}
.ib-ps-tab-badge {
	display: inline-block; margin-left: 4px; padding: 0 6px;
	border-radius: 10px; font-size: 10px; font-weight: 700;
	background: rgba(0,0,0,0.08); vertical-align: middle;
}
.ib-ps-tab.active .ib-ps-tab-badge { background: rgba(255,255,255,0.25); }
.ib-sw-pills { display: flex; gap: 6px; flex-wrap: wrap; }
.ib-ps-refresh-btn {
	margin-left: auto;
	display: flex; align-items: center; gap: 5px;
	padding: 5px 12px;
	border-radius: 6px;
	border: 1px solid var(--border-color);
	background: var(--card-bg);
	color: var(--text-muted);
	font-size: 12px;
	font-family: inherit;
	cursor: pointer;
}
.ib-ps-refresh-btn:hover { border-color: var(--ib-primary); color: var(--ib-primary); }

/* Content area */
.ib-ps-content { padding: 16px; min-height: 200px; }

/* Loading / empty */
.ib-ps-loading { padding: 40px; text-align: center; color: var(--text-muted); font-size: 14px; }
.ib-ps-empty   { padding: 40px; text-align: center; color: var(--text-muted); font-size: 13px; }

/* ----------------------------------------------------------------
   Pipeline Kanban
   ---------------------------------------------------------------- */
.ib-ps-pipeline {
	display: flex;
	gap: 12px;
	overflow-x: auto;
	padding-bottom: 12px;
}
.ib-ps-col {
	min-width: 250px;
	flex: 0 0 250px;
	background: var(--fg-color, #f9fafb);
	border-radius: 8px;
	border: 1px solid var(--border-color);
	display: flex;
	flex-direction: column;
	max-height: calc(100vh - 200px);
}
.ib-ps-col-header {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 10px 12px 8px;
	flex-shrink: 0;
}
.ib-ps-col-title { font-size: 12px; font-weight: 600; color: var(--text-color); display: flex; align-items: center; gap: 5px; }
.ib-ps-col-icon { display: flex; align-items: center; flex-shrink: 0; }
.ib-ps-count-badge {
	font-size: 11px; font-weight: 700;
	color: #fff; padding: 1px 7px;
	border-radius: 10px; min-width: 20px;
	text-align: center;
}
.ib-ps-col-body {
	overflow-y: auto;
	flex: 1;
	padding: 6px;
	display: flex;
	flex-direction: column;
	gap: 6px;
}
.ib-ps-col-empty { padding: 20px; text-align: center; color: var(--text-muted); font-size: 12px; }

/* WO Cards */
.ib-ps-wo-card {
	background: var(--card-bg);
	border: 1px solid var(--border-color);
	border-radius: 8px;
	padding: 10px 10px 8px;
	cursor: pointer;
	transition: transform 0.1s, box-shadow 0.15s, border-color 0.15s;
}
.ib-ps-wo-card:hover {
	transform: translateY(-2px);
	box-shadow: 0 4px 14px rgba(0,0,0,0.10);
	border-color: var(--ib-primary);
}
.ib-ps-wo-card--loading {
	opacity: 0.5;
	pointer-events: none;
}
.ib-ps-card-top {
	display: flex;
	justify-content: space-between;
	align-items: flex-start;
	gap: 6px;
	margin-bottom: 3px;
}
.ib-ps-item-code { font-size: 11px; font-weight: 700; color: var(--text-color); word-break: break-all; line-height: 1.3; }
.ib-ps-card-customer {
	font-size: 11px; color: var(--text-muted);
	margin-bottom: 5px;
	white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.ib-ps-card-chips { display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: 6px; }
.ib-ps-card-meta { display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: 6px; }
.ib-ps-qty-chip {
	font-size: 10px; font-weight: 600;
	background: var(--fg-color, #f3f4f6); color: var(--text-color);
	border-radius: 4px; padding: 1px 6px;
}
.ib-ps-machine-chip--unset { background: #fef9c3; color: #78350f; }

/* Card action buttons */
.ib-ps-card-actions {
	display: flex; gap: 4px;
	margin-top: 7px; padding-top: 7px;
	border-top: 1px solid var(--border-color);
}
.ib-ps-action-btn {
	flex: 1; padding: 4px 6px;
	border-radius: 5px; border: 1px solid transparent;
	font-size: 11px; font-family: inherit; font-weight: 600;
	cursor: pointer; white-space: nowrap;
	transition: opacity 0.12s, transform 0.1s;
}
.ib-ps-action-btn:hover  { opacity: 0.82; transform: translateY(-1px); }
.ib-ps-action-btn:active { transform: translateY(0); opacity: 1; }
.ib-ps-action-start   { background: #dcfce7; color: #15803d; border-color: #bbf7d0; }
.ib-ps-action-start:hover { background: #bbf7d0; }
.ib-ps-action-advance { background: #dbeafe; color: #1d4ed8; border-color: #bfdbfe; }
.ib-ps-action-advance:hover { background: #bfdbfe; }
.ib-ps-action-hold-btn { flex: 0 0 auto; background: #fffbeb; color: #92400e; border-color: #fde68a; padding: 4px 8px; }
.ib-ps-action-hold-btn:hover { background: #fde68a; }

/* Priority badges + Status chips: rendered via _ib_status_pill() as Frappe's
   own .indicator-pill (theme-aware --bg-{color}/--text-on-{color} tokens) —
   no custom color CSS needed here anymore. This is only a density override:
   Frappe's default pill (20px tall, "sm" text style) is roomy for a table
   packed with several per row, so .ib-ps-pill-sm shrinks padding/font while
   keeping every color/theme rule native. */
.ib-ps-pill-sm {
	height: auto; padding: 1px 7px 1px 5px; font-size: 10px; font-weight: 600;
}
.ib-ps-pill-sm::before { height: 5px; width: 5px; margin-right: 4px; }

/* Machine chip */
.ib-ps-machine-chip {
	font-size: 10px; background: #f3f4f6; color: var(--text-color);
	border-radius: 4px; padding: 1px 6px; font-family: monospace;
}

/* Stage chip (used in sub-lists) */
.ib-ps-stage-chip {
	font-size: 10px; color: #fff; font-weight: 600;
	border-radius: 4px; padding: 2px 7px; display: inline-block;
}

/* Progress bar */
.ib-ps-progress-wrap {
	height: 5px; background: var(--border-color);
	border-radius: 3px; overflow: hidden;
	margin-bottom: 3px;
}
.ib-ps-progress-bar { height: 100%; border-radius: 3px; transition: width 0.3s; }
/* Subtle moving stripe on an In-Progress row's own fill — "this one is
   actively running right now", distinct from a static/paused bar at the
   same %. Only the filled portion animates (background-size 200%, not the
   wrapper), so it reads correctly at any fill level including near-0%. */
.ib-ps-progress-wrap--running .ib-ps-progress-bar {
	background-image: linear-gradient(
		135deg, rgba(255,255,255,.35) 25%, transparent 25%, transparent 50%,
		rgba(255,255,255,.35) 50%, rgba(255,255,255,.35) 75%, transparent 75%, transparent
	);
	background-size: 14px 14px;
	animation: ib-ps-progress-stripe 1s linear infinite;
}
@keyframes ib-ps-progress-stripe { from { background-position: 0 0; } to { background-position: 14px 0; } }
@media (prefers-reduced-motion: reduce) {
	.ib-ps-progress-wrap--running .ib-ps-progress-bar { animation: none; }
}
.ib-ps-progress-label { font-size: 10px; color: var(--text-muted); }

/* Work Order stage-pill chips (Order-wise tab) — same visual language as the
   Production Dashboard's stagePills (_render_plan in ib_production_dashboard.js),
   swapped in for the old always-expanded <li> list of full WO name/status/qty/date. */
.ib-ps-wo-chip-row { display: flex; gap: 4px; flex-wrap: wrap; align-items: center; }
.ib-ps-wo-chip {
	font-weight: 700; letter-spacing: .03em; cursor: pointer;
	transition: transform 0.1s, box-shadow 0.15s;
}
.ib-ps-wo-chip:hover { transform: translateY(-1px); box-shadow: 0 2px 6px rgba(0,0,0,0.12); }
.ib-ps-wo-chip--cancelled { text-decoration: line-through; }
/* Genuinely running right now — a soft pulse so "In Progress" reads as
   actively moving, not a static blue label sitting next to a green "done"
   one. Same keyframe shape as the Dashboard's own .ib-pd-stg--live so a
   chip means the same thing (and pulses the same way) on both pages. */
.ib-ps-wo-chip--live { animation: ib-ps-wo-chip-pulse 1.6s ease-in-out infinite; }
@keyframes ib-ps-wo-chip-pulse {
	0%, 100% { box-shadow: 0 0 0 0 rgba(29, 78, 216, 0.35); }
	50%      { box-shadow: 0 0 0 4px rgba(29, 78, 216, 0); }
}
@media (prefers-reduced-motion: reduce) {
	.ib-ps-wo-chip--live { animation: none; }
}
.ib-ps-wo-chip-progress { display: flex; align-items: center; gap: 6px; margin-top: 4px; }
.ib-ps-wo-chip-progress-wrap {
	height: 5px; width: 60px; background: var(--border-color);
	border-radius: 3px; overflow: hidden; display: inline-block; vertical-align: middle;
}
.ib-ps-wo-chip-progress small { font-size: 10px; color: var(--text-muted); white-space: nowrap; }

/* ----------------------------------------------------------------
   Order Sheet / Tables
   ---------------------------------------------------------------- */
.ib-ps-os-toolbar {
	display: flex;
	align-items: center;
	gap: 10px;
	padding-bottom: 12px;
	flex-wrap: wrap;
}
.ib-ps-filter-group {
	display: flex;
	align-items: center;
	gap: 6px;
	font-size: 13px;
	color: var(--text-muted);
}
.ib-ps-filter-group--search {
	flex: 1;
	min-width: 200px;
	max-width: 320px;
	background: var(--card-bg);
	border: 1px solid var(--border-color);
	border-radius: 6px;
	padding: 5px 10px;
}
.ib-ps-filter-group--search input {
	border: none; background: none; outline: none; flex: 1;
	font-size: 13px; color: var(--text-color); padding: 0;
}
.ib-ps-select {
	padding: 5px 10px;
	border: 1px solid var(--border-color);
	border-radius: 6px;
	background: var(--card-bg);
	font-size: 13px;
	font-family: inherit;
	color: var(--text-color);
}
.ib-ps-table-wrap { overflow-x: auto; }
.ib-ps-table {
	width: 100%;
	border-collapse: collapse;
	font-size: 12px;
}
.ib-ps-table thead th {
	background: var(--fg-color, #f9fafb);
	padding: 6px 10px;
	text-align: left;
	border-bottom: 1px solid var(--border-color);
	font-weight: 600;
	font-size: 11px;
	color: var(--text-muted);
}
.ib-ps-table tbody tr {
	border-bottom: 1px solid var(--border-color);
	cursor: pointer;
	transition: background 0.1s;
}
.ib-ps-table tbody tr:hover { background: var(--fg-color, #f9fafb); }
.ib-ps-table td { padding: 6px 10px; vertical-align: middle; }
.ib-ps-os-link { color: var(--ib-primary); text-decoration: none; font-weight: 600; }
.ib-ps-os-link:hover { text-decoration: underline; }
.ib-ps-item-code-sub { font-family: monospace; font-size: 10.5px; color: var(--text-muted); margin-top: 1px; }

/* ----------------------------------------------------------------
   Order Sheet Detail
   ---------------------------------------------------------------- */
.ib-ps-detail-header {
	display: flex;
	align-items: center;
	gap: 16px;
	padding-bottom: 12px;
	border-bottom: 1px solid var(--border-color);
	margin-bottom: 12px;
	flex-wrap: wrap;
}
.ib-ps-back-btn {
	padding: 5px 12px;
	border: 1px solid var(--border-color);
	border-radius: 6px;
	background: var(--card-bg);
	font-size: 12px; font-family: inherit;
	cursor: pointer; white-space: nowrap;
	color: var(--text-color);
}
.ib-ps-back-btn:hover { border-color: var(--ib-primary); color: var(--ib-primary); }
.ib-ps-detail-meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ib-ps-detail-name { font-size: 15px; font-weight: 700; color: var(--text-color); }
.ib-ps-detail-customer { font-size: 13px; color: var(--text-muted); }

/* Pulse animation */
@keyframes ib-ps-pulse {
	0%, 100% { opacity: 1; }
	50%       { opacity: 0.5; }
}
.ib-ps-pulse { animation: ib-ps-pulse 1.5s ease-in-out infinite; }

/* Sub WO list */
.ib-ps-wo-sub-list { list-style: none; margin: 0; padding: 0; }
.ib-ps-wo-sub-item {
	display: flex; align-items: center; gap: 8px;
	font-size: 12px; padding: 3px 0;
	color: var(--text-color);
}
.ib-ps-wo-sub-item--clickable {
	cursor: pointer; border-radius: 4px; padding: 3px 6px; margin: 0 -6px;
	transition: background .12s;
}
.ib-ps-wo-sub-item--clickable:hover { background: var(--subtle-fg, #f8fafc); }
tr.ib-ps-wo-sub-item--clickable { cursor: pointer; }
tr.ib-ps-wo-sub-item--clickable:hover td { background: var(--subtle-fg, #f8fafc); }

/* ----------------------------------------------------------------
   Machines grid
   ---------------------------------------------------------------- */
.ib-ps-machines-grid {
	display: grid;
	grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
	gap: 12px;
}
.ib-ps-machine-master-card {
	background: var(--card-bg);
	border: 1px solid var(--border-color);
	border-radius: 8px;
	padding: 14px;
	display: flex; flex-direction: column; gap: 8px;
}
.ib-ps-machine-master-top {
	display: flex; flex-direction: column; gap: 4px;
}
.ib-ps-machine-code { font-family: monospace; font-size: 12px; color: var(--ib-primary); }
.ib-ps-machine-name { font-size: 14px; font-weight: 700; color: var(--text-color); }
.ib-ps-machine-master-meta { display: flex; gap: 6px; flex-wrap: wrap; }
.ib-ps-machine-master-stats { font-size: 12px; color: var(--text-muted); display: flex; flex-direction: column; gap: 2px; }

.ib-ps-type-chip {
	font-size: 10px; font-weight: 600;
	background: #ede9fe; color: #5b21b6;
	border-radius: 4px; padding: 2px 7px;
}
.ib-ps-location-badge {
	font-size: 10px; font-weight: 600;
	background: #f3f4f6; color: #374151;
	border-radius: 4px; padding: 2px 7px;
	text-transform: capitalize;
}


/* ----------------------------------------------------------------
   Buttons
   ---------------------------------------------------------------- */
.ib-ps-btn-primary {
	padding: 6px 14px;
	border-radius: 6px;
	border: none;
	background: var(--ib-primary);
	color: #fff; font-size: 13px;
	font-family: inherit; cursor: pointer;
	font-weight: 600;
	transition: opacity 0.15s;
}
.ib-ps-btn-primary:hover { opacity: 0.88; }
.ib-ps-btn-success {
	padding: 6px 14px;
	border-radius: 6px;
	border: none;
	background: #16a34a;
	color: #fff; font-size: 13px;
	font-family: inherit; cursor: pointer;
	font-weight: 600;
}
.ib-ps-btn-success:hover { background: #15803d; }
.ib-ps-btn-warn {
	padding: 6px 14px;
	border-radius: 6px;
	border: none;
	background: #d97706;
	color: #fff; font-size: 13px;
	font-family: inherit; cursor: pointer;
	font-weight: 600;
}
.ib-ps-btn-warn:hover { background: #b45309; }
.ib-ps-btn-sm {
	padding: 4px 10px;
	border-radius: 5px;
	border: 1px solid var(--border-color);
	background: var(--card-bg);
	font-size: 12px; font-family: inherit;
	cursor: pointer; color: var(--text-color);
}
.ib-ps-btn-sm:hover { border-color: var(--ib-primary); color: var(--ib-primary); }

/* ----------------------------------------------------------------
   WO detail panel — rendered inside a frappe.ui.Dialog's own body
   (native modal chrome: backdrop, Escape-to-close, header/close button,
   open/close animation all come from Dialog itself, nothing custom here).
   ---------------------------------------------------------------- */
.ib-ps-panel-inner { display: flex; flex-direction: column; }
.ib-ps-panel-header {
	padding-bottom: 12px;
	border-bottom: 1px solid var(--border-color);
	margin-bottom: 12px;
}
.ib-ps-panel-meta { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.ib-ps-panel-so-line {
	display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
	margin-bottom: 8px; font-size: 13px;
}
.ib-ps-panel-so-line a { font-weight: 700; color: var(--ib-primary, #d97757); text-decoration: none; }
.ib-ps-panel-so-line a:hover { text-decoration: underline; }
.ib-ps-panel-customer { font-weight: 600; color: var(--text-color); }
.ib-ps-tag {
	display: inline-block; font-size: 9.5px; font-weight: 800;
	letter-spacing: .03em; border-radius: 4px; padding: 1px 5px;
	vertical-align: middle;
}
.ib-ps-tag--so { background: #dbeafe; color: #1e3a8a; }
.ib-ps-panel-done-note {
	display: flex; align-items: flex-start; gap: 4px;
	font-size: 12px; color: var(--text-color);
	background: var(--subtle-fg, #f8fafc);
	border: 1px solid var(--border-color);
	border-radius: 6px;
	padding: 8px 10px;
	margin: 0 0 8px;
	line-height: 1.5;
}
.ib-ps-panel-machine { font-size: 12px; color: var(--text-muted); margin-top: 6px; }
.ib-ps-panel-actions {
	padding: 12px 16px;
	display: flex; gap: 8px; align-items: stretch;
	border-bottom: 1px solid var(--border-color);
	flex-shrink: 0;
}
.ib-ps-panel-btn { /* inherits from btn classes */ }
/* One prominent primary action, full-width — replaces the old row of 5+
   equal-weight buttons (Assign/Start/Hold/Complete/Advance/DN all competing
   for attention at once). */
.ib-ps-panel-primary { flex: 1; padding: 8px 14px; font-size: 13px; }
.ib-ps-panel-more { flex-shrink: 0; }
.ib-ps-panel-more .dropdown-toggle::after { display: none; }
.ib-ps-panel-more .dropdown-toggle {
	height: 100%; padding: 0 10px;
	display: flex; align-items: center; justify-content: center;
}
.ib-ps-loc-group {
	display: flex; align-items: center; gap: 6px;
	margin-right: 8px;
}
.ib-ps-loc-group select { min-width: 170px; }
.ib-ps-panel-section { padding: 12px 16px; flex: 1; }
.ib-ps-panel-section-title { font-size: 12px; font-weight: 600; color: var(--text-muted); margin-bottom: 8px; }
.ib-ps-entries-list { display: flex; flex-direction: column; gap: 6px; }
.ib-ps-entry-row {
	background: var(--fg-color, #f9fafb);
	border-radius: 5px;
	padding: 8px 10px;
	font-size: 12px;
	display: flex; gap: 12px; flex-wrap: wrap;
	color: var(--text-color);
}
.ib-ps-entry-date { font-weight: 600; color: var(--ib-primary); }

/* Stat pill */
.ib-ps-stat-pill {
	font-size: 11px; font-weight: 600;
	background: var(--fg-color, #f3f4f6);
	color: var(--text-muted);
	border: 1px solid var(--border-color);
	border-radius: 10px;
	padding: 2px 10px;
}
.ib-ps-stage-filter-pill {
	background: var(--ib-primary, #d97757);
	border-color: var(--ib-primary, #d97757);
	color: #fff;
	display: inline-flex;
	align-items: center;
	gap: 5px;
}
.ib-ps-stage-filter-clear {
	background: none;
	border: none;
	color: #fff;
	opacity: .8;
	font-size: 13px;
	line-height: 1;
	padding: 0;
	cursor: pointer;
}
.ib-ps-stage-filter-clear:hover { opacity: 1; }

/* Search input */
.ib-ps-search-input {
	padding: 5px 10px;
	border: 1px solid var(--border-color);
	border-radius: 6px;
	background: var(--card-bg);
	font-size: 13px;
	font-family: inherit;
	color: var(--text-color);
	min-width: 180px;
}
.ib-ps-search-input:focus { outline: none; border-color: var(--ib-primary); }

/* ----------------------------------------------------------------
   Item-wise view — collapsible list, one row per item (not a card grid).
   Collapsed: item identity + how many orders/customers it's spread across.
   Expanded: every order carrying this item, grouped by Sales Order, with
   that order's own customer/ETD and per-stage WO chips — replaces the old
   "click card -> full-page detail with every order's WOs flattened into one
   table" flow, which couldn't answer "which of MY orders has this item"
   when the same item appeared on several unrelated Sales Orders.
   ---------------------------------------------------------------- */
.ib-iw-list { display: flex; flex-direction: column; gap: 8px; }
.ib-iw-row {
	background: var(--card-bg);
	border: 1px solid var(--border-color);
	border-radius: 8px;
	overflow: hidden;
}
.ib-iw-row-header {
	display: flex; align-items: center; gap: 10px;
	padding: 11px 14px;
	cursor: pointer;
	transition: background .12s;
}
.ib-iw-row-header:hover { background: var(--subtle-fg, #f8fafc); }
.ib-iw-row-chevron { flex-shrink: 0; color: var(--text-muted); transition: transform .15s; }
.ib-iw-row-main { flex: 1 1 auto; min-width: 0; }
.ib-iw-row-title { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
.ib-iw-row-name { font-size: 12px; color: var(--text-muted); }
.ib-iw-row-sub { font-size: 11px; color: var(--text-muted); margin-top: 2px; }
.ib-iw-row-progress { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.ib-iw-row-pct { font-size: 11px; font-weight: 600; color: var(--text-color); min-width: 32px; text-align: right; }
.ib-iw-row-body {
	border-top: 1px solid var(--border-color);
	background: var(--subtle-fg, #f8fafc);
	padding: 10px 14px;
	display: flex; flex-direction: column; gap: 8px;
}
.ib-iw-so-group {
	background: var(--card-bg);
	border: 1px solid var(--border-color);
	border-radius: 6px;
	padding: 9px 11px;
}
.ib-iw-so-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; margin-bottom: 8px; }
.ib-iw-so-main { min-width: 0; }
.ib-iw-so-title { display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap; }
.ib-iw-so-link { font-weight: 700; color: var(--ib-primary, #d97757); text-decoration: none; font-size: 12.5px; }
.ib-iw-so-link:hover { text-decoration: underline; }
.ib-iw-so-customer { font-weight: 600; font-size: 12.5px; color: var(--text-color); }
.ib-iw-so-sub { font-size: 11px; color: var(--text-muted); margin-top: 2px; }
.ib-iw-so-side { flex-shrink: 0; }
.ib-iw-so-chips { display: flex; gap: 4px; flex-wrap: wrap; }

/* ----------------------------------------------------------------
   Machine-wise view
   ---------------------------------------------------------------- */
.ib-mw-grid {
	display: grid;
	grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
	gap: 14px;
}
.ib-mw-card {
	background: var(--card-bg);
	border: 1px solid var(--border-color);
	border-radius: 10px;
	padding: 14px;
	display: flex; flex-direction: column; gap: 11px;
	transition: box-shadow .15s, transform .12s;
}
.ib-mw-card:hover { box-shadow: 0 4px 16px rgba(0,0,0,.09); transform: translateY(-1px); }
.ib-mw-card-header { display: flex; flex-direction: column; gap: 5px; }
.ib-mw-code-row { display: flex; align-items: center; gap: 6px; }
.ib-mw-name-row { display: flex; align-items: center; gap: 6px; margin-top: 1px; }

/* Redesigned Machine-wise (2026-08-27) — the "selected machine" header used
   to be a single card capped at max-width:440px, floating alone at the left
   of a full-width row with nothing filling the rest ("machine card is not
   aligned correctly" report — a narrow orphaned box in a wide empty row).
   Now a full-width header bar: identity on top, then a body row splitting
   Load (fixed-width block) from the 4 stat tiles (spread across the
   remaining width as icon+value tiles instead of a cramped 4-col grid
   squeezed into the old 440px box). */
.ib-mw-selected-card {
	background: var(--card-bg);
	border: 1px solid var(--border-color);
	border-radius: 10px;
	padding: 16px 18px;
	display: flex; flex-direction: column; gap: 14px;
	width: 100%;
	margin-top: 14px;
	margin-bottom: 4px;
}
.ib-mw-selected-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }

.ib-mw-body-row { display: flex; align-items: stretch; gap: 20px; flex-wrap: wrap; }

/* Load block — fixed-width column on the left of the body row */
.ib-mw-load-block {
	flex: 0 0 260px;
	background: var(--fg-color, #f9fafb); border-radius: 7px; padding: 10px 12px;
	border: 1px solid var(--border-color);
	display: flex; flex-direction: column; justify-content: center;
}
.ib-mw-load-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.ib-mw-load-bar-wrap { height: 6px; background: var(--border-color); border-radius: 3px; overflow: hidden; }
.ib-mw-load-bar { height: 100%; border-radius: 3px; transition: width .4s; }

.ib-mw-bundle-hint {
	display: flex; align-items: flex-start; gap: 7px;
	background: color-mix(in srgb, var(--ib-primary) 8%, var(--fg-color, #f9fafb));
	border: 1px solid color-mix(in srgb, var(--ib-primary) 25%, var(--border-color));
	border-radius: 7px; padding: 8px 11px; margin: 10px 0;
	font-size: 11.5px; color: var(--text-color); line-height: 1.4;
}
.ib-mw-bundle-hint iconify-icon { flex: 0 0 auto; margin-top: 1px; color: var(--ib-primary); }
.ib-mw-bundle-hint--here { border-width: 1.5px; }

/* Stats — spread across the remaining width, icon+value tiles separated by
   dividers instead of a tight 4-col grid squeezed into a narrow box. */
.ib-mw-stats-row {
	flex: 1 1 320px;
	display: flex; align-items: stretch;
	background: var(--fg-color, #f9fafb);
	border-radius: 7px; border: 1px solid var(--border-color);
	overflow: hidden;
}
.ib-mw-stat {
	flex: 1; display: flex; align-items: center; gap: 8px;
	justify-content: center; padding: 10px 8px;
	border-right: 1px solid var(--border-color);
}
.ib-mw-stat:last-child { border-right: none; }
.ib-mw-stat-icon { color: var(--text-muted); flex-shrink: 0; }
.ib-mw-stat-body { text-align: left; }
.ib-mw-stat-val { font-size: 16px; font-weight: 700; color: var(--text-color); line-height: 1.2; }
.ib-mw-stat-uom { font-size: 10px; font-weight: 500; color: var(--text-muted); }
.ib-mw-stat-label { font-size: 9px; color: var(--text-muted); margin-top: 2px; text-transform: uppercase; letter-spacing: .04em; }
@media (max-width: 780px) {
	.ib-mw-load-block { flex-basis: 100%; }
	.ib-mw-stat { flex-direction: column; gap: 2px; text-align: center; }
	.ib-mw-stat-body { text-align: center; }
}

/* WO list — 2-line row per Work Order (2026-08-09), replacing a 6-column
   <table> that could not fit a ~300px machine card at any layout setting:
   table-layout:auto let it overflow into a scrollbar with a clipped "Status"
   header; table-layout:fixed then made every column too narrow to read
   ("STA"/"PR" headers, unreadable Progress). A row has no column-width
   arithmetic to get wrong — item identity/status stay full-size on their own
   line, item name/customer/progress stay full-size on theirs. */
.ib-mw-wo-list { display: flex; flex-direction: column; }
.ib-mw-wo-rows { display: flex; flex-direction: column; }
.ib-mw-wo-row { padding: 5px 2px; border-bottom: 1px solid var(--border-color); cursor: pointer; transition: background .12s; }
.ib-mw-wo-row:last-child { border-bottom: none; }
.ib-mw-wo-row:hover { background: var(--fg-color,#f9fafb); }
.ib-mw-wo-row-top { display: flex; align-items: center; gap: 5px; }
.ib-mw-stage-chip {
	flex-shrink: 0; font-size: 8.5px; font-weight: 700; text-transform: uppercase;
	letter-spacing: .02em; padding: 1px 5px; border-radius: 4px;
}
.ib-mw-wo-item-cell {
	flex: 1 1 auto; min-width: 0; font-family: monospace; font-size: 11px; font-weight: 600;
	color: var(--text-color); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ib-mw-wo-row-bottom { display: flex; align-items: center; gap: 6px; margin-top: 2px; padding-left: 2px; }
.ib-mw-wo-meta {
	flex: 1 1 auto; min-width: 0; font-size: 10px; color: var(--text-muted);
	overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ib-mw-wo-bar-wrap { flex-shrink: 0; width: 32px; height: 3px; background: var(--border-color); border-radius: 2px; overflow: hidden; }
.ib-mw-wo-bar { height: 100%; border-radius: 2px; }
.ib-mw-wo-pct { flex-shrink: 0; font-size: 9.5px; color: var(--text-muted); min-width: 26px; text-align: right; }
.ib-mw-no-wos { font-size: 11px; color: var(--text-muted); padding: 6px 0; display: flex; align-items: center; gap: 5px; }

/* Footer */
.ib-mw-card-footer { margin-top: auto; padding-top: 2px; }
.ib-mw-edit-btn {
	display: inline-flex; align-items: center; gap: 4px;
	padding: 4px 10px; border-radius: 5px;
	border: 1px solid var(--border-color);
	background: var(--card-bg); color: var(--text-muted);
	font-size: 11px; font-family: inherit; cursor: pointer;
	transition: border-color .12s, color .12s;
}
.ib-mw-edit-btn:hover { border-color: var(--ib-primary); color: var(--ib-primary); }
`;
		const $style = $(`<style id="ib-ps-styles">${css}</style>`);
		$("head").append($style);
	}
}
