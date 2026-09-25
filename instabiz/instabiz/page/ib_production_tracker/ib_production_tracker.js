frappe.pages["ib-production-tracker"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Production Tracker"),
		single_column: true,
	});
	wrapper.prod_tracker = new IbProductionTracker(wrapper);
};

const _IB_PT_STAGE_ICONS = {
	"Coating":          "lucide:paintbrush",
	"Slitting":         "lucide:scissors",
	"Rewinding":        "lucide:rotate-cw",
	"Cutting":          "lucide:scissors",
	"Silicon":          "lucide:droplet",
	"Packing":          "lucide:package",
	"Ready to Deliver": "lucide:truck",
	"Delivered":        "lucide:check-circle",
};

const _IB_PT_STAGES = ["Coating", "Slitting", "Rewinding", "Cutting", "Silicon", "Packing", "Ready to Deliver"];

const _IB_PT_RISK = {
	"overdue":  { label: "Overdue",  color: "#dc2626", bg: "#fef2f2" },
	"at-risk":  { label: "At Risk",  color: "#ea580c", bg: "#fff7ed" },
	"on-track": { label: "On Track", color: "#059669", bg: "#ecfdf5" },
	"none":     { label: "No Date",  color: "#6b7280", bg: "#f9fafb" },
};

const _IB_PT_PRIORITY_COLOR = {
	Urgent: "#dc2626", High: "#ea580c", Normal: "#2563eb", Low: "#6b7280",
};

const _IB_PT_SORT_COLS = {
	delivery:  { label: "Delivery",  get: (o) => o.delivery_date || "9999-99-99" },
	priority:  { label: "Priority",  get: (o) => ({ Urgent: 0, High: 1, Normal: 2, Low: 3 }[o.priority] ?? 9) },
	pct:       { label: "Progress",  get: (o) => o.pct || 0 },
	customer:  { label: "Customer",  get: (o) => (o.customer || "").toLowerCase() },
};

function _ib_pt_esc(s) {
	return frappe.utils.escape_html(String(s || ""));
}

class IbProductionTracker {
	constructor(wrapper) {
		this.page = wrapper.page;
		this._orders = [];
		this._risk_filter = "all";
		this._sort_col = "delivery";
		this._sort_asc = true;
		this._page = 0;
		this._page_size = 20;
		this._is_privileged = frappe.user.has_role(["Sales Manager", "System Manager"]);
		this._setup_toolbar();
		this._setup_content();
		this.refresh();
	}

	_setup_toolbar() {
		this.page.set_secondary_action(__("Refresh"), () => this.refresh());
		this.page.add_inner_button(__("Export CSV"), () => this._export_csv());

		$(this.page.page_form).addClass("ib-page-form");

		this.f_search = this.page.add_field({
			fieldname: "search", label: __("Search"), fieldtype: "Data",
			placeholder: __("Order, customer…"),
			change: () => { this._page = 0; this._render(); },
		});

		this.f_priority = this.page.add_field({
			fieldname: "priority", label: __("Priority"), fieldtype: "Select",
			options: ["", "Urgent", "High", "Normal", "Low"],
			change: () => { this._page = 0; this._render(); },
		});

		this.f_stage = this.page.add_field({
			fieldname: "stage", label: __("Stage"), fieldtype: "Select",
			options: [""].concat(_IB_PT_STAGES),
			change: () => { this._page = 0; this._render(); },
		});

		if (this._is_privileged) {
			this.f_sales_person = this.page.add_field({
				fieldname: "sales_person_user", label: __("Sales Person"),
				fieldtype: "Link", options: "User",
				change: () => this.refresh(),
			});
			this.f_show_completed = this.page.add_field({
				fieldname: "show_completed", label: __("Show Completed"),
				fieldtype: "Check",
				change: () => this.refresh(),
			});
		}
	}

