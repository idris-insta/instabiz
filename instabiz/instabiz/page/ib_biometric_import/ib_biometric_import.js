frappe.pages["ib-biometric-import"].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({
		parent: wrapper,
		title: "Biometric Attendance Import",
		single_column: true,
	});
	wrapper._ib_bio = new IBBiometricImport(wrapper);
};

// ─────────────────────────────────────────────────────────────────────────────

class IBBiometricImport {
	constructor(wrapper) {
		this.wrapper    = wrapper;
		this.page       = wrapper.page;
		this._csv_text  = null;
		this._headers   = [];
		this._col_map   = {};   // {id_col, datetime_col, date_col, time_col, type_col}
		this._inject_styles();
		this._build_layout();
		this._bind_setup_tab();
	}

	_inject_styles() {
		if (document.getElementById("ib-bio-styles")) return;
		const s = document.createElement("style");
		s.id = "ib-bio-styles";
		s.textContent = `
.ib-bio-wrap { padding: 16px; max-width: 900px; }
.ib-bio-tabs { display:flex; gap:4px; margin-bottom:14px; }
.ib-bio-tab  { padding:6px 14px; border-radius:6px; font-size:12px; font-weight:500;
  cursor:pointer; border:1px solid var(--border-color); background:var(--card-bg); color:var(--text-muted); }
.ib-bio-tab.active { background:var(--ib-primary); color:#fff; border-color:var(--ib-primary); }
.ib-bio-card { background:var(--card-bg); border:1px solid var(--border-color); border-radius:8px; padding:16px; margin-bottom:14px; }
.ib-bio-drop { border:2px dashed var(--border-color); border-radius:8px; padding:40px 20px;
  text-align:center; cursor:pointer; color:var(--text-muted); transition:border-color .2s; }
.ib-bio-drop:hover, .ib-bio-drop.drag-over { border-color:var(--ib-primary); color:var(--ib-primary); }
.ib-bio-drop input[type=file] { display:none; }
.ib-bio-col-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:12px; }
.ib-bio-col-label { font-size:11px; font-weight:600; color:var(--text-muted); margin-bottom:4px; text-transform:uppercase; letter-spacing:.4px; }
.ib-bio-col-sel { width:100%; font-size:12px; padding:5px 8px; border:1px solid var(--border-color); border-radius:5px; background:var(--card-bg); color:var(--text-color); }
.ib-bio-table { width:100%; border-collapse:collapse; font-size:12px; }
.ib-bio-table th { padding:7px 8px; text-align:left; font-size:11px; font-weight:600; color:var(--text-muted); border-bottom:1px solid var(--border-color); }
.ib-bio-table td { padding:7px 8px; border-bottom:1px solid var(--border-color); }
.ib-bio-table tr:last-child td { border-bottom:none; }
.ib-bio-table tr:hover td { background:var(--bg-color); }
.ib-bio-badge { display:inline-block; padding:2px 7px; border-radius:10px; font-size:10px; font-weight:600; }
.ib-bio-badge--ok  { background:#d1fae5; color:#065f46; }
.ib-bio-badge--err { background:#fee2e2; color:#991b1b; }
.ib-bio-badge--warn{ background:#fef3c7; color:#92400e; }
.ib-bio-badge--in  { background:#dbeafe; color:#1e40af; }
.ib-bio-badge--out { background:#ede9fe; color:#5b21b6; }
.ib-bio-result { background:var(--card-bg); border:1px solid var(--border-color); border-radius:8px; padding:20px; text-align:center; }
.ib-bio-result-num { font-size:32px; font-weight:800; color:var(--ib-primary); }
.ib-bio-result-lbl { font-size:11px; color:var(--text-muted); text-transform:uppercase; }
.ib-bio-result-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-bottom:16px; }
		`;
		document.head.appendChild(s);
	}

