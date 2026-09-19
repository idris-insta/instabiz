import frappe
from frappe.utils import flt
from erpnext.selling.doctype.customer.customer import Customer

from instabiz.overrides.billing_mode import is_dev_billing_mode, sales_doctype, sales_outstanding_expr
from instabiz.overrides.utils import territory_from_gstin as _utils_territory_from_gstin


def compute_customer_outstanding(customer):
	"""Sum outstanding for this customer — basis controlled by
	instabiz.overrides.billing_mode. Prod mode sums Sales Invoice
	outstanding_amount (ERPNext maintains this in real-time as Payment
	Entries are submitted/cancelled — authoritative single source of truth
	once billing is live). Dev mode sums Sales Order grand_total minus
	custom_advance_paid, since billing isn't live yet and every submitted
	Sales Invoice-based read was silently 0 for every customer, regardless
	of real order/advance activity (this was the actual root cause behind
	the Customer form always showing zero outstanding).

	Only 'Cancelled' is excluded, not 'Closed' — CustomSalesOrder.STATUS_MAP
	maps the DB status 'Closed' to the user-facing label 'Confirmed', i.e. a
	manually-closed order is still a real, legitimately-confirmed sale, not
	a voided one. Excluding it silently undercounted every such order.
	"""
	if is_dev_billing_mode():
		doctype = sales_doctype()
		outstanding_expr = sales_outstanding_expr("t")
		result = frappe.db.sql(
			f"SELECT COALESCE(SUM({outstanding_expr}), 0) FROM `tab{doctype}` t"
			" WHERE t.customer = %s AND t.docstatus = 1 AND t.status != 'Cancelled'",
			customer,
		)
	else:
		result = frappe.db.sql(
			"SELECT COALESCE(SUM(outstanding_amount), 0) FROM `tabSales Invoice`"
			" WHERE customer = %s AND docstatus = 1 AND outstanding_amount > 0",
			customer,
		)
	return flt(result[0][0] if result else 0)


def refresh_customer_outstanding(customer):
	"""Compute and persist custom_outstanding_amount to the Customer record."""
	value = compute_customer_outstanding(customer)
	frappe.db.set_value("Customer", customer, "custom_outstanding_amount", value)


def update_customer_outstanding_on_si(doc, method=None):
	"""doc_event handler: SI on_submit/on_cancel, and (dev mode only matters
	here since prod mode ignores Sales Order) SO on_submit/on_cancel — a
	Sales Order changes this customer's dev-mode outstanding just as much
	as an SI submit changes the prod-mode figure."""
	if doc.customer:
		refresh_customer_outstanding(doc.customer)


class CustomCustomer(Customer):
	def before_insert(self):
		# Auto-assign creating user as the Handled By sales person if not already set.
		# Skip for Administrator and system users who create customers on behalf of others.
		if (
			not self.get("custom_sales_person_user")
			and frappe.session.user not in ("Administrator", "Guest")
		):
			from instabiz.overrides.utils import set_sales_person
			set_sales_person(self)

	def validate(self):
		# Prevent the lead_name fetch (add_fetch in customer.js) from
		# overwriting customer_name on existing records.
		if not self.is_new():
			saved_name = frappe.db.get_value("Customer", self.name, "customer_name")
			if saved_name:
				self.customer_name = saved_name
		_sync_territory_from_billing_state(self)
		_sync_territory_from_gstin(self)  # GSTIN overrides billing state (more authoritative)
		super().validate()

	def onload(self):
		super().onload()
		_backfill_inline_fields(self)
		# Always show live outstanding on form load — no DB write needed here;
		# SI and PE events keep the persisted value current for list views.
		self.custom_outstanding_amount = compute_customer_outstanding(self.name)

	def after_save(self):
		try:
			_sync_addresses(self)
			_sync_contact(self)
		except Exception:
			frappe.log_error(title="IB Customer address sync failed", message=frappe.get_traceback())


# ── Backfill ──────────────────────────────────────────────────────────────────

