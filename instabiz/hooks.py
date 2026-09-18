# ── Scheduler events ──────────────────────────────────────────────────────────
scheduler_events = {
    "daily": [
        # Runs on relieving_date — creates handover doc, notifies HR Managers
        "instabiz.overrides.employee_exit.run_exit_handover_daily",
        # Runs on relieving_date + 1 — disables the ERP user account for any employee
        # with a set relieving_date (no status filter — see the function's own docstring)
        "instabiz.overrides.employee_exit.run_user_disable_daily",
        # Rolls over pending assignments and generates tomorrow's customer board
        "instabiz.overrides.customer_assignment.run_daily_assignment",
        # Sends bell notifications for leads with overdue follow-up dates
        "instabiz.overrides.follow_up.run_follow_up_reminders",
        # Quotation expiry alerts (15/7/1 day email) and auto-expire
        "instabiz.overrides.quotation_expiry.run_quotation_expiry",
        # Compute daily customer health scores (payment/orders/complaints/CSAT)
        "instabiz.overrides.customer_score.run_customer_score",
        # Flag customers with no SO in 60 days → ToDo + bell notification
        "instabiz.overrides.dormant.run_dormant_check",
        # 3-tier owned-customer inactivity escalation: 30d notify, 60d second
        # notice, 90d auto-reassign to the next rep on the territory team.
        # Armed 2026-09-18 (user decision) with a cap of 25 reassignments and
        # 25 notices per sales person per day, most-inactive first — the
        # backlog (631 customers already past 90d) drains over several days.
        # Days, cap and on/off live in Instabiz Settings.
        "instabiz.overrides.customer_dormant_escalation.run_dormant_reassignment_escalation",
        # Monthly sales target milestone notifications (50%/75% elapsed + end-of-month)
        "instabiz.overrides.sales_target.run_target_notifications",
        # Alert rep when SO has no DN after 48h
        "instabiz.overrides.fulfillment_sla.run_fulfillment_sla",
        # Stale quotation + cold lead win-back nudges
        "instabiz.overrides.winback.run_winback",
        # Alert purchase team when bin qty <= reorder level
        "instabiz.overrides.reorder_alert.run_reorder_alert",
        # Alert warehouse/purchase managers for batches expiring within 30 days
        "instabiz.overrides.expiry_alert.run_expiry_alert",
        # Alert purchase team for submitted POs with no linked GRN after 7 days
        "instabiz.overrides.po_followup.run_po_followup",
        # Auto-mark absent for employees with no attendance on previous working day
        "instabiz.overrides.auto_absent.run_auto_absent",
        # Alert HR when employee documents (Passport, PAN, etc.) expire within 30/7 days
        "instabiz.overrides.employee_docs.run_employee_doc_expiry",
        # Alert Purchase roles when PO payment due within 7 days
        "instabiz.overrides.vendor_payment_alert.run_vendor_payment_alert",
        # Overdue Sales Invoice reminders: 7d bell to rep, 15d to managers, 30d block + bell
        "instabiz.overrides.overdue_alert.run_overdue_alert",
        "instabiz.overrides.einvoice_age_alert.run_einvoice_age_alert",
        # Alert Accounts/Sales when PDC cheque date is 3 days away
        "instabiz.overrides.pdc_alert.run_pdc_alert",
        # Flag IB Asset Loans past expected_return_date as Overdue + alert HR/borrower
        "instabiz.overrides.asset_loan_alert.run_asset_loan_alert",
        # Casual/Sick/Privilege leave for the current financial year (new FY on
        # 1 April, new joiners next day) — days from Instabiz Settings
        "instabiz.overrides.leave_allocation.run_yearly_leave_allocation",
        # Monthly payroll draft creation — fires daily but only acts on the 7th
        "instabiz.overrides.payroll.run_monthly_payroll_draft",
        # MRP Phase 1 — disabled 2026-08-12 alongside the production data reset,
        # at user's request. Re-enable by uncommenting if raw-material MRP
        # drafting off open SO demand is wanted again.
        # "instabiz.overrides.mrp.run_mrp",
        # Cross-module Correlation: merge open IB Insights across 2+ domains for
        # the same customer within 7 days into one consolidated Insight
        "instabiz.overrides.insight_correlation.run_insight_correlation",
        # Anomaly/Fraud Watch: duplicate PI bill numbers, duplicate payments,
        # off-market SO/Quotation line rates → IB Insight (severity=Critical)
        "instabiz.overrides.insight_correlation.run_fraud_watch",
    ],
    "weekly": [
        # Price Recommender: velocity/margin-driven price suggestions per item into IB Price Suggestion
        "instabiz.overrides.price_recommender.run_weekly_price_suggestions",
        # Draft one Purchase Material Request from Replenishment Suggestions for
        # the buyer to review (Instabiz Settings -> Stock & Buying)
        "instabiz.overrides.auto_replenish.run_weekly_material_request",
    ],
    "cron": {
        # Poll Active Hikvision terminals (Pull/Both sync_mode) for new
        # attendance events every 15 minutes — near-real-time without
        # hammering the device with constant requests.
        "*/15 * * * *": [
            "instabiz.overrides.hikvision.run_hikvision_sync",
        ],
    },
}

