# Copyright (c) 2026, Instabiz Solutions India Pvt Ltd and Contributors
# See license.txt
"""
instabiz/instabiz/doctype/ib_document_intake/ib_document_intake.py

Document Intake AI: upload a scanned PO/SO (or paste raw text directly) ->
local Tesseract OCR fills Raw Text -> Claude extraction -> human review on
this record -> explicit convert_to_draft() -> real draft SO/PO.

OCR (run_ocr) and extraction (extract) are two independent steps — OCR
needs only a local Tesseract install (no API key, no credits) and only
ever touches raw_text/ocr_error; it's a convenience for filling Raw Text,
not a requirement. Raw Text can always be typed or pasted directly instead.

Guarantees (see tests in test_ib_document_intake.py):
  1. extract() NEVER creates a Sales Order / Purchase Order. It only writes
     extracted_json / match_status / matched_party on THIS record.
  2. If llm.py returns None (no API key / no credits — the documented live
     state of this instance), extraction_error is set to a clear message
     and status stays "Draft" instead of silently producing an empty draft.
  3. convert_to_draft() is the ONLY path that creates a real document, is
     never called implicitly, requires status == "Extracted" (i.e. a
     completed, reviewable extraction already exists) and a resolved
     matched_party, and always inserts with docstatus=0 (draft) — it never
     submits.
"""
import json
import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, flt, nowdate

from instabiz.overrides import llm

_SALES_ROLES = {"Sales User", "Sales Manager", "System Manager"}
_PURCHASE_ROLES = {"Purchase User", "Purchase Manager", "System Manager"}
_ACCOUNTS_ROLES = {"Accounts User", "Accounts Manager"}
GSTIN_RE = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b")


