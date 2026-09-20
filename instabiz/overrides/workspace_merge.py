"""instabiz.overrides.workspace_merge

One tab per module. The Instabiz workspace and the matching ERPNext/HRMS
workspace are merged into the ERPNext one (Buying, Selling, Manufacturing,
Stock, HR):

  - the Instabiz layout comes first, exactly as built (headings, shortcuts,
    cards, number cards, charts);
  - the ERPNext layout follows under an "ERPNext <module>" heading, minus any
    shortcut, link or card the Instabiz part already has;
  - the Instabiz workspace is hidden and takes its sidebar position with it,
    and users whose default workspace was the Instabiz one move to the merged tab.

Runs after every migrate (ERPNext/HRMS updates re-sync their own workspace JSON,
so the merge is rebuilt from the app's JSON + the Instabiz workspace each time).
"""
import json
import os

import frappe

# merged tab (native workspace) -> (Instabiz workspace, app, module folder, workspace folder)
MERGE = {
	"Selling": ("Instabiz", "erpnext", "selling", "selling"),
	"Buying": ("Instabiz Procurement", "erpnext", "buying", "buying"),
	"Manufacturing": ("Instabiz Production", "erpnext", "manufacturing", "manufacturing"),
	"Stock": ("Instabiz Stock", "erpnext", "stock", "stock"),
	"HR": ("Instabiz HR", "hrms", "hr", "hr"),
}

CHILD_TABLES = {
	# table fieldname -> (block type, block data key, row label field)
	"shortcuts": ("shortcut", "shortcut_name", "label"),
	"charts": ("chart", "chart_name", "label"),
	"number_cards": ("number_card", "number_card_name", "label"),
	"quick_lists": ("quick_list", "quick_list_name", "label"),
	"custom_blocks": ("custom_block", "custom_block_name", "label"),
}
SKIP_FIELDS = {"name", "parent", "parentfield", "parenttype", "idx", "doctype", "owner", "creation",
	"modified", "modified_by", "docstatus"}


def _native_json(app, module, folder):
	path = os.path.join(frappe.get_app_path(app, module, "workspace", folder), f"{folder}.json")
	if not os.path.exists(path):
		return None
	with open(path) as f:
		return json.load(f)


def _row(d):
	return {k: v for k, v in d.items() if k not in SKIP_FIELDS}


def _cards(links):
	cards, current = [], None
	for row in links:
		if row.get("type") == "Card Break":
			current = [row, []]
			cards.append(current)
		elif current is not None:
			current[1].append(row)
	return cards


def _merged(ib, native):
	"""(content blocks, child table rows) for the merged workspace."""
	ib = ib.as_dict()
	content = json.loads(ib.get("content") or "[]")
	tables = {t: [_row(r) for r in ib.get(t) or []] for t in CHILD_TABLES}
	links = [_row(r) for r in ib.get("links") or []]

	seen_links = {(r.get("link_type") or "DocType", r.get("link_to")) for r in links if r.get("type") == "Link"}
	seen_links |= {(r.get("type") or "DocType", r.get("link_to")) for r in tables["shortcuts"]}
	labels = {t: {r.get(CHILD_TABLES[t][2]) for r in tables[t]} for t in CHILD_TABLES}
	card_labels = {r.get("label") for r in links if r.get("type") == "Card Break"}

	# ERPNext child rows that survive de-duplication, keyed by their block reference
	keep = {t: {} for t in CHILD_TABLES}
	for t, (_, _, label_field) in CHILD_TABLES.items():
		for r in native.get(t) or []:
			label = r.get(label_field)
			if label in labels[t]:
				continue
			if t == "shortcuts" and (r.get("type") or "DocType", r.get("link_to")) in seen_links:
				continue
			keep[t][label] = _row(r)
	card_rows = {}
	for brk, rows in _cards(native.get("links") or []):
		rows = [r for r in rows if not (r.get("only_for") and r.get("only_for") != "India")
			and (r.get("link_type") or "DocType", r.get("link_to")) not in seen_links]
		if not rows:
			continue
		label = brk.get("label")
		if label in card_labels:
			label = f"{label} (ERPNext)"
		card_rows[brk.get("label")] = (dict(_row(brk), label=label, link_count=len(rows)), [_row(r) for r in rows])

	native_blocks = []
	for b in json.loads(native.get("content") or "[]"):
		data = b.get("data") or {}
		if b["type"] == "card":
			hit = card_rows.get(data.get("card_name"))
			if not hit:
				continue
			native_blocks.append(dict(b, data=dict(data, card_name=hit[0]["label"])))
			continue
		for t, (btype, key, _) in CHILD_TABLES.items():
			if b["type"] == btype:
				if data.get(key) not in keep[t]:
					b = None
				break
		if b and b["type"] == "spacer" and native_blocks and native_blocks[-1]["type"] == "spacer":
			continue
		if b:
			native_blocks.append(b)

	# drop headings left with nothing under them
	cleaned = []
	for i, b in enumerate(native_blocks):
		if b["type"] == "header":
			nxt = next((x for x in native_blocks[i + 1:] if x["type"] not in ("spacer",)), None)
			if nxt is None or nxt["type"] == "header":
				continue
		cleaned.append(b)
	while cleaned and cleaned[-1]["type"] in ("spacer", "header"):
		cleaned.pop()

	if cleaned:
		content.append({"id": "ibm-sp", "type": "spacer", "data": {"col": 12}})
		content.append({"id": "ibm-hd", "type": "header",
			"data": {"text": f'<span class="h4"><b>ERPNext {native.get("title") or native.get("name")}</b></span>', "col": 12}})
		content.extend(cleaned)

	for t in CHILD_TABLES:
		tables[t].extend(keep[t].values())
	for brk, rows in card_rows.values():
		links.append(brk)
		links.extend(rows)
	tables["links"] = links
	return content, tables


