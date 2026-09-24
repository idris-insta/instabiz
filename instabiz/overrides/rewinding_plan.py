# Copyright (c) 2026, Instabiz and contributors
# License: MIT
"""Todo 38 — Rewinding plan thin wrapper over mfg_plans."""
from __future__ import annotations

import frappe

from instabiz.overrides import mfg_plans as _mp

MARKER = _mp.MARKER


@frappe.whitelist()
def create_plan_from_wo(work_order: str, plan_type: str = "rewinding"):
	"""Create / open a Rewinding plan from IB Work Order lines."""
	return _mp.create_plan_from_wo(work_order, plan_type="rewinding")


@frappe.whitelist()
def create_rewinding_plan_from_wo(work_order: str):
	return create_plan_from_wo(work_order)


@frappe.whitelist()
def suggest_multi_width_layout(*args, **kwargs):
	return _mp.suggest_multi_width_layout(*args, **kwargs)


@frappe.whitelist()
def probe_todo38(*args, **kwargs):
	return _mp.probe_todo38(*args, **kwargs)


def ensure_todo38_setup():
	return _mp.ensure_todo38_setup()
