frappe.pages["ib-stock-scan"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({ parent: wrapper, title: __("Scan Stock"), single_column: true });
	wrapper.ib_stock_scan = new IBStockScan(wrapper);
};
frappe.pages["ib-stock-scan"].on_page_show = function (wrapper) {
	if (wrapper.ib_stock_scan) setTimeout(() => wrapper.ib_stock_scan.$bc.focus(), 60);
};

const IB_SS_CSS = `
.ibss-wrap{max-width:560px;margin:0 auto;padding:10px 0 60px}
.ibss-scan{position:relative;margin:12px 0 16px}
.ibss-scan input{width:100%;height:56px;padding:0 16px 0 46px;font-size:16px;
  font-family:var(--font-stack-mono,ui-monospace,monospace);letter-spacing:.02em;
  border:1.5px solid var(--border-color);border-radius:14px;background:var(--control-bg);color:var(--text-color);
  outline:none;transition:border-color .15s,box-shadow .15s}
.ibss-scan input:focus{border-color:var(--primary);box-shadow:0 0 0 4px color-mix(in srgb,var(--primary) 16%,transparent)}
.ibss-scan .i{position:absolute;left:15px;top:18px;opacity:.5}
.ibss-card{border:1px solid var(--border-color);border-radius:14px;background:var(--card-bg);padding:16px;margin-bottom:14px}
.ibss-card.kind-serial{border-color:color-mix(in srgb,#10b981 45%,var(--border-color))}
.ibss-card.kind-batch{border-color:color-mix(in srgb,#f59e0b 45%,var(--border-color))}
.ibss-h{display:flex;align-items:flex-start;gap:10px}
.ibss-h .ibss-badge{font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;
  padding:3px 8px;border-radius:6px;background:var(--control-bg);border:1px solid var(--border-color);color:var(--text-muted)}
.ibss-name{font-weight:650;font-size:15px;line-height:1.3}
.ibss-sub{color:var(--text-muted);font-size:12px;margin-top:2px;word-break:break-all}
.ibss-mono{font-family:var(--font-stack-mono,monospace);font-size:12px}
.ibss-pill{display:inline-block;padding:2px 8px;border-radius:20px;font-size:11px;font-weight:600}
.ibss-pill.g{background:color-mix(in srgb,#10b981 15%,transparent);color:#047857}
.ibss-pill.a{background:color-mix(in srgb,#f59e0b 15%,transparent);color:#b45309}
.ibss-bars{margin:12px 0}
.ibss-bar{display:flex;align-items:center;gap:8px;font-size:12px;margin:4px 0}
.ibss-bar .wh{min-width:120px;color:var(--text-muted)}
.ibss-bar .track{flex:1;height:7px;border-radius:5px;background:var(--control-bg);overflow:hidden}
.ibss-bar .fill{height:100%;background:var(--primary);border-radius:5px}
.ibss-bar .q{min-width:56px;text-align:right;font-weight:600}
.ibss-qtyrow{display:flex;gap:8px;align-items:flex-end;margin-top:12px}
.ibss-qtyrow .fld{flex:1}
.ibss-qtyrow label{font-size:11px;color:var(--text-muted);display:block;margin-bottom:3px}
.ibss-qtyrow input{width:100%;height:40px;border:1px solid var(--border-color);border-radius:9px;padding:0 10px;background:var(--control-bg);color:var(--text-color)}
.ibss-actions{display:flex;gap:8px;margin-top:12px}
.ibss-actions button{flex:1;height:42px;border:0;border-radius:10px;font-weight:600;cursor:pointer;font-size:13px}
.ibss-add{background:#10b981;color:#fff}
.ibss-ded{background:#ef4444;color:#fff}
.ibss-trace{display:inline-flex;align-items:center;gap:6px;margin-top:12px;padding:9px 12px;border-radius:10px;
  background:color-mix(in srgb,var(--primary) 10%,transparent);color:var(--primary);font-weight:600;font-size:13px;text-decoration:none;border:1px solid color-mix(in srgb,var(--primary) 30%,transparent)}
.ibss-trace:hover{background:color-mix(in srgb,var(--primary) 16%,transparent)}
.ibss-feed{border:1px solid var(--border-color);border-radius:14px;background:var(--card-bg);padding:14px 16px}
.ibss-feed h6{font-weight:650;font-size:12px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.06em;margin:0 0 8px}
.ibss-fitem{display:flex;align-items:center;gap:8px;font-size:12px;padding:6px 0;border-top:1px dashed var(--border-color)}
.ibss-fitem:first-of-type{border-top:0}
.ibss-fitem .t{color:var(--text-muted);min-width:52px}
.ibss-fitem .tag{font-size:10px;font-weight:700;padding:1px 6px;border-radius:5px;background:var(--control-bg);border:1px solid var(--border-color)}
.ibss-muted{color:var(--text-muted);font-size:12px}
`;

