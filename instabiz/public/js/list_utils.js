// Shared list view utilities — status multi-select filter + helpers.
// Loaded globally via app_include_js so all *_list.js files can use these.

// ── Global default: newest docs at top for every list view ────────────────────
// Patches ListView.prototype.setup_defaults once. Runs on every route change so
// it fires even if the ListView class is lazy-loaded after initial boot.
(function _ib_patch_listview_sort() {
    function _patch() {
        const proto = frappe?.views?.ListView?.prototype;
        if (!proto || proto._ib_sort_patched) return;
        proto._ib_sort_patched = true;

        // Patch setup_defaults — runs first, sets this.sort_by before SortSelector is created.
        // Must be async: Frappe v15 setup_defaults awaits frappe.model.with_doctype() to load
        // meta before setup_view() runs. A synchronous wrapper returns undefined, causing
        // setup_view() to run immediately before meta is ready → "Cannot read 'fields'" crash.
        const _orig_defaults = proto.setup_defaults;
        proto.setup_defaults = async function () {
            await _orig_defaults.call(this);
            this.sort_by    = "modified";
            this.sort_order = "desc";
        };

        // Patch setup_sort_selector — runs just before SortSelector is instantiated,
        // ensuring the widget gets sort_by="modified" even if setup_defaults was wrong.
        const _orig_sort_sel = proto.setup_sort_selector;
        if (_orig_sort_sel) {
            proto.setup_sort_selector = function () {
                this.sort_by    = "modified";
                this.sort_order = "desc";
                return _orig_sort_sel.call(this);
            };
        }
    }
    frappe.after_ajax(_patch);
    $(document).on("frappe:ready", _patch);
    if (frappe?.router) frappe.router.on("change", _patch);
})();

// Remove ALL active filter rows for a fieldname (filter_area.remove() only drops one per call).
function _ib_remove_filters(listview, fieldname) {
    let guard = 20;
    while (guard-- > 0 && listview.filter_area.get().some((f) => f[1] === fieldname)) {
        listview.filter_area.remove(fieldname);
    }
}

// Final-pass reorder of the whole filter row (native Frappe standard-filter
// fields AND ib_setup_* custom controls together) into an explicit sequence —
// used when matching filter order to list view column order requires moving
// NATIVE fields too (e.g. Customer/Supplier), not just the custom ones
// _ib_chain_anchor already keeps in relative call order. Call once, after
// every ib_setup_* call for this list, with the fully resolved jQuery
// elements in the target left-to-right order (resolve native fields via
// listview.page.fields_dict[fieldname].$wrapper, custom ones via their
// known .ib-* class). appendTo() moves (doesn't clone) so passing every
// visible filter box guarantees the final order; omitting one just leaves
// it wherever it already was.
function ib_reorder_filter_row(listview, $elements) {
    const $container = listview.filter_area && listview.filter_area.standard_filters_wrapper;
    if (!$container || !$container.length) return;
    $elements.forEach(($el) => {
        if ($el && $el.length) $el.appendTo($container);
    });
}

// Chains custom filter controls together in call order, so whatever sequence
// onload() calls the ib_setup_* functions in is exactly the resulting left-to-
// right DOM order — no more fragile per-function class-name lookups (a stale
// lookup here is what caused Sales Order's filter row to render Status/Date/
// Team/SalesPerson instead of the intended order).
function _ib_chain_anchor(listview, $wrapper, fallbackAnchor) {
    const chain = listview._ib_filter_chain;
    if (chain && chain.length && chain.closest("body").length) {
        $wrapper.insertAfter(chain);
    } else if (fallbackAnchor && fallbackAnchor.length) {
        $wrapper.insertAfter(fallbackAnchor);
    } else if (listview.filter_area && listview.filter_area.standard_filters_wrapper) {
        $wrapper.appendTo(listview.filter_area.standard_filters_wrapper);
    } else {
        $wrapper.appendTo(listview.page.page_form);
    }
    listview._ib_filter_chain = $wrapper;
}

function ib_extract_filter_values(value) {
    if (Array.isArray(value)) return value.filter(Boolean);
    if (typeof value === "string") {
        return value.split(",").map((v) => v.trim()).filter(Boolean);
    }
    return [];
}

/**
 * Inject a MultiSelectList status filter into the standard filter bar.
 * Hides the native status field and wires clear-all.
 *
 * @param {object} listview  - Frappe ListView instance
 * @param {string} doctype   - e.g. "Delivery Note"
 * @param {string[]} statuses - ordered list of valid status values
 */
function ib_setup_status_multiselect(listview, doctype, statuses) {
    const slug     = doctype.toLowerCase().replace(/ /g, "-");
    const cssClass = `ib-${slug}-status-multi-filter`;
    const eventNs  = `ib_${slug.replace(/-/g, "_")}_status_multi_clear`;

    const existingField = listview.page.fields_dict.status;
    if (existingField && existingField.$wrapper) {
        existingField.$wrapper.hide();
    }

    $(`.${cssClass}`).remove();
    const $wrapper = $(
        `<div class="form-group frappe-control input-max-width col-md-2 ${cssClass}" ` +
        `data-fieldtype="MultiSelectList" data-fieldname="status_multi"></div>`
    );
    _ib_chain_anchor(listview, $wrapper, existingField && existingField.$wrapper);
    $wrapper.css({ flex: "0 0 140px", maxWidth: "140px" });

    const control = frappe.ui.form.make_control({
        df: {
            label: "",
            fieldtype: "MultiSelectList",
            placeholder: __("Status"),
            input_class: "input-xs",
            get_data(txt) {
                const q = (txt || "").toLowerCase();
                return statuses
                    .filter((s) => s.toLowerCase().includes(q))
                    .map((s) => ({ value: s, description: __("Status") }));
            },
            onchange() {
                const selected = ib_extract_filter_values(control.get_value());
                _ib_remove_filters(listview, "status");
                if (selected.length) {
                    listview.filter_area.add([[doctype, "status", "in", selected]]);
                }
                listview.refresh();
            },
        },
        parent: $wrapper,
        only_input: true,
        render_input: 1,
    });
    control.$wrapper.removeClass("form-group");
    control.$wrapper.css("margin-bottom", 0);

    const current = listview.filter_area
        .get()
        .filter((f) => f[1] === "status")
        .flatMap((f) => ib_extract_filter_values(f[3]));
    if (current.length) control.set_value(current);

    const $clearAllBtn = listview.filter_area && listview.filter_area.filter_x_button;
    if ($clearAllBtn && $clearAllBtn.length) {
        $clearAllBtn
            .off(`click.${eventNs}`)
            .on(`click.${eventNs}`, () => control.set_value([]));
    }
}