	_build_layout() {
		const $pc = $(this.wrapper).find(".page-content");
		this.$wrap = $(`<div class="ib-bio-wrap"></div>`).appendTo($pc);
		this.$wrap.html(`
			<div class="ib-bio-tabs">
				<button class="ib-bio-tab active" data-tab="import">Import</button>
				<button class="ib-bio-tab" data-tab="employees">Employee Mapping</button>
			</div>
			<div id="ib-bio-content"></div>
		`);
		this.$wrap.find(".ib-bio-tab").on("click", (e) => {
			const tab = $(e.currentTarget).data("tab");
			this.$wrap.find(".ib-bio-tab").removeClass("active");
			$(e.currentTarget).addClass("active");
			if (tab === "import") this._bind_setup_tab();
			else this._render_employees_tab();
		});
	}

	_bind_setup_tab() {
		const $c = this.$wrap.find("#ib-bio-content");
		$c.html(`
			<div class="ib-bio-card">
				<div style="font-size:13px;font-weight:600;margin-bottom:10px">Step 1 — Upload Biometric CSV</div>
				<div style="font-size:11px;color:var(--text-muted);margin-bottom:12px">
					Supports ZKTeco, eSSL, and generic biometric formats.<br>
					Tab-separated or comma-separated. Auto-detects columns.
				</div>
				<div class="ib-bio-drop" id="ib-bio-drop">
					<svg width="40" height="40" fill="none" stroke="#adb5bd" stroke-width="1.5" viewBox="0 0 24 24" style="margin-bottom:8px">
						<path d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M16 12l-4-4-4 4M12 8v8"/>
					</svg>
					<div style="font-size:13px;font-weight:600">Drag &amp; drop CSV here, or click to browse</div>
					<div style="font-size:11px;color:var(--text-muted);margin-top:4px">Exported from biometric device</div>
					<input type="file" id="ib-bio-file-input" accept=".csv,.txt,.xls,.xlsx">
				</div>
			</div>
			<div id="ib-bio-mapping" style="display:none">
				<div class="ib-bio-card">
					<div style="font-size:13px;font-weight:600;margin-bottom:10px">Step 2 — Column Mapping</div>
					<div style="font-size:11px;color:var(--text-muted);margin-bottom:8px">
						Columns auto-detected. Adjust if needed.
					</div>
					<div class="ib-bio-col-grid" id="ib-bio-col-grid"></div>
					<div style="margin-top:14px;display:flex;gap:8px">
						<button class="btn btn-sm btn-default" id="ib-bio-preview-btn">Preview</button>
					</div>
				</div>
			</div>
			<div id="ib-bio-preview" style="display:none">
				<div class="ib-bio-card">
					<div style="font-size:13px;font-weight:600;margin-bottom:10px">Step 3 — Preview</div>
					<div id="ib-bio-preview-content"></div>
					<div style="margin-top:14px;display:flex;gap:8px;align-items:center">
						<button class="btn btn-sm btn-primary" id="ib-bio-import-btn">Import All Matched</button>
						<span id="ib-bio-import-status" style="font-size:12px;color:var(--text-muted)"></span>
					</div>
				</div>
			</div>
			<div id="ib-bio-result" style="display:none"></div>
		`);

		const $drop = $c.find("#ib-bio-drop");
		const $input = $c.find("#ib-bio-file-input");

		$drop.on("click", () => $input.trigger("click"));
		$drop.on("dragover", (e) => { e.preventDefault(); $drop.addClass("drag-over"); });
		$drop.on("dragleave", () => $drop.removeClass("drag-over"));
		$drop.on("drop", (e) => {
			e.preventDefault();
			$drop.removeClass("drag-over");
			const file = e.originalEvent.dataTransfer.files[0];
			if (file) this._read_file(file);
		});
		$input.on("change", () => {
			const file = $input[0].files[0];
			if (file) this._read_file(file);
		});
	}

