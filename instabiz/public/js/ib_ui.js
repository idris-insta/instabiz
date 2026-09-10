/**
 * ib_ui.js — IB Design System markup helpers.
 * Pairs with the .ib-ui-* component classes in instabiz.bundle.css.
 * window.ibUI is available on every desk page (loaded via app_include_js).
 */
(function () {
	const ICONS = {
		search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
		"arrow-right": '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
		"arrow-up-right": '<path d="M7 7h10v10"/><path d="M7 17 17 7"/>',
		truck: '<path d="M14 18V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v11a1 1 0 0 0 1 1h2"/><path d="M15 18H9"/><path d="M19 18h2a1 1 0 0 0 1-1v-3.65a1 1 0 0 0-.22-.62l-3.48-4.35A1 1 0 0 0 17.52 8H14"/><circle cx="17" cy="18" r="2"/><circle cx="7" cy="18" r="2"/>',
		layers: '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
		settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
		box: '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>',
		"shopping-cart": '<circle cx="8" cy="21" r="1"/><circle cx="19" cy="21" r="1"/><path d="M2.05 2.05h2l2.66 12.42a2 2 0 0 0 2 1.58h9.78a2 2 0 0 0 1.95-1.57l1.65-7.43H5.12"/>',
		package: '<path d="M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73z"/><path d="M12 22V12"/><polyline points="3.29 7 12 12 20.71 7"/><path d="m7.5 4.27 9 5.15"/>',
		"git-branch": '<line x1="6" x2="6" y1="3" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/>',
		scan: '<path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/><path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/><path d="M7 12h10"/>',
		plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
		minus: '<path d="M5 12h14"/>',
		clock: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
		"trending-up": '<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/>',
		users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
		tag: '<path d="M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586 1.414l8.704 8.704a2.426 2.426 0 0 0 3.42 0l6.58-6.58a2.426 2.426 0 0 0 0-3.42z"/><circle cx="7.5" cy="7.5" r=".5" fill="currentColor"/>',
	};

	function esc(v) {
		return v === undefined || v === null ? "" : frappe.utils.escape_html(String(v));
	}

	const ibUI = {
		esc,
		icon(name, size = 15) {
			return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICONS[name] || ICONS.package}</svg>`;
		},
		link(dt, name) {
			if (!name) return "";
			return `<a href="/app/${frappe.router.slug(dt)}/${encodeURIComponent(name)}">${esc(name)}</a>`;
		},
		pill(text, variant = "muted") {
			return `<span class="ib-ui-pill ib-ui-pill--${variant}">${esc(text)}</span>`;
		},
		kv(rows) {
			const body = (rows || [])
				.filter((r) => r && r[1] !== undefined && r[1] !== null && r[1] !== "")
				.map(([k, v]) => `<div class="k">${esc(k)}</div><div>${v}</div>`)
				.join("");
			return `<div class="ib-ui-kv">${body}</div>`;
		},
		card({ kind, title, icon, body, focus } = {}) {
			const head =
				kind || title
					? `<div class="ib-ui-card-h">${icon ? ibUI.icon(icon) : ""}` +
						`${kind ? `<span class="k">${esc(kind)}</span>` : ""}` +
						`${title ? `<span class="t">${title}</span>` : ""}</div>`
					: "";
			return `<div class="ib-ui-node ${focus ? "is-focus" : ""}"><div class="ib-ui-card">${head}${body || ""}</div></div>`;
		},
		stat({ v, l, sub, route } = {}) {
			const cls = route ? "ib-ui-stat ib-ui-stat--link" : "ib-ui-stat";
			const attr = route ? ` data-route="${esc(route)}"` : "";
			return `<div class="${cls}"${attr}><div class="v">${v ?? ""}</div><div class="l">${esc(l)}</div>${sub ? `<div class="sub">${esc(sub)}</div>` : ""}</div>`;
		},
		statGrid(stats) {
			return `<div class="ib-ui-stat-grid">${(stats || []).map((s) => ibUI.stat(s)).join("")}</div>`;
		},
		skeleton(n = 3) {
			return `<div>${'<div class="ib-ui-skeleton"></div>'.repeat(n)}</div>`;
		},
		empty(msg, icon = "package") {
			return `<div class="ib-ui-empty">${ibUI.icon(icon, 40)}<div>${esc(msg)}</div></div>`;
		},
		chip(text, active) {
			return `<span class="ib-ui-chip ${active ? "is-active" : ""}" data-chip="${esc(text)}">${esc(text)}</span>`;
		},
		table({ head, rows }) {
			const h = `<tr>${(head || []).map((c) => `<th${/qty|amount|total|value|₹|%/i.test(c) ? ' class="num"' : ""}>${esc(c)}</th>`).join("")}</tr>`;
			const b = (rows || [])
				.map((r) => `<tr>${r.map((c) => `<td>${c === null || c === undefined ? "" : c}</td>`).join("")}</tr>`)
				.join("");
			return `<div class="ib-ui-table-wrap"><table class="ib-ui-table"><thead>${h}</thead><tbody>${b}</tbody></table></div>`;
		},
	};

	window.ibUI = ibUI;
})();
