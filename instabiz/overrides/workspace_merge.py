"""instabiz.overrides.workspace_merge

One workspace per module. The native ERPNext/HRMS workspaces (Selling, CRM,
Accounting, Buying, Stock, Manufacturing, HR, Payroll...) stay hidden; their
cards and links are copied into the matching Instabiz workspace so nothing
they offered is lost, plus one Settings card per module.

merge_into_files() rewrites the Instabiz workspace JSON files in the app (a
build step, run by a developer: bench --site <site> execute
instabiz.overrides.workspace_merge.merge_into_files). hide_native() runs after
every migrate so an ERPNext/HRMS update can't bring a native workspace back.
"""
import json
import os

import frappe
from frappe.utils import now

# target Instabiz workspace -> native workspaces (app, module folder, workspace folder)
MERGE_MAP = {
	"Instabiz": [("erpnext", "selling", "selling"), ("erpnext", "crm", "crm")],
	"Instabiz Finance": [
		("erpnext", "accounts", "accounting"), ("erpnext", "accounts", "receivables"),
		("erpnext", "accounts", "payables"), ("erpnext", "accounts", "financial_reports"),
	],
	"Instabiz Procurement": [("erpnext", "buying", "buying")],
	"Instabiz Stock": [("erpnext", "stock", "stock"), ("erpnext", "assets", "assets")],
	"Instabiz Production": [("erpnext", "manufacturing", "manufacturing"), ("erpnext", "quality_management", "quality")],
	"Instabiz HR": [
		("hrms", "hr", "hr"), ("hrms", "hr", "employee_lifecycle"), ("hrms", "hr", "leaves"),
		("hrms", "hr", "shift_&_attendance"), ("hrms", "hr", "recruitment"), ("hrms", "hr", "performance"),
		("hrms", "hr", "expense_claims"), ("hrms", "payroll", "payroll"), ("hrms", "payroll", "salary_payout"),
		("hrms", "payroll", "tax_&_benefits"),
	],
	"Instabiz Misc": [("erpnext", "setup", "erpnext_settings")],
}

# one Settings card per module: (label, link_to, link_type)
SETTINGS_CARD = {
	"Instabiz": [("Sales Settings", "IB Sales Settings", "DocType"), ("Messaging Settings", "IB Messaging Settings", "DocType"),
		("Message Templates", "IB Message Template", "DocType"), ("Terms and Conditions", "Terms and Conditions", "DocType"),
		("Selling Settings", "Selling Settings", "DocType"), ("CRM Settings", "CRM Settings", "DocType")],
	"Instabiz Finance": [("Accounts Settings (Instabiz)", "IB Accounts Settings", "DocType"),
		("Print Settings (Instabiz)", "IB Print Settings", "DocType"), ("Financial Year", "ib-financial-year", "Page"),
		("Accounts Settings", "Accounts Settings", "DocType"), ("Fiscal Year", "Fiscal Year", "DocType"),
		("Accounting Period", "Accounting Period", "DocType"), ("GST Settings", "GST Settings", "DocType")],
	"Instabiz Procurement": [("Stock & Buying Settings", "IB Stock Settings", "DocType"),
		("Buying Settings", "Buying Settings", "DocType"), ("Terms and Conditions", "Terms and Conditions", "DocType")],
	"Instabiz Stock": [("Stock & Buying Settings", "IB Stock Settings", "DocType"), ("Stock Settings", "Stock Settings", "DocType")],
	"Instabiz Production": [("Manufacturing Settings", "Manufacturing Settings", "DocType")],
	"Instabiz HR": [("HR Settings (Instabiz)", "IB HR Settings", "DocType"), ("HR Settings", "HR Settings", "DocType"),
		("Payroll Settings", "Payroll Settings", "DocType")],
	"Instabiz Misc": [("Print Settings (Instabiz)", "IB Print Settings", "DocType"),
		("Messaging Settings", "IB Messaging Settings", "DocType"), ("Print Settings", "Print Settings", "DocType"),
		("System Settings", "System Settings", "DocType")],
}

# Tally-style books on the Finance workspace (added before the native cards,
# so the same reports are not repeated further down)
BOOKS = [("Day Book", "IB Day Book"), ("General Ledger", "General Ledger"), ("Trial Balance", "Trial Balance"),
	("Profit and Loss", "Profit and Loss Statement"), ("Balance Sheet", "Balance Sheet"), ("Cash Flow", "Cash Flow"),
	("Accounts Receivable", "Accounts Receivable"), ("Accounts Payable", "Accounts Payable"),
	("GSTR-1", "GSTR-1"), ("GST Balance", "GST Balance")]

NATIVE = sorted({"Selling", "CRM", "Instabiz CRM", "HR", "Payroll", "Stock", "Buying", "Manufacturing", "Accounting",
		"Payables", "Receivables", "Financial Reports", "Assets", "Quality", "ERPNext Settings",
		"Leaves", "Recruitment", "Employee Lifecycle", "Performance", "Shift & Attendance", "Expense Claims",
		"Salary Payout", "Tax & Benefits"})


