"""feature/wo-per-run — Phase 1 migration: wipe the old per-(item x stage)
production model so the new "one Work Order = one run" model starts clean.

Runs ONCE (tracked in `tabPatch Log`). Pre-model-sync so the old rows are gone
before the IB Work Order schema is reshaped.

KEEPS: Sales Order, IB Container Import, IB Batch (kind='Raw Material'),
       IB Machine, IB Production Floor, Delivery Note / Stock Entry history.
WIPES: IB Work Order (+ new child tables), IB Order Sheet (+ items),
       IB FG Serial, IB Batch (kind='Finished Good'), IB Production Entry.
"""
import frappe


def _wipe(table, where=None):
	if not frappe.db.table_exists(table):
		return 0
	clause = f" WHERE {where}" if where else ""
	n = frappe.db.sql(f"SELECT COUNT(*) FROM `tab{table}`{clause}")[0][0]
	frappe.db.sql(f"DELETE FROM `tab{table}`{clause}")
	return n


def execute():
	counts = {}

	# genealogy first (children / leaf annotations)
	counts["IB FG Serial"] = _wipe("IB FG Serial")
	counts["IB Batch (FG)"] = _wipe("IB Batch", "kind = 'Finished Good'")

	# new run child tables (empty on first run — safety for reruns on a branch)
	for t in ("IB WO Stage Event", "IB WO Output", "IB WO Route Stage"):
		counts[t] = _wipe(t)

	# the runs themselves
	counts["IB Work Order"] = _wipe("IB Work Order")

	# dead doctype from the old model (0 rows expected)
	counts["IB Production Entry"] = _wipe("IB Production Entry")

	# order sheets + items
	counts["IB Order Sheet Item"] = _wipe("IB Order Sheet Item")
	counts["IB Order Sheet"] = _wipe("IB Order Sheet")

	frappe.db.commit()
	frappe.log_error(
		title="wo_per_run_reset",
		message="Production model reset (wo-per-run Phase 1):\n"
		+ "\n".join(f"  {k}: {v} deleted" for k, v in counts.items()),
	)
	print("[wo_per_run_reset] " + ", ".join(f"{k}={v}" for k, v in counts.items()))