# ── Employee Exit Handover: pending document sources ───────────────────────────
# Each entry declares one DocType whose "pending" documents should surface in the
# Employee Exit Handover when the owning employee leaves.
#
# owner_field      : field on the DocType that holds the owner identifier.
# owner_value_from : if set, the owner_field stores a User attribute (e.g.
#                   "first_name") rather than the email. The engine looks up
#                   this attribute from the exiting user's User record to build
#                   the filter and to set the new value on reassignment.
# title_field      : field shown as the document description in the handover.
# module           : display label for the Module column.
# pending_filter   : frappe.get_all-compatible filter dict for "open" docs only.
#
# To add a new module: append one dict here. Zero engine changes required.
exit_handover_sources = [
    {
        "doctype":            "Quotation",
        "owner_field":        "custom_sales_person_user",  # stores user email — unique & stable
        "display_name_field": "custom_sales_person",       # display name updated on reassignment
        "title_field":        "name",
        "module":             "Sales",
        "pending_filter":     {
            # instabiz maps ERPNext "Open"/"Replied"/"Expired" → "Pending"
            "status":    "Pending",
            "docstatus": 1,
        },
    },
    {
        "doctype":            "Sales Order",
        "owner_field":        "custom_sales_person_user",  # stores user email — unique & stable
        "display_name_field": "custom_sales_person",       # display name updated on reassignment
        "title_field":        "name",
        "module":             "Sales",
        "pending_filter":     {
            "status":    ["in", ["Pending", "Dispatched"]],
            "docstatus": 1,
        },
    },
    {
        "doctype":            "Delivery Note",
        "owner_field":        "custom_sales_person_user",
        "display_name_field": "custom_sales_person",
        "title_field":        "name",
        "module":             "Stock",
        "pending_filter":     {
            "docstatus":  0,
            "is_return":  0,   # exclude credit/return DNs
        },
    },
    {
        "doctype":            "Sales Invoice",
        "owner_field":        "custom_sales_person_user",
        "display_name_field": "custom_sales_person",
        "title_field":        "name",
        "module":             "Accounts",
        "pending_filter":     {
            "status":    ["in", ["Draft", "Unpaid", "Overdue"]],
            "docstatus": ["in", [0, 1]],   # exclude cancelled invoices
            "is_return": 0,                # exclude credit notes
        },
    },
]

app_name = "instabiz"
app_title = "Instabiz"
app_publisher = "Instabiz Solutions India Pvt Ltd"
app_description = "Custom ERP extensions for Instabiz"
app_version = "0.0.1"

# ── Fixtures ──────────────────────────────────────────────────────────────────
# Idempotent perf indexes on hot filter columns (overrides/indexes.py)
after_migrate = [
    "instabiz.overrides.indexes.after_migrate",
    "instabiz.overrides.overtime.after_migrate",
]

