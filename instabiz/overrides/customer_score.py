"""instabiz.overrides.customer_score — daily customer health score.

Idris 2026-09-21: order VALUE and order FREQUENCY both matter; behaviour
factors decide health. No fake-stable 60 defaults for missing history.

Weights:
  payment punctuality   25%
  order value (90d net) 25%
  order frequency/recency 20%
  complaints (12 mo)    15%
  CSAT (12 mo)          15%

Health: Green ≥70 / Amber ≥40 / Red <40 / Grey = insufficient history.
"""
from __future__ import annotations

import frappe
from frappe.utils import add_days, cint, flt, today


_WEIGHTS = {
	"payment": 0.25,
	"value": 0.25,
	"frequency": 0.20,
	"complaint": 0.15,
	"csat": 0.15,
}

_SCORE_DROP_ALERT_THRESHOLD = 15.0
# Net sales in 90d for "full marks" on value (INR). Above this still 100.
_VALUE_FULL_MARKS = 500000.0


def run_customer_score():
	customers = frappe.get_all(
		"Customer",
		filters={"disabled": 0},
		fields=["name", "customer_name"],
	)
	for c in customers:
		try:
			_compute_and_save(c)
		except Exception:
			frappe.log_error(f"IB Customer score: {c.name}"[:140], frappe.get_traceback())
	frappe.db.commit()


def _compute_and_save(customer: dict) -> None:
	today_str = today()
	if frappe.db.exists("IB Customer Score", {"customer": customer["name"], "score_date": today_str}):
		return

	payment_score, pay_ok = _payment_score(customer["name"])
	value_score, value_ok = _order_value_score(customer["name"])
	freq_score, freq_ok = _order_frequency_score(customer["name"])
	complaint_score = _complaint_score_12mo(customer["name"])
	csat_score, csat_ok = _csat_score(customer["name"])

	# Insufficient history: no payment trail AND no orders in window → Grey
	if not pay_ok and not value_ok and not freq_ok:
		health_status = "Grey"
		total = 0.0
		# still store component scores for transparency
	else:
		# Renormalize weights when CSAT missing (don't invent 60)
		weights = dict(_WEIGHTS)
		if not csat_ok:
			w = weights.pop("csat")
			rest = sum(weights.values())
			for k in list(weights):
				weights[k] += w * (weights[k] / rest)
			csat_score = 0.0

		total = (
			payment_score * weights.get("payment", 0)
			+ value_score * weights.get("value", 0)
			+ freq_score * weights.get("frequency", 0)
			+ complaint_score * weights.get("complaint", 0)
			+ csat_score * weights.get("csat", 0)
		)
		if total >= 70:
			health_status = "Green"
		elif total >= 40:
			health_status = "Amber"
		else:
			health_status = "Red"

	prev_record = frappe.db.get_value(
		"IB Customer Score",
		{"customer": customer["name"]},
		["name", "total_score"],
		order_by="score_date desc",
		as_dict=True,
	)
	previous_score = flt(prev_record.total_score) if prev_record else 0.0
	score_change = round(total - previous_score, 1)

	# order_score field kept for UI: blend of value+frequency for backward compat
	order_blend = round((value_score + freq_score) / 2.0, 1)

	doc = frappe.get_doc({
		"doctype": "IB Customer Score",
		"customer": customer["name"],
		"score_date": today_str,
		"health_status": health_status,
		"total_score": round(total, 1),
		"previous_score": round(previous_score, 1),
		"score_change": score_change,
		"payment_score": round(payment_score, 1),
		"order_score": order_blend,
		"complaint_score": round(complaint_score, 1),
		"csat_score": round(csat_score, 1),
	})
	# optional component fields if present
	meta = frappe.get_meta("IB Customer Score")
	if meta.has_field("order_value_score"):
		doc.order_value_score = round(value_score, 1)
	if meta.has_field("order_frequency_score"):
		doc.order_frequency_score = round(freq_score, 1)
	doc.insert(ignore_permissions=True)

	if health_status != "Grey" and score_change <= -_SCORE_DROP_ALERT_THRESHOLD:
		_alert_score_drop(customer, round(total, 1), round(previous_score, 1), health_status)


