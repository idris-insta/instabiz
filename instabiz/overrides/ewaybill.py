"""instabiz.overrides.ewaybill

Auto-generate e-Way Bill on Delivery Note submission via india_compliance.

Generation is enqueued as a background job so a failure never rolls back the DN submit.
"""
import frappe
from frappe import _


def _is_ewb_configured():
	try:
		from india_compliance.gst_india.utils import is_api_enabled  # pyright: ignore[reportMissingImports]
	except ImportError:
		return False
	settings = frappe.get_cached_doc("GST Settings")
	return is_api_enabled(settings) and settings.get("enable_e_waybill") and settings.get("enable_e_waybill_from_dn")


def _sync_transporter_fields(doc):
	if doc.get("custom_lr_number") and not doc.get("lr_no"):
		frappe.db.set_value("Delivery Note", doc.name, "lr_no", doc.custom_lr_number, update_modified=False)
		doc.lr_no = doc.custom_lr_number

	if doc.get("custom_transport") and not doc.get("gst_transporter_id"):
		gst_id = frappe.db.get_value("IB Transport", doc.custom_transport, "custom_transport_gst")
		if gst_id:
			frappe.db.set_value("Delivery Note", doc.name, "gst_transporter_id", gst_id, update_modified=False)
			doc.gst_transporter_id = gst_id


def _patch_ship_from(doc):
	"""
	Patch EWaybillData.set_party_address_details to overwrite ship_from with
	the physical warehouse address (address_line_1, city, pin) for the given doc.
	Returns the original method so the caller can restore it.
	"""
	from india_compliance.gst_india.utils.e_waybill import EWaybillData  # pyright: ignore[reportMissingImports]
	from instabiz.overrides.utils import LOCATION_WAREHOUSE

	loc = (doc.get("custom_location") or "").lower()
	wh_name = LOCATION_WAREHOUSE.get(loc)
	_orig = EWaybillData.set_party_address_details

	def _patched(self):
		_orig(self)
		if not wh_name:
			return
		wh = frappe.db.get_value(
			"Warehouse", wh_name, ["address_line_1", "city", "pin"], as_dict=True
		)
		if not wh:
			return
		if wh.address_line_1:
			self.ship_from.address_line1 = wh.address_line_1.replace("\n", " ").strip()
		if wh.city:
			self.ship_from.city = wh.city
		if wh.pin:
			self.ship_from.pincode = wh.pin

	EWaybillData.set_party_address_details = _patched
	return _orig


def _generate_ewaybill_async(doc_name):
	"""Background job — runs after DN is committed, so failures don't affect DN docstatus.

	Not whitelisted (matches the sibling pattern in einvoice.py's
	_generate_einvoice_background): this is only ever meant to be invoked via
	frappe.enqueue() from run_ewaybill_on_submit below, which already applies
	its own gating (self-pickup / not-configured / already-has-ewaybill
	checks). @frappe.whitelist() previously made this directly callable over
	/api/method by ANY authenticated user with an arbitrary doc_name and zero
	permission check — see custom_generate_e_waybill() for the same bug class.
	"""
	doc = frappe.get_doc("Delivery Note", doc_name)
	if doc.get("ewaybill"):
		return

	try:
		from india_compliance.gst_india.utils.e_waybill import (  # pyright: ignore[reportMissingImports]
			_generate_e_waybill,
		)
		_sync_transporter_fields(doc)
		_orig = _patch_ship_from(doc)
		try:
			_generate_e_waybill(doc, throw=False)
		finally:
			from india_compliance.gst_india.utils.e_waybill import EWaybillData  # pyright: ignore[reportMissingImports]
			EWaybillData.set_party_address_details = _orig
	except Exception:
		frappe.log_error(
			title=f"e-Way Bill auto-generation failed: {doc_name}",
			message=frappe.get_traceback(),
			reference_doctype="Delivery Note",
			reference_name=doc_name,
		)


