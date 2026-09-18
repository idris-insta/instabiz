"""IB Collections Priority — who to chase for payment today, most urgent first.

One row per customer, built on the same outstanding basis as IB AR Aging
(billing_mode aware: Sales Order in dev mode, Sales Invoice in prod). Priority
weighs amount by how old the oldest unpaid document is and by the customer's
latest health score. Sales Users see only customers they handle.
"""
import frappe
from frappe import _
from frappe.utils import flt

from instabiz.instabiz.report.ib_ar_aging.ib_ar_aging import _data as ar_rows
from instabiz.overrides.permissions import _is_privileged

_COMPANY_WIDE_ROLES = {"Accounts User", "Accounts Manager", "System Manager", "Sales Manager"}
_HEALTH_WEIGHT = {"Red": 1.3, "Amber": 1.1, "Green": 1.0}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	user = frappe.session.user
	if not (_is_privileged(user) or _COMPANY_WIDE_ROLES & set(frappe.get_roles(user))):
		filters.sales_person_user = user
	data = _data(filters)
	return _columns(), data, None, None, _summary(data)


def _columns():
	return [
		{"label": _("Rank"), "fieldname": "rank", "fieldtype": "Int", "width": 60},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 210},
		{"label": _("Outstanding"), "fieldname": "outstanding", "fieldtype": "Currency", "width": 130},
		{"label": _("Oldest (days)"), "fieldname": "oldest_age", "fieldtype": "Int", "width": 105},
		{"label": _("90+ Days"), "fieldname": "b90plus", "fieldtype": "Currency", "width": 120},
		{"label": _("Documents"), "fieldname": "docs", "fieldtype": "Int", "width": 90},
		{"label": _("Health"), "fieldname": "health", "fieldtype": "Data", "width": 80},
		{"label": _("Priority"), "fieldname": "priority", "fieldtype": "Float", "precision": 1, "width": 90},
		{"label": _("Sales Person"), "fieldname": "sales_person", "fieldtype": "Data", "width": 140},
		{"label": _("Mobile"), "fieldname": "mobile", "fieldtype": "Data", "width": 120},
		{"label": _("Reminder"), "fieldname": "reminder", "fieldtype": "Data", "width": 110},
	]


def _data(filters):
	by_customer = {}
	for r in ar_rows(filters):
		c = by_customer.setdefault(r["customer"], {
			"customer": r["customer"], "outstanding": 0.0, "oldest_age": 0, "b90plus": 0.0,
			"docs": 0, "sales_person": r["sales_person"],
		})
		c["outstanding"] += flt(r["outstanding"])
		c["b90plus"] += flt(r["b90plus"])
		c["oldest_age"] = max(c["oldest_age"], r["age_days"])
		c["docs"] += 1

	if not by_customer:
		return []

	names = list(by_customer)
	health = {
		r.customer: r.health_status
		for r in frappe.db.sql(
			"""
			SELECT s.customer, s.health_status
			FROM `tabIB Customer Score` s
			INNER JOIN (
				SELECT customer, MAX(score_date) AS d FROM `tabIB Customer Score`
				WHERE customer IN %(c)s GROUP BY customer
			) latest ON latest.customer = s.customer AND latest.d = s.score_date
			""",
			{"c": names},
			as_dict=True,
		)
	}
	cust = {
		r.name: r for r in frappe.get_all(
			"Customer", filters={"name": ["in", names]}, fields=["name", "customer_name", "mobile_no"]
		)
	}

	rows = []
	for name, c in by_customer.items():
		h = health.get(name) or ""
		# amount (in lakh) x age factor x health weight
		c["priority"] = round(
			c["outstanding"] / 100000 * (1 + c["oldest_age"] / 30) * _HEALTH_WEIGHT.get(h, 1.0), 1
		)
		c["health"] = h
		c["mobile"] = (cust.get(name) or {}).get("mobile_no") or ""
		c["customer_name"] = (cust.get(name) or {}).get("customer_name") or name
		c["reminder"] = "WhatsApp" if c["mobile"] else ""
		rows.append(c)

	rows.sort(key=lambda r: r["priority"], reverse=True)
	for i, r in enumerate(rows, 1):
		r["rank"] = i
	return rows


def _summary(data):
	total = sum(r["outstanding"] for r in data)
	top10 = sum(r["outstanding"] for r in data[:10])
	return [
		{"label": _("Customers to chase"), "value": len(data), "datatype": "Int", "indicator": "blue"},
		{"label": _("Total outstanding"), "value": total, "datatype": "Currency", "indicator": "orange"},
		{"label": _("Top 10 share"), "value": round(top10 / total * 100, 1) if total else 0,
			"datatype": "Percent", "indicator": "red"},
		{"label": _("Past 90 days"), "value": sum(r["b90plus"] for r in data), "datatype": "Currency", "indicator": "red"},
	]
