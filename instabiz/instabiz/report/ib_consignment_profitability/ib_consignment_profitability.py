"""IB Consignment Profitability — each container (IB Container Import) as a consignment.

Cost: landed cost of each line (invoice × exchange rate + share of duty, freight,
clearing). Where the goods went:
  processed — production runs that loaded a batch from this container (source qty);
              their revenue is the finished goods produced × that item's average
              selling rate (marked "estimated", since finished rolls from several
              jumbos are sold together)
  sold as is — Delivery Notes of the same item from the import date, matched to
              containers first-in-first-out (older container first)
  left       — what is not yet processed or sold, valued at landed cost
Profit = revenue − landed cost of what was processed or sold. The planned figures
come from the selling price entered on the container.
"""
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, getdate


def execute(filters=None):
	f = frappe._dict(filters or {})
	cond = {"docstatus": 1}
	if f.container:
		cond["name"] = f.container
	if f.supplier:
		cond["supplier"] = f.supplier
	if f.from_date and f.to_date:
		cond["import_date"] = ["between", [f.from_date, f.to_date]]
	all_ci = frappe.get_all("IB Container Import", filters={"docstatus": 1}, fields=["name", "container_no", "supplier", "import_date",
		"warehouse", "currency", "exchange_rate"], order_by="import_date asc, name asc")
	wanted = set(frappe.get_all("IB Container Import", filters=cond, pluck="name"))
	if not all_ci:
		return _cols(f), [], _("No submitted container imports yet."), None, None

	lines = frappe.get_all("IB Container Import Item", filters={"parent": ["in", [c.name for c in all_ci]]},
		fields=["parent", "idx", "item_code", "item_name", "stock_uom", "total_qty", "rate", "landed_rate", "landed_amount", "selling_rate"])
	ci_by = {c.name: c for c in all_ci}
	# processed: runs that loaded a batch of this container line
	runs = frappe.db.sql("""SELECT b.name AS batch, b.container_import, b.item, wo.name AS run, wo.status, wo.source_qty
		FROM `tabIB Batch` b JOIN `tabIB Work Order` wo ON wo.source_batch = b.name
		WHERE b.container_import IS NOT NULL AND wo.status != 'Cancelled'""", as_dict=True)
	processed = defaultdict(float)
	run_names = defaultdict(list)
	for r in runs:
		processed[(r.container_import, r.item)] += flt(r.source_qty)
		if r.status == "Completed":
			run_names[(r.container_import, r.item)].append(r.run)
	# revenue from production (estimated)
	avg_rate = _avg_selling_rates()
	prod_rev = defaultdict(float)
	for key, names in run_names.items():
		for o in frappe.get_all("IB WO Output", filters={"parent": ["in", names]}, fields=["item_code", "produced_qty", "uom"]):
			prod_rev[key] += _stock_qty(o.item_code, o.produced_qty, o.uom) * avg_rate.get(o.item_code, 0)

	# sold as is: FIFO of Delivery Note lines of the same item across containers
	rows = []
	for ln in lines:
		ci = ci_by[ln.parent]
		key = (ln.parent, ln.item_code)
		landed_rate = flt(ln.landed_rate) or flt(ln.rate)
		rows.append(frappe._dict(container=ln.parent, container_no=ci.container_no, supplier=ci.supplier, import_date=ci.import_date,
			item_code=ln.item_code, item_name=ln.item_name, uom=ln.stock_uom, qty_in=flt(ln.total_qty), landed_rate=landed_rate,
			landed_cost=flt(ln.landed_amount) or landed_rate * flt(ln.total_qty), selling_rate=flt(ln.selling_rate),
			qty_processed=min(processed.get(key, 0), flt(ln.total_qty)), prod_revenue=prod_rev.get(key, 0), qty_sold=0, sale_revenue=0))
		processed[key] = max(processed.get(key, 0) - flt(ln.total_qty), 0)  # spread over several lines of the same item
	_allocate_sales(rows)

	for r in rows:
		r.qty_left = max(r.qty_in - r.qty_processed - r.qty_sold, 0)
		r.cost_used = (r.qty_processed + r.qty_sold) * r.landed_rate
		r.revenue = r.sale_revenue + r.prod_revenue
		r.profit = r.revenue - r.cost_used
		r.margin_pct = round(r.profit / r.revenue * 100, 1) if r.revenue else None
		r.left_value = r.qty_left * r.landed_rate
		r.planned_value = r.selling_rate * r.qty_in
		r.planned_margin_pct = round((r.planned_value - r.landed_cost) / r.planned_value * 100, 1) if r.planned_value else None
		r.used_pct = round((r.qty_processed + r.qty_sold) / r.qty_in * 100, 1) if r.qty_in else 0
	rows = [r for r in rows if r.container in wanted]
	if f.item_code:
		rows = [r for r in rows if r.item_code == f.item_code]

	if (f.view or "Container") == "Container":
		agg = {}
		for r in rows:
			a = agg.setdefault(r.container, frappe._dict(container=r.container, container_no=r.container_no, supplier=r.supplier,
				import_date=r.import_date, lines=0, landed_cost=0, planned_value=0, cost_used=0, sale_revenue=0, prod_revenue=0,
				revenue=0, profit=0, left_value=0, qty_in=0, qty_used=0))
			a.lines += 1
			for k in ("landed_cost", "planned_value", "cost_used", "sale_revenue", "prod_revenue", "revenue", "profit", "left_value", "qty_in"):
				a[k] += flt(r[k])
			a.qty_used += r.qty_processed + r.qty_sold
		data = list(agg.values())
		for a in data:
			a.margin_pct = round(a.profit / a.revenue * 100, 1) if a.revenue else None
			a.planned_margin_pct = round((a.planned_value - a.landed_cost) / a.planned_value * 100, 1) if a.planned_value else None
			a.used_pct = round(a.qty_used / a.qty_in * 100, 1) if a.qty_in else 0
		data.sort(key=lambda a: getdate(a.import_date), reverse=True)
	else:
		data = rows
	chart = {"data": {"labels": [d.container_no or d.container for d in data[:12]], "datasets": [
		{"name": _("Landed cost used"), "values": [round(d.cost_used) for d in data[:12]]},
		{"name": _("Revenue"), "values": [round(d.revenue) for d in data[:12]]}]}, "type": "bar", "fieldtype": "Currency",
		"colors": ["#94a3b8", "#d97757"]} if data and (f.view or "Container") == "Container" else None
	rev, prof = sum(d.revenue for d in data), sum(d.profit for d in data)
	summary = [
		{"label": _("Landed cost"), "value": sum(d.landed_cost for d in data), "datatype": "Currency"},
		{"label": _("Revenue so far"), "value": rev, "datatype": "Currency"},
		{"label": _("Profit so far"), "value": prof, "datatype": "Currency", "indicator": "green" if prof >= 0 else "red"},
		{"label": _("Margin"), "value": round(prof / rev * 100, 1) if rev else 0, "datatype": "Percent"},
		{"label": _("Stock left (at cost)"), "value": sum(d.left_value for d in data), "datatype": "Currency"},
	]
	return _cols(f), data, None, chart, summary