fixtures = [
    "Custom Field",
    # Default WhatsApp / email wording for the Send buttons (editable in the UI;
    # an edited template is newer than this file, so migrate does not overwrite it)
    "IB Message Template",
    # Quotation / Sales Order print formats used by the list-view Print buttons.
    # They were built in the UI and live only in the database; run
    # "bench --site frontend export-fixtures --app instabiz" once on the dev
    # server to write fixtures/print_format.json, then commit it.
    {"dt": "Print Format", "filters": [["name", "in", ["QPF_V2", "OSPF_V2"]]]},
    {
        "dt": "Workflow",
        "filters": [["document_type", "=", "IB Work Order"]]
    },
    {
        "dt": "Workflow State",
        "filters": [["name", "in", ["In Progress", "Completed", "On Hold", "Cancelled"]]]
    },
    {
        "dt": "Workflow Action Master",
        "filters": [["name", "in", ["Start", "Complete", "Hold", "Resume", "Cancel"]]]
    },
    {
        "dt": "Property Setter",
        "filters": [["doc_type", "in", ["Quotation", "Quotation Item", "Sales Order", "Sales Order Item",
                                          "Lead", "Delivery Note", "Delivery Note Item", "Customer",
                                          "IB Credit Note", "IB Debit Note", "Purchase Invoice",
                                          "Purchase Order", "Purchase Receipt", "Sales Invoice",
                                          "Salary Slip", "IB Work Order", "IB Order Sheet",
                                          # Territory -> "State" label rename (2026-08-31, system-wide,
                                          # label-only — see CLAUDE.md for why the doctype itself can't
                                          # be renamed): every doctype with a Territory Link field.
                                          "C-Form Invoice Detail", "IB Customer Assignment",
                                          "Installation Note", "Lead Sales Team Territory",
                                          "Loyalty Program", "Maintenance Schedule", "Maintenance Visit",
                                          "Opportunity", "POS Invoice", "Pricing Rule",
                                          "Process Statement Of Accounts", "Prospect", "Sales Partner",
                                          "Selling Settings", "Territory", "Territory Item",
                                          "Warranty Claim", "Lead Sales Team"]]]
    },
    {
        # Sales User added 2026-09-03 (user request) — create/write/submit/cancel
        # own Payment Entries, restricted to their own handled customers via
        # permissions.payment_entry_query_conditions/has_permission +
        # payment_entry.enforce_sales_user_own_customer (write-time guard).
        "dt": "Custom DocPerm",
        "filters": [["parent", "=", "Payment Entry"],
                    ["role", "in", ["Sales Manager", "Accounts User", "Accounts Manager", "Sales User"]]]
    },
    {
        # Sales User's if_owner flag on Quotation/Sales Order — was 1, which
        # hard-blocked the row-level "owner OR custom_sales_person_user"
        # reassignment logic in instabiz.overrides.permissions from ever
        # granting access to a reassigned doc's real assignee (Frappe's base
        # DocPerm can only deny beyond what a controller has_permission hook
        # decides, never grant past a stricter base). Fixed live 2026-08-11;
        # exported here so it survives a fresh site setup instead of being a
        # DB-only change with no fixture trail.
        "dt": "Custom DocPerm",
        "filters": [["parent", "in", ["Quotation", "Sales Order"]],
                    ["role", "=", "Sales User"]]
    },
    {
        # Market Segment (standard CRM doctype) had zero Sales User permission —
        # a real Sales User (Mantasha) hit "does not have doctype access" trying
        # to pick a Market Segment on her own Lead. Only Sales Manager had core
        # read/create/write. Adding a Custom DocPerm for one role silently
        # SUPPRESSES every core DocPerm role on that doctype (see
        # frappe.permissions.get_valid_perms — once ANY Custom DocPerm exists
        # for a doctype, core DocPerm rows for it are entirely ignored, not
        # merged) — so Sales Manager's original access had to be re-added here
        # too, as an explicit Custom DocPerm row, or it would have silently lost
        # access. Fixed live 2026-08-25; exported here so it survives a fresh
        # site setup instead of being a DB-only change with no fixture trail.
        "dt": "Custom DocPerm",
        "filters": [["parent", "=", "Market Segment"],
                    ["role", "in", ["Sales User", "Sales Manager"]]]
    },
    {
        # Industry Type (standard Selling doctype, Lead's "Industry" field) —
        # Sales User create-only, Sales Manager full control (2026-09-03, user
        # request). Same Custom DocPerm suppression gotcha as Market Segment
        # above: Sales Master Manager's original core access is replicated
        # unchanged here too, or it would have silently lost access.
        "dt": "Custom DocPerm",
        "filters": [["parent", "=", "Industry Type"],
                    ["role", "in", ["Sales User", "Sales Manager", "Sales Master Manager"]]]
    },
    {
        # Territory ("State"), Campaign, Customer Group — all 3 standard doctypes
        # had zero Sales User create access, blocking a rep from adding a new
        # state/campaign/customer-group inline from a Lead/Customer form
        # (2026-09-08, user request: "give ability to add transport to sales
        # users, and other lists needed for crm"). Same Custom DocPerm
        # suppression gotcha as Market Segment/Industry Type above — every
        # existing core DocPerm row (all permlevels) was replicated unchanged
        # here, with only Sales User's own permlevel-0 `create` flipped to 1
        # (add-only, no write/delete — matches the existing IB Transport/IB
        # Branding convention from 2026-07-24). Also fixed a related bug found
        # in the same pass: the Instabiz workspace's "Transport" shortcut had
        # `restrict_to_role: Sales Manager` even though Sales User already had
        # doctype-level create access since 2026-07-24 — Sales User had zero
        # navigation path to it despite being able to create records via the
        # Link field's "Create a New" dropdown. Cleared (see instabiz.json).
        "dt": "Custom DocPerm",
        "filters": [["parent", "in", ["Territory", "Campaign", "Customer Group"]]]
    },
    {
        "dt": "Purchase Taxes and Charges Template",
        "filters": [["company", "=", "Instabiz Solutions India Pvt Ltd"]]
    },
    {
        "dt": "Sales Taxes and Charges Template",
        "filters": [["company", "=", "Instabiz Solutions India Pvt Ltd"]]
    },
]
# ── Class overrides ───────────────────────────────────────────────────────────
# recalculate_items runs inside each class's validate(), so no need to also
# register it as a doc_event — that would execute it twice per save.
override_doctype_class = {
    "Quotation":         "instabiz.overrides.quotation.CustomQuotation",
    "Sales Order":       "instabiz.overrides.sales_order.CustomSalesOrder",
    "Delivery Note":     "instabiz.overrides.delivery_note.CustomDeliveryNote",
    "Sales Invoice":     "instabiz.overrides.sales_invoice.CustomSalesInvoice",
    "Purchase Order":    "instabiz.overrides.purchase_order.CustomPurchaseOrder",
    "Purchase Receipt":  "instabiz.overrides.purchase_receipt.CustomPurchaseReceipt",
    "Purchase Invoice":  "instabiz.overrides.purchase_invoice.CustomPurchaseInvoice",
    "Customer":          "instabiz.overrides.customer.CustomCustomer",
    "Salary Slip":       "instabiz.overrides.salary_slip.CustomSalarySlip",
}

