/**
 * so_production_panel.js
 * Injected globally via app_include_js. Adds a production stage + dispatch status
 * panel on the Sales Order form. Uses Iconify icons (globally loaded).
 */

frappe.ui.form.on("Sales Order", {
	refresh(frm) {
		if (frm.is_new()) return;
		_ib_so_prod_panel(frm);
	},
	after_save(frm) {
		_ib_so_prod_panel(frm);
	},
});

function _ib_so_prod_panel(frm) {
	const $existing = $(frm.layout.wrapper).find(".ib-so-prod-panel");
	$existing.remove();

	// Current Frappe's Section object exposes `.wrapper`, not `.$wrapper` — the
	// latter was always undefined here, so `$anchor.after($panel)` silently
	// no-op'd on an empty jQuery set. The panel has likely never actually
	// rendered until this fix.
	const $anchor = $(frm.layout.sections[0].wrapper);
	const $panel = $(`
		<div class="ib-so-prod-panel" style="margin:0 0 12px 0">
			<div style="padding:12px 14px;text-align:center;color:var(--text-muted);
				background:var(--card-bg);border:1px solid var(--border-color);
				border-radius:8px;font-size:13px">
				<iconify-icon icon="lucide:loader" width="14" height="14"
					style="vertical-align:middle;margin-right:6px;animation:spin 1s linear infinite"></iconify-icon>
				Loading production status...
			</div>
		</div>
	`);
	$anchor.after($panel);

	frappe.call({
		method: "instabiz.overrides.production.get_so_production_panel",
		args: { sales_order: frm.doc.name },
		callback(r) {
			const data = r.message;
			if (!data) { $panel.remove(); return; }
			$panel.html(_ib_build_prod_panel(data));
		},
		error() { $panel.remove(); },
	});
}

const _IB_STAGE_ICONS = {
	"Coating":          "lucide:paintbrush",
	"Slitting":         "lucide:scissors",
	"Rewinding":        "lucide:rotate-cw",
	"Cutting":          "lucide:cut",
	"Silicon":          "lucide:droplet",
	"Packing":          "lucide:package",
	"Ready to Deliver": "lucide:truck",
	"Delivered":        "lucide:check-circle",
};

const _IB_DISPATCH = {
	"Not Dispatched": { icon: "lucide:clock",       color: "#9ca3af" },
	"Dispatched":     { icon: "lucide:send",         color: "#2563eb" },
	"In Transit":     { icon: "lucide:navigation",   color: "#0891b2" },
	"Delivered":      { icon: "lucide:check-circle", color: "#059669" },
};

const _IB_PRIORITY_COLOR = {
	Urgent: "#dc2626", High: "#ea580c", Normal: "#2563eb", Low: "#6b7280",
};

const _IB_RISK = {
	"overdue":  { label: "Overdue",  color: "#dc2626", bg: "#fef2f2" },
	"at-risk":  { label: "At Risk",  color: "#ea580c", bg: "#fff7ed" },
	"on-track": { label: "On Track", color: "#059669", bg: "#ecfdf5" },
	"none":     { label: "",         color: "#6b7280", bg: "#f9fafb" },
};

function _ib_esc(s) {
	return frappe.utils.escape_html(String(s || ""));
}

