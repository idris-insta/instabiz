import re
import frappe
from frappe import _
import urllib.request
import json as _json

from instabiz.overrides.permissions import _is_privileged
from instabiz.overrides.utils import territory_from_gstin as _territory_from_gstin

# --- Lead scoring + pipeline status sync (Idris 2026-09-21) ---
_TEMP_SCORE = {"Hot": 60, "Warm": 30, "Cold": 0}
_STATUS_TO_TEMP = {
	"Hot Lead": "Hot", "Negotiation": "Hot", "Proposal": "Warm", "Qualified": "Warm",
	"Contacted": "Warm", "Cold Lead": "Cold", "Lost": "Cold",
}
_STATUS_BONUS = {
	"Negotiation": 30, "Proposal": 20, "Qualified": 15,
	"Contacted": 5, "Hot Lead": 10, "Converted": 40, "Customer": 40,
}
_CUSTOM_TO_ERP_STATUS = {
	"Cold Lead": "Open", "Hot Lead": "Open", "Contacted": "Open", "Qualified": "Open",
	"Proposal": "Open", "Negotiation": "Open", "Converted": "Converted",
	"Customer": "Converted", "Lost": "Do Not Contact",
}


def sync_lead_statuses(doc, method=None):
	"""Keep Lead.status (ERPNext) and custom_status (pipeline) aligned; fix temperature."""
	custom = (doc.get("custom_status") or "").strip()
	if custom and custom in _CUSTOM_TO_ERP_STATUS:
		want = _CUSTOM_TO_ERP_STATUS[custom]
		if doc.get("status") != want:
			doc.status = want
	if custom and custom in _STATUS_TO_TEMP:
		want_t = _STATUS_TO_TEMP[custom]
		cur_t = doc.get("custom_lead_temperature") or ""
		if custom == "Cold Lead":
			doc.custom_lead_temperature = "Cold"
		elif not cur_t or cur_t == "Cold" or cur_t != want_t:
			doc.custom_lead_temperature = want_t


def compute_lead_score(doc, method=None):
	"""Auto-compute custom_lead_score (0-100) on every save."""
	sync_lead_statuses(doc)
	temp = doc.get("custom_lead_temperature") or _STATUS_TO_TEMP.get(doc.get("custom_status") or "", "Cold")
	score = _TEMP_SCORE.get(temp, 0)
	score += _STATUS_BONUS.get(doc.get("custom_status") or "", 0)
	if doc.get("mobile_no"):
		score += 5
	if doc.get("email_id"):
		score += 5
	if doc.get("custom_product_of_interest") or doc.get("custom_poi"):
		score += 10
	if doc.get("custom_next_follow_up_date"):
		score += 10
	doc.custom_lead_score = min(score, 100)


def get_permission_query_conditions(user):
    """Limit Lead list to rows owned by or assigned to the current user.

    lead_owner is authoritative when set; owner is the fallback for leads
    that pre-date the round-robin assignment feature (lead_owner = NULL/'').
    """
    if not user:
        user = frappe.session.user
    if _is_privileged(user):
        return "1=1"
    u = frappe.db.escape(user)
    return (
        f"(`tabLead`.`lead_owner` = {u}"
        f" OR ((`tabLead`.`lead_owner` IS NULL OR `tabLead`.`lead_owner` = '')"
        f" AND `tabLead`.`owner` = {u}))"
    )


def has_permission(doc, ptype, user):
    """Allow access to a Lead only if the user owns or is assigned to it."""
    if not user:
        user = frappe.session.user
    if _is_privileged(user):
        return True
    # Allow create and new unsaved docs — lead_owner not set yet
    if ptype == "create" or not doc.name:
        return True
    assigned = doc.lead_owner
    if assigned:
        return assigned == user
    return doc.owner == user


