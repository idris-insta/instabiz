frappe.pages["ib-hrms-dashboard"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({
		parent: wrapper,
		title: "HR Dashboard",
		single_column: true,
	});
	wrapper._ib_hr = new IBHrmsDashboard(wrapper);
};

frappe.pages["ib-hrms-dashboard"].on_page_show = function (wrapper) {
	if (!wrapper._ib_hr) return;
	wrapper._ib_hr.refresh();
	if (!wrapper._ib_hr._auto_refresh) {
		wrapper._ib_hr._auto_refresh = setInterval(() => wrapper._ib_hr.refresh(), 5 * 60 * 1000);
	}
};

frappe.pages["ib-hrms-dashboard"].on_page_hide = function (wrapper) {
	if (wrapper._ib_hr) {
		clearInterval(wrapper._ib_hr._auto_refresh);
		wrapper._ib_hr._auto_refresh = null;
	}
};

// ─────────────────────────────────────────────────────────────────────────────

class IBHrmsDashboard {
	constructor(wrapper) {
		this.wrapper      = wrapper;
		this.page         = wrapper.page;
		this._active_tab  = "attendance";
		this._month       = frappe.datetime.get_today().slice(0, 7) + "-01";
		this._data        = null;
		this._overview    = null;
		this._fetching    = false;
		this._auto_refresh = null;
		this._filters = {
			att_search: "", att_status: "",
			leave_search: "", leave_status: "",
			pay_search: "", pay_status: "",
		};
		this._search_debounce = null;
		this._page = { att: 1, leave: 1, pay: 1 };
		this._page_size = 20;
		this._inject_styles();
		this._build_layout();
		this._bind_toolbar();
		// refresh() started by on_page_show — no double call on first visit
	}

	_inject_styles() {
		if (document.getElementById("ib-hr-styles")) return;
		const s = document.createElement("style");
		s.id = "ib-hr-styles";
		s.textContent = `
.ib-hr-wrap { padding: 16px; max-width: 1400px; }
.ib-hr-kpi-row { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin-bottom: 18px; }
.ib-hr-kpi { background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 8px;
  padding: 14px; border-top: 4px solid; position: relative; overflow: hidden; }
.ib-hr-kpi--link:hover { background: var(--ib-tint-mid, #f7f7f7); }
.ib-hr-kpi-val { font-size: 26px; font-weight: 800; color: var(--heading-color); margin-bottom: 2px; }
.ib-hr-kpi-lbl { font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: .5px; }
.ib-hr-tabs { display: flex; gap: 4px; margin-bottom: 14px; }
.ib-hr-tab { padding: 6px 14px; border-radius: 6px; font-size: 12px; font-weight: 500;
  cursor: pointer; border: 1px solid var(--border-color); background: var(--card-bg); color: var(--text-muted); }
.ib-hr-tab.active { background: var(--ib-primary); color: #fff; border-color: var(--ib-primary); }
.ib-hr-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.ib-hr-table th { text-align: left; padding: 7px 8px; font-size: 11px; color: var(--text-muted);
  border-bottom: 1px solid var(--border-color); position: sticky; top: 0; background: var(--card-bg); }
.ib-hr-table td { padding: 7px 8px; border-bottom: 1px solid var(--border-color); vertical-align: middle; }
.ib-hr-table tr:last-child td { border-bottom: none; }
.ib-hr-table tr:hover td { background: var(--bg-color); }
.ib-hr-card { background: var(--card-bg); border: 1px solid var(--border-color);
  border-radius: 8px; padding: 16px; overflow-x: auto; }
.ib-hr-status-badge { display: inline-block; padding: 2px 8px; border-radius: 10px;
  font-size: 10px; font-weight: 600; }
.ib-hr-status-present { background:#d1fae5; color:#065f46; }
.ib-hr-status-absent { background:#fee2e2; color:#991b1b; }
.ib-hr-status-half { background:#fef3c7; color:#92400e; }
.ib-hr-status-leave { background:#e0e7ff; color:#3730a3; }
.ib-hr-status-open { background:#fef3c7; color:#92400e; }
.ib-hr-status-approved { background:#d1fae5; color:#065f46; }
.ib-hr-status-rejected { background:#fee2e2; color:#991b1b; }
/* Leave-row action buttons — house style (flat hairline, tinted on hover),
   replacing raw Bootstrap btn-success / btn-danger. */
.ib-hr-act-btn {
	display:inline-flex; align-items:center; justify-content:center;
	height:26px; padding:2px 12px;
	background:var(--card-bg); border:1px solid var(--border-color);
	border-radius:6px; font-size:11px; font-weight:500;
	color:var(--text-color); cursor:pointer; white-space:nowrap;
	transition:border-color .15s, color .15s, background .15s;
}
.ib-hr-act-btn + .ib-hr-act-btn { margin-left:6px; }
.ib-hr-act-btn:hover { border-color:var(--ib-primary); color:var(--ib-primary); }
.ib-hr-act-btn--approve:hover { border-color:#16a34a; color:#16a34a; background:#f0fdf4; }
.ib-hr-act-btn--reject:hover  { border-color:#dc2626; color:#dc2626; background:#fef2f2; }
.ib-hr-dept-bars { margin-top: 8px; }
.ib-hr-bar-row { display: flex; align-items: center; gap: 8px; padding: 4px 0; }
.ib-hr-bar-lbl { width: 140px; font-size: 11px; color: var(--text-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ib-hr-bar-track { flex: 1; height: 8px; background: var(--border-color); border-radius: 4px; overflow: hidden; }
.ib-hr-bar-fill { height: 100%; border-radius: 4px; background: #06b6d4; }
.ib-hr-bar-val { width: 30px; text-align: right; font-size: 11px; font-weight: 600; }
.ib-hr-statutory { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.ib-hr-stat-card { background: var(--bg-color); border: 1px solid var(--border-color);
  border-radius: 6px; padding: 14px; }
.ib-hr-stat-title { font-weight: 600; font-size: 13px; margin-bottom: 8px; color: var(--heading-color); }
.ib-hr-stat-row { display: flex; justify-content: space-between; padding: 4px 0;
  border-bottom: 1px dashed var(--border-color); font-size: 12px; }
.ib-hr-stat-row:last-child { border-bottom: none; }
.ib-hr-stat-key { color: var(--text-muted); }
.ib-hr-stat-val { font-weight: 600; color: var(--heading-color); }
.ib-hr-top-bar { display: flex; align-items: center; gap: 8px; margin-bottom: 14px; flex-wrap: wrap; }
.ib-hr-ts { font-size: 11px; color: var(--text-muted); margin-left: auto; }
.ib-hr-filter-bar { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.ib-hr-search { flex: 0 1 220px; padding: 5px 10px; border: 1px solid var(--border-color);
  border-radius: 6px; font-size: 12px; background: var(--input-bg, #fff); color: var(--text-color); }
.ib-hr-status-select { padding: 5px 8px; border: 1px solid var(--border-color); border-radius: 6px;
  font-size: 12px; background: var(--input-bg, #fff); color: var(--text-color); }
.ib-hr-filter-count { font-size: 11px; color: var(--text-muted); margin-left: auto; }
.ib-hr-pagination { display: flex; align-items: center; justify-content: center; gap: 10px; margin-top: 12px; }
.ib-hr-pagination button:disabled { opacity: .4; cursor: default; }
.ib-hr-page-info { font-size: 11px; color: var(--text-muted); }
@media(max-width:900px){ .ib-hr-kpi-row{grid-template-columns:repeat(3,1fr);} .ib-hr-statutory{grid-template-columns:1fr;} }
@media(max-width:540px){ .ib-hr-kpi-row{grid-template-columns:1fr;} }
		`;
		document.head.appendChild(s);
	}

