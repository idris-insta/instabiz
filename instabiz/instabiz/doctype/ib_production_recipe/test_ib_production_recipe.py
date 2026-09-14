# Copyright (c) 2026, Instabiz Solutions India Pvt Ltd and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from instabiz.overrides.mrp import _compute_shortfalls, _explode_demand


class TestIBProductionRecipe(FrappeTestCase):
	def _make_item(self, item_code, item_group="Products"):
		if frappe.db.exists("Item", item_code):
			return item_code
		frappe.get_doc({
			"doctype": "Item",
			"item_code": item_code,
			"item_name": item_code,
			"item_group": item_group,
			"stock_uom": "Nos",
			"is_stock_item": 1,
			# india_compliance makes this mandatory for any is_sales_item once
			# GST Settings.validate_hsn_code is on (it is, live — see item 76 in
			# CLAUDE.md) — the fixture was written before that setting was
			# enabled and started failing all 4 setUp-dependent tests with
			# MandatoryError instead of exercising real Recipe/MRP logic.
			"gst_hsn_code": "39199090",
		}).insert(ignore_permissions=True)
		return item_code

	def setUp(self):
		self.finished = self._make_item("_TEST-MRP-FG-1")
		self.raw = self._make_item("_TEST-MRP-RAW-1")
		# This test runner does not roll back the DB between individual test
		# methods within one `bench run-tests` invocation (only masked before
		# because every DB-touching test here failed identically in setUp on
		# missing gst_hsn_code) — test_creates_recipe and
		# test_rejects_duplicate_pair both use this exact (finished, raw) pair,
		# so a recipe left over from an earlier test method in the same run
		# collides with the "one recipe per pair" uniqueness check before the
		# test under test even gets to run. Clear it defensively so each test
		# method starts from a clean slate regardless of run order.
		frappe.db.delete(
			"IB Production Recipe",
			{"finished_item": self.finished, "recipe_item": self.raw},
		)

	def test_creates_recipe(self):
		doc = frappe.get_doc({
			"doctype": "IB Production Recipe",
			"finished_item": self.finished,
			"recipe_item": self.raw,
			"qty_per": 2.5,
		}).insert(ignore_permissions=True)
		self.assertEqual(doc.qty_per, 2.5)

	def test_rejects_zero_qty_per(self):
		doc = frappe.get_doc({
			"doctype": "IB Production Recipe",
			"finished_item": self.finished,
			"recipe_item": self.raw,
			"qty_per": 0,
		})
		self.assertRaises(frappe.ValidationError, doc.insert, ignore_permissions=True)

	def test_rejects_same_item(self):
		doc = frappe.get_doc({
			"doctype": "IB Production Recipe",
			"finished_item": self.finished,
			"recipe_item": self.finished,
			"qty_per": 1,
		})
		self.assertRaises(frappe.ValidationError, doc.insert, ignore_permissions=True)

	def test_rejects_duplicate_pair(self):
		frappe.get_doc({
			"doctype": "IB Production Recipe",
			"finished_item": self.finished,
			"recipe_item": self.raw,
			"qty_per": 1,
		}).insert(ignore_permissions=True)

		dup = frappe.get_doc({
			"doctype": "IB Production Recipe",
			"finished_item": self.finished,
			"recipe_item": self.raw,
			"qty_per": 3,
		})
		self.assertRaises(frappe.ValidationError, dup.insert, ignore_permissions=True)


class TestMRPCalculation(FrappeTestCase):
	"""Pure-function tests for the demand-explosion and shortfall-detection
	math in instabiz.overrides.mrp — no DB writes, no framework plumbing.
	"""

	def test_explode_demand_single_recipe(self):
		finished_demand = {"FG-1": 100}
		recipes = [{"finished_item": "FG-1", "recipe_item": "RAW-1", "qty_per": 2}]
		self.assertEqual(_explode_demand(finished_demand, recipes), {"RAW-1": 200})

	def test_explode_demand_shared_raw_material(self):
		# Two finished items sharing one raw material must sum, not overwrite.
		finished_demand = {"FG-1": 100, "FG-2": 50}
		recipes = [
			{"finished_item": "FG-1", "recipe_item": "RAW-1", "qty_per": 2},
			{"finished_item": "FG-2", "recipe_item": "RAW-1", "qty_per": 1},
		]
		self.assertEqual(_explode_demand(finished_demand, recipes), {"RAW-1": 250})

	def test_explode_demand_ignores_recipe_with_no_open_demand(self):
		finished_demand = {"FG-1": 100}
		recipes = [
			{"finished_item": "FG-1", "recipe_item": "RAW-1", "qty_per": 2},
			{"finished_item": "FG-2", "recipe_item": "RAW-2", "qty_per": 5},  # no open SO demand
		]
		self.assertEqual(_explode_demand(finished_demand, recipes), {"RAW-1": 200})

	def test_compute_shortfalls_only_returns_deficits(self):
		raw_demand = {"RAW-1": 200, "RAW-2": 50}
		stock_map = {"RAW-1": 120, "RAW-2": 999}
		self.assertEqual(_compute_shortfalls(raw_demand, stock_map), {"RAW-1": 80})

	def test_compute_shortfalls_missing_stock_treated_as_zero(self):
		raw_demand = {"RAW-1": 30}
		stock_map = {}
		self.assertEqual(_compute_shortfalls(raw_demand, stock_map), {"RAW-1": 30})

	def test_compute_shortfalls_exact_stock_match_is_not_a_shortfall(self):
		raw_demand = {"RAW-1": 100}
		stock_map = {"RAW-1": 100}
		self.assertEqual(_compute_shortfalls(raw_demand, stock_map), {})