def _fetch_coords(pincode):
	"""Return (lat, lon) for an Indian pincode via Nominatim, or (None, None)."""
	try:
		import requests as _req
		r = _req.get(
			"https://nominatim.openstreetmap.org/search",
			params={"postalcode": str(pincode), "countrycodes": "in", "format": "json", "limit": 1},
			headers={"User-Agent": "instabiz-erp/1.0", "Accept-Language": "en"},
			timeout=6,
		)
		data = r.json()
		if data:
			return float(data[0]["lat"]), float(data[0]["lon"])
	except Exception:
		pass
	return None, None


def _haversine_km(lat1, lon1, lat2, lon2):
	from math import atan2, cos, radians, sin, sqrt
	R = 6371
	dlat = radians(lat2 - lat1)
	dlon = radians(lon2 - lon1)
	a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
	return max(1, round(R * 2 * atan2(sqrt(a), sqrt(1 - a))))


def _compute_doc_distance(doc):
	"""Straight-line distance (km) between dispatch warehouse/company address and customer address."""
	from instabiz.overrides.utils import LOCATION_WAREHOUSE

	loc = (doc.get("custom_location") or "").lower()
	wh_name = LOCATION_WAREHOUSE.get(loc)

	src_pin = None
	if wh_name:
		src_pin = frappe.db.get_value("Warehouse", wh_name, "pin")
	if not src_pin and doc.get("company_address"):
		src_pin = frappe.db.get_value("Address", doc.company_address, "pincode")

	dst_addr = doc.get("shipping_address_name") or doc.get("customer_address")
	dst_pin = frappe.db.get_value("Address", dst_addr, "pincode") if dst_addr else None

	if not src_pin or not dst_pin:
		return None

	frappe.logger().info(f"[IB EWB] Distance lookup: {src_pin} → {dst_pin}")
	lat1, lon1 = _fetch_coords(src_pin)
	lat2, lon2 = _fetch_coords(dst_pin)

	if None in (lat1, lon1, lat2, lon2):
		frappe.logger().warning(f"[IB EWB] Could not geocode pincodes {src_pin}/{dst_pin}")
		return None

	return _haversine_km(lat1, lon1, lat2, lon2)


def _is_distance_error(exc_str):
	s = (exc_str or "").lower()
	if "distance" not in s:
		return False
	return any(
		kw in s
		for kw in (
			"greater", "less", "more than", "km", "pincode", "pin code", "between",
			"exceed", "acceptable", "too high", "too low", "not available",
		)
	)


def _addr_fields(address_name):
	"""Return address_line1, city, pincode from an Address doc, or None if not found."""
	if not address_name:
		return None
	return frappe.db.get_value(
		"Address", address_name, ["address_line1", "city", "pincode"], as_dict=True
	)


def _apply_addr(side, addr):
	"""Overwrite ship_from / ship_to / bill_from fields from an Address dict."""
	if not addr:
		return
	if addr.address_line1:
		side.address_line1 = addr.address_line1
	if addr.city:
		side.city = addr.city
	if addr.pincode:
		side.pincode = addr.pincode


