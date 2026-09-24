# Copyright (c) 2026, Instabiz Solutions India Pvt Ltd and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, today


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [
		{"label": _("Document Type"), "fieldname": "document_type", "fieldtype": "Data", "width": 110},
		{"label": _("Document"), "fieldname": "parent", "fieldtype": "Dynamic Link", "options": "document_type", "width": 140},
		{"label": _("Date"), "fieldname": "transaction_date", "fieldtype": "Date", "width": 100},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 150},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 180},
		{"label": _("Line thickness"), "fieldname": "line_thickness", "fieldtype": "Data", "width": 110},
		{"label": _("Item thickness"), "fieldname": "item_thickness", "fieldtype": "Data", "width": 110},
		{"label": _("Line color"), "fieldname": "line_color", "fieldtype": "Data", "width": 100},
		{"label": _("Item color"), "fieldname": "item_color", "fieldtype": "Data", "width": 100},
		{"label": _("Mismatch"), "fieldname": "mismatch_fields", "fieldtype": "Data", "width": 140},
		{"label": _("Qty"), "fieldname": "qty", "fieldtype": "Float", "width": 80},
		{"label": _("Rate"), "fieldname": "rate", "fieldtype": "Currency", "width": 100},
		{"label": _("Price List"), "fieldname": "price_list", "fieldtype": "Data", "width": 120},
		{"label": _("Line width_mm"), "fieldname": "line_width_mm", "fieldtype": "Float", "width": 90},
		{"label": _("Line length_mtr"), "fieldname": "line_length_mtr", "fieldtype": "Float", "width": 100},
	]


def get_data(filters):
	from_date = getdate(filters.get("from_date") or add_days(today(), -90))
	to_date = getdate(filters.get("to_date") or today())
	only_submitted = 1 if filters.get("only_submitted") in (1, "1", True, "Yes") else 0
	doc_type = (filters.get("document_type") or "Both").strip()
	item_filter = (filters.get("item_code") or "").strip() or None
	mismatch_field = (filters.get("mismatch_field") or "Any").strip()
	company = (filters.get("company") or "").strip() or None

	parents = []
	if doc_type in ("Both", "Quotation"):
		parents.extend(_load_parents("Quotation", from_date, to_date, only_submitted, company))
	if doc_type in ("Both", "Sales Order"):
		parents.extend(_load_parents("Sales Order", from_date, to_date, only_submitted, company))

	if not parents:
		return []

	by_dt = {}
	for p in parents:
		by_dt.setdefault(p["doctype"], []).append(p)

	lines = []
	for doctype, plist in by_dt.items():
		child = "Quotation Item" if doctype == "Quotation" else "Sales Order Item"
		lines.extend(_load_lines(child, doctype, plist, item_filter))

	item_codes = sorted({r["item_code"] for r in lines if r.get("item_code")})
	masters = _load_items(item_codes)

	rows = []
	for line in lines:
		item = masters.get(line["item_code"]) or {}
		mismatches = _sku_mismatches(line, item, mismatch_field)
		if not mismatches:
			continue
		parent = line["_parent"]
		rows.append(
			{
				"document_type": parent["doctype"],
				"parent": parent["name"],
				"transaction_date": parent.get("transaction_date"),
				"status": parent.get("status"),
				"item_code": line.get("item_code"),
				"item_name": line.get("item_name") or item.get("item_name"),
				"line_thickness": _norm_str(line.get("custom_thickness")),
				"item_thickness": _norm_str(item.get("custom_thickness")),
				"line_color": _norm_str(line.get("color")),
				"item_color": _norm_str(item.get("color")),
				"mismatch_fields": ", ".join(mismatches),
				"qty": line.get("qty"),
				"rate": line.get("rate"),
				"price_list": parent.get("selling_price_list"),
				"line_width_mm": line.get("width_mm"),
				"line_length_mtr": line.get("length_mtr"),
			}
		)

	rows.sort(key=lambda r: (r.get("transaction_date") or "", r.get("document_type") or "", r.get("parent") or ""), reverse=True)
	return rows


def _load_parents(doctype, from_date, to_date, only_submitted, company):
	filters = [
		["transaction_date", ">=", from_date],
		["transaction_date", "<=", to_date],
	]
	if only_submitted:
		filters.append(["docstatus", "=", 1])
	if company:
		filters.append(["company", "=", company])

	fields = ["name", "transaction_date", "status", "selling_price_list", "company", "docstatus"]
	rows = frappe.get_all(doctype, filters=filters, fields=fields, order_by="transaction_date desc", limit_page_length=0)
	for r in rows:
		r["doctype"] = doctype
	return rows


def _load_lines(child_doctype, parenttype, parents, item_filter):
	"""Load child rows for parents already permission-filtered."""
	out = []
	chunk = 200
	parent_map = {p["name"]: p for p in parents}
	parent_names = list(parent_map.keys())
	fields = [
		"name",
		"parent",
		"parenttype",
		"item_code",
		"item_name",
		"qty",
		"rate",
		"custom_thickness",
		"width_mm",
		"length_mtr",
		"color",
	]

	for i in range(0, len(parent_names), chunk):
		batch = parent_names[i : i + chunk]
		filters = {"parent": ["in", batch], "parenttype": parenttype}
		if item_filter:
			filters["item_code"] = item_filter
		try:
			rows = frappe.get_all(child_doctype, filters=filters, fields=fields, limit_page_length=0)
		except frappe.PermissionError:
			# Child list blocked for some roles — read via SQL; parents already filtered
			placeholders = ", ".join(["%s"] * len(batch))
			sql = f"""
				select name, parent, parenttype, item_code, item_name, qty, rate,
					custom_thickness, width_mm, length_mtr, color
				from `tab{child_doctype}`
				where parent in ({placeholders}) and parenttype = %s
			"""
			args = list(batch) + [parenttype]
			if item_filter:
				sql += " and item_code = %s"
				args.append(item_filter)
			rows = frappe.db.sql(sql, args, as_dict=True)
		for r in rows:
			parent = parent_map.get(r["parent"])
			if not parent:
				continue
			r["_parent"] = parent
			out.append(r)
	return out


def _load_items(item_codes):
	if not item_codes:
		return {}
	out = {}
	chunk = 200
	for i in range(0, len(item_codes), chunk):
		batch = item_codes[i : i + chunk]
		for it in frappe.get_all(
			"Item",
			filters={"name": ["in", batch]},
			fields=["name", "item_name", "custom_thickness", "width_mm", "length_mtr", "color"],
			limit_page_length=0,
		):
			out[it["name"]] = it
	return out


def _sku_mismatches(line, item, mismatch_field):
	"""Only thickness + color. Never width/length. Liner is item_code suffix."""
	wanted = []
	mf = (mismatch_field or "Any").lower()
	if mf in ("any", "thickness"):
		wanted.append("custom_thickness")
	if mf in ("any", "color"):
		wanted.append("color")

	found = []
	for field in wanted:
		line_val = line.get(field)
		item_val = item.get(field)
		if not _is_set(line_val, field):
			continue
		if _values_differ(line_val, item_val, field):
			found.append(field)
	return found


def _is_set(val, field):
	if val is None:
		return False
	if field in ("width_mm", "length_mtr"):
		return False  # never used for SKU mismatch
	s = cstr_strip(val)
	return bool(s)


def _values_differ(line_val, item_val, field):
	a = cstr_strip(line_val).casefold()
	b = cstr_strip(item_val).casefold()
	return a != b


def cstr_strip(val):
	if val is None:
		return ""
	return str(val).strip()


def _norm_str(val):
	s = cstr_strip(val)
	return s or None
