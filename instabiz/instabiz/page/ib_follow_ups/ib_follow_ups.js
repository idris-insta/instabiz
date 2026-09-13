frappe.pages["ib-follow-ups"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Follow-Ups"),
		single_column: true,
	});

	const page = new IBFollowUpsPage(wrapper);
	wrapper.ib_follow_ups = page;
};

frappe.pages["ib-follow-ups"].on_page_show = function (wrapper) {
	if (wrapper.ib_follow_ups) {
		wrapper.ib_follow_ups.refresh();
	}
};

const IB_FU_DOCTYPES = [
	"Quotation", "Sales Order", "Delivery Note", "Sales Invoice",
	"Purchase Order", "Purchase Receipt", "Purchase Invoice",
	"Leave Application", "IB Overtime Request", "IB Full Final Settlement", "Employee Exit Handover",
];

const IB_FU_STATUS_LABEL = { Never: "Pending", Overdue: "Overdue", "Followed Up": "Followed Up" };
const IB_FU_STATUS_CLS = { Never: "pending", Overdue: "risk", "Followed Up": "done" };
const IB_FU_STATE_KEY = "ib_follow_ups_state";
const IB_FU_AMOUNT_FIELDS = ["grand_total"];
const IB_FU_HIDDEN_FIELDS = ["name", "modified", "follow_up_status", "last_follow_up", "next_follow_up_date", "days_overdue", "contact_mobile"];
const IB_FU_PAGE_SIZE = 10;

