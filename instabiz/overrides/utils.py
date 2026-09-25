"""instabiz.overrides.utils"""
import frappe
from frappe import _
from frappe.utils import flt

# Users who must never be swept into automatic rotation: never a recipient
# of an auto-assigned lead or dormant/regular pool customer, and their own
# owned customers are never auto-reassigned away by the dormant-escalation
# sweep. Explicit per-user exemption (2026-09-24, user request) — a Sales
# Manager can otherwise still be a legitimate rotation participant, this is
# not role-based.
ROTATION_EXEMPT_USERS = {"sales1@instabizsolutions.com"}  # Nazim Ansari


def build_multi_token_where(fields, search):
	"""Multi-token search condition: every whitespace-separated token in
	`search` must match at least one of `fields` (LIKE), tokens ANDed together.
	Same "AND of tokens, OR of fields" shape already used ad-hoc in several
	custom-page search endpoints — use this instead of rewriting it per page.

	    where, params = build_multi_token_where(["l.lead_name", "l.company_name"], "acme mum")
	    # where  = "(l.lead_name LIKE %s OR l.company_name LIKE %s) AND (l.lead_name LIKE %s OR l.company_name LIKE %s)"
	    # params = ["%acme%", "%acme%", "%mum%", "%mum%"]

	Returns ("", []) if search is blank — caller should skip appending the
	condition/params entirely in that case (don't AND onto an empty string).
	"""
	tokens = [t for t in (search or "").strip().split() if t]
	if not tokens:
		return "", []
	clauses = []
	params = []
	for token in tokens:
		like = f"%{token}%"
		clauses.append("(" + " OR ".join(f"{f} LIKE %s" for f in fields) + ")")
		params.extend([like] * len(fields))
	return " AND ".join(clauses), params


def build_multi_token_where_named(fields, search, prefix="tok"):
	"""Same as build_multi_token_where, but for query sites that build params as
	a dict with %(name)s placeholders instead of a positional list — merge the
	returned dict into your existing params dict (keys are unique per call
	given a distinct `prefix`, so multiple calls in one query won't collide).

	    cond, extra = build_multi_token_where_named(["e.employee_name", "a.employee"], search, "att")
	    if cond:
	        conditions.append(cond)
	        params.update(extra)
	"""
	tokens = [t for t in (search or "").strip().split() if t]
	if not tokens:
		return "", {}
	clauses = []
	out_params = {}
	for i, token in enumerate(tokens):
		key = f"{prefix}_{i}"
		out_params[key] = f"%{token}%"
		clauses.append("(" + " OR ".join(f"{f} LIKE %({key})s" for f in fields) + ")")
	return " AND ".join(clauses), out_params


# ── Location → company billing address + GSTIN ───────────────────────────────
LOCATION_COMPANY_ADDRESS = {
    "maharashtra": "Instabiz Solutions India Pvt Ltd-Billing-1",
    "gujarat":     "Instabiz Gujarat-Billing",
    "chennai":     "INSTABIZ SOLUTIONS CHENNAI-Billing",
}

LOCATION_COMPANY_GSTIN = {
    "maharashtra": "27AAECI3431Q1Z8",
    "gujarat":     "24AAECI3431Q1ZE",
    "chennai":     "33AAECI3431Q1ZF",
}

LOCATION_COST_CENTER = {
    "maharashtra": "Maharashtra - IB",
    "gujarat":     "Gujarat - IB",
    "chennai":     "Chennai - IB",
}

# ── Location → warehouse (for place of dispatch) ──────────────────────────────
LOCATION_WAREHOUSE = {
    "maharashtra": "MAHARASHTRA - IB",
    # GUJARAT - IB became a group warehouse 2026-08-13 (3 floor sub-warehouses
    # added for inter-floor stock transfer tracking) — a group warehouse can't
    # hold stock or be transacted against, so every doc that used to default
    # its set_warehouse here now defaults to the Ground Floor leaf instead.
    "gujarat":     "Ground Floor - GUJARAT - IB",
    "chennai":     "CHENNAI - IB",
}

