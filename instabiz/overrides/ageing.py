"""instabiz.overrides.ageing

User-defined ageing intervals for the ageing reports (AR, AP, stock): the
"Ageing (days)" filter takes break points like "15,30,45,60,90" and the fixed
0-30 / 31-60 / 61-90 / 90+ columns, chart and "oldest" card are rebuilt for
those buckets. Rows must carry age_days and the amount / qty field.
"""
from frappe import _
from frappe.utils import flt

OLD = ("b0_30", "b31_60", "b61_90", "b90plus")


def ranges(filters):
	raw = str((filters or {}).get("ranges") or "30,60,90")
	pts = sorted({int(x) for x in raw.replace(" ", "").split(",") if x.isdigit() and int(x) > 0})
	return pts[:8] or [30, 60, 90]


def labels(pts):
	out, lo = [], 0
	for p in pts:
		out.append(f"{lo}-{p}")
		lo = p + 1
	return out + [f"{pts[-1]}+"]


def rebucket(filters, columns, data, amount_key, fieldtype="Currency", chart=None, summary=None):
	pts = ranges(filters)
	names = labels(pts)
	new_cols = [{"label": _(n), "fieldname": f"age_{i}", "fieldtype": fieldtype, "width": 110} for i, n in enumerate(names)]
	at = next((i for i, c in enumerate(columns) if c.get("fieldname") in OLD), len(columns))
	columns = [c for c in columns if c.get("fieldname") not in OLD]
	columns[at:at] = new_cols
	totals = [0.0] * len(names)
	for row in data:
		age, amt = int(row.get("age_days") or 0), flt(row.get(amount_key))
		idx = next((i for i, p in enumerate(pts) if age <= p), len(pts))
		for i in range(len(names)):
			row[f"age_{i}"] = amt if i == idx else 0
		totals[idx] += amt
		row["b90plus"] = row[f"age_{len(names) - 1}"]
	if chart:
		chart["data"] = {"labels": names, "datasets": [{"name": chart["data"]["datasets"][0]["name"], "values": [round(t, 2) for t in totals]}]}
		chart.pop("colors", None)
	for card in summary or []:
		if "90+" in str(card.get("label")):
			card["label"] = _("{0}+ Days").format(pts[-1])
			card["value"] = totals[-1]
	return columns, data, chart, summary
