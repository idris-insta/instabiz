/**
 * form.js
 * Form-level handlers for all IB transaction doctypes.
 * Optimized for Frappe v15 to prevent UI rounding jitters on blur.
 * Depends on: recalc.js
 */

/**
 * ib_hide_sidebar()
 * Collapse the Frappe list-view filter sidebar.
 */
function ib_hide_sidebar() {
    const route = frappe.get_route();
    if (!route || route[0] !== "List") return;
    $('.layout-side-section').css({ display: 'none', transition: 'none' });
    $('.layout-main-section').css('margin-left', '0');
}

// Global router listener
frappe.router.on("change", function () {
    ib_hide_sidebar();
});

const IB_DOCTYPES        = ["Quotation", "Sales Order", "Delivery Note", "Sales Invoice"];
const IB_REOPEN_DOCTYPES = ["Quotation", "Sales Order"];
const IB_DEBOUNCE        = 500; // Increased to 500ms for stable decimal input

IB_DOCTYPES.forEach(function (doctype) {
    frappe.ui.form.on(doctype, {
        refresh(frm) {
            // Disable auto-fetch for UOM to maintain manual selection control
            const uom_df = frappe.meta.get_docfield(`${doctype} Item`, "uom");
            if (uom_df) {
                uom_df.fetch_from = "";
                uom_df.fetch_enabled = 0;
            }

            frm.set_query("item_code", "items", () => ({ page_length: 50 }));

            // Clicking the row index number opens the row dialog (same as pencil icon)
            const $grid = frm.fields_dict.items.grid.wrapper;
            $grid.off("click.ib_row_open").on("click.ib_row_open", ".grid-row .row-index", function () {
                const docname = $(this).closest(".grid-row").attr("data-name");
                const grid_row = frm.fields_dict.items.grid.grid_rows_by_docname[docname];
                if (grid_row) grid_row.toggle_view(true);
            });

            // UI cleanup for Draft documents
            if (frm.doc.docstatus === 0) {
                frm.remove_custom_button(__("Cancel"));
                if (frm.page.btn_secondary) frm.page.btn_secondary.hide();
            }

            // SI and DN: no reopen or amend — cancelled docs must be re-raised fresh
            if ((doctype === "Sales Invoice" || doctype === "Delivery Note") && frm.doc.docstatus === 2) {
                // defer past Frappe's own button setup
                setTimeout(() => frm.page.clear_primary_action(), 0);
            }

            // Rate/Qty/dimension fields are allow_on_submit=0 core-wide — Frappe's
            // own save-time guard correctly rejects any change to them once
            // docstatus=1 ("Cannot Update After Submit"), but the collapsed grid's
            // inline cell editor doesn't consistently grey them out to match — a
            // user can type a new rate, watch Amount/Total preview-update
            // client-side (core calculate_taxes_and_totals, unrelated to our own
            // recalc.js which already correctly no-ops post-submit), hit Save, and
            // hit that wall with no idea why the number "didn't update". Lock the
            // same fields visually so the grid matches what the server allows.
            if (frm.doc.docstatus === 1) {
                const locked_fields = ["item_code", "qty", "rate", "uom",
                    "width_mm", "length_mtr", "qty_pkg", "total_pkg"];
                const grid = frm.fields_dict.items.grid;
                locked_fields.forEach((f) => {
                    if (grid.docfields.some((df) => df.fieldname === f)) {
                        grid.update_docfield_property(f, "read_only", 1);
                    }
                });
                // grid.refresh() alone updates the docfield metadata but not the
                // already-rendered row controls (their read_only state is set at
                // row-construction time) — a full field refresh actually rebuilds
                // the grid rows, which is what makes the lock visually/functionally
                // real instead of just changing config nothing re-reads.
                frm.refresh_field("items");
            }

            // Custom Reopen logic for Cancelled documents (Q and SO only)
            // Server enforces permissions — no client-side role check needed
            if (
                frm.doc.docstatus === 2 &&
                IB_REOPEN_DOCTYPES.includes(doctype)
            ) {
                frm.page.set_primary_action(__("Reopen"), function () {
                    frappe.confirm(
                        __("Reopen this {0}?").replace("{0}", __(doctype)),
                        function () {
                            frappe.call({
                                method: {
                                    "Quotation": "instabiz.overrides.quotation.reopen_quotation",
                                    "Sales Order": "instabiz.overrides.sales_order.reopen_sales_order",
                                }[doctype],
                                args: { name: frm.doc.name },
                                freeze: true,
                                freeze_message: __("Reopening…"),
                                callback: function (r) {
                                    if (!r.exc) window.location.reload();
                                },
                            });
                        }
                    );
                });
            }
        },


        // after_save / on_submit / after_cancel — Frappe triggers frm.refresh()
        // automatically; redundant calls here caused race conditions with
        // india_compliance's internal reload (e-waybill / IRN generation dialog).
    });

    // Child Table Triggers
    frappe.ui.form.on(`${doctype} Item`, {
        item_code(frm, cdt, cdn) {
            // Reset UOM once on item change without double-triggering refreshes
            frappe.model.set_value(cdt, cdn, "uom", "");
            
            // Allow Frappe to finish fetching item defaults before we recalc
            setTimeout(async () => {
                await ib_recalc_row(frm, cdt, cdn, true);
            }, 600);
        },

        // Dimension triggers - Recalculate Qty then Amount
        uom: ib_debounce(async (frm, cdt, cdn) => {
            ib_toggle_roll_fields(frm, cdt, cdn);
            await ib_recalc_row(frm, cdt, cdn, true);
        }, IB_DEBOUNCE),
        width_mm:   ib_debounce(async (frm, cdt, cdn) => ib_recalc_row(frm, cdt, cdn, true),  IB_DEBOUNCE),
        length_mtr: ib_debounce(async (frm, cdt, cdn) => ib_recalc_row(frm, cdt, cdn, true),  IB_DEBOUNCE),
        qty_pkg:    ib_debounce(async (frm, cdt, cdn) => ib_recalc_row(frm, cdt, cdn, true),  IB_DEBOUNCE),
        total_pkg:  ib_debounce(async (frm, cdt, cdn) => ib_recalc_row(frm, cdt, cdn, true),  IB_DEBOUNCE),

        // Direct value triggers - Recalculate Amount only
        qty:        ib_debounce(async (frm, cdt, cdn) => ib_recalc_row(frm, cdt, cdn, false), IB_DEBOUNCE),
        rate:       ib_debounce(async (frm, cdt, cdn) => ib_recalc_row(frm, cdt, cdn, false), IB_DEBOUNCE),

        // Re-apply field visibility each time a row dialog opens
        form_render(frm, cdt, cdn) {
            ib_toggle_roll_fields(frm, cdt, cdn);
        },

        items_remove: (frm) => frm.refresh_field("items"),
    });
});

