frappe.pages["ib-my-hr"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({ parent: wrapper, title: "My HR", single_column: true });
	wrapper._ib_my_hr = new IBMyHR(wrapper);
};

frappe.pages["ib-my-hr"].on_page_show = function (wrapper) {
	if (wrapper._ib_my_hr) wrapper._ib_my_hr.refresh();
};

// ─────────────────────────────────────────────────────────────────────────────

class IBMyHR {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.page    = wrapper.page;
		this._data   = null;
		this._active_tab = "leaves";
		this._month  = frappe.datetime.get_today().slice(0, 7) + "-01";

		this._inject_styles();
		this._build_layout();
		this._bind_toolbar();
	}

	// ── Styles ────────────────────────────────────────────────────────────────

	_inject_styles() {
		if (document.getElementById("ib-myhr-styles")) return;
		const s = document.createElement("style");
		s.id = "ib-myhr-styles";
		s.textContent = `
:root { --myhr-primary:var(--ib-primary, #d97757); --myhr-green:#059669; --myhr-red:#dc2626;
        --myhr-orange:#ea580c; --myhr-yellow:#d97706; --myhr-indigo:#4338ca; }

.ib-myhr-wrap { padding: 16px; max-width: 1100px; }

/* Profile card */
.ib-myhr-profile { display:flex; align-items:center; gap:14px; background:var(--card-bg);
  border:1px solid var(--border-color); border-radius:10px; padding:16px 20px;
  margin-bottom:16px; }
.ib-myhr-avatar { width:52px; height:52px; border-radius:50%; object-fit:cover;
  background:var(--myhr-primary)18; display:flex; align-items:center; justify-content:center;
  font-size:22px; font-weight:700; color:var(--myhr-primary); flex-shrink:0; }
.ib-myhr-profile-name { font-size:16px; font-weight:700; color:var(--heading-color); }
.ib-myhr-profile-meta { font-size:12px; color:var(--text-muted); margin-top:2px; }
.ib-myhr-profile-right { margin-left:auto; display:flex; gap:8px; }

/* Leave balance chips */
.ib-myhr-balance-row { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:16px; }
.ib-myhr-balance-chip { background:var(--card-bg); border:1px solid var(--border-color);
  border-radius:8px; padding:10px 14px; min-width:130px; }
.ib-myhr-chip-type { font-size:10px; color:var(--text-muted); text-transform:uppercase;
  letter-spacing:.4px; margin-bottom:4px; }
.ib-myhr-chip-vals { display:flex; align-items:baseline; gap:4px; }
.ib-myhr-chip-remaining { font-size:20px; font-weight:800; color:var(--heading-color); }
.ib-myhr-chip-total { font-size:11px; color:var(--text-muted); }
.ib-myhr-chip-bar { height:3px; border-radius:2px; margin-top:6px; background:var(--border-color); }
.ib-myhr-chip-bar-fill { height:100%; border-radius:2px; background:var(--myhr-primary); }

/* Attendance summary strip */
.ib-myhr-att-strip { display:flex; gap:8px; margin-bottom:16px; flex-wrap:wrap; }
.ib-myhr-att-pill { display:flex; align-items:center; gap:5px; padding:6px 12px;
  border-radius:20px; font-size:12px; font-weight:600; }
.ib-myhr-att-pill--present { background:#d1fae518; color:var(--myhr-green); border:1px solid #d1fae5; }
.ib-myhr-att-pill--absent  { background:#fee2e218; color:var(--myhr-red);   border:1px solid #fee2e2; }
.ib-myhr-att-pill--leave   { background:#e0e7ff18; color:var(--myhr-indigo);  border:1px solid #e0e7ff; }
.ib-myhr-att-pill--half    { background:#fef3c718; color:var(--myhr-yellow);border:1px solid #fef3c7; }
.ib-myhr-att-pill--pending { background:#fef9c318; color:#b45309;           border:1px solid #fef08a; }

/* Tabs */
.ib-myhr-tabs { display:flex; gap:4px; margin-bottom:14px; flex-wrap:wrap; }
.ib-myhr-tab { padding:6px 14px; border-radius:6px; font-size:12px; font-weight:500;
  cursor:pointer; border:1px solid var(--border-color); background:var(--card-bg); color:var(--text-muted); }
.ib-myhr-tab.active { background:var(--myhr-primary); color:#fff; border-color:var(--myhr-primary); }

.ib-myhr-card { background:var(--card-bg); border:1px solid var(--border-color);
  border-radius:8px; padding:16px; overflow-x:auto; }

/* Tables */
.ib-myhr-tbl { width:100%; border-collapse:collapse; font-size:12px; }
.ib-myhr-tbl th { text-align:left; padding:7px 8px; font-size:11px; color:var(--text-muted);
  border-bottom:1px solid var(--border-color); }
.ib-myhr-tbl td { padding:7px 8px; border-bottom:1px solid var(--border-color); vertical-align:middle; }
.ib-myhr-tbl tr:last-child td { border-bottom:none; }
.ib-myhr-tbl tr:hover td { background:var(--bg-color); }

/* Badges */
.ib-myhr-badge { display:inline-block; padding:2px 8px; border-radius:10px; font-size:10px; font-weight:600; }
.ib-myhr-badge--open     { background:#fef3c7; color:#92400e; }
.ib-myhr-badge--approved { background:#d1fae5; color:#065f46; }
.ib-myhr-badge--rejected { background:#fee2e2; color:#991b1b; }
.ib-myhr-badge--draft    { background:#f3f4f6; color:#374151; }

/* Apply form */
.ib-myhr-apply-form { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
.ib-myhr-apply-form .ib-myhr-field-full { grid-column:1/-1; }
.ib-myhr-field label { display:block; font-size:11px; font-weight:600; color:var(--text-muted);
  text-transform:uppercase; letter-spacing:.4px; margin-bottom:4px; }
.ib-myhr-field input, .ib-myhr-field select, .ib-myhr-field textarea {
  width:100%; padding:7px 10px; border:1px solid var(--border-color); border-radius:6px;
  font-size:13px; background:var(--input-bg, #fff); color:var(--text-color);
  box-sizing:border-box; }
.ib-myhr-field textarea { resize:vertical; min-height:64px; }
.ib-myhr-field input:focus, .ib-myhr-field select:focus, .ib-myhr-field textarea:focus {
  outline:none; border-color:var(--myhr-primary); }
.ib-myhr-apply-actions { display:flex; gap:8px; margin-top:4px; }
.ib-myhr-btn-primary { padding:8px 18px; border-radius:7px; border:none;
  background:var(--myhr-primary); color:#fff; font-size:13px; font-weight:600; cursor:pointer; }
.ib-myhr-btn-primary:disabled { opacity:.5; cursor:not-allowed; }
.ib-myhr-btn-secondary { padding:8px 14px; border-radius:7px; background:var(--card-bg);
  border:1px solid var(--border-color); color:var(--text-muted); font-size:13px; cursor:pointer; }
.ib-myhr-half-row { display:flex; align-items:center; gap:8px; font-size:13px; }

/* Payslip cards */
.ib-myhr-payslip-list { display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:10px; }
.ib-myhr-payslip-card { background:var(--card-bg); border:1px solid var(--border-color);
  border-radius:8px; padding:14px; }
.ib-myhr-payslip-month { font-size:12px; font-weight:700; color:var(--heading-color); margin-bottom:6px; }
.ib-myhr-payslip-row { display:flex; justify-content:space-between; font-size:11px;
  padding:2px 0; color:var(--text-muted); }
.ib-myhr-payslip-net { font-size:15px; font-weight:800; color:var(--myhr-green); margin-top:6px; }
.ib-myhr-payslip-open { display:block; margin-top:8px; font-size:11px; color:var(--myhr-primary);
  text-decoration:none; font-weight:600; }

/* Attendance calendar */
.ib-myhr-att-grid { display:grid; grid-template-columns:repeat(7,1fr); gap:4px; margin-top:8px; }
.ib-myhr-att-cell { aspect-ratio:1; border-radius:6px; display:flex; flex-direction:column;
  align-items:center; justify-content:center; font-size:10px; font-weight:600;
  border:1px solid var(--border-color); }
.ib-myhr-att-cell--hdr { aspect-ratio:auto; padding:3px; font-size:9px; color:var(--text-muted);
  text-transform:uppercase; border:none; }
.ib-myhr-att-cell--present  { background:#d1fae518; color:var(--myhr-green); border-color:#d1fae5; }
.ib-myhr-att-cell--absent   { background:#fee2e218; color:var(--myhr-red);   border-color:#fee2e2; }
.ib-myhr-att-cell--leave    { background:#e0e7ff18; color:var(--myhr-indigo);  border-color:#e0e7ff; }
.ib-myhr-att-cell--half     { background:#fef3c718; color:var(--myhr-yellow);border-color:#fef3c7; }
.ib-myhr-att-cell--weekend  { background:var(--bg-color); color:var(--text-muted); }
.ib-myhr-att-cell--future   { opacity:.25; }
.ib-myhr-att-cell--empty    { border:none; background:transparent; }
.ib-myhr-att-legend { display:flex; gap:10px; flex-wrap:wrap; margin-top:10px; font-size:11px; color:var(--text-muted); }
.ib-myhr-att-legend-dot { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:3px; }

/* Empty state */
.ib-myhr-empty { text-align:center; padding:40px 20px; color:var(--text-muted); font-size:13px; }

/* Historical-month indicator (reuses the app's shared refresh-time look) */
.ib-myhr-hist-badge { font-size:11px; color:var(--text-muted); }
.ib-myhr-hist-badge--active { color:#b45309; font-weight:600; }

@media(max-width:600px) {
  .ib-myhr-apply-form { grid-template-columns:1fr; }
  .ib-myhr-balance-row { gap:6px; }
  .ib-myhr-balance-chip { min-width:110px; }
  .ib-myhr-att-grid { grid-template-columns:repeat(7,1fr); gap:2px; }
}
		`;
		document.head.appendChild(s);
	}

	// ── Layout ────────────────────────────────────────────────────────────────

	_build_layout() {
		const $pc = $(this.wrapper).find(".page-content");
		this.$wrap = $(`<div class="ib-myhr-wrap"></div>`).appendTo($pc);
		this.$wrap.html(`
			<div id="ib-myhr-profile"></div>
			<div id="ib-myhr-balance"></div>
			<div id="ib-myhr-att-strip"></div>
			<div class="ib-myhr-tabs" id="ib-myhr-tabs">
				<button class="ib-myhr-tab active" data-tab="leaves">My Leaves</button>
				<button class="ib-myhr-tab" data-tab="apply">Apply Leave</button>
				<button class="ib-myhr-tab" data-tab="attendance">Attendance</button>
				<button class="ib-myhr-tab" data-tab="payslips">Payslips</button>
			</div>
			<div class="ib-myhr-card" id="ib-myhr-content">
				<div class="ib-myhr-empty">Loading…</div>
			</div>
		`);

		this.$wrap.find(".ib-myhr-tab").on("click", (e) => {
			const tab = $(e.currentTarget).data("tab");
			this.$wrap.find(".ib-myhr-tab").removeClass("active");
			$(e.currentTarget).addClass("active");
			this._active_tab = tab;
			if (this._data) this._render_tab();
		});
	}

	_bind_toolbar() {
		this._month_field = this.page.add_field({
			fieldname: "month",
			fieldtype: "Date",
			label: "Month",
			default: this._month,
			change: () => {
				const val = this._month_field && this._month_field.get_value();
				if (val) { this._month = val; this.refresh(); }
			},
		});
		this.$hist_label = this.page.add_inner_message("").addClass("ib-myhr-hist-badge");
		this.page.add_button(__("↻ Refresh"), () => this.refresh());
	}

	// Attendance tab is scoped to the selected month — flag it when that
	// month isn't the live current one (Leaves/Payslips tabs use their own
	// fixed recent-history windows, unaffected by this filter).
	_update_hist_badge() {
		if (!this.$hist_label) return;
		const cur_month = frappe.datetime.get_today().slice(0, 7) + "-01";
		const hist = this._month !== cur_month;
		const label = hist
			? `Viewing historical data for ${frappe.datetime.str_to_obj(this._month).toLocaleDateString("en-IN", { month: "long", year: "numeric" })}`
			: "";
		this.$hist_label.text(label).toggleClass("ib-myhr-hist-badge--active", hist);
	}

	// ── Data ──────────────────────────────────────────────────────────────────

	refresh() {
		this._update_hist_badge();
		frappe.call({
			method: "instabiz.instabiz.page.ib_my_hr.ib_my_hr.get_my_hr_data",
			args: { month: this._month },
			callback: (r) => {
				if (!r.message) return;
				this._data = r.message;
				this._render_all();
			},
			error: (err) => {
				const msg = err?.responseJSON?.exc_type === "ValidationError"
					? (err?.responseJSON?.message || "Employee record not found.")
					: "Failed to load HR data.";
				this.$wrap.find("#ib-myhr-content").html(
					`<div class="ib-myhr-empty">${frappe.utils.escape_html(msg)}</div>`
				);
			},
		});
	}

	// ── Render ────────────────────────────────────────────────────────────────

	_render_all() {
		this._render_profile();
		this._render_balance();
		this._render_att_strip();
		this._render_tab();
	}

	_render_profile() {
		const emp = this._data.employee || {};
		const initials = (emp.employee_name || "?").split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase();
		const avatar = emp.image
			? `<img src="${frappe.utils.escape_html(emp.image)}" style="width:52px;height:52px;border-radius:50%;object-fit:cover;">`
			: `<div class="ib-myhr-avatar">${initials}</div>`;
		this.$wrap.find("#ib-myhr-profile").html(`
			<div class="ib-myhr-profile">
				${avatar}
				<div>
					<div class="ib-myhr-profile-name">${frappe.utils.escape_html(emp.employee_name || "")}</div>
					<div class="ib-myhr-profile-meta">
						${frappe.utils.escape_html(emp.designation || "")}
						${emp.department ? ` · ${frappe.utils.escape_html(emp.department)}` : ""}
						${emp.date_of_joining ? ` · Joined ${frappe.format(emp.date_of_joining, {fieldtype:"Date"})}` : ""}
					</div>
				</div>
				<div class="ib-myhr-profile-right">
					<a href="/app/employee/${encodeURIComponent(emp.name)}" target="_blank"
					   class="ib-myhr-btn-secondary" style="text-decoration:none;padding:6px 12px;font-size:12px;">
						View Profile
					</a>
				</div>
			</div>
		`);
	}

	_render_balance() {
		const allocs = this._data.allocations || [];
		if (!allocs.length) {
			this.$wrap.find("#ib-myhr-balance").html(
				`<p style="font-size:12px;color:var(--text-muted);margin-bottom:12px;">No leave allocations found for this year.</p>`
			);
			return;
		}
		const chips = allocs.map(a => {
			const rem = parseFloat(a.remaining || 0);
			const total = parseFloat(a.total_leaves_allocated || 0);
			const pct = total > 0 ? Math.round((rem / total) * 100) : 0;
			const barColor = pct > 50 ? "var(--myhr-green)" : pct > 20 ? "var(--myhr-orange)" : "var(--myhr-red)";
			return `
			<div class="ib-myhr-balance-chip">
				<div class="ib-myhr-chip-type">${frappe.utils.escape_html(a.leave_type)}</div>
				<div class="ib-myhr-chip-vals">
					<span class="ib-myhr-chip-remaining">${rem}</span>
					<span class="ib-myhr-chip-total">/ ${total} days</span>
				</div>
				<div class="ib-myhr-chip-bar">
					<div class="ib-myhr-chip-bar-fill" style="width:${pct}%;background:${barColor}"></div>
				</div>
			</div>`;
		}).join("");
		this.$wrap.find("#ib-myhr-balance").html(
			`<div class="ib-myhr-balance-row">${chips}</div>`
		);
	}

	_render_att_strip() {
		const s = this._data.summary || {};
		const esc = frappe.utils.escape_html;
		this.$wrap.find("#ib-myhr-att-strip").html(`
			<div class="ib-myhr-att-strip">
				<span class="ib-myhr-att-pill ib-myhr-att-pill--present">✓ ${s.present || 0} Present</span>
				<span class="ib-myhr-att-pill ib-myhr-att-pill--absent">✗ ${s.absent || 0} Absent</span>
				<span class="ib-myhr-att-pill ib-myhr-att-pill--leave">⊖ ${s.on_leave || 0} On Leave</span>
				${s.half_day ? `<span class="ib-myhr-att-pill ib-myhr-att-pill--half">½ ${s.half_day} Half Day</span>` : ""}
				${s.pending_leave_requests ? `<span class="ib-myhr-att-pill ib-myhr-att-pill--pending">⏳ ${s.pending_leave_requests} Pending</span>` : ""}
			</div>
		`);
	}

	_render_tab() {
		const $c = this.$wrap.find("#ib-myhr-content");
		if (this._active_tab === "leaves")     this._render_leaves($c);
		else if (this._active_tab === "apply") this._render_apply($c);
		else if (this._active_tab === "attendance") this._render_attendance($c);
		else if (this._active_tab === "payslips")   this._render_payslips($c);
	}

	// ── Tab: My Leaves ────────────────────────────────────────────────────────

	_render_leaves($c) {
		const leaves = this._data.leaves || [];
		if (!leaves.length) {
			$c.html(`<div class="ib-myhr-empty">No leave applications yet. Use "Apply Leave" to submit one.</div>`);
			return;
		}
		const esc = frappe.utils.escape_html;
		const badge = (status) => {
			const cls = { Open:"open", Approved:"approved", Rejected:"rejected", Draft:"draft" }[status] || "draft";
			return `<span class="ib-myhr-badge ib-myhr-badge--${cls}">${esc(status)}</span>`;
		};
		const rows = leaves.map(l => `
			<tr>
				<td><a href="/app/leave-application/${encodeURIComponent(l.name)}" target="_blank"
				       style="color:var(--myhr-primary);font-weight:600;">${esc(l.name)}</a></td>
				<td>${esc(l.leave_type)}</td>
				<td style="white-space:nowrap;">${frappe.format(l.from_date, {fieldtype:"Date"})}</td>
				<td style="white-space:nowrap;">${frappe.format(l.to_date, {fieldtype:"Date"})}</td>
				<td style="text-align:center;">${flt(l.total_leave_days, 1)}</td>
				<td>${badge(l.status)}</td>
				<td>${l.status === "Open" ? `<button class="ib-myhr-btn-secondary ib-myhr-cancel-leave btn btn-xs btn-default"
					data-id="${esc(l.name)}">Cancel</button>` : ""}</td>
			</tr>
		`).join("");
		$c.html(`
			<table class="ib-myhr-tbl">
				<thead><tr>
					<th>Application</th><th>Type</th><th>From</th><th>To</th>
					<th style="text-align:center;">Days</th><th>Status</th><th></th>
				</tr></thead>
				<tbody>${rows}</tbody>
			</table>
		`);

		$c.find(".ib-myhr-cancel-leave").on("click", (e) => {
			const id = $(e.currentTarget).data("id");
			frappe.confirm(`Cancel leave application <b>${id}</b>?`, () => {
				frappe.call({
					method: "instabiz.instabiz.page.ib_my_hr.ib_my_hr.cancel_leave",
					args: { leave_id: id },
					callback: () => {
						frappe.show_alert({ message: "Leave cancelled", indicator: "orange" });
						this.refresh();
					},
					error: () => frappe.show_alert({ message: "Cancel failed", indicator: "red" }),
				});
			});
		});
	}

	// ── Tab: Apply Leave ──────────────────────────────────────────────────────

	_render_apply($c) {
		$c.html(`<div class="ib-myhr-empty">Loading leave types…</div>`);
		frappe.call({
			method: "instabiz.instabiz.page.ib_my_hr.ib_my_hr.get_leave_types",
			callback: (r) => {
				const types = r.message || [];
				const opts = types.map(t => `<option value="${frappe.utils.escape_html(t)}">${frappe.utils.escape_html(t)}</option>`).join("");
				const today = frappe.datetime.get_today();
				$c.html(`
					<div style="max-width:600px;">
						<h4 style="font-size:14px;font-weight:700;margin:0 0 14px;color:var(--heading-color);">Apply for Leave</h4>
						<div class="ib-myhr-apply-form">
							<div class="ib-myhr-field">
								<label>Leave Type *</label>
								<select class="form-control" id="ib-myhr-lt">${opts}</select>
							</div>
							<div class="ib-myhr-field"></div>
							<div class="ib-myhr-field">
								<label>From Date *</label>
								<input type="date" class="form-control" id="ib-myhr-from" value="${today}" min="${today}">
							</div>
							<div class="ib-myhr-field">
								<label>To Date *</label>
								<input type="date" class="form-control" id="ib-myhr-to" value="${today}" min="${today}">
							</div>
							<div class="ib-myhr-field ib-myhr-field-full">
								<label>Reason</label>
								<textarea id="ib-myhr-reason" placeholder="Brief reason for leave…"></textarea>
							</div>
							<div class="ib-myhr-field ib-myhr-field-full">
								<label style="margin-bottom:6px;"></label>
								<div class="ib-myhr-half-row">
									<input type="checkbox" id="ib-myhr-halfd" style="width:auto;">
									<label for="ib-myhr-halfd" style="margin:0;font-size:13px;font-weight:400;text-transform:none;letter-spacing:0;color:var(--text-color);">Half day</label>
								</div>
							</div>
						</div>
						<div class="ib-myhr-apply-actions" style="margin-top:14px;">
							<button class="ib-myhr-btn-primary btn btn-primary btn-sm" id="ib-myhr-submit">Submit Application</button>
							<button class="ib-myhr-btn-secondary btn btn-default btn-sm" id="ib-myhr-clear">Clear</button>
						</div>
						<p style="font-size:11px;color:var(--text-muted);margin-top:10px;">
							Leave is subject to manager approval. You will receive a notification when approved or rejected.
						</p>
					</div>
				`);

				$c.find("#ib-myhr-from").on("change", function () {
					const fd = $(this).val();
					const td = $c.find("#ib-myhr-to").val();
					if (td < fd) $c.find("#ib-myhr-to").val(fd);
					$c.find("#ib-myhr-to").attr("min", fd);
				});

				$c.find("#ib-myhr-clear").on("click", () => {
					$c.find("#ib-myhr-from").val(today);
					$c.find("#ib-myhr-to").val(today);
					$c.find("#ib-myhr-reason").val("");
					$c.find("#ib-myhr-halfd").prop("checked", false);
				});

				$c.find("#ib-myhr-submit").on("click", () => {
					const lt    = $c.find("#ib-myhr-lt").val();
					const from  = $c.find("#ib-myhr-from").val();
					const to    = $c.find("#ib-myhr-to").val();
					const reason= $c.find("#ib-myhr-reason").val();
					const half  = $c.find("#ib-myhr-halfd").is(":checked") ? 1 : 0;

					if (!lt)   return frappe.show_alert({ message: "Select a leave type", indicator: "red" });
					if (!from) return frappe.show_alert({ message: "Select From Date", indicator: "red" });
					if (!to)   return frappe.show_alert({ message: "Select To Date", indicator: "red" });

					const $btn = $c.find("#ib-myhr-submit");
					$btn.prop("disabled", true).text("Submitting…");

					frappe.call({
						method: "instabiz.instabiz.page.ib_my_hr.ib_my_hr.apply_leave",
						args: { leave_type: lt, from_date: from, to_date: to, reason, half_day: half, half_day_date: half ? from : null },
						callback: (r) => {
							$btn.prop("disabled", false).text("Submit Application");
							frappe.show_alert({ message: `Leave submitted: ${r.message?.name}`, indicator: "green" });
							// Switch to Leaves tab
							this.$wrap.find('.ib-myhr-tab[data-tab="leaves"]').trigger("click");
							this.refresh();
						},
						error: () => {
							$btn.prop("disabled", false).text("Submit Application");
							frappe.show_alert({ message: "Submission failed — check error log", indicator: "red" });
						},
					});
				});
			},
			error: () => $c.html(`<div class="ib-myhr-empty">Could not load leave types.</div>`),
		});
	}

	// ── Tab: Attendance ───────────────────────────────────────────────────────

	_render_attendance($c) {
		const att = this._data.attendance || [];
		const today = frappe.datetime.get_today();
		const month_date = frappe.datetime.str_to_obj(this._month);
		const year = month_date.getFullYear();
		const month = month_date.getMonth(); // 0-indexed
		const firstDay = new Date(year, month, 1).getDay(); // 0=Sun
		const daysInMonth = new Date(year, month + 1, 0).getDate();

		// Map date → status
		const attMap = {};
		att.forEach(a => {
			attMap[String(a.attendance_date)] = a.status;
		});

		const statusClass = {
			"Present":       "present",
			"Work From Home":"present",
			"Absent":        "absent",
			"On Leave":      "leave",
			"Half Day":      "half",
		};
		const statusLabel = { "Present":"P", "Work From Home":"WFH", "Absent":"A", "On Leave":"L", "Half Day":"½" };

		const DOW = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
		const headers = DOW.map(d => `<div class="ib-myhr-att-cell ib-myhr-att-cell--hdr">${d}</div>`).join("");

		// Leading empty cells
		let cells = "";
		for (let i = 0; i < firstDay; i++) cells += `<div class="ib-myhr-att-cell ib-myhr-att-cell--empty"></div>`;

		for (let d = 1; d <= daysInMonth; d++) {
			const dateStr = `${year}-${String(month + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
			const dow = new Date(year, month, d).getDay();
			const isWeekend = dow === 0 || dow === 6;
			const isFuture = dateStr > today;
			const status = attMap[dateStr];
			const cls = isFuture ? "future" : isWeekend && !status ? "weekend" : statusClass[status] || (isWeekend ? "weekend" : "");
			const lbl = statusLabel[status] || d;
			cells += `<div class="ib-myhr-att-cell ib-myhr-att-cell--${cls}" title="${dateStr}${status ? " — " + status : ""}">
				<span style="font-size:9px;opacity:.6">${d}</span>
				<span>${typeof lbl === "number" ? "" : lbl}</span>
			</div>`;
		}

		$c.html(`
			<h4 style="font-size:13px;font-weight:700;margin:0 0 10px;">Attendance — ${month_date.toLocaleDateString("en-IN",{month:"long",year:"numeric"})}</h4>
			<div class="ib-myhr-att-grid">${headers}${cells}</div>
			<div class="ib-myhr-att-legend">
				<span><span class="ib-myhr-att-legend-dot" style="background:var(--myhr-green)"></span>Present</span>
				<span><span class="ib-myhr-att-legend-dot" style="background:var(--myhr-red)"></span>Absent</span>
				<span><span class="ib-myhr-att-legend-dot" style="background:var(--myhr-indigo)"></span>On Leave</span>
				<span><span class="ib-myhr-att-legend-dot" style="background:var(--myhr-yellow)"></span>Half Day</span>
				<span><span class="ib-myhr-att-legend-dot" style="background:#d1d5db"></span>Weekend</span>
			</div>
		`);
	}

	// ── Tab: Payslips ─────────────────────────────────────────────────────────

	_render_payslips($c) {
		const slips = this._data.payslips || [];
		const fmt = (v) => "₹" + Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 });

		const gen_btn = `
			<div style="margin-bottom:12px">
				<button class="btn btn-sm btn-default" id="ib-myhr-gen-slip">Generate Salary Slip</button>
			</div>`;

		if (!slips.length) {
			$c.html(`${gen_btn}<div class="ib-myhr-empty">No salary slips available yet.</div>`);
			this._bind_gen_slip($c);
			return;
		}
		const cards = slips.map(s => {
			const monthLabel = s.start_date
				? new Date(s.start_date).toLocaleDateString("en-IN", { month: "long", year: "numeric" })
				: s.name;
			return `
			<div class="ib-myhr-payslip-card">
				<div class="ib-myhr-payslip-month">${frappe.utils.escape_html(monthLabel)}</div>
				<div class="ib-myhr-payslip-row"><span>Gross</span><span>${fmt(s.gross_pay)}</span></div>
				<div class="ib-myhr-payslip-row"><span>Deductions</span><span style="color:var(--myhr-red)">-${fmt(s.total_deduction)}</span></div>
				<div class="ib-myhr-payslip-net">${fmt(s.net_pay)}</div>
				<a href="/app/salary-slip/${encodeURIComponent(s.name)}" target="_blank" class="ib-myhr-payslip-open">
					View Payslip →
				</a>
			</div>`;
		}).join("");
		$c.html(`${gen_btn}<div class="ib-myhr-payslip-list">${cards}</div>`);
		this._bind_gen_slip($c);
	}

	_bind_gen_slip($c) {
		const self = this;
		$c.find("#ib-myhr-gen-slip").on("click", function () {
			// Month picker (2026-08-13) — generate_my_salary_slip already
			// accepted a month param server-side, the button just never sent
			// one (always generated last month only). Offers the last 12
			// completed months — current month is excluded since the
			// backend throws if the month hasn't ended yet.
			const month_map = {};
			const options = [];
			const now = new Date();
			for (let i = 1; i <= 12; i++) {
				const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
				const label = d.toLocaleDateString("en-IN", { month: "long", year: "numeric" });
				const value = frappe.datetime.obj_to_str(d).slice(0, 10);
				options.push(label);
				month_map[label] = value;
			}

			const dialog = new frappe.ui.Dialog({
				title: __("Generate Salary Slip"),
				fields: [
					{
						fieldname: "month",
						fieldtype: "Select",
						label: __("Month"),
						options: options.join("\n"),
						default: options[0],
						reqd: 1,
					},
				],
				primary_action_label: __("Generate"),
				primary_action(values) {
					dialog.get_primary_btn().prop("disabled", true).text(__("Generating…"));
					frappe.call({
						method: "instabiz.instabiz.page.ib_my_hr.ib_my_hr.generate_my_salary_slip",
						args: { month: month_map[values.month] },
						callback(r) {
							const res = r.message || {};
							if (res.status === "exists") {
								frappe.show_alert({ message: __("Slip already generated for {0}", [values.month]), indicator: "orange" });
							} else if (res.status === "created") {
								frappe.show_alert({ message: __("Salary slip generated for {0}", [values.month]), indicator: "green" });
							}
							dialog.hide();
							self.refresh();
						},
						error() {
							dialog.get_primary_btn().prop("disabled", false).text(__("Generate"));
						},
					});
				},
			});
			dialog.show();
		});
	}
}

// helper used in leave table
function flt(v, precision = 0) {
	return parseFloat(v || 0).toFixed(precision).replace(/\.0$/, "");
}