def _allocate_sales(rows):
	by_item = defaultdict(list)
	for r in rows:
		by_item[r.item_code].append(r)
	for item, pool in by_item.items():
		pool.sort(key=lambda r: (getdate(r.import_date), r.container))
		sales = frappe.db.sql("""SELECT dn.posting_date, dni.stock_qty, dni.base_net_amount FROM `tabDelivery Note Item` dni
			JOIN `tabDelivery Note` dn ON dn.name = dni.parent
			WHERE dn.docstatus = 1 AND dn.is_return = 0 AND dni.item_code = %s AND dn.posting_date >= %s
			ORDER BY dn.posting_date, dn.name""", (item, pool[0].import_date), as_dict=True)
		for s in sales:
			left, rate = flt(s.stock_qty), (flt(s.base_net_amount) / flt(s.stock_qty) if flt(s.stock_qty) else 0)
			for r in pool:
				if left <= 0:
					break
				if getdate(r.import_date) > getdate(s.posting_date):
					continue
				room = r.qty_in - r.qty_processed - r.qty_sold
				if room <= 0:
					continue
				take = min(room, left)
				r.qty_sold += take
				r.sale_revenue += take * rate
				left -= take


def _avg_selling_rates():
	return {r.item_code: flt(r.rate) for r in frappe.db.sql("""SELECT dni.item_code, SUM(dni.base_net_amount) / NULLIF(SUM(dni.stock_qty), 0) AS rate
		FROM `tabDelivery Note Item` dni JOIN `tabDelivery Note` dn ON dn.name = dni.parent
		WHERE dn.docstatus = 1 AND dn.is_return = 0 GROUP BY dni.item_code""", as_dict=True)}


def _stock_qty(item_code, qty, uom):
	from instabiz.overrides.production_stock import _stock_qty as sq

	return sq(item_code, qty, uom)


def _cols(f):
	c = lambda label, fn, w=120: {"label": label, "fieldname": fn, "fieldtype": "Currency", "width": w}
	head = [{"label": _("Container"), "fieldname": "container", "fieldtype": "Link", "options": "IB Container Import", "width": 150},
		{"label": _("Container No"), "fieldname": "container_no", "fieldtype": "Data", "width": 120},
		{"label": _("Supplier"), "fieldname": "supplier", "fieldtype": "Link", "options": "Supplier", "width": 150},
		{"label": _("Imported"), "fieldname": "import_date", "fieldtype": "Date", "width": 95}]
	if (f.view or "Container") == "Container":
		return head + [{"label": _("Lines"), "fieldname": "lines", "fieldtype": "Int", "width": 60},
			c(_("Landed Cost"), "landed_cost"), c(_("Planned Sale Value"), "planned_value", 130),
			{"label": _("Planned Margin %"), "fieldname": "planned_margin_pct", "fieldtype": "Percent", "width": 110},
			{"label": _("Used %"), "fieldname": "used_pct", "fieldtype": "Percent", "width": 80},
			c(_("Cost of Used"), "cost_used"), c(_("Sold as is"), "sale_revenue"), c(_("From Production (est.)"), "prod_revenue", 140),
			c(_("Revenue"), "revenue"), c(_("Profit"), "profit"),
			{"label": _("Margin %"), "fieldname": "margin_pct", "fieldtype": "Percent", "width": 90}, c(_("Stock Left (cost)"), "left_value", 130)]
	return head + [{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 160},
		{"label": _("UOM"), "fieldname": "uom", "fieldtype": "Data", "width": 60},
		{"label": _("Qty In"), "fieldname": "qty_in", "fieldtype": "Float", "width": 90},
		c(_("Landed Rate"), "landed_rate", 100), c(_("Selling Price"), "selling_rate", 100),
		{"label": _("Planned Margin %"), "fieldname": "planned_margin_pct", "fieldtype": "Percent", "width": 110},
		{"label": _("Processed"), "fieldname": "qty_processed", "fieldtype": "Float", "width": 90},
		{"label": _("Sold as is"), "fieldname": "qty_sold", "fieldtype": "Float", "width": 90},
		{"label": _("Left"), "fieldname": "qty_left", "fieldtype": "Float", "width": 80},
		c(_("Revenue"), "revenue"), c(_("Profit"), "profit"),
		{"label": _("Margin %"), "fieldname": "margin_pct", "fieldtype": "Percent", "width": 90}]
