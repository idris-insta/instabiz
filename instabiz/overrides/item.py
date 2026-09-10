"""instabiz.overrides.item

Custom item search query + batch-tracking auto-enable for FG item groups.
"""
import frappe
from erpnext.controllers.queries import get_filters_cond, get_match_cond
from frappe.utils import cint, nowdate

# Finished-goods item groups that require batch tracking
_FG_BATCH_GROUPS = {"BOPP", "FOAM", "SPECIALTY"}


# Roll/sheet finished-good groups — used by production's FG-serial generation
# (instabiz.overrides.production._generate_fg_serials) to decide which items get
# an IB FG Serial per unit. NOT tied to native ERPNext has_serial_no (that was
# tried and reverted 2026-09-10 — it forces batch/serial selection on every
# outward stock movement and broke delivery for the whole existing catalogue).
_SERIAL_ITEM_GROUPS = (
	"PLASTIC", "FOAM", "FOAM - PE", "PAPER", "PVC", "CLOTH",
	"FOIL", "FOIL - ALUMINIUM", "REFLECTIVE",
)


def set_batch_no_for_fg(doc, method=None):
	"""No-op. Batch/serial genealogy uses the lightweight IB Batch / IB FG Serial
	annotation doctypes (see instabiz.overrides.traceability) — native ERPNext
	Batch/Serial tracking is deliberately NOT enabled on Items, because it makes
	batch/serial selection mandatory on every Delivery Note / outward movement
	and breaks dispatch of existing batch-null stock. Kept as a wired hook in
	case per-item native tracking is ever wanted for a specific SKU."""
	pass


def sync_barcode_field(doc, method=None):
	"""Mirror the first Item Barcode row into the read-only custom_barcode field
	so the barcode shows on the Details tab without opening Inventory."""
	doc.custom_barcode = doc.barcodes[0].barcode if doc.barcodes else ""


# ── Bulk barcode backfill ────────────────────────────────────────────────────
# The only place a SKU gets a barcode today is as a side effect of passing
# through IB Container Import (_resolve_barcode there). This backs a manual
# "Generate Missing Barcodes" button on the Item list (item_list.js) so the
# whole catalogue can be given a scannable Code128 barcode = its own item_code,
# which is what ib-stock-scan / Container Import already expect as the key.

def _item_has_barcode(item_code: str) -> bool:
	return bool(frappe.db.exists("Item Barcode", {"parent": item_code}))


def _set_item_barcode(item_code: str) -> None:
	item = frappe.get_doc("Item", item_code)
	item.append("barcodes", {"barcode": item_code, "barcode_type": "Code128"})
	item.save(ignore_permissions=True)


# Item groups that are internal-use only (packing consumables, service /
# placeholder items) — never sold as a standalone SKU, so no scannable
# barcode is wanted for them.
_INTERNAL_ITEM_GROUPS = ("PACKAGING",)