# GST state code (first 2 digits of GSTIN) → ERPNext Territory name.
# Shared by lead.py (Lead territory derivation) and ib_transport.py (transporter
# location derivation) — single source of truth, do not duplicate.
GSTIN_STATE_MAP = {
    "01": "Jammu and Kashmir",  "02": "Himachal Pradesh",
    "03": "Punjab",              "04": "Chandigarh",
    "05": "Uttarakhand",         "06": "Haryana",
    "07": "Delhi",               "08": "Rajasthan",
    "09": "Uttar Pradesh",       "10": "Bihar",
    "11": "Sikkim",              "12": "Arunachal Pradesh",
    "13": "Nagaland",            "14": "Manipur",
    "15": "Mizoram",             "16": "Tripura",
    "17": "Meghalaya",           "18": "Assam",
    "19": "West Bengal",         "20": "Jharkhand",
    "21": "Odisha",              "22": "Chhattisgarh",
    "23": "Madhya Pradesh",      "24": "Gujarat",
    "25": "Daman and Diu",       "26": "Dadra and Nagar Haveli",
    "27": "Maharashtra",         "28": "Andhra Pradesh",
    "29": "Karnataka",           "30": "Goa",
    "31": "Lakshadweep",         "32": "Kerala",
    "33": "Tamil Nadu",          "34": "Puducherry",
    "35": "Andaman and Nicobar Islands", "36": "Telangana",
    "37": "Andhra Pradesh",      "38": "Ladakh",
}


def territory_from_gstin(gstin: str):
    """Return Frappe Territory name from GSTIN state code, or None."""
    gstin = (gstin or "").strip()
    if len(gstin) < 2:
        return None
    state_name = GSTIN_STATE_MAP.get(gstin[:2])
    if not state_name:
        return None
    return frappe.db.get_value("Territory", state_name) or None

# ── Dimension fields carried across all transaction child rows ────────────────
DIMENSION_FIELDS = [
    "color",
    "width_mm",
    "length_mtr",
    "qty_pkg",
    "total_pkg",
    "ib_brand",
    "ib_marking",
    "custom_branding",
    "custom_marking",
    "custom_thickness",
    "custom_specifications",
    "custom_description",
]

# ── Parent-level fields carried across document chain ─────────────────────────
PARENT_FIELDS = ["custom_transport", "transport_gst", "booking_for"]

# ── Customer + address fields shared across all mapper postprocess functions ──
ADDRESS_CONTACT_FIELDS = [
    "customer_address",
    "shipping_address_name",
    "address_display",
    "shipping_address",
    "contact_person",
    "contact_display",
    "contact_mobile",
    "contact_email",
    "territory",
    "customer_group",
]

# ── Field map entries shared by every mapper in the Q→SO→DN→SI chain ─────────
# Each mapper merges this with its own doc-link field (e.g. name→quotation).
COMMON_PARENT_FIELD_MAP = {
    "customer":              "customer",
    "customer_name":         "customer_name",
    "customer_address":      "customer_address",
    "shipping_address_name": "shipping_address_name",
    "contact_person":        "contact_person",
    "contact_display":       "contact_display",
    "territory":             "territory",
    "customer_group":        "customer_group",
    "currency":              "currency",
    "selling_price_list":    "selling_price_list",
    "price_list_currency":   "price_list_currency",
    "plc_conversion_rate":   "plc_conversion_rate",
    "conversion_rate":       "conversion_rate",
    "custom_location":       "custom_location",
    "custom_reference_po":   "custom_reference_po",
    "custom_sales_person":   "custom_sales_person",
    "custom_sales_person_user": "custom_sales_person_user",
}

COMMON_CHILD_FIELD_MAP = {
    "custom_branding":  "custom_branding",
    "custom_marking":   "custom_marking",
    "custom_thickness": "custom_thickness",
}

# ─────────────────────────────────────────────────────────────────────────────
# Sales person helpers
# ─────────────────────────────────────────────────────────────────────────────

def set_sales_person(doc):
    """Auto-populate custom_sales_person_user (email) then custom_sales_person (display).

    Uses frappe.session.user — not doc.owner — so the actual logged-in user is
    credited even when doc.owner resolves to 'Administrator'.
    Guard conditions ensure values already carried via mapper are never overwritten.
    """
    if not doc.get("custom_sales_person_user"):
        doc.custom_sales_person_user = frappe.session.user
    if not doc.get("custom_sales_person"):
        full_name = frappe.db.get_value("User", doc.custom_sales_person_user, "full_name")
        if full_name:
            doc.custom_sales_person = full_name