// ── Generic single-value Link filter (any doctype, any Link field) ───────────
// Same chaining as every other ib_setup_list_* control here — call these in
// the exact order you want them to appear left-to-right in the filter row,
// matching list view column order (that's the actual ask this exists for:
// filter row order should match the columns, not whatever order the native
// standard-filter fields happen to render in).
function ib_setup_list_link_filter(listview, doctype, fieldname, placeholder, options) {
    const slug    = doctype.toLowerCase().replace(/ /g, "-");
    const css     = `ib-${slug}-${fieldname.replace(/_/g, "-")}-filter`;
    const eventNs = `ib_${slug.replace(/-/g, "_")}_${fieldname}_clear`;

    const existingField = listview.page.fields_dict[fieldname];
    if (existingField && existingField.$wrapper) {
        existingField.$wrapper.hide();
    }

    $(`.${css}`).remove();
    const $wrapper = $(
        `<div class="form-group frappe-control input-max-width ${css}" ` +
        `data-fieldtype="Link" data-fieldname="${fieldname}"></div>`
    );
    $wrapper.css({ flex: "0 0 160px", maxWidth: "160px" });

    _ib_chain_anchor(listview, $wrapper, existingField && existingField.$wrapper);

    const control = frappe.ui.form.make_control({
        df: {
            label: "",
            fieldtype: "Link",
            options: options,
            placeholder: __(placeholder),
            onchange() {
                const val = control.get_value();
                _ib_remove_filters(listview, fieldname);
                if (val) {
                    listview.filter_area.add([[doctype, fieldname, "=", val]]);
                }
                listview.refresh();
            },
        },
        parent: $wrapper,
        only_input: true,
        render_input: 1,
    });
    control.$wrapper.removeClass("form-group");
    control.$wrapper.css("margin-bottom", 0);

    const current = listview.filter_area.get().find((f) => f[1] === fieldname);
    if (current) control.set_value(current[3]);

    const $clearBtn = listview.filter_area && listview.filter_area.filter_x_button;
    if ($clearBtn && $clearBtn.length) {
        $clearBtn
            .off(`click.${eventNs}`)
            .on(`click.${eventNs}`, () => control.set_value(""));
    }
}

// ── Generic multi-select filter for any field (e.g. custom_location) ──────────
// Same MultiSelectList shape as ib_setup_status_multiselect above, generalized
// to any fieldname + value list + "in" filter — no bare "Select" placeholder
// item the way a native <select> needs one (nothing is picked = no chips, not
// a dead first option). Optional labelMap ({realValue: "Display Label"})
// controls what's SHOWN, both in the dropdown list and the selected-chip
// summary — MultiSelectList's get_data() natively supports value != label
// (unlike a plain <select>, no DOM-patching workaround needed), so the filter
// always applies against the real value regardless of what's displayed.
function ib_setup_list_multiselect_filter(listview, doctype, fieldname, placeholder, values, labelMap) {
    const slug    = doctype.toLowerCase().replace(/ /g, "-");
    const css     = `ib-${slug}-${fieldname.replace(/_/g, "-")}-filter`;
    const eventNs = `ib_${slug.replace(/-/g, "_")}_${fieldname}_clear`;

    const existingField = listview.page.fields_dict[fieldname];
    if (existingField && existingField.$wrapper) {
        existingField.$wrapper.hide();
    }

    $(`.${css}`).remove();
    const $wrapper = $(
        `<div class="form-group frappe-control input-max-width ${css}" ` +
        `data-fieldtype="MultiSelectList" data-fieldname="${fieldname}"></div>`
    );
    $wrapper.css({ flex: "0 0 160px", maxWidth: "160px" });

    _ib_chain_anchor(listview, $wrapper, existingField && existingField.$wrapper);

    const control = frappe.ui.form.make_control({
        df: {
            label: "",
            fieldtype: "MultiSelectList",
            placeholder: __(placeholder),
            input_class: "input-xs",
            get_data(txt) {
                const q = (txt || "").toLowerCase();
                return values
                    .filter((v) => (labelMap && labelMap[v] || v).toLowerCase().includes(q))
                    .map((v) => ({ value: v, label: (labelMap && labelMap[v]) || v, description: __(placeholder) }));
            },
            onchange() {
                const selected = ib_extract_filter_values(control.get_value());
                _ib_remove_filters(listview, fieldname);
                if (selected.length) {
                    listview.filter_area.add([[doctype, fieldname, "in", selected]]);
                }
                listview.refresh();
            },
        },
        parent: $wrapper,
        only_input: true,
        render_input: 1,
    });
    control.$wrapper.removeClass("form-group");
    control.$wrapper.css("margin-bottom", 0);

    // MultiSelectList only populates its internal _options (which set_value's
    // label lookup reads) lazily on dropdown-open — restoring an existing
    // filter here, before the user has ever opened it, would resolve nothing
    // and fall back to showing the raw value instead of labelMap's label.
    // get_data() above is synchronous, so this populates _options immediately.
    control.set_options();

    const current = listview.filter_area
        .get()
        .filter((f) => f[1] === fieldname)
        .flatMap((f) => ib_extract_filter_values(f[3]));
    if (current.length) control.set_value(current);

    const $clearBtn = listview.filter_area && listview.filter_area.filter_x_button;
    if ($clearBtn && $clearBtn.length) {
        $clearBtn
            .off(`click.${eventNs}`)
            .on(`click.${eventNs}`, () => control.set_value([]));
    }
}

