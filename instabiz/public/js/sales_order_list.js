/**
 * sales_order_list.js
 * Sales Order list view — name formatter, sales person column, print button, auto-collapse sidebar.
 */

// Read Order — paste a WhatsApp / email order or attach the customer's PO: the
// intake reads it (Claude when there is credit, else line rules), matches the
// customer and each item by size / colour, and opens for review → Create Draft.
function ib_read_order_dialog() {
    const d = new frappe.ui.Dialog({
        title: __("Read an order"),
        fields: [
            { fieldname: "raw_text", fieldtype: "Small Text", label: __("Paste the order (WhatsApp / email)"),
              description: __("e.g. 48mm x 65m brown - 500 rolls @ 32") },
            { fieldname: "file_url", fieldtype: "Attach", label: __("…or attach the PO (PDF / photo)") },
            { fieldname: "location", fieldtype: "Select", label: __("Location"), reqd: 1,
              options: "\nMAHARASHTRA\nGUJARAT\nCHENNAI" },
        ],
        primary_action_label: __("Read"),
        primary_action(v) {
            if (!v.raw_text && !v.file_url) {
                frappe.msgprint(__("Paste the order or attach a file."));
                return;
            }
            frappe.call({
                method: "instabiz.instabiz.doctype.ib_document_intake.ib_document_intake.quick_read",
                args: v, freeze: true, freeze_message: __("Reading the order…"),
            }).then((r) => {
                d.hide();
                frappe.set_route("Form", "IB Document Intake", r.message);
            });
        },
    });
    d.show();
}

frappe.listview_settings["Sales Order"] = {

    add_fields: ["custom_sales_person", "rounded_total"],

    button: {
        show: () => true,
        get_label: () => __("Print"),
        get_description: () => __("Print Preview"),
        action(doc) {
            window.open(
                "/printview?doctype=Sales%20Order&name=" + encodeURIComponent(doc.name) +
                "&format=OSPF_V2&no_letterhead=1&letterhead=No%20Letterhead&settings=%7B%7D",
                "_blank"
            );
        },
    },

    get_indicator(doc) {
        const map = {
            Draft:      "red",
            Pending:    "orange",
            Dispatched: "blue",
            Confirmed:  "green",
            Cancelled:  "red",
        };
        return [__(doc.status), map[doc.status] || "grey"];
    },

    formatters: {
        name(value, df, doc) {
            const date = frappe.datetime.str_to_user(
                (doc.creation || "").split(" ")[0]
            );
            return `<span title="${value}">${date ? date + "<br>" : ""}<strong>${value}</strong></span>`;
        },
        custom_sales_person(value, df, doc) {
            return doc.owner === frappe.session.user ? __("You") : (value || "");
        },
    },

    onload(listview) {
        ib_setup_list_print(listview, "Sales Order");
        ib_hide_sidebar();
        listview.page.add_inner_button(__("Read Order"), () => ib_read_order_dialog());
        // Filter row order = column order. Live columns: Customer, Amount, Sales
        // Person, Status, Delivery Date, ID (Amount has no filter). Customer is
        // a plain-text customer_name box natively — now an autocomplete
        // suggesting distinct customer names. The date-range control sits at the
        // Delivery Date slot. ID moves out of Frappe's default first slot to sit
        // last in the column-matched group. Sales Team isn't a visible column,
        // so it trails after.
        ib_setup_list_autocomplete_filter(listview, "Sales Order", "customer_name", "Customer");
        ib_setup_list_sales_user_filter(listview, "Sales Order");
        ib_setup_status_multiselect(listview, "Sales Order", [
            "Draft", "Pending", "Dispatched", "Confirmed", "Cancelled",
        ]);
        ib_setup_list_date_filter(listview, "Sales Order", "creation", ["transaction_date", "delivery_date"]);
        ib_setup_list_team_filter(listview, "Sales Order");
        ib_setup_list_multiselect_filter(listview, "Sales Order", "custom_location", "Location",
            ["MAHARASHTRA", "GUJARAT", "CHENNAI"],
            { MAHARASHTRA: "BHIWANDI", GUJARAT: "SARIGRAM" });
        ib_reorder_filter_row(listview, [
            $(".ib-sales-order-customer-name-filter"),
            $(".ib-sales-order-sales-user-filter"),
            $(".ib-sales-order-status-multi-filter"),
            $(".ib-sales-order-custom-location-filter"),
            $(".ib-sales-order-date-range-filter"),
            listview.page.fields_dict.name && listview.page.fields_dict.name.$wrapper,
            $(".ib-sales-order-team-filter"),
        ]);
        ib_setup_so_total_bar(listview);

        // Re-add bar on navigate-back (Frappe calls refresh() on page re-show)
        const _orig_refresh = listview.refresh.bind(listview);
        listview.refresh = function () {
            if (!$(".ib-so-total-bar").length) {
                ib_setup_so_total_bar(listview);
            }
            return _orig_refresh();
        };

        const _orig_render_list = listview.render_list.bind(listview);
        listview.render_list = function () {
            _orig_render_list();
            ib_disable_status_click_filter(listview);
            ib_inject_so_prod_badges(listview);
        };

        frappe.router.on("change", function () {
            const route = frappe.get_route();
            if (!route || route[0] !== "List" || route[1] !== "Sales Order") {
                $(".ib-so-total-bar").remove();
            }
        });
    },
};

