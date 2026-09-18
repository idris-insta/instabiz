"""IB Incentive Statement — the COMM ACC workbook, live.

Month view: one line per sales person — scale, sale, GST, unpaid, net sale, the
incentive earned in each slab band and the total (the monthly sheet).
Year view: net sale and incentive per month across the financial year (the
SALES sheet). Sales Users see only their own line.
"""
import frappe
from frappe import _
from frappe.utils import add_months, flt, getdate, today

from instabiz.overrides.incentive_scale import month_bounds, net_sales, scale_slabs, slab_breakup

SLABS = 5


def execute(filters=None):
	f = frappe._dict(filters or {})
	f.deduct_unpaid = bool(frappe.utils.cint(f.deduct_unpaid))
	user = _scope(f)
	if (f.view or "Month") == "Year":
		return _year(f, user)
	return _month(f, user)


def _scope(f):
	roles = set(frappe.get_roles())
	if roles & {"System Manager", "Sales Manager", "Accounts Manager", "Accounts User"}:
		return f.sales_person or None
	return frappe.session.user


def _people(sales, user):
	users = set(sales)
	scaled = frappe.get_all("User", filters={"enabled": 1, "custom_incentive_scale": ["is", "set"]}, pluck="name")
	users |= set(scaled)
	if user:
		users = {user}
	info = {u.name: u for u in frappe.get_all("User", filters={"name": ["in", list(users) or [""]]},
		fields=["name", "full_name", "custom_incentive_scale"])}
	return [info[u] for u in users if u in info]


def _month(f, user):
	start, end = month_bounds(f.month or today())
	sales = net_sales(start, end, user, f.deduct_unpaid)
	slab_cache, data = {}, []
	for u in _people(sales, user):
		s = sales.get(u.name) or frappe._dict(gross=0, gst=0, unpaid=0, net=0, docs=0)
		scale = u.custom_incentive_scale
		if scale not in slab_cache:
			slab_cache[scale] = scale_slabs(scale)
		breakup = slab_breakup(s.net, slab_cache[scale])
		row = frappe._dict(sales_person=u.name, person=u.full_name, scale=scale or _("Not set"), docs=s.docs,
			gross=s.gross, gst=s.gst, unpaid=s.unpaid, net=s.net, incentive=sum(b[5] for b in breakup))
		for i, b in enumerate(breakup[:SLABS], 1):
			row[f"slab_{i}"] = b[5]
			row[f"slab_{i}_base"] = b[4]
		data.append(row)
	data.sort(key=lambda r: -r.net)
	total = frappe._dict(person="<b>" + _("Total") + "</b>", bold=1)
	for k in ["docs", "gross", "gst", "unpaid", "net", "incentive"] + [f"slab_{i}" for i in range(1, SLABS + 1)]:
		total[k] = sum(flt(r.get(k)) for r in data)
	if data:
		data.append(total)
	cols = [
		{"label": _("Sales Person"), "fieldname": "person", "fieldtype": "Data", "width": 160},
		{"label": _("Scale"), "fieldname": "scale", "fieldtype": "Data", "width": 140},
		{"label": _("Orders"), "fieldname": "docs", "fieldtype": "Int", "width": 70},
		_cur(_("Sale (with GST)"), "gross"), _cur(_("GST"), "gst", 110),
		_cur(_("Unpaid"), "unpaid", 110), _cur(_("Net Sale"), "net"),
	]
	band_labels = _band_labels(slab_cache)
	for i in range(1, SLABS + 1):
		cols.append(_cur(band_labels.get(i, _("Slab {0}").format(i)), f"slab_{i}", 115))
	cols.append(_cur(_("Incentive"), "incentive", 120))
	chart = {"data": {"labels": [r.person for r in data if not r.bold][:15],
		"datasets": [{"name": _("Incentive"), "values": [round(r.incentive) for r in data if not r.bold][:15]}]},
		"type": "bar", "fieldtype": "Currency", "colors": ["#d97757"]} if data else None
	summary = [
		{"label": _("Net Sale"), "value": total.net if data else 0, "datatype": "Currency"},
		{"label": _("Total Incentive"), "value": total.incentive if data else 0, "datatype": "Currency", "indicator": "green"},
		{"label": _("People"), "value": len(data) - 1 if data else 0, "datatype": "Int"},
	]
	return cols, data, None, chart, summary


def _band_labels(slab_cache):
	"""Show the band edges in the header when everyone is on the same scale."""
	scales = {k for k in slab_cache if k}
	if len(scales) != 1:
		return {}
	out = {}
	for i, s in enumerate(slab_cache[next(iter(scales))][:SLABS], 1):
		hi = _("& above") if not flt(s.to_amount) else frappe.utils.fmt_money(s.to_amount, 0)
		out[i] = f"{flt(s.rate_pct):g}% ({frappe.utils.fmt_money(s.from_amount, 0)} – {hi})"
	return out


def _year(f, user):
	from erpnext.accounts.utils import get_fiscal_year
	fy = get_fiscal_year(getdate(f.month or today()), as_dict=True)
	months, d = [], getdate(fy.year_start_date)
	while d <= getdate(fy.year_end_date):
		months.append(d)
		d = add_months(d, 1)
	people, rows = {}, {}
	slab_cache = {}
	for m in months:
		start, end = month_bounds(m)
		sales = net_sales(start, end, user, f.deduct_unpaid)
		for u in _people(sales, user):
			people[u.name] = u
			s = sales.get(u.name)
			if not s:
				continue
			scale = u.custom_incentive_scale
			if scale not in slab_cache:
				slab_cache[scale] = scale_slabs(scale)
			inc = sum(b[5] for b in slab_breakup(s.net, slab_cache[scale]))
			r = rows.setdefault(u.name, frappe._dict(person=u.full_name, scale=scale or _("Not set"), net_total=0, inc_total=0))
			key = m.strftime("%b").lower()
			r[f"net_{key}"] = s.net
			r[f"inc_{key}"] = inc
			r.net_total += s.net
			r.inc_total += inc
	cols = [{"label": _("Sales Person"), "fieldname": "person", "fieldtype": "Data", "width": 150},
		{"label": _("Scale"), "fieldname": "scale", "fieldtype": "Data", "width": 130}]
	for m in months:
		key = m.strftime("%b").lower()
		cols.append(_cur(m.strftime("%b") + " " + _("Net"), f"net_{key}", 110))
		cols.append(_cur(m.strftime("%b") + " " + _("Inc."), f"inc_{key}", 95))
	cols += [_cur(_("Net Sale (Year)"), "net_total", 130), _cur(_("Incentive (Year)"), "inc_total", 120)]
	data = sorted(rows.values(), key=lambda r: -r.net_total)
	return cols, data, None, None, [
		{"label": _("Year Net Sale"), "value": sum(r.net_total for r in data), "datatype": "Currency"},
		{"label": _("Year Incentive"), "value": sum(r.inc_total for r in data), "datatype": "Currency", "indicator": "green"},
	]


def _cur(label, fieldname, width=130):
	return {"label": label, "fieldname": fieldname, "fieldtype": "Currency", "width": width}