class IBStockScan {
	constructor(wrapper) {
		this.page = wrapper.page;
		this._resolved = null;
		this._feed = [];
		if (!document.getElementById("ibss-css")) {
			const s = document.createElement("style");
			s.id = "ibss-css";
			s.textContent = IB_SS_CSS;
			document.head.appendChild(s);
		}
		this._build();
	}

	_build() {
		this.$wrap = $(`<div class="ibss-wrap"></div>`).appendTo(this.page.main);
		this.$wrap.html(`
			<div class="ibss-scan">
				<span class="i">${ico("scan")}</span>
				<input type="text" placeholder="${__("Scan barcode, batch or serial…")}" autocomplete="off" spellcheck="false">
			</div>
			<div class="ibss-result"></div>
			<div class="ibss-feed"><h6>${__("This session")}</h6><div class="ibss-feed-list ibss-muted">${__("No scans yet")}</div></div>
		`);
		this.$bc = this.$wrap.find(".ibss-scan input")[0];
		this.$result = this.$wrap.find(".ibss-result");
		this.$feedList = this.$wrap.find(".ibss-feed-list");

		this.wh = frappe.ui.form.make_control({
			df: { fieldtype: "Link", options: "Warehouse", label: __("Warehouse"), fieldname: "wh", reqd: 1 },
			render_input: true,
			parent: $('<div style="display:none">').appendTo(this.$wrap),
		});
		const lastWh = localStorage.getItem("ib_stock_scan_warehouse");
		if (lastWh) this.wh.set_value(lastWh);

		$(this.$bc).on("keydown", (e) => {
			if (e.key === "Enter") {
				e.preventDefault();
				this._resolve(this.$bc.value.trim());
			}
		});
		setTimeout(() => this.$bc.focus(), 80);
	}

	_resolve(code) {
		if (!code) return;
		frappe.call({
			method: "instabiz.overrides.stock_scan.resolve_barcode",
			args: { barcode: code },
			freeze: true,
			callback: (r) => {
				if (!r.message) return;
				this._resolved = { code, ...r.message };
				this._renderResult(r.message);
			},
			error: () => {
				this._resolved = null;
				this.$result.html(`<div class="ibss-card"><div class="ibss-muted">${__("Unknown code")} <span class="ibss-mono">${frappe.utils.escape_html(code)}</span></div></div>`);
				this.$bc.value = "";
				this.$bc.focus();
			},
		});
	}

	_traceBtn(id) {
		return `<a class="ibss-trace" href="/app/ib-trace?id=${encodeURIComponent(id)}" target="_blank">${ico("git-branch")} ${__("Open Traceability")}</a>`;
	}

