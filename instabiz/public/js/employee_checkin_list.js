/**
 * Employee Checkin — consolidated daily attendance list view.
 * One row per employee showing IN/OUT/work-hours for a selected date.
 */

(function () {
    const API        = "instabiz.overrides.checkin.get_daily_attendance";
    const API_UNDO   = "instabiz.overrides.checkin.undo_attendance";
    const TZ  = "Asia/Kolkata";

    /* ── helpers ──────────────────────────────────────────────────────────── */

    function fmt_time(str) {
        if (!str || str === "—") return "—";
        try {
            return new Date(str).toLocaleTimeString("en-IN", {
                hour: "numeric", minute: "2-digit", hour12: true, timeZone: TZ,
            });
        } catch (e) { return "—"; }
    }

    function fmt_datetime(str) {
        if (!str || str === "—") return "—";
        try {
            const d    = new Date(str);
            const date = d.toLocaleDateString("en-IN", { day: "2-digit", month: "short", timeZone: TZ });
            const time = d.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", hour12: true, timeZone: TZ });
            return `${date}, ${time}`;
        } catch (e) { return "—"; }
    }

    function pill(color, label) {
        if (!label || label === "—") return `<span style="color:#bbb;margin-left:5px;">—</span>`;
        const hex = { blue: "#1572b2", green: "#28a745", orange: "#ff851b", red: "#e74c3c", gray: "#6c757d" }[color] || "#6c757d";
        return `<div style="display:inline-flex;align-items:center;background:${hex}15;color:${hex};border:1px solid ${hex}30;padding:2px 10px;border-radius:12px;font-size:11px;font-weight:600;white-space:nowrap;line-height:1.5;">${label}</div>`;
    }

    /* ── summary cards ────────────────────────────────────────────────────── */

    function render_cards($cards_wrap, summary, s) {
        const cards = [
            { id: null,       label: "Total",     value: summary.present + summary.absent, accent: false },
            { id: "Present",  label: "Present",   value: summary.present,  color: "#28a745" },
            { id: "Absent",   label: "Absent",    value: summary.absent,   color: "#e74c3c" },
            { id: "IN",       label: "Still In",  value: summary.still_in, color: "#1572b2" },
        ];

        $cards_wrap.html(cards.map(c => {
            const active = s.status_filter === c.id;
            const clr    = c.color || "var(--text-color)";
            return `
            <div class="eck-card${active ? " eck-card--active" : ""}" data-status="${c.id || ""}"
                style="cursor:${c.id ? "pointer" : "default"};">
                <div class="eck-card-value" style="color:${clr};">${c.value}</div>
                <div class="eck-card-label">${c.label}</div>
            </div>`;
        }).join(""));

        $cards_wrap.find(".eck-card[data-status]").on("click", function () {
            const id = $(this).data("status") || null;
            if (!id) return;
            s.status_filter = (s.status_filter === id) ? null : id;
            $cards_wrap.find(".eck-card").removeClass("eck-card--active");
            if (s.status_filter) $cards_wrap.find(`.eck-card[data-status="${s.status_filter}"]`).addClass("eck-card--active");
            apply_filter(s);
        });
    }

    /* ── factory / office detection (matches attendance terminal logic) ─────── */

    function is_factory(dept) {
        return (dept || "").toLowerCase().includes("factory");
    }

    /* ── filter + render table ────────────────────────────────────────────── */

    function apply_filter(s) {
        let rows = s.all_rows_data || [];
        const absent_statuses = ["Absent"];
        if (s.status_filter === "Present")  rows = rows.filter(r => !absent_statuses.includes(r.status));
        if (s.status_filter === "Absent")   rows = rows.filter(r => absent_statuses.includes(r.status));
        if (s.status_filter === "IN")       rows = rows.filter(r => r.status === "IN");
        if (s.category === "factory")       rows = rows.filter(r => is_factory(r.department));
        if (s.category === "office")        rows = rows.filter(r => !is_factory(r.department));
        render_table(s.$table_wrap, rows, s.all_rows_data.length, s);
    }

    /* ── data load ────────────────────────────────────────────────────────── */

    function load(listview) {
        const s = listview._eck;
        if (!s) return;

        s.$table_wrap.html(`<div style="padding:30px 0;text-align:center;color:#aaa;">Loading…</div>`);

        frappe.call({
            method: API,
            args: { date: s.date, department: s.dept, search: s.search, limit: 9999, offset: 0 },
            callback: function (r) {
                if (!r || !r.message) return;
                const { data, total, summary, privileged } = r.message;
                s.all_rows_data = data;
                s.status_filter = null;
                s.privileged    = !!privileged;
                render_cards(s.$cards_wrap, summary, s);
                apply_filter(s);
            },
        });
    }

    /* ── table render ─────────────────────────────────────────────────────── */

    function render_table($wrap, data, total, s) {
        const priv  = s && s.privileged;
        const cols  = priv ? 9 : 8;

        const rows = data.map(emp => {
            return `
            <tr style="border-bottom:1px solid var(--border-color);vertical-align:middle;">
                <td style="padding:10px 12px;">
                    <div style="font-weight:600;">${frappe.utils.escape_html(emp.employee_name)}</div>
                    <div style="font-size:11px;color:#888;margin-top:2px;">${frappe.utils.escape_html(emp.employee)}</div>
                </td>
                <td style="padding:10px 12px;font-size:12px;">${frappe.utils.escape_html(emp.department || "—")}</td>
                <td style="padding:10px 12px;font-size:12px;">${frappe.utils.escape_html(emp.designation || "—")}</td>
                <td style="padding:10px 12px;">
                    ${pill({ IN: "blue", OUT: "gray", Present: "green", "Half Day": "orange", Absent: "red" }[emp.status] || "gray", emp.status)}
                </td>
                <td style="padding:10px 12px;">${pill("blue",  fmt_time(emp.in_time))}</td>
                <td style="padding:10px 12px;">${pill("gray",  fmt_time(emp.out_time))}</td>
                <td style="padding:10px 12px;">${pill(emp.work_hours ? "green" : "gray", emp.work_hours || "—")}</td>
                <td style="padding:10px 12px;min-width:150px;">${pill("gray", fmt_datetime(emp.last_in))}</td>
                ${priv ? `<td style="padding:10px 12px;">
                    ${emp.can_undo
                        ? `<button class="eck-undo-btn"
                                data-employee="${frappe.utils.escape_html(emp.employee)}"
                                data-name="${frappe.utils.escape_html(emp.employee_name)}"
                                title="${__("Undo attendance")}">
                                <iconify-icon icon="mdi:undo-variant" width="13"></iconify-icon> ${__("Undo")}
                           </button>`
                        : ""}
                </td>` : ""}
            </tr>`;
        }).join("");

        const empty = `<tr><td colspan="${cols}" style="text-align:center;color:#aaa;padding:50px 0;">No records found</td></tr>`;
        const tbody = rows || empty;

        $wrap.html(`
            <div style="border:1px solid var(--border-color);border-radius:var(--border-radius);overflow:hidden;background:#fff;">
                <table style="width:100%;border-collapse:collapse;font-size:13px;">
                    <thead>
                        <tr style="background:var(--subtle-fg);border-bottom:2px solid var(--border-color);">
                            <th class="eck-th">Employee</th>
                            <th class="eck-th">Department</th>
                            <th class="eck-th">Role</th>
                            <th class="eck-th">Status</th>
                            <th class="eck-th">In</th>
                            <th class="eck-th">Out</th>
                            <th class="eck-th">Work Hours</th>
                            <th class="eck-th">Last In</th>
                            ${priv ? `<th class="eck-th"></th>` : ""}
                        </tr>
                    </thead>
                    <tbody>${tbody}</tbody>
                </table>
            </div>
            <div style="margin-top:8px;font-size:12px;color:var(--text-muted);text-align:right;">
                ${data.length} of ${total} employee${total !== 1 ? "s" : ""}
            </div>`);

        if (priv) {
            $wrap.find(".eck-undo-btn").on("click", function () {
                const employee = $(this).data("employee");
                const name     = $(this).data("name");
                const date     = s.date;
                frappe.confirm(
                    __("Undo attendance for {0} on {1}? Check-in logs will be deleted and any attendance record cancelled.", [name, date]),
                    () => {
                        frappe.call({
                            method: API_UNDO,
                            args: { employee, date },
                            callback: ({ exc }) => {
                                if (!exc) {
                                    frappe.show_alert({ message: __("Undone for {0}", [name]), indicator: "orange" });
                                    load(s.listview);
                                }
                            },
                        });
                    }
                );
            });
        }
    }

    /* ── listview hook ────────────────────────────────────────────────────── */

    frappe.listview_settings["Employee Checkin"] = {
        onload: function (listview) {
            listview._eck = {
                date:          frappe.datetime.get_today(),
                dept:          "",
                search:        "",
                category:      null,
                status_filter: null,
                privileged:    false,
                all_rows_data: [],
                $cards_wrap:   null,
                $table_wrap:   null,
                listview:      listview,
            };

            listview.page.main.find(".standard-filter-section").hide();

            if (!document.getElementById("eck-styles")) {
                const s = document.createElement("style");
                s.id = "eck-styles";
                s.textContent = `
                    .eck-cat-group { display:flex; border:1px solid var(--border-color); border-radius:6px; overflow:hidden; }
                    .eck-cat-btn {
                        padding:4px 14px; font-size:12px; font-weight:500; cursor:pointer;
                        background:var(--card-bg); color:var(--text-muted);
                        border:none; border-right:1px solid var(--border-color);
                        transition:all 0.12s;
                    }
                    .eck-cat-btn:last-child { border-right:none; }
                    .eck-cat-btn--active { background:var(--ib-primary,#d97757); color:#fff; }
                    .eck-card { display:flex;flex-direction:column;align-items:center;padding:12px 20px;background:var(--card-bg);border:1px solid var(--border-color);border-radius:8px;min-width:80px; }
                    .eck-cards { display:flex;gap:10px;padding:12px 15px 4px;flex-wrap:wrap; }
                    .eck-card--active { border-color:var(--ib-primary,#d97757); }
                    .eck-card-value { font-size:22px;font-weight:800;line-height:1; }
                    .eck-card-label { font-size:11px;color:var(--text-muted);margin-top:4px;text-transform:uppercase;letter-spacing:0.4px; }
                    .eck-th { padding:10px 12px;text-align:left;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.4px;white-space:nowrap; }
                    .eck-undo-btn { display:inline-flex;align-items:center;gap:3px;padding:3px 9px;font-size:11px;font-weight:500;cursor:pointer;background:none;border:1px solid var(--border-color);border-radius:4px;color:var(--text-muted);transition:all 0.12s; }
                    .eck-undo-btn:hover { border-color:#e74c3c;color:#e74c3c;background:#e74c3c12; }
                `;
                document.head.appendChild(s);
            }

            listview.set_primary_action = function () {
                listview.page.set_primary_action(
                    `<iconify-icon icon="mdi:refresh" width="14" style="vertical-align:-2px;margin-right:4px;"></iconify-icon>${__("Refresh")}`,
                    function () { load(listview); }
                );
            };
            listview.set_primary_action();

            ib_hide_sidebar();
        },

        refresh: function (listview) {
            listview.page.main.find(".standard-filter-section").hide();

            if (!listview._eck.$table_wrap) {
                const s   = listview._eck;
                const $fl = listview.page.main.find(".frappe-list");

                // Summary cards
                s.$cards_wrap = $(`<div class="eck-cards"></div>`);

                // Filters
                const $sub = $(`
                    <div style="display:flex;gap:8px;padding:10px 15px 12px;flex-wrap:wrap;align-items:center;">
                        <input type="date" class="form-control eck-date"
                            style="height:28px;font-size:12px;width:150px;padding:2px 8px;"
                            value="${s.date}">
                        <div class="eck-cat-group">
                            <button class="eck-cat-btn eck-cat-btn--active" data-cat="">All</button>
                            <button class="eck-cat-btn" data-cat="office">Office</button>
                            <button class="eck-cat-btn" data-cat="factory">Factory</button>
                        </div>
                        <input type="text" class="form-control eck-search"
                            style="height:28px;font-size:12px;width:200px;margin-left:auto;"
                            placeholder="Search employee…">
                    </div>`);

                let search_t;
                $sub.find(".eck-date").on("change", function () {
                    s.date = $(this).val() || frappe.datetime.get_today();
                    load(listview);
                });
                $sub.find(".eck-cat-btn").on("click", function () {
                    $sub.find(".eck-cat-btn").removeClass("eck-cat-btn--active");
                    $(this).addClass("eck-cat-btn--active");
                    s.category = $(this).data("cat") || null;
                    apply_filter(s);
                });
                $sub.find(".eck-search").on("input", function () {
                    clearTimeout(search_t);
                    const v = $(this).val().trim();
                    search_t = setTimeout(function () { s.search = v; load(listview); }, 400);
                });

                s.$table_wrap = $(`<div style="padding:0 15px 20px;"></div>`);

                const $container = $("<div>")
                    .append(s.$cards_wrap)
                    .append($sub)
                    .append(s.$table_wrap);

                $fl.before($container);
                $fl.hide();

                listview.page.set_title(__("Employee Daily Checkin"));

                frappe.realtime.doctype_subscribe("Employee Checkin");
                frappe.realtime.off("list_update");
                frappe.realtime.on("list_update", function (data) {
                    if (data && data.doctype === "Employee Checkin") load(listview);
                });
                listview.page.wrapper.one("hide", function () {
                    frappe.realtime.off("list_update");
                });
            }

            load(listview);
        },
    };
})();
