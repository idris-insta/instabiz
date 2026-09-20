"""Regression tests for money and status paths.

Run: bench --site <site> run-tests --app instabiz --module instabiz.tests.test_core_paths
"""
import pathlib
import subprocess
import sys

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from instabiz.overrides import auto_absent, payment_entry
from instabiz.overrides.ib_status import status_map, stored_statuses


class _Doc(frappe._dict):
	def get(self, key, default=None):
		return self[key] if key in self else default


class TestStoredStatuses(FrappeTestCase):
	def test_every_remapped_status_includes_its_stored_label(self):
		for doctype in ("Quotation", "Sales Order", "Delivery Note", "Sales Invoice"):
			for raw, stored in status_map(doctype).items():
				self.assertIn(stored, stored_statuses(doctype, raw), f"{doctype} {raw}")
				self.assertIn(raw, stored_statuses(doctype, raw), f"{doctype} {raw} (legacy rows)")

	def test_known_mappings(self):
		self.assertIn("Pending", stored_statuses("Quotation", "Open"))
		self.assertIn("Cancelled", stored_statuses("Quotation", "Lost"))
		self.assertIn("Confirmed", stored_statuses("Sales Order", "Completed"))
		self.assertIn("Confirmed", stored_statuses("Delivery Note", "Completed"))
		self.assertEqual(stored_statuses("Purchase Order", "Completed"), ("Completed",))

	def test_no_raw_status_literals_in_code(self):
		script = pathlib.Path(frappe.get_app_path("instabiz")).parent / "scripts" / "check_status_literals.py"
		if not script.exists():
			self.skipTest("scripts/ not shipped with this install")
		result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
		self.assertEqual(result.returncode, 0, result.stdout)


class TestAutoReconcile(FrappeTestCase):
	def _run(self, doc):
		calls = []
		orig = frappe.db.sql

		def spy(query, *args, **kwargs):
			if "FOR UPDATE" in str(query) and "tabSales Invoice" in str(query):
				calls.append(query)
				return []
			return orig(query, *args, **kwargs)

		frappe.db.sql = spy
		try:
			payment_entry._auto_reconcile(doc)
		finally:
			frappe.db.sql = orig
		return calls

	def test_on_account_advance_is_not_matched_to_invoices(self):
		doc = _Doc(payment_type="Receive", party_type="Customer", party="_T", references=[],
			paid_amount=100, custom_advance_for_so="SO-X")
		self.assertEqual(self._run(doc), [])

	def test_plain_receipt_is_still_matched(self):
		doc = _Doc(payment_type="Receive", party_type="Customer", party="_T", references=[], paid_amount=100)
		self.assertEqual(len(self._run(doc)), 1)

	def test_payment_with_references_is_left_alone(self):
		doc = _Doc(payment_type="Receive", party_type="Customer", party="_T",
			references=[{"reference_name": "X"}], paid_amount=100)
		self.assertEqual(self._run(doc), [])


class TestAutoAbsentHolidays(FrappeTestCase):
	def test_employee_without_list_uses_company_default(self):
		company = frappe.db.get_single_value("Global Defaults", "default_company")
		if not company:
			self.skipTest("no default company")
		hl = frappe.get_doc({
			"doctype": "Holiday List", "holiday_list_name": "_Test IB Fallback HL",
			"from_date": add_days(nowdate(), -30), "to_date": add_days(nowdate(), 30),
			"holidays": [{"holiday_date": add_days(nowdate(), -1), "description": "t"}],
		}).insert(ignore_permissions=True, ignore_if_duplicate=True)
		previous = frappe.db.get_value("Company", company, "default_holiday_list")
		frappe.db.set_value("Company", company, "default_holiday_list", hl.name)
		frappe.clear_cache()
		try:
			emp = frappe.get_doc({
				"doctype": "Employee", "first_name": "_Test IB Holiday", "gender": "Male",
				"date_of_birth": "1990-01-01", "date_of_joining": "2025-01-01",
				"company": company, "status": "Active",
			}).insert(ignore_permissions=True)
			resolved = auto_absent._resolve_holiday_list(_Doc(name=emp.name, holiday_list=None))
			self.assertEqual(resolved, hl.name)
			self.assertTrue(auto_absent._is_holiday(add_days(nowdate(), -1), resolved))
			self.assertEqual(auto_absent._resolve_holiday_list(_Doc(name=emp.name, holiday_list="X")), "X")
		finally:
			frappe.db.set_value("Company", company, "default_holiday_list", previous)


