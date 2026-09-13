"""
instabiz.overrides.permissions

Shared row-level permission helpers for sales documents.

Privileged roles (System Manager, Sales Manager) see all documents.
All other users see only documents they own (owner) or are assigned to
(custom_sales_person_user).
"""

import frappe

_PRIVILEGED_ROLES = {"System Manager", "Sales Manager"}


def _is_privileged(user):
    # Primary check: does the user have any of the privileged roles directly?
    if _PRIVILEGED_ROLES & set(frappe.get_roles(user)):
        return True
    # Fallback: check the role profile name — covers cases where the Role
    # Profile "Sales Manager" was not configured to propagate the "Sales Manager"
    # role to the user's Has Role table
    profile = frappe.db.get_value("User", user, "role_profile_name") or ""
    return profile in _PRIVILEGED_ROLES


def _sales_doc_query_conditions(doctype, user):
    """Return a SQL WHERE fragment limiting list results to the current user.

    Privileged users receive "1=1" (match everything) rather than "" (empty).
    Returning "" is falsy — Frappe treats it as "no custom condition" and falls
    back to its own DocType if_owner logic, which may restrict custom roles.
    Returning "1=1" is truthy — Frappe uses it as the sole condition and skips
    the fallback, so privileged users genuinely see all documents.
    """
    if not user:
        user = frappe.session.user
    if _is_privileged(user):
        return "1=1"
    u = frappe.db.escape(user)
    # If custom_sales_person_user is set use it exclusively (respects reassignment).
    # Fall back to owner when the field is NULL or empty string (pre-deployment docs).
    return (
        f"(`tab{doctype}`.`custom_sales_person_user` = {u}"
        f" OR ((`tab{doctype}`.`custom_sales_person_user` IS NULL"
        f" OR `tab{doctype}`.`custom_sales_person_user` = '')"
        f" AND `tab{doctype}`.`owner` = {u}))"
    )


def _sales_doc_has_permission(doc, ptype, user):
    """Allow access only if the user is assigned to the document."""
    if not user:
        user = frappe.session.user
    if _is_privileged(user):
        return True
    # Allow create and new unsaved docs — custom_sales_person_user not set yet
    if ptype == "create" or not doc.name:
        return True
    assigned = doc.get("custom_sales_person_user")
    if assigned:
        # Field is set — use it exclusively (respects reassignment)
        return assigned == user
    # Field is NULL (doc pre-dates the sales person tracking) — fall back to owner
    return doc.owner == user


# ── Customer: restrict Sales Users to their assignments + owned records ───────

def _is_sales_user_only(user):
    """True when user has Sales User role but NO privileged role.
    Accounts, HR, Purchase, Stock roles etc. all bypass restriction.
    """
    if not user:
        user = frappe.session.user
    roles = set(frappe.get_roles(user))
    if _PRIVILEGED_ROLES & roles:
        return False
    return "Sales User" in roles


