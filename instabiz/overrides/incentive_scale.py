"""instabiz.overrides.incentive_scale

Monthly sales incentive the way "COMM ACC MUM 2026.xlsx" works it out:
  net sale  = sale − GST (− unpaid, when asked)
  incentive = sum over the person's scale of rate × the part of net sale inside each band
(marginal slabs; the last band has no cap). The person's scale comes from
User.custom_incentive_scale.

Sales follow the billing mode used everywhere else: Sales Orders by creation
date while billing runs on orders, Sales Invoices by posting date afterwards.
"""
import frappe
from frappe.utils import flt, get_first_day, get_last_day, getdate

from instabiz.overrides.billing_mode import is_dev_billing_mode

# The four scales on the STRUCTURE sheet (band size, then 0 / 0.25 / 0.5 / 0.75 / 1 %)
DEFAULT_SCALES = {
	"Sales Executive": 250000,
	"Area Sales Manager": 500000,
	"Sales Manager": 1000000,
	"Export Sales Manager": 1000000,
}
RATES = (0, 0.25, 0.5, 0.75, 1.0)
# who was on which sheet block (first name → scale); only applied to users with no scale yet
SHEET_PEOPLE = {
	"nazim": "Sales Manager", "junaid": "Area Sales Manager", "abdul": "Area Sales Manager",
	"amira": "Area Sales Manager", "prajakta": "Sales Executive", "mantasha": "Sales Executive",
	"nidhi": "Sales Executive", "ruhi": "Sales Executive", "sarvajeet": "Sales Executive", "zaid": "Sales Executive",
}


def slab_breakup(net, slabs):
	"""[(label, from, to, rate, base, incentive)] for a net sale on a scale."""
	out = []
	for i, s in enumerate(sorted(slabs, key=lambda s: flt(s.from_amount))):
		lo, hi = flt(s.from_amount), flt(s.to_amount)
		top = net if not hi else min(net, hi)
		base = max(top - lo, 0)
		out.append((s.slab_label or f"Slab {i + 1}", lo, hi, flt(s.rate_pct), base, round(base * flt(s.rate_pct) / 100, 2)))
	return out


def scale_slabs(scale):
	if not scale or not frappe.db.exists("IB Incentive Scale", scale):
		return []
	return frappe.get_all("IB Incentive Scale Slab", filters={"parent": scale},
		fields=["slab_label", "from_amount", "to_amount", "rate_pct"], order_by="from_amount asc")


def net_sales(month_start, month_end, user=None, deduct_unpaid=False):
	"""{user: {gross, gst, unpaid, net, docs}} for the period."""
	if is_dev_billing_mode():
		doctype, date_expr = "Sales Order", "DATE(creation)"
		unpaid_expr = "GREATEST(rounded_total - IFNULL(custom_advance_paid, 0), 0)"
	else:
		doctype, date_expr = "Sales Invoice", "posting_date"
		unpaid_expr = "outstanding_amount"
	cond, args = "", {"from": month_start, "to": month_end}
	if user:
		cond = " AND custom_sales_person_user = %(user)s"
		args["user"] = user
	rows = frappe.db.sql(
		f"""SELECT custom_sales_person_user AS user, SUM(base_rounded_total) AS gross,
		           SUM(base_rounded_total - base_net_total) AS gst,
		           SUM(({unpaid_expr}) * base_net_total / NULLIF(base_rounded_total, 0)) AS unpaid,
		           COUNT(*) AS docs
		FROM `tab{doctype}`
		WHERE docstatus = 1 AND IFNULL(custom_sales_person_user, '') != ''
		  AND {date_expr} BETWEEN %(from)s AND %(to)s {cond}
		GROUP BY custom_sales_person_user""",
		args, as_dict=True,
	)
	out = {}
	for r in rows:
		unpaid = flt(r.unpaid) if deduct_unpaid else 0
		out[r.user] = frappe._dict(gross=flt(r.gross), gst=flt(r.gst), unpaid=unpaid,
			net=flt(r.gross) - flt(r.gst) - unpaid, docs=r.docs)
	return out


def month_bounds(month):
	d = getdate(month)
	return get_first_day(d), get_last_day(d)


@frappe.whitelist()
def incentive_for(user, month):
	"""One person's incentive for one month (used by the report and the Sales Incentives page)."""
	if user != frappe.session.user and not frappe.has_permission("IB Incentive Scale", "write"):
		frappe.throw(frappe._("Not permitted"), frappe.PermissionError)
	start, end = month_bounds(month)
	scale = frappe.db.get_value("User", user, "custom_incentive_scale")
	sale = net_sales(start, end, user).get(user) or frappe._dict(gross=0, gst=0, unpaid=0, net=0, docs=0)
	rows = slab_breakup(sale.net, scale_slabs(scale))
	return {"scale": scale, "sale": sale, "slabs": rows, "incentive": sum(r[5] for r in rows)}


def after_migrate():
	_ensure_user_field()
	_seed_scales()
	_map_sheet_people()


def _ensure_user_field():
	if frappe.db.exists("Custom Field", {"dt": "User", "fieldname": "custom_incentive_scale"}):
		return
	frappe.get_doc({
		"doctype": "Custom Field", "dt": "User", "fieldname": "custom_incentive_scale",
		"label": "Incentive Scale", "fieldtype": "Link", "options": "IB Incentive Scale",
		"insert_after": "role_profile_name",
		"description": "Monthly sales incentive scale (IB Incentive Scale).",
	}).insert(ignore_permissions=True)


def _seed_scales():
	if not frappe.db.exists("DocType", "IB Incentive Scale"):
		return
	for name, band in DEFAULT_SCALES.items():
		if frappe.db.exists("IB Incentive Scale", name):
			continue
		doc = frappe.new_doc("IB Incentive Scale")
		doc.scale_name = name
		for i, rate in enumerate(RATES):
			doc.append("slabs", {"slab_label": f"Slab {i + 1}", "from_amount": band * i,
				"to_amount": 0 if i == len(RATES) - 1 else band * (i + 1), "rate_pct": rate})
		doc.insert(ignore_permissions=True)


def _map_sheet_people():
	if not frappe.db.has_column("User", "custom_incentive_scale"):
		return
	users = frappe.get_all("User", filters={"enabled": 1, "user_type": "System User"},
		fields=["name", "first_name", "custom_incentive_scale"])
	by_first = {}
	for u in users:
		by_first.setdefault((u.first_name or "").strip().lower(), []).append(u)
	for first, scale in SHEET_PEOPLE.items():
		match = by_first.get(first) or []
		if len(match) == 1 and not match[0].custom_incentive_scale and frappe.db.exists("IB Incentive Scale", scale):
			frappe.db.set_value("User", match[0].name, "custom_incentive_scale", scale, update_modified=False)
