frappe.pages["ib-trace"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Traceability"),
		single_column: true,
	});
	new IBTrace(page);
};

frappe.pages["ib-trace"].on_page_show = function (wrapper) {
	const inst = wrapper.__ibtrace;
	if (inst) setTimeout(() => inst.$input && inst.$input.focus(), 60);
};

const IB_TRACE_CSS = `
.ibt-wrap{max-width:820px;margin:0 auto;padding:8px 0 60px}
.ibt-search{position:relative;margin:14px 0 8px}
.ibt-search input{width:100%;height:52px;padding:0 46px 0 44px;font-size:15px;font-family:var(--font-stack,inherit);
  border:1.5px solid var(--border-color);border-radius:12px;background:var(--control-bg);color:var(--text-color);
  transition:border-color .15s,box-shadow .15s;outline:none}
.ibt-search input:focus{border-color:var(--primary);box-shadow:0 0 0 3px color-mix(in srgb,var(--primary) 18%,transparent)}
.ibt-search .ibt-ico{position:absolute;left:14px;top:16px;opacity:.5;pointer-events:none}
.ibt-search .ibt-go{position:absolute;right:8px;top:8px;height:36px;width:36px;border:0;border-radius:9px;
  background:var(--primary);color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center}
.ibt-hint{color:var(--text-muted);font-size:12px;margin-bottom:18px}
.ibt-chip{display:inline-block;padding:3px 9px;margin:2px 4px 2px 0;font-size:11px;border-radius:20px;
  border:1px solid var(--border-color);color:var(--text-muted);cursor:pointer;background:var(--card-bg)}
.ibt-chip:hover{border-color:var(--primary);color:var(--text-color)}
.ibt-chain{position:relative;padding-left:30px}
.ibt-chain::before{content:"";position:absolute;left:11px;top:14px;bottom:14px;width:2px;background:var(--border-color)}
.ibt-node{position:relative;margin:0 0 14px}
.ibt-node::before{content:"";position:absolute;left:-24px;top:16px;width:14px;height:14px;border-radius:50%;
  background:var(--card-bg);border:2px solid var(--border-color)}
.ibt-node.is-focus::before{border-color:var(--primary);background:var(--primary);box-shadow:0 0 0 4px color-mix(in srgb,var(--primary) 20%,transparent)}
.ibt-card{border:1px solid var(--border-color);border-radius:12px;background:var(--card-bg);padding:14px 16px;
  transition:border-color .15s,transform .15s}
.ibt-node.is-focus .ibt-card{border-color:var(--primary)}
.ibt-card:hover{transform:translateY(-1px)}
.ibt-card-h{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.ibt-card-h .ibt-kind{font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--text-muted);font-weight:600}
.ibt-card-h .ibt-title{font-weight:650;font-size:14px}
.ibt-card-h .ibt-title a{color:var(--text-color)}
.ibt-kv{display:grid;grid-template-columns:130px 1fr;gap:3px 10px;font-size:12.5px}
.ibt-kv .k{color:var(--text-muted)}
.ibt-pill{display:inline-block;padding:2px 8px;border-radius:20px;font-size:11px;font-weight:600;border:1px solid transparent}
.ibt-pill.rm{background:color-mix(in srgb,#f59e0b 15%,transparent);color:#b45309}
.ibt-pill.fg{background:color-mix(in srgb,#10b981 15%,transparent);color:#047857}
.ibt-pill.ok{background:color-mix(in srgb,#10b981 15%,transparent);color:#047857}
.ibt-serials{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.ibt-sn{font-family:var(--font-stack-mono,ui-monospace,monospace);font-size:11px;padding:4px 8px;border-radius:7px;
  border:1px solid var(--border-color);background:var(--control-bg);cursor:pointer;transition:border-color .12s}
.ibt-sn:hover{border-color:var(--primary)}
.ibt-sn.is-focus{border-color:var(--primary);background:color-mix(in srgb,var(--primary) 10%,transparent)}
.ibt-wo-row{display:flex;align-items:center;gap:8px;padding:5px 0;font-size:12.5px;border-top:1px dashed var(--border-color)}
.ibt-wo-row:first-child{border-top:0}
.ibt-stage{font-size:10px;font-weight:700;padding:2px 6px;border-radius:5px;background:var(--control-bg);border:1px solid var(--border-color)}
.ibt-skel{height:80px;border-radius:12px;background:linear-gradient(90deg,var(--control-bg) 25%,var(--card-bg) 37%,var(--control-bg) 63%);
  background-size:400% 100%;animation:ibtsk 1.2s ease-in-out infinite;margin-bottom:12px}
@keyframes ibtsk{0%{background-position:100% 0}100%{background-position:-100% 0}}
.ibt-empty{text-align:center;color:var(--text-muted);padding:50px 20px}
.ibt-empty svg{opacity:.3;margin-bottom:10px}
`;