# ── Server-side doc events ────────────────────────────────────────────────────
# REMOVED: recalculate_* hooks — already handled inside the override classes
# above. Keeping them here caused double execution on every validate.
doc_events = {
    "User": {
        "after_insert": [
            "instabiz.overrides.user.create_sales_person_for_user",
            "instabiz.overrides.user.copy_admin_defaults",
            "instabiz.overrides.user.copy_admin_ui_settings",
        ],
    },
    "Lead Sales Team": {
        # "after_save" is not a real Frappe doc-event (never fired by core) —
        # this hook silently never ran; "on_update" is the correct post-save event.
        "on_update": "instabiz.overrides.customer_assignment.sync_team_leader_role",
    },
    "Lead": {
        "before_insert": [
            "instabiz.overrides.lead.check_duplicate_lead",
            "instabiz.overrides.lead.set_territory_from_pincode",
            "instabiz.overrides.lead.compute_lead_score",
        ],
        "after_insert": "instabiz.overrides.lead.assign_lead_owner",
        "on_update":    [
            "instabiz.overrides.lead.assign_lead_owner",
            "instabiz.overrides.lead.compute_lead_score",
        ],
    },
    "Item": {
        "before_save": [
            "instabiz.overrides.item.set_batch_no_for_fg",
            "instabiz.overrides.item.sync_barcode_field",
        ],
    },
    "Comment": {
        "after_insert": "instabiz.overrides.comment.notify_owner_on_comment",
    },
    "Employee": {
        "after_save": "instabiz.overrides.employee_drive.sync_employee_docs_to_drive",
    },
    "Quotation": {
        "on_update": "instabiz.overrides.document_attachment_sync.sync_document_attachments_to_drive",
    },
    "Sales Order": {
        "on_update": "instabiz.overrides.document_attachment_sync.sync_document_attachments_to_drive",
        "on_submit": [
            "instabiz.overrides.stock_events.publish_stock_update",
            "instabiz.overrides.customer_assignment.mark_assignment_done_on_so",
            "instabiz.overrides.production.on_so_submit_create_order_sheet",
            "instabiz.overrides.customer.update_customer_outstanding_on_si",
        ],
        "on_cancel": [
            "instabiz.overrides.stock_events.publish_stock_update",
            "instabiz.overrides.customer.update_customer_outstanding_on_si",
        ],
    },
    "Delivery Note": {
        "on_update": "instabiz.overrides.document_attachment_sync.sync_document_attachments_to_drive",
        "on_submit": [
            "instabiz.overrides.stock_events.publish_stock_update",
            "instabiz.overrides.dispatch_notification.run_dispatch_notification",
            "instabiz.overrides.ewaybill.run_ewaybill_on_submit",
            "instabiz.overrides.production.mark_wos_delivered",
        ],
        "on_cancel": "instabiz.overrides.stock_events.publish_stock_update",
    },
    "Sales Invoice": {
        "on_update": "instabiz.overrides.document_attachment_sync.sync_document_attachments_to_drive",
        "on_submit": [
            "instabiz.overrides.customer.update_customer_outstanding_on_si",
            "instabiz.overrides.document_attachment_sync.sync_document_attachments_to_drive",
            "instabiz.overrides.einvoice.run_einvoice_on_submit",
        ],
        "on_cancel": "instabiz.overrides.customer.update_customer_outstanding_on_si",
        "on_trash":  "instabiz.overrides.customer.update_customer_outstanding_on_si",
    },
    "Payment Entry": {
        "validate":      "instabiz.overrides.payment_entry.enforce_sales_user_own_customer",
        "before_submit": "instabiz.overrides.payment_entry.before_submit",
        "on_submit":     "instabiz.overrides.payment_entry.on_submit",
        "on_cancel":     "instabiz.overrides.payment_entry.on_cancel",
    },
    "Stock Entry": {
        "on_submit": "instabiz.overrides.stock_events.publish_stock_update",
        "on_cancel": "instabiz.overrides.stock_events.publish_stock_update",
    },
    "Stock Reconciliation": {
        "on_submit": "instabiz.overrides.stock_events.publish_stock_update",
        "on_cancel": "instabiz.overrides.stock_events.publish_stock_update",
    },
    "Salary Structure Assignment": {
        # per-day / per-hour rate beside the monthly base (overtime rate)
        "validate": "instabiz.overrides.overtime.set_assignment_rates",
    },
    "IB Work Order": {
        # wo-per-run (feature/wo-per-run): milestone bell + genealogy cleanup on
        # the new run shape. Old per-(item x stage) handlers in production.py are
        # dead post-migration.
        "on_update": "instabiz.overrides.production_run.on_work_order_update_notify",
        "on_trash": "instabiz.overrides.production_run.reverse_run_stock",
    },
}