def check_duplicate_lead(doc, method=None):
    """Block lead creation if same mobile_no or email_id already exists.

    Root-cause fix (2026-08-28): a duplicate match here is a hard block, not a
    merge — but every real import that hits this block has had to fall back to
    manually updating the existing Lead instead (e.g. reassigning lead_owner,
    see the PACKPLUS import). That workaround never touched territory, so an
    existing Lead's territory — right or wrong — silently outlived every later
    import that happened to re-match the same mobile/email, no matter what the
    new row's own State/GSTIN/pincode said. That's the recurring "Gujarat lead
    shows a Bengaluru territory" bug: not a fuzzy name/city match, and not a
    Territory-tree matching bug (both confirmed exact-name lookups, see
    instabiz.overrides.utils.territory_from_gstin) — the existing record's
    territory was just never re-verified against the new import row.

    Fixed here, not by patching data again: before throwing, re-derive
    territory fresh from *this* row's own GSTIN/pincode (same authoritative
    source set_territory_from_pincode uses for a brand-new Lead) and, if it
    disagrees with the existing Lead's current territory, correct the existing
    record and log an auditable Comment explaining why — so a future import
    hitting the same duplicate can't silently keep carrying a stale value, and
    any correction is visible on the Lead's own timeline instead of invisible.
    """
    existing = None
    if doc.mobile_no:
        existing = frappe.db.get_value(
            "Lead", {"mobile_no": doc.mobile_no}, ["name", "lead_name", "territory"], as_dict=True
        )
    if not existing and doc.email_id:
        existing = frappe.db.get_value(
            "Lead", {"email_id": doc.email_id}, ["name", "lead_name", "territory"], as_dict=True
        )
    if existing:
        _reconcile_territory_on_duplicate(doc, existing)
        link = f'<a href="/app/lead/{existing.name}">{existing.lead_name or existing.name}</a>'
        frappe.throw(
            f"Duplicate lead: {link} already exists with this phone or email.",
            title=_("Duplicate Lead"),
        )


def _reconcile_territory_on_duplicate(doc, existing):
    """Re-derive territory from the *new* row's own data and correct the
    existing (duplicate-matched) Lead if it disagrees. Never inherits the
    existing record's territory onto the new row — the new row's own data is
    always authoritative. No-ops (and logs nothing) if the new row carries no
    derivable GSTIN/pincode, or if the derived value matches what's already
    there."""
    new_territory = _derive_territory_from_row(doc)
    if not new_territory or new_territory == existing.territory:
        return
    old_territory = existing.territory or "(blank)"
    frappe.db.set_value("Lead", existing.name, "territory", new_territory, update_modified=False)
    frappe.get_doc("Lead", existing.name).add_comment(
        "Info",
        _(
            "Territory corrected {0} → {1} during duplicate-lead import "
            "(re-derived from the new row's own GSTIN/pincode, not carried "
            "over from the previously stored value)."
        ).format(old_territory, new_territory),
    )


# GST state code → Territory derivation lives in instabiz.overrides.utils now
# (shared with ib_transport.py) — imported at top of file as _territory_from_gstin.


def _territory_from_pincode(pincode: str):
    """Return (territory, state) from India Post pincode API, or (None, None)."""
    pincode = str(pincode).strip()
    if not re.match(r"^\d{6}$", pincode):
        return None, None
    try:
        url = f"https://api.postalpincode.in/pincode/{pincode}"
        with urllib.request.urlopen(url, timeout=3) as resp:
            data = _json.loads(resp.read().decode())
        if data and data[0].get("Status") == "Success" and data[0].get("PostOffice"):
            state = data[0]["PostOffice"][0].get("State", "")
            territory = frappe.db.get_value("Territory", state) or None
            return territory, state
    except Exception:
        pass
    return None, None


def _derive_territory_from_row(doc):
    """Derive territory purely from this row's own data — GSTIN state code
    first (authoritative), pincode API fallback. Never reads doc.territory or
    any other document; returns None if neither source resolves. Shared by
    set_territory_from_pincode (new Lead insert) and
    _reconcile_territory_on_duplicate (duplicate-match correction) so both
    paths derive territory the exact same way."""
    gstin = (doc.get("custom_gstin") or "").strip()
    if gstin:
        territory = _territory_from_gstin(gstin)
        if territory:
            return territory
    pincode = doc.get("custom_pincode") or ""
    if pincode:
        territory, _ = _territory_from_pincode(pincode)
        if territory:
            return territory
    return None