// ── Generic distinct-value autocomplete filter for a free-text Data field ─────
// Native standard filters on Data fields (customer_name, supplier_name, title,
// company_name, …) render as plain text boxes with no suggestions. This swaps
// one for an Autocomplete that suggests distinct existing values of that field
// (LIKE match, debounced, capped 20) while still allowing a free-typed partial
// (ignore_validation). Applies the same `like %x%` match the native Data filter
// used, so behaviour is unchanged for anyone who just types. Call in the exact
// left-to-right slot you want it, chained like every other ib_setup_list_*.
// matchDoctype: doctype to pull suggestion values from (defaults to `doctype`).
function ib_setup_list_autocomplete_filter(listview, doctype, fieldname, placeholder, matchDoctype) {
    const src     = matchDoctype || doctype;
    const slug    = doctype.toLowerCase().replace(/ /g, "-");
    const css     = `ib-${slug}-${fieldname.replace(/_/g, "-")}-filter`;
    const eventNs = `ib_${slug.replace(/-/g, "_")}_${fieldname}_ac_clear`;

    const nativeField = listview.page.fields_dict[fieldname];
    if (nativeField && nativeField.$wrapper) nativeField.$wrapper.hide();

    $(`.${css}`).remove();
    const $wrapper = $(
        `<div class="form-group frappe-control input-max-width ${css}" ` +
        `data-fieldtype="Autocomplete" data-fieldname="${fieldname}"></div>`
    );
    $wrapper.css({ flex: "0 0 160px", maxWidth: "160px" });
    _ib_chain_anchor(listview, $wrapper, nativeField && nativeField.$wrapper);

    const control = frappe.ui.form.make_control({
        df: {
            label: "",
            fieldtype: "Autocomplete",
            placeholder: __(placeholder),
            input_class: "input-xs",
            ignore_validation: 1,
            onchange() {
                const val = (control.get_value() || "").trim();
                _ib_remove_filters(listview, fieldname);
                if (val) {
                    listview.filter_area.add([[doctype, fieldname, "like", `%${val}%`]]);
                }
                listview.refresh();
            },
        },
        parent: $wrapper,
        only_input: true,
        render_input: 1,
    });
    control.$wrapper.removeClass("form-group");
    control.$wrapper.css("margin-bottom", 0);

    let _t = null;
    function load(txt) {
        clearTimeout(_t);
        _t = setTimeout(function () {
            frappe.db
                .get_list(src, {
                    fields: [fieldname],
                    filters: txt
                        ? [[fieldname, "like", `%${txt}%`]]
                        : [[fieldname, "is", "set"]],
                    order_by: `${fieldname} asc`,
                    limit: 50,
                })
                .then(function (rows) {
                    const seen = new Set();
                    const vals = [];
                    (rows || []).forEach(function (r) {
                        const v = (r[fieldname] || "").toString().trim();
                        if (v && !seen.has(v.toLowerCase())) {
                            seen.add(v.toLowerCase());
                            vals.push(v);
                        }
                    });
                    control.set_data(vals.slice(0, 20));
                    if (control.awesomplete && control.$input.is(":focus")) {
                        control.awesomplete.evaluate();
                    }
                });
        }, 200);
    }
    control.$input.on("input focus", function () {
        load((control.$input.val() || "").trim());
    });

    const current = listview.filter_area.get().find((f) => f[1] === fieldname);
    if (current) control.set_value(String(current[3]).replace(/^%|%$/g, ""));

    const $clearBtn = listview.filter_area && listview.filter_area.filter_x_button;
    if ($clearBtn && $clearBtn.length) {
        $clearBtn
            .off(`click.${eventNs}`)
            .on(`click.${eventNs}`, () => control.set_value(""));
    }
}

// ── Generic sales person (User link) filter ───────────────────────────────────
// allowNone (opt-in, Customer only as of 2026-09-03): adds a synthetic
// "— Unassigned —" entry to the suggestion list, alongside real Users, so a
// manager can filter for unhandled customers (custom_sales_person_user not
// set) the same way they'd pick any real rep — not a separate control.
// Needs Autocomplete (not Link — a plain Link only ever suggests real rows of
// its target doctype, no room for a non-doctype pseudo-value), so allowNone
// swaps the control type; existing Quotation/SO callers (allowNone omitted)
// are unaffected and keep the native Link control exactly as before.
const IB_NONE_SALES_USER = "__none__";

