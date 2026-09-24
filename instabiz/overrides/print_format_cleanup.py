"""instabiz.overrides.print_format_cleanup

Print Formats built in the UI are database records. They are not in git, a fresh
site never has them, and the format that replaces one cannot remove it — so the
Print dropdown grows a row per attempt and nobody can tell which one is current.

Six had built up. Each is superseded by a format that ships in the app (or, for
the two quotation ones, by the QPF_V2 fixture), and every replacement carries the
Thickness / Colour / Width / Length / Qty-per-pkg / Total-pkg columns that the
older ones predate. They are switched off here, so this site, dev and production
end up matching a fresh site instead of each carrying its own pile.

Disabled rather than deleted: the record and its html stay, so anything that turns
out to still be wanted is one tick away in the UI instead of gone. Same call as
overrides/client_script_cleanup.py made for the Client Scripts.

Deliberately NOT touched: "IRS 1099 Form", which is a standard ERPNext Regional
format, not ours.
"""
import json
import os

import frappe

# Print Format name -> what replaced it
SUPERSEDED = {
	"QuotationPF": "QPF_V2 (fixtures/print_format.json) — also the Quotation default now",
	"QPF_UnderWorking": "QPF_V2 — this was a working draft of it",
	"OrderSheetPF": "OSPF_V2 (fixtures/print_format.json), already the Sales Order default",
	"SI PF V1": "IB GST Tax Invoice (print_format/ib_gst_tax_invoice/)",
	"Outstanding-Amount": "IB Outstanding Statement (print_format/ib_outstanding_statement/)",
	"Outstanding-Amount-Format": "IB Outstanding Statement (print_format/ib_outstanding_statement/)",
}


def shipped():
	"""Every Print Format the app carries as a file, as {name: parsed json}.

	Each entry also gets _folder and _template (the .html beside the json, or None).
	"""
	base = os.path.join(frappe.get_app_path("instabiz"), "instabiz", "print_format")
	out = {}
	if not os.path.isdir(base):
		return out
	for folder in sorted(os.listdir(base)):
		meta = os.path.join(base, folder, folder + ".json")
		if not os.path.isfile(meta):
			continue
		try:
			with open(meta, encoding="utf-8") as fh:
				doc = json.load(fh)
		except Exception:
			frappe.log_error(f"IB print format json unreadable: {folder}", frappe.get_traceback())
			continue
		if not doc.get("name"):
			continue
		template = os.path.join(base, folder, folder + ".html")
		doc["_folder"] = folder
		doc["_template"] = None
		if os.path.isfile(template):
			with open(template, encoding="utf-8") as fh:
				doc["_template"] = fh.read()
		# Two folders can declare the same name — a rename that left the old folder
		# behind, or a stale copy in a container that only ever gets files added to
		# it. Keying by name alone silently keeps whichever sorted last, which is
		# how a wrongly-named folder stays invisible. Remember the losers so
		# assert_shipped_formats_usable can say so.
		if doc["name"] in out:
			kept, dropped = out[doc["name"]], doc
			if frappe.scrub(doc["name"]) == folder:
				kept, dropped = doc, out[doc["name"]]
			kept.setdefault("_shadowed_by", []).append(dropped["_folder"])
			kept["_shadowed_by"] += dropped.pop("_shadowed_by", [])
			out[doc["name"]] = kept
			continue
		out[doc["name"]] = doc
	return out