class IBTrace {
	constructor(page) {
		this.page = page;
		page.wrapper.__ibtrace = this;
		if (!document.getElementById("ibt-css")) {
			const s = document.createElement("style");
			s.id = "ibt-css";
			s.textContent = IB_TRACE_CSS;
			document.head.appendChild(s);
		}
		this._build();
		const qid = frappe.utils.get_url_arg("id");
		if (qid) {
			this.$input.value = qid;
			this.run(qid);
		}
	}

	_build() {
		this.$wrap = $(`<div class="ibt-wrap"></div>`).appendTo(this.page.main);
		this.$wrap.html(`
			<div class="ibt-search">
				<span class="ibt-ico">${feather("search")}</span>
				<input type="text" placeholder="${__("Scan or paste a Batch, Work Order, or Serial…")}" autocomplete="off" spellcheck="false">
				<button class="ibt-go" title="${__("Trace")}">${feather("arrow-right")}</button>
			</div>
			<div class="ibt-hint">${__("Forward and backward genealogy — imported material → production → finished units.")}</div>
			<div class="ibt-result"></div>
		`);
		this.$input = this.$wrap.find("input")[0];
		this.$result = this.$wrap.find(".ibt-result");
		this.$wrap.find(".ibt-go").on("click", () => this.run(this.$input.value));
		$(this.$input).on("keydown", (e) => {
			if (e.key === "Enter") this.run(this.$input.value);
		});
		setTimeout(() => this.$input.focus(), 80);
	}

	run(id) {
		id = (id || "").trim();
		if (!id) return;
		if (frappe.get_route()[0] === "ib-trace") frappe.set_route("ib-trace", { id });
		this.$result.html(`<div class="ibt-chain">${'<div class="ibt-skel"></div>'.repeat(3)}</div>`);
		frappe.call({
			method: "instabiz.overrides.traceability.get_trace",
			args: { trace_id: id },
			callback: (r) => this.render(r.message || {}, id),
			error: () => this.renderEmpty(__("Nothing found for “{0}”.", [frappe.utils.escape_html(id)])),
		});
	}

	renderEmpty(msg) {
		this.$result.html(`<div class="ibt-empty">${feather("package", 40)}<div>${msg}</div></div>`);
	}

	renderDN(d) {
		const dn = d.delivery_note || {};
		let html = node("Delivery Note", "truck", link("Delivery Note", dn.name), kv([
			["Customer", esc(dn.customer_name)],
			["Date", fmtDate(dn.posting_date)],
			["Status", esc(dn.status)],
			["Warehouse", esc(dn.set_warehouse)],
		]), "is-focus");
		(d.lines || []).forEach((ln) => {
			const b = ln.source_batch;
			const src = ln.source;
			const body = kv([
				["Item", esc(ln.item_code)],
				["Qty", ln.qty],
				["Sales Order", link("Sales Order", ln.sales_order)],
				["Source (RM) Batch", b ? link("IB Batch", b.name) : `<span class="text-muted">${__("not linked")}</span>`],
				["Supplier Lot", b ? esc(b.supplier_lot) : ""],
				["From", src ? `${esc(src.source_type)} ${link(src.dt, src.name)}` : ""],
				["Produced Serials", (ln.serials || []).length || ""],
			]);
			html += node(`Line — ${ln.item_code}`, "box", "", body, "");
		});
		this.$result.html(`<div class="ibt-chain">${html}</div>`);
	}