function ib_setup_list_sales_user_filter(listview, doctype, placeholder, allowNone) {
    placeholder = placeholder || "Sales Person";
    const slug    = doctype.toLowerCase().replace(/ /g, "-");
    const css     = `ib-${slug}-sales-user-filter`;
    const eventNs = `ib_${slug.replace(/-/g, "_")}_sales_user_clear`;

    $(`.${css}`).remove();

    const $wrapper = $(
        `<div class="form-group frappe-control input-max-width ${css}" ` +
        `data-fieldtype="${allowNone ? "Autocomplete" : "Link"}" data-fieldname="custom_sales_person_user"></div>`
    );
    $wrapper.css({ flex: "0 0 160px", maxWidth: "160px" });

    _ib_chain_anchor(listview, $wrapper);

    function apply(val) {
        _ib_remove_filters(listview, "custom_sales_person_user");
        if (val === IB_NONE_SALES_USER) {
            listview.filter_area.add([[doctype, "custom_sales_person_user", "is", "not set"]]);
        } else if (val) {
            listview.filter_area.add([[doctype, "custom_sales_person_user", "=", val]]);
        }
        listview.refresh();
    }

    let control;
    if (allowNone) {
        control = frappe.ui.form.make_control({
            df: {
                label: "",
                fieldtype: "Autocomplete",
                placeholder: __(placeholder),
                ignore_validation: 1,
                onchange() {
                    apply(control.get_value());
                },
            },
            parent: $wrapper,
            only_input: true,
            render_input: 1,
        });

        let _t = null;
        function load(txt) {
            clearTimeout(_t);
            _t = setTimeout(function () {
                frappe.db
                    .get_list("User", {
                        fields: ["name", "full_name"],
                        filters: txt ? [["full_name", "like", `%${txt}%`]] : [],
                        order_by: "full_name asc",
                        limit: 20,
                    })
                    .then(function (rows) {
                        const data = [{ label: __("— Unassigned —"), value: IB_NONE_SALES_USER }].concat(
                            (rows || []).map((r) => ({ label: r.full_name || r.name, value: r.name }))
                        );
                        control.set_data(data);
                        if (control.awesomplete && control.$input.is(":focus")) {
                            control.awesomplete.evaluate();
                        }
                    });
            }, 200);
        }
        control.$input.on("input focus", function () {
            load((control.$input.val() || "").trim());
        });
        load("");
    } else {
        control = frappe.ui.form.make_control({
            df: {
                label: "",
                fieldtype: "Link",
                options: "User",
                placeholder: __(placeholder),
                onchange() {
                    apply(control.get_value());
                },
            },
            parent: $wrapper,
            only_input: true,
            render_input: 1,
        });
    }
    control.$wrapper.removeClass("form-group");
    control.$wrapper.css("margin-bottom", 0);

    const current = listview.filter_area.get().find((f) => f[1] === "custom_sales_person_user");
    if (current) {
        // "is"/"not set" filters carry no meaningful f[3] value to restore —
        // represent them as the synthetic None entry instead of a raw value.
        control.set_value(current[2] === "is" ? IB_NONE_SALES_USER : current[3]);
    }

    const $clearBtn = listview.filter_area && listview.filter_area.filter_x_button;
    if ($clearBtn && $clearBtn.length) {
        $clearBtn
            .off(`click.${eventNs}`)
            .on(`click.${eventNs}`, () => control.set_value(""));
    }
}

// ── Generic date range filter ─────────────────────────────────────────────────
function ib_setup_list_date_filter(listview, doctype, dateField, nativeFieldsToHide) {
    (nativeFieldsToHide || []).forEach(function (fn) {
        const f = listview.page.fields_dict[fn];
        if (f && f.$wrapper) f.$wrapper.hide();
    });

    const slug    = doctype.toLowerCase().replace(/ /g, "-");
    const css     = `ib-${slug}-date-range-filter`;
    const eventNs = `ib_${slug.replace(/-/g, "_")}_date_clear`;

    $(`.${css}`).remove();

    const $wrapper = $(
        `<div class="form-group frappe-control input-max-width ${css}" ` +
        `data-fieldtype="DateRange" data-fieldname="${dateField}_range"></div>`
    );
    $wrapper.css({ flex: "0 0 210px", maxWidth: "210px" });

    _ib_chain_anchor(listview, $wrapper);

    const control = frappe.ui.form.make_control({
        df: {
            label: "",
            fieldtype: "DateRange",
            placeholder: __("From – To"),
            onchange() {
                const val = control.get_value();
                _ib_remove_filters(listview, dateField);
                if (val && val[0] && val[1]) {
                    // "Between" (not >=/<=) so Frappe extends the end date to
                    // 23:59:59.999999 for datetime fields like `creation` — a
                    // raw "<=" truncates to midnight and silently drops every
                    // doc created later that day (see get_between_date_filter
                    // in frappe/model/db_query.py).
                    listview.filter_area.add([
                        [doctype, dateField, "Between", [val[0], val[1]]],
                    ]);
                }
                listview.refresh();
            },
        },
        parent: $wrapper,
        only_input: true,
        render_input: 1,
    });
    control.$wrapper.removeClass("form-group");
    control.$wrapper.css("margin-bottom", 0);

    const $clearBtn = listview.filter_area && listview.filter_area.filter_x_button;
    if ($clearBtn && $clearBtn.length) {
        $clearBtn
            .off(`click.${eventNs}`)
            .on(`click.${eventNs}`, () => control.set_value(null));
    }
}

// ── Generic Lead Sales Team filter ────────────────────────────────────────────
function ib_setup_list_team_filter(listview, doctype) {
    const slug    = doctype.toLowerCase().replace(/ /g, "-");
    const css     = `ib-${slug}-team-filter`;
    const eventNs = `ib_${slug.replace(/-/g, "_")}_team_clear`;

    $(`.${css}`).remove();

    const $wrapper = $(
        `<div class="form-group frappe-control input-max-width ${css}" ` +
        `data-fieldtype="Link" data-fieldname="lead_sales_team"></div>`
    );
    $wrapper.css({ flex: "0 0 160px", maxWidth: "160px" });

    _ib_chain_anchor(listview, $wrapper);

    const control = frappe.ui.form.make_control({
        df: {
            label: "",
            fieldtype: "Link",
            options: "Lead Sales Team",
            placeholder: __("Sales Team"),
            onchange() {
                const teamName = control.get_value();
                listview.filter_area.remove("custom_sales_person_user");
                if (!teamName) {
                    listview.refresh();
                    return;
                }
                frappe.db.get_list("Lead Sales Team Member", {
                    filters: { parent: teamName, parenttype: "Lead Sales Team" },
                    fields: ["user"],
                    limit: 200,
                }).then(function (members) {
                    const users = members.map(function (m) { return m.user; }).filter(Boolean);
                    if (users.length) {
                        listview.filter_area.add([
                            [doctype, "custom_sales_person_user", "in", users],
                        ]);
                    }
                    listview.refresh();
                });
            },
        },
        parent: $wrapper,
        only_input: true,
        render_input: 1,
    });
    control.$wrapper.removeClass("form-group");
    control.$wrapper.css("margin-bottom", 0);

    const $clearBtn = listview.filter_area && listview.filter_area.filter_x_button;
    if ($clearBtn && $clearBtn.length) {
        $clearBtn
            .off(`click.${eventNs}`)
            .on(`click.${eventNs}`, () => control.set_value(""));
    }
}