@frappe.whitelist()
def custom_generate_e_waybill(
	doctype=None,
	docname=None,
	values=None,
	force=False,
	transaction_type=None,
	bill_from_address=None,
	dispatch_from_address=None,
	ship_to_address=None,
):
	from india_compliance.gst_india.utils.e_waybill import (  # pyright: ignore[reportMissingImports]
		EWaybillData,
		generate_e_waybill,
	)
	from instabiz.overrides.utils import LOCATION_WAREHOUSE

	frappe.logger().info(
		f"[IB EWB] custom_generate_e_waybill — txn_type={transaction_type!r} "
		f"bill_from={bill_from_address!r} dispatch={dispatch_from_address!r} ship_to={ship_to_address!r}"
	)

	doc = frappe.get_doc(doctype, docname)
	# This whitelisted endpoint overrides india_compliance's own generate_e_waybill
	# (see hooks.py override_whitelisted_methods), whose original implementation
	# goes through load_doc(doctype, docname, "submit") -> doc.check_permission("submit").
	# This override dropped that check entirely, letting any authenticated user
	# generate/mutate an e-way bill for a Delivery Note they have no access to
	# (row-level Sales isolation bypassed). Restore the same check the original had.
	doc.check_permission("submit")
	txn_type = int(transaction_type) if transaction_type else None
	loc = (doc.get("custom_location") or "").lower()
	wh_name = LOCATION_WAREHOUSE.get(loc)

	# Correct stale company_gstin/company_address on submitted docs (e.g. created before
	# the post-super() fix was in place). Permanent correction — wrong data, not a temp patch.
	from instabiz.overrides.utils import LOCATION_COMPANY_ADDRESS, LOCATION_COMPANY_GSTIN  # noqa: PLC0415
	correct_gstin = LOCATION_COMPANY_GSTIN.get(loc)
	correct_addr  = LOCATION_COMPANY_ADDRESS.get(loc)
	updates = {}
	if correct_gstin and doc.get("company_gstin") != correct_gstin:
		updates["company_gstin"] = correct_gstin
	if correct_addr and doc.get("company_address") != correct_addr:
		updates["company_address"] = correct_addr
	if updates:
		frappe.db.set_value(doctype, docname, updates, update_modified=False)
		doc.update(updates)

	_orig = EWaybillData.set_party_address_details

	def _patched(self):
		_orig(self)

		# --- Bill From override (explicit address wins over default) ---
		bill_from_addr = _addr_fields(bill_from_address)
		if bill_from_addr:
			_apply_addr(self.bill_from, bill_from_addr)
			_apply_addr(self.ship_from, bill_from_addr)   # ship_from defaults to copy of bill_from

		# --- Dispatch From: explicit address > warehouse lookup ---
		dispatch_addr = _addr_fields(dispatch_from_address)
		if dispatch_addr:
			_apply_addr(self.ship_from, dispatch_addr)
		elif wh_name:
			wh = frappe.db.get_value(
				"Warehouse", wh_name, ["address_line_1", "city", "pin"], as_dict=True
			)
			if wh:
				if wh.address_line_1:
					self.ship_from.address_line1 = wh.address_line_1.replace("\n", " ").strip()
				if wh.city:
					self.ship_from.city = wh.city
				if wh.pin:
					self.ship_from.pincode = wh.pin

		# --- Ship To override ---
		ship_to_addr = _addr_fields(ship_to_address)
		if ship_to_addr:
			_apply_addr(self.ship_to, ship_to_addr)

		# --- Transaction type override ---
		if txn_type:
			self.transaction_details.transaction_type = txn_type

	EWaybillData.set_party_address_details = _patched
	try:
		try:
			return generate_e_waybill(doctype=doctype, docname=docname, values=values, force=force)
		except Exception as e:
			if not _is_distance_error(str(e)):
				raise
			# Distance rejected by NIC — compute from pincodes and retry once
			computed_km = _compute_doc_distance(doc)
			if not computed_km:
				raise
			values_dict = frappe.parse_json(values) if isinstance(values, str) else dict(values or {})
			values_dict["distance"] = computed_km
			frappe.logger().info(f"[IB EWB] Distance error — retrying with computed {computed_km} km")
			return generate_e_waybill(doctype=doctype, docname=docname, values=values_dict, force=force)
	finally:
		EWaybillData.set_party_address_details = _orig