class IBDocumentIntake(Document):
	def validate(self):
		if not self.status:
			self.status = "Draft"
		roles = set(frappe.get_roles(frappe.session.user))
		if "System Manager" in roles:
			return
		if self.intake_type == "Sales Order" and not (_SALES_ROLES & roles):
			frappe.throw(_("You need a Sales role to create a Sales Order intake."))
		if self.intake_type in ("Purchase Order", "Purchase Invoice") and not ((_PURCHASE_ROLES | _ACCOUNTS_ROLES) & roles):
			frappe.throw(_("You need a Purchase or Accounts role to create a {0} intake.").format(self.intake_type))

	# ── OCR ──────────────────────────────────────────────────────────────────

	@frappe.whitelist()
	def run_ocr(self):
		"""OCR the attached Scanned Document (image or PDF) into Raw Text.
		Local Tesseract only — no LLM/API call, no credit dependency. Never
		touches extracted_json/status; purely fills raw_text so the existing
		extract() flow can run on it exactly as if it had been pasted."""
		self.check_permission("write")
		if not self.scanned_document:
			frappe.throw(_("Attach a Scanned Document first."))

		try:
			text = _ocr_file(self.scanned_document)
		except Exception as e:
			self.ocr_error = f"OCR failed: {e}"
			self.save()
			return {"ok": False, "message": self.ocr_error}

		if not text.strip():
			self.ocr_error = "OCR ran but found no readable text — try a clearer scan or paste the text manually."
			self.save()
			return {"ok": False, "message": self.ocr_error}

		self.raw_text = text
		self.ocr_error = ""
		self.save()
		return {"ok": True, "text": text}

	# ── extraction ───────────────────────────────────────────────────────────

	@frappe.whitelist()
	def extract(self):
		"""Send raw_text to Claude for structured extraction, fuzzy-match the
		party/items against real records, and save the result on THIS record.
		Never creates any other document — see module docstring."""
		self.check_permission("write")
		if not (self.raw_text or "").strip():
			frappe.throw(_("Paste the raw PO/SO text into Raw Text before extracting."))

		system = (
			"You are a data-extraction assistant for an Indian B2B adhesive-tape "
			"manufacturer. Extract structured order details from the raw text below "
			"(an email body or an OCR'd PO/SO scan). Reply with ONLY a JSON object, "
			"no prose, no markdown fences, in exactly this shape:\n"
			'{"party_name": "...", "party_gstin": "buyer GSTIN or null", "delivery_date": "YYYY-MM-DD or null", '
			'"items": [{"description": "...", "qty": <number or null>, "rate": <number or null>}]}\n'
			"Keep each item description with its sizes as written (width mm, length m, micron, colour, "
			"material), e.g. '48mm x 65m brown BOPP 40 mic'.\n"
			"If a field is not present in the text, use null. Never invent data that "
			"is not present in the text."
		)
		if self.intake_type == "Purchase Invoice":
			system = (
				"You read supplier tax invoices (purchase bills) for an Indian B2B adhesive-tape "
				"manufacturer. Reply with ONLY a JSON object, no prose, no markdown fences:\n"
				'{"party_name": "supplier name", "supplier_gstin": "...", "bill_no": "...", '
				'"bill_date": "YYYY-MM-DD", "grand_total": <number>, '
				'"items": [{"description": "...", "hsn": "...", "qty": <number>, "rate": <number before tax>}]}\n'
				"Use null for anything not in the text. Never invent data."
			)
		prompt = f"Document type: {self.intake_type}\n\nRaw text:\n{(self.raw_text or '')[:6000]}"
		raw = llm.complete(system, prompt, max_tokens=1200)

		if not raw and self.intake_type == "Purchase Invoice":
			return self._extract_bill_header()

		rule_note = ""
		if not raw and self.intake_type in ("Sales Order", "Purchase Order"):
			# no Claude: read the lines ourselves (qty / rate / sizes / party by GSTIN or first line)
			ruled = rule_extract(self.raw_text or "", "Customer" if self.intake_type == "Sales Order" else "Supplier")
			if ruled.get("items"):
				raw = json.dumps(ruled)
				rule_note = _("Read without AI (Claude key has no credit) — check every line.")

		if not raw:
			self.extracted_json = json.dumps({"error": "extraction_unavailable"}, indent=2)
			self.extraction_error = (
				"Extraction unavailable — the Claude API key is missing or the "
				"account has no credits. Fill in the fields manually or retry later."
			)
			self.match_status = ""
			self.matched_party = ""
			self.status = "Draft"
			self.save()
			return {"ok": False, "message": self.extraction_error}

		parsed = _parse_llm_json(raw)
		if not isinstance(parsed, dict):
			self.extracted_json = json.dumps({"error": "unparseable", "raw": raw[:2000]}, indent=2)
			self.extraction_error = (
				"Claude returned a response that could not be parsed as JSON — "
				"please retry or enter the details manually."
			)
			self.match_status = ""
			self.matched_party = ""
			self.status = "Draft"
			self.save()
			return {"ok": False, "message": self.extraction_error}

		doctype = "Customer" if self.intake_type == "Sales Order" else "Supplier"
		party_guess = (parsed.get("party_name") or "").strip()
		party_match = match_supplier_gstin(parsed.get("supplier_gstin")) if doctype == "Supplier" else None
		if not party_match or party_match["status"] == "Not Matched":
			party_match = match_party(party_guess, doctype)

		if parsed.get("party_gstin") and doctype == "Customer" and party_match["status"] not in ("Exact Match",):
			by_gstin = match_customer_gstin(parsed["party_gstin"])
			if by_gstin:
				party_match = {"status": "Exact Match", "matches": [by_gstin]}
		customer = party_match["matches"][0] if doctype == "Customer" and party_match["status"] in (
			"Exact Match", "Fuzzy Match") and party_match["matches"] else None

		items = parsed.get("items") or []
		if not isinstance(items, list):
			items = []
		for it in items:
			if isinstance(it, dict):
				m = match_item(it.get("description") or "")
				if m["status"] != "Exact Match":
					spec = spec_match_item(it.get("description") or "", customer)
					if spec["status"] in ("Exact Match", "Fuzzy Match") or (
							m["status"] == "Not Matched" and spec["matches"]):
						m = spec
				it["match"] = m
		parsed["items"] = items

		self.customer_or_supplier = party_guess
		# Keep the full party-match candidate list on the record (not just the
		# single-result match_status/matched_party summary fields) so a human
		# reviewer can actually see what Ambiguous/Not Matched considered —
		# this is otherwise only present in the RPC response, which is lost
		# the moment the form does frm.reload_doc().
		parsed["party_match"] = party_match
		self.extracted_json = json.dumps(parsed, indent=2, default=str)
		self.match_status = party_match["status"]
		self.matched_party = (
			party_match["matches"][0]
			if party_match["status"] in ("Exact Match", "Fuzzy Match") and party_match["matches"]
			else ""
		)
		self.extraction_error = rule_note
		self.status = "Extracted"
		self.save()
		return {"ok": True, "extracted": parsed, "party_match": party_match}

	def _extract_bill_header(self):
		"""No AI available: read the bill header with plain rules (supplier GSTIN, bill
		number, date, total). The lines are then entered on the Purchase Invoice itself."""
		parsed = read_bill_header(self.raw_text)
		party_match = match_supplier_gstin(parsed.get("supplier_gstin"))
		parsed["items"] = []
		parsed["party_match"] = party_match
		parsed["read_by"] = "rules"
		self.customer_or_supplier = parsed.get("supplier_gstin") or ""
		self.extracted_json = json.dumps(parsed, indent=2, default=str)
		self.match_status = party_match["status"]
		self.matched_party = party_match["matches"][0] if party_match["status"] == "Exact Match" else ""
		self.extraction_error = _(
			"Read without AI (no Claude key): supplier, bill no, date and total only. "
			"Convert opens a new Purchase Invoice with these filled in — add the lines there."
		)
		self.status = "Extracted"
		self.save()
		return {"ok": True, "extracted": parsed, "party_match": party_match}

	# ── conversion (the ONLY path that creates a real document) ────────────

	@frappe.whitelist()
	def convert_to_draft(self):
		"""Explicit human action. Creates a real, still-draft (docstatus=0)
		Sales Order / Purchase Order from the reviewed extraction on this
		record. Requires an already-Extracted record with a resolved party —
		never runs implicitly from extract()."""
		self.check_permission("write")
		if self.status == "Converted":
			frappe.throw(
				_("Already converted to {0} {1}.").format(self.created_doctype, self.created_docname)
			)
		if self.status != "Extracted":
			frappe.throw(_("Run Extract first and review the extracted fields before converting."))
		if not (self.matched_party or "").strip():
			frappe.throw(_("Resolve the customer/supplier match before converting — see Match Status."))
		if not frappe.db.exists(
			"Customer" if self.intake_type == "Sales Order" else "Supplier", self.matched_party
		):
			frappe.throw(_("Matched party {0} no longer exists.").format(self.matched_party))

		try:
			parsed = json.loads(self.extracted_json or "{}")
		except Exception:
			frappe.throw(_("Extracted JSON is not valid — re-run Extract or fix it manually."))

		items = parsed.get("items") or []
		resolved_items = []
		for it in items:
			if not isinstance(it, dict):
				continue
			match = it.get("match") or {}
			item_code = None
			if match.get("status") in ("Exact Match", "Fuzzy Match") and match.get("matches"):
				item_code = match["matches"][0]
			if not item_code:
				frappe.throw(
					_("Item '{0}' has no confirmed match — resolve it in Extracted JSON before converting.")
					.format(it.get("description") or "?")
				)
			resolved_items.append({
				"item_code": item_code,
				"qty": flt(it.get("qty")) or 1,
				"rate": flt(it.get("rate")) or 0,
			})
		if not resolved_items and self.intake_type == "Purchase Invoice":
			return {"ok": True, "open_new": self._bill_fields(parsed)}
		if not resolved_items:
			frappe.throw(_("No line items to convert — check the extraction."))

		delivery_date = parsed.get("delivery_date") or add_days(nowdate(), 7)
		try:
			delivery_date = frappe.utils.getdate(delivery_date)
		except Exception:
			delivery_date = add_days(nowdate(), 7)
		company = frappe.db.get_single_value("Global Defaults", "default_company")

		if self.intake_type == "Sales Order":
			if not (self.location or "").strip() or self.location == "Select":
				frappe.throw(_("Select a Location before converting — Sales Order requires one to save."))
			doc = frappe.new_doc("Sales Order")
			doc.customer = self.matched_party
			doc.company = company
			doc.custom_location = self.location
			doc.transaction_date = nowdate()
			doc.delivery_date = delivery_date
			for ri in resolved_items:
				uom = frappe.db.get_value("Item", ri["item_code"], "stock_uom") or "Nos"
				doc.append("items", {
					**ri, "uom": uom, "conversion_factor": 1, "delivery_date": delivery_date,
				})
		elif self.intake_type == "Purchase Invoice":
			doc = frappe.new_doc("Purchase Invoice")
			doc.update(self._bill_fields(parsed))
			for ri in resolved_items:
				uom = frappe.db.get_value("Item", ri["item_code"], "stock_uom") or "Nos"
				doc.append("items", {**ri, "uom": uom, "stock_uom": uom, "conversion_factor": 1})
		else:
			doc = frappe.new_doc("Purchase Order")
			doc.supplier = self.matched_party
			doc.company = company
			doc.transaction_date = nowdate()
			doc.schedule_date = delivery_date
			for ri in resolved_items:
				uom = frappe.db.get_value("Item", ri["item_code"], "stock_uom") or "Nos"
				doc.append("items", {
					**ri, "uom": uom, "stock_uom": uom, "conversion_factor": 1,
					"schedule_date": delivery_date,
				})

		# Standard insert() — docstatus stays 0 (draft). submit() is never called.
		doc.insert(ignore_permissions=False)

		if self.scanned_document and doc.doctype == "Purchase Invoice":
			frappe.get_doc({"doctype": "File", "file_url": self.scanned_document,
				"attached_to_doctype": doc.doctype, "attached_to_name": doc.name}).insert(ignore_permissions=True)
		self.created_doctype = doc.doctype
		self.created_docname = doc.name
		self.status = "Converted"
		self.save()
		return {"ok": True, "doctype": doc.doctype, "docname": doc.name}


	def _bill_fields(self, parsed):
		from instabiz.overrides.utils import LOCATION_WAREHOUSE
		loc = (self.location or "").strip()
		if not loc or loc == "Select":
			frappe.throw(_("Select a Location before converting — the bill is booked to that branch."))
		try:
			bill_date = frappe.utils.getdate(parsed.get("bill_date")) if parsed.get("bill_date") else None
		except Exception:
			bill_date = None
		return {
			"supplier": self.matched_party,
			"company": frappe.db.get_single_value("Global Defaults", "default_company"),
			"custom_location": loc,
			"set_warehouse": LOCATION_WAREHOUSE.get(loc.lower()),
			"bill_no": parsed.get("bill_no"),
			"bill_date": str(bill_date) if bill_date else None,
			"posting_date": nowdate(),
			"remarks": _("From {0}").format(self.name),
		}


