frappe.pages["ib-dispatch-scan"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({ parent: wrapper, title: __("Dispatch Scan"), single_column: true });
	wrapper.ib_dispatch_scan = new IBDispatchScan(wrapper);
};

frappe.pages["ib-dispatch-scan"].on_page_hide = function (wrapper) {
	if (wrapper.ib_dispatch_scan) wrapper.ib_dispatch_scan._stopCamera();
};

// ─────────────────────────────────────────────────────────────────────────────
// Mobile-camera scan → Delivery Note. Scan FG serial/batch labels with the
// phone's back camera, build a cart, then create (and optionally submit) a
// Delivery Note from it. Real stock deduction happens on DN submit — see
// instabiz.overrides.dispatch_scan / delivery_note._stamp_scanned_dispatch_units.

const IBDS_CSS = `
.ibds-wrap{max-width:520px;margin:0 auto;padding:8px 0 140px}
.ibds-card{border:1px solid var(--border-color);border-radius:14px;background:var(--card-bg);padding:14px;margin-bottom:12px}
.ibds-field{margin-bottom:10px}
.ibds-field label{font-size:11px;color:var(--text-muted);display:block;margin-bottom:3px;font-weight:600;text-transform:uppercase;letter-spacing:.04em}
.ibds-camwrap{position:relative;border-radius:16px;overflow:hidden;background:#000;margin-bottom:12px}
.ibds-video{width:100%;display:block;max-height:52vh;object-fit:cover}
.ibds-reticle{position:absolute;inset:14%;border:2.5px solid color-mix(in srgb,var(--primary) 80%,white);
  border-radius:16px;pointer-events:none;box-shadow:0 0 0 999px rgba(0,0,0,.28)}
.ibds-laser{position:absolute;left:16%;right:16%;top:50%;height:3px;transform:translateY(-50%);
  background-image:radial-gradient(circle,#ff3b30 1.6px,transparent 1.7px);
  background-size:11px 3px;background-repeat:repeat-x;border-radius:2px;
  box-shadow:0 0 8px 1.5px rgba(255,59,48,.85),0 0 2px rgba(255,59,48,1);
  animation:ibds-laser-blink 1s ease-in-out infinite;pointer-events:none}
@keyframes ibds-laser-blink{0%,100%{opacity:1}50%{opacity:.2}}
@media (prefers-reduced-motion: reduce){.ibds-laser{animation:none;opacity:.85}}
.ibds-camoff{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;
  min-height:200px;border:1.5px dashed var(--border-color);border-radius:16px;color:var(--text-muted)}
.ibds-camtoolbar{display:flex;justify-content:center;gap:10px;margin:-6px 0 12px}
.ibds-btn{height:46px;padding:0 18px;border-radius:12px;border:1px solid var(--border-color);
  background:var(--control-bg);color:var(--text-color);font-weight:600;font-size:14px;display:inline-flex;
  align-items:center;gap:8px;cursor:pointer}
.ibds-btn.primary{background:var(--primary);border-color:var(--primary);color:#fff}
.ibds-btn:disabled{opacity:.45;cursor:not-allowed}
.ibds-manual{display:flex;gap:8px;margin-bottom:12px}
.ibds-manual input{flex:1;height:44px;border:1px solid var(--border-color);border-radius:10px;padding:0 12px;
  background:var(--control-bg);color:var(--text-color);font-family:var(--font-stack-mono,monospace);font-size:14px}
.ibds-flash{animation:ibds-flash .5s ease}
@keyframes ibds-flash{0%{background:color-mix(in srgb,#10b981 25%,var(--card-bg))}100%{background:var(--card-bg)}}
.ibds-cart-row{display:flex;align-items:center;gap:10px;padding:9px 0;border-bottom:1px solid var(--border-color)}
.ibds-cart-row:last-child{border-bottom:none}
.ibds-cart-name{font-weight:600;font-size:14px}
.ibds-cart-sub{font-size:11.5px;color:var(--text-muted)}
.ibds-cart-qty{font-weight:700;font-size:14px;min-width:70px;text-align:right}
.ibds-cart-rm{border:none;background:none;color:var(--text-muted);cursor:pointer;padding:6px}
.ibds-muted{color:var(--text-muted);font-size:13px;padding:10px 2px}
.ibds-footer{position:fixed;left:0;right:0;bottom:0;background:var(--card-bg);border-top:1px solid var(--border-color);
  padding:10px 16px calc(10px + env(safe-area-inset-bottom));z-index:50}
.ibds-footer-inner{max-width:520px;margin:0 auto}
.ibds-footer-sum{display:flex;justify-content:space-between;font-size:12.5px;color:var(--text-muted);margin-bottom:8px}
.ibds-footer-row{display:flex;gap:10px;align-items:center}
.ibds-submitnow{display:flex;align-items:center;gap:6px;font-size:12.5px;color:var(--text-muted);white-space:nowrap}
.ibds-cta{flex:1;height:50px;border-radius:12px;border:none;background:var(--primary);color:#fff;font-weight:700;
  font-size:15px}
.ibds-cta:disabled{opacity:.4}
.ibds-success{text-align:center;padding:20px 10px}
.ibds-success .ico{color:#10b981;margin-bottom:8px}
`;