def merge_modules():
	"""after_migrate: build the merged module tabs and hide the Instabiz duplicates."""
	dev_mode = frappe.conf.developer_mode
	frappe.conf.developer_mode = 0  # never write the merged result into erpnext/hrms files
	try:
		for target, (ib_name, app, module, folder) in MERGE.items():
			if not (frappe.db.exists("Workspace", target) and frappe.db.exists("Workspace", ib_name)):
				continue
			native = _native_json(app, module, folder)
			if not native:
				continue
			ib = frappe.get_doc("Workspace", ib_name)
			content, tables = _merged(ib, native)

			ws = frappe.get_doc("Workspace", target)
			ws.content = json.dumps(content)
			for t, rows in tables.items():
				ws.set(t, [])
				for r in rows:
					ws.append(t, r)
			ws.is_hidden = 0
			ws.sequence_id = ib.sequence_id
			ws.flags.ignore_links = True
			ws.save(ignore_permissions=True)

			frappe.db.set_value("Workspace", ib_name, "is_hidden", 1, update_modified=False)
			frappe.db.sql("UPDATE `tabUser` SET default_workspace = %s WHERE default_workspace = %s", (target, ib_name))
		show_tabs()
	finally:
		frappe.conf.developer_mode = dev_mode
	frappe.clear_cache()


# ── sidebar tabs ──────────────────────────────────────────────────────────────
# top-level tab -> children shown under it
SHOW_TABS = {
	"Selling": [],
	"CRM": [],
	"Accounting": ["Payables", "Receivables", "Financial Reports"],
}
SIDEBAR_ORDER = ["Dashboards", "Selling", "CRM", "Buying", "Stock", "Manufacturing", "Accounting", "Instabiz Finance", "HR",
	"Reports", "GST India"]

NATIVE_REPORTS = {
	"Selling": ["Sales Analytics", "Sales Order Analysis", "Sales Register", "Item-wise Sales Register",
		"Gross Profit", "Customer Acquisition and Loyalty", "Inactive Customers"],
	"Buying": ["Purchase Analytics", "Purchase Order Analysis", "Purchase Register", "Item-wise Purchase Register",
		"Supplier-Wise Sales Analytics"],
	"Stock": ["Stock Balance", "Stock Ledger", "Stock Projected Qty", "Stock Ageing", "Warehouse wise Item Balance Age and Value",
		"Batch-Wise Balance History"],
	"Accounts": ["General Ledger", "Trial Balance", "Balance Sheet", "Profit and Loss Statement", "Cash Flow",
		"Accounts Receivable", "Accounts Payable", "Customer Ledger Summary", "Supplier Ledger Summary",
		"Bank Reconciliation Statement"],
	"HR & Payroll": ["Monthly Attendance Sheet", "Employee Leave Balance", "Salary Register", "Employee Birthday"],
	"CRM": ["Lead Details", "Lead Conversion Time", "Campaign Efficiency", "Opportunity Summary by Sales Stage"],
	"GST": ["GSTR-1", "GSTR-3B Details", "GST Itemised Sales Register", "GST Itemised Purchase Register"],
}
# Instabiz reports go to the group of the doctype they report on
MODULE_GROUP = {"Selling": "Selling", "Buying": "Buying", "Stock": "Stock", "Accounts": "Accounts", "HR": "HR & Payroll",
	"Payroll": "HR & Payroll", "CRM": "CRM", "GST India": "GST", "Manufacturing": "Production", "Setup": "Selling"}
GROUP_ORDER = ["Selling", "CRM", "Buying", "Stock", "Production", "Accounts", "HR & Payroll", "GST", "Other"]


def _report_group(report):
	ref = frappe.db.get_value("Report", report, "ref_doctype")
	module = frappe.db.get_value("DocType", ref, "module") if ref else None
	if module == "Instabiz":
		name = (ref or "").lower()
		if any(k in name for k in ("work order", "order sheet", "dpr", "machine", "batch", "production")):
			return "Production"
		if any(k in name for k in ("employee", "salary", "loan", "attendance", "overtime", "leave")):
			return "HR & Payroll"
		if any(k in name for k in ("container", "gate pass", "stock")):
			return "Stock"
		if any(k in name for k in ("credit note", "debit note", "expense", "pdc", "journal", "payment")):
			return "Accounts"
		return "Selling"
	return MODULE_GROUP.get(module, "Other")