# ── module-level helpers (also unit-tested directly) ──────────────────────

_DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y", "%d-%b-%Y", "%d-%b-%y", "%d/%b/%Y")


def read_bill_header(text):
	"""Rule-based bill header: the first GSTIN that is not one of ours is the
	supplier's; bill number, date and grand total from the usual labels."""
	from datetime import datetime

	text = text or ""
	ours = set(frappe.get_all("Address", filters={"is_your_company_address": 1}, pluck="gstin")) - {None, ""}
	gstins = [g for g in GSTIN_RE.findall(text.upper()) if g not in ours]
	no = re.search(r"(?:invoice|bill|inv)\.?\s*(?:no|number|#)\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]{1,24})", text, re.I)
	dt = re.search(r"date\s*[:\-]?\s*(\d{1,2}[./\-][A-Za-z0-9]{1,3}[./\-]\d{2,4})", text, re.I)
	tot = None
	for m in re.finditer(r"(?:grand\s*total|invoice\s*total|total\s*amount|net\s*payable)\s*[:\-]?\s*(?:rs\.?|inr|\u20b9)?\s*([\d,]+\.?\d*)", text, re.I):
		tot = m.group(1)
	bill_date = None
	if dt:
		for fmt in _DATE_FORMATS:
			try:
				bill_date = datetime.strptime(dt.group(1), fmt).date().isoformat()
				break
			except ValueError:
				continue
	return {"supplier_gstin": gstins[0] if gstins else None, "bill_no": no.group(1) if no else None,
		"bill_date": bill_date, "grand_total": flt(tot.replace(",", "")) if tot else None}