def _backfill_inline_fields(doc):
	"""On load: populate inline custom address/contact fields from native linked docs if blank."""
	needs_billing = not doc.custom_billing
	needs_shipping = not doc.custom_shipping
	needs_contact = not doc.custom_contact_person_name

	if needs_billing or needs_shipping:
		linked_addrs = frappe.get_all(
			"Dynamic Link",
			filters={"link_doctype": "Customer", "link_name": doc.name, "parenttype": "Address"},
			fields=["parent"],
		)
		for row in linked_addrs:
			vals = frappe.db.get_value(
				"Address", row["parent"],
				["address_type", "address_line1", "city", "state", "pincode"],
			)
			if not vals:
				continue
			addr_type, line1, city, state, pincode = vals
			if needs_billing and addr_type == "Billing":
				doc.custom_billing = line1 or ""
				doc.custom_bt_city = city or ""
				doc.custom_bt_state = state or ""
				doc.custom_bt_pincode = pincode or ""
				needs_billing = False
			elif needs_shipping and addr_type == "Shipping":
				doc.custom_shipping = line1 or ""
				doc.custom_st_city = city or ""
				doc.custom_st_state = state or ""
				doc.custom_st_pincode = pincode or ""
				needs_shipping = False
			if not needs_billing and not needs_shipping:
				break

	if needs_contact:
		linked_contacts = frappe.get_all(
			"Dynamic Link",
			filters={"link_doctype": "Customer", "link_name": doc.name, "parenttype": "Contact"},
			fields=["parent"],
			limit=1,
		)
		if linked_contacts:
			try:
				contact = frappe.get_doc("Contact", linked_contacts[0]["parent"])
				doc.custom_contact_person_name = contact.first_name or ""
				for p in contact.phone_nos:
					if p.is_primary_mobile_no:
						doc.custom_primary_contact_person = p.phone
						break
				else:
					if contact.phone_nos:
						doc.custom_primary_contact_person = contact.phone_nos[0].phone
			except Exception:
				pass


# ── Sync: custom fields → native Address/Contact doctypes ─────────────────────

def _sync_addresses(doc):
	if not doc.custom_billing:
		return

	billing_name = _upsert_address(
		doc.name, doc.customer_name, "Billing",
		doc.custom_billing, doc.custom_bt_city, doc.custom_bt_state, doc.custom_bt_pincode,
	)
	frappe.db.set_value("Customer", doc.name, "customer_primary_address", billing_name)

	if doc.custom_bill_and_ship_to_same_address or not doc.custom_shipping:
		return

	_upsert_address(
		doc.name, doc.customer_name, "Shipping",
		doc.custom_shipping, doc.custom_st_city, doc.custom_st_state, doc.custom_st_pincode,
	)


def _upsert_address(customer_name, customer_display, addr_type, line1, city, state, pincode):
	"""Find or create an Address of addr_type linked to customer. Returns address name."""
	linked = frappe.get_all(
		"Dynamic Link",
		filters={"link_doctype": "Customer", "link_name": customer_name, "parenttype": "Address"},
		fields=["parent"],
	)
	existing_name = None
	for row in linked:
		t = frappe.db.get_value("Address", row["parent"], "address_type")
		if t == addr_type:
			existing_name = row["parent"]
			break

	if existing_name:
		addr = frappe.get_doc("Address", existing_name)
	else:
		addr = frappe.new_doc("Address")
		addr.address_title = f"{customer_display} - {addr_type}"
		addr.address_type = addr_type
		addr.country = "India"
		addr.append("links", {"link_doctype": "Customer", "link_name": customer_name})

	addr.address_line1 = line1 or ""
	addr.city = city or ""
	addr.state = state or ""
	addr.pincode = pincode or ""
	addr.flags.ignore_mandatory = True
	addr.save(ignore_permissions=True)
	return addr.name


def _sync_contact(doc):
	if not doc.custom_contact_person_name and not doc.custom_primary_contact_person:
		return

	linked = frappe.get_all(
		"Dynamic Link",
		filters={"link_doctype": "Customer", "link_name": doc.name, "parenttype": "Contact"},
		fields=["parent"],
		limit=1,
	)

	if linked:
		contact = frappe.get_doc("Contact", linked[0]["parent"])
	else:
		contact = frappe.new_doc("Contact")
		contact.append("links", {"link_doctype": "Customer", "link_name": doc.name})

	contact.first_name = doc.custom_contact_person_name or doc.customer_name
	contact.last_name = ""

	if doc.custom_primary_contact_person:
		contact.phone_nos = []
		contact.append("phone_nos", {
			"phone": doc.custom_primary_contact_person,
			"is_primary_mobile_no": 1,
		})

	contact.flags.ignore_mandatory = True
	contact.save(ignore_permissions=True)
	frappe.db.set_value("Customer", doc.name, "customer_primary_contact", contact.name)


