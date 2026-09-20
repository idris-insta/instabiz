import frappe
from frappe.utils import today, add_days

_WH_SHORT = {
	"MAHARASHTRA - IB": "MH",
	"CHENNAI - IB":     "CN",
	"GUJARAT - IB":     "GJ",
	"Ground Floor - GUJARAT - IB": "GJ-G",
	"First Floor - GUJARAT - IB":  "GJ-1",
	"Second Floor - GUJARAT - IB": "GJ-2",
}

# voucher_type → (table, party_field)  None = no party
_PARTY_MAP = {
	"Delivery Note":      ("tabDelivery Note",      "customer"),
	"Sales Invoice":      ("tabSales Invoice",       "customer"),
	"Sales Order":        ("tabSales Order",         "customer"),
	"Purchase Receipt":   ("tabPurchase Receipt",    "supplier"),
	"Purchase Invoice":   ("tabPurchase Invoice",    "supplier"),
	"Purchase Order":     ("tabPurchase Order",      "supplier"),
}

# voucher_type → short label shown in badge
_VTYPE_SHORT = {
	"Delivery Note":        "DN",
	"Sales Invoice":        "SI",
	"Sales Order":          "SO",
	"Purchase Receipt":     "PR",
	"Purchase Invoice":     "PI",
	"Purchase Order":       "PO",
	"Stock Entry":          "SE",
	"Stock Reconciliation": "SR",
}


@frappe.whitelist()
def get_ledger(item_code=None, warehouse=None, from_date=None, to_date=None,
               voucher_type=None, customer=None, limit=50, offset=0):
	# Real gap, fixed: this had NO permission check at all — any authenticated
	# user could call it directly (bypassing the page's own role restriction,
	# which only gates the desk UI, not the RPC) and pull real cost/valuation
	# data (incoming_rate/outgoing_rate/stock_value) plus customer names off
	# every delivery, company-wide. Matches the page's own `roles` list
	# (ib_stock_dashboard.json) exactly — same audience, now actually enforced.
	frappe.only_for(["Sales Manager", "System Manager", "Stock User", "Stock Manager"])
	limit  = int(limit)
	offset = int(offset)

	if not from_date:
		from_date = add_days(today(), -30)
	if not to_date:
		to_date = today()

	conditions = ["sle.is_cancelled = 0", "sle.posting_date BETWEEN %(from_date)s AND %(to_date)s"]
	params = {"from_date": from_date, "to_date": to_date}

	if item_code:
		conditions.append("sle.item_code = %(item_code)s")
		params["item_code"] = item_code

	if warehouse:
		# GUJARAT - IB became a group warehouse 2026-08-13 (3 floor sub-warehouses
		# for inter-floor transfer tracking) — new Stock Ledger Entries post
		# against the floor leaf warehouses, not the group itself, so an exact
		# match here would silently return nothing for anyone filtering by it.
		if warehouse == "GUJARAT - IB":
			conditions.append("sle.warehouse IN %(warehouse_list)s")
			params["warehouse_list"] = ("Ground Floor - GUJARAT - IB", "First Floor - GUJARAT - IB", "Second Floor - GUJARAT - IB")
		else:
			conditions.append("sle.warehouse = %(warehouse)s")
			params["warehouse"] = warehouse

	if voucher_type:
		conditions.append("sle.voucher_type = %(voucher_type)s")
		params["voucher_type"] = voucher_type

	if customer:
		# Stock Ledger Entry has no direct customer field — resolve via the
		# voucher (Delivery Note / Sales Invoice / Sales Order all carry `customer`).
		# voucher_type is mutually exclusive per row, so at most one join matches
		# — no row fan-out.
		conditions.append("COALESCE(dn.customer, si.customer, so.customer) = %(customer)s")
		params["customer"] = customer

	where = " AND ".join(conditions)

	rows = frappe.db.sql(f"""
		SELECT
			sle.name,
			sle.posting_date,
			sle.posting_datetime,
			sle.item_code,
			i.item_name,
			i.stock_uom,
			i.width_mm,
			i.length_mtr,
			i.custom_thickness,
			i.color,
			i.custom_liner,
			i.custom_adhesive_type,
			sle.warehouse,
			sle.actual_qty,
			sle.qty_after_transaction,
			sle.incoming_rate,
			sle.outgoing_rate,
			sle.stock_value,
			sle.voucher_type,
			sle.voucher_no
		FROM `tabStock Ledger Entry` sle
		INNER JOIN `tabItem` i ON i.name = sle.item_code
		LEFT JOIN `tabDelivery Note` dn ON sle.voucher_type = 'Delivery Note' AND sle.voucher_no = dn.name
		LEFT JOIN `tabSales Invoice` si ON sle.voucher_type = 'Sales Invoice' AND sle.voucher_no = si.name
		LEFT JOIN `tabSales Order` so ON sle.voucher_type = 'Sales Order' AND sle.voucher_no = so.name
		WHERE {where}
		ORDER BY sle.posting_datetime DESC, sle.creation DESC
		LIMIT %(limit)s OFFSET %(offset)s
	""", {**params, "limit": limit, "offset": offset}, as_dict=True)

	summary = frappe.db.sql(f"""
		SELECT
			COUNT(*) AS total,
			COALESCE(SUM(CASE WHEN sle.actual_qty > 0 THEN  sle.actual_qty  ELSE 0 END), 0) AS qty_in,
			COALESCE(SUM(CASE WHEN sle.actual_qty < 0 THEN -sle.actual_qty  ELSE 0 END), 0) AS qty_out
		FROM `tabStock Ledger Entry` sle
		INNER JOIN `tabItem` i ON i.name = sle.item_code
		LEFT JOIN `tabDelivery Note` dn ON sle.voucher_type = 'Delivery Note' AND sle.voucher_no = dn.name
		LEFT JOIN `tabSales Invoice` si ON sle.voucher_type = 'Sales Invoice' AND sle.voucher_no = si.name
		LEFT JOIN `tabSales Order` so ON sle.voucher_type = 'Sales Order' AND sle.voucher_no = so.name
		WHERE {where}
	""", params, as_dict=True)[0]

	_resolve_parties(rows)
	_enrich(rows)

	return {"data": rows, "total": summary.total, "summary": summary}