def match_supplier_gstin(gstin):
	"""Supplier by GSTIN — on the Supplier itself, else on one of its addresses."""
	gstin = (gstin or "").strip().upper()
	if not gstin:
		return {"status": "Not Matched", "matches": []}
	names = frappe.get_all("Supplier", filters={"gstin": gstin}, pluck="name")
	if not names:
		names = frappe.db.sql_list(
			"""SELECT DISTINCT dl.link_name FROM `tabAddress` a
			JOIN `tabDynamic Link` dl ON dl.parent = a.name AND dl.parenttype = 'Address'
			WHERE dl.link_doctype = 'Supplier' AND a.gstin = %s""", gstin)
	if len(names) == 1:
		return {"status": "Exact Match", "matches": names}
	if names:
		return {"status": "Ambiguous", "matches": names}
	return {"status": "Not Matched", "matches": []}


# ── Order reading without AI + size-aware item matching ─────────────────────

_QTY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(rolls?|pcs|nos|no\.?|boxes|box|ctns?|cartons?|pkts?|packets?|kgs?|sqm|sqmt)\b", re.I)
_RATE_RE = re.compile(r"(?:@|rs\.?|₹|rate[:\s]*)\s*(\d+(?:\.\d+)?)", re.I)
_W_RE = re.compile(r"(\d{1,4}(?:\.\d+)?)\s*mm\b", re.I)
_L_RE = re.compile(r"(\d{1,5}(?:\.\d+)?)\s*(?:m|mtr|mtrs|meter|metre|meters|metres|yds?)\b", re.I)
_MIC_RE = re.compile(r"(\d{2,3})\s*(?:mic|micron|microns|µ|um)\b", re.I)


