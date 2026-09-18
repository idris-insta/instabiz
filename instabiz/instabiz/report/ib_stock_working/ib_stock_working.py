"""IB Stock Working — the F STOCK WORKING workbook, live from the stock ledger.

Summary (the MAIN sheet): per material — microns, colour, jumbo width × length,
SQM per jumbo roll, stock in SQM and stock in jumbo rolls.
Ledger (one material, the numbered sheets): every movement with date, challan,
party, width, length, qty/ctn, ctns, SQM in, SQM out and running stock.

Quantities are converted to SQM: stock UOM already in square metres is used
as is; anything else (rolls, nos) is multiplied by the item's width × length.
"""
import frappe
from frappe import _
from frappe.utils import flt, getdate, today

SQM_UOMS = {"sqm", "sqmt", "sq meter", "sq. meter", "square meter", "square metre", "sq mtr", "m2"}
DETAIL = {"Delivery Note": "Delivery Note Item", "Purchase Receipt": "Purchase Receipt Item",
	"Stock Entry": "Stock Entry Detail", "Sales Invoice": "Sales Invoice Item", "Purchase Invoice": "Purchase Invoice Item"}
PARTY = {"Delivery Note": "customer_name", "Sales Invoice": "customer_name", "Purchase Receipt": "supplier_name",
	"Purchase Invoice": "supplier_name"}


def execute(filters=None):
	f = frappe._dict(filters or {})
	if (f.view or "Summary") == "Ledger":
		if not f.item_code:
			frappe.msgprint(_("Pick a material to see its ledger."))
			return _ledger_columns(), []
		return _ledger(f)
	return _summary(f)


def _factor(item):
	"""SQM per stock unit."""
	if (item.stock_uom or "").strip().lower() in SQM_UOMS:
		return 1.0
	return flt(item.width_mm) / 1000 * flt(item.length_mtr)


def _roll_sqm(item):
	return flt(item.width_mm) / 1000 * flt(item.length_mtr)


def _items(f):
	cond, args = "i.disabled = 0 AND i.is_stock_item = 1 AND IFNULL(i.width_mm, 0) > 0 AND IFNULL(i.length_mtr, 0) > 0", {}
	if f.item_group:
		cond += " AND i.item_group = %(item_group)s"
		args["item_group"] = f.item_group
	if f.item_code:
		cond += " AND i.name = %(item_code)s"
		args["item_code"] = f.item_code
	return frappe.db.sql(f"""SELECT i.name, i.item_name, i.item_group, i.stock_uom, i.width_mm, i.length_mtr,
		i.custom_thickness AS microns, i.color FROM `tabItem` i WHERE {cond} ORDER BY i.item_group, i.item_name""",
		args, as_dict=True)


def _summary(f):
	items = _items(f)
	if not items:
		return _summary_columns(), []
	args = {"items": tuple(i.name for i in items)}
	wh = ""
	if f.warehouse:
		wh = " AND b.warehouse IN (SELECT name FROM `tabWarehouse` WHERE lft >= (SELECT lft FROM `tabWarehouse` WHERE name = %(wh)s) AND rgt <= (SELECT rgt FROM `tabWarehouse` WHERE name = %(wh)s))"
		args["wh"] = f.warehouse
	qty = dict(frappe.db.sql(f"SELECT b.item_code, SUM(b.actual_qty) FROM `tabBin` b WHERE b.item_code IN %(items)s {wh} GROUP BY b.item_code", args))
	data = []
	for i, it in enumerate(items, 1):
		stock_sqm = flt(qty.get(it.name)) * _factor(it)
		if f.hide_zero and abs(stock_sqm) < 0.001:
			continue
		roll = _roll_sqm(it)
		data.append(frappe._dict(sr=i, item_code=it.name, item_name=it.item_name, item_group=it.item_group,
			microns=it.microns, color=it.color, width_mm=it.width_mm, length_mtr=it.length_mtr, sqm_per_roll=roll,
			stock_qty=flt(qty.get(it.name)), stock_uom=it.stock_uom, stock_sqm=stock_sqm,
			stock_rolls=stock_sqm / roll if roll else 0))
	return _summary_columns(), data, None, None, [
		{"label": _("Materials"), "value": len(data), "datatype": "Int"},
		{"label": _("Stock (SQM)"), "value": sum(d.stock_sqm for d in data), "datatype": "Float"},
		{"label": _("Stock (jumbo rolls)"), "value": round(sum(d.stock_rolls for d in data), 2), "datatype": "Float"},
	]