class TestCreditOverride(FrappeTestCase):
	def setUp(self):
		from instabiz.overrides import permissions, sales_order
		self.so = sales_order
		self.perm = permissions
		self._orig = (sales_order._check_credit_limit, sales_order._check_overdue_block, permissions._is_privileged)
		sales_order._check_credit_limit = lambda doc: frappe.throw("over limit")
		sales_order._check_overdue_block = lambda doc: None
		self.comments = []

	def tearDown(self):
		self.so._check_credit_limit, self.so._check_overdue_block, self.perm._is_privileged = self._orig

	def _doc(self, reason=None):
		doc = _Doc(custom_credit_override_reason=reason)
		doc.add_comment = lambda kind, text: self.comments.append(text)
		return doc

	def test_block_without_reason(self):
		self.perm._is_privileged = lambda user: True
		self.assertRaises(frappe.ValidationError, self.so._run_credit_checks, self._doc())

	def test_rep_cannot_override(self):
		self.perm._is_privileged = lambda user: False
		self.assertRaises(frappe.ValidationError, self.so._run_credit_checks, self._doc("customer paid by cheque"))

	def test_manager_override_is_recorded(self):
		self.perm._is_privileged = lambda user: True
		self.so._run_credit_checks(self._doc("customer paid by cheque"))
		self.assertEqual(len(self.comments), 1)
		self.assertIn("customer paid by cheque", self.comments[0])

	def test_credit_limit_on_overdue_off_by_default(self):
		# IB Sales Settings never saved: credit-limit check runs (it only acts on
		# customers with a limit), 30-day overdue block stays off.
		credit, overdue = [], []
		self.so._check_credit_limit = lambda doc: credit.append(1)
		self.so._check_overdue_block = lambda doc: overdue.append(1)
		orig = self.so.check_advance_approval
		self.so.check_advance_approval = lambda doc: None
		saved = frappe.db.sql("SELECT field, value FROM `tabSingles` WHERE doctype=%s", "IB Sales Settings")
		frappe.db.sql("DELETE FROM `tabSingles` WHERE doctype=%s", "IB Sales Settings")
		conf = frappe.local.conf
		prev = conf.get("ib_so_credit_checks")
		try:
			conf.pop("ib_so_credit_checks", None)
			self.so.CustomSalesOrder.before_submit(self._doc())
			self.assertEqual((credit, overdue), ([1], []))
			conf["ib_so_credit_checks"] = 1  # older switch forces both on
			self.so.CustomSalesOrder.before_submit(self._doc())
			self.assertEqual((credit, overdue), ([1, 1], [1]))
		finally:
			self.so.check_advance_approval = orig
			for field, value in saved:
				frappe.db.sql("INSERT INTO `tabSingles` (doctype, field, value) VALUES (%s, %s, %s)",
					("IB Sales Settings", field, value))
			if prev is None:
				conf.pop("ib_so_credit_checks", None)
			else:
				conf["ib_so_credit_checks"] = prev


