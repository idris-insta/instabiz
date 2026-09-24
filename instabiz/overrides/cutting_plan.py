# Copyright (c) 2026, Instabiz and contributors
# License: MIT
"""Todo 38 (+ todo44 seed) — Cutting plan thin wrapper over mfg_plans."""
from __future__ import annotations

import frappe

from instabiz.overrides import mfg_plans as _mp

MARKER = _mp.MARKER


@frappe.whitelist()
def create_plan_from_wo(work_order: str, plan_type: str = "cutting"):
	"""Create / open a Cutting plan from IB Work Order lines (includes soft undersize tips)."""
	return _mp.create_plan_from_wo(work_order, plan_type="cutting")


@frappe.whitelist()
def create_cutting_plan_from_wo(work_order: str):
	return create_plan_from_wo(work_order)


@frappe.whitelist()
def suggest_cutting_undersize(*args, **kwargs):
	"""Soft undersize suggestion — never auto-applied (todo44 seed)."""
	return _mp.suggest_cutting_undersize(*args, **kwargs)


@frappe.whitelist()
def suggest_multi_width_layout(*args, **kwargs):
	return _mp.suggest_multi_width_layout(*args, **kwargs)


@frappe.whitelist()
def probe_todo38(*args, **kwargs):
	return _mp.probe_todo38(*args, **kwargs)


def ensure_todo38_setup():
	return _mp.ensure_todo38_setup()