def _resolve_parties(rows):
	"""Batch-fetch party names grouped by voucher_type — no N+1."""
	by_type = {}
	for r in rows:
		vt = r.get("voucher_type")
		if vt in _PARTY_MAP:
			by_type.setdefault(vt, []).append(r["voucher_no"])

	party_lookup = {}
	for vt, vouchers in by_type.items():
		table, field = _PARTY_MAP[vt]
		results = frappe.db.sql(
			f"SELECT name, `{field}` AS party FROM `{table}` WHERE name IN %(vouchers)s",
			{"vouchers": vouchers},
			as_dict=True,
		)
		for res in results:
			party_lookup[(vt, res["name"])] = res["party"]

	for r in rows:
		r["party"] = party_lookup.get((r.get("voucher_type"), r.get("voucher_no")), "")


def _enrich(rows):
	"""Add derived display fields."""
	for r in rows:
		r["wh_short"]    = _WH_SHORT.get(r.get("warehouse"), r.get("warehouse", ""))
		r["vtype_short"] = _VTYPE_SHORT.get(r.get("voucher_type"), r.get("voucher_type", ""))
		r["qty_in"]      = r["actual_qty"] if r["actual_qty"] > 0 else 0
		r["qty_out"]     = abs(r["actual_qty"]) if r["actual_qty"] < 0 else 0
		r["rate"]        = r["incoming_rate"] if r["actual_qty"] > 0 else (r["outgoing_rate"] if r["actual_qty"] < 0 else 0)
		dt = r.get("posting_datetime")
		r["posting_dt_str"] = dt.strftime("%d %b %Y %H:%M") if dt else str(r.get("posting_date", ""))