	_read_file(file) {
		const reader = new FileReader();
		reader.onload = (e) => {
			this._csv_text = e.target.result;
			this._detect_columns();
		};
		reader.readAsText(file);
	}

	_detect_columns() {
		frappe.call({
			method: "instabiz.instabiz.page.ib_biometric_import.ib_biometric_import.detect_columns",
			args: { csv_text: this._csv_text },
			callback: (r) => {
				if (!r.message) return;
				this._headers = r.message.headers || [];
				this._build_col_map_ui(r.message);
				this.$wrap.find("#ib-bio-mapping").show();
				this.$wrap.find("#ib-bio-preview").hide();
				this.$wrap.find("#ib-bio-result").hide();
			},
		});
	}

	_best_match(headers, ...candidates) {
		for (const c of candidates) {
			const h = headers.find(h => h.toLowerCase().replace(/[\s_]/g, "").includes(c.replace(/[\s_]/g, "")));
			if (h) return h;
		}
		return "";
	}

	_build_col_map_ui(detected) {
		const h = detected.headers;
		const opts = `<option value="">(none)</option>` + h.map(c => `<option value="${frappe.utils.escape_html(c)}">${frappe.utils.escape_html(c)}</option>`).join("");

		const sel = (id, label, ...candidates) => {
			const def = this._best_match(h, ...candidates);
			return `
				<div>
					<div class="ib-bio-col-label">${label}</div>
					<select class="ib-bio-col-sel" id="${id}">${opts.replace(`value="${frappe.utils.escape_html(def)}"`, `value="${frappe.utils.escape_html(def)}" selected`)}</select>
				</div>`;
		};

		this.$wrap.find("#ib-bio-col-grid").html(`
			${sel("ib-col-id",       "Employee ID / User ID",        "userid", "empid", "employeeid", "id", "no")}
			${sel("ib-col-datetime", "Combined Date+Time (optional)", "datetime", "checktime", "punchtime", "timestamp")}
			${sel("ib-col-date",     "Date (if separate)",            "date", "attdate", "punchdate")}
			${sel("ib-col-time",     "Time (if separate)",            "time", "punchtime", "checktime")}
			${sel("ib-col-type",     "IN / OUT Type",                 "status", "type", "punchtype", "logtype", "inout")}
		`);

		this.$wrap.find("#ib-bio-preview-btn").off("click").on("click", () => this._run_preview());
	}

	_get_col_map() {
		return {
			id_col:       this.$wrap.find("#ib-col-id").val() || null,
			datetime_col: this.$wrap.find("#ib-col-datetime").val() || null,
			date_col:     this.$wrap.find("#ib-col-date").val() || null,
			time_col:     this.$wrap.find("#ib-col-time").val() || null,
			type_col:     this.$wrap.find("#ib-col-type").val() || null,
		};
	}

	_run_preview() {
		const map = this._get_col_map();
		if (!map.id_col) {
			frappe.show_alert({ message: "Select the Employee ID column first", indicator: "orange" });
			return;
		}
		frappe.show_alert({ message: "Parsing…", indicator: "blue" });

		frappe.call({
			method: "instabiz.instabiz.page.ib_biometric_import.ib_biometric_import.preview_biometric",
			args: { csv_text: this._csv_text, ...map },
			callback: (r) => {
				if (!r.message) return;
				this._preview_data = r.message;
				this._render_preview(r.message);
				this.$wrap.find("#ib-bio-preview").show();
				this.$wrap.find("#ib-bio-result").hide();
			},
			error: () => frappe.show_alert({ message: "Preview failed — check error log", indicator: "red" }),
		});
	}

