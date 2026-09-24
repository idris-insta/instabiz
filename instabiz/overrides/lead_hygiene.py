"""instabiz.overrides.lead_hygiene

Process Cold Lead pile (Idris 2026-09-21):
1. Batch-sync ERPNext status <-> custom_status + temperature + score.
2. Win-back already nudges stale cold leads (winback.py).
3. Redistribute chronically stale Cold Leads (no activity 60d+, still Cold Lead,
   never progressed) via territory round-robin — capped per day so we don't
   reshuffle the whole 3k pile overnight.
"""
from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, cint, nowdate

from instabiz.overrides.lead import (
	_CUSTOM_TO_ERP_STATUS,
	_STATUS_TO_TEMP,
	_do_assign,
	compute_lead_score,
)

STALE_DAYS = 60
DAILY_REASSIGN_CAP = 80


@frappe.whitelist()
def process_cold_lead_pile(sync_limit=500, reassign_limit=None, dry_run=0):
	"""Run sync + optional RR redistrib. Called daily and manually.

	Rewrites status on hundreds of Leads and can hand ownership to another rep,
	so a plain Sales User must not be able to trigger it from the console.
	"""
	if frappe.session.user != "Administrator" and not (
		{"Sales Manager", "System Manager"} & set(frappe.get_roles())
	):
		frappe.throw(_("Only a Sales Manager can run lead hygiene."), frappe.PermissionError)
	dry_run = cint(dry_run)
	reassign_limit = cint(reassign_limit) if reassign_limit is not None else DAILY_REASSIGN_CAP
	synced = _batch_sync_statuses(limit=cint(sync_limit) or 500, dry_run=dry_run)
	reassigned = _reassign_stale_cold_leads(limit=reassign_limit, dry_run=dry_run)
	if not dry_run:
		frappe.db.commit()
	return {"synced": synced, "reassigned": reassigned, "dry_run": dry_run}


def run_daily_lead_hygiene():
	return process_cold_lead_pile(sync_limit=800, reassign_limit=DAILY_REASSIGN_CAP, dry_run=0)


def _batch_sync_statuses(limit=500, dry_run=0):
	rows = frappe.db.sql(
		"""
		SELECT name, status, custom_status, custom_lead_temperature
		FROM tabLead
		WHERE IFNULL(status,'') NOT IN ('Converted', 'Do Not Contact')
		ORDER BY modified DESC
		LIMIT %s
		""",
		limit,
		as_dict=True,
	)
	n = 0
	for r in rows:
		custom = (r.custom_status or "").strip()
		if not custom:
			# default blank pipeline → Cold Lead
			custom = "Cold Lead"
		want_status = _CUSTOM_TO_ERP_STATUS.get(custom)
		want_temp = _STATUS_TO_TEMP.get(custom)
		updates = {}
		if not r.custom_status:
			updates["custom_status"] = "Cold Lead"
		if want_status and r.status != want_status:
			updates["status"] = want_status
		if want_temp and r.custom_lead_temperature != want_temp:
			updates["custom_lead_temperature"] = want_temp
		if updates and not dry_run:
			frappe.db.set_value("Lead", r.name, updates, update_modified=False)
			# refresh score
			doc = frappe.get_doc("Lead", r.name)
			compute_lead_score(doc)
			frappe.db.set_value("Lead", r.name, "custom_lead_score", doc.custom_lead_score, update_modified=False)
			n += 1
		elif updates:
			n += 1
	return n


def _reassign_stale_cold_leads(limit=80, dry_run=0):
	"""Cold Lead, no meaningful progress, stale 60d → RR in territory."""
	if not cint(frappe.conf.get("ib_lead_round_robin_enabled", 0)):
		return 0
	cutoff = add_days(nowdate(), -STALE_DAYS)
	rows = frappe.db.sql(
		"""
		SELECT name, territory, lead_owner, modified
		FROM tabLead
		WHERE custom_status = 'Cold Lead'
		  AND IFNULL(status,'') NOT IN ('Converted', 'Do Not Contact')
		  AND IFNULL(territory,'') != ''
		  AND modified < %s
		  AND IFNULL(custom_next_follow_up_date, '2000-01-01') < %s
		ORDER BY modified ASC
		LIMIT %s
		""",
		(cutoff, cutoff, limit * 3),
		as_dict=True,
	)
	done = 0
	for r in rows:
		if done >= limit:
			break
		# skip if recently activity-logged
		recent = frappe.db.exists(
			"Comment",
			{
				"reference_doctype": "Lead",
				"reference_name": r.name,
				"creation": [">=", cutoff],
			},
		)
		if recent:
			continue
		if dry_run:
			done += 1
			continue
		doc = frappe.get_doc("Lead", r.name)
		old = doc.lead_owner
		# clear owner so _do_assign will set new (assign_lead_owner skips if set)
		doc.lead_owner = None
		_do_assign(doc)
		if doc.lead_owner and doc.lead_owner != old:
			frappe.get_doc({
				"doctype": "Comment",
				"comment_type": "Info",
				"reference_doctype": "Lead",
				"reference_name": doc.name,
				"content": _(
					"Cold Lead hygiene: reassigned from {0} to {1} (stale {2}+ days, round-robin)."
				).format(old or "—", doc.lead_owner, STALE_DAYS),
			}).insert(ignore_permissions=True)
			done += 1
	return done