	_month_options() {
		const first = frappe.datetime.get_today().slice(0, 7) + "-01";
		const out = [];
		for (let i = 0; i < 12; i++) {
			const m = frappe.datetime.add_months(first, -i).slice(0, 7) + "-01";
			out.push({ value: m, label: frappe.datetime.str_to_obj(m).toLocaleString("en-IN", { month: "short", year: "numeric" }) });
		}
		return out;
	}

	_build_layout() {
		this.$wrap = ibUI.mount(this.page);
		this.$wrap.html(`
			<div class="ib-ui-filter-note" id="ib-hr-note"></div>
			<div class="ib-dash-cards" data-cards>
				<div data-card="kpis" class="ib-dash-c--12" id="ib-hr-kpis"></div>
				<div data-card="attendance" class="ib-dash-c--8">
					${ibUI.chartCard({ id: "ib-hr-att-trend", kind: "ATTENDANCE", title: __("Day by day"), height: 220 })}
				</div>
				<div data-card="att_mix" class="ib-dash-c--4">
					${ibUI.chartCard({ id: "ib-hr-att-mix", kind: "MONTH", title: __("Attendance mix"), height: 220 })}
				</div>
				<div data-card="departments" class="ib-dash-c--6">
					<div class="ib-ui-card"><div class="ib-ui-card-h"><span class="k">PEOPLE</span>
						<span class="t">${__("Headcount by department")}</span></div>
						<div id="ib-hr-dept"></div></div>
				</div>
				<div data-card="payroll" class="ib-dash-c--6">
					${ibUI.chartCard({ id: "ib-hr-pay", kind: "PAYROLL", title: __("Salary cost — last 6 months"), height: 230 })}
				</div>
				<div data-card="moments" class="ib-dash-c--4">
					<div class="ib-ui-card"><div class="ib-ui-card-h"><span class="k">NEXT 30 DAYS</span>
						<span class="t">${__("Birthdays & anniversaries")}</span></div>
						<div id="ib-hr-moments"></div></div>
				</div>
				<div data-card="absentees" class="ib-dash-c--4">
					<div class="ib-ui-card"><div class="ib-ui-card-h"><span class="k">WATCH</span>
						<span class="t">${__("Most absent this month")}</span></div>
						<div id="ib-hr-absentees"></div></div>
				</div>
				<div data-card="leave_mix" class="ib-dash-c--4">
					${ibUI.chartCard({ id: "ib-hr-leave", kind: "LEAVE", title: __("Leave taken by type"), height: 200 })}
				</div>
				<div data-card="lists" class="ib-dash-c--12">
					<div class="ib-ui-card">
						<div class="ib-hr-tabs">
							<button class="ib-hr-tab active" data-tab="attendance">${__("Attendance")}</button>
							<button class="ib-hr-tab" data-tab="leaves">${__("Leaves")}</button>
							<button class="ib-hr-tab" data-tab="payroll">${__("Payroll")}</button>
						</div>
						<div id="ib-hr-content"></div>
					</div>
				</div>
			</div>
		`);

		this.$wrap.find(".ib-hr-tab").on("click", (e) => {
			const tab = $(e.currentTarget).data("tab");
			this.$wrap.find(".ib-hr-tab").removeClass("active");
			$(e.currentTarget).addClass("active");
			this._active_tab = tab;
			this._render_tab();
		});

		this.filters = ibDash.filters(this.page, {
			key: "hr-dash",
			fields: [
				{ fieldname: "month", label: __("Month"), fieldtype: "Select",
					options: this._month_options(), default: this._month, width: "130px" },
				ibDash.F.link("Department", "department"),
				ibDash.F.link("Branch", "branch"),
			],
			onChange: (v) => {
				this._month = v.month || this._month;
				this._page = { att: 1, leave: 1, pay: 1 };
				this.refresh();
			},
		});
		this.cards = ibDash.personalise(this.page, {
			key: "hr-dash",
			cards: [
				{ id: "kpis", label: __("Headline numbers"), locked: 1 },
				{ id: "attendance", label: __("Attendance day by day") },
				{ id: "att_mix", label: __("Attendance mix") },
				{ id: "departments", label: __("Headcount by department") },
				{ id: "payroll", label: __("Salary cost trend") },
				{ id: "moments", label: __("Birthdays & anniversaries") },
				{ id: "absentees", label: __("Most absent") },
				{ id: "leave_mix", label: __("Leave by type") },
				{ id: "lists", label: __("Attendance / leave / payroll lists"), locked: 1 },
			],
			container: () => this.$wrap.find("[data-cards]"),
		});
		this.cards.apply();
	}