	_render_preview(data) {
		const { rows, total, unmatched_count, unmatched_ids } = data;
		const matched = rows.filter(r => r.matched);
		const $pc = this.$wrap.find("#ib-bio-preview-content");

		let warn = "";
		if (unmatched_count) {
			warn = `<div style="background:#fef3c7;border:1px solid #fcd34d;border-radius:6px;padding:10px;margin-bottom:12px;font-size:12px">
				<strong>⚠ ${unmatched_count} biometric ID(s) not matched to any employee:</strong>
				<div style="margin-top:4px;color:#92400e">${unmatched_ids.join(", ")}</div>
				<div style="margin-top:6px;font-size:11px">Go to "Employee Mapping" tab to assign biometric IDs to employees.</div>
			</div>`;
		}

		const rowHtml = rows.map(r => `
			<tr>
				<td>${frappe.utils.escape_html(r.biometric_id)}</td>
				<td>${frappe.utils.escape_html(r.raw_name || "—")}</td>
				<td>${r.matched
					? `<a href="#" class="ib-bio-emp-link" data-emp="${frappe.utils.escape_html(r.employee)}">${frappe.utils.escape_html(r.employee)}</a>`
					: `<span class="ib-bio-badge ib-bio-badge--err">Not found</span>`
				}</td>
				<td>${r.date_str}</td>
				<td>${(r.datetime_str || "").slice(11, 16)}</td>
				<td><span class="ib-bio-badge ${r.log_type === 'IN' ? 'ib-bio-badge--in' : 'ib-bio-badge--out'}">${r.log_type}</span></td>
			</tr>
		`).join("");

		$pc.html(`
			${warn}
			<div style="font-size:12px;margin-bottom:8px;color:var(--text-muted)">
				Showing ${Math.min(rows.length, 50)} of ${total} rows &nbsp;·&nbsp;
				<span style="color:${unmatched_count ? '#dc2626' : '#10b981'}">
					${total - unmatched_count} matched, ${unmatched_count} unmatched
				</span>
			</div>
			<div style="overflow-x:auto">
			<table class="ib-bio-table">
				<thead><tr>
					<th>Bio ID</th><th>Name (device)</th><th>ERPNext Employee</th>
					<th>Date</th><th>Time</th><th>Type</th>
				</tr></thead>
				<tbody>${rowHtml}</tbody>
			</table>
			</div>
		`);

		$pc.find(".ib-bio-emp-link").on("click", function (e) {
			e.preventDefault();
			frappe.set_route("Form", "Employee", $(this).data("emp"));
		});

		this.$wrap.find("#ib-bio-import-btn").off("click").on("click", () => {
			if (!matched.length) {
				frappe.show_alert({ message: "No matched rows to import", indicator: "orange" });
				return;
			}
			frappe.confirm(
				`Import ${matched.length} checkin records (${unmatched_count} unmatched will be skipped)?`,
				() => this._run_import()
			);
		});
		this.$wrap.find("#ib-bio-import-status").text(
			`${matched.length} matched row${matched.length !== 1 ? "s" : ""} ready to import`
		);
	}

	_run_import() {
		const map = this._get_col_map();
		frappe.show_alert({ message: "Importing…", indicator: "blue" });

		frappe.call({
			method: "instabiz.instabiz.page.ib_biometric_import.ib_biometric_import.import_biometric",
			args: { csv_text: this._csv_text, ...map },
			callback: (r) => {
				if (!r.message) return;
				this._render_result(r.message);
			},
			error: () => frappe.show_alert({ message: "Import failed — check error log", indicator: "red" }),
		});
	}