# ── Territory sync from billing state ────────────────────────────────────────

# Handles common abbreviations and alternate spellings in billing state field
_STATE_ALIASES = {
	"tamilnadu": "Tamil Nadu",
	"tn": "Tamil Nadu",
	"mh": "Maharashtra",
	"gj": "Gujarat",
	"gujrat": "Gujarat",
	"wb": "West Bengal",
	"ap": "Andhra Pradesh",
	"ka": "Karnataka",
	"kl": "Kerala",
	"up": "Uttar Pradesh",
	"mp": "Madhya Pradesh",
	"rj": "Rajasthan",
	"hr": "Haryana",
	"pb": "Punjab",
	"ts": "Telangana",
	"od": "Odisha",
	"uk": "Uttarakhand",
	"hp": "Himachal Pradesh",
	"jh": "Jharkhand",
	"ga": "Goa",
	"dl": "Delhi",
	"dd": "Daman & Diu",
	"dn": "Dadra & Nagar",
	"dadra and nagar haveli and daman and diu": "Daman & Diu",
	"dadra & nagar haveli": "Dadra & Nagar",
}


def _sync_territory_from_billing_state(doc):
	"""Derive territory from billing state and set it on the Customer.

	Fires in validate() so territory is always consistent with billing address.
	Skips if billing state is blank. Falls back to alias map for common
	abbreviations/variations before giving up.
	"""
	state = (doc.custom_bt_state or "").strip()
	if not state:
		return

	# Exact match against Territory names (case-insensitive)
	territory = frappe.db.get_value("Territory", {"name": state})
	if not territory:
		# Try case-insensitive exact match via SQL
		rows = frappe.db.sql(
			"SELECT name FROM `tabTerritory` WHERE LOWER(name) = LOWER(%s) AND is_group = 0 LIMIT 1",
			state,
		)
		territory = rows[0][0] if rows else None

	if not territory:
		# Alias fallback
		canonical = _STATE_ALIASES.get(state.lower())
		if canonical:
			territory = frappe.db.get_value("Territory", canonical) or canonical

	if territory and territory != doc.territory:
		doc.territory = territory


# ── Territory sync from GSTIN state code ─────────────────────────────────────

# Maps GSTIN 2-digit state code → Territory name as it exists in this system.
# Codes without a matching Territory are absent from the dict (skip silently).
# Was a second, independently-hand-maintained copy of the GSTIN-state-code
# map (utils.py's GSTIN_STATE_MAP, used by lead.py/ib_transport.py) — the two
# had drifted: this copy had "04": "Delhi" (wrong; 04 is Chandigarh per the
# real CBIC state code list, and utils.py's copy already had it right),
# duplicate/colliding "04"/"07" both mapping to Delhi, differently-spelled
# state names for 25/26 that wouldn't match whichever spelling the real
# Territory record uses, and was missing 12 codes utils.py's copy had (J&K,
# Sikkim, Arunachal, Nagaland, Manipur, Mizoram, Tripura, Meghalaya,
# Lakshadweep, Puducherry, A&N Islands, Ladakh) — meaning Customers from
# those states never got GSTIN-based territory auto-derivation even though
# Leads (via the same GSTIN, through lead.py) would. Now reuses utils.py's
# single copy instead of maintaining a second one that can drift again.
def _territory_from_gstin(gstin):
	"""Return Territory name derived from GSTIN 2-digit state code, or None."""
	return _utils_territory_from_gstin(gstin)


def _sync_territory_from_gstin(doc):
	"""Set territory from GSTIN state code.

	Runs after _sync_territory_from_billing_state so GSTIN (government-issued,
	authoritative) can override a manually typed billing state that may be wrong.
	Only updates when GSTIN yields a territory that differs from current value.
	"""
	gstin = (doc.get("gstin") or "").strip()
	if not gstin:
		return
	territory = _territory_from_gstin(gstin)
	if not territory:
		return
	# Verify territory exists in this installation before setting
	if not frappe.db.exists("Territory", territory):
		return
	if territory != doc.territory:
		doc.territory = territory