	_setup_content() {
		this.$body = $(this.page.main);
		this.$content = $(`
			<div class="ib-pt-wrap">
				<div class="ib-pt-cards"></div>
				<div class="ib-pt-chips">
					<span class="ib-pt-chip ib-pt-chip--active" data-risk="all">${__("All")}</span>
					<span class="ib-pt-chip" data-risk="overdue">${__("Overdue")}</span>
					<span class="ib-pt-chip" data-risk="at-risk">${__("At Risk")}</span>
					<span class="ib-pt-chip" data-risk="on-track">${__("On Track")}</span>
				</div>
				<div class="ib-card ib-pt-list-wrap">
					<div class="ib-pt-list-header">
						<span class="ib-pt-sort-col" data-col="customer">${__("Order")} <span class="ib-sort-icon"></span></span>
						<span>${__("Stage")}</span>
						<span class="ib-pt-sort-col" data-col="pct">${__("Progress")} <span class="ib-sort-icon"></span></span>
						<span class="ib-pt-sort-col" data-col="delivery">${__("Delivery")} <span class="ib-sort-icon"></span></span>
					</div>
					<div class="ib-pt-list"></div>
					<div class="ib-pt-empty" style="display:none">${__("No in-flight orders.")}</div>
					<div class="ib-pt-pagination">
						<div class="ib-pt-page-size">
							${__("Rows per page")}:
							<select class="ib-pt-page-size-select">
								<option value="20">20</option>
								<option value="50">50</option>
								<option value="100">100</option>
								<option value="0">${__("All")}</option>
							</select>
						</div>
						<span class="ib-pt-page-info"></span>
						<div class="ib-pt-page-btns">
							<button class="btn btn-default btn-xs ib-pt-prev">${__("Prev")}</button>
							<button class="btn btn-default btn-xs ib-pt-next">${__("Next")}</button>
						</div>
					</div>
				</div>
			</div>
		`).appendTo(this.$body);

		this.$cards = this.$content.find(".ib-pt-cards");
		this.$chips = this.$content.find(".ib-pt-chips");
		this.$list  = this.$content.find(".ib-pt-list");
		this.$empty = this.$content.find(".ib-pt-empty");
		this.$header = this.$content.find(".ib-pt-list-header");
		this.$pagination = this.$content.find(".ib-pt-pagination");
		this.$page_info = this.$content.find(".ib-pt-page-info");
		this.$page_size_select = this.$content.find(".ib-pt-page-size-select");

		this.$chips.on("click", ".ib-pt-chip", (e) => {
			this.$chips.find(".ib-pt-chip").removeClass("ib-pt-chip--active");
			$(e.currentTarget).addClass("ib-pt-chip--active");
			this._risk_filter = $(e.currentTarget).data("risk");
			this._page = 0;
			this._render();
		});

		this.$header.on("click", ".ib-pt-sort-col", (e) => {
			const col = $(e.currentTarget).data("col");
			this._sort_asc = (this._sort_col === col) ? !this._sort_asc : true;
			this._sort_col = col;
			this._render();
		});

		this.$page_size_select.on("change", () => {
			this._page_size = parseInt(this.$page_size_select.val(), 10) || 0;
			this._page = 0;
			this._render();
		});

		this.$content.find(".ib-pt-prev").on("click", () => {
			if (this._page <= 0) return;
			this._page -= 1;
			this._render();
		});
		this.$content.find(".ib-pt-next").on("click", () => {
			this._page += 1;
			this._render();
		});
	}

	refresh() {
		this.$list.html(`<div class="ib-pt-spinner"><span></span><span></span><span></span></div>`);
		// Self-bumped request-generation token — refresh() is wired to two
		// filter change handlers plus the toolbar Refresh button, so a slower
		// response from a filter state the user has already changed away
		// from could otherwise land after a faster, newer response and
		// silently overwrite the list with the wrong filter's results (same
		// bug class fixed on the Production Stages page's loaders).
		const gen = (this._load_gen = (this._load_gen || 0) + 1);
		frappe.call({
			method: "instabiz.overrides.production.get_my_production_orders",
			args: {
				sales_person_user: this._is_privileged ? (this.f_sales_person.get_value() || null) : null,
				show_completed: this._is_privileged ? (this.f_show_completed.get_value() ? 1 : 0) : 0,
			},
			callback: (r) => {
				if (gen !== this._load_gen) return; // stale — a newer refresh() already superseded this
				this._orders = r.message || [];
				this._page = 0;
				this._render_cards();
				this._render();
			},
		});
	}

	_render_cards() {
		const total = this._orders.length;
		const overdue = this._orders.filter(o => o.risk === "overdue").length;
		const at_risk = this._orders.filter(o => o.risk === "at-risk").length;
		const ready = this._orders.filter(o => o.pct >= 100).length;

		const card = (label, value, variant) => `
			<div class="ib-card ib-pt-card ${variant ? "ib-pt-card--" + variant : ""}">
				<div class="ib-pt-card-value">${value}</div>
				<div class="ib-pt-card-label">${label}</div>
			</div>`;

		this.$cards.html(`
			${card(__("In Production"), total)}
			${card(__("Overdue"), overdue, overdue ? "danger" : "")}
			${card(__("At Risk"), at_risk, at_risk ? "warn" : "")}
			${card(__("Ready to Deliver"), ready, ready ? "accent" : "")}
		`);
	}