function ibdsIco(name, size = 15) {
	const P = {
		camera: '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/><circle cx="12" cy="13" r="3"/>',
		x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
		"check-circle": '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="m9 11 3 3L22 4"/>',
	};
	return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${P[name] || ""}</svg>`;
}

class IBDispatchScan {
	constructor(wrapper) {
		this.page = wrapper.page;
		this.cart = []; // [{item_code, item_name, kind, unit_qty, serial_no|batch, stock_uom}]
		this._seen = new Set(); // serial_no/batch already in cart, dedupe client-side
		this._camBusyUntil = 0;
		if (!$("#ibds-style").length) $(`<style id="ibds-style">${IBDS_CSS}</style>`).appendTo("head");
		this._build();
	}

	_build() {
		this.$wrap = $(`<div class="ibds-wrap"></div>`).appendTo(this.page.main);
		this.$wrap.html(`
			<div class="ibds-card">
				<div class="ibds-field"><label>${__("Customer")}</label><div class="ibds-customer"></div></div>
				<div class="ibds-field"><label>${__("Sales Order (optional)")}</label><div class="ibds-so"></div></div>
			</div>

			<div class="ibds-camwrap" style="display:none">
				<video class="ibds-video" playsinline muted></video>
				<div class="ibds-reticle"></div>
				<div class="ibds-laser"></div>
			</div>
			<div class="ibds-camoff">
				${ibdsIco("camera", 22)}
				<div>${__("Camera is off")}</div>
			</div>
			<div class="ibds-camtoolbar">
				<button class="ibds-btn primary ibds-camstart">${ibdsIco("camera", 15)} ${__("Start Camera")}</button>
				<button class="ibds-btn ibds-camstop" style="display:none">${ibdsIco("x", 15)} ${__("Stop Camera")}</button>
			</div>
			<div class="ibds-manual">
				<input type="text" class="ibds-manual-input" placeholder="${__("...or type/scan a code")}" autocomplete="off" spellcheck="false">
				<button class="ibds-btn ibds-manual-go">${__("Add")}</button>
			</div>

			<div class="ibds-card">
				<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
					<strong>${__("Scanned")}</strong><span class="ibds-cart-count ibds-muted" style="padding:0"></span>
				</div>
				<div class="ibds-cart-list"><div class="ibds-muted">${__("No units scanned yet")}</div></div>
			</div>

			<div class="ibds-footer">
				<div class="ibds-footer-inner">
					<div class="ibds-footer-sum"><span class="ibds-sum-units">0 units</span><span class="ibds-sum-qty">0 qty</span></div>
					<div class="ibds-footer-row">
						<label class="ibds-submitnow"><input type="checkbox" class="ibds-submitnow-cb"> ${__("Submit now")}</label>
						<button class="ibds-cta" disabled>${__("Create Delivery Note")}</button>
					</div>
				</div>
			</div>
		`);

		this.customer = frappe.ui.form.make_control({
			df: { fieldtype: "Link", options: "Customer", fieldname: "customer", placeholder: __("Select customer") },
			render_input: true,
			parent: this.$wrap.find(".ibds-customer"),
		});
		this.so = frappe.ui.form.make_control({
			df: {
				fieldtype: "Link", options: "Sales Order", fieldname: "sales_order",
				placeholder: __("Select sales order"),
				get_query: () => ({
					filters: { docstatus: 1, customer: this.customer.get_value() || "" },
				}),
			},
			render_input: true,
			parent: this.$wrap.find(".ibds-so"),
		});

		this.$wrap.find(".ibds-camstart").on("click", () => this._startCamera());
		this.$wrap.find(".ibds-camstop").on("click", () => this._stopCamera());
		this.$wrap.find(".ibds-manual-go").on("click", () => this._submitManual());
		this.$wrap.find(".ibds-manual-input").on("keydown", (e) => {
			if (e.key === "Enter") { e.preventDefault(); this._submitManual(); }
		});
		this.$wrap.find(".ibds-cta").on("click", () => this._createDN());
	}

	_submitManual() {
		const $i = this.$wrap.find(".ibds-manual-input");
		const v = $i.val().trim();
		if (!v) return;
		$i.val("");
		this._handleCode(v);
	}

	_stripUrl(v) {
		const m = String(v || "").match(/[?&]id=([^&\s]+)/);
		return m ? decodeURIComponent(m[1]) : String(v || "").trim();
	}

	async _startCamera() {
		if (!this.customer.get_value()) {
			frappe.msgprint(__("Pick a customer first."));
			return;
		}
		if (!("BarcodeDetector" in window)) {
			frappe.msgprint(
				__("This browser can't scan via camera (needs Chrome on Android, or a Chromium browser). Use the code field below with a handheld scanner instead."),
			);
			return;
		}
		try {
			this._det = new window.BarcodeDetector({
				formats: ["qr_code", "code_128", "code_39", "ean_13", "codabar"],
			});
			this._stream = await navigator.mediaDevices.getUserMedia({
				video: { facingMode: "environment" },
			});
			const v = this.$wrap.find(".ibds-video")[0];
			v.srcObject = this._stream;
			await v.play();
			this.$wrap.find(".ibds-camwrap").show();
			this.$wrap.find(".ibds-camoff").hide();
			this.$wrap.find(".ibds-camstart").hide();
			this.$wrap.find(".ibds-camstop").show();
			this._camLoop(v);
		} catch (e) {
			frappe.msgprint(__("Could not open the camera: {0}", [e.message || e]));
			this._stopCamera();
		}
	}

	async _camLoop(v) {
		if (!this._stream) return;
		try {
			if (Date.now() > this._camBusyUntil) {
				const hits = await this._det.detect(v);
				if (hits && hits.length) {
					const code = this._stripUrl(hits[0].rawValue);
					if (navigator.vibrate) navigator.vibrate(60);
					this._camBusyUntil = Date.now() + 1500; // debounce re-detecting the same held-up label
					this._handleCode(code);
				}
			}
		} catch (_e) {
			/* transient decode error — keep looping */
		}
		this._camRAF = requestAnimationFrame(() => this._camLoop(v));
	}

	_stopCamera() {
		if (this._camRAF) cancelAnimationFrame(this._camRAF);
		this._camRAF = null;
		if (this._stream) {
			this._stream.getTracks().forEach((t) => t.stop());
			this._stream = null;
		}
		this.$wrap.find(".ibds-camwrap").hide();
		this.$wrap.find(".ibds-camoff").show();
		this.$wrap.find(".ibds-camstop").hide();
		this.$wrap.find(".ibds-camstart").show();
	}

	_handleCode(code) {
		if (!code) return;
		const key = this._stripUrl(code);
		if (this._seen.has(key)) {
			if (navigator.vibrate) navigator.vibrate([50, 40, 50]);
			frappe.show_alert({ message: __("Already scanned: {0}", [key]), indicator: "orange" });
			return;
		}
		frappe.call({
			method: "instabiz.overrides.dispatch_scan.scan_into_cart",
			args: { barcode: key },
			callback: (r) => {
				if (!r.message) return;
				this._addToCart(key, r.message);
			},
			error: (r) => {
				if (navigator.vibrate) navigator.vibrate([80, 50, 80]);
				frappe.show_alert({
					message: (r && r._server_messages) ? __("Rejected — see message") : __("Could not resolve that code"),
					indicator: "red",
				});
			},
		});
	}

	_addToCart(key, m) {
		this._seen.add(key);
		this.cart.push({
			key,
			item_code: m.item_code,
			item_name: m.item_name,
			kind: m.kind,
			unit_qty: flt(m.unit_qty || m.batch_qty || 1),
			stock_uom: m.stock_uom,
			serial_no: m.kind === "serial" ? m.serial : null,
			batch: m.kind === "batch" ? m.batch : null,
		});
		if (navigator.vibrate) navigator.vibrate(30);
		this._renderCart();
	}

	_removeFromCart(idx) {
		const row = this.cart[idx];
		if (row) this._seen.delete(row.key);
		this.cart.splice(idx, 1);
		this._renderCart();
	}

	_renderCart() {
		const $list = this.$wrap.find(".ibds-cart-list");
		if (!this.cart.length) {
			$list.html(`<div class="ibds-muted">${__("No units scanned yet")}</div>`);
		} else {
			$list.html(this.cart.map((r, i) => `
				<div class="ibds-cart-row ibds-flash">
					<div style="flex:1;min-width:0">
						<div class="ibds-cart-name">${frappe.utils.escape_html(r.item_name || r.item_code)}</div>
						<div class="ibds-cart-sub">${frappe.utils.escape_html(r.serial_no || r.batch || "")}</div>
					</div>
					<div class="ibds-cart-qty">${format_number(r.unit_qty, null, 2)} ${frappe.utils.escape_html(r.stock_uom || "")}</div>
					<button class="ibds-cart-rm" data-i="${i}">${ibdsIco("x", 13)}</button>
				</div>
			`).join(""));
			$list.find(".ibds-cart-rm").on("click", (e) => this._removeFromCart(parseInt($(e.currentTarget).data("i"), 10)));
		}
		this.$wrap.find(".ibds-cart-count").text(this.cart.length ? `${this.cart.length} ${__("scanned")}` : "");
		const totalQty = this.cart.reduce((s, r) => s + flt(r.unit_qty), 0);
		const items = new Set(this.cart.map((r) => r.item_code)).size;
		this.$wrap.find(".ibds-sum-units").text(`${this.cart.length} ${__("units")} · ${items} ${__("SKU")}${items === 1 ? "" : "s"}`);
		this.$wrap.find(".ibds-sum-qty").text(`${format_number(totalQty, null, 2)} ${__("total qty")}`);
		this.$wrap.find(".ibds-cta").prop("disabled", !this.cart.length);
	}

	_createDN() {
		const customer = this.customer.get_value();
		if (!customer) return frappe.msgprint(__("Pick a customer first."));
		if (!this.cart.length) return;
		const submitNow = this.$wrap.find(".ibds-submitnow-cb").is(":checked");
		const lines = this.cart.map((r) => ({
			item_code: r.item_code, kind: r.kind, unit_qty: r.unit_qty,
			serial_no: r.serial_no, batch: r.batch,
		}));
		this.$wrap.find(".ibds-cta").prop("disabled", true).text(__("Creating…"));
		frappe.call({
			method: "instabiz.overrides.dispatch_scan.build_delivery_note",
			args: {
				customer,
				lines: JSON.stringify(lines),
				sales_order: this.so.get_value() || null,
				submit: submitNow ? 1 : 0,
			},
			freeze: true,
			callback: (r) => {
				if (!r.message) return;
				this._stopCamera();
				this._showSuccess(r.message);
			},
			error: () => {
				this.$wrap.find(".ibds-cta").prop("disabled", false).text(__("Create Delivery Note"));
			},
		});
	}

	_showSuccess(m) {
		this.$wrap.find(".ibds-camwrap, .ibds-camoff, .ibds-camtoolbar, .ibds-manual, .ibds-card, .ibds-footer").remove();
		$(`
			<div class="ibds-success">
				${ibdsIco("check-circle", 40)}
				<h4>${m.submitted ? __("Delivery Note submitted") : __("Delivery Note created (Draft)")}</h4>
				<p class="ibds-muted">${frappe.utils.escape_html(m.delivery_note)}</p>
				<div style="display:flex;gap:10px;justify-content:center;margin-top:16px">
					<button class="ibds-btn ibds-open">${__("Open")}</button>
					<button class="ibds-btn primary ibds-again">${__("Scan Another")}</button>
				</div>
			</div>
		`).appendTo(this.$wrap);
		this.$wrap.find(".ibds-open").on("click", () => frappe.set_route("Form", "Delivery Note", m.delivery_note));
		this.$wrap.find(".ibds-again").on("click", () => this._reset());
	}

	_reset() {
		this.cart = [];
		this._seen = new Set();
		this.$wrap.remove();
		this._build();
	}
}
