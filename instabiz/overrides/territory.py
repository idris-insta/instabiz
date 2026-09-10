"""instabiz.overrides.territory

Hide the tree root "All Territories" from every Territory link picker, list view
and report query. It's the structural root of the Territory tree — never valid
data to select (e.g. on Lead Sales Team, Customer, Lead). The tree view itself
is unaffected (it builds via get_children, not this query condition).
"""
import frappe

_ROOT = "All Territories"


def territory_query_conditions(user=None):
	return f"`tabTerritory`.`name` != {frappe.db.escape(_ROOT)}"
