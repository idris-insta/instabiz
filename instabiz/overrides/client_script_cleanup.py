"""instabiz.overrides.client_script_cleanup

Client Scripts are database records. Anything written in the UI lives only on
the site it was typed into — it is not in git, a fresh site never has it, and
the code that supersedes it cannot remove it.

Eleven of them had built up on the live site. Ten were later rewritten as real
app code without the original being retired, so both copies ran: the same
buttons appeared twice on IB Batch and IB Work Order, and the same handlers
fired twice on Delivery Note, Sales Invoice and IB Gate Pass.

Every one of them is now shipped in public/js (see the "Ported from" comments
there), so the database copies are switched off here — on this site, on dev and
on production, the next time each one migrates.

Disabled rather than deleted: the record and its history stay, so anything
missed is one tick away in the UI instead of gone.
"""
import frappe

# Client Script name -> the file that now carries it
SUPERSEDED = {
	"Todo52 Gate Locks — DN": "public/js/dn_gate_locks.js",
	"Todo52 Gate Locks — SI": "public/js/dn_gate_locks.js",
	"Todo52 Gate Locks — Gate Pass": "public/js/dn_gate_locks.js",
	"IB Batch — Todo36 Jumbo/Carton Serials": "public/js/ib_batch_mfg_serials.js",
	"IB Batch Coating Jumbo Label": "public/js/ib_batch_mfg_serials.js",
	"IB Work Order — Todo44/36 Undersize + Serials": "public/js/ib_work_order_mfg_plans.js",
	# Older, smaller script. Its three buttons are a subset of the todo44/36 one
	# above, which ib_work_order_mfg_plans.js ships in full.
	"IB Work Order — MFG Plans (todo38)": "public/js/ib_work_order_mfg_plans.js",
	"IB Transport Charges SI": "public/js/sales_invoice.js",
	"IB Supplier Buying Price List": "public/js/supplier.js",
	"IB PI Allocate Container": "public/js/ib_purchase_common.js",
	"IB PR Short Claim": "public/js/ib_purchase_common.js",
}


def after_migrate():
	# A name that matches nothing is almost always a typo in the list above, not
	# a script someone deleted — say so rather than silently doing nothing.
	live = {r.name for r in frappe.get_all("Client Script", fields=["name"])}
	for name in SUPERSEDED:
		if name not in live:
			frappe.logger().info(f"client_script_cleanup: no Client Script named {name!r}")

	for name, shipped_in in SUPERSEDED.items():
		if name not in live:
			continue
		if not frappe.db.get_value("Client Script", name, "enabled"):
			continue
		frappe.db.set_value("Client Script", name, "enabled", 0)
		frappe.db.set_value(
			"Client Script", name, "script",
			(frappe.db.get_value("Client Script", name, "script") or "")
			+ f"\n\n/* Superseded by {shipped_in} (instabiz app code). Disabled"
			  f" automatically on migrate — see overrides/client_script_cleanup.py. */",
		)
	frappe.clear_cache()


def status():
	"""What is still enabled, and where its replacement lives."""
	out = []
	for r in frappe.get_all("Client Script", fields=["name", "dt", "enabled"], order_by="dt"):
		out.append({
			"name": r.name,
			"doctype": r.dt,
			"enabled": r.enabled,
			"shipped_in": SUPERSEDED.get(r.name, "— not superseded, still database-only"),
		})
	return out
