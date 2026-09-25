"""instabiz.overrides.customer_dormant_escalation

Daily scheduler: 3-tier escalation for an OWNED customer with no submitted
Sales Order in a while (2026-09-04, user-designed feature — inactivity basis,
reassign target, and no-override were all explicit user decisions, not
guessed). Same "days since last submitted SO" basis dormant.py/
classify_customer()/the Customer list's recency highlight already use.

  30-59 days  -> bell notification to the owning rep ("heads up")
  60-89 days  -> a second, more urgent bell notification ("second warning")
  90+  days   -> customer is REASSIGNED to the next member of the SAME
                 territory team, round-robin (not to the unowned pool, not a
                 manager queue — explicit user choice)

State is tracked on Customer.custom_dormant_tier ("" / "30" / "60" / "90") —
the highest tier already actioned for the CURRENT inactivity streak. It
resets to "" the moment the customer is active again (days < 30), so a
customer that goes dormant more than once over its lifetime escalates fresh
each time rather than being silently skipped forever after its first cycle.
No rep override/snooze exists (explicit user decision) — the day count is
the only input.

Round-robin state lives on Lead Sales Team.custom_last_rotation_user (the
last member a reassignment landed on for that team) — advanced past the
customer's own outgoing owner if the naive next-in-line would be them.
"""
import frappe
from frappe.utils import date_diff, today

from instabiz.overrides.customer_assignment import _reassign_customer_ownership
from instabiz.overrides.utils import ROTATION_EXEMPT_USERS

_NEVER_ORDERED_DAYS = 99999  # always sorts into the 90+ bucket


def _team_for_territory(territory):
	return frappe.db.get_value("Lead Sales Team Territory", {"territory": territory}, "parent")


def _team_members(team):
	return frappe.get_all(
		"Lead Sales Team Member", filters={"parent": team}, fields=["user"], order_by="idx asc"
	)


def _next_team_member(team, exclude_user):
	"""Round-robin next member of `team`, skipping `exclude_user` (the
	customer's own current/failing owner — reassigning them to themselves
	would be a no-op) even if they're next in the naive rotation order."""
	members = [m.user for m in _team_members(team) if m.user not in ROTATION_EXEMPT_USERS]
	if not members:
		return None
	candidates = [m for m in members if m != exclude_user] or members
	if len(candidates) == 1:
		return candidates[0]

	last = frappe.db.get_value("Lead Sales Team", team, "custom_last_rotation_user")
	if last in candidates:
		idx = candidates.index(last)
		nxt = candidates[(idx + 1) % len(candidates)]
	else:
		nxt = candidates[0]

	frappe.db.set_value("Lead Sales Team", team, "custom_last_rotation_user", nxt, update_modified=False)
	return nxt


def _order_free_days_phrase(days):
	# days can be the _NEVER_ORDERED_DAYS sentinel — never surface the raw
	# number to a real person, say what's actually true instead.
	if days >= _NEVER_ORDERED_DAYS:
		return "has not yet placed an order"
	return f"has not placed an order in {days} days"


def _notify(customer, customer_name, owner, tier, days):
	phrase = _order_free_days_phrase(days)
	if tier == "30":
		subject = f"A check-in is recommended for {customer_name}"
		body = f"{customer_name} {phrase}. A brief check-in would help keep the relationship active."
	else:  # "60"
		subject = f"A follow-up is due for {customer_name}"
		body = (
			f"{customer_name} {phrase}. Should this continue for another month, the account "
			f"will be reassigned to the next representative on the team, so it continues to "
			f"receive proper attention."
		)
	frappe.get_doc({
		"doctype": "Notification Log",
		"for_user": owner,
		"from_user": "Administrator",
		"type": "Alert",
		"document_type": "Customer",
		"document_name": customer,
		"subject": subject[:140],
		"email_content": body,
	}).insert(ignore_permissions=True)


def run_dormant_reassignment_escalation():
	rows = frappe.db.sql(
		"""
		SELECT c.name AS customer, c.customer_name, c.territory,
		       c.custom_sales_person_user AS owner,
		       c.custom_dormant_tier AS tier,
		       MAX(so.transaction_date) AS last_order_date
		FROM `tabCustomer` c
		LEFT JOIN `tabSales Order` so ON so.customer = c.name AND so.docstatus = 1
		WHERE c.disabled = 0
		  AND c.custom_sales_person_user IS NOT NULL AND c.custom_sales_person_user != ''
		  AND c.territory IS NOT NULL AND c.territory != ''
		GROUP BY c.name
		""",
		as_dict=True,
	)

	for row in rows:
		if row.owner in ROTATION_EXEMPT_USERS:
			continue  # never nudged, never rotated — exempt owner, see ROTATION_EXEMPT_USERS

		days = date_diff(today(), row.last_order_date) if row.last_order_date else _NEVER_ORDERED_DAYS
		tier = row.tier or ""

		if days < 30:
			if tier:
				frappe.db.set_value(
					"Customer", row.customer,
					{"custom_dormant_tier": "", "custom_dormant_tier_basis_date": row.last_order_date},
					update_modified=False,
				)
			continue

		if days < 60:
			if not tier:
				_notify(row.customer, row.customer_name, row.owner, "30", days)
				frappe.db.set_value(
					"Customer", row.customer,
					{"custom_dormant_tier": "30", "custom_dormant_tier_basis_date": row.last_order_date},
					update_modified=False,
				)
		elif days < 90:
			if tier in ("", "30"):
				_notify(row.customer, row.customer_name, row.owner, "60", days)
				frappe.db.set_value(
					"Customer", row.customer,
					{"custom_dormant_tier": "60", "custom_dormant_tier_basis_date": row.last_order_date},
					update_modified=False,
				)
		else:
			if tier == "90":
				continue
			team = _team_for_territory(row.territory)
			if not team:
				continue  # nowhere to reassign to — leave tier as-is, don't silently drop the customer
			new_owner = _next_team_member(team, exclude_user=row.owner)
			if not new_owner or new_owner == row.owner:
				continue
			# _reassign_customer_ownership already notifies both the outgoing
			# and incoming owner (a real bell each) — no second notification
			# from here, that would just double up the old owner's inbox for
			# the same event (caught live: reconstructing a 631-customer test
			# run's undo showed exactly 2 "you lost this customer"-shaped
			# notifications per reassignment before this was removed).
			_reassign_customer_ownership(row.customer, new_owner)
			frappe.db.set_value(
				"Customer", row.customer,
				{"custom_dormant_tier": "90", "custom_dormant_tier_basis_date": row.last_order_date},
				update_modified=False,
			)

	frappe.db.commit()