# ── Row-level permission restrictions ────────────────────────────────────────
# Users only see documents they own or are assigned to (custom_sales_person_user
# for sales docs, lead_owner for Leads).
# Roles in _PRIVILEGED_ROLES (System Manager, Sales Manager) bypass the filter.
permission_query_conditions = {
    "Lead":              "instabiz.overrides.lead.get_permission_query_conditions",
    "Customer":          "instabiz.overrides.permissions.customer_query_conditions",
    "Quotation":         "instabiz.overrides.permissions.quotation_query_conditions",
    "Sales Order":       "instabiz.overrides.permissions.sales_order_query_conditions",
    "Delivery Note":     "instabiz.overrides.permissions.delivery_note_query_conditions",
    "Sales Invoice":     "instabiz.overrides.permissions.sales_invoice_query_conditions",
    "Employee Checkin":  "instabiz.overrides.checkin.employee_checkin_query_conditions",
    "IB Asset Loan":     "instabiz.instabiz.doctype.ib_asset_loan.ib_asset_loan.get_permission_query_conditions",
    "Payment Entry":     "instabiz.overrides.permissions.payment_entry_query_conditions",
    "Territory":         "instabiz.overrides.territory.territory_query_conditions",
    "Salary Slip":       "instabiz.overrides.permissions.salary_slip_query_conditions",
}