// ── Patch erpnext.utils.update_child_items for Q + SO ────────────────────────
// ERPNext's native dialog only shows qty/rate. Intercept and show our extended
// dialog that includes dimension fields (color, width, length, qty_pkg, etc.).
(function _ib_patch_update_child_items() {
    let _retries = 0;
    const _try = () => {
        if (!window.erpnext || !erpnext.utils || !erpnext.utils.update_child_items) {
            if (++_retries < 50) setTimeout(_try, 300);
            return;
        }
        const _orig = erpnext.utils.update_child_items.bind(erpnext.utils);
        erpnext.utils.update_child_items = function (opts) {
            const dt = opts.frm && opts.frm.doc && opts.frm.doc.doctype;
            if (dt === "Quotation" || dt === "Sales Order") {
                _ib_update_items_dialog(opts.frm, dt);
            } else {
                _orig.call(this, opts);
            }
        };
    };
    $(document).ready(_try);
}());

// ── Update Items with Dimensions dialog (Q + SO, submitted) ──────────────────

function _ib_update_items_dialog(frm, doctype) {
    const data = (frm.doc.items || []).map((d) => ({
        docname:          d.name,
        item_code:        d.item_code,
        color:            d.color || "",
        width_mm:         d.width_mm || 0,
        length_mtr:       d.length_mtr || 0,
        qty_pkg:          d.qty_pkg || 0,
        total_pkg:        d.total_pkg || 0,
        rate:             d.rate || 0,
        custom_thickness: d.custom_thickness || "",
        custom_branding:  d.custom_branding || "",
        custom_marking:   d.custom_marking || "",
    }));

    const dialog = new frappe.ui.Dialog({
        title: __("Update Items"),
        size: "extra-large",
        fields: [
            {
                fieldname: "items",
                fieldtype: "Table",
                label: "Items",
                cannot_add_rows: true,
                in_place_edit: false,
                reqd: 1,
                data: data,
                get_data: () => data,
                fields: [
                    { fieldname: "docname",          fieldtype: "Data",     read_only: 1, hidden: 1 },
                    { fieldname: "item_code",        label: __("Item"),         fieldtype: "Data",     read_only: 1, in_list_view: 1, columns: 2 },
                    { fieldname: "color",            label: __("Color"),        fieldtype: "Link",     options: "Color",        in_list_view: 1 },
                    { fieldname: "width_mm",         label: __("Width MM"),     fieldtype: "Float",    in_list_view: 1 },
                    { fieldname: "length_mtr",       label: __("Length MTR"),   fieldtype: "Float",    in_list_view: 1 },
                    { fieldname: "qty_pkg",          label: __("Qty/Pkg"),      fieldtype: "Float",    in_list_view: 1 },
                    { fieldname: "total_pkg",        label: __("Total Pkg"),    fieldtype: "Float",    in_list_view: 1 },
                    { fieldname: "rate",             label: __("Rate"),         fieldtype: "Currency",  in_list_view: 1 },
                    { fieldname: "custom_thickness", label: __("Thickness"),    fieldtype: "Data" },
                    { fieldname: "custom_branding",  label: __("Branding"),     fieldtype: "Link",     options: "IB Branding" },
                    { fieldname: "custom_marking",   label: __("Marking"),      fieldtype: "Data" },
                ],
            },
        ],
        primary_action_label: __("Update"),
        primary_action(values) {
            const items = (values.items || []).filter((d) => !!d.item_code);
            frappe.call({
                method: "instabiz.overrides.utils.update_item_dimensions",
                freeze: true,
                freeze_message: __("Updating…"),
                args: {
                    parent_doctype: doctype,
                    parent_name: frm.doc.name,
                    items: JSON.stringify(items),
                },
                callback(r) {
                    if (!r.exc) {
                        dialog.hide();
                        frappe.show_alert({ message: __("Items updated"), indicator: "green" });
                        frm.reload_doc();
                    }
                },
            });
        },
    });
    dialog.show();
}