def sync_sales_team(doc):
    """Mirror custom_sales_person into ERPNext's sales_team child table.

    Keeps native Sales Person analytics/reports in sync.
    Returns silently if the doctype has no sales_team table or if the
    Sales Person master record does not exist. Never adds duplicate rows.
    """
    if not frappe.get_meta(doc.doctype).get_field("sales_team"):
        return

    sp_value = (doc.get("custom_sales_person") or "").strip()
    if not sp_value:
        return

    sp_name, commission_rate = frappe.db.get_value(
        "Sales Person", {"sales_person_name": sp_value}, ["name", "commission_rate"]
    ) or (None, None)
    if not sp_name:
        return

    for row in doc.get("sales_team") or []:
        if row.sales_person == sp_name:
            return

    doc.append("sales_team", {
        "sales_person": sp_name,
        "allocated_percentage": 100,
        "commission_rate": commission_rate or 0,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Status remap mixin
# ─────────────────────────────────────────────────────────────────────────────

class IbStatusMixin:
    """Mixin for all IB sales document classes.

    Remaps ERPNext's internal status values to IB display labels after every
    set_status() call. Also handles _validate_selects() by temporarily
    swapping back to a safe ERPNext value ("Draft") so Frappe's select-field
    validator doesn't reject our custom labels.

    Subclasses must declare:
        STATUS_MAP = {"ERPNext status": "IB label", ...}
    """
    STATUS_MAP: dict = {}

    def set_status(self, update=False, status=None, update_modified=True):
        super().set_status(update=update, status=status, update_modified=update_modified)
        if self.status in self.STATUS_MAP:
            self.status = self.STATUS_MAP[self.status]
            if update:
                self.db_set("status", self.status, update_modified=update_modified)

    def _validate_selects(self):
        remapped = self.status
        if remapped in self.STATUS_MAP.values():
            self.status = "Draft"
        super()._validate_selects()
        self.status = remapped


# ─────────────────────────────────────────────────────────────────────────────
# Generic reopen helper
# ─────────────────────────────────────────────────────────────────────────────

def reopen_sales_doc(doctype, name, item_doctype, pre_checks=None, extra_steps=None):
    """Reopen a cancelled IB sales document, resetting it back to Draft (docstatus=0).

    doctype       : "Quotation", "Sales Order", etc.
    name          : document name
    item_doctype  : child item table name e.g. "Quotation Item"
    pre_checks    : callable(name) — raise frappe.ValidationError to block reopen
    extra_steps   : callable(doc) — runs inside the try block after child row reset,
                    before set_status (e.g. reverting linked doc statuses)
    """
    doc = frappe.get_doc(doctype, name)
    frappe.has_permission(doctype, "cancel", doc=doc, throw=True)

    if doc.docstatus != 2:
        frappe.throw(_("Only a cancelled {0} can be reopened.").format(doctype))

    if pre_checks:
        pre_checks(name)

    try:
        frappe.db.set_value(doctype, name, "docstatus", 0)
        # Child item rows carry docstatus=2 after cancellation, making them
        # read-only even when the parent returns to Draft — reset them too.
        frappe.db.sql(
            f"UPDATE `tab{item_doctype}` SET docstatus=0 WHERE parent=%s", name
        )
        frappe.db.sql(
            "UPDATE `tabSales Taxes and Charges`"
            " SET docstatus=0 WHERE parent=%s AND parenttype=%s",
            (name, doctype),
        )
        doc.reload()
        if extra_steps:
            extra_steps(doc)
        doc.set_status(update=True)
    except Exception:
        frappe.db.rollback()
        raise

    doc.add_comment("Edit", _("Reopened by {0}").format(frappe.session.user))
    frappe.msgprint(
        _("{0} {1} has been reopened.").format(doctype, name),
        indicator="green",
        alert=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Mapper helpers
# ─────────────────────────────────────────────────────────────────────────────

def item_postprocess(source_item, target_item, source_doc):
    """Shared get_mapped_doc postprocess callback — copies all dimension fields."""
    map_dimension_fields(source_item, target_item)


def apply_location_cost_center(doc):
    """Set cost_center on parent + every item/tax row from LOCATION_COST_CENTER.

    Runs on SO / DN / SI validate() so GL entries carry the correct cost center.
    Always overwrites — location is authoritative for cost center allocation.
    """
    loc = (doc.get("custom_location") or "").lower()
    cc = LOCATION_COST_CENTER.get(loc)
    if not cc:
        return
    doc.cost_center = cc
    for item in doc.get("items") or []:
        item.cost_center = cc
    for tax in doc.get("taxes") or []:
        tax.cost_center = cc


# ─────────────────────────────────────────────────────────────────────────────
# Field copy helpers
# ─────────────────────────────────────────────────────────────────────────────

ROLL_UOMS = {"PCS", "PC", "NOS", "NO", "ROLL", "ROLLS", "UNIT"}


def roll_area(item_code, uom, width_mm, length_mtr):
    """m² in one roll (width mm × length m) when the item is stocked in SQMT and the
    line counts rolls; 0 otherwise. Tape items are stocked in SQMT but sold in
    rolls — without this every roll counted as 1 m²."""
    if not (flt(width_mm) and flt(length_mtr)) or (uom or "").strip().upper() not in ROLL_UOMS or not item_code:
        return 0
    if frappe.get_cached_value("Item", item_code, "stock_uom") != "SQMT":
        return 0
    return flt(width_mm) / 1000 * flt(length_mtr)


def apply_roll_area(doc):
    """Rows in rolls with width and length: conversion factor = m² per roll, so
    stock qty, reservations and stock ledger count real m²."""
    for item in doc.get("items") or []:
        area = roll_area(item.get("item_code"), item.get("uom"), item.get("width_mm"), item.get("length_mtr"))
        if area:
            item.conversion_factor = area
            if item.meta.get_field("stock_qty"):
                item.stock_qty = flt(item.get("qty")) * area


def dimension_qty(uom, width_mm, length_mtr, qty_pkg, total_pkg):
    """Qty the dimensions imply, or None when they don't imply one.

    The single copy of the rule. Quotation has always worked this way; every
    other document that takes items goes through here too, so an item reads and
    computes the same wherever it is added.

    Square Meter:  (width_mm / 1000) * length_mtr * qty_pkg * total_pkg
    Any other UOM: qty_pkg * total_pkg

    Returns None on an incomplete set — a row with total_pkg still blank may
    carry a hand-typed qty, and zeroing it out on save is never what was meant.
    A can of aerosol has no width and never will; that is the None case, not a
    missing-data case.
    """
    uom = (uom or "").strip().upper()
    width_mm, length_mtr = flt(width_mm), flt(length_mtr)
    qty_pkg, total_pkg = flt(qty_pkg), flt(total_pkg)

    if uom == "SQMT":
        if width_mm and length_mtr and qty_pkg and total_pkg:
            return (width_mm / 1000) * length_mtr * qty_pkg * total_pkg
        return None
    if qty_pkg and total_pkg:
        return qty_pkg * total_pkg
    return None


def recalculate_items(doc):
    """
    For every item row, derive qty from dimensions then amount from qty * rate.

    Formula lives in dimension_qty(); amount and the roll conversion factor are
    the parts specific to a priced sales document.
    Rolls of an SQMT item: conversion factor = m² per roll (apply_roll_area)
    """
    apply_roll_area(doc)
    if doc.get("is_return"):
        return

    for item in doc.get("items") or []:
        # Row already priced in the source document — preserve qty, recalc amount only
        if item.get("against_sales_order") or item.get("delivery_note"):
            item.amount = round(flt(item.get("qty")) * flt(item.get("rate")), 2)
            continue

        uom        = (item.get("uom") or "").strip()
        width_mm   = flt(item.get("width_mm"))
        length_mtr = flt(item.get("length_mtr"))
        qty_pkg    = flt(item.get("qty_pkg"))
        total_pkg  = flt(item.get("total_pkg"))
        rate       = flt(item.get("rate"))

        derived = dimension_qty(uom, width_mm, length_mtr, qty_pkg, total_pkg)
        if derived is not None:
            item.qty = derived

        item.amount = round(flt(item.get("qty")) * rate, 2)


def recalc_item_margins(doc):
    """
    custom_valuation_rate/custom_margin_pct are both no_copy — Frappe's
    Duplicate clears them (to None) and nothing re-derives them until a user
    manually re-touches the row's rate in the browser (form.js's
    _ib_update_margin). Fill them in here, but ONLY when genuinely blank
    (custom_valuation_rate is None — the post-duplicate/brand-new-row state).
    A row that already has a real value (even 0.0, from a prior normal save)
    is left untouched: valuation_rate is a live moving-average that drifts
    with every stock transaction, so recomputing it on every save would
    silently change an old quotation's margin on any unrelated re-save.
    """
    for item in doc.get("items") or []:
        if item.get("custom_valuation_rate") is not None:
            continue
        cost = 0
        if item.get("item_code"):
            cost = flt(frappe.db.get_value("Item", item.item_code, "valuation_rate"))
        item.custom_valuation_rate = cost
        rate = flt(item.get("rate"))
        item.custom_margin_pct = round(flt((rate - cost) / rate * 100), 1) if (rate and cost) else 0


def recalculate_purchase_items(doc):
	"""
	For purchase docs (PO / GRN / PI):
	  - ROLL items where stock_uom=SQMT: enforce rate = custom_sqmt_rate × conversion_factor
	  - qty from the row's dimensions, the same rule Quotation uses (dimension_qty).
	    Buying the same roll should read and compute the same as selling it.
	"""
	if doc.get("is_return"):
		return
	for item in doc.get("items") or []:
		sqmt_rate = float(item.get("custom_sqmt_rate") or 0)
		cf        = float(item.get("conversion_factor") or 1)
		uom       = (item.get("uom") or "").strip().upper()
		stock_uom = (item.get("stock_uom") or "").strip().upper()
		if sqmt_rate and uom == "ROLL" and stock_uom == "SQMT" and cf > 0:
			item.rate = round(sqmt_rate * cf, 2)
			item.price_list_rate = item.rate  # prevent super().validate() from resetting to 0

		derived = dimension_qty(uom, item.get("width_mm"), item.get("length_mtr"),
			item.get("qty_pkg"), item.get("total_pkg"))
		if derived is not None:
			item.qty = round(derived, 6)


def map_dimension_fields(source_item, target_item):
    """Copy all dimension + brand/marking custom fields from source to target child row."""
    for field in DIMENSION_FIELDS:
        value = source_item.get(field)
        if value is not None:
            target_item.set(field, value)


def map_parent_fields(source_doc, target_doc):
    """Copy transport fields from parent source doc to parent target doc."""
    for field in PARENT_FIELDS:
        value = source_doc.get(field)
        if value is not None:
            target_doc.set(field, value)


def map_address_contact_fields(source_doc, target_doc):
    """Copy address + contact fields from source to target parent doc.

    Also rebuilds address_display and shipping_address from the linked
    Address doctype to avoid carrying stale pre-rendered HTML blobs.
    """
    for field in ADDRESS_CONTACT_FIELDS:
        value = source_doc.get(field)
        if value:
            target_doc.set(field, value)

    try:
        from frappe.contacts.doctype.address.address import get_address_display  # pyright: ignore[reportMissingImports]
        if target_doc.get("customer_address"):
            target_doc.address_display = get_address_display(target_doc.customer_address)
        if target_doc.get("shipping_address_name"):
            target_doc.shipping_address = get_address_display(target_doc.shipping_address_name)
    except Exception:
        frappe.log_error(
            title="Address display rebuild failed",
            message=frappe.get_traceback(),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Document transfer helper (used by Employee Exit Handover)
# ─────────────────────────────────────────────────────────────────────────────

def transfer_documents(doctype, owner_field, names, to_user,
                       owner_set_value=None,
                       display_name_field=None,
                       handover_ref=None):
    """Batch-reassign ownership of `names` in `doctype` to `to_user`.

    owner_set_value     : exact value to write into owner_field. When None,
                          to_user (email) is used. Pass this when owner_field
                          is a Data field storing e.g. User.first_name rather
                          than the user's email address (e.g. custom_sales_person).
    display_name_field  : optional second field updated with the new user's
                          full_name (e.g. custom_lead_owner_name on Lead).
    handover_ref        : Employee Exit Handover name stamped on audit comments.

    Returns the count of documents updated.
    """
    if not names:
        return 0

    if isinstance(names, str):
        import json as _json
        names = _json.loads(names)

    names = list(names)

    if not frappe.db.exists("User", to_user):
        frappe.throw(_("User {0} not found").format(to_user))

    full_name   = frappe.db.get_value("User", to_user, "full_name") or to_user
    field_value = owner_set_value if owner_set_value is not None else to_user

    set_parts  = [f"`{owner_field}` = %s"]
    set_values = [field_value]

    if display_name_field:
        set_parts.append(f"`{display_name_field}` = %s")
        set_values.append(full_name)

    placeholders = ", ".join(["%s"] * len(names))
    frappe.db.sql(
        f"UPDATE `tab{doctype}` SET {', '.join(set_parts)} WHERE `name` IN ({placeholders})",
        set_values + names,
    )

    now   = frappe.utils.now()
    actor = frappe.session.user

    if handover_ref:
        content = _(
            "Reassigned from {0} to {1} as part of exit handover {2}"
        ).format(actor, full_name, handover_ref)
    else:
        content = _("Ownership transferred to {0}").format(full_name)

    rows = [
        (frappe.generate_hash(length=10), doctype, name, content, actor, now, now, actor)
        for name in names
    ]
    frappe.db.sql(
        "INSERT INTO `tabComment`"
        " (name, comment_type, reference_doctype, reference_name,"
        "  content, owner, creation, modified, modified_by, docstatus, published, seen)"
        " VALUES " + ", ".join(
            ["(%s, 'Info', %s, %s, %s, %s, %s, %s, %s, 0, 0, 0)"] * len(rows)
        ),
        [v for row in rows for v in row],
    )

    return len(names)


# ── Document attachment stamping + tamper guard ───────────────────────────────

def _stamp_document_attachments(doc, fieldname="custom_document_attachments"):
	"""Stamp uploaded_by/uploaded_on the first time a document row gets a file.

	Child table row controllers do NOT get their own validate() called by Frappe
	during a parent save (confirmed — Document.run_method only invokes hooks for
	the parent) — this has to run from the parent's own validate() instead.
	"""
	from frappe.utils import now_datetime

	for row in doc.get(fieldname) or []:
		if not row.attachment:
			continue
		if not row.uploaded_by:
			row.uploaded_by = frappe.session.user
		if not row.uploaded_on:
			row.uploaded_on = now_datetime()


def _guard_document_attachments(doc, fieldname="custom_document_attachments"):
	"""Once uploaded, a document row (LR copy, receipt, advance payment
	screenshot, etc.) can only be removed or have its file swapped by
	Sales Manager / System Manager — everyone else can add rows freely, but
	can't delete or silently swap out proof documents already on record.
	"""
	from instabiz.overrides.permissions import _is_privileged

	_stamp_document_attachments(doc, fieldname)

	if _is_privileged(frappe.session.user):
		return
	if doc.is_new():
		return

	# get_doc_before_save() only returns a value if something else already
	# populated it earlier in the request (e.g. version tracking) — it does NOT
	# lazily fetch on its own. Force a real fetch of the pre-save state here, or
	# this guard silently no-ops and a non-privileged user can delete/swap freely.
	doc.load_doc_before_save()
	old_doc = doc.get_doc_before_save()
	if not old_doc:
		return

	old_rows = {r.name: r.attachment for r in (old_doc.get(fieldname) or [])}
	if not old_rows:
		return
	new_rows = {r.name: r.attachment for r in (doc.get(fieldname) or []) if r.name}

	for row_name, old_attachment in old_rows.items():
		if row_name not in new_rows:
			frappe.throw(
				_("Only Sales Manager or System Manager can remove an uploaded document."),
				frappe.PermissionError,
			)
		if new_rows[row_name] != old_attachment:
			frappe.throw(
				_("Only Sales Manager or System Manager can replace an uploaded document's file."),
				frappe.PermissionError,
			)


# ── Item lifecycle enforcement ────────────────────────────────────────────────

def _check_item_lifecycle(doc):
	"""Block save if any row contains a discontinued item."""
	discontinued = []
	for row in doc.get("items") or []:
		if not row.item_code:
			continue
		if frappe.db.get_value("Item", row.item_code, "custom_is_discontinued"):
			discontinued.append(f"Row {row.idx}: {row.item_code}")

	if discontinued:
		frappe.throw(
			_("Cannot save — the following items are discontinued:") + "<br>" + "<br>".join(discontinued),
			title=_("Discontinued Item"),
		)


# ── Customer-specific item spec check ─────────────────────────────────────────

def _check_customer_item_spec(doc):
	"""Warn if any row deviates from a customer-agreed spec."""
	customer = doc.get("customer")
	if not customer:
		return

	warnings = []
	for row in doc.get("items") or []:
		if not row.item_code:
			continue
		spec = frappe.db.get_value(
			"IB Customer Item Spec",
			{"customer": customer, "item_code": row.item_code},
			["custom_width_mm", "custom_thickness"],
			as_dict=True,
		)
		if not spec:
			continue

		mismatches = []
		if spec.custom_width_mm and row.get("width_mm") and abs(row.width_mm - spec.custom_width_mm) > 0.01:
			mismatches.append(f"Width: order {row.width_mm} mm vs agreed {spec.custom_width_mm} mm")
		if spec.custom_thickness and row.get("custom_thickness") and row.custom_thickness != spec.custom_thickness:
			mismatches.append(f"Thickness: order '{row.custom_thickness}' vs agreed '{spec.custom_thickness}'")

		if mismatches:
			warnings.append(f"Row {row.idx} ({row.item_code}): " + "; ".join(mismatches))

	if warnings:
		frappe.msgprint(
			_("Customer spec mismatch — please verify before proceeding:")
			+ "<br>" + "<br>".join(warnings),
			title=_("Spec Mismatch"),
			indicator="orange",
		)


@frappe.whitelist()
def update_item_dimensions(parent_doctype, parent_name, items):
	"""Update dimension fields on submitted Q / SO item rows and recalculate qty + totals."""
	import json
	from frappe.utils import flt as _flt

	data = json.loads(items)
	parent = frappe.get_doc(parent_doctype, parent_name)
	if not frappe.has_permission(parent_doctype, "write", parent):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	child_doctype = parent_doctype + " Item"
	_dim_fields = [
		"color", "width_mm", "length_mtr", "qty_pkg", "total_pkg",
		"custom_thickness", "custom_branding", "custom_marking",
	]

	for d in data:
		if not d.get("docname"):
			continue

		child = frappe.get_doc(child_doctype, d["docname"])

		for field in _dim_fields:
			if field in d:
				child.set(field, d[field] if d[field] not in ("", None) or not isinstance(d.get(field), str) else None)

		if d.get("rate") is not None:
			child.rate = _flt(d["rate"])

		# Recalculate qty from dimensions (mirrors recalculate_items logic)
		uom        = (child.uom or "").strip()
		width_mm   = _flt(child.width_mm)
		length_mtr = _flt(child.length_mtr)
		qty_pkg    = _flt(child.qty_pkg)
		total_pkg  = _flt(child.total_pkg)

		if uom == "SQMT":
			if width_mm and length_mtr and qty_pkg and total_pkg:
				child.qty = round((width_mm / 1000) * length_mtr * qty_pkg * total_pkg, 6)
		else:
			if qty_pkg and total_pkg:
				child.qty = qty_pkg * total_pkg

		child.amount = round(_flt(child.qty) * _flt(child.rate), 2)
		child.flags.ignore_validate_update_after_submit = True
		child.save(ignore_permissions=True)

	# Recalculate parent totals
	parent.reload()
	parent.flags.ignore_validate_update_after_submit = True
	parent.calculate_taxes_and_totals()
	parent.save(ignore_permissions=True)
	frappe.db.commit()
	return {"status": "ok"}