class TestSettingsAndHelpers(FrappeTestCase):
	def test_overtime_rates_follow_day_basis(self):
		from unittest.mock import patch

		from instabiz.overrides import overtime

		with patch.object(overtime, "get", return_value="26 days"), patch.object(overtime, "get_float", return_value=8.0):
			self.assertEqual(overtime.rates_for(26000, "2026-09-10"), (1000.0, 125.0))
		with patch.object(overtime, "get", return_value="Days in the month"), patch.object(overtime, "get_float", return_value=8.0):
			self.assertEqual(overtime.rates_for(30000, "2026-09-10"), (1000.0, 125.0))  # September has 30 days

	def test_whatsapp_number_normalised(self):
		from instabiz.overrides.messaging import _normalize_phone

		self.assertEqual(_normalize_phone("98765 43210"), "919876543210")
		self.assertEqual(_normalize_phone("+91-98765-43210"), "919876543210")
		self.assertEqual(_normalize_phone("098765 43210"), "919876543210")
		self.assertEqual(_normalize_phone(""), "")

	def test_item_spec_and_repeated_text(self):
		from instabiz.overrides.print_helpers import _extra_text, item_spec

		row = frappe._dict(item_code="T-48", item_name="Tape 48mm", width_mm=48, length_mtr=65,
			custom_thickness="40 mic", qty_pkg=36, total_pkg=3)
		self.assertEqual(item_spec(row), "48 mm × 65 m · 40 mic · 36 per pkg × 3 pkg")
		self.assertEqual(_extra_text("Tape 48mm", row), "")
		self.assertEqual(_extra_text("Printed logo", row), "Printed logo")

	def test_setting_falls_back_to_old_constant(self):
		from instabiz.overrides import ib_settings

		self.assertEqual(ib_settings.get_int("no_such_field_xyz", 48), 48)
		self.assertTrue(ib_settings.get_check("no_such_field_xyz", True))

class TestDashboards(FrappeTestCase):
	"""Every dashboard has to answer when called — a signature that drifted out
	of step with its page is invisible until someone opens it."""

	RPCS = [
		("instabiz.instabiz.page.ib_main_dashboard.ib_main_dashboard", "get_dashboard_data", {}),
		("instabiz.instabiz.page.ib_hrms_dashboard.ib_hrms_dashboard", "get_hr_overview", {}),
		("instabiz.instabiz.page.ib_finance_dashboard.ib_finance_dashboard", "get_finance_data", {}),
		("instabiz.instabiz.page.ib_procurement_dashboard.ib_procurement_dashboard", "get_procurement_data", {}),
		("instabiz.instabiz.page.ib_collections_dashboard.ib_collections_dashboard", "get_collections_data", {"limit": 5}),
		("instabiz.instabiz.page.ib_customer_health.ib_customer_health", "get_customer_health", {"limit": 5}),
		("instabiz.instabiz.page.ib_business_pulse.ib_business_pulse", "get_pulse_data", {}),
	]

	FILTERED = [
		("instabiz.instabiz.page.ib_main_dashboard.ib_main_dashboard", "get_dashboard_data"),
		("instabiz.instabiz.page.ib_finance_dashboard.ib_finance_dashboard", "get_finance_data"),
		("instabiz.instabiz.page.ib_procurement_dashboard.ib_procurement_dashboard", "get_procurement_data"),
	]

	def test_every_dashboard_rpc_answers(self):
		for module, method, kwargs in self.RPCS:
			with self.subTest(rpc=f"{module}.{method}"):
				result = frappe.get_attr(f"{module}.{method}")(**kwargs)
				self.assertIsInstance(result, dict)
				self.assertTrue(result)

	def test_filters_are_accepted_end_to_end(self):
		args = {"from_date": add_days(nowdate(), -30), "to_date": nowdate(), "location": "GUJARAT"}
		for module, method in self.FILTERED:
			with self.subTest(rpc=f"{module}.{method}"):
				self.assertIsInstance(frappe.get_attr(f"{module}.{method}")(**args), dict)

	def test_dashboards_workspace_targets_exist(self):
		from instabiz.overrides.dashboards import build_dashboards_workspace

		build_dashboards_workspace()
		ws = frappe.get_doc("Workspace", "Dashboards")
		self.assertTrue(ws.links)
		for row in ws.links:
			if row.type == "Card Break":
				continue
			self.assertTrue(frappe.db.exists(row.link_type, row.link_to), f"{row.link_type} {row.link_to}")
		for row in ws.shortcuts:
			self.assertTrue(frappe.db.exists(row.type, row.link_to), f"{row.type} {row.link_to}")

	def test_no_native_dashboard_is_listed_twice(self):
		from instabiz.overrides.dashboards import IB_EQUIVALENT, usable_dashboards

		for name in usable_dashboards():
			self.assertNotIn(name, IB_EQUIVALENT, f"{name} duplicates an Instabiz dashboard")

	def test_number_cards_all_compute(self):
		from instabiz.overrides.dashboards import smoke_dashboards

		self.assertEqual(smoke_dashboards()["failures"]["cards"], [])
