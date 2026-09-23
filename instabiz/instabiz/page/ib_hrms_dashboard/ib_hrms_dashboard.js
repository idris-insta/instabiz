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

	_build_layout() {
		const $pc = $(this.wrapper).find(".page-content");
		this.$wrap = $(`<div class="ib-hr-wrap"></div>`).appendTo($pc);
		this.$wrap.html(`
			<div class="ib-hr-top-bar">
				<button class="btn btn-xs btn-default" id="ib-hr-refresh">↻ Refresh</button>
				<span class="ib-hr-ts" id="ib-hr-ts"></span>
			</div>
			<div class="ib-hr-kpi-row" id="ib-hr-kpis"></div>
			<div class="ib-hr-tabs">
				<button class="ib-hr-tab active" data-tab="attendance">Attendance</button>
				<button class="ib-hr-tab" data-tab="leaves">Leaves</button>
				<button class="ib-hr-tab" data-tab="payroll">Payroll</button>
			</div>
			<div class="ib-hr-card" id="ib-hr-content"></div>
		`);

		this.$wrap.find(".ib-hr-tab").on("click", (e) => {
			const tab = $(e.currentTarget).data("tab");
			this.$wrap.find(".ib-hr-tab").removeClass("active");
			$(e.currentTarget).addClass("active");
			this._active_tab = tab;
			this._render_tab();
		});

		this.$wrap.find("#ib-hr-refresh").on("click", () => this.refresh());
	}

	_bind_toolbar() {
		// Month picker removed 2026-08-13 — this dashboard always shows the
		// current month now, no historical browsing. this._month stays fixed
		// at whatever the constructor set it to (today's month).
		this.page.add_button(__("Go to Employees"), () => frappe.set_route("List", "Employee"));
		this.page.add_button(__("New Leave"), () => frappe.new_doc("Leave Application"));
	}

	_set_ts(text) {
		this.$wrap.find("#ib-hr-ts").text(text);
	}

	refresh() {
		const req_month = this._month;
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
				this._render_kpis(r.message);
				this._render_tab();
				this._set_ts("Updated " + frappe.datetime.now_time());
				ib_countup_all && ib_countup_all(this.$wrap);
			},
			error: () => {
				if (this._month === req_month) this._set_ts("Error — click Refresh");
			},
		});
		if (opts) {
			this._set_ts("Loading…");
			this.$wrap.find("#ib-hr-kpis").html(window.ib_skel_kpis ? ib_skel_kpis(4) : "");
			frappe.call(opts);
		}
	}

	_render_kpis(d) {
		const fmt = (v) => "₹" + Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 });
		const today = frappe.datetime.get_today();
		const month_start = this._month;
		const attend_pct = d.total_emp ? Math.round(d.present_today / d.total_emp * 100) : 0;
		const payrollLabel = d.payroll_is_draft
			? "Payroll MTD (draft)"
			: (d.payroll_draft_count ? `Payroll MTD +${d.payroll_draft_count} drafts` : "Payroll MTD");
		const kpis = [
			{
				label: "Active Employees", val: d.total_emp, rawNum: d.total_emp, color: "#06b6d4",
				click() { frappe.route_options = { status: "Active" }; frappe.set_route("List", "Employee"); },
			},
			{
				label: "Present Today", val: `${d.present_today} (${attend_pct}%)`, rawNum: null, color: "#10b981",
				click() { frappe.route_options = { attendance_date: today, status: "Present", docstatus: 1 }; frappe.set_route("List", "Attendance"); },
			},
			{
				label: "Absent Today", val: d.absent_today, rawNum: d.absent_today, color: "#ef4444",
				click() { frappe.route_options = { attendance_date: today, status: "Absent", docstatus: 1 }; frappe.set_route("List", "Attendance"); },
			},
			{
				label: "Pending Leaves", val: d.pending_leaves, rawNum: d.pending_leaves, color: "#f59e0b",
				click() { frappe.route_options = { status: "Open", docstatus: 0 }; frappe.set_route("List", "Leave Application"); },
			},
			{
				label: payrollLabel,
				val: window.ib_fmt_inr_compact ? window.ib_fmt_inr_compact(d.payroll_mtd) : fmt(d.payroll_mtd),
				rawNum: d.payroll_mtd, isInr: true, color: "#d97757",
				click() { frappe.route_options = { start_date: month_start }; frappe.set_route("List", "Salary Slip"); },
			},
		];
		const $kpis = this.$wrap.find("#ib-hr-kpis").html(kpis.map((k, i) => {
			const rawNum = typeof k.rawNum !== "undefined" ? k.rawNum : null;
			const cuAttr = rawNum !== null
				? (k.isInr ? `data-countup="${rawNum}" data-cu-inr="1" data-cu-compact="1"` : `data-countup="${rawNum}"`)
				: "";
			const titleAttr = k.isInr ? `title="${fmt(rawNum)}"` : "";
			return `
			<div class="ib-hr-kpi ib-hr-kpi--link" data-kpi="${i}" style="border-top-color:${k.color};cursor:pointer">
				<div class="ib-hr-kpi-val" style="color:${k.color}" ${cuAttr} ${titleAttr}>${k.val}</div>
				<div class="ib-hr-kpi-lbl">${k.label}</div>
				<div style="position:absolute;bottom:8px;right:10px;font-size:10px;color:${k.color};opacity:.5">→</div>
			</div>`;
		}).join(""));
		$kpis.find(".ib-hr-kpi--link").on("click", (e) => {
			kpis[parseInt($(e.currentTarget).data("kpi"), 10)].click();
		});
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