def customer_query_conditions(user):
    """Sales Users see only customers they own, are permanently assigned to,
    shared with them, or unhandled (no custom_sales_person_user) customers
    from their Lead Sales Team territories or daily board assignments.

    Critically: daily board assignments (IB Customer Assignment) and territory
    fallback only surface customers with NO permanent custom_sales_person_user.
    This prevents Idris- or manager-owned customers from leaking into a
    Sales User's list just because they were assigned for a visit.

    Everyone else (Sales Manager, Accounts, System Manager …) sees all.
    """
    if not user:
        user = frappe.session.user
    if not _is_sales_user_only(user):
        return "1=1"
    u = frappe.db.escape(user)
    return (
        f"(`tabCustomer`.`custom_sales_person_user` = {u}"
        # owner fallback only when custom_sales_person_user is not set on this customer
        # (covers legacy docs created before the field existed; does NOT re-surface
        # reassigned customers where the owner ≠ current assignee)
        f" OR ((`tabCustomer`.`custom_sales_person_user` IS NULL"
        f"      OR `tabCustomer`.`custom_sales_person_user` = '')"
        f"     AND `tabCustomer`.`owner` = {u})"
        # Shared explicitly with this user — always visible regardless of ownership
        f" OR `tabCustomer`.`name` IN ("
        f"   SELECT `customer` FROM `tabIB Customer Share`"
        f"   WHERE `shared_with` = {u}"
        f" )"
        # Daily board assignment — only for pool customers (no permanent owner)
        f" OR ("
        f"   (`tabCustomer`.`custom_sales_person_user` IS NULL"
        f"    OR `tabCustomer`.`custom_sales_person_user` = '')"
        f"   AND `tabCustomer`.`name` IN ("
        f"     SELECT `customer` FROM `tabIB Customer Assignment`"
        f"     WHERE `assigned_to` = {u}"
        f"     AND `assigned_date` >= DATE_SUB(CURDATE(), INTERVAL 90 DAY)"
        f"   )"
        f" )"
        # Territory fallback — only for pool customers in the user's territory
        f" OR ("
        f"   (`tabCustomer`.`custom_sales_person_user` IS NULL"
        f"    OR `tabCustomer`.`custom_sales_person_user` = '')"
        f"   AND `tabCustomer`.`territory` IN ("
        f"     SELECT t.`territory`"
        f"     FROM `tabLead Sales Team Territory` t"
        f"     JOIN `tabLead Sales Team Member` m ON m.`parent` = t.`parent`"
        f"     WHERE m.`user` = {u}"
        f"   )"
        f" ))"
    )


def customer_has_permission(doc, ptype, user):
    """Allow create always; for existing docs check ownership, permanent assignment, share,
    or unhandled customer in the user's Lead Sales Team territories."""
    if not user:
        user = frappe.session.user
    if not _is_sales_user_only(user):
        return True
    if ptype == "create" or not doc.name:
        return True
    # Permanent assignment takes priority over ownership — prevents the original
    # creator from retaining access after a customer is reassigned to someone else
    assigned_user = (
        doc.get("custom_sales_person_user")
        or frappe.db.get_value("Customer", doc.name, "custom_sales_person_user")
    )
    if assigned_user:
        return assigned_user == user
    # No permanent assignee — fall back to owner (legacy docs pre-dating the field)
    if doc.owner == user:
        return True
    # Shared with this user via IB Customer Share
    if frappe.db.exists("IB Customer Share", {"customer": doc.name, "shared_with": user}):
        return True
    # IB Customer Assignment — only for pool customers (no permanent custom_sales_person_user).
    # A daily-board visit assignment for a manager-owned customer does NOT grant access.
    if not assigned_user and frappe.db.exists(
        "IB Customer Assignment", {"customer": doc.name, "assigned_to": user}
    ):
        return True
    # Unhandled customer in the user's Lead Sales Team territories
    if not assigned_user:
        territory = doc.get("territory") or frappe.db.get_value("Customer", doc.name, "territory")
        if territory:
            in_territory = frappe.db.sql(
                """
                SELECT 1
                FROM `tabLead Sales Team Territory` t
                JOIN `tabLead Sales Team Member` m ON m.`parent` = t.`parent`
                WHERE m.`user` = %s AND t.`territory` = %s
                LIMIT 1
                """,
                (user, territory),
            )
            if in_territory:
                return True
    return False


# ── Per-doctype entry points registered in hooks.py ──────────────────────────

def quotation_query_conditions(user):
    return _sales_doc_query_conditions("Quotation", user)

def quotation_has_permission(doc, ptype, user):
    return _sales_doc_has_permission(doc, ptype, user)


def sales_order_query_conditions(user):
    return _sales_doc_query_conditions("Sales Order", user)

def sales_order_has_permission(doc, ptype, user):
    return _sales_doc_has_permission(doc, ptype, user)


def delivery_note_query_conditions(user):
    return _sales_doc_query_conditions("Delivery Note", user)