	_bind_toolbar() {
		this.page.set_secondary_action(__("Refresh"), () => this.refresh(), "refresh");
		this.page.add_menu_item(__("Employees"), () => frappe.set_route("List", "Employee"));
		this.page.add_menu_item(__("New Leave Application"), () => frappe.new_doc("Leave Application"));
		this.page.add_menu_item(__("Payroll Summary"), () => frappe.set_route("query-report", "IB Payroll Summary"));
	}

	_set_ts(text) {
		this.$wrap.find("#ib-hr-note .ts").text(text);
	}

	_note() {
		const f = (this.filters && this.filters.get()) || {};
		const label = (this._overview && this._overview.meta.month_label) || "";
		this.$wrap.find("#ib-hr-note").html(
			`${ibUI.icon("calendar", 13)}<b>${ibUI.esc(label)}</b>` +
			`${f.department ? `<span>·</span><span>${ibUI.esc(f.department)}</span>` : ""}` +
			`${f.branch ? `<span>·</span><span>${ibUI.esc(f.branch)}</span>` : ""}` +
			`<span style="margin-left:auto" class="ts"></span>`,
		);
	}

	refresh() {
		const req_month = this._month;
		const f = (this.filters && this.filters.get()) || {};

		// Overview (analytics) and the operational lists are independent — a
		// slow list query should not hold up the numbers at the top.
		frappe.call({
			method: "instabiz.instabiz.page.ib_hrms_dashboard.ib_hrms_dashboard.get_hr_overview",
			args: { month: req_month, department: f.department, branch: f.branch },
			callback: (r) => {
				if (!r.message || this._month !== req_month) return;
				this._overview = r.message;
				this._note();
				this._render_kpis(r.message);
				this._render_charts(r.message);
				this._render_side(r.message);
				this._set_ts(__("Updated") + " " + frappe.datetime.now_time());
				this.cards.apply();
			},
			error: () => this._set_ts(__("Could not load")),
		});

		const opts = ib_guarded_call(this, {
			method: "instabiz.instabiz.page.ib_hrms_dashboard.ib_hrms_dashboard.get_hrms_data",
			args: {
				month: req_month, ...this._filters,
				att_offset: (this._page.att - 1) * this._page_size,
				leave_offset: (this._page.leave - 1) * this._page_size,
				pay_offset: (this._page.pay - 1) * this._page_size,
				page_size: this._page_size,
			},
			callback: (r) => {
				if (!r.message || this._month !== req_month) return;
				this._data = r.message;
				this._render_tab();
			},
		});
		if (opts) frappe.call(opts);
	}

