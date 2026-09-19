import frappe

from instabiz.overrides.portal import get_portal_customer

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/portal"
		raise frappe.Redirect
	customer = get_portal_customer(throw=False)
	context.no_customer = not customer
	context.customer_name = frappe.db.get_value("Customer", customer, "customer_name") if customer else ""
	context.show_sidebar = False
	context.no_breadcrumbs = True
	return context