@frappe.whitelist()
def get_transport_gstin(transport_name):
	"""
	Return the GST transporter ID for an IB Transport entry.
	Priority: IB Transport.custom_transport_gst → local DB name match → GST public API name search.
	A GSTIN newly resolved via the fallback searches is saved back onto the IB
	Transport record (via doc.save(), not db.set_value, so its own before_save
	hook also derives custom_transport_state) — future e-way bills for the same
	transporter skip the search entirely.
	"""
	if not transport_name:
		return ""

	gstin = frappe.db.get_value("IB Transport", transport_name, "custom_transport_gst") or ""
	if gstin:
		return gstin

	# Local DB fallback: address or supplier records with a similar name
	gstin = _search_gstin_local(transport_name)
	if not gstin:
		# GST public API fallback: search by trade name
		gstin = _search_gstin_by_name(transport_name)

	if gstin and frappe.db.exists("IB Transport", transport_name):
		try:
			transport_doc = frappe.get_doc("IB Transport", transport_name)
			transport_doc.custom_transport_gst = gstin
			transport_doc.save(ignore_permissions=True)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "IB Transport GSTIN capture failed")

	return gstin or ""


def _search_gstin_local(name):
	"""Search Address and Supplier tables for a GSTIN matching the given name."""
	like = f"%{name}%"

	row = frappe.db.sql(
		"SELECT gstin FROM `tabAddress` WHERE gstin IS NOT NULL AND gstin != '' "
		"AND (address_title LIKE %s OR name LIKE %s) LIMIT 1",
		(like, like),
		as_dict=True,
	)
	if row:
		return row[0].gstin

	row = frappe.db.sql(
		"SELECT tax_id FROM `tabSupplier` WHERE tax_id IS NOT NULL AND tax_id != '' "
		"AND supplier_name LIKE %s LIMIT 1",
		(like,),
		as_dict=True,
	)
	if row:
		return row[0].tax_id

	return ""


def _search_gstin_by_name(name):
	"""Try GST public API name-based taxpayer search via india_compliance."""
	try:
		from india_compliance.gst_india.api_classes.public import PublicAPI  # pyright: ignore[reportMissingImports]
		api = PublicAPI()
		resp = api.get("search", params={"action": "TP", "CMPNM": name, "from": "1", "to": "5"})
		# API may return a list of matches or a single dict
		if isinstance(resp, list) and resp:
			item = resp[0]
		elif isinstance(resp, dict) and resp.get("gstin"):
			item = resp
		else:
			return ""
		return item.get("gstin") or item.get("GSTIN") or ""
	except Exception:
		return ""


def run_ewaybill_on_submit(doc, method=None):
	"""Not wired any more: e-Way Bills are made from the Sales Invoice (see after_migrate)."""
	if doc.get("is_return") or not doc.get("customer"):
		return

	# Self pickup — no third-party transporter; e-waybill must be generated from the Sales Invoice.
	# Matches "SELF PICKUP", "SELF PIKUP" and any future variants.
	if "SELF" in (doc.get("custom_transport") or "").upper():
		frappe.msgprint(
			_("Transport is Self Pickup — e-Way Bill not auto-generated. "
			  "Generate it from the linked Sales Invoice using the e-Way Bill action button."),
			title=_("Self Pickup — Generate E-Waybill from SI"),
			indicator="orange",
			alert=True,
		)
		return

	if not _is_ewb_configured():
		frappe.msgprint(
			_("e-Way Bill credentials not configured in GST Settings. "
			  "Generate e-Way Bill manually from the Delivery Note."),
			title=_("e-Way Bill Not Generated"),
			indicator="orange",
			alert=True,
		)
		return

	if doc.get("ewaybill"):
		return

	# Enqueue so DN commit is not rolled back if e-waybill API fails
	frappe.enqueue(
		"instabiz.overrides.ewaybill._generate_ewaybill_async",
		doc_name=doc.name,
		queue="short",
		now=frappe.flags.in_test,
	)


def after_migrate():
	"""e-Way Bills are made from the Sales Invoice (it carries the GST); the
	Delivery Note is internal and has no tax, so the Delivery Note route is off."""
	if frappe.db.exists("DocType", "GST Settings") and frappe.db.get_single_value(
			"GST Settings", "enable_e_waybill_from_dn"):
		frappe.db.set_single_value("GST Settings", "enable_e_waybill_from_dn", 0)