	_render_kpis(d) {
		const pending = (d.pending_leaves || 0) + (d.ot_pending || 0) + (d.pending_ffs || 0);
		const kpis = [
			{
				key: "headcount", l: __("Active people"), icon: "users", tone: "brand", v: d.headcount,
				sub: `${d.joiners} ${__("joined")} · ${d.exits} ${__("left")}`,
			},
			{
				key: "present", l: __("In today"), icon: "check-circle", tone: "ok", v: d.present_today,
				sub: `${d.on_leave_today} ${__("on leave")}`,
			},
			{
				key: "absent", l: __("Absent today"), icon: "alert-triangle",
				tone: d.absent_today ? "warn" : "ok", v: d.absent_today,
				sub: d.headcount ? `${Math.round((d.absent_today / d.headcount) * 100)}% ${__("of the team")}` : "",
			},
			{
				key: "att_rate", l: __("Attendance rate"), icon: "activity",
				tone: d.att_rate >= 85 ? "ok" : d.att_rate >= 70 ? "warn" : "danger",
				v: `${d.att_rate}%`, delta: d.att_delta, deltaSuffix: __("pts vs last month"),
				sub: `${d.att_marked} ${__("days marked")}`,
			},
			{
				key: "pending", l: __("Waiting on you"), icon: "clock", tone: pending ? "warn" : "ok",
				v: pending, sub: `${d.pending_leaves} ${__("leave")} · ${d.ot_pending} ${__("OT")} · ${d.pending_ffs} ${__("F&F")}`,
			},
			{
				key: "payroll", l: d.payroll_is_draft ? __("Payroll (draft)") : __("Payroll"), icon: "wallet",
				tone: "info", v: ibUI.moneyShort(d.payroll_net), title: ibUI.moneyFull(d.payroll_net),
				sub: `${d.payroll_submitted_count} ${__("submitted")} · ${d.payroll_draft_count} ${__("draft")}`,
			},
			{
				key: "overtime", l: __("Overtime"), icon: "clock", tone: "neutral",
				v: `${ibUI.shortNum(d.ot_hours, 1)} ${__("hrs")}`, sub: `${d.late_count} ${__("late arrivals")}`,
			},
			{
				key: "attrition", l: __("Attrition (12 mo)"), icon: "git-branch",
				tone: d.attrition >= 20 ? "danger" : d.attrition >= 10 ? "warn" : "ok",
				v: `${d.attrition}%`, sub: __("leavers against headcount"),
			},
		];
		this.$wrap.find("#ib-hr-kpis").html(ibUI.kpiGrid(kpis, { min: 170 })).find("[data-kpi]").on("click", (e) => {
			e.stopPropagation();
			this._drill($(e.currentTarget).attr("data-kpi"));
		});
	}

	_drill(key) {
		const today = frappe.datetime.get_today();
		const go = (dt, filters) => { frappe.route_options = filters; frappe.set_route("List", dt); };
		switch (key) {
			case "headcount": return go("Employee", { status: "Active" });
			case "present": return go("Attendance", { attendance_date: today, status: "Present", docstatus: 1 });
			case "absent": return go("Attendance", { attendance_date: today, status: "Absent", docstatus: 1 });
			case "att_rate": return go("Attendance", { attendance_date: ["between", [this._month, this._overview.meta.period_end]] });
			case "pending": return go("Leave Application", { status: "Open", docstatus: 0 });
			case "payroll": return go("Salary Slip", { start_date: this._month });
			case "overtime": return go("IB Overtime Request", { date: ["between", [this._month, this._overview.meta.period_end]] });
			case "attrition": return go("Employee", { status: "Left" });
		}
	}

	_render_charts(d) {
		const t = d.att_trend || [];
		ibDash.chart(this.$wrap.find("#ib-hr-att-trend"), {
			type: "bar", stacked: true, height: 220, currency: false, xIsSeries: 1,
			labels: t.map((r) => r.label),
			datasets: [
				{ name: __("Present"), values: t.map((r) => parseFloat(r.present || 0)) },
				{ name: __("Absent"), values: t.map((r) => parseFloat(r.absent || 0)) },
				{ name: __("On leave"), values: t.map((r) => parseFloat(r.leave_ || 0)) },
			],
			colors: ["#10b981", "#ef4444", "#f59e0b"],
			empty: __("No attendance marked this month"), emptyIcon: "calendar",
		});

		const mix = d.att_mix || [];
		ibDash.chart(this.$wrap.find("#ib-hr-att-mix"), {
			type: "donut", height: 220, currency: false, xIsSeries: 0,
			labels: mix.map((r) => r.status),
			datasets: [{ name: __("Days"), values: mix.map((r) => parseFloat(r.c || 0)) }],
			empty: __("Nothing marked yet"), emptyIcon: "calendar",
		});

		const pay = d.pay_trend || [];
		ibDash.chart(this.$wrap.find("#ib-hr-pay"), {
			type: "line", height: 230, currency: true,
			labels: pay.map((r) => r.label),
			datasets: [
				{ name: __("Net pay"), values: pay.map((r) => parseFloat(r.net || 0)) },
				{ name: __("Gross"), values: pay.map((r) => parseFloat(r.gross || 0)) },
			],
			dots: 1, empty: __("No salary slips yet"), emptyIcon: "wallet",
		});

		const lv = d.leave_by_type || [];
		ibDash.chart(this.$wrap.find("#ib-hr-leave"), {
			type: "donut", height: 200, currency: false, xIsSeries: 0,
			labels: lv.map((r) => r.label),
			datasets: [{ name: __("Days"), values: lv.map((r) => parseFloat(r.days || 0)) }],
			empty: __("No leave taken"), emptyIcon: "calendar",
		});
	}