	render(d, queried) {
		if (!d.kind) return this.renderEmpty(__("No result."));
		if (d.kind === "item") {
			return this.$result.html(
				`<div class="ibt-empty">${feather("tag", 40)}<div>${frappe.utils.escape_html(d.message || "")}</div>
				 <div style="margin-top:8px">${link("Item", d.item)}</div></div>`,
			);
		}
		if (d.kind === "delivery_note") return this.renderDN(d);

		const nodes = [];
		const focus = (k) => (queried && k === queried ? "is-focus" : "");
		const b = d.batch || d.source_batch;
		const src = d.source;
		const serials = d.serials || d.siblings || [];

		if (src) {
			const isPR = src.source_type === "Purchase Receipt";
			nodes.push(node(src.source_type || "Container Import", isPR ? "shopping-cart" : "truck",
				link(src.dt || "IB Container Import", src.name), kv([
					["Container No", esc(src.container_no)],
					["Supplier", esc(src.supplier)],
					[isPR ? "Received" : "Import Date", fmtDate(src.import_date)],
					["Warehouse", esc(src.warehouse)],
				]), focus(src.name)));
		}

		if (b) {
			const kind = b.kind || "";
			nodes.push(node(
				d.kind === "work_order" || d.kind === "serial" ? "Source (RM) Batch" : "Batch",
				"layers",
				link("IB Batch", b.name),
				kv([
					["Kind", kind ? `<span class="ibt-pill ${kind === "Finished Good" ? "fg" : "rm"}">${esc(kind)}</span>` : ""],
					["Item", esc(b.item)],
					["Qty", b.qty],
					["Supplier Lot", esc(b.supplier_lot)],
					["Received", fmtDate(b.received_date)],
					["GSM", b.gsm || ""],
					["Width (mm)", b.width_mm || ""],
				]),
				focus(b.name),
			));
		}

		if (d.kind === "serial" && d.fg_batch) {
			nodes.push(node("FG Batch", "layers", link("IB Batch", d.fg_batch.name), kv([
				["Kind", `<span class="ibt-pill fg">${esc(d.fg_batch.kind || "Finished Good")}</span>`],
				["Work Order", link("IB Work Order", d.fg_batch.work_order)],
			]), focus(d.fg_batch.name)));
		}

		const wos = d.work_orders || (d.stages ? d.stages : []);
		if (d.kind === "work_order" && d.work_order) {
			const w = d.work_order;
			nodes.push(node("Work Order", "settings", link("IB Work Order", w.name), kv([
				["Item", esc(w.item_code)],
				["Current Stage", `<span class="ibt-stage">${esc(w.stage)}</span>`],
				["Status", esc(w.status)],
				["Sales Order", link("Sales Order", w.sales_order)],
				["Serials Produced", w.produced_serials || 0],
			]) + woRows(d.stages, w.item_code), focus(w.name)));
		} else if (wos.length) {
			nodes.push(node("Work Orders", "settings", `${wos.length} ${__("stage(s)")}`, woRows(wos), ""));
		}

		if (d.kind === "serial" && d.work_order) {
			const w = d.work_order;
			nodes.push(node("Work Order", "settings", link("IB Work Order", w.name), kv([
				["Final Stage", `<span class="ibt-stage">${esc(w.stage)}</span>`],
				["Sales Order", link("Sales Order", w.sales_order)],
			]), focus(w.name)));
		}

		if (d.kind === "serial" && d.serial) {
			const s = d.serial;
			nodes.push(node("Finished Unit", "box", `<span style="font-family:var(--font-stack-mono,monospace)">${esc(s.serial_no || s.name)}</span>`, kv([
				["Box / Roll No", s.box_no],
				["Status", `<span class="ibt-pill ok">${esc(s.status || "In Stock")}</span>`],
				["Produced On", fmtDT(s.produced_on)],
				["Size", [s.width_mm ? `${Math.round(s.width_mm)}mm` : "", s.length_mtr ? `${Math.round(s.length_mtr)}m` : ""].filter(Boolean).join(" × ")],
				["Delivery Note", link("Delivery Note", s.delivery_note)],
				["Customer", link("Customer", s.customer)],
			]), "is-focus"));
		}

		if (serials.length && d.kind !== "serial") {
			nodes.push(node("Finished Units", "box", `${serials.length} ${__("serial(s)")}`,
				`<div class="ibt-serials">${serials.map((s) =>
					`<span class="ibt-sn" data-sn="${esc(s.serial_no || s.name)}">${esc((s.serial_no || s.name).split("::").slice(-2).join("::"))}</span>`,
				).join("")}</div>`, ""));
		} else if (d.kind === "serial" && serials.length > 1) {
			nodes.push(node("Same Production Run", "box", `${serials.length} ${__("units")}`,
				`<div class="ibt-serials">${serials.map((s) => {
					const nm = s.serial_no || s.name;
					return `<span class="ibt-sn ${nm === (d.serial.serial_no || d.serial.name) ? "is-focus" : ""}" data-sn="${esc(nm)}">${esc(nm.split("::").slice(-1)[0])}</span>`;
				}).join("")}</div>`, ""));
		}

		if (d.deliveries && d.deliveries.length) {
			nodes.push(node("Shipped Direct (no production)", "truck",
				`${d.deliveries.length} ${__("delivery note(s)")}`,
				`<div class="ibt-kv">${d.deliveries.map((x) =>
					`<div class="k">${link("Delivery Note", x.delivery_note)}</div>` +
					`<div>${esc(x.customer)} · ${esc(x.qty)} · ${esc((x.items || []).join(", "))}</div>`,
				).join("")}</div>`, ""));
		}

		if (d.sales_orders && d.sales_orders.length) {
			nodes.push(node("Sales Orders", "shopping-cart", `${d.sales_orders.length} ${__("downstream")}`,
				`<div>${d.sales_orders.map((s) => link("Sales Order", s)).join(" &nbsp; ")}</div>`, ""));
		}

		this.$result.html(`<div class="ibt-chain">${nodes.join("")}</div>`);
		this.$result.find(".ibt-sn").on("click", (e) => {
			const sn = e.currentTarget.getAttribute("data-sn");
			this.$input.value = sn;
			this.run(sn);
		});
	}
}

