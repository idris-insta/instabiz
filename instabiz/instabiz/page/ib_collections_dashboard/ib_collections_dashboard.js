frappe.pages["ib-collections-dashboard"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({ parent: wrapper, title: "Collections", single_column: true });
	wrapper._ib_col = new IBCollectionsDashboard(wrapper);
};

frappe.pages["ib-collections-dashboard"].on_page_show = function (wrapper) {
	if (wrapper._ib_col) wrapper._ib_col.load();
};

class IBCollectionsDashboard {
	constructor(wrapper) {
		this.$wrap = $(wrapper).find(".layout-main-section");
		this._search = "";
		this._filter_sp = null;
		this._location = "";
		this._overdue_only = false;
		this._min_days_overdue = 0;
		this._min_outstanding = 0;
		this._invoices = [];
		this._privileged = false;
		this._sp_loaded = false;
		this._loading = false;
		this._offset = 0;
		this._page_size = 50;
		this._customer_total = 0;
		this._inject_styles();
		this._build_layout();
		// load() started by on_page_show — no double call on first visit
	}

	_inject_styles() {
		if (document.getElementById("ib-col-css")) return;
		const s = document.createElement("style");
		s.id = "ib-col-css";
		s.textContent = `
:root { --ib-p:#d97757; }
.ib-col-wrap { padding:16px; max-width:1400px; }
.ib-col-toolbar { display:flex; align-items:center; gap:10px; margin-bottom:16px; flex-wrap:wrap; }
.ib-col-toolbar h2 { font-size:1.2rem; font-weight:700; color:var(--heading-color); margin:0; flex:1; }
.ib-col-input { padding:6px 12px; border:1px solid var(--border-color); border-radius:6px;
  font-size:12px; background:var(--card-bg,#fff); color:var(--text-color); min-width:200px; }
.ib-col-input:focus { outline:none; border-color:var(--ib-p); }
.ib-col-btn { padding:6px 14px; border:1px solid var(--border-color); border-radius:6px;
  background:var(--card-bg,#fff); color:var(--text-color); cursor:pointer; font-size:12px; transition:all .15s; }
.ib-col-btn:hover { border-color:var(--ib-p); color:var(--ib-p); }
.ib-col-btn.active { background:var(--ib-p); color:#fff; border-color:var(--ib-p); }
.ib-col-kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-bottom:16px; }
.ib-col-kpi { background:var(--card-bg,#fff); border:1px solid var(--border-color); border-radius:8px;
  padding:14px 16px; position:relative; overflow:hidden; }
.ib-col-kpi-bar { position:absolute; left:0; top:0; bottom:0; width:4px; border-radius:8px 0 0 8px; }
.ib-col-kpi-l { font-size:10px; color:var(--text-muted); text-transform:uppercase; letter-spacing:.06em; }
.ib-col-kpi-v { font-size:1.3rem; font-weight:700; color:var(--heading-color); margin-top:4px; }
.ib-col-tbl-wrap { background:var(--card-bg,#fff); border:1px solid var(--border-color); border-radius:10px; overflow:auto; }
.ib-col-tbl { width:100%; border-collapse:collapse; font-size:12px; min-width:900px; }
.ib-col-tbl th { text-align:left; padding:10px 12px; color:var(--text-muted); font-weight:500;
  border-bottom:2px solid var(--border-color); position:sticky; top:0; background:var(--card-bg,#fff); z-index:1; }
.ib-col-tbl td { padding:10px 12px; border-bottom:1px solid var(--border-color); vertical-align:middle; }
.ib-col-tbl tr:last-child td { border-bottom:none; }
.ib-col-tbl tbody tr.ib-col-data-row:hover td { background:var(--control-bg,#f8fafc); }
.ib-col-badge { display:inline-block; padding:2px 8px; border-radius:99px; font-size:10px; font-weight:600; }
.ib-col-badge.red { background:#fee2e2; color:#dc2626; }
.ib-col-badge.amber { background:#fef3c7; color:#d97706; }
.ib-col-badge.green { background:#d1fae5; color:#059669; }
.ib-col-badge.blue { background:#dbeafe; color:#1d4ed8; }
.ib-col-expand-btn { background:none; border:none; cursor:pointer; color:var(--text-muted); font-size:14px; padding:0 4px; }
.ib-col-inv-row { background:var(--control-bg,#f8fafc); }
.ib-col-inv-row td { padding:6px 12px; font-size:11px; color:var(--text-muted); border-bottom:1px solid var(--border-color); }
.ib-col-inv-inner { display:flex; gap:12px; align-items:center; flex-wrap:wrap; padding:4px 0; }
.ib-col-pay-btn { padding:4px 10px; border:1px solid var(--ib-p); border-radius:5px;
  color:var(--ib-p); background:none; cursor:pointer; font-size:11px; font-weight:600;
  transition:all .15s; white-space:nowrap; }
.ib-col-pay-btn:hover { background:var(--ib-p); color:#fff; }
.ib-col-advance-tag { display:inline-block; padding:2px 7px; border-radius:99px;
  font-size:10px; font-weight:600; background:#dbeafe; color:#1d4ed8; }
.ib-col-loading { display:flex; align-items:center; justify-content:center; padding:32px;
  color:var(--text-muted); font-size:13px; gap:8px; }
.ib-col-spinner { width:16px; height:16px; border:2px solid var(--border-color);
  border-top-color:var(--ib-p); border-radius:50%; animation:ib-spin .6s linear infinite; }
@keyframes ib-spin { to { transform:rotate(360deg); } }
.ib-col-filters { display:flex; align-items:center; gap:10px; margin-bottom:12px; flex-wrap:wrap; }
.ib-col-filters .ib-col-input { min-width:140px; }
.ib-col-filter-label { font-size:11px; color:var(--text-muted); white-space:nowrap; }
.ib-col-clear-btn { color:var(--text-muted); }
.ib-col-clear-btn:hover { color:#dc2626; border-color:#dc2626; }
`;
		document.head.appendChild(s);
	}

