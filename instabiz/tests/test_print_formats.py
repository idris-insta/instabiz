"""Regression tests for the shipped Print Formats.

Run: bench --site <site> run-tests --app instabiz --module instabiz.tests.test_print_formats

The one that matters is test_every_folder_matches_scrubbed_name. Frappe looks a
standard print format's template up by frappe.scrub(name), not by the folder the
json was imported from, and printview.get_html_and_style swallows
TemplateNotFoundError and returns html=None. So a folder named anything else
installs cleanly, appears in the Print dropdown, and prints a blank page with no
error in any log. That is exactly what "IB Stock Count Sheet" did when it was
first added in a folder called ib_stock_count.
"""
import json
import os
import pathlib

import frappe
from frappe.tests.utils import FrappeTestCase

DIMENSION_FIELDS = ("custom_thickness", "color", "width_mm", "length_mtr", "qty_pkg", "total_pkg")


def _print_format_dir():
	return pathlib.Path(frappe.get_app_path("instabiz")) / "instabiz" / "print_format"


def _shipped():
	"""(folder name, parsed json, html text) for every print format in the app."""
	out = []
	for folder in sorted(_print_format_dir().iterdir()):
		if not folder.is_dir():
			continue
		meta = folder / f"{folder.name}.json"
		if not meta.exists():
			continue
		html = folder / f"{folder.name}.html"
		out.append((
			folder.name,
			json.loads(meta.read_text(encoding="utf-8")),
			html.read_text(encoding="utf-8") if html.exists() else None,
		))
	return out


class TestShippedPrintFormats(FrappeTestCase):
	def test_shipped_formats_are_found(self):
		self.assertGreater(len(_shipped()), 50, "print_format/ folder looks empty")

	def test_every_folder_matches_scrubbed_name(self):
		for folder, meta, _html in _shipped():
			self.assertEqual(
				frappe.scrub(meta["name"]),
				folder,
				f"{meta['name']!r} lives in {folder}/ but Frappe will look for "
				f"{frappe.scrub(meta['name'])}/ — it would print a blank page",
			)

	def test_one_folder_per_format(self):
		"""Two folders declaring one name is how a wrong name stays invisible.

		Anything that keys formats by name keeps whichever sorted last, so a stale
		folder left behind by a rename hides the mismatch instead of showing it.
		"""
		seen = {}
		for folder, meta, _html in _shipped():
			seen.setdefault(meta["name"], []).append(folder)
		dupes = {name: folders for name, folders in seen.items() if len(folders) > 1}
		self.assertEqual(dupes, {}, "more than one folder declares the same Print Format")

	def test_every_format_has_a_template(self):
		for folder, meta, html in _shipped():
			self.assertTrue(
				(html or "").strip() or (meta.get("html") or "").strip(),
				f"{meta['name']!r} ({folder}/) has no html",
			)

	def test_includes_point_at_templates_that_exist(self):
		"""Most formats are one-line stubs including templates/print/docs/*.html."""
		app = pathlib.Path(frappe.get_app_path("instabiz"))
		for folder, meta, html in _shipped():
			for line in (html or "").splitlines():
				if 'include "templates/print/' not in line:
					continue
				rel = line.split('include "', 1)[1].split('"', 1)[0]
				self.assertTrue(
					(app / rel).exists(),
					f"{meta['name']!r} includes {rel}, which does not exist",
				)

	def test_doc_types_exist(self):
		for folder, meta, _html in _shipped():
			dt = meta.get("doc_type")
			if not dt:
				continue
			self.assertTrue(
				frappe.db.exists("DocType", dt),
				f"{meta['name']!r} is for DocType {dt!r}, which does not exist",
			)

	def test_none_disabled(self):
		for folder, meta, _html in _shipped():
			self.assertFalse(meta.get("disabled"), f"{meta['name']!r} ships disabled")

	def test_report_formats_reach_the_html_column(self):
		"""A Report print format has no file fallback.

		desk.query_report.get_print_format_data reads the html column and never
		looks at disk, so nothing renders unless something puts the template there.
		General Ledger shipped html="" with its real template sitting in
		general_ledger.html, which nothing reads for a Report format — so the report
		printed whatever that one site's column happened to hold.
		print_format_cleanup copies the file into the column on every migrate; this
		checks the file it copies is actually there.
		"""
		from instabiz.overrides.print_format_cleanup import shipped as shipped_meta

		for name, meta in shipped_meta().items():
			if (meta.get("print_format_for") or "DocType") != "Report":
				continue
			self.assertTrue(meta.get("report"), f"{name!r} names no report")
			self.assertTrue(
				(meta.get("_template") or "").strip(),
				f"{name!r} is a Report print format with no {meta['_folder']}.html"
				f" — nothing would reach its html column",
			)

	def test_report_format_column_matches_the_file(self):
		"""After migrate, the column a Report format prints from is the shipped file."""
		from instabiz.overrides.print_format_cleanup import (
			assert_shipped_formats_usable,
			shipped as shipped_meta,
		)

		assert_shipped_formats_usable()
		for name, meta in shipped_meta().items():
			if (meta.get("print_format_for") or "DocType") != "Report":
				continue
			if not frappe.db.exists("Print Format", name):
				continue
			column = frappe.db.get_value("Print Format", name, "html") or ""
			self.assertEqual(
				(meta.get("_template") or "").replace("\r\n", "\n").strip(),
				column.replace("\r\n", "\n").strip(),
				f"{name!r} prints from a column that does not match {meta['_folder']}.html",
			)