def rule_extract(text, party_doctype="Customer"):
	"""Plain-text order → {party_name, party_gstin, delivery_date, items[]}.
	A line is an item when it has a quantity with a unit (500 rolls, 20 ctn…)."""
	lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
	gstins = [g for g in GSTIN_RE.findall((text or "").upper()) if not frappe.db.exists("Address", {"gstin": g, "is_your_company_address": 1})]
	items = []
	for ln in lines:
		q = _QTY_RE.search(ln)
		if not q or GSTIN_RE.search(ln.upper()):
			continue
		r = _RATE_RE.search(ln)
		desc = ln
		for pat in (q, r):
			if pat:
				desc = desc.replace(pat.group(0), " ")
		desc = re.sub(r"^\s*\d+[.)]\s*", "", desc)
		desc = re.sub(r"[-–:|,]+\s*$", "", re.sub(r"\s{2,}", " ", desc)).strip(" -–:|,")
		if len(desc) < 3:
			continue
		items.append({"description": desc, "qty": flt(q.group(1)), "rate": flt(r.group(1)) if r else None})
	party = ""
	for ln in lines[:6]:
		if not _QTY_RE.search(ln) and not re.match(r"^(to|date|po|order|dear|hi|hello|subject)\b", ln, re.I) and len(ln) > 3:
			party = re.sub(r"^(from|m/s\.?|ms\.?)\s*[:\-]?\s*", "", ln, flags=re.I)
			break
	return {"party_name": party, "party_gstin": gstins[0] if gstins else None, "delivery_date": None, "items": items}


def match_customer_gstin(gstin):
	gstin = (gstin or "").strip().upper()
	if not gstin:
		return None
	cust = frappe.db.get_value("Customer", {"gstin": gstin}, "name") if frappe.db.has_column("Customer", "gstin") else None
	if cust:
		return cust
	row = frappe.db.sql("""SELECT dl.link_name FROM `tabAddress` a JOIN `tabDynamic Link` dl ON dl.parent = a.name
		WHERE a.gstin = %s AND dl.link_doctype = 'Customer' LIMIT 1""", gstin)
	return row[0][0] if row else None


def _spec_of(text):
	t = (text or "").lower()
	w = _W_RE.search(t)
	ln = _L_RE.search(re.sub(r"\d+(?:\.\d+)?\s*mm\b", " ", t))
	mic = _MIC_RE.search(t)
	return {"width": flt(w.group(1)) if w else 0, "length": flt(ln.group(1)) if ln else 0,
		"micron": mic.group(1) if mic else "", "tokens": _tokenize(re.sub(r"\d+(?:\.\d+)?\s*[a-zµ]*", " ", t))}