// Redirect Sales Users who land on the Customer Board workspace page to the actual board page.
function _ib_maybe_redirect_to_board() {
    const parts = frappe.get_route();
    if (!parts || !parts.length) return;
    const route = parts.join("/");
    if (route === "customer-board" && !frappe.user.has_role(["Sales Manager", "System Manager"])) {
        frappe.set_route("ib-customer-board");
    }
}
frappe.router.on("change", _ib_maybe_redirect_to_board);
frappe.after_ajax(function () { _ib_maybe_redirect_to_board(); });

function ib_disable_status_click_filter(listview) {
    listview.$result.find(".indicator-pill").each(function () {
        $(this)
            .removeClass("filterable")
            .off("click.ib_disable_status_filter")
            .on("click.ib_disable_status_filter", function (e) {
                e.preventDefault();
                e.stopPropagation();
            });
    });
}

// Latest frm to inject into — updated each time a submitted SI/DN form loads.
let _ib_ewb_frm = null;

// Guard: prevents infinite retry loop when distance error triggers a retry.
let _ib_ewb_retrying = false;

// Address controls created by make_control — referenced by the frappe.call interceptor.
let _ib_ewb_bill_from_ctrl = null;
let _ib_ewb_dispatch_ctrl  = null;
let _ib_ewb_ship_to_ctrl   = null;

function _ib_is_distance_error(msg) {
    const s = (msg || "").toLowerCase();
    return s.includes("distance") && (
        s.includes("greater") || s.includes("less") ||
        s.includes("more than") || s.includes("pincode") ||
        s.includes("between") || s.includes("km") || s.includes("exceed")
    );
}

async function _ib_recalc_and_retry() {
    frappe.show_alert({ message: __("Distance error — recalculating from pincodes…"), indicator: "orange" });
    const fromPin = ($("#ib-from-pin").val() || "").trim();
    const toPin   = ($("#ib-to-pin").val()   || "").trim();
    if (!fromPin || !toPin) {
        _ib_ewb_retrying = false;
        frappe.show_alert({ message: __("Pincodes not available for auto-retry. Update distance manually."), indicator: "red" });
        return;
    }
    await _ib_calc_and_fill(fromPin, toPin, null, null);
    // Brief pause so the dialog distance field is fully updated before retry
    await new Promise(r => setTimeout(r, 600));
    if (frappe.cur_dialog) {
        frappe.cur_dialog.get_primary_btn().trigger("click");
    } else {
        _ib_ewb_retrying = false;
    }
}