@frappe.whitelist()
def backfill_missing_barcodes(dry_run=1):
	"""Give every enabled, stock-tracked Item with no Item Barcode row a Code128
	barcode equal to its item_code. Skips internal-use groups and non-stock
	(service) items. dry_run=1 (default) only reports what would change."""
	frappe.only_for(["Stock Manager", "System Manager"])
	dry_run = cint(dry_run)

	candidates = frappe.get_all(
		"Item",
		filters={
			"disabled": 0,
			"has_variants": 0,
			"is_stock_item": 1,
			"item_group": ["not in", _INTERNAL_ITEM_GROUPS],
		},
		pluck="name",
		order_by="name asc",
	)
	pending = [code for code in candidates if not _item_has_barcode(code)]

	if dry_run:
		return {"dry_run": True, "count": len(pending), "sample": pending[:50]}

	created, failed = 0, []
	for code in pending:
		sp = f"ib_bc_{created}"
		frappe.db.savepoint(sp)
		try:
			_set_item_barcode(code)
			created += 1
		except Exception as e:
			frappe.db.rollback(save_point=sp)
			failed.append({"item": code, "error": str(e)})
		if created % 100 == 0:
			frappe.db.commit()
	frappe.db.commit()

	return {"dry_run": False, "created": created, "failed": failed, "failed_count": len(failed)}


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def item_query(doctype, txt, searchfield, start, page_len, filters, as_dict=False):
    doctype = "Item"
    conditions = []

    if isinstance(filters, str):
        import json
        filters = json.loads(filters)

    # Handle party-specific item rules (same as ERPNext)
    if filters and isinstance(filters, dict):
        if filters.get("customer") or filters.get("supplier"):
            scrub = frappe.scrub
            party = filters.get("customer") or filters.get("supplier")
            item_rules = frappe.get_all(
                "Party Specific Item",
                filters={"party": party},
                fields=["restrict_based_on", "based_on_value"],
            )
            filters_dict = {}
            for rule in item_rules:
                if rule["restrict_based_on"] == "Item":
                    rule["restrict_based_on"] = "name"
                filters_dict.setdefault(rule.restrict_based_on, []).append(rule.based_on_value)
            for f in filters_dict:
                filters[scrub(f)] = ["in", filters_dict[f]]
            filters.pop("customer", None)
            filters.pop("supplier", None)
        else:
            filters.pop("customer", None)
            filters.pop("supplier", None)

    page_len = min(int(page_len), 500)

    # ── Multi-token search ────────────────────────────────────────────────────
    # Split the search text into whitespace-separated tokens so that typing
    # "blue 1200" finds items containing both "blue" AND "1200" anywhere in
    # any of the searched fields — order of words doesn't matter.
    # Each token produces one AND block; a single token behaves like before.
    tokens = [t.strip() for t in txt.split() if t.strip()] or [""]

    token_sql_parts = []
    token_params    = {}
    for i, token in enumerate(tokens):
        key = f"tok{i}"
        token_params[key] = f"%{token}%" if token else "%"
        token_sql_parts.append(
            f"(tabItem.name            LIKE %({key})s"
            f" OR tabItem.item_name    LIKE %({key})s"
            f" OR tabItem.item_code    LIKE %({key})s"
            f" OR tabItem.item_group   LIKE %({key})s"
            f" OR tabItem.color        LIKE %({key})s"
            f" OR tabItem.custom_liner LIKE %({key})s"
            f" OR tabItem.name IN ("
            f"     SELECT parent FROM `tabItem Barcode` WHERE barcode LIKE %({key})s"
            f" ))"
        )

    search_condition = "\n            AND ".join(token_sql_parts)

    return frappe.db.sql(
        """
        SELECT
            tabItem.name,
            tabItem.item_name,
            CONCAT_WS(", ",
                NULLIF(TRIM(tabItem.color), ""),
                NULLIF(TRIM(tabItem.custom_liner), "")
            ) AS spec
        FROM `tabItem` tabItem
        WHERE
            tabItem.docstatus < 2
            AND tabItem.disabled = 0
            AND tabItem.has_variants = 0
            AND (
                tabItem.end_of_life > %(today)s
                OR IFNULL(tabItem.end_of_life, '0000-00-00') = '0000-00-00'
            )
            AND {search_condition}
            {fcond} {mcond}
        ORDER BY
            IF(LOCATE(%(_txt)s, tabItem.name),        LOCATE(%(_txt)s, tabItem.name),        99999),
            IF(LOCATE(%(_txt)s, tabItem.item_name),   LOCATE(%(_txt)s, tabItem.item_name),   99999),
            tabItem.idx DESC,
            tabItem.name,
            tabItem.item_name
        LIMIT %(start)s, %(page_len)s
        """.format(
            search_condition=search_condition,
            fcond=get_filters_cond(doctype, filters, conditions).replace("%", "%%"),
            mcond=get_match_cond(doctype).replace("%", "%%"),
        ),
        {
            "today":    nowdate(),
            "_txt":     txt.replace("%", ""),
            "start":    start,
            "page_len": page_len,
            **token_params,
        },
        as_dict=as_dict,
    )