// ── ROLL UOM: hide qty_pkg + total_pkg, force both to 1 ──────────────────────

function ib_toggle_roll_fields(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!row) return;
    const is_roll = ib_is_roll(row.uom);

    if (is_roll) {
        if (flt(row.qty_pkg) !== 1) frappe.model.set_value(cdt, cdn, "qty_pkg", 1);
        if (flt(row.total_pkg) !== 1) frappe.model.set_value(cdt, cdn, "total_pkg", 1);
    }

    // Toggle visibility in expanded row dialog
    const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
    if (!grid) return;
    const grid_row = grid.grid_rows_by_docname && grid.grid_rows_by_docname[cdn];
    if (grid_row && grid_row.fields_dict) {
        ["qty_pkg", "total_pkg"].forEach(f => {
            const fd = grid_row.fields_dict[f];
            if (fd) {
                fd.df.hidden = is_roll ? 1 : 0;
                fd.refresh();
            }
        });
    }
}

// ── Quotation: Margin % on item rows ─────────────────────────────────────────

function _ib_update_margin(frm, cdt, cdn) {
    const row = locals[cdt][cdn];
    if (!row) return;
    const rate = flt(row.rate);
    const cost = flt(row.custom_valuation_rate);
    const margin = (rate && cost) ? flt((rate - cost) / rate * 100, 1) : 0;
    if (Math.abs(flt(margin) - flt(row.custom_margin_pct)) > 0.05) {
        frappe.model.set_value(cdt, cdn, "custom_margin_pct", margin);
    }
}

frappe.ui.form.on("Quotation Item", {
    item_code(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!row || !row.item_code) return;
        frappe.db.get_value("Item", row.item_code, "valuation_rate", (r) => {
            if (!r || !r.valuation_rate) return;
            frappe.model.set_value(cdt, cdn, "custom_valuation_rate", flt(r.valuation_rate));
            _ib_update_margin(frm, cdt, cdn);
        });
    },
    rate(frm, cdt, cdn) {
        _ib_update_margin(frm, cdt, cdn);
    },
    custom_valuation_rate(frm, cdt, cdn) {
        _ib_update_margin(frm, cdt, cdn);
    },
});

// ── Quotation: Sale Type & Currency → clear taxes; currency → convert rates ───