function ib_watch_ewaybill_dialog(frm) {
    _ib_ewb_frm = frm;

    // Patch frappe.ui.Dialog.prototype.show once — fires synchronously on every dialog open.
    if (frappe.ui.Dialog._ib_patched) return;
    frappe.ui.Dialog._ib_patched = true;

    // Persistent frappe.call interceptor — reads #ib-txn-type + address fields at call time.
    // Also wraps callback/error to auto-retry on NIC distance validation errors.
    const _origCall = frappe.call.bind(frappe);
    frappe.call = function (opts, ...rest) {
        if (opts && typeof opts.method === "string" && opts.method.includes("generate_e_waybill")) {
            const sel       = document.getElementById("ib-txn-type");
            const txnType   = sel ? parseInt(sel.value, 10) : 1;
            opts.args = opts.args || {};
            opts.args.transaction_type = txnType;
            const billFrom  = (_ib_ewb_bill_from_ctrl?.get_value?.() || "").trim();
            const dispatch  = (_ib_ewb_dispatch_ctrl?.get_value?.()  || "").trim();
            const shipTo    = (_ib_ewb_ship_to_ctrl?.get_value?.()   || "").trim();
            if (billFrom) opts.args.bill_from_address   = billFrom;
            if (dispatch) opts.args.dispatch_from_address = dispatch;
            if (shipTo)   opts.args.ship_to_address     = shipTo;

            // Wrap error callback — NIC distance errors come as HTTP 417.
            // Frappe v15 calls opts.error_callback(r) where r is the PARSED response
            // object (not the XHR) for 417 errors. Handle both shapes.
            const _origErr = opts.error;
            opts.error = async function (r_or_xhr) {
                let msg = "";
                try {
                    // r_or_xhr is the parsed response for 417, raw XHR for 500
                    const resp = (r_or_xhr && (r_or_xhr.exception || r_or_xhr._server_messages))
                        ? r_or_xhr
                        : (r_or_xhr?.responseJSON || JSON.parse(r_or_xhr?.responseText || "{}"));
                    let sm = "";
                    try { sm = JSON.parse(resp._server_messages || "[]").map(m => { try { return JSON.parse(m).message; } catch(_) { return m; } }).join(" "); } catch (_) {}
                    msg = [resp.exception, resp.exc_type, sm].filter(Boolean).join(" ");
                } catch (_) { msg = String(r_or_xhr || ""); }

                if (!_ib_ewb_retrying && _ib_is_distance_error(msg)) {
                    _ib_ewb_retrying = true;
                    await _ib_recalc_and_retry();
                } else {
                    _ib_ewb_retrying = false;
                    if (_origErr) _origErr(r_or_xhr);
                }
            };

            // Wrap success callback — rare but some paths return exc inline
            const _origCb = opts.callback;
            const _ib_is_initial_generate = opts.method.endsWith("generate_e_waybill");
            const _ib_part_b_missing = !(opts.args.vehicle_no || "").trim();
            opts.callback = async function (r) {
                if (!_ib_ewb_retrying && r && r.exc && _ib_is_distance_error(r.exc)) {
                    _ib_ewb_retrying = true;
                    await _ib_recalc_and_retry();
                    return;
                }
                _ib_ewb_retrying = false;
                if (_origCb) _origCb(r);

                // NIC only computes Valid Until (transport validity) once Part B
                // (vehicle/transport doc) is filled - an e-way bill generated with
                // Part A only has no computed validity and isn't legally usable for
                // the actual goods movement yet. Nudge rather than block, since
                // Part-A-only generation is a real, valid NIC workflow (e.g. goods
                // not yet loaded) - just make sure it isn't forgotten.
                if (_ib_is_initial_generate && _ib_part_b_missing && r && !r.exc) {
                    frappe.show_alert({
                        message: __(
                            "e-Way Bill generated with Part A only - no vehicle/transporter " +
                            "details yet, so NIC hasn't set a Valid Until date. Fill Part B " +
                            "(Update Vehicle Info) before the goods actually move."
                        ),
                        indicator: "orange",
                    }, 12);
                }
            };
        }

        // e-Invoice "Generate" (india_compliance e_invoice_actions.js) fires straight
        // to the real government IRP on click with zero review screen - unlike the
        // e-Waybill dialog above, which shows a full editable form first. An IRN is
        // only cancellable within 24h of generation, so a mis-click here is a real
        // problem. Gate it with a one-time confirm showing what's about to be filed -
        // no data injection needed (e-Invoice's own args are already complete),
        // just a review step matching the e-Waybill flow's own rigor.
        if (
            opts && typeof opts.method === "string" &&
            opts.method.includes("e_invoice.generate_e_invoice") &&
            _ib_ewb_frm && _ib_ewb_frm.doctype === "Sales Invoice" &&
            !opts._ib_confirmed
        ) {
            const frm = _ib_ewb_frm;
            const d = frm.doc;
            const gt = format_currency ? format_currency(d.grand_total, d.currency) : d.grand_total;
            return new Promise((resolve, reject) => {
                frappe.confirm(
                    __(
                        "Generate e-Invoice (IRN) for <b>{0}</b>?<br><br>" +
                        "Customer: <b>{1}</b><br>" +
                        "Grand Total: <b>{2}</b><br>" +
                        "Items: <b>{3}</b><br><br>" +
                        "This files the invoice with the government IRP immediately - " +
                        "it cannot be edited afterward, and can only be cancelled within 24 hours.",
                        [d.name, frappe.utils.escape_html(d.customer_name || d.customer), gt, (d.items || []).length]
                    ),
                    () => {
                        const retryOpts = Object.assign({}, opts, { _ib_confirmed: true });
                        resolve(_origCall(retryOpts, ...rest));
                    },
                    () => {
                        // User cancelled - restore any button/dialog freeze the caller may set
                        if (opts.always) opts.always();
                        resolve();
                    }
                );
            });
        }

        return _origCall(opts, ...rest);
    };

    const _orig = frappe.ui.Dialog.prototype.show;
    frappe.ui.Dialog.prototype.show = function () {
        _orig.call(this);
        if (!_ib_ewb_frm) return;
        if (!this.title || !this.title.includes("e-Waybill")) return;
        const el = this.$wrapper && this.$wrapper[0];
        if (!el) return;
        // Small delay so Bootstrap finishes appending to body
        setTimeout(() => {
            if ($(el).find(".ib-sp-wrap").length) return;
            _ib_inject_self_pickup(el);
            _ib_populate_distance(_ib_ewb_frm);

            if (!_ib_ewb_frm || !_ib_ewb_frm.doc) return;
            const transport = (_ib_ewb_frm.doc.custom_transport || "").toUpperCase();

            // Auto-check self-pickup when the transport is a self-pickup entry
            if (transport.includes("SELF")) {
                const cb = document.getElementById("ib-self-pickup");
                if (cb && !cb.checked) {
                    cb.checked = true;
                    cb.dispatchEvent(new Event("change", { bubbles: true }));
                }
                return; // self-pickup uses company GSTIN — skip transporter lookup
            }

            // Populate gst_transporter_id from IB Transport (with fallback to name search)
            if (_ib_ewb_frm.doc.custom_transport) {
                _ib_fetch_and_fill_transporter_gstin(_ib_ewb_frm.doc.custom_transport);
            }
        }, 80);
    };
}

function _ib_fetch_and_fill_transporter_gstin(transport_name) {
    frappe.call({
        method: "instabiz.overrides.ewaybill.get_transport_gstin",
        args: { transport_name },
        callback(r) {
            const gstin = (r.message || "").trim();
            if (!gstin) return;
            const field = document.querySelector('input[data-fieldname="gst_transporter_id"]');
            if (field && !field.value) {
                field.value = gstin;
                field.dispatchEvent(new Event("change", { bubbles: true }));
                field.dispatchEvent(new Event("input",  { bubbles: true }));
            }
            // Also update via frappe dialog API so the value is serialized in values dict
            if (frappe.cur_dialog) {
                try { frappe.cur_dialog.set_value("gst_transporter_id", gstin); } catch (_) {}
            }
        },
    });
}