class IBFollowUpsPage {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.page = wrapper.page;
		const saved = this._load_state();
		this._doctype = saved.doctype || IB_FU_DOCTYPES[0];
		this._search = "";
		this._status_filter = "all";
		this._page = 0;
		this._docs = [];
		this._build();
		this.refresh();
	}

	_load_state() {
		try {
			return JSON.parse(localStorage.getItem(IB_FU_STATE_KEY)) || {};
		} catch (e) {
			return {};
		}
	}

	_save_state() {
		localStorage.setItem(IB_FU_STATE_KEY, JSON.stringify({ doctype: this._doctype }));
	}

	_build() {
		const $body = $(`
			<div class="ib-fu-page">
				<div class="ib-fu-summary"></div>
				<div class="ib-fu-card ib-fu-doctype-row">
					<div class="ib-fu-doctype-field"></div>
					<span class="ib-fu-refresh-time"></span>
				</div>
				<div class="ib-fu-card ib-fu-table-card">
					<div class="ib-fu-toolbar">
						<input type="text" class="ib-fu-search" id="ib-fu-search" placeholder="${__("Search…")}">
						<div class="ib-fu-filter" data-filter="all">${__("All")}</div>
						<div class="ib-fu-filter" data-filter="Never">${__("Pending")}</div>
						<div class="ib-fu-filter" data-filter="Overdue">${__("Overdue")}</div>
						<div class="ib-fu-filter" data-filter="Followed Up">${__("Followed Up")}</div>
						<span class="ib-fu-count" id="ib-fu-count"></span>
					</div>
					<div id="ib-fu-body"></div>
					<div class="ib-fu-pager" id="ib-fu-pager"></div>
				</div>
			</div>
		`).appendTo(this.page.main);

		this.$summary = $body.find(".ib-fu-summary");
		this.$body = $body.find("#ib-fu-body");
		this.$search = $body.find("#ib-fu-search");
		this.$count = $body.find("#ib-fu-count");
		this.$pager = $body.find("#ib-fu-pager");
		this.$refresh_time = $body.find(".ib-fu-refresh-time");
		this.$filters = $body.find(".ib-fu-filter");
		this.$filters.filter(`[data-filter="all"]`).addClass("active");

		this.doctype_ctrl = frappe.ui.form.make_control({
			df: {
				fieldtype: "Select", label: __("Document Type"), fieldname: "doctype",
				options: IB_FU_DOCTYPES.join("\n"),
				onchange: () => {
					this._doctype = this.doctype_ctrl.get_value();
					this._status_filter = "all";
					this._page = 0;
					this.$filters.removeClass("active").filter(`[data-filter="all"]`).addClass("active");
					this._save_state();
					this.refresh();
				},
			},
			parent: $body.find(".ib-fu-doctype-field"),
			render_input: true,
		});
		this.doctype_ctrl.set_value(this._doctype);

		this.$search.on("input", () => {
			this._search = this.$search.val();
			this._page = 0;
			this._render_list();
		});
		this.$filters.on("click", (e) => {
			this._status_filter = $(e.currentTarget).data("filter");
			this._page = 0;
			this.$filters.removeClass("active");
			$(e.currentTarget).addClass("active");
			this._render_list();
		});
		this.$pager.on("click", "button", (e) => {
			this._page += e.currentTarget.id === "ib-fu-next" ? 1 : -1;
			this._render_list();
		});

		this._inject_css();
	}

	_inject_css() {
		if (document.getElementById("ib-fu-style")) return;
		$(`<style id="ib-fu-style">
			.ib-fu-page { padding-top: 4px; }
			.ib-fu-card { background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 8px; }
			.ib-fu-summary { display: flex; gap: 12px; margin: 12px 0; flex-wrap: wrap; }
			.ib-fu-kpi { flex: 1; min-width: 140px; padding: 14px 16px; cursor: pointer; transition: border-color .15s; }
			.ib-fu-kpi.active { border-color: var(--ib-primary, var(--primary)); }
			.ib-fu-kpi .ib-fu-kpi-value { font-size: 24px; font-weight: 700; line-height: 1.2; }
			.ib-fu-kpi .ib-fu-kpi-label { font-size: 12px; color: var(--text-muted); margin-top: 2px; }
			.ib-fu-doctype-row { padding: 10px 12px; margin-bottom: 12px; display: flex; align-items: center; gap: 12px; }
			.ib-fu-doctype-field { min-width: 240px; }
			.ib-fu-refresh-time { margin-left: auto; font-size: 11px; color: var(--text-muted); }
			.ib-fu-table-card { padding: 14px 16px; }
			.ib-fu-toolbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; padding-bottom: 12px; border-bottom: 1px solid var(--border-color); }
			.ib-fu-search { flex: 1 1 200px; min-width: 160px; padding: 6px 10px; border-radius: 7px; border: 1px solid var(--border-color); background: var(--control-bg, var(--card-bg)); color: var(--text-color); font-size: 12px; }
			.ib-fu-filter { padding: 6px 12px; border-radius: 20px; font-size: 12px; font-weight: 500; cursor: pointer; border: 1px solid var(--border-color); background: var(--card-bg); color: var(--text-muted); transition: all .15s; white-space: nowrap; }
			.ib-fu-filter:hover { border-color: var(--ib-primary, var(--primary)); color: var(--heading-color); }
			.ib-fu-filter.active { background: var(--ib-primary, var(--primary)); border-color: var(--ib-primary, var(--primary)); color: #fff; }
			.ib-fu-count { font-size: 11px; color: var(--text-muted); margin-left: auto; white-space: nowrap; }
			.ib-fu-table { width: 100%; border-collapse: collapse; font-size: 12px; }
			.ib-fu-table th { text-align: left; padding: 8px 10px; font-size: 10px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: .5px; border-bottom: 2px solid var(--border-color); }
			.ib-fu-table td { padding: 8px 10px; border-bottom: 1px solid var(--border-color); color: var(--text-color); vertical-align: top; }
			.ib-fu-table tr:last-child td { border-bottom: none; }
			.ib-fu-table tbody tr:hover td { background: var(--bg-color); }
			.ib-fu-badge { font-size: 10px; font-weight: 600; padding: 2px 8px; border-radius: 20px; white-space: nowrap; }
			.ib-fu-badge.done { background: rgba(22,163,74,.12); color: #16a34a; }
			.ib-fu-badge.pending { background: rgba(217,119,87,.12); color: #d97757; }
			.ib-fu-badge.risk { background: rgba(220,38,38,.12); color: #dc2626; }
			.ib-fu-contact-btns { display: inline-flex; gap: 6px; margin-left: 6px; vertical-align: middle; }
			.ib-fu-contact-btns a { color: var(--text-muted); }
			.ib-fu-contact-btns a:hover { color: var(--ib-primary, var(--primary)); }
			.ib-fu-due-text { font-size: 11px; color: var(--text-muted); display: block; }
			.ib-fu-due-text.overdue { color: #dc2626; font-weight: 600; }
			.ib-fu-empty { padding: 40px 20px; text-align: center; color: var(--text-muted); font-size: 12px; }
			.ib-fu-empty .fa { font-size: 24px; margin-bottom: 8px; opacity: .5; display: block; }
			.ib-fu-pager { display: flex; align-items: center; justify-content: center; gap: 12px; padding-top: 12px; margin-top: 4px; border-top: 1px solid var(--border-color); font-size: 12px; }
			.ib-fu-pager button { padding: 4px 12px; border-radius: 6px; border: 1px solid var(--border-color); background: var(--card-bg); color: var(--text-color); cursor: pointer; font-size: 12px; }
			.ib-fu-pager button:disabled { opacity: .4; cursor: not-allowed; }
			.ib-fu-pager span { color: var(--text-muted); }
			.ib-fu-history { max-height: 220px; overflow-y: auto; border: 1px solid var(--border-color); border-radius: 6px; margin-bottom: 14px; }
			.ib-fu-history-empty { padding: 16px; text-align: center; color: var(--text-muted); font-size: 12px; }
			.ib-fu-history-row { padding: 8px 12px; border-bottom: 1px solid var(--border-color); font-size: 12px; }
			.ib-fu-history-row:last-child { border-bottom: none; }
			.ib-fu-history-top { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
			.ib-fu-history-type { font-weight: 600; }
			.ib-fu-history-when { font-size: 11px; color: var(--text-muted); white-space: nowrap; }
			.ib-fu-history-notes { color: var(--text-muted); margin-top: 2px; }
			.ib-fu-history-next { font-size: 11px; color: var(--text-muted); margin-top: 2px; }
			.ib-fu-history-label { font-size: 11px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: .5px; margin-bottom: 6px; }
		</style>`).appendTo("head");
	}

	refresh() {
		this.$body.html(`<div class="ib-fu-empty">${__("Loading...")}</div>`);
		frappe.call({
			method: "instabiz.overrides.follow_ups.get_my_documents",
			args: { doctype: this._doctype },
			callback: (r) => {
				this._docs = r.message || [];
				this._render_summary();
				this._render_list();
				this.$refresh_time.text(__("Updated {0}", [frappe.datetime.now_time()]));
			},
		});
	}

	_render_summary() {
		const total = this._docs.length;
		const overdue = this._docs.filter((d) => d.follow_up_status === "Overdue").length;
		const pending = this._docs.filter((d) => d.follow_up_status === "Never").length;
		const followed = total - overdue - pending;

		const card = (key, label, value, color) => `
			<div class="ib-fu-card ib-fu-kpi ${this._status_filter === key ? "active" : ""}" data-filter="${key}">
				<div class="ib-fu-kpi-value" style="color:${color};">${value}</div>
				<div class="ib-fu-kpi-label">${label}</div>
			</div>`;

		this.$summary.html(
			card("all", __("Total My Docs"), total, "var(--text-color)") +
			card("Followed Up", __("Followed Up"), followed, "#16a34a") +
			card("Never", __("Pending"), pending, "#d97757") +
			card("Overdue", __("Overdue"), overdue, "#dc2626")
		);

		this.$summary.find(".ib-fu-kpi").on("click", (e) => {
			const key = $(e.currentTarget).data("filter");
			this._status_filter = key;
			this._page = 0;
			this.$filters.removeClass("active").filter(`[data-filter="${key}"]`).addClass("active");
			this._render_summary();
			this._render_list();
		});
	}

	_render_list() {
		const q = (this._search || "").toLowerCase();
		let rows = this._docs || [];
		if (this._status_filter !== "all") {
			rows = rows.filter((d) => d.follow_up_status === this._status_filter);
		}
		if (q) {
			rows = rows.filter((d) => JSON.stringify(d).toLowerCase().includes(q));
		}

		this.$count.text(__("{0} document(s)", [rows.length]));

		if (!rows.length) {
			this.$pager.empty();
			const msg = this._docs.length
				? __("Nothing matches this filter — try clearing the search or status filter above.")
				: __("No documents assigned to you for {0} yet.", [this._doctype]);
			this.$body.html(`<div class="ib-fu-empty"><span class="fa fa-inbox"></span>${msg}</div>`);
			return;
		}

		const pages = Math.max(1, Math.ceil(rows.length / IB_FU_PAGE_SIZE));
		if (this._page >= pages) this._page = pages - 1;
		const start = this._page * IB_FU_PAGE_SIZE;
		const page_rows = rows.slice(start, start + IB_FU_PAGE_SIZE);

		this.$body.html(`
			<table class="ib-fu-table">
				<thead><tr>
					<th>${__("Document")}</th>
					<th>${__("Details")}</th>
					<th>${__("Status")}</th>
					<th>${__("Next / Last Follow-up")}</th>
					<th></th>
				</tr></thead>
				<tbody>${page_rows.map((d) => this._row_html(d)).join("")}</tbody>
			</table>
		`);

		this.$body.find(".ib-fu-log-btn").on("click", (e) => {
			this._open_log_dialog($(e.currentTarget).data("name"));
		});

		if (pages > 1) {
			this.$pager.html(`
				<button id="ib-fu-prev" ${this._page === 0 ? "disabled" : ""}>← ${__("Prev")}</button>
				<span>${__("Page {0} of {1}", [this._page + 1, pages])}</span>
				<button id="ib-fu-next" ${this._page >= pages - 1 ? "disabled" : ""}>${__("Next")} →</button>
			`);
		} else {
			this.$pager.empty();
		}
	}

	_row_html(d) {
		const status = d.follow_up_status;
		return `
			<tr>
				<td><a href="/app/${frappe.router.slug(this._doctype)}/${encodeURIComponent(d.name)}" target="_blank">${frappe.utils.escape_html(d.name)}</a></td>
				<td>${this._detail_text(d)}${this._contact_buttons(d)}</td>
				<td><span class="ib-fu-badge ${IB_FU_STATUS_CLS[status]}">${IB_FU_STATUS_LABEL[status]}</span></td>
				<td>${this._due_text(d)}</td>
				<td class="text-right"><button class="btn btn-xs btn-default ib-fu-log-btn" data-name="${frappe.utils.escape_html(d.name)}">${__("Log Follow-up")}</button></td>
			</tr>`;
	}

	_due_text(d) {
		if (d.follow_up_status === "Never") return "—";
		if (d.follow_up_status === "Overdue") {
			return `<span class="ib-fu-due-text overdue">${__("{0} days overdue", [d.days_overdue])}</span>`;
		}
		if (d.next_follow_up_date) {
			const days = frappe.datetime.get_day_diff(d.next_follow_up_date, frappe.datetime.now_date());
			const rel = days === 0 ? __("today") : days === 1 ? __("in 1 day") : __("in {0} days", [days]);
			return `<span class="ib-fu-due-text">${frappe.datetime.str_to_user(d.next_follow_up_date)} (${rel})</span>`;
		}
		return `<span class="ib-fu-due-text">${__("Logged {0}", [frappe.datetime.comment_when(d.last_follow_up)])}</span>`;
	}

	_contact_buttons(d) {
		if (!d.contact_mobile) return "";
		const digits = String(d.contact_mobile).replace(/[^0-9]/g, "");
		if (!digits) return "";
		const wa_number = digits.length === 10 ? "91" + digits : digits;
		return `
			<span class="ib-fu-contact-btns">
				<a href="tel:${digits}" title="${__("Call")}"><iconify-icon icon="lucide:phone"></iconify-icon></a>
				<a href="https://wa.me/${wa_number}" target="_blank" title="${__("WhatsApp")}"><iconify-icon icon="lucide:message-circle"></iconify-icon></a>
			</span>`;
	}

	_detail_text(d) {
		return Object.keys(d)
			.filter((k) => !IB_FU_HIDDEN_FIELDS.includes(k))
			.map((k) => {
				const v = d[k];
				if (!v && v !== 0) return null;
				return IB_FU_AMOUNT_FIELDS.includes(k) ? frappe.format(v, { fieldtype: "Currency" }) : frappe.utils.escape_html(String(v));
			})
			.filter(Boolean)
			.join(" · ");
	}

	_history_html(history) {
		if (!history.length) {
			return `<div class="ib-fu-history-empty">${__("No follow-ups logged yet — this will be the first.")}</div>`;
		}
		return history.map((h) => `
			<div class="ib-fu-history-row">
				<div class="ib-fu-history-top">
					<span class="ib-fu-history-type">${frappe.utils.escape_html(h.follow_up_type)} · ${frappe.utils.escape_html(h.outcome)}</span>
					<span class="ib-fu-history-when">${frappe.utils.escape_html(h.owner)} · ${frappe.datetime.comment_when(h.creation)}</span>
				</div>
				${h.notes ? `<div class="ib-fu-history-notes">${frappe.utils.escape_html(h.notes)}</div>` : ""}
				${h.next_follow_up_date ? `<div class="ib-fu-history-next">${__("Next follow-up set for")} ${frappe.datetime.str_to_user(h.next_follow_up_date)}</div>` : ""}
			</div>
		`).join("");
	}

	_open_log_dialog(docname) {
		const default_next = frappe.datetime.add_days(frappe.datetime.now_date(), 3);
		const d = new frappe.ui.Dialog({
			title: __("Follow-up: {0}", [docname]),
			size: "small",
			fields: [
				{ fieldtype: "HTML", fieldname: "history_label", options: `<div class="ib-fu-history-label">${__("Previously Logged")}</div>` },
				{ fieldtype: "HTML", fieldname: "history" },
				{ fieldtype: "Section Break", label: __("Log a New Follow-up") },
				{ fieldtype: "Select", fieldname: "follow_up_type", label: __("Type"), reqd: 1,
					options: "Call\nMeeting\nWhatsApp\nEmail\nVisit\nOther", default: "Call" },
				{ fieldtype: "Select", fieldname: "outcome", label: __("Outcome"), reqd: 1,
					options: "Positive\nNeutral\nNegative\nNo Answer", default: "Positive" },
				{ fieldtype: "Small Text", fieldname: "notes", label: __("Notes") },
				{ fieldtype: "Date", fieldname: "next_follow_up_date", label: __("Next Follow-up Date"), default: default_next },
			],
			primary_action_label: __("Save"),
			primary_action: (values) => {
				frappe.call({
					method: "instabiz.overrides.follow_ups.log_follow_up",
					args: {
						reference_doctype: this._doctype,
						reference_name: docname,
						...values,
					},
					freeze: true,
					callback: () => {
						d.hide();
						frappe.show_alert({ message: __("Follow-up logged"), indicator: "green" });
						this.refresh();
					},
				});
			},
		});
		d.get_field("history").$wrapper.html(`<div class="ib-fu-history"><div class="ib-fu-history-empty">${__("Loading...")}</div></div>`);
		d.show();

		frappe.call({
			method: "instabiz.overrides.follow_ups.get_follow_up_history",
			args: { reference_doctype: this._doctype, reference_name: docname },
			callback: (r) => {
				d.get_field("history").$wrapper.html(`<div class="ib-fu-history">${this._history_html(r.message || [])}</div>`);
			},
		});
	}
}