	_build_layout() {
		this.$wrap.html(`
		<div class="ib-col-wrap">
			<div class="ib-col-toolbar">
				<h2>Collections Dashboard</h2>
				<input class="ib-col-input form-control" id="ib-col-search" placeholder="Search customer…" />
				<select class="ib-col-input form-control" id="ib-col-sp" style="min-width:160px;display:none">
					<option value="">All Reps</option>
				</select>
				<button class="ib-col-btn btn btn-default btn-sm" id="ib-col-overdue">Overdue Only</button>
				<button class="ib-col-btn btn btn-default btn-sm" id="ib-col-refresh">↻ Refresh</button>
				<button class="ib-col-btn btn btn-default btn-sm" id="ib-col-si">Outstanding SIs</button>
			</div>
			<div class="ib-col-filters">
				<span class="ib-col-filter-label">Location</span>
				<select class="ib-col-input form-control" id="ib-col-location" style="min-width:130px">
					<option value="">All locations</option>
					<option value="MAHARASHTRA">MAHARASHTRA</option>
					<option value="GUJARAT">GUJARAT</option>
					<option value="CHENNAI">CHENNAI</option>
				</select>
				<span class="ib-col-filter-label">Min days overdue</span>
				<input type="number" min="0" class="ib-col-input form-control" id="ib-col-min-overdue"
					placeholder="e.g. 30" style="min-width:100px" />
				<span class="ib-col-filter-label">Min outstanding ₹</span>
				<input type="number" min="0" class="ib-col-input form-control" id="ib-col-min-outstanding"
					placeholder="e.g. 100000" style="min-width:140px" />
				<button class="ib-col-btn btn btn-default btn-sm ib-col-clear-btn" id="ib-col-clear">Clear Filters</button>
			</div>
			<div id="ib-col-kpis" class="ib-col-kpis"></div>
			<div class="ib-col-tbl-wrap">
				<table class="ib-col-tbl">
					<thead><tr>
						<th style="width:32px"></th>
						<th>Customer</th>
						<th id="ib-col-th-sp" style="display:none">Rep</th>
						<th style="text-align:right">Outstanding</th>
						<th style="text-align:right">Advance</th>
						<th style="text-align:right">Net Due</th>
						<th>Earliest Due</th>
						<th>Status</th>
						<th>Invoices</th>
						<th>Action</th>
					</tr></thead>
					<tbody id="ib-col-body">
						<tr><td colspan="9"><div class="ib-col-loading"><div class="ib-col-spinner"></div>Loading…</div></td></tr>
					</tbody>
				</table>
			</div>
			<div id="ib-col-pagination" style="display:flex;align-items:center;gap:10px;justify-content:flex-end;margin-top:10px"></div>
		</div>`);

		let _search_t;
		this.$wrap.find("#ib-col-search").on("input", (e) => {
			clearTimeout(_search_t);
			_search_t = setTimeout(() => { this._search = e.target.value.trim(); this._offset = 0; this.load(); }, 350);
		});
		this.$wrap.find("#ib-col-sp").on("change", (e) => {
			this._filter_sp = e.target.value || null;
			this._offset = 0;
			this.load();
		});
		this.$wrap.find("#ib-col-location").on("change", (e) => {
			this._location = e.target.value || "";
			this._offset = 0;
			this.load();
		});
		this.$wrap.find("#ib-col-overdue").on("click", () => {
			this._overdue_only = !this._overdue_only;
			this.$wrap.find("#ib-col-overdue").toggleClass("active", this._overdue_only);
			this._offset = 0;
			this.load();
		});
		this.$wrap.find("#ib-col-refresh").on("click", () => this.load());
		this.$wrap.find("#ib-col-si").on("click", () => {
			// Sales Order (dev billing mode) has no outstanding_amount column —
			// a filter built for Sales Invoice's own field breaks the list view
			// on that doctype.
			const filters = this._dev_mode ? { docstatus: 1 } : { outstanding_amount: [">", 0], docstatus: 1 };
			frappe.set_route("List", this._doctype || "Sales Invoice", filters);
		});

		let _min_od_t;
		this.$wrap.find("#ib-col-min-overdue").on("input", (e) => {
			clearTimeout(_min_od_t);
			_min_od_t = setTimeout(() => {
				this._min_days_overdue = cint(e.target.value) || 0;
				this._offset = 0;
				this.load();
			}, 350);
		});
		let _min_out_t;
		this.$wrap.find("#ib-col-min-outstanding").on("input", (e) => {
			clearTimeout(_min_out_t);
			_min_out_t = setTimeout(() => {
				this._min_outstanding = flt(e.target.value) || 0;
				this._offset = 0;
				this.load();
			}, 350);
		});
		this.$wrap.find("#ib-col-clear").on("click", () => {
			this._search = ""; this._filter_sp = null; this._overdue_only = false; this._location = "";
			this._min_days_overdue = 0; this._min_outstanding = 0; this._offset = 0;
			this.$wrap.find("#ib-col-search").val("");
			this.$wrap.find("#ib-col-sp").val("");
			this.$wrap.find("#ib-col-location").val("");
			this.$wrap.find("#ib-col-min-overdue").val("");
			this.$wrap.find("#ib-col-min-outstanding").val("");
			this.$wrap.find("#ib-col-overdue").removeClass("active");
			this.load();
		});
	}