async function _ib_populate_distance(frm) {
    try {
        const src_addr = frm.doc.company_address;
        const dst_addr = frm.doc.shipping_address_name || frm.doc.customer_address;
        if (!src_addr && !dst_addr) return;

        const [src_val, dst_val] = await Promise.all([
            src_addr ? frappe.db.get_value("Address", src_addr, ["pincode", "city", "state"]) : null,
            dst_addr ? frappe.db.get_value("Address", dst_addr, ["pincode", "city", "state"]) : null,
        ]);

        const src = src_val?.message;
        const dst = dst_val?.message;

        // Pre-fill pincode fields in the dialog UI
        const fromIn = document.getElementById("ib-from-pin");
        const toIn   = document.getElementById("ib-to-pin");
        if (fromIn && src?.pincode) fromIn.value = src.pincode;
        if (toIn   && dst?.pincode) toIn.value   = dst.pincode;

        // Auto-calculate if both pincodes available
        if (src?.pincode && dst?.pincode) {
            await _ib_calc_and_fill(src.pincode, dst.pincode, src, dst);
        }
    } catch (_) {}
}

async function _ib_calc_and_fill(fromPin, toPin, srcFallback, dstFallback) {
    const $result = $("#ib-dist-result");
    const $btn    = $("#ib-calc-dist");
    $result.text("Calculating…").css("color", "var(--text-muted)");
    $btn.prop("disabled", true);
    try {
        const [src_geo, dst_geo] = await Promise.all([
            _ib_geocode_addr(fromPin, srcFallback?.city, srcFallback?.state),
            _ib_geocode_addr(toPin,   dstFallback?.city, dstFallback?.state),
        ]);

        if (!src_geo || !dst_geo) {
            $result.text("Could not locate one or both pincodes.").css("color", "var(--red-500, #e74c3c)");
            return;
        }

        const dist = Math.max(1, Math.round(_ib_haversine(src_geo.lat, src_geo.lng, dst_geo.lat, dst_geo.lng)));

        // Set dialog distance field
        const distInput = document.querySelector('input[data-fieldname="distance"]');
        if (distInput) {
            distInput.value = dist;
            distInput.dispatchEvent(new Event("change", { bubbles: true }));
            distInput.dispatchEvent(new Event("input",  { bubbles: true }));
        }
        if (frappe.cur_dialog) frappe.cur_dialog.set_value("distance", dist);

        $result
            .html(`<span style="color:var(--green-600,#27ae60)">✓</span> <strong>${dist} km</strong> straight-line distance (pincode ${fromPin} → ${toPin})`)
            .css("color", "");
    } catch (e) {
        $result.text("Error calculating distance.").css("color", "var(--red-500, #e74c3c)");
    } finally {
        $btn.prop("disabled", false);
    }
}

async function _ib_geocode_addr(pincode, city, state) {
    // Try pincode first (countrycodes=in is the correct Nominatim param)
    if (pincode) {
        const r1 = await fetch(
            `https://nominatim.openstreetmap.org/search?postalcode=${encodeURIComponent(pincode)}&countrycodes=in&format=json&limit=1`,
            { headers: { "Accept-Language": "en" } }
        );
        const d1 = await r1.json();
        if (d1.length) return { lat: parseFloat(d1[0].lat), lng: parseFloat(d1[0].lon) };
    }
    // Fallback: city + state search
    if (city) {
        const q = [city, state, "India"].filter(Boolean).join(", ");
        const r2 = await fetch(
            `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(q)}&format=json&limit=1`,
            { headers: { "Accept-Language": "en" } }
        );
        const d2 = await r2.json();
        if (d2.length) return { lat: parseFloat(d2[0].lat), lng: parseFloat(d2[0].lon) };
    }
    return null;
}