def spec_match_item(description, customer=None, limit=5):
	"""Size-aware match: width mm, length m, micron and colour/material words
	against the Item master, with a boost for items this customer bought before."""
	s = _spec_of(description)
	if not (s["width"] or s["length"] or s["micron"] or s["tokens"]):
		return {"status": "Not Matched", "matches": []}
	fields = ["name", "item_name", "width_mm", "length_mtr", "custom_thickness", "color"]
	fields = [f for f in fields if f in ("name", "item_name") or frappe.db.has_column("Item", f)]
	rows = frappe.get_all("Item", filters={"disabled": 0, "is_sales_item": 1}, fields=fields)
	bought = set()
	if customer:
		bought = set(frappe.db.sql_list("""SELECT DISTINCT c.item_code FROM `tabSales Order Item` c
			JOIN `tabSales Order` p ON p.name = c.parent WHERE p.customer = %s AND p.docstatus = 1""", customer))
	colours = {c.lower() for c in frappe.get_all("Color", pluck="name")} if frappe.db.table_exists("Color") else set()
	scored = []
	for r in rows:
		score = 0.0
		if s["width"] and flt(r.get("width_mm")):
			score += 3 if abs(flt(r.width_mm) - s["width"]) < 0.5 else -2
		if s["length"] and flt(r.get("length_mtr")):
			score += 2 if abs(flt(r.length_mtr) - s["length"]) < 0.5 else -1
		if s["micron"]:
			score += 2 if s["micron"] in (str(r.get("custom_thickness") or "") + " " + (r.item_name or "")).lower() else 0
		name_tokens = _tokenize(r.item_name) | _tokenize(r.get("color"))
		for tok in s["tokens"]:
			if len(tok) < 3:
				continue
			if tok in name_tokens:
				score += 2 if tok in colours else 1
		if r.name in bought:
			score += 2
		if score >= 4:
			scored.append((score, r.name))
	scored.sort(key=lambda x: x[0], reverse=True)
	if not scored:
		return {"status": "Not Matched", "matches": []}
	if len(scored) == 1 or scored[0][0] - scored[1][0] >= 2:
		return {"status": "Fuzzy Match", "matches": [scored[0][1]], "how": "size / colour match"}
	return {"status": "Ambiguous", "matches": [x[1] for x in scored[:limit]], "how": "size / colour match"}


def _parse_llm_json(raw):
	raw = (raw or "").strip()
	if raw.startswith("```"):
		raw = re.sub(r"^```(json)?", "", raw, flags=re.I).strip()
		raw = raw.rstrip("`").strip()
	try:
		return json.loads(raw)
	except Exception:
		m = re.search(r"\{.*\}", raw, re.S)
		if m:
			try:
				return json.loads(m.group(0))
			except Exception:
				return None
		return None


def _ocr_file(file_url):
	"""Run local Tesseract OCR on an attached file (image or PDF) and return
	the extracted text. PDFs are rasterized page-by-page via pdf2image
	(needs poppler-utils) before OCR — Tesseract itself only reads images."""
	import pytesseract
	from PIL import Image

	file_doc = frappe.get_doc("File", {"file_url": file_url})
	# only a file the caller may open (not someone else's private attachment)
	if not frappe.has_permission("File", "read", doc=file_doc):
		frappe.throw(_("You cannot read that file."), frappe.PermissionError)
	path = file_doc.get_full_path()

	if path.lower().endswith(".pdf"):
		from pdf2image import convert_from_path
		pages = convert_from_path(path)
		return "\n\n".join(pytesseract.image_to_string(page) for page in pages)

	return pytesseract.image_to_string(Image.open(path))


def _tokenize(text):
	return set(re.findall(r"\w+", (text or "").lower()))


