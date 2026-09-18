// Financial year you are looking at (Tally's "change period"). The navbar
// shows it; choosing another year makes reports open inside that year.
// Server side: instabiz.overrides.financial_year (boot + set_year).
(function () {
	const fy = () => frappe.boot && frappe.boot.ib_fiscal_year;

	// ERPNext's report defaults call erpnext.utils.get_fiscal_year(today).
	// When a past year is chosen, "today" means "the chosen year".
	function patch_fy() {
		if (!window.erpnext || !erpnext.utils || !erpnext.utils.get_fiscal_year || erpnext.utils.__ib_fy) return;
		erpnext.utils.__ib_fy = true;
		const orig = erpnext.utils.get_fiscal_year;
		erpnext.utils.get_fiscal_year = function (date, with_dates = false, boolean = false) {
			const y = fy();
			if (y && !y.is_current && (!date || date === frappe.datetime.get_today())) {
				return with_dates ? [y.name, y.start, y.end] : y.name;
			}
			return orig.call(this, date, with_dates, boolean);
		};
	}
	patch_fy();
	$(document).on("app_ready", patch_fy);

	// Date filters whose default falls outside the chosen year are pulled
	// into it: start-type filters to the year start, the rest to year end.
	const START = /^(from|start|period_start|posting_date_from)/;
	function patch_reports() {
		const QR = frappe.views && frappe.views.QueryReport;
		if (!QR || QR.prototype.__ib_fy) return;
		QR.prototype.__ib_fy = true;
		const orig = QR.prototype.setup_filters;
		QR.prototype.setup_filters = function () {
			const y = fy();
			if (y && !y.is_current && this.report_settings && this.report_settings.filters) {
				this.report_settings.filters.forEach((df) => {
					if (df.fieldtype !== "Date" || !df.default) return;
					let value = typeof df.default === "function" ? df.default() : df.default;
					if (!value || (value >= y.start && value <= y.end)) return;
					df.default = START.test(df.fieldname) ? y.start : y.end;
				});
			}
			return orig.apply(this, arguments);
		};
	}
	patch_reports();
	$(document).on("app_ready", patch_reports);

	function add_navbar_item() {
		const y = fy();
		if (!y || $(".ib-fy-switch").length) return;
		const $item = $(`<li class="nav-item ib-fy-switch">
			<a class="nav-link" href="#" title="${__("Financial year you are viewing")}"
				style="font-size:12px;font-weight:600;padding:4px 10px;border-radius:12px;margin-top:6px;
				${y.is_current ? "" : "background:var(--bg-orange);color:var(--text-on-orange);"}">
				FY ${frappe.utils.escape_html(y.name)}${y.is_current ? "" : " · " + __("past year")}
			</a></li>`);
		$item.on("click", "a", (e) => {
			e.preventDefault();
			frappe.db.get_list("Fiscal Year", { fields: ["name"], filters: { disabled: 0 }, order_by: "year_start_date desc", limit: 20 })
				.then((rows) => {
					frappe.prompt([{ fieldname: "fiscal_year", fieldtype: "Select", label: __("Financial year"),
						options: rows.map((r) => r.name), default: y.name,
						description: __("Reports and date filters open in this year, for you only.") }],
						(v) => frappe.call({ method: "instabiz.overrides.financial_year.set_year", args: v, freeze: true,
							callback: () => window.location.reload() }),
						__("Change financial year"), __("Switch"));
				});
		});
		$(".navbar .navbar-nav").first().prepend($item);
	}
	$(document).on("app_ready page-change", add_navbar_item);
	frappe.router && frappe.router.on && frappe.router.on("change", add_navbar_item);
})();