def set_territory_from_pincode(doc, method=None):
    """Derive territory on Lead insert: GSTIN state code first, pincode fallback."""
    # Never overwrite a territory the row already carries (manually set, or
    # provided directly by an import file/mapping) — this row's own data
    # always wins, but an explicit value already on the row still outranks a
    # derived guess.
    if doc.territory:
        return
    territory = _derive_territory_from_row(doc)
    if territory:
        doc.territory = territory


def assign_lead_owner(doc, method=None):
    """Assign lead_owner via round-robin, or default to the creator.

    Round-robin (via Lead Sales Team) is gated by site_config
    "ib_lead_round_robin_enabled" (default off — Issue #7, 2026-08-04:
    round-robin was misassigning/losing leads, follow-ups getting missed).
    While off, a new Lead's lead_owner defaults to doc.owner (the creator)
    on insert. Manual reassignment by Sales Manager/System Manager still
    works via transfer_leads(). Never overwrites a manually assigned
    lead_owner. Round-robin logic (_do_assign) is left intact, dormant,
    for re-enabling later.
    """
    # Never overwrite a manually assigned lead_owner
    if doc.lead_owner:
        return

    if not frappe.utils.cint(frappe.conf.get("ib_lead_round_robin_enabled", 0)):
        if method != "after_insert":
            return
        full_name = frappe.db.get_value("User", doc.owner, "full_name") or doc.owner
        frappe.db.set_value("Lead", doc.name, {
            "lead_owner":             doc.owner,
            "custom_lead_owner_name": full_name,
        }, update_modified=False)
        doc.lead_owner             = doc.owner
        doc.custom_lead_owner_name = full_name
        return

    if not doc.territory:
        return

    # On update, skip if territory hasn't changed
    if method != "after_insert":
        before = doc.get_doc_before_save()
        if not before:
            # on_update fired immediately after insert — after_insert already handled it
            return
        if before.territory == doc.territory:
            return

    _do_assign(doc)


def _do_assign(doc):
    rows = frappe.db.sql(
        """
        SELECT DISTINCT lst.name
        FROM `tabLead Sales Team` lst
        INNER JOIN `tabLead Sales Team Territory` lstt
            ON lstt.parent = lst.name
        WHERE lstt.territory = %(territory)s
        ORDER BY lst.name ASC
        LIMIT 1
        """,
        {"territory": doc.territory},
        as_dict=True,
    )

    if not rows:
        return

    team_name = rows[0].name

    lock_key = f"ib_rr_{team_name}"
    acquired = frappe.db.sql("SELECT GET_LOCK(%s, 30)", lock_key)[0][0]
    if not acquired:
        frappe.log_error(f"Round-robin lock timeout for team {team_name}", frappe.get_traceback())
        return
    try:
        team = frappe.get_doc("Lead Sales Team", team_name)

        if not team.members:
            return

        idx      = (team.rr_index or 0) % len(team.members)
        member   = team.members[idx]
        next_idx = (idx + 1) % len(team.members)

        full_name = frappe.db.get_value("User", member.user, "full_name") or member.user

        frappe.db.set_value("Lead Sales Team", team.name, "rr_index", next_idx)
        frappe.db.set_value("Lead", doc.name, {
            "lead_owner":             member.user,
            "custom_lead_owner_name": full_name,
        }, update_modified=False)
        doc.lead_owner             = member.user
        doc.custom_lead_owner_name = full_name

        doc.add_comment("Edit", _("Lead auto-assigned to {0} via round-robin").format(full_name))
    finally:
        frappe.db.sql("SELECT RELEASE_LOCK(%s)", lock_key)


