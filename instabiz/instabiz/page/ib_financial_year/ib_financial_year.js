// Financial Year: switch the year you are looking at, compare years, create
// the next one, lock the books and close the year (instabiz.overrides.financial_year).
frappe.pages["ib-financial-year"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Financial Year"), single_column: true });
	const M = "instabiz.overrides.financial_year";
	const $body = $(`<div class="ibfy"></div>`).appendTo(page.main);
	$(`<style>
		.ibfy { padding: 12px 0 40px; }
		.ibfy-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(290px, 1fr)); gap: 12px; }
		.ibfy-card { border: 1px solid var(--border-color); border-radius: 10px; background: var(--card-bg); padding: 14px 16px; }
		.ibfy-card.sel { border-color: var(--primary); box-shadow: 0 0 0 1px var(--primary) inset; }
		.ibfy-card h4 { margin: 0 0 2px; font-size: 16px; font-weight: 700; }
		.ibfy-dates { color: var(--text-muted); font-size: 12px; margin-bottom: 10px; }
		.ibfy-kv { display: grid; grid-template-columns: 1fr auto; gap: 3px 10px; font-size: 12.5px; }
		.ibfy-kv span:nth-child(even) { text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; }
		.ibfy-tag { display: inline-block; font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 10px; margin-left: 6px; vertical-align: middle; }
		.ibfy-tag.cur { background: var(--bg-green); color: var(--text-on-green); }
		.ibfy-tag.sel { background: var(--bg-blue); color: var(--text-on-blue); }
		.ibfy-card .btn { margin-top: 12px; }
		.ibfy h5 { margin: 22px 0 10px; font-size: 13px; text-transform: uppercase; letter-spacing: .05em; color: var(--text-muted); }
		.ibfy-check { border: 1px solid var(--border-color); border-radius: 10px; background: var(--card-bg); }
		.ibfy-check div { display: grid; grid-template-columns: 22px 1fr; gap: 8px; padding: 9px 14px; border-top: 1px solid var(--border-color); font-size: 13px; }
		.ibfy-check div:first-child { border-top: 0; }
		.ibfy-check small { display: block; color: var(--text-muted); }
		.ibfy-ok { color: var(--green-600, #2f9e44); font-weight: 700; }
		.ibfy-no { color: var(--red-600, #e03131); font-weight: 700; }
		.ibfy-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
	</style>`).appendTo($body);
	const $content = $(`<div></div>`).appendTo($body);

	const money = (v) => format_currency(v || 0, frappe.defaults.get_default("currency") || "INR", 0);

	function render(d) {
		const years = d.years
			.map((y) => {
				const t = y.totals;
				return `<div class="ibfy-card ${y.is_selected ? "sel" : ""}">
					<h4>${frappe.utils.escape_html(y.name)}
						${y.is_current ? `<span class="ibfy-tag cur">${__("Current")}</span>` : ""}
						${y.is_selected ? `<span class="ibfy-tag sel">${__("Viewing")}</span>` : ""}</h4>
					<div class="ibfy-dates">${frappe.datetime.str_to_user(y.year_start_date)} – ${frappe.datetime.str_to_user(y.year_end_date)}</div>
					<div class="ibfy-kv">
						<span>${__("Income")}</span><span>${money(t.income)}</span>
						<span>${__("Expenses")}</span><span>${money(t.expense)}</span>
						<span>${__("Profit / loss")}</span><span>${money(t.profit)}</span>
						<span>${__("Orders")}</span><span>${t.orders} · ${money(t.order_value)}</span>
						<span>${__("Purchases")}</span><span>${money(t.purchases)}</span>
						<span>${__("Receipts")}</span><span>${money(t.receipts)}</span>
						<span>${__("Vouchers")}</span><span>${t.vouchers}</span>
					</div>
					${y.is_selected ? "" : `<button class="btn btn-sm btn-default" data-year="${frappe.utils.escape_html(y.name)}">${__("View this year")}</button>`}
				</div>`;
			})
			.join("");
		const checks = d.checklist
			.map((c) => `<div><span class="${c.ok ? "ibfy-ok" : "ibfy-no"}">${c.ok ? "✓" : "✕"}</span>
				<span>${frappe.utils.escape_html(c.label)}<small>${frappe.utils.escape_html(c.detail || "")}</small></span></div>`)
			.join("");
		const manage = d.can_manage
			? `<h5>${__("Manage")}</h5><div class="ibfy-actions">
				<button class="btn btn-sm btn-default" data-act="next">${__("Create next financial year")}</button>
				<button class="btn btn-sm btn-default" data-act="lock">${__("Lock books up to a date")}</button>
				<button class="btn btn-sm btn-default" data-act="close">${__("Year-end closing voucher")}</button>
				<span class="text-muted small">${__("Books locked till")}: <b>${d.frozen_upto ? frappe.datetime.str_to_user(d.frozen_upto) : __("not locked")}</b></span>
			</div>`
			: "";
		$content.html(`
			<p class="text-muted">${__("Pick the year you want to look at. Reports and date filters open inside that year for you only; posting dates are not affected.")}</p>
			<div class="ibfy-grid">${years}</div>
			<h5>${__("Year-end checklist")} · ${frappe.utils.escape_html(d.selected || "")}</h5>
			<div class="ibfy-check">${checks}</div>
			${manage}`);
		$content.find("[data-year]").on("click", (e) => switch_year($(e.currentTarget).data("year")));
		$content.find("[data-act=next]").on("click", () =>
			frappe.confirm(__("Create the next financial year?"), () =>
				frappe.call({ method: `${M}.create_next_year`, callback: (r) => { frappe.show_alert(__("Created {0}", [r.message])); load(); } })));
		$content.find("[data-act=lock]").on("click", () =>
			frappe.prompt([{ fieldname: "upto", fieldtype: "Date", label: __("Lock all entries up to"), default: d.frozen_upto,
				description: __("Only Accounts Managers can post or change entries on or before this date. Leave blank to unlock.") }],
				(v) => frappe.call({ method: `${M}.lock_books`, args: { upto: v.upto }, callback: () => load() }),
				__("Lock books"), __("Save")));
		$content.find("[data-act=close]").on("click", () => {
			const y = d.years.find((x) => x.is_selected);
			frappe.new_doc("Period Closing Voucher", { company: d.company, fiscal_year: y.name,
				posting_date: y.year_end_date, period_start_date: y.year_start_date, period_end_date: y.year_end_date,
				transaction_date: frappe.datetime.get_today(), remarks: __("Year-end closing for {0}", [y.name]) });
		});
	}

	function switch_year(name) {
		frappe.call({ method: `${M}.set_year`, args: { fiscal_year: name }, freeze: true,
			callback: () => { frappe.show_alert(__("Now viewing {0}", [name])); setTimeout(() => window.location.reload(), 400); } });
	}

	function load() {
		frappe.call({ method: `${M}.get_overview`, callback: (r) => r.message && render(r.message) });
	}
	page.set_primary_action(__("Refresh"), load, "refresh");
	load();
};