@frappe.whitelist()
def backfill_territory_from_gstin():
	"""Bulk-fix: set territory from GSTIN 2-digit state code for all customers
	where the derived territory differs from current. Sales Manager / System Manager only."""
	from instabiz.overrides.permissions import _PRIVILEGED_ROLES
	if not (_PRIVILEGED_ROLES & set(frappe.get_roles())):
		frappe.throw(frappe._("Not permitted"), frappe.PermissionError)

	customers = frappe.db.sql(
		"SELECT name, territory, gstin FROM `tabCustomer`"
		" WHERE gstin IS NOT NULL AND gstin != ''",
		as_dict=True,
	)

	updated = []
	skipped_no_map = []
	skipped_no_territory = []

	for c in customers:
		territory = _territory_from_gstin(c.gstin)
		if not territory:
			skipped_no_map.append({"customer": c.name, "gstin": c.gstin})
			continue
		if not frappe.db.exists("Territory", territory):
			skipped_no_territory.append({"customer": c.name, "gstin": c.gstin, "territory": territory})
			continue
		if territory == c.territory:
			continue
		frappe.db.set_value("Customer", c.name, "territory", territory, update_modified=False)
		updated.append({"customer": c.name, "old": c.territory, "new": territory, "gstin": c.gstin})

	frappe.db.commit()
	return {
		"updated": len(updated),
		"skipped_no_map": len(skipped_no_map),
		"skipped_no_territory": len(skipped_no_territory),
		"details": updated,
	}


@frappe.whitelist()
def backfill_territory_from_billing_state():
	"""One-time or on-demand fix: set territory = billing state for all
	customers where they differ. Sales Manager / System Manager only."""
	from instabiz.overrides.permissions import _PRIVILEGED_ROLES
	if not (_PRIVILEGED_ROLES & set(frappe.get_roles())):
		frappe.throw(frappe._("Not permitted"), frappe.PermissionError)

	customers = frappe.db.sql(
		"""
		SELECT name, territory, custom_bt_state
		FROM `tabCustomer`
		WHERE custom_bt_state IS NOT NULL AND custom_bt_state != ''
		AND (territory IS NULL OR territory = ''
		     OR LOWER(territory) != LOWER(custom_bt_state))
		""",
		as_dict=True,
	)

	updated = []
	skipped = []
	for c in customers:
		state = (c.custom_bt_state or "").strip()
		territory = frappe.db.get_value("Territory", {"name": state})
		if not territory:
			rows = frappe.db.sql(
				"SELECT name FROM `tabTerritory` WHERE LOWER(name) = LOWER(%s) AND is_group = 0 LIMIT 1",
				state,
			)
			territory = rows[0][0] if rows else None
		if not territory:
			canonical = _STATE_ALIASES.get(state.lower())
			if canonical:
				territory = frappe.db.get_value("Territory", canonical) or None

		if territory:
			frappe.db.set_value("Customer", c.name, "territory", territory, update_modified=False)
			updated.append({"customer": c.name, "old": c.territory, "new": territory})
		else:
			skipped.append({"customer": c.name, "bt_state": c.custom_bt_state})

	frappe.db.commit()
	return {"updated": len(updated), "skipped": len(skipped), "details": updated, "unresolved": skipped}


# ── Whitelisted helpers ───────────────────────────────────────────────────────

@frappe.whitelist()
def get_outstanding(customer):
	# /portal: the logged-in customer downloading their own statement (checked in portal.download_pdf)
	if frappe.flags.get("ib_portal_customer") != customer and not frappe.has_permission("Customer", "read", customer):
		frappe.throw(frappe._("Not permitted"), frappe.PermissionError)
	return compute_customer_outstanding(customer)