has_permission = {
    "Lead":              "instabiz.overrides.lead.has_permission",
    "Customer":          "instabiz.overrides.permissions.customer_has_permission",
    "Quotation":         "instabiz.overrides.permissions.quotation_has_permission",
    "Sales Order":       "instabiz.overrides.permissions.sales_order_has_permission",
    "Delivery Note":     "instabiz.overrides.permissions.delivery_note_has_permission",
    "Sales Invoice":     "instabiz.overrides.permissions.sales_invoice_has_permission",
    "Employee Checkin":  "instabiz.overrides.checkin.employee_checkin_has_permission",
    "Payment Entry":     "instabiz.overrides.permissions.payment_entry_has_permission",
    "Salary Slip":       "instabiz.overrides.permissions.salary_slip_has_permission",
}

# ── Whitelisted method overrides ──────────────────────────────────────────────
override_whitelisted_methods = {
    # Quotation → Sales Order
    "erpnext.selling.doctype.quotation.quotation.make_sales_order":
        "instabiz.overrides.quotation.custom_make_sales_order",

    # Sales Order → Delivery Note
    "erpnext.selling.doctype.sales_order.sales_order.make_delivery_note":
        "instabiz.overrides.sales_order.custom_make_delivery_note",

    # Delivery Note → Sales Invoice
    "erpnext.stock.doctype.delivery_note.delivery_note.make_sales_invoice":
        "instabiz.overrides.delivery_note.custom_make_sales_invoice",

    # e-Waybill generation — accept transaction_type override from UI
    "india_compliance.gst_india.utils.e_waybill.generate_e_waybill":
        "instabiz.overrides.ewaybill.custom_generate_e_waybill",

    # Lead → Customer (carry territory, pincode, sales person)
    "erpnext.crm.doctype.lead.lead.make_customer":
        "instabiz.overrides.lead.custom_make_customer",

    # Workspace shortcut role filtering
    "frappe.desk.desktop.get_desktop_page":
        "instabiz.overrides.workspace_filter.get_desktop_page",

    # Native Script Report client-script patches (column hides etc.) —
    # additive, chains the original script, see report_patches.py's own
    # module docstring for why this doesn't edit the shipped .js directly.
    "frappe.desk.query_report.get_script":
        "instabiz.overrides.report_patches.get_script",

    # Native Script Report data patches (extra columns computed from data
    # this app has but the native report doesn't know about) — runs the
    # report's own native query first, only appends on top.
    "frappe.desk.query_report.run":
        "instabiz.overrides.report_patches.run",
}

# Exposes Python functions directly as Jinja globals (by function name, not
# dotted path) — used by the "IB Job Order Summary" print format
# (instabiz/instabiz/print_format/ib_job_order_summary/) to reuse the same
# "one actionable Work Order per item" logic the Order-wise list's bulk-print
# button already calls over HTTP. Deliberately NOT called via the `frappe.call`
# Jinja global for this: that goes through frappe.handler.execute_cmd ->
# is_valid_http_method, which reads frappe.local.request.method — fine for a
# real browser print/download click, but throws AttributeError when there is
# no active HTTP request (e.g. frappe.get_print(...) from bench console, or
# any future scheduled/emailed use of this print format). A `jinja` methods
# hook calls the function directly with no HTTP-request dependency at all.
jinja = {
    "methods": [
        # shared data for customer / supplier print formats (print_helpers.py)
        "instabiz.overrides.print_helpers.ib_print",
        "instabiz.overrides.print_helpers.ib_items",
        "instabiz.overrides.print_helpers.ib_hsn_summary",
        "instabiz.overrides.print_helpers.ib_totals",
        "instabiz.overrides.print_helpers.ib_statement",
        "instabiz.overrides.print_helpers.ib_money",
        "instabiz.overrides.print_helpers.ib_date",
        "instabiz.overrides.print_helpers.ib_outstanding_rows",
        "instabiz.overrides.production.get_order_sheet_wo_names",
        "instabiz.overrides.production.get_order_sheet_stage_workflow",
        "instabiz.instabiz.doctype.ib_container_import.ib_container_import.get_barcode_data_uri",
        "instabiz.instabiz.doctype.ib_container_import.ib_container_import.get_qr_data_uri",
    ],
}

# ── Frontend assets ───────────────────────────────────────────────────────────
extend_bootinfo = "instabiz.overrides.ib_settings.boot_session"

