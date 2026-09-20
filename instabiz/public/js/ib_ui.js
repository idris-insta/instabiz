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
		"refresh-cw": '<path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M8 16H3v5"/>',
		"alert-triangle": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
		"check-circle": '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="m9 11 3 3L22 4"/>',
		"calendar": '<path d="M8 2v4"/><path d="M16 2v4"/><rect width="18" height="18" x="3" y="4" rx="2"/><path d="M3 10h18"/>',
		"factory": '<path d="M2 20a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8l-7 5V8l-7 5V4a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2Z"/><path d="M17 18h1"/><path d="M12 18h1"/><path d="M7 18h1"/>',
		"wallet": '<path d="M19 7V4a1 1 0 0 0-1-1H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4h3a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1"/><path d="M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4"/>',
		"file-text": '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
		"activity": '<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/>',
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

		// ── page shell ──────────────────────────────────────────────────────
		// Mounts a fresh .ib-ui-page into page.main (never wipes page.main
		// itself — see feedback_frappe_page_shell_gotcha). Returns the jQuery
		// body element to render into.
		mount(page, { narrow = false } = {}) {
			const $el = $(`<div class="ib-ui-page${narrow ? " ib-ui-page--narrow" : ""}"></div>`);
			$(page.main).find(".ib-ui-page").remove();
			$(page.main).append($el);
			return $el;
		},

		btn(label, { variant = "", icon, attrs = "" } = {}) {
			const v = variant ? ` ib-ui-btn--${variant}` : "";
			return `<button class="ib-ui-btn${v}" ${attrs}>${icon ? ibUI.icon(icon, 13) : ""}${esc(label)}</button>`;
		},

		toolbar(inner) {
			return `<div class="ib-ui-toolbar">${Array.isArray(inner) ? inner.join("") : inner || ""}</div>`;
		},

		// returns { el, input } — caller appends el, binds input events
		search(placeholder = "Search…") {
			const el = $(`<div class="ib-ui-search"><span class="ico">${ibUI.icon("search")}</span>` +
				`<input type="text" placeholder="${esc(placeholder)}" autocomplete="off" spellcheck="false"></div>`);
			return { el, input: el.find("input")[0], $input: el.find("input") };
		},

		// tabs — returns { el, setActive(id) }. onSwitch(id) fired on click.
		tabs(list, active, onSwitch) {
			const el = $(`<div class="ib-ui-tabs">${(list || [])
				.map((t) => `<button class="ib-ui-tab${t.id === active ? " is-active" : ""}" data-tab="${esc(t.id)}">${esc(t.label)}</button>`)
				.join("")}</div>`);
			el.on("click", ".ib-ui-tab", function () {
				el.find(".ib-ui-tab").removeClass("is-active");
				$(this).addClass("is-active");
				onSwitch && onSwitch($(this).data("tab"));
			});
			return { el, setActive: (id) => { el.find(".ib-ui-tab").removeClass("is-active");
				el.find(`[data-tab="${id}"]`).addClass("is-active"); } };
		},

		section(title, bodyHtml, { action } = {}) {
			return `<div class="ib-ui-section"><div class="ib-ui-section-h"><h5>${esc(title)}</h5>` +
				`${action || ""}</div>${bodyHtml || ""}</div>`;
		},

		bar(pct, { showLabel = true } = {}) {
			const p = Math.max(0, Math.min(100, Math.round(pct || 0)));
			const cls = p >= 75 ? "ok" : p >= 40 ? "warn" : "danger";
			return `<div class="ib-ui-bar"><span class="track"><span class="fill ${cls}" style="width:${p}%"></span></span>` +
				`${showLabel ? `<span class="pctlbl">${p}%</span>` : ""}</div>`;
		},

		feed(items, heading = "Recent") {
			const body = (items || []).length
				? (items || []).map((it) =>
					`<div class="ib-ui-feed-item"><span class="ib-ui-hint">${esc(it.t || "")}</span>` +
					`${it.tag ? `<span class="ib-ui-pill ib-ui-pill--muted">${esc(it.tag)}</span>` : ""}` +
					`<span>${it.text || ""}</span>${it.right ? `<span style="margin-left:auto">${it.right}</span>` : ""}</div>`).join("")
				: `<div class="ib-ui-hint">${esc("Nothing yet")}</div>`;
			return `<div class="ib-ui-feed"><h6>${esc(heading)}</h6>${body}</div>`;
		},

		refreshTime(d) {
			const t = (d || new Date()).toLocaleTimeString();
			return `<span class="ib-ui-refresh-time">${ibUI.icon("refresh-cw", 11)} ${esc(t)}</span>`;
		},

		// ── formatting ──────────────────────────────────────────────────────
		money(v) {
			return `<span class="ib-ui-num">${frappe.format(v || 0, { fieldtype: "Currency" })}</span>`;
		},
		num(v, dp = 0) {
			return `<span class="ib-ui-num">${frappe.format(flt(v || 0), { fieldtype: "Float", precision: dp })}</span>`;
		},
		pct(v) {
			return `<span class="ib-ui-num">${Math.round(v || 0)}%</span>`;
		},

		// compact Indian short form — 1.2 Cr / 4.5 L / 12.3 K. Used for KPI
		// values and chart axis labels, where the full ₹12,34,56,789 forces a
		// line break and pushes the ₹ onto a line of its own.
		shortNum(v, dp) {
			const f = parseFloat(v) || 0;
			const n = Math.abs(f), sign = f < 0 ? "-" : "";
			const cut = (x, u) => sign + (x >= 100 ? Math.round(x) : Math.round(x * 10) / 10) + u;
			if (n >= 1e7) return cut(n / 1e7, " Cr");
			if (n >= 1e5) return cut(n / 1e5, " L");
			if (n >= 1e4) return cut(n / 1e3, " K");
			return sign + n.toLocaleString("en-IN", { maximumFractionDigits: dp === undefined ? 0 : dp });
		},
		moneyFull(v) {
			return "₹" + (parseFloat(v) || 0).toLocaleString("en-IN", { maximumFractionDigits: 2 });
		},
		// ₹ + short form, full value kept in the tooltip
		moneyShort(v) {
			return `<span class="ib-ui-num" title="${esc(ibUI.moneyFull(v))}">₹${esc(ibUI.shortNum(v))}</span>`;
		},
		// ▲ 12% vs last month — invert:1 for metrics where down is good
		deltaChip(v, { suffix = "", invert = false } = {}) {
			const n = parseFloat(v);
			if (!isFinite(n)) return `<span class="ib-ui-delta neu">&mdash;</span>`;
			const r = Math.round(n * 10) / 10;
			if (!r) return `<span class="ib-ui-delta neu">flat${suffix ? " " + esc(suffix) : ""}</span>`;
			const good = invert ? r < 0 : r > 0;
			return `<span class="ib-ui-delta ${good ? "up" : "down"}">${r > 0 ? "▲" : "▼"} ` +
				`${Math.abs(r)}%${suffix ? " " + esc(suffix) : ""}</span>`;
		},
		// inline sparkline for a KPI card — no library, scales to the card
		sparkline(values, { h = 26 } = {}) {
			const v = (values || []).map((x) => parseFloat(x) || 0);
			if (v.length < 2) return "";
			const min = Math.min.apply(null, v.concat([0]));
			const max = Math.max.apply(null, v);
			const span = max - min || 1;
			const pts = v.map((x, i) => `${((i / (v.length - 1)) * 100).toFixed(2)},` +
				`${(h - 1 - ((x - min) / span) * (h - 5)).toFixed(2)}`);
			return `<svg class="ib-ui-spark" viewBox="0 0 100 ${h}" preserveAspectRatio="none" aria-hidden="true">` +
				`<polygon class="a" points="0,${h} ${pts.join(" ")} 100,${h}"/>` +
				`<polyline class="l" points="${pts.join(" ")}"/></svg>`;
		},
		// The KPI card every dashboard uses: label, one big number that never
		// wraps, a delta chip, a sub-line and an optional sparkline.
		// { l, v, sub, delta, deltaSuffix, invert, icon, tone, spark, route, key, title }
		kpi(k) {
			k = k || {};
			const tone = k.tone || "brand";
			const attr = k.route ? ` data-route="${esc(k.route)}"` : (k.key ? ` data-kpi="${esc(k.key)}"` : "");
			const click = k.route || k.key ? " is-click" : "";
			const delta = k.delta === undefined || k.delta === null || k.delta === ""
				? "" : ibUI.deltaChip(k.delta, { suffix: k.deltaSuffix, invert: k.invert });
			return `<div class="ib-ui-kpi ib-ui-kpi--${esc(tone)}${click}"${attr}>` +
				`<div class="ib-ui-kpi-h">${k.icon ? ibUI.icon(k.icon, 13) : ""}<span class="l">${esc(k.l)}</span></div>` +
				`<div class="v"${k.title ? ` title="${esc(k.title)}"` : ""}>${k.v === undefined || k.v === null ? "" : k.v}</div>` +
				`<div class="f">${delta}${k.sub ? `<span class="sub">${esc(k.sub)}</span>` : ""}</div>` +
				`${k.spark ? ibUI.sparkline(k.spark) : ""}</div>`;
		},
		kpiGrid(list, { min = 180 } = {}) {
			return `<div class="ib-ui-kpi-grid" style="--ib-kpi-min:${min}px">` +
				`${(list || []).filter(Boolean).map((k) => ibUI.kpi(k)).join("")}</div>`;
		},
		// Card whose body is a chart slot — keeps every dashboard chart in the
		// same frame (title row, optional right-hand action, fixed height).
		chartCard({ id, kind, title, right, height = 220, note } = {}) {
			return `<div class="ib-ui-card ib-ui-card--chart"><div class="ib-ui-card-h">` +
				`${kind ? `<span class="k">${esc(kind)}</span>` : ""}` +
				`${title ? `<span class="t">${esc(title)}</span>` : ""}` +
				`${right ? `<span class="r">${right}</span>` : ""}</div>` +
				`${note ? `<div class="ib-ui-hint" style="margin:-4px 0 6px">${esc(note)}</div>` : ""}` +
				`<div class="ib-ui-chart" id="${esc(id)}" style="height:${height}px"></div></div>`;
		},
		// wire every [data-route="app/xyz"] inside $root to navigate on click
		wireRoutes($root) {
			$root.on("click", "[data-route]", function (e) {
				e.stopPropagation();
				const r = $(this).attr("data-route");
				if (r) frappe.set_route(r.split("/").filter(Boolean));
			});
		},
	};

	window.ibUI = ibUI;
})();