def _payment_score(customer: str) -> tuple[float, bool]:
	rows = frappe.db.sql(
		"""
		SELECT si.due_date,
		       COALESCE(MAX(pe.posting_date), CURDATE()) AS paid_on,
		       si.status, si.outstanding_amount
		FROM `tabSales Invoice` si
		LEFT JOIN `tabPayment Entry Reference` per
			ON per.reference_name = si.name AND per.reference_doctype = 'Sales Invoice'
		LEFT JOIN `tabPayment Entry` pe
			ON pe.name = per.parent AND pe.docstatus = 1
		WHERE si.customer = %s AND si.docstatus = 1 AND si.is_return = 0
		  AND si.status IN ('Paid', 'Overdue', 'Unpaid', 'Partly Paid')
		  AND si.posting_date >= %s
		GROUP BY si.name, si.due_date, si.status, si.outstanding_amount
		""",
		(customer, add_days(today(), -365)),
		as_dict=True,
	)
	if not rows:
		return 0.0, False

	late_days = []
	for r in rows:
		if r.status in ("Overdue", "Unpaid", "Partly Paid") and flt(r.outstanding_amount) > 0 and r.due_date:
			late_days.append(max(0, (frappe.utils.getdate(today()) - frappe.utils.getdate(r.due_date)).days))
		elif r.paid_on and r.due_date and r.paid_on > r.due_date:
			late_days.append(max(0, (r.paid_on - r.due_date).days))
		else:
			late_days.append(0)
	avg_late = sum(late_days) / len(late_days)
	return min(100.0, max(0.0, 100.0 - avg_late * 5)), True


def _order_value_score(customer: str) -> tuple[float, bool]:
	"""Net sales (grand − taxes approx via base_net_total) last 90 days → 0–100."""
	net = flt(
		frappe.db.sql(
			"""
			SELECT COALESCE(SUM(base_net_total), 0)
			FROM `tabSales Invoice`
			WHERE customer = %s AND docstatus = 1 AND is_return = 0
			  AND posting_date >= %s
			""",
			(customer, add_days(today(), -90)),
		)[0][0]
	)
	if net <= 0:
		# try SO if no SI yet
		net = flt(
			frappe.db.sql(
				"""
				SELECT COALESCE(SUM(base_net_total), 0)
				FROM `tabSales Order`
				WHERE customer = %s AND docstatus = 1
				  AND transaction_date >= %s
				""",
				(customer, add_days(today(), -90)),
			)[0][0]
		)
	if net <= 0:
		return 0.0, False
	# sqrt curve so mid-size accounts aren't crushed vs whales
	import math
	score = 100.0 * math.sqrt(min(net, _VALUE_FULL_MARKS) / _VALUE_FULL_MARKS)
	return min(100.0, score), True


def _order_frequency_score(customer: str) -> tuple[float, bool]:
	"""Frequency + recency of submitted SOs in 180 days."""
	rows = frappe.db.sql(
		"""
		SELECT transaction_date
		FROM `tabSales Order`
		WHERE customer = %s AND docstatus = 1
		  AND transaction_date >= %s
		ORDER BY transaction_date DESC
		""",
		(customer, add_days(today(), -180)),
		as_dict=True,
	)
	if not rows:
		return 0.0, False
	count = len(rows)
	# 6+ orders in 180d → strong frequency
	freq = min(100.0, count * (100.0 / 6.0))
	last = rows[0].transaction_date
	days_since = (frappe.utils.getdate(today()) - frappe.utils.getdate(last)).days
	# recency: 100 if ordered in last 14d, down to 0 at 180d
	recency = min(100.0, max(0.0, 100.0 - (days_since / 180.0) * 100.0))
	return 0.6 * freq + 0.4 * recency, True


