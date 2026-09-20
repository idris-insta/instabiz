"""instabiz.instabiz.page.ib_stock_dashboard.ib_stock_dashboard"""
import frappe
from frappe.utils import cint, flt


WAREHOUSES = {
	"maharashtra": "MAHARASHTRA - IB",
	"chennai":     "CHENNAI - IB",
	"gujarat":     "GUJARAT - IB",
}


@frappe.whitelist()
def get_stock_data(item_group=None, uom=None, warehouse=None, hide_zero_stock=1, show_zero_only=0):
	# Real gap, fixed: no permission check at all — flagged once before (see
	# project history) as "plausibly intentional, low confidence" and left
	# alone, but its own sibling on this same merged page (get_ledger, the
	# Ledger tab) turned out to leak real cost/valuation + customer data with
	# the identical gap. Matches the page's own `roles` list exactly.
	frappe.only_for(["Sales Manager", "System Manager", "Stock User", "Stock Manager"])
	conditions = ["i.disabled = 0", "i.is_stock_item = 1"]
	values = {}

	if item_group:
		conditions.append("i.item_group = %(item_group)s")
		values["item_group"] = item_group

	if uom:
		conditions.append("i.stock_uom = %(uom)s")
		values["uom"] = uom

	where = " AND ".join(conditions)

	rows = frappe.db.sql(
		f"""
		SELECT
			i.item_name,
			i.item_code,
			i.item_group,
			i.stock_uom,
			i.width_mm,
			i.length_mtr,
			i.custom_thickness,
			i.color,
			i.custom_liner,
			i.custom_adhesive_type,
			COALESCE(mh.actual_qty,   0) AS maharashtra,
			COALESCE(mh.reserved_qty, 0) AS mh_reserved,
			COALESCE(cn.actual_qty,   0) AS chennai,
			COALESCE(cn.reserved_qty, 0) AS cn_reserved,
			COALESCE(gj.actual_qty,   0) AS gujarat,
			COALESCE(gj.reserved_qty, 0) AS gj_reserved,
			COALESCE(ir_mh.warehouse_reorder_level, 0) AS mh_reorder_level,
			COALESCE(ir_cn.warehouse_reorder_level, 0) AS cn_reorder_level,
			COALESCE(ir_gj.warehouse_reorder_level, 0) AS gj_reorder_level
		FROM tabItem i
		LEFT JOIN tabBin mh ON mh.item_code = i.item_code
			AND mh.warehouse = 'MAHARASHTRA - IB'
		LEFT JOIN tabBin cn ON cn.item_code = i.item_code
			AND cn.warehouse = 'CHENNAI - IB'
		LEFT JOIN (
			SELECT item_code, SUM(actual_qty) AS actual_qty, SUM(reserved_qty) AS reserved_qty
			FROM tabBin
			WHERE warehouse IN ('Ground Floor - GUJARAT - IB', 'First Floor - GUJARAT - IB', 'Second Floor - GUJARAT - IB')
			GROUP BY item_code
		) gj ON gj.item_code = i.item_code
		LEFT JOIN `tabItem Reorder` ir_mh
			ON ir_mh.parent = i.item_code AND ir_mh.warehouse = 'MAHARASHTRA - IB'
		LEFT JOIN `tabItem Reorder` ir_cn
			ON ir_cn.parent = i.item_code AND ir_cn.warehouse = 'CHENNAI - IB'
		LEFT JOIN `tabItem Reorder` ir_gj
			ON ir_gj.parent = i.item_code AND ir_gj.warehouse = 'GUJARAT - IB'
		WHERE {where}
		ORDER BY i.item_group, i.item_name
		""",
		values,
		as_dict=True,
	)

	data = []
	total_in_stock  = 0
	total_zero      = 0
	total_negative  = 0
	total_low_stock = 0

	for row in rows:
		mh  = flt(row.maharashtra)
		cn  = flt(row.chennai)
		gj  = flt(row.gujarat)
		res = flt(row.mh_reserved) + flt(row.cn_reserved) + flt(row.gj_reserved)

		mh_reorder    = flt(row.mh_reorder_level)
		cn_reorder    = flt(row.cn_reorder_level)
		gj_reorder    = flt(row.gj_reorder_level)

		if warehouse:
			wh_map = {
				"MAHARASHTRA - IB": (mh, flt(row.mh_reserved), mh_reorder),
				"CHENNAI - IB":     (cn, flt(row.cn_reserved), cn_reorder),
				"GUJARAT - IB":     (gj, flt(row.gj_reserved), gj_reorder),
			}
			wh_stock, wh_res, reorder_level = wh_map.get(warehouse, (0, 0, 0))
			total_stock     = wh_stock
			total_available = wh_stock - wh_res
		else:
			total_stock     = mh + cn + gj
			total_available = total_stock - res
			# Only meaningful as a combined figure when no single warehouse is
			# selected — matches total_stock/total_available also being combined
			# in this branch (see the warehouse-filtered branch above for the
			# per-warehouse case).
			reorder_level = mh_reorder + cn_reorder + gj_reorder

		if total_stock > 0:
			total_in_stock += 1
		else:
			total_zero += 1

		if total_available < 0:
			total_negative += 1

		low_stock = bool(reorder_level > 0 and 0 < total_stock <= reorder_level)
		if low_stock:
			total_low_stock += 1

		w = _fmt_dim(row.width_mm)
		l = _fmt_dim(row.length_mtr)

		data.append({
			"item_name":        row.item_name,
			"item_code":        row.item_code,
			"specification":    _build_spec(row),
			"spec_dimension":   f"{w}mm × {l}mtr" if (w and l) else "",
			"spec_sqmt":        _fmt_qty(flt(w) / 1000 * flt(l)) if (w and l) else "",
			"spec_width":       w or "",
			"spec_length":      l or "",
			"spec_thickness":   (row.custom_thickness or "").strip(),
			"spec_color":       (row.color or "").strip(),
			"spec_liner":       (row.custom_liner or "").strip(),
			"spec_adhesive":    (row.custom_adhesive_type or "").strip(),
			"uom":              row.stock_uom,
			"maharashtra":      _fmt_qty(mh),
			"chennai":          _fmt_qty(cn),
			"gujarat":          _fmt_qty(gj),
			"mh_reserved":      _fmt_qty(flt(row.mh_reserved)),
			"cn_reserved":      _fmt_qty(flt(row.cn_reserved)),
			"gj_reserved":      _fmt_qty(flt(row.gj_reserved)),
			"mh_reorder_level": _fmt_qty(mh_reorder),
			"cn_reorder_level": _fmt_qty(cn_reorder),
			"gj_reorder_level": _fmt_qty(gj_reorder),
			"total_stock":      _fmt_qty(total_stock),
			"total_available":  _fmt_qty(total_available),
			"reorder_level":    _fmt_qty(reorder_level),
			"low_stock":        low_stock,
		})

	return {
		"data": data,
		"summary": {
			"total":     len(rows),
			"in_stock":  total_in_stock,
			"zero":      total_zero,
			"negative":  total_negative,
			"low_stock": total_low_stock,
			"showing":   len(data),
		},
	}


# ── helpers ───────────────────────────────────────────────────────────────────

def _build_spec(row):
	uom = row.stock_uom or ""

	if uom == "SQMT":
		parts = []
		w = _fmt_dim(row.width_mm)
		l = _fmt_dim(row.length_mtr)
		if w and l:
			parts.append(f"{w}mm \u00d7 {l}mtr")
		if row.custom_thickness:
			parts.append(row.custom_thickness.strip())
		color = (row.color or "").strip()
		liner = (row.custom_liner or "").strip()
		if color and liner:
			parts.append(f"{color} with {liner}")
		elif color:
			parts.append(color)
		elif liner:
			parts.append(liner)
		return " | ".join(parts)

	if uom == "PCS":
		return (row.color or "").strip()

	if uom == "KG":
		return (row.custom_adhesive_type or "").strip()

	return ""


def _fmt_dim(val):
	"""Return dimension as int string if whole number, else float string."""
	if not val:
		return None
	f = flt(val)
	return str(int(f)) if f == int(f) else str(f)


def _fmt_qty(val):
	"""Strip unnecessary decimals from qty values."""
	f = flt(val)
	if f == 0:
		return 0
	return int(f) if f == int(f) else round(f, 2)
