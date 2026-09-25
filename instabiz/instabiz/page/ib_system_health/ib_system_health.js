frappe.pages["ib-system-health"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({ parent: wrapper, title: "System Health", single_column: true });
	wrapper._ib_health = new IBSystemHealth(wrapper.page);
};

frappe.pages["ib-system-health"].on_page_show = function (wrapper) {
	if (wrapper._ib_health) wrapper._ib_health.refresh();
};

// Rebuilt on the IB Design System (window.ibUI + .ib-ui-* components), 2026-09-20.
const IB_HEALTH_PILL = {
	online: "ok",
	offline: "danger",
	degraded: "warn",
	unknown: "muted",
};

class IBSystemHealth {
	constructor(page) {
		this.page = page;
		this._fetching = false;
		this.$el = ibUI.mount(page);
		this._build_layout();
	}

	_build_layout() {
		this.$el.html(`
			${ibUI.toolbar([
				`<span style="flex:1;font-size:1.15rem;font-weight:700;color:var(--heading-color)">System Health</span>`,
				`<span id="ib-health-ts" class="ib-ui-hint"></span>`,
				`<span id="ib-health-summary" hidden></span>`,
				ibUI.btn("Refresh", { variant: "ghost", icon: "refresh-cw", attrs: 'id="ib-health-refresh"' }),
			])}
			<div id="ib-health-grid" class="ib-ui-grid" style="grid-template-columns:repeat(auto-fit,minmax(260px,1fr))">
				${ibUI.skeleton(3)}
			</div>
		`);
		this.$el.find("#ib-health-refresh").on("click", () => this.refresh());
	}

	refresh() {
		if (this._fetching) return;
		this._fetching = true;
		const $btn = this.$el.find("#ib-health-refresh");
		$btn.prop("disabled", true).text("Checking…");

		frappe.call({
			method: "instabiz.instabiz.page.ib_system_health.ib_system_health.get_health_status",
			callback: (r) => {
				this._fetching = false;
				$btn.prop("disabled", false).html(ibUI.icon("refresh-cw", 13) + " Refresh");
				if (!r.message) return;
				this._render(r.message);
			},
			error: () => {
				this._fetching = false;
				$btn.prop("disabled", false).html(ibUI.icon("refresh-cw", 13) + " Refresh");
			},
		});
	}

	_render(data) {
		const checks = data.checks || [];
		this.$el.find("#ib-health-ts").text(
			"Last checked: " + frappe.datetime.str_to_user(data.checked_at)
		);

		const online = checks.filter((c) => c.status === "online").length;
		const allOnline = checks.length && online === checks.length;
		this.$el
			.find("#ib-health-summary")
			.prop("hidden", false)
			.html(ibUI.pill(`${online}/${checks.length} online`, allOnline ? "ok" : "warn"));

		const $grid = this.$el.find("#ib-health-grid");
		if (!checks.length) {
			$grid.html(ibUI.empty("No checks configured.", "activity"));
			return;
		}

		$grid.html(
			checks
				.map((c) => {
					const variant = IB_HEALTH_PILL[c.status] || IB_HEALTH_PILL.unknown;
					return `
						<div class="ib-ui-card">
							<div class="ib-ui-card-h">
								<span class="t" style="flex:1">${ibUI.esc(c.label || "")}</span>
								${ibUI.pill(c.status || "", variant)}
							</div>
							<div class="ib-ui-hint">${ibUI.esc(c.detail || "")}</div>
						</div>`;
				})
				.join("")
		);
	}
}