	_cols() { return this._privileged ? 10 : 9; }

	load() {
		if (this._loading) return;
		this._loading = true;
		this.$wrap.find("#ib-col-body").html(
			`<tr><td colspan="${this._cols()}"><div class="ib-col-loading"><div class="ib-col-spinner"></div>Loading…</div></td></tr>`
		);
		frappe.call({
			method: "instabiz.instabiz.page.ib_collections_dashboard.ib_collections_dashboard.get_collections_data",
			args: {
				search: this._search || null,
				filter_sp: this._filter_sp,
				location: this._location,
				overdue_only: this._overdue_only ? 1 : 0,
				min_days_overdue: this._min_days_overdue || 0,
				min_outstanding: this._min_outstanding || 0,
				offset: this._offset,
				limit: this._page_size,
			},
			callback: (r) => {
				this._loading = false;
				if (!r.message) return;
				const d = r.message;
				this._doctype = d.doctype;
				this._dev_mode = d.dev_mode;
				this._invoices = d.invoices || [];
				this._privileged = d.privileged;
				this._customer_total = d.customer_total || 0;
				this._render_kpis(d.kpis);
				this._render_table(d.customers || []);
				if (d.privileged && !this._sp_loaded) {
					this._sp_loaded = true;
					this._setup_sp_filter();
				}
			},
			error: () => {
				this._loading = false;
				this.$wrap.find("#ib-col-body").html(
					`<tr><td colspan="${this._cols()}" style="text-align:center;color:#dc2626;padding:24px">Failed to load data</td></tr>`
				);
			}
		});
	}

