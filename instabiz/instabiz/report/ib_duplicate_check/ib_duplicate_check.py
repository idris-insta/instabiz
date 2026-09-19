"""IB Duplicate Check — purchase bills and payments that look entered twice
(same rules as the warning on save), for the chosen dates."""
import frappe
from frappe import _

from instabiz.overrides.duplicate_check import pe_matches, pi_matches


def execute(filters=None):
	f = frappe._dict(filters or {})
	data, seen = [], set()
	sources = [("Purchase Invoice", pi_matches, "supplier_name", "grand_total", "bill_no"),
		("Payment Entry", pe_matches, "party_name", "paid_amount", "reference_no")]
	for doctype, finder, party, amount, ref in sources:
		if f.doctype and f.doctype != doctype:
			continue
		for name in frappe.get_all(doctype, filters={"docstatus": ["!=", 2], "posting_date": ["between", [f.from_date, f.to_date]]},
				pluck="name", order_by="posting_date desc"):
			doc = frappe.get_doc(doctype, name)
			for other, why in finder(doc):
				key = (doctype, *sorted((name, other)))
				if key in seen:
					continue
				seen.add(key)
				o = frappe.db.get_value(doctype, other, ["posting_date", "docstatus"], as_dict=True)
				data.append({"doctype": doctype, "document": name, "date": doc.posting_date, "party": doc.get(party),
					"amount": doc.get(amount), "ref": doc.get(ref), "status": ["Draft", "Submitted"][doc.docstatus],
					"other": other, "other_date": o.posting_date, "other_status": ["Draft", "Submitted"][o.docstatus], "why": why})
	cols = [
		{"label": _("Type"), "fieldname": "doctype", "fieldtype": "Data", "width": 120},
		{"label": _("Document"), "fieldname": "document", "fieldtype": "Dynamic Link", "options": "doctype", "width": 170},
		{"label": _("Date"), "fieldname": "date", "fieldtype": "Date", "width": 95},
		{"label": _("Party"), "fieldname": "party", "fieldtype": "Data", "width": 190},
		{"label": _("Amount"), "fieldname": "amount", "fieldtype": "Currency", "width": 120},
		{"label": _("Bill / Ref No"), "fieldname": "ref", "fieldtype": "Data", "width": 120},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 85},
		{"label": _("Looks Like"), "fieldname": "other", "fieldtype": "Dynamic Link", "options": "doctype", "width": 170},
		{"label": _("Its Date"), "fieldname": "other_date", "fieldtype": "Date", "width": 95},
		{"label": _("Its Status"), "fieldname": "other_status", "fieldtype": "Data", "width": 85},
		{"label": _("Why"), "fieldname": "why", "fieldtype": "Data", "width": 200},
	]
	return cols, data, None, None, [{"label": _("Suspected pairs"), "value": len(data), "datatype": "Int",
		"indicator": "red" if data else "green"}]
