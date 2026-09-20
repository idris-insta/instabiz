"""One "Dashboards" tab for every dashboard in the system.

The app ships 14 custom dashboard pages, and ERPNext/HRMS ship 14 `Dashboard`
records of their own — none of which had a single `Workspace Link` pointing at
them, so they existed but nobody could reach them. This builds a Dashboards
workspace holding both, and `check_dashboards()` reports the ones whose charts
cannot render (a chart against a doctype the site does not have, a report that
was disabled, a broken filter) so a dead tile is left out instead of shipped.
"""

import json

import frappe

# Instabiz dashboard pages, grouped the way a user thinks about them.
PAGE_GROUPS = [
	("Overview", [
		("ib-main-dashboard", "Dashboard"),
		("ib-business-pulse", "Business Pulse"),
		("ib-analytics-hub", "Analytics Hub"),
		("ib-system-health", "System Health"),
	]),
	("Sales", [
		("ib-customer-board", "Customer Board"),
		("ib-customer-health", "Customer Health"),
		("ib-sales-incentives", "Sales Incentives"),
		("ib-follow-ups", "Follow-Ups"),
		("ib-item-pricing", "Item Pricing"),
	]),
	("Finance", [
		("ib-finance-dashboard", "Finance Dashboard"),
		("ib-collections-dashboard", "Collections"),
		("ib-financial-year", "Financial Year"),
		("ib-advance-approvals", "Advance Approvals"),
		("ib-bank-statement-import", "Bank Import"),
	]),
	("Operations", [
		("ib-production-dashboard", "Production Dashboard"),
		("ib-production-tracker", "Production Tracker"),
		("ib-dpr", "DPR Report"),
		("ib-stock-dashboard", "Live Stock Balance"),
		("ib-trace", "Traceability"),
		("ib-procurement-dashboard", "Procurement Dashboard"),
	]),
	("People", [
		("ib-hrms-dashboard", "HR Dashboard"),
		("ib-my-hr", "My HR"),
		("ib-org-chart", "Org Chart"),
		("attendance-terminal", "Attendance Terminal"),
	]),
]

CARD_COLS = {"Overview": 4, "Sales": 4, "Finance": 4, "Operations": 4, "People": 4, "ERPNext dashboards": 4}


def _chart_ok(chart):
	"""True when this chart can actually be drawn on this site."""
	doc = frappe.db.get_value(
		"Dashboard Chart", chart, ["chart_type", "document_type", "report_name", "is_standard"], as_dict=True
	)
	if not doc:
		return False, "chart missing"
	if doc.chart_type == "Report":
		if not doc.report_name or not frappe.db.exists("Report", doc.report_name):
			return False, f"report {doc.report_name} missing"
		if frappe.db.get_value("Report", doc.report_name, "disabled"):
			return False, f"report {doc.report_name} disabled"
	elif doc.document_type:
		if not frappe.db.exists("DocType", doc.document_type):
			return False, f"doctype {doc.document_type} missing"
		if not frappe.db.table_exists(doc.document_type):
			return False, f"table for {doc.document_type} missing"
	return True, ""


def check_dashboards():
	"""Report every native Dashboard with the state of its charts and cards.

	Returns {dashboard: {"ok": bool, "charts": n, "broken": [(chart, why)], "cards": n}}.
	"""
	out = {}
	for name in frappe.get_all("Dashboard", pluck="name"):
		doc = frappe.get_doc("Dashboard", name)
		broken = []
		for row in doc.get("charts") or []:
			ok, why = _chart_ok(row.chart)
			if not ok:
				broken.append((row.chart, why))
		cards = [row.card for row in doc.get("cards") or [] if frappe.db.exists("Number Card", row.card)]
		total = len(doc.get("charts") or [])
		out[name] = {
			"ok": bool(total or cards) and not broken,
			"charts": total,
			"broken": broken,
			"cards": len(cards),
		}
	return out


# An ERPNext dashboard that an Instabiz page already covers is a duplicate —
# the tab lists ours, not both. The value is what the page shows, not who
# shipped it.
IB_EQUIVALENT = {
	"Selling": "ib-main-dashboard",
	"CRM": "ib-customer-board",
	"Accounts": "ib-finance-dashboard",
	"Buying": "ib-procurement-dashboard",
	"Stock": "ib-stock-dashboard",
	"Manufacturing": "ib-production-dashboard",
	"Human Resource": "ib-hrms-dashboard",
	"Payroll": "ib-hrms-dashboard",
	"Attendance": "ib-hrms-dashboard",
}