function _ib_haversine(lat1, lon1, lat2, lon2) {
    const R = 6371;
    const toRad = (x) => (x * Math.PI) / 180;
    const dLat = toRad(lat2 - lat1);
    const dLon = toRad(lon2 - lon1);
    const a =
        Math.sin(dLat / 2) ** 2 +
        Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function _ib_inject_self_pickup(modal_el) {
    const $modal = $(modal_el);
    if ($modal.find(".ib-sp-wrap").length) return;

    const $part_a = $modal.find('[data-fieldname="section_part_a"]');
    if (!$part_a.length) return;

    const $row = $(`
        <div class="ib-sp-wrap" style="padding:8px 15px 10px;display:flex;align-items:center;gap:8px;
            border-bottom:1px solid var(--border-color);background:var(--subtle-fg,#f5f5f5);">
            <input type="checkbox" id="ib-self-pickup"
                style="width:14px;height:14px;cursor:pointer;accent-color:#d97757;flex-shrink:0;">
            <label for="ib-self-pickup"
                style="margin:0;font-size:12px;font-weight:600;cursor:pointer;user-select:none;">
                Self Pickup
            </label>
        </div>
    `);

    $part_a.before($row);

    // ── Transaction Type injected into the second field slot of section 1 ────────
    const $txnTarget = $modal.find('.form-page > div:nth-child(1) > .section-body > div:nth-child(2)');
    if ($txnTarget.length) {
        $txnTarget.append($(`
            <div class="frappe-control" data-fieldtype="Select" data-fieldname="ib_transaction_type"
                style="margin-bottom:0;">
                <div class="clearfix">
                    <label class="control-label"
                        style="padding-right:0;font-size:var(--text-sm);">Transaction Type</label>
                </div>
                <div class="control-input-wrapper">
                    <div class="control-input">
                        <select id="ib-txn-type" class="input-with-feedback form-control bold">
                            <option value="1">Regular</option>
                            <option value="2">Bill To - Ship To</option>
                            <option value="3">Bill From - Dispatch From</option>
                            <option value="4">Combination (2 &amp; 3)</option>
                        </select>
                    </div>
                </div>
            </div>
        `));
    }

    // ── Address fields — vertical stack, full-width, directly above self-pickup ──
    const $addrWrap = $(
        '<div class="ib-addr-wrap" ' +
        'style="display:none;padding:12px 15px 0;border-top:1px solid var(--border-color);"></div>'
    );

    const $billFromCol = $('<div></div>').appendTo($addrWrap);
    const $dispatchCol = $('<div></div>').appendTo($addrWrap);
    const $shipToCol   = $('<div></div>').appendTo($addrWrap);

    // Sits directly above self-pickup row
    $row.before($addrWrap);

    function _ib_make_addr_ctrl(label, fieldname, $parent) {
        const ctrl = frappe.ui.form.make_control({
            df: { label: __(label), fieldtype: "Data", fieldname },
            parent: $parent,
            render_input: true,
        });
        ctrl.$wrapper.find(".control-label").css("font-size", "var(--text-sm)");
        return ctrl;
    }

    _ib_ewb_bill_from_ctrl = _ib_make_addr_ctrl("Bill From Address",     "ib_bill_from_addr", $billFromCol);
    _ib_ewb_dispatch_ctrl  = _ib_make_addr_ctrl("Dispatch From Address", "ib_dispatch_addr",  $dispatchCol);
    _ib_ewb_ship_to_ctrl   = _ib_make_addr_ctrl("Ship To Address",       "ib_ship_to_addr",   $shipToCol);

    function _ib_update_addr_fields(val) {
        const showBillFrom = val === 3 || val === 4;
        const showDispatch = val === 3 || val === 4;
        const showShipTo   = val === 2 || val === 4;
        $addrWrap.css("display", (showBillFrom || showDispatch || showShipTo) ? "block" : "none");
        $billFromCol.css("display", showBillFrom ? "block" : "none");
        $dispatchCol.css("display", showDispatch ? "block" : "none");
        $shipToCol.css("display",   showShipTo   ? "block" : "none");
    }

    $("#ib-txn-type").on("change", function () {
        _ib_update_addr_fields(parseInt(this.value, 10));
    });



    // ── Pincode distance calculator ───────────────────────────────────────────────
    const $distField = $modal.find('[data-fieldname="distance"]').closest(".frappe-control");
    if ($distField.length) {
        const $calcWrap = $(`
            <div class="ib-dist-calc" style="
                margin: 8px 0 4px;
                padding: 10px 12px;
                background: var(--subtle-fg, #f7f7f7);
                border: 1px solid var(--border-color);
                border-radius: 6px;
            ">
                <div style="font-size:10px; font-weight:700; letter-spacing:.5px;
                             color:var(--text-muted); margin-bottom:7px; text-transform:uppercase;">
                    Pincode Distance Calculator
                </div>
                <div style="display:flex; gap:8px; align-items:flex-end; flex-wrap:wrap;">
                    <div style="flex:1; min-width:90px;">
                        <label style="font-size:11px; color:var(--text-muted); display:block; margin-bottom:2px;">From Pincode</label>
                        <input id="ib-from-pin" type="text" maxlength="6"
                            placeholder="421302"
                            class="form-control"
                            style="font-size:12px; height:28px; padding:2px 8px;">
                    </div>
                    <div style="flex:1; min-width:90px;">
                        <label style="font-size:11px; color:var(--text-muted); display:block; margin-bottom:2px;">To Pincode</label>
                        <input id="ib-to-pin" type="text" maxlength="6"
                            placeholder="400703"
                            class="form-control"
                            style="font-size:12px; height:28px; padding:2px 8px;">
                    </div>
                    <button id="ib-calc-dist" class="btn btn-xs"
                        style="height:28px; padding:0 12px; background:var(--primary,#d97757);
                               color:#fff; border:none; border-radius:4px; font-size:11px;
                               cursor:pointer; flex-shrink:0;">
                        Calculate
                    </button>
                </div>
                <div id="ib-dist-result" style="margin-top:6px; font-size:11px; min-height:16px;"></div>
            </div>
        `);
        $distField.before($calcWrap);

        // Calculate button click
        $(document).off("click.ib_calc_dist").on("click.ib_calc_dist", "#ib-calc-dist", async function () {
            const fromPin = ($("#ib-from-pin").val() || "").trim();
            const toPin   = ($("#ib-to-pin").val()   || "").trim();
            if (!fromPin || !toPin) {
                $("#ib-dist-result")
                    .text("Enter both pincodes.")
                    .css("color", "var(--orange-500, #e67e22)");
                return;
            }
            await _ib_calc_and_fill(fromPin, toPin, null, null);
        });

        // Recalculate on pincode field Enter key
        $(document).off("keydown.ib_pin").on("keydown.ib_pin", "#ib-from-pin, #ib-to-pin", async function (e) {
            if (e.key === "Enter") $("#ib-calc-dist").trigger("click");
        });
    }

    document.addEventListener("change", function (e) {
        if (e.target.id === "ib-self-pickup") {
            const gst = document.querySelector('input[data-fieldname="gst_transporter_id"]');
            const trn = $modal.find('[data-fieldname="transporter"]').closest(".frappe-control")[0];
            // Self-pickup transporter = company itself — use company GSTIN, not customer GSTIN
            const gstin = (_ib_ewb_frm && _ib_ewb_frm.doc && _ib_ewb_frm.doc.company_gstin) || "";
            if (e.target.checked) {
                if (gst) {
                    gst.value = gstin;
                    gst.dispatchEvent(new Event("change", { bubbles: true }));
                    gst.dispatchEvent(new Event("input",  { bubbles: true }));
                }
                if (trn) trn.style.display = "none";
            } else {
                if (gst) gst.value = "";
                if (trn) trn.style.display = "";
            }
        }
    });
}