function _ib_overall_progress_row(data) {
	if (data.overall_pct == null) return "";
	const risk = _IB_RISK[data.risk] || _IB_RISK.none;
	const pct = data.overall_pct;
	const days = data.days_left;
	const daysTxt = days == null ? "" :
		days < 0 ? __("{0}d overdue", [Math.abs(days)]) :
		days === 0 ? __("Due today") :
		__("{0}d left", [days]);
	return `
	<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap">
		<div style="flex:1;min-width:160px;display:flex;align-items:center;gap:8px">
			<div style="flex:1;height:7px;background:#e5e7eb;border-radius:4px;overflow:hidden;max-width:200px">
				<div style="width:${pct}%;height:100%;background:${pct >= 100 ? "#059669" : "#2563eb"};border-radius:4px;transition:width .3s"></div>
			</div>
			<span style="font-size:12px;font-weight:600;color:var(--text-color)">${pct}%</span>
			${data.overall_current_stage ? `<span style="font-size:11px;color:var(--text-muted)">— ${_ib_esc(data.overall_current_stage)}</span>` : ""}
		</div>
		${daysTxt ? `<span style="background:${risk.bg};color:${risk.color};padding:2px 9px;
			border-radius:10px;font-size:10px;font-weight:700">${daysTxt}</span>` : ""}
		<a href="/app/ib-production-tracker" style="font-size:11px;color:var(--text-muted);white-space:nowrap">
			${__("View in Production Tracker")} →</a>
	</div>`;
}

function _ib_build_prod_panel(data) {
	if (!data.has_order_sheet) {
		return `
		<div class="ib-so-prod-panel" style="
			padding:12px 14px;background:var(--card-bg);
			border:1px solid var(--border-color);border-radius:8px;
			border-left:4px solid #9ca3af;margin:0 0 12px 0">
			<div style="display:flex;align-items:center;gap:8px;color:var(--text-muted);font-size:13px">
				<iconify-icon icon="lucide:factory" width="15" height="15"></iconify-icon>
				<strong>Production</strong>
				<span style="background:#f1f5f9;padding:1px 8px;border-radius:10px;
					font-size:10px;font-weight:700;color:#9ca3af">NOT STARTED</span>
			</div>
			<div style="font-size:12px;color:var(--text-muted);margin-top:5px">
				Production not started yet. Will be scheduled automatically.
			</div>
		</div>`;
	}

	const dispatch   = data.dispatch || {};
	const dispMeta   = _IB_DISPATCH[dispatch.status] || _IB_DISPATCH["Not Dispatched"];
	const priColor   = _IB_PRIORITY_COLOR[data.priority] || "#6b7280";

	const rtdBanner = data.ready_to_deliver ? `
		<div style="background:#fff7ed;border:1px solid #ea580c40;border-radius:6px;
			padding:9px 12px;margin-bottom:10px;display:flex;align-items:center;gap:8px">
			<iconify-icon icon="lucide:package-check" width="15" height="15"
				style="color:#ea580c;flex-shrink:0"></iconify-icon>
			<strong style="color:#ea580c;font-size:12px">Ready for Packaging & Dispatch</strong>
			<span style="font-size:11px;color:var(--text-muted)">All stages complete</span>
		</div>` : "";

	const itemRows = (data.items || []).map(item => {
		const stageCells = (item.stages || []).map(s => {
			const icon  = _IB_STAGE_ICONS[s.stage] || "lucide:circle";
			const done  = s.status === "Completed";
			const active = s.status === "In Progress";
			const col   = done ? "#059669" : active ? "#2563eb" : "#d1d5db";
			const bg    = done ? "#d1fae5" : active ? "#dbeafe" : "#f9fafb";
			const label = s.stage.replace("Ready to Deliver", "RTD");
			return `<span title="${_ib_esc(s.stage)}: ${_ib_esc(s.status || "Not created")} (${s.completed_qty||0}/${s.target_qty||0})"
				style="display:inline-flex;align-items:center;gap:3px;background:${bg};
				color:${col};border:1px solid ${col}40;border-radius:10px;
				padding:2px 7px;font-size:10px;font-weight:600;white-space:nowrap;margin:1px">
				<iconify-icon icon="${icon}" width="9" height="9"></iconify-icon>
				${_ib_esc(label)}</span>`;
		}).join("");

		const pct = item.completion_pct || 0;
		const cur = item.current_stage || (pct >= 100 ? "Complete" : "Pending");

		return `<tr style="border-bottom:1px solid var(--border-color)">
			<td style="padding:5px 8px;font-size:12px;font-family:monospace;white-space:nowrap">
				${_ib_esc(item.item_code)}</td>
			<td style="padding:5px 8px">
				<div style="display:flex;flex-wrap:wrap;gap:2px">${stageCells}</div></td>
			<td style="padding:5px 8px;font-size:11px;color:var(--text-muted);white-space:nowrap">
				${_ib_esc(cur)}</td>
			<td style="padding:5px 8px;white-space:nowrap">
				<div style="display:inline-flex;align-items:center;gap:4px;font-size:11px">
					<div style="width:56px;height:5px;background:#e5e7eb;border-radius:3px;display:inline-block;overflow:hidden">
						<div style="width:${pct}%;height:100%;background:#059669;border-radius:3px"></div></div>
					<span style="color:var(--text-muted)">${pct}%</span></div></td>
		</tr>`;
	}).join("");

	const dispSection = dispatch.status && dispatch.status !== "Not Dispatched" ? `
		<div style="margin-top:10px;padding:9px 12px;background:${dispMeta.color}10;
			border:1px solid ${dispMeta.color}30;border-radius:6px;
			display:flex;align-items:center;gap:10px;flex-wrap:wrap">
			<iconify-icon icon="${dispMeta.icon}" width="14" height="14"
				style="color:${dispMeta.color};flex-shrink:0"></iconify-icon>
			<strong style="color:${dispMeta.color};font-size:12px">${_ib_esc(dispatch.status)}</strong>
			${dispatch.latest_dn ? `<a href="/app/delivery-note/${dispatch.latest_dn}" target="_blank"
				style="font-size:11px">${dispatch.latest_dn}</a>` : ""}
			${dispatch.lr_number ? `<span style="font-size:11px;color:var(--text-muted)">LR: ${_ib_esc(dispatch.lr_number)}</span>` : ""}
			${dispatch.transporter ? `<span style="font-size:11px;color:var(--text-muted)">${_ib_esc(dispatch.transporter)}</span>` : ""}
			${dispatch.vehicle ? `<span style="font-size:11px;color:var(--text-muted)">${_ib_esc(dispatch.vehicle)}</span>` : ""}
		</div>` : "";

	return `
	<div class="ib-so-prod-panel" style="
		background:var(--card-bg);border:1px solid var(--border-color);
		border-radius:8px;overflow:hidden;margin:0 0 12px 0">
		<div style="padding:9px 13px;background:var(--subtle-fg,#f8fafc);
			border-bottom:1px solid var(--border-color);
			display:flex;align-items:center;gap:8px;flex-wrap:wrap">
			<iconify-icon icon="lucide:factory" width="14" height="14"
				style="color:var(--text-muted);flex-shrink:0"></iconify-icon>
			<strong style="font-size:13px">Production</strong>
			<span style="background:${priColor}18;color:${priColor};
				padding:1px 7px;border-radius:10px;font-size:10px;font-weight:700;
				text-transform:uppercase">${_ib_esc(data.priority || "Normal")}</span>
			<span style="background:var(--control-bg,#f1f5f9);padding:1px 7px;
				border-radius:10px;font-size:10px;color:var(--text-muted)">
				${_ib_esc(data.status || "")}</span>
			${data.delivery_date ? `<span style="font-size:11px;color:var(--text-muted);margin-left:auto">
				<iconify-icon icon="lucide:calendar" width="11" height="11"
					style="vertical-align:middle;margin-right:3px"></iconify-icon>
				${frappe.datetime.str_to_user(data.delivery_date)}</span>` : ""}
		</div>
		<div style="padding:11px 13px">
			${_ib_overall_progress_row(data)}
			${rtdBanner}
			<div style="overflow-x:auto">
				<table style="width:100%;border-collapse:collapse;font-size:12px">
					<thead><tr style="border-bottom:2px solid var(--border-color)">
						<th style="padding:3px 8px;text-align:left;font-size:10px;font-weight:700;text-transform:uppercase;color:var(--text-muted)">Item</th>
						<th style="padding:3px 8px;text-align:left;font-size:10px;font-weight:700;text-transform:uppercase;color:var(--text-muted)">Stages</th>
						<th style="padding:3px 8px;text-align:left;font-size:10px;font-weight:700;text-transform:uppercase;color:var(--text-muted)">Current</th>
						<th style="padding:3px 8px;text-align:left;font-size:10px;font-weight:700;text-transform:uppercase;color:var(--text-muted)">Progress</th>
					</tr></thead>
					<tbody>${itemRows || `<tr><td colspan="4" style="padding:12px;text-align:center;color:var(--text-muted)">No items</td></tr>`}</tbody>
				</table>
			</div>
			${dispSection}
		</div>
	</div>`;
}