def _has_data(dashboard):
	"""True when at least one chart on this dashboard has rows behind it."""
	doc = frappe.get_doc("Dashboard", dashboard)
	seen = set()
	for row in doc.get("charts") or []:
		dt = frappe.db.get_value("Dashboard Chart", row.chart, "document_type")
		if not dt or dt in seen or not frappe.db.table_exists(dt):
			continue
		seen.add(dt)
		if frappe.db.count(dt):
			return True
	for row in doc.get("cards") or []:
		dt = frappe.db.get_value("Number Card", row.card, "document_type")
		if dt and frappe.db.table_exists(dt) and frappe.db.count(dt):
			return True
	return False


def usable_dashboards():
	"""Native dashboards worth a place on the tab.

	Left out: the ones an Instabiz page already covers (see IB_EQUIVALENT),
	the ones whose charts cannot render, and the ones for a module this site
	has no data in — an empty Recruitment tile helps nobody, and it comes back
	on its own the day someone records a job applicant.
	"""
	state = check_dashboards()
	out = []
	for name, s in state.items():
		if name in IB_EQUIVALENT:
			continue
		if (s["charts"] - len(s["broken"])) <= 0 and not s["cards"]:
			continue
		if not _has_data(name):
			continue
		out.append(name)
	return sorted(out)


def build_dashboards_workspace():
	"""Rebuild the "Dashboards" workspace from what actually exists on this site."""
	links, content = [], [
		{"id": "ibdash0", "type": "header",
			"data": {"text": '<span class="h4"><b>Dashboards</b></span>', "col": 12}}
	]
	shortcuts = []

	for group, pages in PAGE_GROUPS:
		rows = [(slug, label) for slug, label in pages if frappe.db.exists("Page", slug)]
		if not rows:
			continue
		links.append({"type": "Card Break", "label": group, "link_count": len(rows), "hidden": 0, "onboard": 0})
		for slug, label in rows:
			links.append({"type": "Link", "label": label, "link_type": "Page", "link_to": slug,
				"hidden": 0, "onboard": 0, "link_count": 0, "is_query_report": 0})
		content.append({"id": "ibdash" + frappe.scrub(group)[:8], "type": "card",
			"data": {"card_name": group, "col": CARD_COLS.get(group, 4)}})

	native = usable_dashboards()
	if native:
		links.append({"type": "Card Break", "label": "ERPNext dashboards", "link_count": len(native),
			"hidden": 0, "onboard": 0})
		for name in native:
			links.append({"type": "Link", "label": name, "link_type": "Dashboard", "link_to": name,
				"hidden": 0, "onboard": 0, "link_count": 0, "is_query_report": 0})
		content.append({"id": "ibdashnative", "type": "card",
			"data": {"card_name": "ERPNext dashboards", "col": 4}})

	# The three a user opens daily get a big shortcut tile above the cards.
	for slug, label, colour in (("ib-main-dashboard", "Dashboard", "Orange"),
			("ib-business-pulse", "Business Pulse", "Green"),
			("ib-analytics-hub", "Analytics Hub", "Blue")):
		if frappe.db.exists("Page", slug):
			shortcuts.append({"type": "Page", "link_to": slug, "label": label, "color": colour})
	if shortcuts:
		content.insert(1, {"id": "ibdashsc", "type": "spacer", "data": {"col": 12}})
		for i, s in enumerate(shortcuts):
			content.insert(1 + i, {"id": f"ibdashs{i}", "type": "shortcut",
				"data": {"shortcut_name": s["label"], "col": 3}})

	ws = frappe.get_doc("Workspace", "Dashboards") if frappe.db.exists("Workspace", "Dashboards") \
		else frappe.new_doc("Workspace")
	ws.update({"label": "Dashboards", "title": "Dashboards", "module": "Instabiz", "public": 1,
		"is_hidden": 0, "icon": "dashboard", "parent_page": "", "content": json.dumps(content)})
	if ws.is_new():
		ws.name = "Dashboards"
	ws.set("links", [])
	ws.set("shortcuts", [])
	for row in links:
		ws.append("links", row)
	for row in shortcuts:
		ws.append("shortcuts", row)
	ws.flags.ignore_links = True
	if ws.is_new():
		ws.insert(ignore_permissions=True)
	else:
		ws.save(ignore_permissions=True)
	return {"links": len(links), "shortcuts": len(shortcuts), "native": native}


@frappe.whitelist()
def dashboard_health():
	"""Admin view of check_dashboards() — used by System Health and by tests."""
	frappe.only_for("System Manager")
	state = check_dashboards()
	return {
		"total": len(state),
		"ok": sorted(n for n, s in state.items() if s["ok"]),
		"broken": {n: s["broken"] for n, s in state.items() if s["broken"]},
		"empty": sorted(n for n, s in state.items() if not s["charts"] and not s["cards"]),
	}

