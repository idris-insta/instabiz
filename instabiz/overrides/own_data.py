"""A plain Sales User sees only their own data.

"Own" = customers they handle (Customer.custom_sales_person_user) or that are
shared with them (IB Customer Share), plus documents they made or are assigned
to. Managers (Sales / System) and accounts staff see everything, as before.

- permission_query_conditions / has_permission for the Instabiz doctypes a
  Sales User can read (support tickets, gate passes, credit notes, PDCs, ...);
- locked_user() for Script Reports: a report calls it at the top and limits
  itself to that user (works for view, export and print alike).
"""
import frappe

UNRESTRICTED_ROLES = {"System Manager", "Sales Manager", "Accounts User", "Accounts Manager"}


def locked_user(user=None):
	"""The Sales User whose view is limited to own data; None for everyone else."""
	user = user or frappe.session.user
	if user == "Administrator":
		return None
	roles = set(frappe.get_roles(user))
	if roles & UNRESTRICTED_ROLES or "Sales User" not in roles:
		return None
	return user


def own_customers_sql(user):
	u = frappe.db.escape(user)
	return (f"(SELECT name FROM `tabCustomer` WHERE custom_sales_person_user = {u} "
		f"UNION SELECT customer FROM `tabIB Customer Share` WHERE shared_with = {u})")


def _rules(user):
	u = frappe.db.escape(user)
	own = own_customers_sql(user)
	return {
		"IB Support Ticket": f"(`tabIB Support Ticket`.customer IN {own} OR `tabIB Support Ticket`.assigned_to = {u} "
			f"OR `tabIB Support Ticket`.owner = {u})",
		"IB Gate Pass": f"(`tabIB Gate Pass`.owner = {u} OR (`tabIB Gate Pass`.party_type = 'Customer' "
			f"AND `tabIB Gate Pass`.party IN {own}))",
		"IB Campaign": f"(`tabIB Campaign`.owner = {u} OR `tabIB Campaign`.sales_person = {u})",
		"IB Customer Score": f"`tabIB Customer Score`.customer IN {own}",
		"IB Sales Target": f"`tabIB Sales Target`.sales_user = {u}",
		"IB Sample Request": f"(`tabIB Sample Request`.assigned_to = {u} OR `tabIB Sample Request`.owner = {u} "
			f"OR `tabIB Sample Request`.customer IN {own})",
		"IB Document Intake": f"`tabIB Document Intake`.owner = {u}",
		"IB Credit Note": f"(`tabIB Credit Note`.owner = {u} OR `tabIB Credit Note`.customer IN {own})",
		"IB Customer Assignment": f"`tabIB Customer Assignment`.assigned_to = {u}",
		"IB PDC": f"(`tabIB PDC`.sales_person_user = {u} OR `tabIB PDC`.owner = {u} OR `tabIB PDC`.customer IN {own})",
		"IB Price Suggestion": f"(IFNULL(`tabIB Price Suggestion`.customer, '') = '' "
			f"OR `tabIB Price Suggestion`.customer IN {own})",
		"IB Customer Item Spec": f"`tabIB Customer Item Spec`.customer IN {own}",
		"IB Customer Share": f"(`tabIB Customer Share`.shared_with = {u} OR `tabIB Customer Share`.shared_by = {u})",
	}


DOCTYPES = (
	"IB Support Ticket", "IB Gate Pass", "IB Campaign", "IB Customer Score", "IB Sales Target", "IB Sample Request",
	"IB Document Intake", "IB Credit Note", "IB Customer Assignment", "IB PDC", "IB Price Suggestion",
	"IB Customer Item Spec", "IB Customer Share",
)


def query_conditions(user=None, doctype=None):
	user = user or frappe.session.user
	if not doctype or not locked_user(user):
		return ""
	return _rules(user).get(doctype, "")


def has_permission(doc, ptype=None, user=None):
	user = user or frappe.session.user
	if not locked_user(user) or doc.is_new() or not frappe.db.exists(doc.doctype, doc.name):
		return True
	cond = _rules(user).get(doc.doctype)
	if not cond:
		return True
	return bool(frappe.db.sql(f"SELECT 1 FROM `tab{doc.doctype}` WHERE name = %s AND {cond}", doc.name))


# company-wide sales reports with no per-rep view: managers only
MANAGER_REPORTS = ("IB Daily Sales Report", "IB Territory Report")


def after_migrate():
	for report in MANAGER_REPORTS:
		if frappe.db.exists("Has Role", {"parent": report, "parenttype": "Report", "role": "Sales User"}):
			frappe.db.delete("Has Role", {"parent": report, "parenttype": "Report", "role": "Sales User"})