@frappe.whitelist()
def get_pincode_info(pincode):
    """Fetch city, district and state for an Indian pincode via India Post API."""
    try:
        url = f"https://api.postalpincode.in/pincode/{pincode}"
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = _json.loads(resp.read().decode())
    except Exception:
        frappe.throw(_("Could not reach pincode lookup service. Please try again."))

    if not data or data[0].get("Status") != "Success" or not data[0].get("PostOffice"):
        return None

    po       = data[0]["PostOffice"][0]
    state    = po.get("State", "")
    district = po.get("District", "")
    city     = po.get("Division", "") or district

    territory = frappe.db.get_value("Territory", state) or None

    return {
        "city":      city,
        "district":  district,
        "state":     state,
        "territory": territory,
    }


@frappe.whitelist()
def set_lead_status(lead, status):
	"""Update custom_status directly — bypasses full validate."""
	VALID = {"Cold Lead", "Hot Lead", "Contacted", "Qualified", "Proposal", "Negotiation", "Converted", "Customer", "Lost"}
	if status not in VALID:
		frappe.throw(_("Invalid status"))
	doc = frappe.get_doc("Lead", lead)
	if not has_permission(doc, "write", frappe.session.user):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	old_status = doc.custom_status or ""
	frappe.db.set_value("Lead", lead, "custom_status", status)
	# frappe.db.set_value bypasses Document events — Lead.on_update (compute_lead_score,
	# status bonus up to 30 pts) never fires from this path. Recompute + persist explicitly
	# so the score picker stays live instead of freezing at whatever it was pre-status-change.
	doc.custom_status = status
	compute_lead_score(doc)
	frappe.db.set_value("Lead", lead, "custom_lead_score", doc.custom_lead_score, update_modified=False)
	if old_status != status:
		actor = frappe.db.get_value("User", frappe.session.user, "full_name") or frappe.session.user
		frappe.get_doc({
			"doctype": "Comment",
			"comment_type": "Info",
			"reference_doctype": "Lead",
			"reference_name": lead,
			"content": f"Status changed: <b>{old_status or '—'}</b> → <b>{status}</b> by {actor}",
			"owner": frappe.session.user,
		}).insert(ignore_permissions=True)
	return status


@frappe.whitelist()
def custom_make_customer(source_name, target_doc=None):
	"""Wrap ERPNext make_customer and carry instabiz custom fields to Customer."""
	from erpnext.crm.doctype.lead.lead import _make_customer
	customer_doc = _make_customer(source_name, target_doc)

	lead = frappe.get_doc("Lead", source_name)

	# Carry territory
	if lead.territory and not customer_doc.territory:
		customer_doc.territory = lead.territory

	# Carry pincode → billing pincode on Customer
	if lead.get("custom_pincode"):
		customer_doc.custom_bt_pincode = lead.custom_pincode

	# Carry city / district / state from lead custom fields
	if lead.get("city"):
		customer_doc.custom_bt_city = lead.city
	if lead.get("custom_district"):
		customer_doc.custom_district = lead.custom_district

	# Carry international flag + country
	if lead.get("custom_is_international"):
		customer_doc.custom_is_international = 1
	if lead.get("custom_country"):
		customer_doc.custom_country = lead.custom_country

	# Wire the sales person user so permissions work immediately
	if lead.lead_owner:
		customer_doc.custom_sales_person_user = lead.lead_owner

	return customer_doc


