"""IB Price Suggestions — read-only listing/export of `IB Price Suggestion` rows.

Pure listing report (no aggregation) — the actual computation lives in the
weekly scheduler (`instabiz.overrides.price_recommender.run_weekly_price_suggestions`),
which never writes anywhere except `IB Price Suggestion`. This report exists
for consistency/exportability with the rest of the app's reports, per the
build spec — the doctype's own list view already shows the same data, this
adds filters + a chart + summary cards to match the other 20 Script Reports.
"""
import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = filters or {}
	data = _data(filters)
	columns = _columns()
	return columns, data, None, _chart(data, filters), _summary(data)


def _columns():
	return [
		{"label": _("Item"),             "fieldname": "item",                  "fieldtype": "Link",     "options": "Item", "width": 150},
		{"label": _("Item Name"),        "fieldname": "item_name",             "fieldtype": "Data",     "width": 200},
		{"label": _("Customer"),         "fieldname": "customer",              "fieldtype": "Link",     "options": "Customer", "width": 150},
		{"label": _("Current Price"),    "fieldname": "current_price",         "fieldtype": "Currency", "width": 120},
		{"label": _("Suggested Price"),  "fieldname": "suggested_price",       "fieldtype": "Currency", "width": 130},
		{"label": _("Deviation %"),      "fieldname": "deviation_pct",         "fieldtype": "Percent",  "width": 110},
		{"label": _("Margin Target %"),  "fieldname": "margin_target_pct",     "fieldtype": "Percent",  "width": 120},
		{"label": _("Current Margin %"), "fieldname": "current_margin_pct",    "fieldtype": "Percent",  "width": 120},
		{"label": _("Demand Velocity"),  "fieldname": "demand_velocity_signal","fieldtype": "Data",     "width": 220},
		{"label": _("Needs Review"),     "fieldname": "needs_review",          "fieldtype": "Check",    "width": 100},
		{"label": _("Status"),           "fieldname": "status",                "fieldtype": "Data",     "width": 100},
		{"label": _("Computed On"),      "fieldname": "computed_on",           "fieldtype": "Date",     "width": 110},
	]


def _data(filters):
	conditions = ["1=1"]
	params = {}

	if filters.get("status"):
		conditions.append("status = %(status)s")
		params["status"] = filters["status"]
	if filters.get("needs_review_only"):
		conditions.append("needs_review = 1")
	if filters.get("item"):
		conditions.append("item = %(item)s")
		params["item"] = filters["item"]
	if filters.get("customer"):
		conditions.append("customer = %(customer)s")
		params["customer"] = filters["customer"]
	from instabiz.overrides.own_data import locked_user, own_customers_sql

	if locked_user():  # a plain Sales User: general suggestions + their own customers
		conditions.append(f"(IFNULL(customer, '') = '' OR customer IN {own_customers_sql(locked_user())})")

	return frappe.db.sql(
		f"""
		SELECT item, item_name, customer, current_price, suggested_price,
		       deviation_pct, margin_target_pct, current_margin_pct,
		       demand_velocity_signal, needs_review, status, computed_on
		FROM `tabIB Price Suggestion`
		WHERE {" AND ".join(conditions)}
		ORDER BY ABS(deviation_pct) DESC, computed_on DESC
		""",
		params,
		as_dict=True,
	)


def _chart(data, filters=None):
	if not data:
		return None
	chart_type = (filters or {}).get("chart_type") or "bar"
	top = sorted(data, key=lambda r: abs(flt(r.get("deviation_pct"))), reverse=True)[:10]
	return {
		"data": {
			"labels": [r["item"] for r in top],
			"datasets": [
				{"name": _("Current Price"),   "values": [flt(r["current_price"]) for r in top]},
				{"name": _("Suggested Price"), "values": [flt(r["suggested_price"]) for r in top]},
			],
		},
		"type": chart_type,
		"colors": ["#6b7280", "#d97757"],
	}


def _summary(data):
	if not data:
		return None
	needs_review_count = sum(1 for r in data if r.get("needs_review"))
	avg_deviation = flt(sum(abs(flt(r.get("deviation_pct"))) for r in data) / len(data), 2)
	new_count = sum(1 for r in data if r.get("status") == "New")
	return [
		{"value": len(data),             "label": _("Suggestions"),      "datatype": "Int",     "indicator": "blue"},
		{"value": new_count,             "label": _("New"),              "datatype": "Int",     "indicator": "orange"},
		{"value": needs_review_count,    "label": _("Needs Review"),     "datatype": "Int",     "indicator": "red"},
		{"value": avg_deviation,         "label": _("Avg |Deviation| %"),"datatype": "Percent", "indicator": "purple"},
	]