	_render_side(d) {
		// Department names here are long ("Factory Administration - IB") — a bar
		// chart truncates every x label to "...", so this reads as a ranked list.
		const dept = (d.by_department || []).slice(0, 10);
		const $d = this.$wrap.find("#ib-hr-dept");
		if (!dept.length) {
			$d.html(ibUI.empty(__("No departments set"), "users"));
		} else {
			const dmax = Math.max(...dept.map((r) => r.c)) || 1;
			$d.html(
				`<div class="ib-dash-rank">${dept
					.map(
						(r) => `<div class="row">
							<span class="nm" title="${ibUI.esc(r.label)}">${ibUI.esc(r.label)}</span>
							${ibUI.bar((r.c / dmax) * 100, { showLabel: false })}
							<span class="amt">${r.c}</span></div>`,
					)
					.join("")}</div>`,
			);
		}
		const $m = this.$wrap.find("#ib-hr-moments");
		const moments = d.moments || [];
		if (!moments.length) {
			$m.html(ibUI.empty(__("Nothing in the next 30 days"), "calendar"));
		} else {
			$m.html(
				`<div class="ib-hr-people">${moments
					.map((p) => {
						const when = p.in_days === 0 ? __("Today") : p.in_days === 1 ? __("Tomorrow") : `${__("in")} ${p.in_days}d`;
						return `<div class="row" data-route="app/employee/${encodeURIComponent(p.name)}">
							<span class="ib-ui-pill ib-ui-pill--${p.kind === "Birthday" ? "info" : "ok"}">${p.kind === "Birthday" ? "🎂" : "🎉"}</span>
							<span class="nm">${ibUI.esc(p.employee_name)}<span class="sub">${ibUI.esc(p.department || "")}</span></span>
							<span class="when">${ibUI.esc(when)}</span></div>`;
					})
					.join("")}</div>`,
			);
			ibUI.wireRoutes($m);
		}

		const $a = this.$wrap.find("#ib-hr-absentees");
		const abs = d.absentees || [];
		if (!abs.length) return $a.html(ibUI.empty(__("Nobody absent this month"), "check-circle"));
		const max = Math.max(...abs.map((r) => r.days)) || 1;
		$a.html(
			`<div class="ib-dash-rank">${abs
				.map(
					(r) => `<div class="row" data-route="app/employee/${encodeURIComponent(r.employee)}">
						<span class="nm" title="${ibUI.esc(r.employee_name)}">${ibUI.esc(r.employee_name)}</span>
						${ibUI.bar((r.days / max) * 100, { showLabel: false })}
						<span class="amt">${r.days} ${__("d")}</span></div>`,
				)
				.join("")}</div>`,
		);
		ibUI.wireRoutes($a);
	}

	_render_tab() {
		if (!this._data) return;
		switch (this._active_tab) {
			case "attendance": this._render_attendance(); break;
			case "leaves":     this._render_leaves();     break;
			case "payroll":    this._render_payroll();    break;
		}
	}

	// prefix: "att" | "leave" | "pay"
	_filter_bar_html(prefix, placeholder, statusOptions, count) {
		const opts = ["<option value=''>All statuses</option>"]
			.concat(statusOptions.map(s => `<option value="${s}" ${this._filters[`${prefix}_status`] === s ? "selected" : ""}>${s}</option>`))
			.join("");
		return `
			<div class="ib-hr-filter-bar">
				<input type="text" class="ib-hr-search" data-prefix="${prefix}" placeholder="${placeholder}" value="${frappe.utils.escape_html(this._filters[`${prefix}_search`] || "")}">
				<select class="ib-hr-status-select" data-prefix="${prefix}">${opts}</select>
				<span class="ib-hr-filter-count">${count} record${count === 1 ? "" : "s"}</span>
			</div>`;
	}

	_bind_filter_bar(prefix) {
		const $search = this.$wrap.find(`.ib-hr-search[data-prefix="${prefix}"]`);
		const $status = this.$wrap.find(`.ib-hr-status-select[data-prefix="${prefix}"]`);
		$search.on("input", (e) => {
			const val = $(e.currentTarget).val();
			clearTimeout(this._search_debounce);
			this._search_debounce = setTimeout(() => {
				this._filters[`${prefix}_search`] = val;
				this._page[prefix] = 1;
				this.refresh();
			}, 400);
		});
		$status.on("change", (e) => {
			this._filters[`${prefix}_status`] = $(e.currentTarget).val();
			this._page[prefix] = 1;
			this.refresh();
		});
		// Preserve focus/cursor across the debounced re-render for the active field
		if (document.activeElement === $search.get(0)) {
			const el = $search.get(0);
			const pos = el.selectionStart;
			setTimeout(() => { el.focus(); el.setSelectionRange(pos, pos); }, 0);
		}
	}