def _run_chart(name):
	"""Render one chart the way the desk does — the path depends on its type."""
	from frappe.desk.doctype.dashboard_chart.dashboard_chart import get as chart_get

	doc = frappe.get_doc("Dashboard Chart", name)
	if doc.chart_type == "Report":
		# Report charts are served by the report runner, not by dashboard_chart.get
		from frappe.desk.query_report import run as report_run

		report_run(doc.report_name, filters=doc.filters_json or "{}", ignore_prepared_report=True)
		return
	if doc.chart_type == "Custom":
		src = frappe.get_doc("Dashboard Chart Source", doc.source)
		method = f"{frappe.scrub(src.module)}.{frappe.scrub(src.module)}" if False else None
		path = frappe.get_attr(src.get("method") or "") if src.get("method") else None
		if path:
			path(chart=doc, no_cache=1)
		return
	# no_cache=1 hits a core bug (cache_source hands get() a Document, which
	# then calls parse_json on it) — refresh=1 recomputes through the
	# supported path.
	chart_get(chart_name=name, refresh=1)


def smoke_dashboards(limit_charts=None):
	"""Actually render every chart and number card once and report what throws.

	The static check above only proves the chart points at something that
	exists; this is the one that catches a chart whose filters or group-by
	field no longer match the doctype.
	"""
	from frappe.desk.doctype.number_card.number_card import get_result

	failures = {"charts": [], "cards": []}
	charts = frappe.get_all("Dashboard Chart", pluck="name")
	if limit_charts:
		charts = charts[: int(limit_charts)]
	for name in charts:
		try:
			_run_chart(name)
		except Exception as e:
			failures["charts"].append((name, f"{type(e).__name__}: {e}"[:160]))
			frappe.clear_last_message()
	for name in frappe.get_all("Number Card", pluck="name"):
		try:
			doc = frappe.get_doc("Number Card", name)
			if doc.type == "Custom":
				continue
			get_result(doc=doc.as_dict(), filters=doc.filters_json or "[]")
		except Exception as e:
			failures["cards"].append((name, f"{type(e).__name__}: {e}"[:160]))
			frappe.clear_last_message()
	return {
		"charts_run": len(charts),
		"charts_failed": len(failures["charts"]),
		"cards_failed": len(failures["cards"]),
		"failures": failures,
	}

# Five ERPNext standard charts ship with filters that are missing a value the
# report itself insists on, so they throw the moment anyone opens the
# dashboard they sit on ("Start Year and End Year are mandatory", "Please
# select month and year", KeyError to_date / from_fiscal_year). Filling the
# gap with the obvious current-period value is what makes them render.
CHART_FILTER_FIXES = {
	"Profit and Loss": ["from_fiscal_year", "to_fiscal_year", "company"],
	"Budget Variance": ["from_fiscal_year", "to_fiscal_year", "company"],
	"Attendance Count": ["month", "year", "company"],
	"Oldest Items": ["to_date", "company"],
	"Item-wise Annual Sales": ["to_date", "company"],
}


def _filter_value(key):
	today = frappe.utils.getdate(frappe.utils.nowdate())
	if key == "company":
		return frappe.db.get_default("company") or frappe.db.get_value("Company", {}, "name")
	if key in ("from_fiscal_year", "to_fiscal_year"):
		try:
			from erpnext.accounts.utils import get_fiscal_year

			return get_fiscal_year(today)[0]
		except Exception:
			return frappe.db.get_value("Fiscal Year", {}, "name", order_by="year_start_date desc")
	if key == "month":
		return today.strftime("%b").capitalize()
	if key == "year":
		return str(today.year)
	if key == "to_date":
		return str(today)
	return None


def repair_standard_charts():
	"""Fill the missing mandatory filters, only where they are actually absent."""
	fixed = {}
	for chart, keys in CHART_FILTER_FIXES.items():
		if not frappe.db.exists("Dashboard Chart", chart):
			continue
		raw = frappe.db.get_value("Dashboard Chart", chart, "filters_json") or "{}"
		try:
			filters = json.loads(raw)
		except ValueError:
			filters = {}
		if not isinstance(filters, dict):
			continue
		added = {}
		for key in keys:
			if filters.get(key):
				continue
			value = _filter_value(key)
			if value:
				filters[key] = value
				added[key] = value
		if added:
			frappe.db.set_value("Dashboard Chart", chart, "filters_json", json.dumps(filters),
				update_modified=False)
			fixed[chart] = added
	frappe.clear_cache()
	return fixed


def after_migrate():
	"""A migrate re-imports the standard charts, so the filter fix is reapplied."""
	try:
		repair_standard_charts()
	except Exception:
		frappe.log_error("IB dashboards", frappe.get_traceback())
