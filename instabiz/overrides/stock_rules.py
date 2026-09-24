"""instabiz.overrides.stock_rules

Locked Stock rules (Idris 2026-09-20), implemented 2026-09-21:

1. Negative stock allowed WITH warning (not hard-block).
2. Monthly physical stock recon: per-item due notifications to Stock Managers.
3. BWD <-> SGM branch moves: Material Transfer via branch_transfer + warn that a
   real branch/GST invoice must also be booked so stock and books align.
"""
from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_months, cint, flt, get_first_day, get_last_day, nowdate, today


def ensure_stock_lock_setup():
	# Allow negative stock at system level; we warn in validate hooks.
	ss = frappe.get_single("Stock Settings")
	changed = False
	if not cint(ss.allow_negative_stock):
		ss.allow_negative_stock = 1
		changed = True
	if changed:
		ss.save(ignore_permissions=True)
	_ensure_recon_fields()
	return {"allow_negative_stock": 1}


def _ensure_recon_fields():
	fields = [
		{
			"dt": "Item",
			"fieldname": "custom_last_stock_recon_date",
			"label": "Last Stock Recon Date",
			"fieldtype": "Date",
			"read_only": 1,
			"insert_after": "stock_uom",
		},
		{
			"dt": "Item",
			"fieldname": "custom_next_stock_recon_due",
			"label": "Next Stock Recon Due",
			"fieldtype": "Date",
			"insert_after": "custom_last_stock_recon_date",
		},
	]
	for f in fields:
		if frappe.db.exists("Custom Field", {"dt": f["dt"], "fieldname": f["fieldname"]}):
			continue
		try:
			if frappe.get_meta(f["dt"]).has_field(f["fieldname"]):
				continue
		except Exception:
			pass
		try:
			frappe.get_doc({"doctype": "Custom Field", **f}).insert(ignore_permissions=True)
		except Exception:
			frappe.log_error("IB stock recon fields", frappe.get_traceback())


def warn_if_negative_stock(doc, method=None):
	"""Soft warning when a transaction would leave bin qty below zero.

	allow_negative_stock is on company-wide, so nothing stops an outward move
	against an empty bin — this is the only signal anyone gets.
	"""
	# An invoice only touches stock when Update Stock is ticked; without it the
	# Delivery Note already moved the goods and warning again is just noise.
	if doc.doctype in ("Sales Invoice", "Purchase Invoice") and not cint(doc.get("update_stock")):
		return
	try:
		rows = []
		for row in doc.get("items") or []:
			item = row.get("item_code")
			wh = (
				row.get("warehouse")
				or row.get("s_warehouse")
				or row.get("from_warehouse")
				or doc.get("set_warehouse")
				or doc.get("from_warehouse")
			)
			if not item or not wh:
				continue
			# outbound qty
			qty = flt(row.get("stock_qty") or row.get("qty") or 0)
			if doc.doctype == "Stock Entry":
				# only source side consumes
				if not row.get("s_warehouse"):
					continue
				wh = row.s_warehouse
			elif doc.doctype in ("Delivery Note", "Sales Invoice"):
				pass
			elif doc.doctype == "Purchase Receipt" and cint(doc.get("is_return")):
				pass
			else:
				# receipts increase stock — skip
				if doc.doctype in ("Purchase Receipt",) and not cint(doc.get("is_return")):
					continue
			actual = flt(frappe.db.get_value("Bin", {"item_code": item, "warehouse": wh}, "actual_qty"))
			if actual - qty < -0.0001:
				rows.append(f"{item} @ {wh}: have {actual:g}, need {qty:g}")
		if rows:
			frappe.msgprint(
				_("Negative stock warning (allowed):<br>{0}").format("<br>".join(rows[:12])),
				indicator="orange",
				alert=True,
				title=_("Negative Stock"),
			)
	except Exception:
		frappe.log_error("IB negative stock warn", frappe.get_traceback())


def warn_branch_gst_invoice(doc, method=None):
	"""BWD <-> SGM Material Transfer: remind to book branch/GST invoice."""
	if doc.doctype != "Stock Entry":
		return
	if (doc.purpose or "") != "Material Transfer":
		return
	from_wh = doc.get("from_warehouse") or (doc.items[0].s_warehouse if doc.items else None)
	to_wh = doc.get("to_warehouse") or doc.get("custom_final_warehouse") or (
		doc.items[0].t_warehouse if doc.items else None
	)
	if not from_wh or not to_wh:
		return
	fl = _branch_of(from_wh)
	tl = _branch_of(to_wh)
	if fl and tl and fl != tl and {fl, tl} <= {"maharashtra", "gujarat"}:
		frappe.msgprint(
			_(
				"Inter-branch move <b>{0}</b> → <b>{1}</b>: also book a real branch / GST invoice "
				"so stock and accounts stay aligned (locked Stock rule)."
			).format(from_wh, to_wh),
			indicator="blue",
			alert=True,
			title=_("Branch Invoice Required"),
		)