	// `rows` already arrives as exactly one page from the server (LIMIT/OFFSET
	// there, not here) — `total` is the real unbounded count for that tab's
	// filters, so page count reflects what's actually in the DB, not just
	// what happened to be in a hard-capped batch.
	_paginate(rows, prefix, total) {
		const total_pages = Math.max(1, Math.ceil((total || 0) / this._page_size));
		if (this._page[prefix] > total_pages) this._page[prefix] = total_pages;
		return { page_rows: rows, total_pages };
	}

	_pagination_html(prefix, total_pages) {
		if (total_pages <= 1) return "";
		const page = this._page[prefix];
		return `
			<div class="ib-hr-pagination">
				<button class="btn btn-xs btn-default ib-hr-page-prev" data-prefix="${prefix}" ${page <= 1 ? "disabled" : ""}>&larr; Prev</button>
				<span class="ib-hr-page-info">Page ${page} of ${total_pages}</span>
				<button class="btn btn-xs btn-default ib-hr-page-next" data-prefix="${prefix}" ${page >= total_pages ? "disabled" : ""}>Next &rarr;</button>
			</div>`;
	}

	_bind_pagination(prefix) {
		this.$wrap.find(`.ib-hr-page-prev[data-prefix="${prefix}"]`).on("click", () => {
			if (this._page[prefix] > 1) { this._page[prefix]--; this.refresh(); }
		});
		this.$wrap.find(`.ib-hr-page-next[data-prefix="${prefix}"]`).on("click", () => {
			this._page[prefix]++; this.refresh();
		});
	}

	_render_attendance() {
		const rows = this._data.attendance || [];
		const status_badge = (s) => {
			const cls = s === "Present" ? "present" : s === "Absent" ? "absent"
				: s === "Half Day" ? "half" : "leave";
			return `<span class="ib-hr-status-badge ib-hr-status-${cls}">${s}</span>`;
		};

		const total = this._data.attendance_total || 0;
		let html = this._filter_bar_html("att", "Search employee…", ["Present", "Absent", "Half Day", "On Leave"], total);
		const { page_rows, total_pages } = this._paginate(rows, "att", total);

		if (!rows.length) {
			html += `<div style="padding:20px;text-align:center;color:var(--text-muted);font-size:12px">No matching attendance records</div>`;
		} else {
			html += `<table class="ib-hr-table">
				<thead><tr><th>Employee</th><th>Name</th><th>Department</th><th>Date</th><th>Status</th></tr></thead>
				<tbody>${page_rows.map(r => `
					<tr>
						<td><a href="#" class="ib-hr-emp-link" data-emp="${frappe.utils.escape_html(r.employee)}">${frappe.utils.escape_html(r.employee || "")}</a></td>
						<td>${frappe.utils.escape_html(r.employee_name || "")}</td>
						<td>${frappe.utils.escape_html(r.department || "—")}</td>
						<td>${frappe.datetime.str_to_user(r.attendance_date) || r.attendance_date}</td>
						<td>${status_badge(r.status || "")}</td>
					</tr>
				`).join("")}</tbody>
			</table>`;
			html += this._pagination_html("att", total_pages);
		}
		this.$wrap.find("#ib-hr-content").html(html);
		this.$wrap.find(".ib-hr-emp-link").on("click", function (e) {
			e.preventDefault();
			frappe.set_route("Form", "Employee", $(this).data("emp"));
		});
		this._bind_filter_bar("att");
		this._bind_pagination("att");
	}