frappe.ui.form.on("Quotation", {
    refresh(frm) {
        // Unhide conversion_rate when a non-INR currency is active
        if (frm.doc.currency && frm.doc.currency !== "INR") {
            frm.set_df_property("conversion_rate", "hidden", 0);
            frm.refresh_field("conversion_rate");
        }
    },

    custom_sale_type(frm) {
        if (frm.doc.custom_sale_type === "Export") {
            setTimeout(() => {
                frm.doc.taxes_and_charges = "";
                frm.refresh_field("taxes_and_charges");
                frm.clear_table("taxes");
                frm.refresh_field("taxes");
            }, 100);
        } else if (!frm.doc.currency || frm.doc.currency === "INR") {
            frappe.db.get_value(
                "Sales Taxes and Charges Template",
                { is_default: 1, company: frm.doc.company },
                "name"
            ).then(r => {
                const tpl_name = r && r.message && r.message.name;
                if (!tpl_name) return;
                frappe.db.get_doc("Sales Taxes and Charges Template", tpl_name)
                    .then(template => {
                        frm.doc.taxes_and_charges = tpl_name;
                        frm.refresh_field("taxes_and_charges");
                        frm.clear_table("taxes");
                        (template.taxes || []).forEach(row => {
                            const child = frm.add_child("taxes");
                            child.charge_type            = row.charge_type;
                            child.account_head           = row.account_head;
                            child.description            = row.description;
                            child.rate                   = row.rate;
                            child.included_in_print_rate = row.included_in_print_rate;
                        });
                        frm.refresh_field("taxes");
                    });
            });
        }
    },

    currency(frm) {
        const is_foreign = frm.doc.currency && frm.doc.currency !== "INR";

        // Show/hide conversion_rate field
        frm.set_df_property("conversion_rate", "hidden", is_foreign ? 0 : 1);
        frm.refresh_field("conversion_rate");

        if (!is_foreign) return;

        // Foreign currency = export; clear taxes immediately
        frm.doc.taxes_and_charges = "";
        frm.refresh_field("taxes_and_charges");
        frm.clear_table("taxes");
        frm.refresh_field("taxes");

        // Fetch exchange rate then convert item rates from INR to the selected currency
        frappe.call({
            method: "erpnext.setup.utils.get_exchange_rate",
            args: {
                transaction_date: frm.doc.transaction_date || frappe.datetime.get_today(),
                from_currency: frm.doc.currency,
                to_currency: "INR",
            },
            callback(r) {
                const conv_rate = r && flt(r.message);
                if (!conv_rate || conv_rate <= 0) {
                    frappe.show_alert({
                        message: __("No exchange rate found for {0}. Set conversion rate manually.", [frm.doc.currency]),
                        indicator: "orange",
                    }, 6);
                    return;
                }

                frm.set_value("conversion_rate", conv_rate);

                // Convert item rates: assume current rates are in INR
                (frm.doc.items || []).forEach(item => {
                    if (!item.rate) return;
                    const new_rate = flt(item.rate / conv_rate, 4);
                    frappe.model.set_value(item.doctype, item.name, "rate", new_rate);
                });
                frm.refresh_field("items");

                frappe.show_alert({
                    message: __("Rates converted to {0}. 1 {0} = {1} INR.", [frm.doc.currency, flt(conv_rate, 2)]),
                    indicator: "blue",
                }, 5);
            },
        });
    },
});

// ── List-view: Guard to prevent accidental bulk-cancellation of drafts ────────
(function () {
    frappe.router.on("change", function () {
        var route = frappe.get_route();
        if (!route || route[0] !== "List" || !IB_DOCTYPES.includes(route[1])) return;

        setTimeout(function () {
            if (!cur_list) return;
            $(cur_list.wrapper)
                .off("change.ib_cancel_guard")
                .on(
                    "change.ib_cancel_guard",
                    ".list-row-checkbox, .list-header-subject input[type='checkbox']",
                    function () {
                        setTimeout(function () {
                            if (!cur_list) return;
                            var checked = cur_list.get_checked_items();
                            if (!checked.length) return;
                            
                            // Only allow bulk cancel if all selected rows are Submitted (1)
                            var all_submitted = checked.every(function (r) {
                                return r.docstatus == 1;
                            });
                            
                            cur_list.page.actions_btn_group
                                .find("a[data-label='Cancel']")
                                .closest("li")
                                .toggle(all_submitted);
                        }, 60);
                    }
                );
        }, 400);
    });
}());