def _complaint_score_12mo(customer: str) -> float:
	"""Open/recent complaints in last 12 months only."""
	if frappe.db.exists("DocType", "IB Support Ticket"):
		cnt = frappe.db.count(
			"IB Support Ticket",
			filters={
				"customer": customer,
				"creation": [">=", add_days(today(), -365)],
				"status": ["not in", ["Closed", "Cancelled", "Resolved"]],
			},
		)
		# also count resolved in window lightly
		resolved = frappe.db.count(
			"IB Support Ticket",
			filters={
				"customer": customer,
				"creation": [">=", add_days(today(), -365)],
				"status": ["in", ["Closed", "Resolved"]],
			},
		)
		penalty = cnt * 25 + resolved * 5
	else:
		# fallback: lifetime field but capped interpretation
		lifetime = cint(frappe.db.get_value("Customer", customer, "custom_complaint_count") or 0)
		penalty = min(lifetime, 4) * 20
	return max(0.0, 100.0 - penalty)


def _csat_score(customer: str) -> tuple[float, bool]:
	result = frappe.db.sql(
		"""
		SELECT AVG(CAST(custom_csat_rating AS DECIMAL(10,2))) AS avg_rating, COUNT(*) AS n
		FROM `tabSales Invoice`
		WHERE customer = %s AND docstatus = 1 AND is_return = 0
		  AND custom_csat_rating IS NOT NULL AND custom_csat_rating != ''
		  AND posting_date >= %s
		""",
		(customer, add_days(today(), -365)),
	)
	if not result or not result[0][1]:
		return 0.0, False
	avg = float(result[0][0] or 0)
	# assume 1–5 scale
	return min(100.0, max(0.0, (avg - 1) / 4 * 100)), True


def _alert_score_drop(customer: dict, new_score: float, prev_score: float, status: str) -> None:
	managers = frappe.get_all(
		"Has Role",
		filters={"role": ["in", ["Sales Manager", "System Manager"]], "parenttype": "User"},
		pluck="parent",
	)
	for u in set(managers) - {"Administrator"}:
		if not frappe.db.get_value("User", u, "enabled"):
			continue
		frappe.get_doc({
			"doctype": "Notification Log",
			"for_user": u,
			"type": "Alert",
			"subject": (
				"Health drop: {0} {1:g}->{2:g} ({3})".format(
					customer.get("customer_name") or customer.get("name"), prev_score, new_score, status
				)
			)[:140],
			"document_type": "Customer",
			"document_name": customer["name"],
			"from_user": "Administrator",
		}).insert(ignore_permissions=True)


def ensure_health_fields():
	"""Grey status + value/frequency component fields."""
	# health_status options
	ps = frappe.db.exists(
		"Property Setter",
		{"doc_type": "IB Customer Score", "field_name": "health_status", "property": "options"},
	)
	opts = "Green\nAmber\nRed\nGrey"
	if ps:
		frappe.db.set_value("Property Setter", ps, "value", opts)
	else:
		frappe.get_doc({
			"doctype": "Property Setter",
			"doctype_or_field": "DocField",
			"doc_type": "IB Customer Score",
			"field_name": "health_status",
			"property": "options",
			"value": opts,
			"property_type": "Text",
		}).insert(ignore_permissions=True)
	for f in (
		{"fieldname": "order_value_score", "label": "Order Value Score", "insert_after": "order_score"},
		{"fieldname": "order_frequency_score", "label": "Order Frequency Score", "insert_after": "order_value_score"},
	):
		if frappe.db.exists("Custom Field", {"dt": "IB Customer Score", "fieldname": f["fieldname"]}):
			continue
		if frappe.get_meta("IB Customer Score").has_field(f["fieldname"]):
			continue
		frappe.get_doc({
			"doctype": "Custom Field",
			"dt": "IB Customer Score",
			"fieldtype": "Float",
			**f,
		}).insert(ignore_permissions=True)
	frappe.clear_cache(doctype="IB Customer Score")
	return True