@frappe.whitelist()
def get_outstanding_statement_rows(customer):
	"""Itemized outstanding rows for the IB Outstanding Statement print format —
	same basis as compute_customer_outstanding() (instabiz.overrides.billing_mode).
	Called from the print format's Jinja via frappe.call(), since frappe.conf
	isn't reachable from the sandboxed print-format Jinja context.

	Also resolves which of the company's 3 state GSTINs (Maharashtra/Gujarat/
	Chennai) belongs at the top of the statement — the print format previously
	always showed the Company master's single default `gstin` field, which is
	set to Maharashtra's, regardless of which location actually billed this
	customer. Each Sales Order/Sales Invoice already carries its own correct
	`company_gstin` (set per-location at creation — see quotation.py/
	sales_invoice.py); this reads it straight off the transactions actually
	being listed rather than re-deriving it from scratch. Most-recent
	transaction wins when a customer has outstanding dues billed from more
	than one location — falls back to the Company master's default gstin only
	when there are no outstanding rows at all (nothing to read a location off)."""
	if not frappe.has_permission("Customer", "read", customer):
		frappe.throw(frappe._("Not permitted"), frappe.PermissionError)

	dev_mode = is_dev_billing_mode()
	if dev_mode:
		doctype = sales_doctype()
		outstanding_expr = sales_outstanding_expr("t")
		rows = frappe.db.sql(
			f"SELECT t.name, t.transaction_date AS doc_date, COALESCE(NULLIF(t.custom_total_with_gst, 0), t.grand_total) AS grand_total,"
			f" t.company_gstin,"
			f" {outstanding_expr} AS balance"
			f" FROM `tab{doctype}` t"
			" WHERE t.customer = %s AND t.docstatus = 1 AND t.status != 'Cancelled'"
			f" AND {outstanding_expr} > 0"
			" ORDER BY t.transaction_date ASC",
			customer, as_dict=True,
		)
	else:
		rows = frappe.db.sql(
			"SELECT name, posting_date AS doc_date, grand_total, company_gstin,"
			" outstanding_amount AS balance"
			" FROM `tabSales Invoice`"
			" WHERE customer = %s AND docstatus = 1 AND outstanding_amount > 0"
			" ORDER BY posting_date ASC",
			customer, as_dict=True,
		)

	company_gstin = rows[-1].company_gstin if rows else None
	if not company_gstin:
		default_company = frappe.db.get_single_value("Global Defaults", "default_company")
		company_gstin = frappe.db.get_value("Company", default_company, "gstin") if default_company else None

	return {
		"dev_mode": dev_mode,
		"doc_label": frappe._("Order") if dev_mode else frappe._("Invoice"),
		"rows": rows,
		"total": flt(sum(flt(r.balance) for r in rows)),
		"company_gstin": company_gstin,
		"bank_account": _bank_account_for_gstin(company_gstin),
	}


# Maharashtra (27...) and Gujarat (24...) share one real HDFC account; Chennai
# (33...) has its own — same pairing as the "GUJARAT & MAHARASHTRA - HDFC" /
# "CHENNAI - HDFC" Bank Account masters (see CLAUDE.md item 74).
_GSTIN_PREFIX_BANK_ACCOUNT = {
	"27": "GUJARAT & MAHARASHTRA - HDFC",
	"24": "GUJARAT & MAHARASHTRA - HDFC",
	"33": "CHENNAI - HDFC",
}


def _bank_account_for_gstin(company_gstin):
	"""Remittance details for the Outstanding Statement footer — resolved from
	the same location the statement's own GSTIN was resolved for, not a single
	hardcoded default (a customer billed from Chennai should never be shown
	the Maharashtra/Gujarat account)."""
	bank_account_name = _GSTIN_PREFIX_BANK_ACCOUNT.get((company_gstin or "")[:2])
	if not bank_account_name:
		return None
	row = frappe.db.get_value(
		"Bank Account", bank_account_name,
		["bank", "bank_account_no", "branch_code"], as_dict=True,
	)
	if not row:
		return None
	# "GUJARAT & MAHARASHTRA - HDFC"'s branch_code field has a known data-entry
	# defect (a branch address string appended ahead of the real IFSC) — the
	# real IFSC (per CLAUDE.md item 74, matches CHENNAI - HDFC's own clean
	# value) is always the last "&"-separated segment. Not corrected in the
	# source record itself — corrected only for display here.
	ifsc = (row.branch_code or "").split("&")[-1].strip()
	return {"bank": row.bank, "account_no": row.bank_account_no, "ifsc": ifsc}


@frappe.whitelist()
def clear_overdue_block(customer):
	"""Manually lift the overdue block flag. Sales Manager / System Manager only."""
	from instabiz.overrides.permissions import _PRIVILEGED_ROLES
	if not (_PRIVILEGED_ROLES & set(frappe.get_roles())):
		frappe.throw(frappe._("Not permitted"), frappe.PermissionError)
	frappe.db.set_value("Customer", customer, "custom_overdue_block", 0, update_modified=False)
	actor = frappe.db.get_value("User", frappe.session.user, "full_name") or frappe.session.user
	frappe.get_doc({
		"doctype": "Comment",
		"comment_type": "Info",
		"reference_doctype": "Customer",
		"reference_name": customer,
		"content": f"Overdue block manually cleared by {actor}.",
		"owner": frappe.session.user,
	}).insert(ignore_permissions=True)
	return "ok"


