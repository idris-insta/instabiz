/**
 * ib_dash_kit.js — shared dashboard kit for every IB dashboard page.
 *
 * window.ibDash gives four things, so no dashboard hand-rolls them again:
 *   ibDash.chart(el, opts)        theme-aware frappe.Chart wrapper (short axis
 *                                numbers, currency tooltips, empty state,
 *                                auto-destroy, dark-mode palette)
 *   ibDash.filters(page, spec)    filter bar in page.page_form, values saved
 *                                per user+page, period presets → from/to dates
 *   ibDash.personalise(page, ..)  show / hide / reorder cards, saved per user
 *   ibDash.store / read           tiny per-user localStorage helper
 *
 * Loaded globally via app_include_js, after ib_ui.js.
 */
(function () {
	const user = () => (frappe.session && frappe.session.user) || "guest";
	const isDark = () => document.documentElement.getAttribute("data-theme") === "dark";

	// ── palettes ────────────────────────────────────────────────────────────
	// Brand orange first, then hues that stay distinguishable on both themes
	// (checked against Frappe's light #fff / dark #1c2126 card backgrounds).
	const PALETTE_LIGHT = ["#d97757", "#2f9e8f", "#6366f1", "#f59e0b", "#0ea5e9", "#a855f7", "#64748b", "#ef4444"];
	const PALETTE_DARK = ["#e8916f", "#3fbfad", "#818cf8", "#fbbf24", "#38bdf8", "#c084fc", "#94a3b8", "#f87171"];
	const TONE = {
		brand: "#d97757", ok: "#10b981", warn: "#f59e0b", danger: "#ef4444",
		info: "#6366f1", neutral: "#64748b",
	};

	function palette(n, tone) {
		const base = isDark() ? PALETTE_DARK : PALETTE_LIGHT;
		if (tone && TONE[tone]) return [TONE[tone]];
		if (!n || n <= base.length) return base.slice(0, n || base.length);
		const out = [];
		for (let i = 0; i < n; i++) out.push(base[i % base.length]);
		return out;
	}

	// ── chart ───────────────────────────────────────────────────────────────
	// opts: { type, labels, datasets, height, currency, percent, dp, colors,
	//         tone, stacked, spline, dots, empty, emptyIcon, yMarkers,
	//         onSelect(index, label) }
	function chart(el, opts) {
		const node = el instanceof jQuery ? el[0] : el;
		if (!node) return null;
		opts = opts || {};

		// Frappe charts append into the node and never clean up after
		// themselves; destroy + empty keeps repeated refreshes from stacking
		// several <svg>s (which is what produced the inner scrollbar and the
		// stray dots on the main dashboard).
		if (node._ibChart) {
			try { node._ibChart.destroy && node._ibChart.destroy(); } catch (e) { /* already gone */ }
			node._ibChart = null;
		}
		$(node).empty();

		const sets = (opts.datasets || []).filter((s) => s && (s.values || []).length);
		const hasValue = sets.some((s) => (s.values || []).some((v) => parseFloat(v)));
		if (!sets.length || (!hasValue && opts.hide_empty !== false)) {
			$(node).html(ibUI.empty(opts.empty || "No data for this period", opts.emptyIcon || "activity"));
			return null;
		}

		const n = (opts.labels || []).length;
		const points = Math.max.apply(null, sets.map((s) => (s.values || []).length).concat([0]));
		const fmt = (v) => {
			if (opts.percent) return (Math.round((v || 0) * 10) / 10) + "%";
			if (opts.currency === false) return ibUI.shortNum(v, opts.dp);
			return "₹" + Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: opts.dp || 0 });
		};

		const cfg = {
			type: opts.type || "line",
			height: opts.height || 220,
			colors: opts.colors || palette(sets.length, opts.tone),
			animate: opts.animate === undefined ? 1 : opts.animate,
			truncateLegends: 1,
			data: { labels: opts.labels || [], datasets: sets },
			axisOptions: Object.assign({
				xIsSeries: opts.xIsSeries === undefined ? 1 : opts.xIsSeries,
				// Long ₹ numbers are what clipped the y-axis — 12,45,678 needs
				// ~70px of gutter that frappe-charts does not reserve.
				shortenYAxisNumbers: 1,
				xAxisMode: "tick",
			}, opts.axisOptions || {}),
			barOptions: Object.assign({ stacked: opts.stacked ? 1 : 0, spaceRatio: n > 12 ? 0.3 : 0.45 }, opts.barOptions || {}),
			lineOptions: Object.assign({
				regionFill: opts.regionFill === undefined ? 1 : opts.regionFill,
				spline: opts.spline === undefined ? 1 : opts.spline,
				hideDots: opts.dots ? 0 : (points > 10 ? 1 : 0),
			}, opts.lineOptions || {}),
			tooltipOptions: Object.assign({
				formatTooltipX: (d) => String(d),
				formatTooltipY: fmt,
			}, opts.tooltipOptions || {}),
		};
		if (opts.yMarkers) cfg.data.yMarkers = opts.yMarkers;
		if (opts.maxSlices) cfg.maxSlices = opts.maxSlices;
		if (opts.valuesOverPoints) cfg.valuesOverPoints = 1;

		let c = null;
		try {
			c = new frappe.Chart(node, cfg);
		} catch (e) {
			console.warn("IB: chart render failed", e);
			$(node).html(ibUI.empty("Chart could not be drawn", "alert-triangle"));
			return null;
		}
		node._ibChart = c;
		$(node).addClass("ib-ui-chart");
		if (cfg.lineOptions.hideDots) $(node).addClass("no-dots");
		if (opts.onSelect) {
			try {
				c.parent.addEventListener("data-select", (e) => opts.onSelect(e.index, (opts.labels || [])[e.index]));
			} catch (e) { /* older frappe-charts — skip */ }
		}
		return c;
	}

	// ── per-user store ──────────────────────────────────────────────────────
	function key(k) { return `ib:${k}:${user()}`; }
	function store(k, v) {
		try { localStorage.setItem(key(k), JSON.stringify(v)); } catch (e) { /* private mode */ }
	}
	function read(k, def) {
		try {
			const raw = localStorage.getItem(key(k));
			return raw === null ? def : JSON.parse(raw);
		} catch (e) { return def; }
	}

	// ── period presets ──────────────────────────────────────────────────────
	const PERIODS = [
		"Today", "Yesterday", "This Week", "This Month", "Last Month",
		"Last 30 Days", "Last 90 Days", "This Quarter", "This Year", "Last Year", "Custom",
	];

	function range(preset) {
		const D = frappe.datetime, today = D.get_today();
		const monthStart = (d) => d.slice(0, 7) + "-01";
		switch (preset) {
			case "Today": return [today, today];
			case "Yesterday": return [D.add_days(today, -1), D.add_days(today, -1)];
			case "This Week": return [D.week_start(), today];
			case "Last Month": {
				const s = monthStart(D.add_months(today, -1));
				return [s, D.month_end(s)];
			}
			case "Last 30 Days": return [D.add_days(today, -29), today];
			case "Last 90 Days": return [D.add_days(today, -89), today];
			case "This Quarter": {
				const m = parseInt(today.slice(5, 7), 10);
				const qs = m - ((m - 1) % 3);
				return [`${today.slice(0, 4)}-${String(qs).padStart(2, "0")}-01`, today];
			}
			case "This Year": return [`${today.slice(0, 4)}-01-01`, today];
			case "Last Year": {
				const y = parseInt(today.slice(0, 4), 10) - 1;
				return [`${y}-01-01`, `${y}-12-31`];
			}
			case "This Month":
			default: return [monthStart(today), today];
		}
	}

	// Field shorthands — every dashboard picks the ones it actually filters on.
	const F = {
		period(def) {
			return { fieldname: "period", label: __("Period"), fieldtype: "Select",
				options: PERIODS.join("\n"), default: def || "This Month", width: "125px" };
		},
		from() { return { fieldname: "from_date", label: __("From"), fieldtype: "Date", only_custom: 1 }; },
		to() { return { fieldname: "to_date", label: __("To"), fieldtype: "Date", only_custom: 1 }; },
		location() {
			return { fieldname: "location", label: __("Location"), fieldtype: "Select",
				options: ["", "MAHARASHTRA", "GUJARAT", "CHENNAI"].join("\n"), width: "130px" };
		},
		salesPerson() {
			return { fieldname: "sales_person", label: __("Sales Person"), fieldtype: "Link", options: "User" };
		},
		link(doctype, fieldname, label, extra) {
			return Object.assign({ fieldname: fieldname || frappe.scrub(doctype), label: label || __(doctype),
				fieldtype: "Link", options: doctype }, extra || {});
		},
		select(fieldname, label, options, def) {
			return { fieldname, label, fieldtype: "Select", options: options.join("\n"), default: def || "" };
		},
	};

	/**
	 * Build the filter bar. Values persist per user+page and are restored on
	 * the next visit, so a factory user who always looks at Gujarat does not
	 * re-pick it every morning.
	 *
	 *   const f = ibDash.filters(page, {
	 *       key: "main-dash",
	 *       fields: [ibDash.F.period(), ibDash.F.location(), ibDash.F.salesPerson()],
	 *       onChange: () => this.refresh(),
	 *   });
	 *   f.get()  →  { period, from_date, to_date, location, sales_person }
	 */
	function filters(page, spec) {
		spec = spec || {};
		const skey = "filters:" + (spec.key || page.title || "dash");
		const saved = spec.remember === false ? {} : (read(skey, {}) || {});
		const fields = (spec.fields || []).slice();
		const hasPeriod = fields.some((f) => f.fieldname === "period");
		if (hasPeriod && !fields.some((f) => f.fieldname === "from_date")) {
			const at = fields.findIndex((f) => f.fieldname === "period") + 1;
			fields.splice(at, 0, F.from(), F.to());
		}

		$(page.page_form).addClass("ib-page-form ib-dash-form").removeClass("hide");
		const controls = {};
		let ready = false, timer = null;

		const fire = () => {
			if (!ready) return;
			clearTimeout(timer);
			timer = setTimeout(() => {
				if (spec.remember !== false) store(skey, raw());
				spec.onChange && spec.onChange(get());
			}, spec.debounce === undefined ? 250 : spec.debounce);
		};

		fields.forEach((f) => {
			const df = Object.assign({}, f);
			const only_custom = df.only_custom;
			delete df.only_custom;
			delete df.width;
			if (saved[df.fieldname] !== undefined && saved[df.fieldname] !== null && saved[df.fieldname] !== "")
				df.default = saved[df.fieldname];
			df.change = fire;
			const ctl = page.add_field(df);
			controls[f.fieldname] = ctl;
			ctl._only_custom = only_custom;
			if (df.default !== undefined && df.default !== "" && ctl.set_value) ctl.set_value(df.default);
			if (f.width) ctl.$wrapper.css("min-width", f.width);
		});

		const syncCustom = () => {
			if (!hasPeriod) return;
			const custom = (controls.period && controls.period.get_value()) === "Custom";
			["from_date", "to_date"].forEach((k) => {
				if (controls[k]) controls[k].$wrapper.toggleClass("hide", !custom);
			});
		};
		if (hasPeriod && controls.period) {
			// Seed the custom boxes so switching to Custom starts from the
			// period the user was already looking at instead of two blanks.
			const seed = range(controls.period.get_value());
			if (controls.from_date && !controls.from_date.get_value()) controls.from_date.set_value(saved.from_date || seed[0]);
			if (controls.to_date && !controls.to_date.get_value()) controls.to_date.set_value(saved.to_date || seed[1]);
			controls.period.$input && controls.period.$input.on("change", syncCustom);
			syncCustom();
		}

		function raw() {
			const out = {};
			Object.keys(controls).forEach((k) => { out[k] = controls[k].get_value() || ""; });
			return out;
		}

		function get() {
			const out = raw();
			if (hasPeriod) {
				if (out.period === "Custom") {
					out.from_date = out.from_date || range("This Month")[0];
					out.to_date = out.to_date || frappe.datetime.get_today();
				} else {
					const r = range(out.period);
					out.from_date = r[0]; out.to_date = r[1];
				}
			}
			Object.keys(out).forEach((k) => { if (out[k] === "Select") out[k] = ""; });
			return out;
		}

		function set(vals) {
			Object.keys(vals || {}).forEach((k) => {
				if (controls[k] && controls[k].set_value) controls[k].set_value(vals[k]);
			});
			syncCustom();
		}

		function reset() {
			ready = false;
			(spec.fields || []).forEach((f) => {
				if (controls[f.fieldname] && controls[f.fieldname].set_value)
					controls[f.fieldname].set_value(f.default || "");
			});
			syncCustom();
			ready = true;
			store(skey, raw());
			spec.onChange && spec.onChange(get());
		}

		page.add_menu_item(__("Reset filters"), reset, true);
		ready = true;
		return { get, set, raw, reset, controls, label: () => describe(get(), hasPeriod) };
	}

	function describe(v, hasPeriod) {
		const bits = [];
		if (hasPeriod && v.period) {
			bits.push(v.period === "Custom"
				? `${frappe.datetime.str_to_user(v.from_date)} – ${frappe.datetime.str_to_user(v.to_date)}`
				: v.period);
		}
		["location", "sales_person", "department", "branch", "warehouse", "customer", "item_group"].forEach((k) => {
			if (v[k]) bits.push(v[k]);
		});
		return bits.join(" · ");
	}

	/**
	 * Card personalisation. Cards are plain elements carrying data-card="id"
	 * inside `container`; the saved order/visibility is applied on every
	 * render and edited from the page menu.
	 *
	 *   this.cards = ibDash.personalise(page, {
	 *       key: "main-dash",
	 *       cards: [{ id: "kpis", label: "KPI row", locked: 1 }, { id: "trend", label: "Revenue trend" }],
	 *       container: () => this.$el.find("[data-cards]"),
	 *   });
	 *   ... after each render:  this.cards.apply();
	 */
	function personalise(page, spec) {
		const skey = "cards:" + (spec.key || page.title || "dash");
		const all = spec.cards || [];
		let saved = read(skey, null);

		const def = () => ({ order: all.map((c) => c.id), hidden: all.filter((c) => c.off).map((c) => c.id) });
		if (!saved || !Array.isArray(saved.order)) saved = def();
		// Cards added by a later release must show up for users who already
		// have a saved layout, instead of silently vanishing.
		all.forEach((c) => { if (saved.order.indexOf(c.id) === -1) saved.order.push(c.id); });
		saved.order = saved.order.filter((id) => all.some((c) => c.id === id));
		saved.hidden = (saved.hidden || []).filter((id) => all.some((c) => c.id === id && !c.locked));

		function apply() {
			const $c = spec.container ? spec.container() : null;
			if (!$c || !$c.length) return;
			saved.order.forEach((id) => {
				const $el = $c.find(`> [data-card="${id}"]`);
				if ($el.length) $c.append($el);
			});
			$c.find("> [data-card]").each(function () {
				$(this).toggleClass("hide", saved.hidden.indexOf($(this).data("card")) !== -1);
			});
		}

		function dialog() {
			const d = new frappe.ui.Dialog({
				title: __("Customise layout"),
				fields: [{ fieldtype: "HTML", fieldname: "list" }],
				primary_action_label: __("Save"),
				primary_action: () => {
					saved.order = d.$wrapper.find(".ib-pz-row").map(function () { return $(this).data("id"); }).get();
					saved.hidden = d.$wrapper.find(".ib-pz-row").filter(function () {
						return !$(this).find("input").prop("checked");
					}).map(function () { return $(this).data("id"); }).get();
					store(skey, saved);
					d.hide();
					spec.onApply ? spec.onApply() : apply();
				},
				secondary_action_label: __("Reset"),
				secondary_action: () => {
					saved = def();
					store(skey, saved);
					d.hide();
					spec.onApply ? spec.onApply() : apply();
				},
			});
			const rows = saved.order.map((id) => {
				const c = all.find((x) => x.id === id) || { id, label: id };
				const on = saved.hidden.indexOf(id) === -1;
				return `<div class="ib-pz-row" data-id="${ibUI.esc(id)}">
					<label><input type="checkbox" ${on ? "checked" : ""} ${c.locked ? "disabled" : ""}> ${ibUI.esc(c.label || id)}</label>
					<span class="acts"><button class="up" title="${__("Move up")}">&uarr;</button><button class="dn" title="${__("Move down")}">&darr;</button></span>
				</div>`;
			}).join("");
			d.fields_dict.list.$wrapper.html(
				`<div class="ib-pz">${rows}<div class="ib-pz-hint">${__("Untick to hide a card. Arrows change the order.")}</div></div>`);
			d.$wrapper.on("click", ".ib-pz-row .up", function () {
				const $r = $(this).closest(".ib-pz-row"), $p = $r.prev(".ib-pz-row");
				if ($p.length) $r.insertBefore($p);
				return false;
			});
			d.$wrapper.on("click", ".ib-pz-row .dn", function () {
				const $r = $(this).closest(".ib-pz-row"), $n = $r.next(".ib-pz-row");
				if ($n.length) $r.insertAfter($n);
				return false;
			});
			d.show();
		}

		page.add_menu_item(__("Customise layout…"), dialog, true);
		return {
			apply, dialog,
			hidden: () => saved.hidden.slice(),
			order: () => saved.order.slice(),
			visible: (id) => saved.hidden.indexOf(id) === -1,
		};
	}

	// ── house defaults for every frappe.Chart on the desk ─────────────────
	// The pages built before this kit call frappe.Chart directly. Rather than
	// rewrite each one, give the constructor the two defaults they all want:
	// short y-axis numbers (a full ₹1,68,73,067 label is clipped by the chart
	// gutter) and truncated legends. Anything a caller sets itself wins.
	function patchChart() {
		if (!window.frappe || !frappe.Chart || frappe.Chart._ibPatched) return !!(window.frappe && frappe.Chart);
		const Orig = frappe.Chart;
		const Patched = function (parent, options) {
			options = options || {};
			options.axisOptions = Object.assign({ shortenYAxisNumbers: 1 }, options.axisOptions || {});
			if (options.truncateLegends === undefined) options.truncateLegends = 1;
			return new Orig(parent, options);
		};
		Patched.prototype = Orig.prototype;
		Patched._ibPatched = true;
		Patched._ibOriginal = Orig;
		frappe.Chart = Patched;
		return true;
	}
	if (!patchChart()) {
		// frappe-charts can arrive with a later bundle — retry briefly, then stop.
		let tries = 0;
		const t = setInterval(() => {
			if (patchChart() || ++tries > 20) clearInterval(t);
		}, 500);
	}

	window.ibDash = { chart, palette, TONE, filters, F, PERIODS, range, personalise, store, read, describe, isDark };
})();