	_render_leaves() {
		const rows = this._data.leaves || [];
		const status_badge = (s) => {
			const cls = s === "Open" ? "open" : s === "Approved" ? "approved" : "rejected";
			return `<span class="ib-hr-status-badge ib-hr-status-${cls}">${s}</span>`;
		};
		const is_mgr = frappe.user.has_role("HR Manager") || frappe.user.has_role("System Manager");

		const total = this._data.leave_total || 0;
		let html = this._filter_bar_html("leave", "Search employee…", ["Open", "Approved", "Rejected"], total);
		const { page_rows, total_pages } = this._paginate(rows, "leave", total);
		if (!rows.length) {
			html += `<div style="padding:20px;text-align:center;color:var(--text-muted);font-size:12px">No matching leave applications</div>`;
		} else {
			html += `<table class="ib-hr-table">
				<thead><tr><th>Employee</th><th>Leave Type</th><th>From</th><th>To</th><th>Days</th><th>Status</th>${is_mgr ? "<th>Actions</th>" : ""}</tr></thead>
				<tbody>${page_rows.map(r => `
					<tr data-leave="${frappe.utils.escape_html(r.name)}">
						<td><a href="#" class="ib-hr-leave-link" data-leave="${frappe.utils.escape_html(r.name)}">${frappe.utils.escape_html(r.employee_name || r.employee || "")}</a></td>
						<td>${frappe.utils.escape_html(r.leave_type || "")}</td>
						<td>${frappe.datetime.str_to_user(r.from_date) || r.from_date}</td>
						<td>${frappe.datetime.str_to_user(r.to_date) || r.to_date}</td>
						<td>${r.total_leave_days || ""}</td>
						<td>${status_badge(r.status || "")}</td>
						${is_mgr && r.status === "Open" ? `<td>
							<button class="ib-hr-act-btn ib-hr-act-btn--approve ib-hr-approve-btn" data-id="${frappe.utils.escape_html(r.name)}" data-employee="${frappe.utils.escape_html(r.employee_name || r.name)}">Approve</button>
							<button class="ib-hr-act-btn ib-hr-act-btn--reject ib-hr-reject-btn" data-id="${frappe.utils.escape_html(r.name)}" data-employee="${frappe.utils.escape_html(r.employee_name || r.name)}">Reject</button>
						</td>` : `<td></td>`}
					</tr>
				`).join("")}</tbody>
			</table>`;
			html += this._pagination_html("leave", total_pages);
		}
		this.$wrap.find("#ib-hr-content").html(html);
		this.$wrap.find(".ib-hr-leave-link").on("click", function (e) {
			e.preventDefault();
			frappe.set_route("Form", "Leave Application", $(this).data("leave"));
		});

		if (is_mgr) {
			this.$wrap.find(".ib-hr-approve-btn").on("click", (e) => {
				const id = $(e.currentTarget).data("id");
				const employee = $(e.currentTarget).data("employee");
				frappe.confirm(`Approve leave for <b>${frappe.utils.escape_html(employee)}</b> (${id})?`, () => {
					frappe.call({
						method: "instabiz.instabiz.page.ib_hrms_dashboard.ib_hrms_dashboard.approve_leave",
						args: { leave_id: id },
						callback: (r) => {
							if (r.message?.status === "ok") {
								frappe.show_alert({ message: "Leave approved", indicator: "green" });
								this.refresh();
							}
						},
						error: () => frappe.show_alert({ message: "Approve failed", indicator: "red" }),
					});
				});
			});
			this.$wrap.find(".ib-hr-reject-btn").on("click", (e) => {
				const id = $(e.currentTarget).data("id");
				const employee = $(e.currentTarget).data("employee");
				frappe.confirm(`Reject leave for <b>${frappe.utils.escape_html(employee)}</b> (${id})?`, () => {
					frappe.call({
						method: "instabiz.instabiz.page.ib_hrms_dashboard.ib_hrms_dashboard.reject_leave",
						args: { leave_id: id },
						callback: (r) => {
							if (r.message?.status === "ok") {
								frappe.show_alert({ message: "Leave rejected", indicator: "orange" });
								this.refresh();
							}
						},
						error: () => frappe.show_alert({ message: "Reject failed", indicator: "red" }),
					});
				});
			});
		}
		this._bind_filter_bar("leave");
		this._bind_pagination("leave");
	}

