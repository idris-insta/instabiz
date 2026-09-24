"""IB Gate Pass â€” the security gate register.

Every vehicle / material going out or coming in gets a gate pass, usually made
from the Delivery Note, Purchase Receipt or Stock Entry it belongs to (items,
party, vehicle and LR copied over). Returnable, job-work and sample passes stay
Open until everything is back: security records returned quantities and the
status moves to Partly Returned / Returned. A daily run tells the stock team
about returnables past their expected date.
"""
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, nowdate, today

RETURNABLE = ("Returnable", "Job Work", "Sample")
LOCATION_OF = {"MAHARASHTRA": "maharashtra", "GUJARAT": "gujarat", "CHENNAI": "chennai"}


class IBGatePass(Document):
	def validate(self):
		if self.purpose in RETURNABLE and not self.expected_return_date:
			frappe.throw(_("Set Expected Back By for a {0} gate pass.").format(self.purpose))
		for row in self.items:
			if flt(row.returned_qty) > flt(row.qty):
				frappe.throw(_("Row {0}: returned qty is more than the qty sent.").format(row.idx))
		if self.party and not self.party_name and self.party_type in ("Customer", "Supplier", "Employee"):
			field = {"Customer": "customer_name", "Supplier": "supplier_name", "Employee": "employee_name"}[self.party_type]
			self.party_name = frappe.db.get_value(self.party_type, self.party, field)
		self.status = "Draft" if self.docstatus == 0 else self.status

	def on_submit(self):
		self.db_set("status", "Open" if self.purpose in RETURNABLE else "Closed")

	def on_cancel(self):
		self.db_set("status", "Cancelled")

	def on_update_after_submit(self):
		self._set_return_status()

	def _set_return_status(self):
		if self.purpose not in RETURNABLE:
			return
		sent = sum(flt(r.qty) for r in self.items)
		back = sum(flt(r.returned_qty) for r in self.items)
		status = "Returned" if back >= sent > 0 else ("Partly Returned" if back > 0 else "Open")
		self.db_set("status", status)
		self.db_set("returned_on", nowdate() if status == "Returned" else None)


@frappe.whitelist()
def record_return(gate_pass, returns):
	"""Security enters what came back: returns = [{row: name, qty: n}]."""
	doc = frappe.get_doc("IB Gate Pass", gate_pass)
	doc.check_permission("write")
	if doc.docstatus != 1:
		frappe.throw(_("Submit the gate pass first."))
	returns = frappe.parse_json(returns)
	by_row = {r.name: r for r in doc.items}
	for r in returns:
		row = by_row.get(r.get("row"))
		if row and flt(r.get("qty")):
			row.returned_qty = min(flt(row.qty), flt(row.returned_qty) + flt(r.get("qty")))
	doc.save()
	doc.add_comment("Info", _("Returned: {0}").format(", ".join(
		f"{by_row[r['row']].item_code or by_row[r['row']].description} {flt(r['qty']):g}" for r in returns if r.get("row") in by_row and flt(r.get("qty")))))
	return doc.status


