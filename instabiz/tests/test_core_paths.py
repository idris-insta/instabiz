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

	def test_checks_off_by_default(self):
		called = []
		self.so._check_credit_limit = lambda doc: called.append(1)
		orig = self.so.check_advance_approval
		self.so.check_advance_approval = lambda doc: None
		try:
			conf = frappe.local.conf
			prev = conf.get("ib_so_credit_checks")
			conf.pop("ib_so_credit_checks", None)
			self.so.CustomSalesOrder.before_submit(self._doc())
			self.assertEqual(called, [])
			conf["ib_so_credit_checks"] = 1
			self.so.CustomSalesOrder.before_submit(self._doc())
			self.assertEqual(called, [1])
		finally:
			self.so.check_advance_approval = orig
			if prev is None:
				conf.pop("ib_so_credit_checks", None)
			else:
				conf["ib_so_credit_checks"] = prev