	_renderResult(m) {
		if (m.kind === "serial") {
			this.$result.html(`
				<div class="ibss-card kind-serial">
					<div class="ibss-h">
						<span class="ibss-badge">${__("Finished Unit")}</span>
						<div style="flex:1">
							<div class="ibss-name ibss-mono">${esc(m.serial)}</div>
							<div class="ibss-sub">${esc(m.item_name || m.item_code)} · ${__("Box")} ${esc(m.box_no)} · <span class="ibss-pill g">${esc(m.serial_status || "In Stock")}</span></div>
						</div>
					</div>
					<div style="margin-top:10px;font-size:12px;color:var(--text-muted)">
						${m.fg_batch ? `${__("FG Batch")}: <span class="ibss-mono">${esc(m.fg_batch)}</span><br>` : ""}
						${m.work_order ? `${__("Work Order")}: ${esc(m.work_order)} &nbsp; ` : ""}
						${m.sales_order ? `${__("SO")}: ${esc(m.sales_order)}` : ""}
					</div>
					${this._traceBtn(m.serial)}
				</div>`);
			this._done();
			return;
		}
		if (m.kind === "batch") {
			this.$result.html(`
				<div class="ibss-card kind-batch">
					<div class="ibss-h">
						<span class="ibss-badge">${__("Batch")}</span>
						<div style="flex:1">
							<div class="ibss-name">${esc(m.item_name || m.item_code)}</div>
							<div class="ibss-sub"><span class="ibss-mono">${esc(m.batch)}</span> · <span class="ibss-pill a">${esc(m.batch_kind || "Batch")}</span>${m.container_no ? ` · ${__("Container")} ${esc(m.container_no)}` : ""}</div>
						</div>
					</div>
					${m.supplier_lot ? `<div style="margin-top:8px;font-size:12px;color:var(--text-muted)">${__("Supplier Lot")}: ${esc(m.supplier_lot)}</div>` : ""}
					${this._traceBtn(m.batch)}
				</div>`);
			this._done();
			return;
		}

		// item
		const bal = m.balances || [];
		const max = Math.max(1, ...bal.map((b) => b.actual_qty));
		const bars = bal.length
			? `<div class="ibss-bars">${bal
					.map((b) => `<div class="ibss-bar"><span class="wh">${esc(shortWh(b.warehouse))}</span>
						<span class="track"><span class="fill" style="width:${(b.actual_qty / max) * 100}%"></span></span>
						<span class="q">${b.actual_qty}</span></div>`)
					.join("")}</div>`
			: `<div class="ibss-muted" style="margin:8px 0">${__("No stock in any warehouse")}</div>`;

		this.$result.html(`
			<div class="ibss-card kind-item">
				<div class="ibss-h">
					<span class="ibss-badge">${__("Item")}</span>
					<div style="flex:1"><div class="ibss-name">${esc(m.item_name || m.item_code)}</div>
					<div class="ibss-sub ibss-mono">${esc(m.item_code)}</div></div>
				</div>
				${bars}
				<div class="ibss-qtyrow">
					<div class="fld ibss-wh-mount"></div>
					<div style="width:96px"><label>${__("Qty")}</label><input type="number" class="ibss-qty" min="0" step="any" value="1"></div>
				</div>
				<div class="ibss-actions">
					<button class="ibss-add">${ico("plus")} ${__("Add")}</button>
					<button class="ibss-ded">${ico("minus")} ${__("Deduct")}</button>
				</div>
			</div>`);
		this.$result.find(".ibss-wh-mount").append(this.wh.$wrapper.show());
		this.$result.find(".ibss-add").on("click", () => this._adjust("Add"));
		this.$result.find(".ibss-ded").on("click", () => this._adjust("Deduct"));
	}

	_done() {
		this.$bc.value = "";
		this.$bc.focus();
	}

	_adjust(dir) {
		if (!this._resolved || this._resolved.kind === "batch" || this._resolved.kind === "serial") {
			frappe.msgprint(__("Scan a SKU barcode to add or deduct stock."));
			return;
		}
		const warehouse = this.wh.get_value();
		const qty = flt(this.$result.find(".ibss-qty").val());
		if (!warehouse) return frappe.msgprint(__("Select a warehouse"));
		if (!qty || qty <= 0) return frappe.msgprint(__("Enter a qty greater than 0"));
		localStorage.setItem("ib_stock_scan_warehouse", warehouse);
		frappe.call({
			method: "instabiz.overrides.stock_scan.adjust_stock",
			args: { barcode: this._resolved.code, warehouse, qty, direction: dir },
			freeze: true,
			callback: (r) => {
				if (!r.message) return;
				frappe.show_alert({
					message: __("{0} {1} × {2} → {3}", [dir, qty, this._resolved.item_code, r.message.new_qty]),
					indicator: dir === "Add" ? "green" : "orange",
				});
				this._feed.unshift({ t: frappe.datetime.now_time(), tag: dir, txt: `${qty} × ${this._resolved.item_code}`, se: r.message.stock_entry });
				this._renderFeed();
				this._resolved = null;
				this.$result.html("");
				this._done();
			},
		});
	}

	_renderFeed() {
		if (!this._feed.length) return;
		this.$feedList.removeClass("ibss-muted").html(
			this._feed
				.map((f) => `<div class="ibss-fitem"><span class="t">${f.t}</span><span class="tag">${f.tag}</span>
					<span>${esc(f.txt)}</span>
					<a style="margin-left:auto" href="/app/stock-entry/${f.se}" target="_blank">${esc(f.se)}</a></div>`)
				.join(""),
		);
	}
}

function esc(v) {
	return v === undefined || v === null ? "" : frappe.utils.escape_html(String(v));
}
function shortWh(w) {
	return (w || "").replace(" - IB", "");
}
function ico(name) {
	const P = {
		scan: '<path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/><path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/><path d="M7 12h10"/>',
		plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
		minus: '<path d="M5 12h14"/>',
		"git-branch": '<line x1="6" x2="6" y1="3" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/>',
	};
	return `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${P[name] || ""}</svg>`;
}