	// Filter + sort the full order set — used by both _render (paginated view)
	// and _export_csv (full filtered/sorted set, ignoring pagination).
	_filtered_sorted() {
		const term = (this.f_search.get_value() || "").trim().toLowerCase();
		const priority = this.f_priority.get_value();
		const stage = this.f_stage.get_value();

		let rows = this._orders;
		if (this._risk_filter !== "all") rows = rows.filter(o => o.risk === this._risk_filter);
		if (priority) rows = rows.filter(o => o.priority === priority);
		if (stage) rows = rows.filter(o => o.current_stage === stage);
		if (term) {
			rows = rows.filter(o => [o.sales_order, o.customer, o.sales_person]
				.filter(Boolean).join(" ").toLowerCase().includes(term));
		}

		const sortDef = _IB_PT_SORT_COLS[this._sort_col];
		if (sortDef) {
			rows = [...rows].sort((a, b) => {
				const av = sortDef.get(a), bv = sortDef.get(b);
				const cmp = av < bv ? -1 : av > bv ? 1 : 0;
				return this._sort_asc ? cmp : -cmp;
			});
		}
		return rows;
	}

	_render() {
		const all_rows = this._filtered_sorted();

		this.$header.find(".ib-sort-icon").text("");
		this.$header.find(`[data-col="${this._sort_col}"] .ib-sort-icon`).text(this._sort_asc ? " ↑" : " ↓");

		if (!all_rows.length) {
			this.$list.empty();
			this.$empty.show();
			this.$pagination.hide();
			return;
		}
		this.$empty.hide();

		const page_size = this._page_size || all_rows.length;
		const max_page = Math.max(0, Math.ceil(all_rows.length / page_size) - 1);
		if (this._page > max_page) this._page = max_page;
		const start = this._page * page_size;
		const rows = all_rows.slice(start, start + page_size);

		this.$list.html(rows.map(o => this._row_html(o)).join(""));

		this.$list.find(".ib-pt-row").on("click", (e) => {
			const so = $(e.currentTarget).data("so");
			this._toggle_detail($(e.currentTarget), so);
		});

		this.$pagination.show();
		const end = Math.min(start + page_size, all_rows.length);
		this.$page_info.text(__("Showing {0}-{1} of {2}", [start + 1, end, all_rows.length]));
		this.$content.find(".ib-pt-prev").prop("disabled", this._page <= 0);
		this.$content.find(".ib-pt-next").prop("disabled", this._page >= max_page);
	}

	_row_html(o) {
		const risk = _IB_PT_RISK[o.risk] || _IB_PT_RISK.none;
		const priColor = _IB_PT_PRIORITY_COLOR[o.priority] || "#6b7280";
		const stageIcon = _IB_PT_STAGE_ICONS[o.current_stage] || "lucide:circle";
		const pct = o.pct || 0;
		const deliveryTxt = o.delivery_date ? frappe.datetime.str_to_user(o.delivery_date) : __("No date");
		const daysTxt = o.days_left == null ? "" :
			o.days_left < 0 ? __("{0}d overdue", [Math.abs(o.days_left)]) :
			o.days_left === 0 ? __("Due today") :
			__("{0}d left", [o.days_left]);

		return `
		<div class="ib-pt-row" data-so="${_ib_pt_esc(o.sales_order)}">
			<div class="ib-pt-row-main">
				<div class="ib-pt-row-id">
					<a href="/app/sales-order/${_ib_pt_esc(o.sales_order)}" onclick="event.stopPropagation()">${_ib_pt_esc(o.sales_order)}</a>
					<span class="ib-pt-priority" style="background:${priColor}18;color:${priColor}">${_ib_pt_esc(o.priority || "Normal")}</span>
				</div>
				<div class="ib-pt-row-customer">${_ib_pt_esc(o.customer)}</div>
				${o.sales_person ? `<div class="ib-pt-row-sp">${_ib_pt_esc(o.sales_person)}</div>` : ""}
			</div>
			<div class="ib-pt-row-stage">
				<iconify-icon icon="${stageIcon}" width="13" height="13"></iconify-icon>
				${_ib_pt_esc(o.current_stage || (pct >= 100 ? "Ready to Deliver" : "Pending"))}
			</div>
			<div class="ib-pt-row-progress">
				<div class="ib-pt-bar"><div class="ib-pt-bar-fill" style="width:${pct}%;background:${pct >= 100 ? "#059669" : "#2563eb"}"></div></div>
				<span class="ib-pt-pct">${pct}%</span>
			</div>
			<div class="ib-pt-row-delivery">
				<div>${deliveryTxt}</div>
				<span class="ib-pt-risk-badge" style="background:${risk.bg};color:${risk.color}">${daysTxt || risk.label}</span>
			</div>
			<div class="ib-pt-row-detail" style="display:none"></div>
		</div>`;
	}