def match_party(name_guess, doctype, limit=5):
	"""Exact match first, then LIKE, then token-overlap fuzzy match, against
	real Customer/Supplier records. Never assumes Claude's string is a real
	docname — ambiguous/no-match cases are surfaced, not guessed silently."""
	name_guess = (name_guess or "").strip()
	if not name_guess:
		return {"status": "Not Matched", "matches": []}

	field = "customer_name" if doctype == "Customer" else "supplier_name"

	# 1. Exact match — either the docname itself or the display-name field.
	if frappe.db.exists(doctype, name_guess):
		return {"status": "Exact Match", "matches": [name_guess]}
	exact = frappe.db.get_value(doctype, {field: name_guess}, "name")
	if exact:
		return {"status": "Exact Match", "matches": [exact]}

	# 2. Substring LIKE fallback.
	like_rows = frappe.db.sql(
		f"SELECT name FROM `tab{doctype}` WHERE {field} LIKE %s LIMIT %s",
		(f"%{name_guess}%", limit),
		as_dict=True,
	)
	if len(like_rows) == 1:
		return {"status": "Fuzzy Match", "matches": [like_rows[0].name]}
	if len(like_rows) > 1:
		return {"status": "Ambiguous", "matches": [r.name for r in like_rows]}

	# 3. Token-overlap fuzzy fallback.
	guess_tokens = _tokenize(name_guess)
	if not guess_tokens:
		return {"status": "Not Matched", "matches": []}
	rows = frappe.db.sql(f"SELECT name, {field} AS label FROM `tab{doctype}`", as_dict=True)
	scored = []
	for r in rows:
		tokens = _tokenize(r.label)
		if not tokens:
			continue
		overlap = len(guess_tokens & tokens) / len(guess_tokens | tokens)
		if overlap >= 0.4:
			scored.append((overlap, r.name))
	scored.sort(key=lambda x: x[0], reverse=True)
	if not scored:
		return {"status": "Not Matched", "matches": []}
	if len(scored) == 1 or (scored[0][0] - scored[1][0]) > 0.2:
		return {"status": "Fuzzy Match", "matches": [scored[0][1]]}
	return {"status": "Ambiguous", "matches": [s[1] for s in scored[:limit]]}


def match_item(description, limit=5):
	"""Same exact -> LIKE -> token-overlap fuzzy strategy as match_party, but
	against Item.item_name / item_code."""
	description = (description or "").strip()
	if not description:
		return {"status": "Not Matched", "matches": []}

	if frappe.db.exists("Item", description):
		return {"status": "Exact Match", "matches": [description]}
	exact = frappe.db.get_value("Item", {"item_name": description}, "name")
	if exact:
		return {"status": "Exact Match", "matches": [exact]}

	like_rows = frappe.db.sql(
		"SELECT name FROM `tabItem` WHERE item_name LIKE %s AND disabled = 0 LIMIT %s",
		(f"%{description}%", limit),
		as_dict=True,
	)
	if len(like_rows) == 1:
		return {"status": "Fuzzy Match", "matches": [like_rows[0].name]}
	if len(like_rows) > 1:
		return {"status": "Ambiguous", "matches": [r.name for r in like_rows]}

	guess_tokens = _tokenize(description)
	if not guess_tokens:
		return {"status": "Not Matched", "matches": []}
	rows = frappe.db.sql(
		"SELECT name, item_name FROM `tabItem` WHERE disabled = 0", as_dict=True
	)
	scored = []
	for r in rows:
		tokens = _tokenize(r.item_name)
		if not tokens:
			continue
		overlap = len(guess_tokens & tokens) / len(guess_tokens | tokens)
		if overlap >= 0.4:
			scored.append((overlap, r.name))
	scored.sort(key=lambda x: x[0], reverse=True)
	if not scored:
		return {"status": "Not Matched", "matches": []}
	if len(scored) == 1 or (scored[0][0] - scored[1][0]) > 0.2:
		return {"status": "Fuzzy Match", "matches": [scored[0][1]]}
	return {"status": "Ambiguous", "matches": [s[1] for s in scored[:limit]]}


@frappe.whitelist()
def quick_read(raw_text=None, file_url=None, location=None, intake_type="Sales Order"):
	"""Sales Order list → Read Order: one intake from pasted text (WhatsApp / email)
	or an attached PO, OCR if needed, then extract. Returns the intake name."""
	doc = frappe.get_doc({"doctype": "IB Document Intake", "intake_type": intake_type,
		"location": location or "", "raw_text": raw_text or "", "scanned_document": file_url or None})
	doc.insert()
	if file_url and not (raw_text or "").strip():
		doc.run_ocr()
		doc.reload()
	if (doc.raw_text or "").strip():
		doc.extract()
	return doc.name