	_render_payroll() {
		const slips = this._data.salary_slips || [];
		const fmt = (v) => "₹" + Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 });
		const month_start = this._month;
		const is_mgr = frappe.user.has_role("HR Manager") || frappe.user.has_role("System Manager");

		// Real totals across the whole filtered set (server-aggregated) — slips
		// here is just the current page, so these can't be derived from it once
		// pagination is real instead of "cap at 100, sum in JS".
		const total_records = this._data.pay_total || 0;
		const submitted_count = this._data.pay_submitted_count || 0;
		const draft_count = this._data.pay_draft_count || 0;
		const submitted_net_total = this._data.pay_submitted_net_total || 0;

		const mgr_btns = is_mgr ? `
			<div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap">
				<button class="btn btn-sm btn-default ib-hr-gen-slips">⚙ Generate Payroll (All)</button>
				<button class="btn btn-sm btn-default ib-hr-gen-single">+ Generate Slip for Employee</button>
				${draft_count ? `<button class="btn btn-sm btn-primary ib-hr-submit-all">✓ Submit All Drafts (${draft_count})</button>` : ""}
			</div>` : "";
		const filter_bar = this._filter_bar_html("pay", "Search employee…", ["Draft", "Submitted"], total_records);

		if (!slips.length) {
			this.$wrap.find("#ib-hr-content").html(`
				${mgr_btns}
				${filter_bar}
				<div style="padding:20px;text-align:center;color:var(--text-muted);font-size:12px">
					No matching salary slips for this month.
				</div>`);
			this._bind_payroll_btns(month_start, draft_count);
			this._bind_filter_bar("pay");
			return;
		}
		const draftInfo = draft_count ? ` &nbsp;·&nbsp; <span style="color:#f59e0b;font-weight:500">${draft_count} draft${draft_count > 1 ? "s" : ""} pending submit</span>` : "";
		const { page_rows, total_pages } = this._paginate(slips, "pay", total_records);
		this.$wrap.find("#ib-hr-content").html(`
			${mgr_btns}
			${filter_bar}
			<div style="margin-bottom:10px;font-size:13px;display:flex;align-items:center;gap:12px;flex-wrap:wrap">
				<span><strong>${submitted_count}</strong> submitted · Net Pay: <strong style="color:var(--ib-primary)">${fmt(submitted_net_total)}</strong>${draftInfo}</span>
				<a href="#" class="ib-hr-view-all-slips" style="margin-left:auto;font-size:11px;color:var(--ib-primary)">View all in list →</a>
			</div>
			<table class="ib-hr-table">
				<thead><tr><th>Employee</th><th>Name</th><th>Gross Pay</th><th>Deductions</th><th>Net Pay</th><th>Status</th></tr></thead>
				<tbody>${page_rows.map(r => `
					<tr>
						<td><a href="#" class="ib-hr-emp-link" data-emp="${frappe.utils.escape_html(r.employee)}">${frappe.utils.escape_html(r.employee || "")}</a></td>
						<td><a href="#" class="ib-hr-slip-link" data-slip="${frappe.utils.escape_html(r.name)}">${frappe.utils.escape_html(r.employee_name || "")}</a></td>
						<td>${fmt(r.gross_pay)}</td>
						<td style="color:#dc2626">${fmt(r.total_deduction)}</td>
						<td style="font-weight:600;color:var(--ib-primary)">${fmt(r.net_pay)}</td>
						<td><span class="ib-hr-status-badge ${r.slip_status === 'Submitted' ? 'ib-hr-status-present' : 'ib-hr-status-half'}">${frappe.utils.escape_html(r.slip_status || '')}</span></td>
					</tr>
				`).join("")}</tbody>
			</table>
			${this._pagination_html("pay", total_pages)}
		`);
		this.$wrap.find(".ib-hr-slip-link").on("click", function (e) {
			e.preventDefault();
			frappe.set_route("Form", "Salary Slip", $(this).data("slip"));
		});
		// Employee-ID column's own link — was only ever bound inside
		// _render_attendance(), so the Payroll tab's emp-link anchors
		// (added 2026-08-13) rendered but did nothing on click.
		this.$wrap.find(".ib-hr-emp-link").on("click", function (e) {
			e.preventDefault();
			frappe.set_route("Form", "Employee", $(this).data("emp"));
		});
		this.$wrap.find(".ib-hr-view-all-slips").on("click", (e) => {
			e.preventDefault();
			frappe.route_options = { start_date: month_start };
			frappe.set_route("List", "Salary Slip");
		});
		this._bind_payroll_btns(month_start, draft_count);
		this._bind_filter_bar("pay");
		this._bind_pagination("pay");
	}

	_open_generate_single_dialog(month_start) {
		const d = new frappe.ui.Dialog({
			title: __("Generate Salary Slip for Employee"),
			fields: [
				{
					fieldname: "employee", fieldtype: "Link", options: "Employee",
					label: "Employee", reqd: 1,
					get_query: () => ({ filters: { status: "Active" } }),
				},
				{
					fieldname: "notify", fieldtype: "Check", label: "Notify employee (bell notification)",
					default: 1,
				},
			],
			primary_action_label: __("Generate"),
			primary_action: (values) => {
				d.disable_primary_action();
				frappe.call({
					method: "instabiz.instabiz.page.ib_hrms_dashboard.ib_hrms_dashboard.generate_single_slip",
					args: { employee: values.employee, month: month_start, notify: values.notify ? 1 : 0 },
					callback: (r) => {
						d.enable_primary_action();
						const res = r.message || {};
						if (res.status === "exists") {
							frappe.show_alert({ message: `Slip already exists: ${res.slip}`, indicator: "orange" });
						} else if (res.status === "created") {
							frappe.show_alert({ message: `Slip ${res.slip} generated`, indicator: "green" });
						}
						d.hide();
						this.refresh();
					},
					error: () => d.enable_primary_action(),
				});
			},
		});
		d.show();
	}

	_bind_payroll_btns(month_start, draft_count) {
		this.$wrap.find(".ib-hr-gen-single").on("click", () => this._open_generate_single_dialog(month_start));
		this.$wrap.find(".ib-hr-gen-slips").on("click", () => {
			frappe.confirm(`Generate salary slips for ${month_start.slice(0, 7)}?`, () => {
				frappe.show_alert({ message: "Generating payroll…", indicator: "blue" });
				frappe.call({
					method: "instabiz.overrides.payroll.trigger_payroll_draft",
					args: { month: month_start },
					callback: (r) => {
						if (r.message) {
							frappe.show_alert({ message: r.message.summary || "Done", indicator: "green" });
							this.refresh();
						}
					},
					error: () => frappe.show_alert({ message: "Failed — check error log", indicator: "red" }),
				});
			});
		});
		if (draft_count) {
			this.$wrap.find(".ib-hr-submit-all").on("click", () => {
				frappe.confirm(`Submit all ${draft_count} draft salary slips for ${month_start.slice(0, 7)}?`, () => {
					frappe.show_alert({ message: "Submitting…", indicator: "blue" });
					frappe.call({
						method: "instabiz.overrides.payroll.submit_all_drafts",
						args: { month_start },
						callback: (r) => {
							const res = r.message || {};
							frappe.show_alert({ message: `Submitted ${res.submitted || 0} slips`, indicator: "green" });
							this.refresh();
						},
						error: () => frappe.show_alert({ message: "Failed — check error log", indicator: "red" }),
					});
				});
			});
		}
	}
}