def build_reports_workspace():
	"""One "Reports" tab: every enabled Instabiz report + the key ERPNext / HRMS / GST ones."""
	groups = {g: [] for g in GROUP_ORDER}
	for r in frappe.get_all("Report", filters={"module": "Instabiz", "disabled": 0}, pluck="name", order_by="name"):
		groups[_report_group(r)].append(r)
	for g, names in NATIVE_REPORTS.items():
		for r in names:
			if frappe.db.exists("Report", {"name": r, "disabled": 0}) and r not in groups[g]:
				groups[g].append(r)
	links, content = [], [{"id": "ibrep0", "type": "header", "data": {"text": "<span class=\"h4\"><b>Reports</b></span>", "col": 12}}]
	for g in GROUP_ORDER:
		names = groups[g]
		if not names:
			continue
		links.append({"type": "Card Break", "label": g, "link_count": len(names), "hidden": 0, "onboard": 0})
		short = [r.replace("IB ", "", 1) for r in names]
		for r in names:
			rtype = frappe.db.get_value("Report", r, "report_type")
			label = r.replace("IB ", "", 1)
			if short.count(label) > 1:  # "IB Stock Ageing" next to ERPNext "Stock Ageing"
				label = r
			links.append({"type": "Link", "label": label, "link_type": "Report", "link_to": r,
				"is_query_report": 1 if rtype in ("Script Report", "Query Report") else 0, "hidden": 0, "onboard": 0,
				"link_count": 0})
		content.append({"id": "ibrep" + frappe.scrub(g)[:8], "type": "card", "data": {"card_name": g, "col": 4}})
	ws = frappe.get_doc("Workspace", "Reports") if frappe.db.exists("Workspace", "Reports") else frappe.new_doc("Workspace")
	ws.update({"label": "Reports", "title": "Reports", "module": "Instabiz", "public": 1, "is_hidden": 0,
		"icon": "file", "parent_page": "", "content": json.dumps(content)})
	if ws.is_new():
		ws.name = "Reports"
	ws.set("links", [])
	for row in links:
		ws.append("links", row)
	ws.flags.ignore_links = True
	ws.save(ignore_permissions=True) if not ws.is_new() else ws.insert(ignore_permissions=True)


def _shortcut_key(s):
	return (s.type or "DocType", s.link_to, s.url or "", s.doc_view or "List", s.stats_filter or "[]")


def dedupe_workspace(name):
	"""Drop a shortcut or card link that opens the same thing twice (the first one stays)."""
	ws = frappe.get_doc("Workspace", name)
	seen, shortcuts, drop = set(), [], set()
	for s in ws.shortcuts:
		key = _shortcut_key(s)
		if key in seen:
			drop.add(s.label)
			continue
		seen.add(key)
		shortcuts.append(s)
	links, seen, current, changed = [], set(), None, False
	for row in ws.links:
		if row.type == "Card Break":
			current = row
			current.link_count = 0
			links.append(row)
			continue
		key = (row.link_type or "DocType", row.link_to)
		if key in seen:
			changed = True
			continue
		seen.add(key)
		if current is not None:
			current.link_count += 1
		links.append(row)
	if not drop and not changed:
		return
	ws.shortcuts = shortcuts
	ws.links = links
	content = json.loads(ws.content or "[]")
	kept = {s.label for s in ws.shortcuts}
	ws.content = json.dumps([b for b in content if not (b["type"] == "shortcut"
		and (b.get("data") or {}).get("shortcut_name") in drop - kept)])
	ws.flags.ignore_links = True
	ws.save(ignore_permissions=True)


def show_tabs():
	"""Selling / CRM / Accounting (+ its sub-tabs) visible, Reports built, sidebar in a fixed order."""
	for tab, children in SHOW_TABS.items():
		if not frappe.db.exists("Workspace", tab):
			continue
		frappe.db.set_value("Workspace", tab, {"is_hidden": 0, "parent_page": "", "public": 1}, update_modified=False)
		for child in children:
			if frappe.db.exists("Workspace", child):
				frappe.db.set_value("Workspace", child, {"is_hidden": 0, "parent_page": tab, "public": 1},
					update_modified=False)
	build_reports_workspace()
	from instabiz.overrides.dashboards import build_dashboards_workspace

	build_dashboards_workspace()
	for name in frappe.get_all("Workspace", filters={"public": 1, "is_hidden": 0}, pluck="name"):
		dedupe_workspace(name)
	for i, name in enumerate(SIDEBAR_ORDER, 1):
		if frappe.db.exists("Workspace", name):
			frappe.db.set_value("Workspace", name, "sequence_id", i, update_modified=False)