@frappe.whitelist()
def transfer_leads(leads, to_user):
    """Bulk transfer lead ownership to a given user.

    Restricted to Sales Manager and System Manager only.
    """
    if frappe.session.user != "Administrator" and not any(
        r in frappe.get_roles() for r in ("Sales Manager", "System Manager")
    ):
        frappe.throw(_("Only Sales Managers can transfer leads."), frappe.PermissionError)

    if isinstance(leads, str):
        leads = _json.loads(leads)

    leads = list(leads)

    if not leads:
        return {"transferred": 0, "to": to_user}

    if not frappe.db.exists("User", to_user):
        frappe.throw(_("User {0} not found").format(to_user))

    full_name = frappe.db.get_value("User", to_user, "full_name") or to_user

    placeholders = ", ".join(["%s"] * len(leads))
    old_owners = frappe.db.sql(
        f"SELECT name, lead_owner, lead_name FROM `tabLead` WHERE name IN ({placeholders})",
        leads,
        as_dict=True,
    )
    frappe.db.sql(
        f"UPDATE `tabLead` SET lead_owner = %s, custom_lead_owner_name = %s"
        f" WHERE name IN ({placeholders})",
        [to_user, full_name] + leads,
    )

    now     = frappe.utils.now()
    actor   = frappe.session.user
    content = _("Lead transferred to {0}").format(full_name)
    rows    = [
        (frappe.generate_hash(length=10), lead_name, content, actor, now, now, actor)
        for lead_name in leads
    ]
    frappe.db.sql(
        "INSERT INTO `tabComment`"
        " (name, comment_type, reference_doctype, reference_name, content,"
        "  owner, creation, modified, modified_by, docstatus, published, seen)"
        " VALUES " + ", ".join(["(%s, 'Info', 'Lead', %s, %s, %s, %s, %s, %s, 0, 0, 0)"] * len(rows)),
        [v for row in rows for v in row],
    )
    frappe.db.commit()

    # Bell-notify the new owner and every displaced old owner — same convention
    # as customer_assignment.py's _notify_customer_reassignment: from_user=
    # Administrator, subject capped to 140 chars, any free-text field (lead_name,
    # full_name) escaped before it goes into subject (Frappe's bell dropdown
    # renders Notification Log.subject via .html()).
    safe_to_name = frappe.utils.escape_html(full_name)
    lead_names = [frappe.utils.escape_html(r.lead_name or r.name) for r in old_owners]
    frappe.get_doc({
        "doctype":       "Notification Log",
        "subject":       (_("{0} lead(s) transferred to you").format(len(leads)))[:140],
        "email_content": "<br>".join(lead_names[:50]),
        "for_user":      to_user,
        "from_user":     "Administrator",
        "type":          "Alert",
        "document_type": "Lead",
        "document_name": leads[0],
    }).insert(ignore_permissions=True)

    by_old_owner = {}
    for r in old_owners:
        if r.lead_owner and r.lead_owner != to_user:
            by_old_owner.setdefault(r.lead_owner, []).append(r.lead_name or r.name)

    for old_owner, names in by_old_owner.items():
        subject = _("{0} lead(s) reassigned to {1}").format(len(names), safe_to_name)
        frappe.get_doc({
            "doctype":       "Notification Log",
            "subject":       subject[:140],
            "email_content": "<br>".join(frappe.utils.escape_html(n) for n in names[:50]),
            "for_user":      old_owner,
            "from_user":     "Administrator",
            "type":          "Alert",
            "document_type": "Lead",
        }).insert(ignore_permissions=True)

    return {"transferred": len(leads), "to": full_name}