// ── SO List: sticky selection total bar ──────────────────────────────────────

function ib_setup_so_total_bar(listview) {
    $(".ib-so-total-bar").remove();
    const $bar = $("<div>").attr("id", "ib-so-total-bar").addClass("ib-so-total-bar");
    const $pill = $("<span>").attr("id", "ib-so-sel-count").addClass("ib-so-sel-pill").text("0 selected");
    const $label = $("<span>").addClass("ib-so-total-label").text("Total");
    const $value = $("<span>").attr("id", "ib-so-total-value").addClass("ib-so-total-value").text("—");
    $bar.append($pill, $label, $value);
    $("body").append($bar);

    // .off().on() keeps binding idempotent across before_render calls
    listview.$result.off("change.ib_so_total").on("change.ib_so_total", "input[type=checkbox]", function () {
        setTimeout(() => ib_update_so_total_bar(listview), 0);
    });
}

// ── Production badge injection ────────────────────────────────────────────────

function ib_inject_so_prod_badges(listview) {
    if (!listview.data || !listview.data.length) return;
    const soNames = listview.data.map(r => r.name).filter(Boolean);
    if (!soNames.length) return;

    frappe.call({
        method: "instabiz.overrides.production.get_so_list_badges",
        args: { sales_orders: soNames },
        callback(r) {
            const badges = r.message || {};
            soNames.forEach(name => {
                const info = badges[name];
                if (!info) return;
                const $row = listview.$result.find(`.list-row[data-name="${CSS.escape(name)}"]`);
                if (!$row.length) return;
                $row.find(".ib-so-prod-badge").remove();
                const $badge = $(`
                    <span class="ib-so-prod-badge" style="
                        display:inline-flex;align-items:center;gap:3px;
                        background:${info.color}15;color:${info.color};
                        border:1px solid ${info.color}40;border-radius:10px;
                        padding:1px 7px;font-size:10px;font-weight:600;
                        white-space:nowrap;vertical-align:middle;margin-left:6px">
                        <iconify-icon icon="lucide:factory" width="9" height="9"></iconify-icon>
                        ${frappe.utils.escape_html(info.badge)}
                    </span>`);
                $row.find(".level-item.list-row-activity").prepend($badge);
            });
        },
    });
}

function ib_update_so_total_bar(listview) {
    const checked = listview.get_checked_items();
    const count   = checked.length;
    const total   = checked.reduce((s, r) => s + (r.rounded_total || 0), 0);

    $("#ib-so-sel-count").text(`${count} order${count !== 1 ? "s" : ""} selected`);
    const formatted = $("<div>").html(frappe.format(total, { fieldtype: "Currency" })).text().trim();
    $("#ib-so-total-value").text(formatted);
    $("#ib-so-total-bar").toggleClass("ib-so-total-bar--active", count > 0);
}