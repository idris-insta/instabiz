"""IB Wastage Analysis — wastage of completed stages (IB WO Stage Event) against
the norm (machine Wastage Norm %, else IB Stock Settings default), grouped by
stage, machine, operator, item group, item or month. Qty is in each run's
own unit; runs of different units are kept apart in the Unit column."""
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import add_months, flt, getdate, today

from instabiz.overrides.wastage_watch import norm_for

GROUPS = {"Stage": "stage", "Machine": "machine", "Operator": "operator", "Item Group": "item_group",
	"Item": "item", "Month": "month"}


def execute(filters=None):
	f = frappe._dict(filters or {})
	f.from_date = f.from_date or add_months(today(), -1)
	f.to_date = f.to_date or today()
	by = GROUPS.get(f.group_by or "Machine", "machine")
	cond, args = ["e.skipped = 0", "e.completed_at IS NOT NULL", "e.input_qty > 0",
		"DATE(e.completed_at) BETWEEN %(from_date)s AND %(to_date)s", "wo.status != 'Cancelled'"], dict(f)
	for key, sql in (("location", "wo.location = %(location)s"), ("stage", "e.stage = %(stage)s"),
			("machine", "e.machine = %(machine)s"), ("operator", "e.operator = %(operator)s"),
			("item_group", "i.item_group = %(item_group)s")):
		if f.get(key):
			cond.append(sql)
	rows = frappe.db.sql(f"""SELECT e.stage, e.machine, e.operator, e.input_qty, e.output_qty, e.wastage_qty,
			e.wastage_pct, e.completed_at, wo.name AS run, wo.source_item AS item, i.item_group,
			(SELECT o.uom FROM `tabIB WO Output` o WHERE o.parent = wo.name ORDER BY o.idx LIMIT 1) AS uom
		FROM `tabIB WO Stage Event` e JOIN `tabIB Work Order` wo ON wo.name = e.parent
		LEFT JOIN `tabItem` i ON i.name = wo.source_item
		WHERE {' AND '.join(cond)}""", args, as_dict=True)

	agg = defaultdict(lambda: frappe._dict(events=0, input_qty=0.0, output_qty=0.0, wastage_qty=0.0, above=0, runs=set()))
	for r in rows:
		key_val = getdate(r.completed_at).strftime("%Y-%m") if by == "month" else (r.get(by) or _("(not set)"))
		a = agg[(key_val, r.uom or "")]
		a.events += 1
		a.input_qty += flt(r.input_qty)
		a.output_qty += flt(r.output_qty)
		a.wastage_qty += flt(r.wastage_qty)
		a.runs.add(r.run)
		a.norm_sum = a.get("norm_sum", 0) + norm_for(r.machine)
		if flt(r.wastage_pct) > norm_for(r.machine):
			a.above += 1
	data = []
	for (key_val, uom), a in agg.items():
		pct = round(a.wastage_qty / a.input_qty * 100, 2) if a.input_qty else 0
		norm = round(a.norm_sum / a.events, 2) if a.events else 0
		data.append({"group": key_val, "uom": uom, "runs": len(a.runs), "events": a.events,
			"input_qty": round(a.input_qty, 2), "output_qty": round(a.output_qty, 2), "wastage_qty": round(a.wastage_qty, 2),
			"wastage_pct": pct, "norm_pct": norm, "gap": round(pct - norm, 2), "above": a.above,
			"yield_pct": round(100 - pct, 2)})
	data.sort(key=lambda d: d["group"] if by == "month" else -d["gap"])

	cols = [{"label": _(f.group_by or "Machine"), "fieldname": "group", "fieldtype": "Data", "width": 170},
		{"label": _("Unit"), "fieldname": "uom", "fieldtype": "Data", "width": 70},
		{"label": _("Runs"), "fieldname": "runs", "fieldtype": "Int", "width": 70},
		{"label": _("Stages"), "fieldname": "events", "fieldtype": "Int", "width": 70},
		{"label": _("Input"), "fieldname": "input_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Output"), "fieldname": "output_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Wastage"), "fieldname": "wastage_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Wastage %"), "fieldname": "wastage_pct", "fieldtype": "Percent", "width": 95},
		{"label": _("Norm %"), "fieldname": "norm_pct", "fieldtype": "Percent", "width": 85},
		{"label": _("Over Norm (pts)"), "fieldname": "gap", "fieldtype": "Float", "width": 110},
		{"label": _("Stages Above Norm"), "fieldname": "above", "fieldtype": "Int", "width": 120},
		{"label": _("Yield %"), "fieldname": "yield_pct", "fieldtype": "Percent", "width": 85}]
	top = data[:12]
	chart = {"data": {"labels": [str(d["group"]) for d in top], "datasets": [
		{"name": _("Wastage %"), "values": [d["wastage_pct"] for d in top]},
		{"name": _("Norm %"), "values": [d["norm_pct"] for d in top]}]}, "type": "bar",
		"colors": ["#d97757", "#94a3b8"]} if top else None
	tin = sum(d["input_qty"] for d in data)
	tw = sum(d["wastage_qty"] for d in data)
	summary = [
		{"label": _("Stages completed"), "value": sum(d["events"] for d in data), "datatype": "Int"},
		{"label": _("Overall wastage %"), "value": round(tw / tin * 100, 2) if tin else 0, "datatype": "Percent"},
		{"label": _("Stages above norm"), "value": sum(d["above"] for d in data), "datatype": "Int",
			"indicator": "red" if any(d["above"] for d in data) else "green"},
	]
	msg = None if rows else _("No completed stages in this period. Wastage is recorded when the operator enters the real output on Complete.")
	return cols, data, msg, chart, summary