	_setup_sp_filter() {
		frappe.call({
			method: "instabiz.instabiz.page.ib_collections_dashboard.ib_collections_dashboard.get_sales_users",
			callback: (r) => {
				if (!r.message) return;
				const $sel = this.$wrap.find("#ib-col-sp");
				$sel.find("option:not(:first)").remove();
				r.message.forEach(u => {
					$sel.append(`<option value="${frappe.utils.escape_html(u.user)}">${frappe.utils.escape_html(u.full_name || u.user)}</option>`);
				});
				if (this._filter_sp) $sel.val(this._filter_sp);
				$sel.show();
				this.$wrap.find("#ib-col-th-sp").show();
			}
		});
	}

	_fmt(v) {
		return "₹" + Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 });
	}

	// KPI-card version of _fmt — crore/lakh scale ("₹13.55 Cr") with the
	// exact amount as a hover title, same fix as Customer Health/ib_ui.js's
	// compact money mode. Table/row amounts elsewhere on this page keep
	// _fmt's full precision — only these 4 top KPI cards are narrow enough
	// to overflow on a real crore-scale customer base.
	_fmtC(v) {
		return `<span title="${this._fmt(v)}">${window.ib_fmt_inr_compact ? window.ib_fmt_inr_compact(v) : this._fmt(v)}</span>`;
	}

	_render_kpis(k) {
		this.$wrap.find("#ib-col-kpis").html(`
			<div class="ib-col-kpi">
				<div class="ib-col-kpi-bar" style="background:#ef4444"></div>
				<div class="ib-col-kpi-l">Total Outstanding</div>
				<div class="ib-col-kpi-v" style="color:#dc2626">${this._fmtC(k.total_outstanding)}</div>
			</div>
			<div class="ib-col-kpi">
				<div class="ib-col-kpi-bar" style="background:#1d4ed8"></div>
				<div class="ib-col-kpi-l">Advance Available</div>
				<div class="ib-col-kpi-v" style="color:#1d4ed8">${this._fmtC(k.total_advance)}</div>
			</div>
			<div class="ib-col-kpi">
				<div class="ib-col-kpi-bar" style="background:#d97757"></div>
				<div class="ib-col-kpi-l">Net Due</div>
				<div class="ib-col-kpi-v">${this._fmtC(k.net_outstanding)}</div>
			</div>
			<div class="ib-col-kpi">
				<div class="ib-col-kpi-bar" style="background:#f59e0b"></div>
				<div class="ib-col-kpi-l">Overdue Customers</div>
				<div class="ib-col-kpi-v" style="color:${k.overdue_count > 0 ? "#d97706" : "inherit"}">${k.overdue_count} / ${k.customer_count}</div>
			</div>
			<div class="ib-col-kpi">
				<div class="ib-col-kpi-bar" style="background:#10b981"></div>
				<div class="ib-col-kpi-l">Collected (90d)</div>
				<div class="ib-col-kpi-v" style="color:#059669">${this._fmtC(k.collected_90d)}</div>
			</div>
		`);
	}

	_render_table(customers) {
		const cols = this._cols();
		if (!customers.length) {
			const has_filters = this._search || this._filter_sp || this._location || this._overdue_only
				|| this._min_days_overdue || this._min_outstanding;
			const msg = has_filters
				? "No customers match the current filters — try Clear Filters"
				: "No outstanding customers";
			this.$wrap.find("#ib-col-body").html(
				`<tr><td colspan="${cols}" style="text-align:center;color:var(--text-muted);padding:32px">${msg}</td></tr>`
			);
			return;
		}

		const rows = customers.map((c, idx) => {
			const overdue_days = Math.max(0, Number(c.days_overdue || 0));
			const overdue = overdue_days > 0;
			const status_cls = overdue ? (overdue_days > 30 ? "red" : "amber") : "green";
			const status_lbl = overdue ? `${overdue_days}d overdue` : "Current";
			const inv_list = this._invoices.filter(i => i.customer === c.customer);
			const sp_cell = this._privileged
				? `<td>${frappe.utils.escape_html(c.sp_name || c.sp_user || "—")}</td>` : "";

			const inv_chips = inv_list.map(inv => {
				const od = Math.max(0, Number(inv.days_overdue || 0));
				const cls = od > 30 ? "red" : od > 0 ? "amber" : "green";
				return `<span class="ib-col-inv-chip"
					data-inv="${frappe.utils.escape_html(inv.name)}"
					style="display:inline-flex;align-items:center;gap:6px;padding:4px 8px;
					background:var(--card-bg,#fff);border:1px solid var(--border-color);
					border-radius:6px;cursor:pointer;">
					<span class="ib-col-inv-link" style="color:var(--ib-p);font-size:11px">${frappe.utils.escape_html(inv.name)}</span>
					<span class="ib-col-badge ${cls}" style="font-size:9px">${this._fmt(inv.outstanding_amount)}</span>
					${od > 0 ? `<span style="font-size:9px;color:#dc2626">+${od}d</span>` : ""}
				</span>`;
			}).join("");

			return `
			<tr class="ib-col-data-row" data-customer="${frappe.utils.escape_html(c.customer)}">
				<td><button class="ib-col-expand-btn" data-idx="${idx}" title="Show invoices">▶</button></td>
				<td style="font-weight:600">
					<span class="ib-col-cust-link" data-customer="${frappe.utils.escape_html(c.customer)}"
						style="color:var(--ib-p);cursor:pointer">
						${frappe.utils.escape_html(c.customer_name || c.customer)}
					</span>
					${c.advance > 0 ? `<span class="ib-col-advance-tag" style="margin-left:6px">Adv: ${this._fmt(c.advance)}</span>` : ""}
				</td>
				${sp_cell}
				<td style="text-align:right;font-weight:700;color:#dc2626">${this._fmt(c.outstanding)}</td>
				<td style="text-align:right;color:#1d4ed8">${c.advance > 0 ? this._fmt(c.advance) : "—"}</td>
				<td style="text-align:right;font-weight:600">${this._fmt(c.net_outstanding)}</td>
				<td>${c.earliest_due ? frappe.datetime.str_to_user(c.earliest_due) : "—"}</td>
				<td><span class="ib-col-badge ${status_cls}">${status_lbl}</span></td>
				<td style="color:var(--text-muted)">${c.invoice_count}</td>
				<td>
					<button class="ib-col-pay-btn btn btn-xs btn-default"
						data-customer="${frappe.utils.escape_html(c.customer)}"
						data-cname="${frappe.utils.escape_html(c.customer_name || c.customer)}">
						Log Payment
					</button>
				</td>
			</tr>
			<tr class="ib-col-inv-row" id="ib-col-inv-${idx}" style="display:none">
				<td colspan="${cols}">
					<div class="ib-col-inv-inner">
						${inv_chips || '<span style="color:var(--text-muted);font-size:11px">No outstanding invoices loaded</span>'}
					</div>
				</td>
			</tr>`;
		}).join("");

		this.$wrap.find("#ib-col-body").html(rows);
		this._bind_table_events();
		this._render_pagination();
	}

	_render_pagination() {
		const total = this._customer_total;
		const $p = this.$wrap.find("#ib-col-pagination");
		if (total <= this._page_size) { $p.html(""); return; }
		const from = this._offset + 1;
		const to = Math.min(total, this._offset + this._page_size);
		$p.html(`
			<span style="font-size:11px;color:var(--text-muted)">${from}–${to} of ${total} customers</span>
			<button class="ib-col-btn btn btn-default btn-sm" id="ib-col-prev" ${this._offset === 0 ? "disabled" : ""}>&larr; Prev</button>
			<button class="ib-col-btn btn btn-default btn-sm" id="ib-col-next" ${to >= total ? "disabled" : ""}>Next &rarr;</button>
		`);
		$p.find("#ib-col-prev").on("click", () => {
			this._offset = Math.max(0, this._offset - this._page_size);
			this.load();
		});
		$p.find("#ib-col-next").on("click", () => {
			this._offset += this._page_size;
			this.load();
		});
	}

	_bind_table_events() {
		// Expand/collapse invoice row
		this.$wrap.find(".ib-col-expand-btn").on("click", function () {
			const idx = $(this).data("idx");
			const $inv = $(`#ib-col-inv-${idx}`);
			const open = $inv.is(":visible");
			$inv.toggle(!open);
			$(this).text(open ? "▶" : "▼");
		});

		// Customer link → Customer form
		this.$wrap.find(".ib-col-cust-link").on("click", function () {
			frappe.set_route("Form", "Customer", $(this).data("customer"));
		});

		// Invoice chip → SI (or SO, in dev billing mode) form
		const inv_doctype = this._doctype || "Sales Invoice";
		this.$wrap.find(".ib-col-inv-chip").on("click", function () {
			frappe.set_route("Form", inv_doctype, $(this).data("inv"));
		});

		// Log Payment button
		const self = this;
		this.$wrap.find(".ib-col-pay-btn").on("click", function () {
			self._show_payment_dialog($(this).data("customer"), $(this).data("cname"));
		});
	}

	_show_payment_dialog(customer, customer_name) {
		const doctype = this._doctype || "Sales Invoice";
		const inv_list = this._invoices.filter(i => i.customer === customer);
		const fields = [
			{ fieldtype: "Currency", fieldname: "amount", label: "Amount Received", reqd: 1 },
			{ fieldtype: "Date", fieldname: "posting_date", label: "Date", default: frappe.datetime.get_today(), reqd: 1 },
			{ fieldtype: "Link", fieldname: "mode_of_payment", label: "Mode of Payment", options: "Mode of Payment", reqd: 1 },
			{ fieldtype: "Data", fieldname: "reference_no", label: "Cheque / Reference No" },
		];

		if (inv_list.length) {
			fields.push({
				fieldtype: "Select",
				fieldname: "against_invoice",
				label: "Against Invoice (optional — leave blank to auto-allocate)",
				options: [""].concat(inv_list.map(i => `${i.name} (₹${Number(i.outstanding_amount).toLocaleString("en-IN", { maximumFractionDigits: 0 })})`)).join("\n"),
			});
		}

		const d = new frappe.ui.Dialog({
			title: `Log Payment — ${frappe.utils.escape_html(customer_name)}`,
			fields,
			primary_action_label: "Open Payment Entry",
			primary_action(vals) {
				// Extract just the invoice name (before the space) if selected
				const inv_raw = (vals.against_invoice || "").trim();
				const against_invoice = inv_raw ? inv_raw.split(" ")[0] : null;

				frappe.route_options = {
					payment_type: "Receive",
					party_type: "Customer",
					party: customer,
					posting_date: vals.posting_date,
					paid_amount: vals.amount,
					received_amount: vals.amount,
					reference_no: vals.reference_no || "",
					mode_of_payment: vals.mode_of_payment,
				};
				if (against_invoice) {
					frappe.route_options["references"] = JSON.stringify([{
						reference_doctype: doctype,
						reference_name: against_invoice,
					}]);
				}
				d.hide();
				frappe.new_doc("Payment Entry");
			}
		});
		d.show();
	}
}