	_render_result(res) {
		const $r = this.$wrap.find("#ib-bio-result");
		const errHtml = (res.errors || []).length
			? `<div style="margin-top:12px;font-size:11px;color:#dc2626">
				${res.errors.map(e => `${frappe.utils.escape_html(e.biometric_id)} @ ${e.time}: ${frappe.utils.escape_html(e.error)}`).join("<br>")}
			   </div>`
			: "";

		$r.html(`
			<div class="ib-bio-result">
				<div style="font-size:15px;font-weight:600;margin-bottom:16px">Import Complete</div>
				<div class="ib-bio-result-grid">
					<div><div class="ib-bio-result-num" style="color:#10b981">${res.created}</div><div class="ib-bio-result-lbl">Created</div></div>
					<div><div class="ib-bio-result-num" style="color:var(--text-muted)">${res.skipped}</div><div class="ib-bio-result-lbl">Skipped (dup)</div></div>
					<div><div class="ib-bio-result-num" style="color:#f59e0b">${res.unmatched}</div><div class="ib-bio-result-lbl">Unmatched</div></div>
					<div><div class="ib-bio-result-num" style="color:#dc2626">${(res.errors || []).length}</div><div class="ib-bio-result-lbl">Errors</div></div>
				</div>
				${errHtml}
				<div style="display:flex;gap:8px;justify-content:center;margin-top:16px">
					<button class="btn btn-sm btn-default" id="ib-bio-new-import">Import Another File</button>
					<a href="/app/employee-checkin" class="btn btn-sm btn-default">View Employee Checkins →</a>
				</div>
				${res.created ? `<div style="margin-top:12px;font-size:11px;color:var(--text-muted)">
					Run "Process Attendance" in HRMS to convert these checkins to Attendance records,
					or let the HRMS shift attendance cron handle it automatically.</div>` : ""}
			</div>
		`).show();
		this.$wrap.find("#ib-bio-preview").hide();

		$r.find("#ib-bio-new-import").on("click", () => {
			this._csv_text = null;
			this._bind_setup_tab();
		});
	}

	_render_employees_tab() {
		const $c = this.$wrap.find("#ib-bio-content");
		$c.html(`<div class="ib-bio-card"><div style="font-size:12px;color:var(--text-muted)">Loading factory employees…</div></div>`);

		frappe.call({
			method: "instabiz.instabiz.page.ib_biometric_import.ib_biometric_import.get_unmatched_employees",
			callback: (r) => {
				const rows = r.message || [];
				const tbody = rows.map(emp => `
					<tr data-emp="${frappe.utils.escape_html(emp.name)}">
						<td>${frappe.utils.escape_html(emp.employee_name)}</td>
						<td style="font-size:11px;color:var(--text-muted)">${frappe.utils.escape_html(emp.department || "")}</td>
						<td>
							<input class="ib-bio-bid-input" type="text" value="${frappe.utils.escape_html(emp.custom_biometric_id || "")}"
							  placeholder="Device User ID" style="width:120px;font-size:12px;padding:4px 7px;border:1px solid var(--border-color);border-radius:4px">
						</td>
						<td>
							<button class="btn btn-xs btn-default ib-bio-save-bid">Save</button>
						</td>
					</tr>
				`).join("");

				$c.html(`
					<div class="ib-bio-card">
						<div style="font-size:13px;font-weight:600;margin-bottom:6px">Factory Employee → Biometric ID Mapping</div>
						<div style="font-size:11px;color:var(--text-muted);margin-bottom:12px">
							Enter the biometric device User ID for each factory employee.<br>
							This is the numeric ID the device assigned to the person (usually 1–200).
						</div>
						<div style="overflow-x:auto">
						<table class="ib-bio-table">
							<thead><tr><th>Employee Name</th><th>Department</th><th>Biometric Device ID</th><th></th></tr></thead>
							<tbody>${tbody}</tbody>
						</table>
						</div>
					</div>
				`);

				$c.find(".ib-bio-save-bid").on("click", function () {
					const $row = $(this).closest("tr");
					const emp  = $row.data("emp");
					const bid  = $row.find(".ib-bio-bid-input").val().trim();
					frappe.call({
						method: "instabiz.instabiz.page.ib_biometric_import.ib_biometric_import.save_biometric_id",
						args: { employee: emp, biometric_id: bid },
						callback: () => frappe.show_alert({ message: "Saved", indicator: "green" }),
						error: () => frappe.show_alert({ message: "Save failed", indicator: "red" }),
					});
				});
			},
		});
	}
}