def _scrub(name):
	return frappe.scrub(name)


def _target_path(name):
	folder = _scrub(name)
	return frappe.get_app_path("instabiz", "instabiz", "workspace", folder, f"{folder}.json")


def _native_path(app, module, folder):
	return os.path.join(frappe.get_app_path(app, module, "workspace", folder), f"{folder}.json")


def _cards(links):
	"""[(label, [link rows])] from a flat Card Break / Link list."""
	cards, current = [], None
	for row in links:
		if row.get("type") == "Card Break":
			current = (row.get("label"), [])
			cards.append(current)
		elif current is not None:
			current[1].append(row)
	return cards


def _key(row):
	return (row.get("link_type") or "DocType", row.get("link_to"))


def _link_row(label, link_to, link_type, source=None):
	row = {"type": "Link", "label": label, "link_to": link_to, "link_type": link_type,
		"hidden": 0, "is_query_report": 0, "onboard": 0, "link_count": 0, "dependencies": "", "only_for": ""}
	if source:
		for field in ("is_query_report", "onboard", "dependencies", "only_for", "report_ref_doctype"):
			if source.get(field) is not None:
				row[field] = source.get(field)
	return row


def merge_into_files():
	written = []
	for target, sources in MERGE_MAP.items():
		path = _target_path(target)
		if not os.path.exists(path):
			continue
		with open(path) as f:
			ws = json.load(f)
		seen = {_key(r) for r in ws.get("links", []) if r.get("type") == "Link"}
		seen |= {(s.get("type") or "DocType", s.get("link_to")) for s in ws.get("shortcuts", [])}
		cards = _cards(ws.get("links", []))
		by_label = {label: rows for label, rows in cards}
		new_labels = []  # (label, section heading)
		section = {"name": "Settings"}

		def add(label, rows):
			keep = []
			for r in rows:
				if r.get("only_for") and r.get("only_for") != "India":
					continue
				if _key(r) in seen or not r.get("link_to"):
					continue
				seen.add(_key(r))
				keep.append(r)
			if not keep:
				return
			if label not in by_label:
				by_label[label] = []
				cards.append((label, by_label[label]))
				new_labels.append((label, section["name"]))
			by_label[label].extend(keep)

		settings = [_link_row(label, link_to, link_type) for label, link_to, link_type in SETTINGS_CARD.get(target, [])
			if link_type != "DocType" or frappe.db.exists("DocType", link_to)]
		add("Settings", settings)
		section["name"] = "Books"
		if target == "Instabiz Finance":
			books = []
			for label, report in BOOKS:
				if frappe.db.exists("Report", report):
					row = _link_row(label, report, "Report")
					row["is_query_report"] = 1
					books.append(row)
			add("Books", books)
		for app, module, folder in sources:
			npath = _native_path(app, module, folder)
			if not os.path.exists(npath):
				continue
			with open(npath) as f:
				native = json.load(f)
			section["name"] = native.get("title") or native.get("label") or folder.title()
			for label, rows in _cards(native.get("links", [])):
				add(label, [_link_row(r.get("label"), r.get("link_to"), r.get("link_type") or "DocType", r) for r in rows])

		links = []
		for label, rows in cards:
			links.append({"type": "Card Break", "label": label, "hidden": 0, "is_query_report": 0, "onboard": 0,
				"link_count": len(rows), "dependencies": "", "only_for": "", "link_type": "DocType"})
			links.extend(rows)
		ws["links"] = links

		content = json.loads(ws.get("content") or "[]")
		present = {b["data"].get("card_name") for b in content if b.get("type") == "card"}
		add_blocks = [(label, heading) for label, heading in new_labels if label not in present]
		last_heading = None
		for label, heading in add_blocks:
			if heading != last_heading:
				content.append({"id": frappe.generate_hash(length=10), "type": "header",
					"data": {"text": f'<span class="h4"><b>{heading}</b></span>', "col": 12}})
				last_heading = heading
			content.append({"id": frappe.generate_hash(length=10), "type": "card",
				"data": {"card_name": label, "col": 4}})
		ws["content"] = json.dumps(content)
		ws["modified"] = now()
		with open(path, "w") as f:
			f.write(frappe.as_json(ws) + "\n")
		written.append(f"{target}: +{len(add_blocks)} cards, {sum(1 for r in links if r['type'] == 'Link')} links")
	print("\n".join(written))
	return written


def hide_native():
	"""after_migrate: keep the native module workspaces hidden (merged above)."""
	for name in NATIVE:
		if frappe.db.exists("Workspace", name):
			frappe.db.set_value("Workspace", name, "is_hidden", 1, update_modified=False)