def assert_shipped_formats_usable():
	"""Keep every format the app ships printable, and say so when one cannot be.

	Two things break a shipped format quietly, and neither logs anything:

	1. The folder must be frappe.scrub(name). printview.get_print_format builds the
	   path from the scrubbed NAME, not from the folder the json was imported from,
	   and get_html_and_style swallows TemplateNotFoundError and returns html=None
	   — so the format installs, appears in the Print dropdown, and prints a blank
	   page. "IB Stock Count Sheet" did exactly that from a folder called
	   ib_stock_count. Only reported here; the fix is to rename the folder, and
	   tests/test_print_formats.py fails on it.

	2. A Report print format (print_format_for="Report", e.g. General Ledger) is
	   read by desk.query_report.get_print_format_data straight out of the html
	   column. Nothing ever looks at the file for those, so General Ledger's
	   template sat in general_ledger.html doing nothing and the report printed
	   whatever that one site's column happened to hold. The .html file stays the
	   one source — it is what a diff can be read — and it is copied into the
	   column here on every migrate.

	For an ordinary DocType format the disk file wins whenever it exists, whatever
	the standard flag says (get_print_format checks the path first), so the flag is
	only about whether the format is editable in the UI. It is still put back to
	"Yes" so a shipped format is not presented as a local edit, and `disabled` is
	cleared so the retirement list below is the only thing that ever disables one.
	"""
	fixed, broken = [], []
	for name, meta in shipped().items():
		row = frappe.db.get_value(
			"Print Format", name, ["standard", "html", "disabled", "print_format_for"], as_dict=True
		)
		if not row:
			broken.append(f"{name}: shipped in {meta['_folder']}/ but not installed")
			continue
		if frappe.scrub(name) != meta["_folder"]:
			broken.append(
				f"{name}: ships in {meta['_folder']}/ but Frappe looks for"
				f" {frappe.scrub(name)}/ — it prints a blank page"
			)
		for shadow in meta.get("_shadowed_by") or []:
			broken.append(
				f"{name}: also declared by {shadow}/ — delete that folder, two folders"
				f" for one format is how a wrong name goes unnoticed"
			)

		changes = {}
		if meta.get("standard") == "Yes" and row.standard != "Yes":
			changes["standard"] = "Yes"
		if row.disabled:
			changes["disabled"] = 0
		# A Report format has no file fallback, so push the file into the column.
		# Compared on normalised newlines: the checkout may be CRLF and the column
		# is not, and a line-ending difference is not a change worth writing.
		if (meta.get("print_format_for") or "DocType") == "Report":
			template = meta.get("_template")
			if not (template or "").strip():
				broken.append(f"{name}: Report print format with no {meta['_folder']}.html to load")
			elif template.replace("\r\n", "\n") != (row.html or "").replace("\r\n", "\n"):
				changes["html"] = template
		if not changes:
			continue
		# db.set_value, not doc.save(): Print Format.validate refuses to save a
		# standard="Yes" format outside developer_mode, and this is not an edit —
		# it is restoring what the app ships.
		frappe.db.set_value("Print Format", name, changes, update_modified=False)
		fixed.append(f"{name}:{','.join(sorted(changes))}")

	if fixed:
		frappe.logger().info("print_format_cleanup: restored -> " + "; ".join(fixed))
	for line in broken:
		frappe.logger().warning("print_format_cleanup: " + line)
	return {"fixed": fixed, "broken": broken}


def after_migrate():
	assert_shipped_formats_usable()
	live = set(frappe.get_all("Print Format", pluck="name"))
	for name in SUPERSEDED:
		if name not in live:
			# A name that matches nothing is almost always a typo in the list
			# above, not a format someone deleted — say so rather than silently
			# doing nothing.
			frappe.logger().info(f"print_format_cleanup: no Print Format named {name!r}")

	for name, replaced_by in SUPERSEDED.items():
		if name not in live:
			continue
		if frappe.db.get_value("Print Format", name, "disabled"):
			continue
		# A default_print_format still pointing here would leave the doctype with
		# a disabled default, which prints nothing. Say so loudly; do not silently
		# repoint it, because which format a doctype defaults to is a decision.
		for ps in frappe.get_all(
			"Property Setter",
			filters={"property": "default_print_format", "value": name},
			fields=["name", "doc_type"],
		):
			frappe.logger().warning(
				f"print_format_cleanup: {ps.doc_type} still defaults to {name!r}"
				f" — repoint it before this takes effect"
			)
		frappe.db.set_value("Print Format", name, "disabled", 1)
	frappe.clear_cache()


def status():
	"""Every non-standard Print Format, and where its replacement lives."""
	out = []
	for r in frappe.get_all(
		"Print Format",
		filters={"standard": "No"},
		fields=["name", "doc_type", "module", "disabled"],
		order_by="doc_type",
	):
		out.append({
			"name": r.name,
			"doctype": r.doc_type,
			"module": r.module,
			"disabled": r.disabled,
			"replaced_by": SUPERSEDED.get(r.name, "— not superseded, still database-only"),
		})
	return out
