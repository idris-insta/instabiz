"""IB Complaints Analysis — tickets grouped by root cause, type, customer, item,
owner or month: how many, still open, past deadline, average hours to resolve
and % resolved on time. "List" shows every ticket."""
import frappe
from frappe import _
from frappe.utils import flt, time_diff_in_hours

GROUPS = {"Root Cause": "root_cause", "Type": "ticket_type", "Customer": "customer_name", "Item": "item_code",
	"Owner": "assigned_to", "Month": "month", "Source": "source"}
OPEN = ("Open", "In Progress", "Waiting on Customer")


def execute(filters=None):
	f = frappe._dict(filters or {})
	f.from_date = f.from_date or frappe.utils.add_months(frappe.utils.today(), -3)
	f.to_date = f.to_date or frappe.utils.today()
	flt_ = {"opened_at": ["between", [f.from_date, f"{f.to_date} 23:59:59"]]}
	for k in ("customer", "ticket_type", "status", "assigned_to", "item_code"):
		if f.get(k):
			flt_[k] = f.get(k)
	rows = frappe.get_all("IB Support Ticket", filters=flt_, fields=["name", "subject", "customer", "customer_name", "ticket_type",
		"priority", "status", "source", "assigned_to", "item_code", "root_cause", "opened_at", "resolved_at", "resolution_due",
		"sla_breached", "qty_affected"], order_by="opened_at desc")
	for r in rows:
		r.month = r.opened_at.strftime("%Y-%m") if r.opened_at else ""
		r.hours = round(time_diff_in_hours(r.resolved_at, r.opened_at), 1) if r.resolved_at and r.opened_at else None
	if (f.group_by or "Root Cause") == "List":
		cols = [{"label": _("Ticket"), "fieldname": "name", "fieldtype": "Link", "options": "IB Support Ticket", "width": 150},
			{"label": _("Opened"), "fieldname": "opened_at", "fieldtype": "Datetime", "width": 140},
			{"label": _("Customer"), "fieldname": "customer_name", "fieldtype": "Data", "width": 180},
			{"label": _("Subject"), "fieldname": "subject", "fieldtype": "Data", "width": 200},
			{"label": _("Type"), "fieldname": "ticket_type", "fieldtype": "Data", "width": 100},
			{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
			{"label": _("Root Cause"), "fieldname": "root_cause", "fieldtype": "Data", "width": 110},
			{"label": _("Hours to resolve"), "fieldname": "hours", "fieldtype": "Float", "width": 110},
			{"label": _("Past Deadline"), "fieldname": "sla_breached", "fieldtype": "Check", "width": 90}]
		return cols, rows, None, None, _summary(rows)
	key = GROUPS.get(f.group_by or "Root Cause", "root_cause")
	agg = {}
	for r in rows:
		g = agg.setdefault(r.get(key) or _("(not set)"), frappe._dict(group=r.get(key) or _("(not set)"), count=0, open=0, late=0,
			hours=[], on_time=0, resolved=0, qty=0))
		g.count += 1
		g.qty += flt(r.qty_affected)
		g.open += r.status in OPEN
		g.late += bool(r.sla_breached)
		if r.hours is not None:
			g.hours.append(r.hours)
			g.resolved += 1
			g.on_time += not r.sla_breached
	data = []
	for g in sorted(agg.values(), key=lambda g: -g.count):
		g.avg_hours = round(sum(g.hours) / len(g.hours), 1) if g.hours else None
		g.on_time_pct = round(g.on_time / g.resolved * 100, 1) if g.resolved else None
		del g["hours"]
		data.append(g)
	cols = [{"label": _(f.group_by or "Root Cause"), "fieldname": "group", "fieldtype": "Data", "width": 200},
		{"label": _("Tickets"), "fieldname": "count", "fieldtype": "Int", "width": 80},
		{"label": _("Still Open"), "fieldname": "open", "fieldtype": "Int", "width": 90},
		{"label": _("Past Deadline"), "fieldname": "late", "fieldtype": "Int", "width": 100},
		{"label": _("Avg Hours to Resolve"), "fieldname": "avg_hours", "fieldtype": "Float", "width": 140},
		{"label": _("Resolved on Time %"), "fieldname": "on_time_pct", "fieldtype": "Percent", "width": 130},
		{"label": _("Qty Affected"), "fieldname": "qty", "fieldtype": "Float", "width": 100}]
	chart = {"data": {"labels": [str(g.group) for g in data[:12]], "datasets": [{"name": _("Tickets"), "values": [g.count for g in data[:12]]}]},
		"type": "bar", "colors": ["#d97757"]} if data else None
	return cols, data, None, chart, _summary(rows)


def _summary(rows):
	resolved = [r for r in rows if r.hours is not None]
	return [{"label": _("Tickets"), "value": len(rows), "datatype": "Int"},
		{"label": _("Open"), "value": sum(r.status in OPEN for r in rows), "datatype": "Int", "indicator": "orange"},
		{"label": _("Past deadline"), "value": sum(bool(r.sla_breached) for r in rows), "datatype": "Int", "indicator": "red"},
		{"label": _("Avg hours to resolve"), "value": round(sum(r.hours for r in resolved) / len(resolved), 1) if resolved else 0, "datatype": "Float"}]