app_include_css = ["instabiz.bundle.css"]
app_include_js  = [
    "/assets/instabiz/js/env_badge.js",               # DËV / PRØD environment badge (display-only, hostname-based)
    "https://cdn.jsdelivr.net/npm/iconify-icon@2.1.0/dist/iconify-icon.min.js",  # Iconify icons (CDN)
    "/assets/instabiz/js/ib_color_map.js",            # item color name → hex mapping
    "/assets/instabiz/js/ib_ui.js",                   # IB Design System markup helpers (window.ibUI) — pairs with .ib-ui-* CSS
    "/assets/instabiz/js/ib_icons.js",                # shared SVG icon registry (IB_ICONS.svg)
    "/assets/instabiz/js/ib_stock_common.js",         # shared stock page utilities (IBStock.*)
    "/assets/instabiz/js/pincode.js",               # shared pincode autofill utility
    "/assets/instabiz/js/recalc.js",                # dimension → qty → amount helpers
    "/assets/instabiz/js/form.js",                  # form handlers (depends on recalc.js)
    "/assets/instabiz/js/list_utils.js",            # shared list view helpers (status multiselect, extract filter values)
    "/assets/instabiz/js/comment_popover.js",       # inline comment popover on list rows
    "/assets/instabiz/js/ib_list_print.js",         # shared list view print utility
    "/assets/instabiz/js/report_export.js",         # global: select rows on any Script Report -> branded PDF export
    "/assets/instabiz/js/ib_dash_utils.js",         # dashboard shared: countUp loader, skeleton helpers, fmt
    "/assets/instabiz/js/so_production_panel.js",  # SO form: production stage + dispatch status panel
    "/assets/instabiz/js/ib_simple_payment_dialog.js",  # shared simplified Payment Entry dialog for Sales Users
    "/assets/instabiz/js/ib_messaging.js",           # Send ▸ WhatsApp / Email on sales, purchase and customer forms
    "/assets/instabiz/js/ib_quick_actions.js",       # Repeat order + last-price hint on Quotation / Sales Order
    # ib_stock_dashboard.js is loaded by Frappe's page engine (not global)
    # "/assets/instabiz/js/quotation_list.js",        # Quotation list view
    # "/assets/instabiz/js/sales_order_list.js",      # Sales Order list view
    "/assets/instabiz/js/app_redirect.js"
]

# ── DocType-specific list JS (appended AFTER the app's own list JS) ───────────
doctype_list_js = {
    "Employee Checkin":  "public/js/employee_checkin_list.js",
    "Lead":              "public/js/lead_list.js",
    "Quotation":         "public/js/quotation_list.js",
    "Sales Order":       "public/js/sales_order_list.js",
    "Delivery Note":     "public/js/delivery_note_list.js",
    "Sales Invoice":     "public/js/sales_invoice_list.js",
    "Purchase Order":    "public/js/purchase_order_list.js",
    "Purchase Receipt":  "public/js/purchase_receipt_list.js",
    "Purchase Invoice":  "public/js/purchase_invoice_list.js",
    "Customer":          "public/js/customer_list.js",
    "GL Entry":          "public/js/gl_entry_list.js",
    "IB Container Import": "public/js/ib_container_import_list.js",
    "Payment Entry":     "public/js/payment_entry_list.js",
    "Item":              "public/js/item_list.js",
}

doctype_js = {
    "Lead":                    "public/js/lead.js",
    "Address":                 "public/js/address.js",
    "Customer":                "public/js/customer.js",
    "Quotation":               "public/js/ib_sales_common.js",
    "Sales Order":             "public/js/ib_sales_common.js",
    "Employee Exit Handover":  "public/js/employee_exit_handover.js",
    "IB Sample Request":       "public/js/sample_request.js",
    "Employee":                "public/js/employee.js",
    "Job Applicant":           "public/js/job_applicant.js",
    "Sales Invoice":           "public/js/sales_invoice.js",
    "Delivery Note":           "public/js/delivery_note.js",
    "Purchase Order":          "public/js/ib_purchase_common.js",
    "Purchase Receipt":        "public/js/ib_purchase_common.js",
    "Purchase Invoice":        "public/js/ib_purchase_common.js",
    "IB Credit Note":          "public/js/ib_credit_note.js",
    "IB Debit Note":           "public/js/ib_debit_note.js",
    "Payment Entry":           "public/js/payment_entry.js",
    "Salary Structure Assignment": "public/js/salary_structure_assignment.js",
    "Item":                    "public/js/item.js",
}