@frappe.whitelist()
def log_lead_activity(lead, activity_type, outcome, notes, next_follow_up_date=None):
	"""Log a call/meeting/WA/email/visit activity on a Lead timeline."""
	doc = frappe.get_doc("Lead", lead)
	if not has_permission(doc, "write", frappe.session.user):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	VALID_TYPES = {"Call", "Meeting", "WhatsApp", "Email", "Visit"}
	VALID_OUTCOMES = {"Positive", "Neutral", "Negative", "No Answer"}
	if activity_type not in VALID_TYPES:
		frappe.throw(_("Invalid activity type"))
	if outcome not in VALID_OUTCOMES:
		frappe.throw(_("Invalid outcome"))

	actor = frappe.db.get_value("User", frappe.session.user, "full_name") or frappe.session.user
	icon_map = {"Call": "📞", "Meeting": "🤝", "WhatsApp": "💬", "Email": "📧", "Visit": "📍"}

	parts = [f"{icon_map[activity_type]} <b>{activity_type}</b> — Outcome: <b>{outcome}</b>"]
	if notes:
		parts.append(frappe.utils.escape_html(notes).replace("\n", "<br>"))
	if next_follow_up_date:
		parts.append(f"Next follow-up: <b>{next_follow_up_date}</b>")
	parts.append(f"<i>Logged by {actor}</i>")

	frappe.get_doc({
		"doctype": "Comment",
		"comment_type": "Info",
		"reference_doctype": "Lead",
		"reference_name": lead,
		"content": "<br>".join(parts),
		"owner": frappe.session.user,
	}).insert(ignore_permissions=True)

	# Comment.insert() doesn't touch the parent Lead's own modified timestamp,
	# so the Lead list view (default sort: modified DESC) never reflected
	# actual activity recency — only real field/status edits on the Lead
	# itself. Bump it here so logging an activity surfaces the lead to the
	# top, matching what reps actually expect "last touched" to mean.
	frappe.db.set_value(
		"Lead", lead,
		{"modified": frappe.utils.now(), "modified_by": frappe.session.user},
		update_modified=False,
	)

	frappe.db.set_value("Lead", lead, "custom_last_activity_at", frappe.utils.now(), update_modified=False)

	if next_follow_up_date:
		frappe.db.set_value("Lead", lead, "custom_next_follow_up_date", next_follow_up_date, update_modified=False)
		# follow-up-date presence is worth +10 in compute_lead_score(); db.set_value skips
		# the on_update hook that would normally recompute it.
		doc.custom_next_follow_up_date = next_follow_up_date
		compute_lead_score(doc)
		frappe.db.set_value("Lead", lead, "custom_lead_score", doc.custom_lead_score, update_modified=False)

	return "ok"


@frappe.whitelist()
def get_team_member_users(team):
    """Return user emails for all members of a Lead Sales Team (used by list view filter)."""
    rows = frappe.db.sql(
        """
        SELECT m.user
        FROM `tabLead Sales Team Member` m
        INNER JOIN `tabLead Sales Team` lst ON lst.name = m.parent
        WHERE m.parent = %(team)s
          AND m.parenttype = 'Lead Sales Team'
          AND m.user IS NOT NULL
          AND m.user != ''
        """,
        {"team": team},
        as_list=True,
    )
    return [r[0] for r in rows if r[0]]


@frappe.whitelist()
def rectify_lead_territories(dry_run=True):
    """Re-derive territory for all leads using India Post pincode API.

    System Manager / Sales Manager only. Set dry_run=0 to actually update.
    Returns list of {lead, name, old_territory, new_territory} for all changes.
    """
    if not any(r in frappe.get_roles() for r in ("Sales Manager", "System Manager")):
        frappe.throw(_("Only Sales Managers can rectify lead territories."), frappe.PermissionError)

    dry_run = frappe.utils.cint(dry_run)

    leads = frappe.db.sql(
        """
        SELECT name, lead_name, territory,
               IFNULL(custom_pincode, '') AS custom_pincode,
               IFNULL(custom_gstin, '')   AS custom_gstin
        FROM `tabLead`
        WHERE status NOT IN ('Converted', 'Junk')
        ORDER BY creation ASC
        """,
        as_dict=True,
    )

    changes = []
    for lead in leads:
        # Same derivation _reconcile_territory_on_duplicate and
        # set_territory_from_pincode use — GSTIN authoritative, pincode fallback.
        new_territory = _derive_territory_from_row(lead)

        if not new_territory:
            continue
        if new_territory == lead.territory:
            continue

        changes.append({
            "lead": lead.name,
            "name": lead.lead_name or lead.name,
            "old_territory": lead.territory or "",
            "new_territory": new_territory,
        })

        if not dry_run:
            frappe.db.set_value("Lead", lead.name, "territory", new_territory, update_modified=False)

    if not dry_run and changes:
        frappe.db.commit()

    return {
        "dry_run": bool(dry_run),
        "total_leads": len(leads),
        "changes": len(changes),
        "details": changes,
    }