def _branch_of(warehouse: str) -> str:
	w = (warehouse or "").upper()
	if "MAHARASHTRA" in w or "BWD" in w:
		return "maharashtra"
	if "GUJARAT" in w or "SGM" in w:
		return "gujarat"
	if "CHENNAI" in w:
		return "chennai"
	parent = frappe.db.get_value("Warehouse", warehouse, "parent_warehouse") or ""
	return _branch_of(parent) if parent else ""


def stamp_item_recon_from_sr(doc, method=None):
	"""On Stock Reconciliation submit, stamp last/next recon dates on items."""
	if doc.docstatus != 1:
		return
	next_due = add_months(get_first_day(doc.posting_date or today()), 1)
	for row in doc.get("items") or []:
		if not row.get("item_code"):
			continue
		if frappe.get_meta("Item").has_field("custom_last_stock_recon_date"):
			frappe.db.set_value(
				"Item",
				row.item_code,
				{
					"custom_last_stock_recon_date": doc.posting_date,
					"custom_next_stock_recon_due": next_due,
				},
				update_modified=False,
			)


def run_monthly_recon_due_notifies():
	"""Daily: notify Stock Managers of items whose next recon due date is today or past."""
	ensure_stock_lock_setup()
	if not frappe.get_meta("Item").has_field("custom_next_stock_recon_due"):
		return {"notified": 0}
	due = frappe.db.sql(
		"""
		SELECT name, item_name, custom_next_stock_recon_due
		FROM tabItem
		WHERE disabled = 0 AND is_stock_item = 1
		  AND custom_next_stock_recon_due IS NOT NULL
		  AND custom_next_stock_recon_due <= %s
		ORDER BY custom_next_stock_recon_due
		LIMIT 200
		""",
		today(),
		as_dict=True,
	)
	if not due:
		# seed next due for items that never had recon: end of month
		end = get_last_day(today())
		frappe.db.sql(
			"""
			UPDATE tabItem SET custom_next_stock_recon_due = %s
			WHERE disabled = 0 AND is_stock_item = 1
			  AND (custom_next_stock_recon_due IS NULL OR custom_next_stock_recon_due = '')
			""",
			end,
		)
		return {"seeded_due": end, "notified": 0}

	users = set(
		frappe.get_all(
			"Has Role",
			filters={"role": ["in", ["Stock Manager", "Stock User", "Factory Management"]], "parenttype": "User"},
			pluck="parent",
		)
	)
	n = 0
	for r in due:
		marker = f"[ib-stock-recon-due-{r.name}-{r.custom_next_stock_recon_due}]"
		if frappe.db.exists("Notification Log", {"subject": ["like", f"%{marker}%"]}):
			continue
		# Notification Log.subject is capped at 140 chars. The marker is what makes
		# this idempotent, so trim the item name to fit rather than the tail —
		# a truncated marker never matches and the alert repeats every single day.
		head = _("Stock recon due: ")
		tail = f" ({r.custom_next_stock_recon_due}) {marker}"
		room = 140 - len(head) - len(tail)
		label = (r.item_name or r.name)
		if room < 1:
			label = ""
		elif len(label) > room:
			label = label[: max(room - 1, 1)] + "…"
		subject = f"{head}{label}{tail}"[:140]
		for u in users - {"Administrator"}:
			if not frappe.db.get_value("User", u, "enabled"):
				continue
			frappe.get_doc(
				{
					"doctype": "Notification Log",
					"for_user": u,
					"type": "Alert",
					"subject": subject,
					"document_type": "Item",
					"document_name": r.name,
				}
			).insert(ignore_permissions=True)
			n += 1
	return {"notified": n, "items": len(due)}


def smoke_check():
	ensure_stock_lock_setup()
	ss = frappe.get_single("Stock Settings")
	return {
		"allow_negative_stock": cint(ss.allow_negative_stock),
		"recon_fields": frappe.get_meta("Item").has_field("custom_next_stock_recon_due"),
	}