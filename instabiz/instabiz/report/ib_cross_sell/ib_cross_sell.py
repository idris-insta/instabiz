"""IB Cross Sell — families each customer doesn't buy yet.

Customer view: families bought, their value, and the families most often
bought alongside them that this customer has never taken — the next thing to
offer. "Single family only" narrows to one-family accounts (e.g. BOPP only).
Pairs view: for each two families, how many customers buy both, and how
likely a buyer of the first is to buy the second — evidence, not opinion.
"""
from collections import defaultdict
from itertools import combinations

import frappe
from frappe import _
from frappe.utils import flt

from instabiz.overrides.sales_analytics import period, sales_lines


def execute(filters=None):
	f = frappe._dict(filters or {})
	start, end, _m = period(f, months=12)
	lines = sales_lines(start, end)
	fam = defaultdict(lambda: defaultdict(float))
	info = {}
	for r in lines:
		fam[r.customer][r.item_group or "—"] += flt(r.amount)
		info[r.customer] = r
	if (f.view or "Customer") == "Pairs":
		return _pairs(fam)
	return _customers(f, fam, info)


def _affinity(fam):
	"""P(buys B | buys A) for every family pair."""
	buyers = defaultdict(int)
	both = defaultdict(int)
	for fams in fam.values():
		keys = sorted(fams)
		for a in keys:
			buyers[a] += 1
		for a, b in combinations(keys, 2):
			both[(a, b)] += 1
			both[(b, a)] += 1
	return buyers, both


def _customers(f, fam, info):
	buyers, both = _affinity(fam)
	data = []
	for cust, fams in fam.items():
		if f.single_family and len(fams) != 1:
			continue
		if f.family and f.family not in fams:
			continue
		score = defaultdict(float)
		for a in fams:
			for (x, b), n in both.items():
				if x == a and b not in fams and buyers[a]:
					score[b] = max(score[b], n / buyers[a])
		suggestions = sorted(score.items(), key=lambda kv: -kv[1])[:3]
		value = sum(fams.values())
		data.append(frappe._dict(customer=cust, customer_name=info[cust].customer_name, sales_person=info[cust].sales_person,
			families=len(fams), bought=", ".join(k for k, _v in sorted(fams.items(), key=lambda kv: -kv[1])),
			value=value, main_family=max(fams.items(), key=lambda kv: kv[1])[0],
			main_share=round(max(fams.values()) * 100 / value, 1) if value else 0,
			next_1=_fmt(suggestions, 0), next_2=_fmt(suggestions, 1), next_3=_fmt(suggestions, 2)))
	data.sort(key=lambda d: -d.value)
	cols = [
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 200},
		{"label": _("Sales Person"), "fieldname": "sales_person", "fieldtype": "Data", "width": 115},
		{"label": _("Families"), "fieldname": "families", "fieldtype": "Int", "width": 70},
		{"label": _("Value"), "fieldname": "value", "fieldtype": "Currency", "width": 120},
		{"label": _("Main Family"), "fieldname": "main_family", "fieldtype": "Data", "width": 120},
		{"label": _("Main %"), "fieldname": "main_share", "fieldtype": "Float", "precision": 1, "width": 70},
		{"label": _("Offer Next"), "fieldname": "next_1", "fieldtype": "Data", "width": 170},
		{"label": _("Then"), "fieldname": "next_2", "fieldtype": "Data", "width": 160},
		{"label": _("Then"), "fieldname": "next_3", "fieldtype": "Data", "width": 160},
		{"label": _("Buys Now"), "fieldname": "bought", "fieldtype": "Data", "width": 260},
	]
	single = [d for d in data if d.families == 1]
	return cols, data, None, None, [
		{"label": _("Customers"), "value": len(data), "datatype": "Int"},
		{"label": _("Avg families / customer"), "value": round(sum(d.families for d in data) / len(data), 1) if data else 0, "datatype": "Float"},
		{"label": _("Single-family accounts"), "value": len(single), "datatype": "Int", "indicator": "orange"},
		{"label": _("Their value"), "value": sum(d.value for d in single), "datatype": "Currency"},
	]


def _fmt(s, i):
	return f"{s[i][0]} ({round(s[i][1] * 100)}%)" if len(s) > i else ""


def _pairs(fam):
	buyers, both = _affinity(fam)
	data = []
	for (a, b), n in both.items():
		if a < b:
			data.append(frappe._dict(family_a=a, family_b=b, both=n, buyers_a=buyers[a], buyers_b=buyers[b],
				a_to_b=round(n * 100 / buyers[a], 1), b_to_a=round(n * 100 / buyers[b], 1)))
	data.sort(key=lambda d: -d.both)
	cols = [
		{"label": _("Family A"), "fieldname": "family_a", "fieldtype": "Data", "width": 150},
		{"label": _("Family B"), "fieldname": "family_b", "fieldtype": "Data", "width": 150},
		{"label": _("Customers buying both"), "fieldname": "both", "fieldtype": "Int", "width": 150},
		{"label": _("Buyers of A"), "fieldname": "buyers_a", "fieldtype": "Int", "width": 100},
		{"label": _("Buyers of B"), "fieldname": "buyers_b", "fieldtype": "Int", "width": 100},
		{"label": _("A buyers who take B %"), "fieldname": "a_to_b", "fieldtype": "Float", "precision": 1, "width": 150},
		{"label": _("B buyers who take A %"), "fieldname": "b_to_a", "fieldtype": "Float", "precision": 1, "width": 150},
	]
	return cols, data