def _summary_columns():
	return [
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 170},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 200},
		{"label": _("Microns"), "fieldname": "microns", "fieldtype": "Data", "width": 75},
		{"label": _("Color"), "fieldname": "color", "fieldtype": "Data", "width": 80},
		{"label": _("Width (MM)"), "fieldname": "width_mm", "fieldtype": "Float", "width": 90},
		{"label": _("Length (MTR)"), "fieldname": "length_mtr", "fieldtype": "Float", "width": 95},
		{"label": _("SQM / Roll"), "fieldname": "sqm_per_roll", "fieldtype": "Float", "precision": 2, "width": 95},
		{"label": _("Stock Qty"), "fieldname": "stock_qty", "fieldtype": "Float", "width": 95},
		{"label": _("UOM"), "fieldname": "stock_uom", "fieldtype": "Data", "width": 65},
		{"label": _("Stock (SQM)"), "fieldname": "stock_sqm", "fieldtype": "Float", "precision": 2, "width": 115},
		{"label": _("Stock in Rolls"), "fieldname": "stock_rolls", "fieldtype": "Float", "precision": 2, "width": 110},
	]


def _ledger_columns():
	flt_col = lambda label, fn, w=90, p=2: {"label": label, "fieldname": fn, "fieldtype": "Float", "precision": p, "width": w}
	return [
		{"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 90},
		{"label": _("Voucher Type"), "fieldname": "voucher_type", "fieldtype": "Data", "width": 115},
		{"label": _("CH No / Voucher"), "fieldname": "voucher_no", "fieldtype": "Dynamic Link", "options": "voucher_type", "width": 150},
		{"label": _("Party"), "fieldname": "party", "fieldtype": "Data", "width": 180},
		{"label": _("Warehouse"), "fieldname": "warehouse", "fieldtype": "Link", "options": "Warehouse", "width": 140},
		flt_col(_("Width (MM)"), "width_mm", 85, 0), flt_col(_("Length (MTR)"), "length_mtr", 90, 0),
		flt_col(_("QTY/CTN"), "qty_pkg", 75, 0), flt_col(_("CTNS"), "total_pkg", 65, 0),
		flt_col(_("SQM In"), "sqm_in", 105), flt_col(_("SQM Out"), "sqm_out", 105),
		flt_col(_("Stock (SQM)"), "balance_sqm", 115), flt_col(_("Stock in Rolls"), "balance_rolls", 105),
	]


def _ledger(f):
	item = _items(frappe._dict(item_code=f.item_code))
	if not item:
		frappe.msgprint(_("This item has no width / length set, so SQM can't be worked out."))
		return _ledger_columns(), []
	item = item[0]
	factor, roll = _factor(item), _roll_sqm(item)
	start, end = getdate(f.from_date or "2000-01-01"), getdate(f.to_date or today())
	args = {"item": f.item_code, "from": start, "to": end}
	wh = ""
	if f.warehouse:
		wh = " AND warehouse IN (SELECT name FROM `tabWarehouse` WHERE lft >= (SELECT lft FROM `tabWarehouse` WHERE name = %(wh)s) AND rgt <= (SELECT rgt FROM `tabWarehouse` WHERE name = %(wh)s))"
		args["wh"] = f.warehouse
	opening = flt(frappe.db.sql(f"""SELECT SUM(actual_qty) FROM `tabStock Ledger Entry`
		WHERE is_cancelled = 0 AND item_code = %(item)s AND posting_date < %(from)s {wh}""", args)[0][0]) * factor
	sle = frappe.db.sql(f"""SELECT posting_date, voucher_type, voucher_no, voucher_detail_no, warehouse, actual_qty
		FROM `tabStock Ledger Entry` WHERE is_cancelled = 0 AND item_code = %(item)s
		  AND posting_date BETWEEN %(from)s AND %(to)s {wh}
		ORDER BY posting_date, posting_time, creation""", args, as_dict=True)
	dims = _detail_dims(sle)
	parties = _parties(sle)
	balance = opening
	data = [frappe._dict(party="<b>" + _("Opening Stock") + "</b>", balance_sqm=opening,
		balance_rolls=opening / roll if roll else 0, bold=1)]
	for r in sle:
		sqm = flt(r.actual_qty) * factor
		balance += sqm
		d = dims.get(r.voucher_detail_no) or {}
		data.append(frappe._dict(posting_date=r.posting_date, voucher_type=r.voucher_type, voucher_no=r.voucher_no,
			party=parties.get((r.voucher_type, r.voucher_no), ""), warehouse=r.warehouse,
			width_mm=d.get("width_mm"), length_mtr=d.get("length_mtr"), qty_pkg=d.get("qty_pkg"), total_pkg=d.get("total_pkg"),
			sqm_in=sqm if sqm > 0 else 0, sqm_out=-sqm if sqm < 0 else 0,
			balance_sqm=balance, balance_rolls=balance / roll if roll else 0))
	sqm_in = sum(flt(d.sqm_in) for d in data)
	sqm_out = sum(flt(d.sqm_out) for d in data)
	data.append(frappe._dict(party="<b>" + _("Closing Stock") + "</b>", sqm_in=sqm_in, sqm_out=sqm_out,
		balance_sqm=balance, balance_rolls=balance / roll if roll else 0, bold=1))
	return _ledger_columns(), data, None, None, [
		{"label": _("Jumbo"), "value": f"{flt(item.width_mm):g} mm × {flt(item.length_mtr):g} m = {roll:g} SQM", "datatype": "Data"},
		{"label": _("SQM In"), "value": sqm_in, "datatype": "Float"},
		{"label": _("SQM Out"), "value": sqm_out, "datatype": "Float"},
		{"label": _("Closing (SQM)"), "value": balance, "datatype": "Float"},
		{"label": _("Closing (rolls)"), "value": round(balance / roll, 2) if roll else 0, "datatype": "Float"},
	]


def _detail_dims(sle):
	out = {}
	for vtype, child in DETAIL.items():
		names = [r.voucher_detail_no for r in sle if r.voucher_type == vtype and r.voucher_detail_no]
		if not names:
			continue
		cols = [c for c in ("width_mm", "length_mtr", "qty_pkg", "total_pkg") if frappe.db.has_column(child, c)]
		if not cols:
			continue
		for row in frappe.db.sql(f"SELECT name, {', '.join(cols)} FROM `tab{child}` WHERE name IN %(n)s",
				{"n": tuple(names)}, as_dict=True):
			out[row.name] = row
	return out


def _parties(sle):
	out = {}
	for vtype, field in PARTY.items():
		names = list({r.voucher_no for r in sle if r.voucher_type == vtype})
		if names:
			for name, party in frappe.db.sql(f"SELECT name, {field} FROM `tab{vtype}` WHERE name IN %(n)s", {"n": tuple(names)}):
				out[(vtype, name)] = party
	names = list({r.voucher_no for r in sle if r.voucher_type == "Stock Entry"})
	if names:
		for name, purpose in frappe.db.sql("SELECT name, stock_entry_type FROM `tabStock Entry` WHERE name IN %(n)s", {"n": tuple(names)}):
			out[("Stock Entry", name)] = purpose
	return out