@frappe.whitelist()
def make_from(doctype, name):
	"""Unsaved gate pass filled from a Delivery Note / Purchase Receipt / Stock Entry / Sales Invoice."""
	src = frappe.get_doc(doctype, name)
	src.check_permission("read")
	gp = frappe.new_doc("IB Gate Pass")
	gp.reference_doctype, gp.reference_name = doctype, name
	gp.posting_date = today()
	if doctype in ("Delivery Note", "Sales Invoice"):
		gp.gate_pass_type, gp.purpose, gp.party_type, gp.party = "Outward", "Delivery", "Customer", src.customer
		gp.party_name = src.customer_name
	elif doctype == "Purchase Receipt":
		gp.gate_pass_type, gp.purpose, gp.party_type, gp.party = "Inward", "Purchase Receipt", "Supplier", src.supplier
		gp.party_name = src.supplier_name
	elif doctype == "Stock Entry":
		receipt = src.stock_entry_type in ("Material Receipt",) or bool(src.get("outgoing_stock_entry"))
		gp.gate_pass_type = "Inward" if receipt else "Outward"
		gp.purpose = "Branch Transfer" if src.purpose == "Material Transfer" else ("Job Work" if src.purpose == "Send to Subcontractor" else "Other")
	loc = (src.get("custom_location") or "").upper()
	if not loc:
		wh = (src.get("set_warehouse") or src.get("from_warehouse") or src.get("to_warehouse")
			or (src.items[0].get("warehouse") or src.items[0].get("s_warehouse") or src.items[0].get("t_warehouse") if src.items else "") or "").upper()
		loc = next((k for k in LOCATION_OF if k in wh), "")
	gp.location = LOCATION_OF.get(loc, "gujarat")
	gp.vehicle_no = src.get("vehicle_no") or src.get("custom_vehicle_no") or ""
	gp.lr_no = src.get("custom_lr_number") or src.get("lr_no")
	gp.lr_date = src.get("lr_date")
	gp.transporter = src.get("custom_transport") or src.get("transport")
	for it in src.items:
		gp.append("items", {"item_code": it.item_code, "description": (it.get("item_name") or "")[:140],
			"qty": it.qty, "uom": it.get("uom") or it.get("stock_uom"), "packages": it.get("total_pkg") or None})
	return gp.as_dict()


@frappe.whitelist()
def auto_create_for_delivery_note(dn_name):
	"""Idempotent: create+submit Outward Gate Pass for a submitted Delivery Note. IB_DN_AUTO_GATE_PASS_V1"""
	frappe.get_doc("Delivery Note", dn_name).check_permission("read")
	existing = frappe.db.exists(
		"IB Gate Pass",
		{"reference_doctype": "Delivery Note", "reference_name": dn_name, "docstatus": ["<", 2]},
	)
	if existing:
		return existing
	data = make_from("Delivery Note", dn_name)
	gp = frappe.get_doc(data)
	if not gp.vehicle_no:
		pass  # todo52: do not invent TBD vehicle
	# System-generated on DN submit: the dispatch user who submits the DN does not
	# need submit rights on IB Gate Pass, and insert already bypasses permissions â€”
	# submitting under the caller's roles would fail and lose the gate pass.
	gp.flags.ignore_permissions = True
	gp.insert(ignore_permissions=True)
	gp.submit()
	return gp.name

def run_overdue_returnables():
	"""Daily: returnables past their date â†’ one bell per pass to stock managers (once)."""
	rows = frappe.get_all("IB Gate Pass", filters={"docstatus": 1, "status": ["in", ["Open", "Partly Returned"]],
		"purpose": ["in", RETURNABLE], "expected_return_date": ["<", today()]},
		fields=["name", "party_name", "expected_return_date", "purpose"])
	if not rows:
		return
	users = set(frappe.get_all("Has Role", filters={"role": ["in", ["Stock Manager", "Factory Management"]], "parenttype": "User"}, pluck="parent"))
	for r in rows:
		marker = f"[ib-gp-overdue-{r.name}]"
		if frappe.db.exists("Notification Log", {"document_name": r.name, "subject": ["like", f"%{marker}%"]}):
			continue
		days = (getdate(today()) - getdate(r.expected_return_date)).days
		for u in users - {"Administrator"}:
			if frappe.db.get_value("User", u, "enabled"):
				frappe.get_doc({"doctype": "Notification Log", "for_user": u, "type": "Alert",
					"subject": _("{0} not back: {1} ({2} days late) {3}").format(r.purpose, r.party_name or r.name, days, marker)[:140],
					"document_type": "IB Gate Pass", "document_name": r.name}).insert(ignore_permissions=True)
	frappe.db.commit()

@frappe.whitelist()
def auto_create_for_purchase_receipt(pr_name):
	"""Idempotent Inward Gate Pass for submitted Purchase Receipt."""
	from instabiz.overrides.purchase_rules import auto_inward_gate_pass_for_pr
	return auto_inward_gate_pass_for_pr(pr_name)