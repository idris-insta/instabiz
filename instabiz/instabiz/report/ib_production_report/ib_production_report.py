"""instabiz.instabiz.report.ib_production_report.ib_production_report"""
import frappe
from frappe.utils import flt


def execute(filters=None):
	"""Per-completion production report.

	Sourced from IB WO Stage Event (one row per stage actually completed),
	not IB Work Order.stage/.completed_qty/.target_uom — those are orphaned
	pre-WO-per-run legacy DB columns, confirmed NULL/0 on every real modern
	Work Order (see get_dpr()'s docstring, instabiz/overrides/production.py,
	fixed the same way 2026-09-13) — this report always returned real rows
	(status='Completed' correctly matched real WOs) but every one of them
	showed a blank stage and "0" output, silently, since the WO-per-run
	migration. Wastage is left out for the same reason get_dpr() leaves it
	out: wastage isn't captured on a real completion path either.

	Output Qty carries a Unit column (target_uom) — a raw qty number with no
	unit is meaningless (a Work Order's target_uom varies per item: PCS,
	SQMT, ROLL, KG all occur), and the chart/summary below never sum across
	rows of different units into one blended figure, same reasoning as
	get_dpr()'s own output_by_uom split.
	"""
	columns = _columns()
	data = _data(filters)
	chart = _chart(data, filters)
	summary = _summary(data)
	return columns, data, None, chart, summary


def _columns():
	return [
		{"fieldname": "completed_date", "label": "Date", "fieldtype": "Date", "width": 100},
		{"fieldname": "work_order", "label": "Work Order", "fieldtype": "Link", "options": "IB Work Order", "width": 135},
		{"fieldname": "item_code", "label": "Item", "fieldtype": "Link", "options": "Item", "width": 130},
		{"fieldname": "stage", "label": "Stage", "fieldtype": "Data", "width": 115},
		{"fieldname": "machine", "label": "Machine", "fieldtype": "Link", "options": "IB Machine", "width": 110},
		{"fieldname": "operator", "label": "Operator", "fieldtype": "Link", "options": "User", "width": 130},
		{"fieldname": "order_sheet", "label": "Order Sheet", "fieldtype": "Link", "options": "IB Order Sheet", "width": 135},
		{"fieldname": "sales_order", "label": "Sales Order", "fieldtype": "Link", "options": "Sales Order", "width": 135},
		{"fieldname": "customer_name", "label": "Customer", "fieldtype": "Data", "width": 150},
		{"fieldname": "output_qty", "label": "Output Qty", "fieldtype": "Float", "width": 90},
		{"fieldname": "target_uom", "label": "Unit", "fieldtype": "Data", "width": 70},
		{"fieldname": "hours", "label": "Hours", "fieldtype": "Float", "width": 75},
	]


def _data(filters):
	conditions = "e.skipped = 0"
	params = {}
	if filters:
		if filters.get("from_date"):
			conditions += " AND DATE(e.completed_at) >= %(from_date)s"
			params["from_date"] = filters["from_date"]
		if filters.get("to_date"):
			conditions += " AND DATE(e.completed_at) <= %(to_date)s"
			params["to_date"] = filters["to_date"]
		if filters.get("stage"):
			conditions += " AND e.stage = %(stage)s"
			params["stage"] = filters["stage"]
		if filters.get("machine"):
			conditions += " AND e.machine = %(machine)s"
			params["machine"] = filters["machine"]
		if filters.get("operator"):
			conditions += " AND e.operator = %(operator)s"
			params["operator"] = filters["operator"]

	return frappe.db.sql(
		f"""
		SELECT wo.name AS work_order, DATE(e.completed_at) AS completed_date,
		       fo.item_code, e.stage, e.machine, e.operator, wo.order_sheet,
		       wo.sales_order, so.customer_name, e.output_qty AS output_qty,
		       COALESCE(fo.uom, 'Unknown') AS target_uom,
		       TIMESTAMPDIFF(MINUTE, e.started_at, e.completed_at) / 60.0 AS hours
		FROM `tabIB WO Stage Event` e
		JOIN `tabIB Work Order` wo ON wo.name = e.parent
		LEFT JOIN `tabIB WO Output` fo
			ON fo.parent = e.parent
			AND fo.idx = (SELECT MIN(idx) FROM `tabIB WO Output` WHERE parent = e.parent)
		LEFT JOIN `tabSales Order` so ON so.name = wo.sales_order
		WHERE {conditions}
		ORDER BY e.completed_at DESC, wo.creation DESC
		""",
		params,
		as_dict=True,
	)


def _chart(data, filters=None):
	if not data:
		return None

	# One dataset per UOM (not one blended series) — a stage that produced
	# both PCS and SQMT work gets two bars, not one bar adding them together.
	stages = []
	stage_output = {}  # uom -> {stage -> qty}
	for row in data:
		s = row.stage or "Unknown"
		if s not in stages:
			stages.append(s)
		uom = row.target_uom or "Unknown"
		stage_output.setdefault(uom, {})
		stage_output[uom][s] = flt(stage_output[uom].get(s, 0)) + flt(row.output_qty)

	chart_type = (filters or {}).get("chart_type", "bar")
	return {
		"data": {
			"labels": stages,
			"datasets": [
				{"name": f"Output ({uom})", "values": [by_stage.get(s, 0) for s in stages]}
				for uom, by_stage in sorted(stage_output.items())
			],
		},
		"type": chart_type,
		"fieldtype": "Float",
	}


def _summary(data):
	if not data:
		return []
	total_entries = len(data)
	total_hours = round(sum(flt(r.hours) for r in data if r.hours), 2)

	output_by_uom = {}
	for r in data:
		uom = r.target_uom or "Unknown"
		output_by_uom[uom] = output_by_uom.get(uom, 0.0) + flt(r.output_qty)

	summary = [
		{"value": total_entries, "label": "Work Orders Completed", "indicator": "blue", "datatype": "Int"},
	]
	for uom, qty in sorted(output_by_uom.items()):
		summary.append({"value": round(qty, 2), "label": f"Output — {uom}", "indicator": "green", "datatype": "Float"})
	summary.append({"value": total_hours, "label": "Total Hours", "indicator": "blue", "datatype": "Float"})
	return summary