def delivery_note_has_permission(doc, ptype, user):
    return _sales_doc_has_permission(doc, ptype, user)


def sales_invoice_query_conditions(user):
    return _sales_doc_query_conditions("Sales Invoice", user)

def sales_invoice_has_permission(doc, ptype, user):
    return _sales_doc_has_permission(doc, ptype, user)


# ── Payment Entry: Sales User restricted to their own handled customers ───────
# Accounts User/Accounts Manager keep their existing full (unrestricted)
# access — this only narrows the plain Sales User role, which previously had
# no Payment Entry permission at all (2026-09-03, user request: "let sales
# user add payment entry only for their assigned/handled customers"). Payment
# Entry has no custom_sales_person_user of its own — scoping is a live join
# through party -> Customer.custom_sales_person_user, so it always reflects
# who currently handles that customer (not a frozen creation-time snapshot
# like Quotation/SO/DN/SI use).
_PE_UNRESTRICTED_ROLES = _PRIVILEGED_ROLES | {"Accounts User", "Accounts Manager"}

def payment_entry_query_conditions(user):
    if not user:
        user = frappe.session.user
    if _PE_UNRESTRICTED_ROLES & set(frappe.get_roles(user)):
        return "1=1"
    if "Sales User" not in frappe.get_roles(user):
        return "1=1"  # no scoped role at all — leave to standard doctype permission
    u = frappe.db.escape(user)
    return (
        f"(`tabPayment Entry`.`party_type` = 'Customer'"
        f" AND `tabPayment Entry`.`party` IN"
        f" (SELECT name FROM `tabCustomer` WHERE custom_sales_person_user = {u}))"
    )

def payment_entry_has_permission(doc, ptype, user):
    if not user:
        user = frappe.session.user
    if _PE_UNRESTRICTED_ROLES & set(frappe.get_roles(user)):
        return True
    if "Sales User" not in frappe.get_roles(user):
        return True
    if ptype == "create" or not doc.name:
        return True
    if doc.party_type != "Customer" or not doc.party:
        return False
    return frappe.db.get_value("Customer", doc.party, "custom_sales_person_user") == user


# ── Salary Slip: Employee role scoped to their own payslip only ──────────────
# Core HRMS's own Salary Slip DocPerm grants role "Employee" (and "Employee
# Self Service") read=1 with if_owner=0 - unrestricted, company-wide read
# access for anyone holding the plain Employee role, which is effectively
# every real user in this app. Confirmed live: a plain Sales User
# (zaid.khan@, roles Employee/Sales User/Team Leader, no HR role) could read
# another employee's disposable test Salary Slip directly by name via
# frappe.has_permission - a real payroll-privacy gap, not something
# instabiz's own permission hardening had reached yet. HR Manager/HR User
# already have their own unrestricted read=1 rows and are left untouched -
# a has_permission controller hook can only DENY, never grant beyond the
# base DocPerm (see frappe/permissions.py's has_controller_permissions
# docstring), so there is no risk of this hook accidentally widening access
# for any role.
_SS_PRIVILEGED_ROLES = {"HR Manager", "HR User"}

def _salary_slip_own_employee(user):
    return frappe.db.get_value("Employee", {"user_id": user}, "name")

def salary_slip_query_conditions(user=None):
    if not user:
        user = frappe.session.user
    if _SS_PRIVILEGED_ROLES & set(frappe.get_roles(user)):
        return ""
    employee = _salary_slip_own_employee(user)
    if not employee:
        return "1=0"
    return f"`tabSalary Slip`.employee = {frappe.db.escape(employee)}"

def salary_slip_has_permission(doc, ptype, user):
    if not user:
        user = frappe.session.user
    if _SS_PRIVILEGED_ROLES & set(frappe.get_roles(user)):
        return None
    employee = _salary_slip_own_employee(user)
    if not employee:
        return False
    return doc.employee == employee