// ── helpers ────────────────────────────────────────────────────────────────
function esc(v) {
	return v === undefined || v === null ? "" : frappe.utils.escape_html(String(v));
}
function link(dt, name) {
	if (!name) return "";
	return `<a href="/app/${frappe.router.slug(dt)}/${encodeURIComponent(name)}">${esc(name)}</a>`;
}
function fmtDate(d) {
	return d ? frappe.datetime.str_to_user(d) : "";
}
function fmtDT(d) {
	return d ? frappe.datetime.str_to_user(d) : "";
}
function kv(rows) {
	const body = rows
		.filter((r) => r && r[1] !== undefined && r[1] !== null && r[1] !== "")
		.map(([k, v]) => `<div class="k">${esc(k)}</div><div>${v}</div>`)
		.join("");
	return `<div class="ibt-kv">${body}</div>`;
}
function woRows(wos, itemCode) {
	if (!wos || !wos.length) return "";
	return wos
		.map((w) => `<div class="ibt-wo-row">
			<span class="ibt-stage">${esc(w.stage)}</span>
			<span>${link("IB Work Order", w.name)}</span>
			<span style="color:var(--text-muted)">${esc(w.status || "")}</span>
			<span style="margin-left:auto;color:var(--text-muted);font-size:11px">${w.completed_at ? fmtDT(w.completed_at) : w.started_at ? fmtDT(w.started_at) : ""}</span>
		</div>`)
		.join("");
}
function node(kind, icon, title, bodyHtml, focusCls) {
	return `<div class="ibt-node ${focusCls || ""}">
		<div class="ibt-card">
			<div class="ibt-card-h">${feather(icon)}<span class="ibt-kind">${esc(kind)}</span><span class="ibt-title">${title}</span></div>
			${bodyHtml || ""}
		</div>
	</div>`;
}
function feather(name, size = 15) {
	const P = {
		search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
		"arrow-right": '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
		truck: '<path d="M14 18V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v11a1 1 0 0 0 1 1h2"/><path d="M15 18H9"/><path d="M19 18h2a1 1 0 0 0 1-1v-3.65a1 1 0 0 0-.22-.62l-3.48-4.35A1 1 0 0 0 17.52 8H14"/><circle cx="17" cy="18" r="2"/><circle cx="7" cy="18" r="2"/>',
		layers: '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
		settings: '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
		box: '<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>',
		"shopping-cart": '<circle cx="8" cy="21" r="1"/><circle cx="19" cy="21" r="1"/><path d="M2.05 2.05h2l2.66 12.42a2 2 0 0 0 2 1.58h9.78a2 2 0 0 0 1.95-1.57l1.65-7.43H5.12"/>',
		package: '<path d="M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73z"/><path d="M12 22V12"/><polyline points="3.29 7 12 12 20.71 7"/><path d="m7.5 4.27 9 5.15"/>',
		tag: '<path d="M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586 1.414l8.704 8.704a2.426 2.426 0 0 0 3.42 0l6.58-6.58a2.426 2.426 0 0 0 0-3.42z"/><circle cx="7.5" cy="7.5" r=".5" fill="currentColor"/>',
	};
	return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${P[name] || P.package}</svg>`;
}