	_toggle_detail($row, so_name) {
		const $detail = $row.find(".ib-pt-row-detail");
		if ($detail.is(":visible")) { $detail.slideUp(120); return; }

		this.$list.find(".ib-pt-row-detail").not($detail).slideUp(120);

		if ($detail.data("loaded")) { $detail.slideDown(120); return; }
		$detail.html(`<div class="ib-pt-spinner"><span></span><span></span><span></span></div>`).slideDown(120);

		frappe.call({
			method: "instabiz.overrides.production.get_so_production_timeline",
			args: { sales_order: so_name },
			callback: (r) => {
				$detail.data("loaded", true).html(this._detail_html(r.message));
			},
			error: () => $detail.html(`<div class="text-muted" style="padding:10px">${__("Could not load detail.")}</div>`),
		});
	}

	_detail_html(data) {
		if (!data || !data.has_order_sheet || !(data.items || []).length) {
			return `<div class="text-muted" style="padding:10px">${__("No production detail available.")}</div>`;
		}
		return `<table class="ib-pt-detail-table">
			<thead><tr>
				<th>${__("Item")}</th><th>${__("Stages")}</th><th>${__("Progress")}</th>
			</tr></thead>
			<tbody>${data.items.map(item => {
				const chips = (item.stages || []).map(s => {
					const done = s.status === "Completed";
					const active = s.status === "In Progress";
					const col = done ? "#059669" : active ? "#2563eb" : "#d1d5db";
					const bg   = done ? "#d1fae5" : active ? "#dbeafe" : "#f9fafb";
					const icon = _IB_PT_STAGE_ICONS[s.stage] || "lucide:circle";
					const label = s.stage.replace("Ready to Deliver", "RTD");
					return `<span class="ib-pt-stage-chip" style="background:${bg};color:${col};border-color:${col}40"
						title="${_ib_pt_esc(s.stage)}: ${_ib_pt_esc(s.status || "Not created")}">
						<iconify-icon icon="${icon}" width="9" height="9"></iconify-icon> ${_ib_pt_esc(label)}</span>`;
				}).join("");
				return `<tr>
					<td class="ib-pt-detail-item">${_ib_pt_esc(item.item_code)}</td>
					<td>${chips}</td>
					<td>
						<div class="ib-pt-bar" style="width:70px">
							<div class="ib-pt-bar-fill" style="width:${item.completion_pct}%;background:${item.completion_pct >= 100 ? "#059669" : "#2563eb"}"></div>
						</div>
						<span class="ib-pt-pct">${item.completion_pct}%</span>
					</td>
				</tr>`;
			}).join("")}</tbody>
		</table>`;
	}

	_export_csv() {
		const rows = this._filtered_sorted();
		if (!rows.length) {
			frappe.show_alert({ message: __("Nothing to export."), indicator: "orange" });
			return;
		}
		const headers = ["Sales Order", "Customer", "Sales Person", "Priority", "Current Stage", "Progress %", "Delivery Date", "Days Left", "Risk"];
		const csvEscape = (v) => `"${String(v == null ? "" : v).replace(/"/g, '""')}"`;
		const lines = [headers.join(",")];
		rows.forEach(o => {
			lines.push([
				o.sales_order, o.customer, o.sales_person || "", o.priority || "",
				o.current_stage || "", o.pct, o.delivery_date || "", o.days_left ?? "", o.risk,
			].map(csvEscape).join(","));
		});
		const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
		const url = URL.createObjectURL(blob);
		const a = document.createElement("a");
		a.href = url;
		a.download = `production-tracker-${frappe.datetime.get_today()}.csv`;
		document.body.appendChild(a);
		a.click();
		a.remove();
		URL.revokeObjectURL(url);
	}
}