class TestDimensionColumns(FrappeTestCase):
	"""The shared item grid is what puts the dimension columns on every document.

	Every sales / purchase format renders through it, so testing the macro covers
	all of them at once — and catches a column being dropped from the macro, which
	would silently remove it from a dozen formats.
	"""

	def _macros(self):
		path = pathlib.Path(frappe.get_app_path("instabiz")) / "templates" / "print" / "ib_print_macros.html"
		return path.read_text(encoding="utf-8")

	def test_item_grid_renders_every_dimension_field(self):
		macros = self._macros()
		grid = macros.split("{% macro item_grid(")[1].split("{% endmacro %}")[0]
		for field in DIMENSION_FIELDS:
			self.assertIn(field, grid, f"item_grid no longer reads row.{field}")

	def test_item_spec_covers_every_dimension_field(self):
		"""Formats that build their own grid show the same numbers as one line."""
		from instabiz.overrides.print_helpers import item_spec

		row = frappe._dict(
			width_mm=1060, length_mtr=1000, custom_thickness="60 MIC", color="Blue",
			qty_pkg=2, total_pkg=8, custom_branding="", custom_marking="",
		)
		spec = item_spec(row)
		for fragment in ("1060", "1000", "60 MIC", "Blue", "2", "8"):
			self.assertIn(fragment, spec, f"item_spec dropped {fragment!r}: {spec!r}")


class TestDefaultPrintFormats(FrappeTestCase):
	def test_defaults_point_at_a_format_that_ships(self):
		"""A default naming a format nobody ships is a blank Print button on a new site.

		Quotation defaulted to "QuotationPF" for months — a format that only ever
		existed in one database.
		"""
		shipped = {meta["name"] for _f, meta, _h in _shipped()}
		fixture = pathlib.Path(frappe.get_app_path("instabiz")) / "fixtures" / "print_format.json"
		if fixture.exists():
			shipped |= {r["name"] for r in json.loads(fixture.read_text(encoding="utf-8"))}

		setters = pathlib.Path(frappe.get_app_path("instabiz")) / "fixtures" / "property_setter.json"
		missing = []
		for row in json.loads(setters.read_text(encoding="utf-8")):
			if row.get("property") != "default_print_format":
				continue
			value = row.get("value")
			if not value or value in shipped:
				continue
			# Standard ERPNext / Frappe formats are fine — they ship with those apps.
			if frappe.db.exists("Print Format", value) and frappe.db.get_value(
				"Print Format", value, "standard"
			) == "Yes":
				continue
			missing.append(f"{row.get('doc_type')} -> {value}")
		self.assertEqual(missing, [], "default_print_format points at formats we do not ship")