@frappe.whitelist()
def log_customer_activity(customer, activity_type, outcome, notes):
	"""Log a call/meeting/WA/email/visit activity on a Customer timeline."""
	if not frappe.has_permission("Customer", "write", customer):
		frappe.throw(frappe._("Not permitted"), frappe.PermissionError)

	VALID_TYPES = {"Call", "Meeting", "WhatsApp", "Email", "Visit"}
	VALID_OUTCOMES = {"Interested", "Not Interested", "Follow Up", "No Response"}
	if activity_type not in VALID_TYPES:
		frappe.throw(frappe._("Invalid activity type"))
	if outcome not in VALID_OUTCOMES:
		frappe.throw(frappe._("Invalid outcome"))

	actor = frappe.db.get_value("User", frappe.session.user, "full_name") or frappe.session.user
	icon_map = {"Call": "📞", "Meeting": "🤝", "WhatsApp": "💬", "Email": "📧", "Visit": "📍"}

	parts = [f"{icon_map[activity_type]} <b>{activity_type}</b> — Outcome: <b>{outcome}</b>"]
	if notes:
		parts.append(frappe.utils.escape_html(notes).replace("\n", "<br>"))
	parts.append(f"<i>Logged by {actor}</i>")

	frappe.get_doc({
		"doctype": "Comment",
		"comment_type": "Info",
		"reference_doctype": "Customer",
		"reference_name": customer,
		"content": "<br>".join(parts),
		"owner": frappe.session.user,
	}).insert(ignore_permissions=True)

	return "ok"


@frappe.whitelist()
def get_customer_phones(customers):
	import json
	names = json.loads(customers)
	if not names:
		return {}
	# Row-level isolation: only return phones for customers the caller can
	# actually see (frappe.get_list applies Customer's own permission_query_conditions
	# hook, customer_query_conditions) — the raw SQL below has no permission
	# check of its own, so without this filter a non-privileged Sales User could
	# request phone numbers for any customer system-wide, not just their own.
	permitted = frappe.get_list("Customer", filters={"name": ["in", names]}, pluck="name")
	if not permitted:
		return {}
	rows = frappe.db.sql(
		"""
		SELECT dl.link_name AS customer, cp.phone
		FROM `tabContact Phone` cp
		JOIN `tabDynamic Link` dl ON dl.parent = cp.parent
		WHERE dl.link_doctype = 'Customer'
		  AND dl.link_name IN %(names)s
		ORDER BY cp.is_primary_mobile_no DESC, cp.idx ASC
		""",
		{"names": permitted},
		as_dict=True,
	)
	# Keep first phone per customer
	result = {}
	for r in rows:
		if r.customer not in result:
			result[r.customer] = (r.phone or "").strip()
	return result


@frappe.whitelist()
def get_customer_inactivity(customers):
	"""Days since each customer's last submitted Sales Order — same basis
	dormant.py/classify_customer() already use for "dormant" — for the
	Customer list view's row-highlight tiers (2026-09-03, user request).
	None (never ordered) is treated as maximally inactive by the caller."""
	import json
	names = json.loads(customers)
	if not names:
		return {}
	# Same row-level isolation as get_customer_phones above — raw SQL has no
	# permission check of its own.
	permitted = frappe.get_list("Customer", filters={"name": ["in", names]}, pluck="name")
	if not permitted:
		return {}
	rows = frappe.db.sql(
		"""
		SELECT customer, MAX(transaction_date) AS last_order_date
		FROM `tabSales Order`
		WHERE docstatus = 1 AND customer IN %(names)s
		GROUP BY customer
		""",
		{"names": permitted},
		as_dict=True,
	)
	last_order = {r.customer: r.last_order_date for r in rows}
	today = frappe.utils.today()
	result = {}
	for name in permitted:
		last_date = last_order.get(name)
		result[name] = frappe.utils.date_diff(today, last_date) if last_date else None
	return result
