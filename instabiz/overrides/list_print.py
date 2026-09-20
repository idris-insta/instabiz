"""instabiz.overrides.list_print — backend helpers for list-view and party-ledger printing."""
import html as _html_mod
import frappe
from frappe import _


@frappe.whitelist()
def get_print_company_info():
    """Returns company name, logo, GSTIN, and address for print headers."""
    company = frappe.defaults.get_global_default("company")
    if not company:
        rows = frappe.db.get_all("Company", fields=["name"], limit=1)
        company = rows[0].name if rows else ""
    if not company:
        return {}

    doc = frappe.get_cached_doc("Company", company)
    # Address is linked via Dynamic Link, not a field on Company
    addr_rows = frappe.db.sql(
        """
        SELECT a.address_line1, a.address_line2, a.city, a.state, a.pincode
        FROM `tabAddress` a
        INNER JOIN `tabDynamic Link` dl ON dl.parent = a.name
        WHERE dl.link_doctype = 'Company' AND dl.link_name = %s
        ORDER BY a.is_primary_address DESC, a.creation ASC
        LIMIT 1
        """,
        company,
        as_dict=True,
    )
    addr = addr_rows[0] if addr_rows else None

    # GSTIN: try india_compliance field first, then tax_id
    gstin = (
        getattr(doc, "gstin", None)
        or getattr(doc, "tax_id", None)
        or ""
    )

    return {
        "name":    company,
        "logo":    doc.company_logo or "",
        "gstin":   gstin,
        "phone":   doc.phone_no or "",
        "email":   doc.email or "",
        "address": addr,
    }


@frappe.whitelist()
def get_party_gl(party_type, party, from_date=None, to_date=None):
    """
    Returns GL entries for a party with running balance.
    party_type: 'Customer' or 'Supplier'
    """
    from instabiz.overrides.permissions import _is_privileged

    if party_type not in ("Customer", "Supplier"):
        frappe.throw(_("Invalid party type."), frappe.PermissionError)

    user = frappe.session.user
    if not _is_privileged(user):
        if party_type == "Customer":
            owner = frappe.db.get_value("Customer", party, "custom_sales_person_user")
            if owner != user:
                frappe.throw(_("Not permitted to view this ledger."), frappe.PermissionError)
        else:
            if not set(frappe.get_roles(user)) & {"Purchase User", "Purchase Manager", "Accounts User", "Accounts Manager"}:
                frappe.throw(_("Not permitted to view this ledger."), frappe.PermissionError)

    filters = {
        "party_type": party_type,
        "party": party,
        "is_cancelled": 0,
    }
    if from_date:
        filters["posting_date"] = [">=", from_date]
    if to_date:
        if isinstance(filters.get("posting_date"), list):
            # combine into between
            filters["posting_date"] = ["between", [from_date, to_date]]
        else:
            filters["posting_date"] = ["<=", to_date]

    entries = frappe.db.get_all(
        "GL Entry",
        filters=filters,
        fields=[
            "posting_date", "voucher_type", "voucher_no",
            "remarks", "debit", "credit",
        ],
        order_by="posting_date asc, creation asc",
        limit=2000,
    )

    balance = 0.0
    for e in entries:
        balance += (e.debit or 0) - (e.credit or 0)
        e["balance"] = balance

    return entries


@frappe.whitelist()
def get_gl_entries(filters=None, from_date=None, to_date=None,
                   account=None, party_type=None, party=None, limit=500):
    """Full GL entry list for the GL print view."""
    frappe.only_for(["System Manager", "Accounts Manager", "Accounts User"])
    db_filters = {"is_cancelled": 0}
    if from_date:
        db_filters["posting_date"] = [">=", from_date]
    if to_date:
        if "posting_date" in db_filters:
            db_filters["posting_date"] = ["between", [from_date, to_date]]
        else:
            db_filters["posting_date"] = ["<=", to_date]
    if account:
        db_filters["account"] = account
    if party_type:
        db_filters["party_type"] = party_type
    if party:
        db_filters["party"] = party

    entries = frappe.db.get_all(
        "GL Entry",
        filters=db_filters,
        fields=[
            "posting_date", "account", "party_type", "party",
            "voucher_type", "voucher_no", "debit", "credit", "remarks",
        ],
        order_by="posting_date asc, creation asc",
        limit=int(limit),
    )
    return entries


@frappe.whitelist()
def get_customer_outstanding_letter(customer):
    """Generate outstanding reminder letter HTML for a customer (used by the report Print Reminder button)."""
    # Real gap, fixed: no permission check at all -- any authenticated user
    # could call this directly for any customer and get real outstanding
    # invoice amounts/dates + billing address. Customer's own
    # permission_query_conditions hook (customer_query_conditions) already
    # scopes a non-privileged Sales User to their own customers -- reuse it
    # here instead of inventing a separate rule.
    frappe.has_permission("Customer", "read", customer, throw=True)
    from frappe.utils import today as today_fn, getdate, date_diff, flt, formatdate

    def _esc(v):
        return _html_mod.escape(str(v or ""))

    def _fmt(v):
        return f"₹ {flt(v):,.2f}"

    # Company info
    co = get_print_company_info()
    co_name    = _esc(co.get("name") or "")
    co_logo    = co.get("logo") or ""
    co_gstin   = _esc(co.get("gstin") or "")
    co_phone   = _esc(co.get("phone") or "")
    co_addr    = co.get("address") or {}
    co_addr_str = ", ".join(
        _esc(p) for p in [
            co_addr.get("address_line1"), co_addr.get("address_line2"),
            co_addr.get("city"), co_addr.get("state"),
            str(co_addr.get("pincode") or ""),
        ] if p
    )

    # Customer name
    cust_name = _esc(
        frappe.db.get_value("Customer", customer, "customer_name") or customer
    )

    # Customer primary address
    ca_rows = frappe.db.sql(
        """
        SELECT a.address_line1, a.address_line2, a.city, a.state, a.pincode
        FROM `tabAddress` a
        INNER JOIN `tabDynamic Link` dl ON dl.parent = a.name
        WHERE dl.link_doctype = 'Customer' AND dl.link_name = %s
        ORDER BY a.is_primary_address DESC, a.creation ASC LIMIT 1
        """,
        customer, as_dict=True,
    )
    ca = ca_rows[0] if ca_rows else {}
    cust_addr_html = "<br>".join(
        _esc(p) for p in [
            ca.get("address_line1"), ca.get("address_line2"),
            ca.get("city"), ca.get("state"),
            str(ca.get("pincode") or ""),
        ] if p
    )

    # Outstanding invoices
    today_date = getdate(today_fn())
    invoices = frappe.db.sql(
        """
        SELECT name, posting_date, due_date, outstanding_amount
        FROM `tabSales Invoice`
        WHERE customer = %s AND docstatus = 1 AND outstanding_amount > 0
          AND is_return = 0
        ORDER BY posting_date ASC
        """,
        customer, as_dict=True,
    )

    if not invoices:
        return f"<html><body style='font-family:Arial;padding:40px'>" \
               f"<h3>No outstanding invoices for {cust_name}</h3></body></html>"

    total = b30 = b3060 = b6090 = b90120 = b120180 = bover = 0.0
    inv_rows_html = ""

    for inv in invoices:
        ref = getdate(inv.due_date or inv.posting_date)
        age = max(0, date_diff(today_date, ref))
        amt = flt(inv.outstanding_amount)
        total += amt

        d30 = d3060 = d6090 = d90120 = d120180 = dover = "-"
        if age <= 30:
            b30 += amt;   d30    = _fmt(amt)
        elif age <= 60:
            b3060 += amt; d3060  = _fmt(amt)
        elif age <= 90:
            b6090 += amt; d6090  = _fmt(amt)
        elif age <= 120:
            b90120 += amt; d90120 = _fmt(amt)
        elif age <= 180:
            b120180 += amt; d120180 = _fmt(amt)
        else:
            bover += amt; dover  = _fmt(amt)

        age_c = "#c0392b" if age > 90 else "#e67e22" if age > 30 else "#27ae60"
        age_l = "Current" if age == 0 else f"{age} Days"
        pd = formatdate(str(inv.posting_date), "dd-MMM-yy")
        inv_rows_html += f"""
            <tr>
                <td class="c">{pd}</td>
                <td><strong>{_esc(inv.name)}</strong></td>
                <td class="c" style="color:{age_c}">{age_l}</td>
                <td class="r">{d30}</td><td class="r">{d3060}</td>
                <td class="r">{d6090}</td><td class="r">{d90120}</td>
                <td class="r">{d120180}</td><td class="r">{dover}</td>
            </tr>"""

    date_str   = formatdate(str(today_date), "dd-MMM-yy")
    logo_html  = f'<img src="{co_logo}" style="height:42px;object-fit:contain" alt="">' if co_logo else ""
    co_contact = " | ".join(p for p in [
        (f"Tel: {co_phone}") if co_phone else "",
        (f"Email: {co.get('email') or ''}")  if co.get("email") else "",
    ] if p)

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Outstanding Statement — {cust_name}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: Arial, sans-serif; font-size: 12px; color: #1a1a1a; background: #fff; }}
        .page {{ max-width: 1050px; margin: 0 auto; padding: 20px 24px; }}
        .hdr {{ display: flex; justify-content: space-between; align-items: flex-start;
                border-bottom: 2px solid #d97757; padding-bottom: 12px; margin-bottom: 18px; }}
        .co-name {{ font-size: 16px; font-weight: 700; color: #d97757; }}
        .co-meta {{ font-size: 10px; color: #555; margin-top: 4px; line-height: 1.5; }}
        .stmt-title {{ font-size: 13px; font-weight: 700; color: #c0392b;
                       letter-spacing: 1px; text-transform: uppercase; }}
        .two-col {{ display: flex; justify-content: space-between;
                    align-items: flex-start; margin-bottom: 20px; }}
        .to-lbl {{ font-size: 10px; color: #888; font-weight: 700; text-transform: uppercase; }}
        .to-name {{ font-size: 15px; font-weight: 700; margin: 4px 0; }}
        .to-addr {{ font-size: 12px; color: #555; line-height: 1.6; }}
        .box {{ border: 1px solid #faebcc; background: #fcf8e3; padding: 12px 16px;
                border-radius: 4px; text-align: right; min-width: 220px; }}
        .box-lbl {{ font-size: 11px; color: #8a6d3b; margin-bottom: 4px; }}
        .box-amt {{ font-size: 22px; font-weight: 700; color: #333; }}
        p.intro {{ font-size: 12px; margin-bottom: 18px; line-height: 1.7; }}
        table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 11px; }}
        th {{ padding: 7px 8px; font-size: 10px; font-weight: 700; border: 1px solid #ddd;
              background: #f9f9f9; text-align: center; }}
        td {{ padding: 5px 8px; border: 1px solid #eee; }}
        td.r {{ text-align: right; font-variant-numeric: tabular-nums; }}
        td.c {{ text-align: center; }}
        .tot td {{ font-weight: 700; background: #f5f5f5 !important;
                   border-top: 2px solid #d97757; }}
        .bank {{ border: 1px solid #ddd; border-radius: 4px; width: 54%; font-size: 11px; }}
        .bank-hdr {{ background: #f9f9f9; padding: 7px 12px; font-weight: 700;
                     border-bottom: 1px solid #ddd; font-size: 11px; }}
        .bank td {{ border: none; padding: 3px 8px; font-size: 11px; }}
        .sig {{ text-align: right; }}
        .sig-line {{ border-top: 1px dashed #ccc; display: inline-block; width: 200px;
                     padding-top: 4px; font-size: 10px; color: #888; margin-top: 50px; }}
        @media print {{
            .page {{ padding: 0; }}
            thead tr {{ print-color-adjust: exact; -webkit-print-color-adjust: exact; }}
        }}
    </style>
</head>
<body>
<div class="page">
    <div class="hdr">
        <div style="display:flex;align-items:center;gap:12px">
            {logo_html}
            <div>
                <div class="co-name">{co_name}</div>
                <div class="co-meta">
                    {co_addr_str}<br>
                    {("GSTIN: " + co_gstin) if co_gstin else ""}
                    {(" | " + co_contact) if co_contact else ""}
                </div>
            </div>
        </div>
        <div style="text-align:right">
            <div class="stmt-title">Outstanding Statement</div>
            <div style="font-size:11px;color:#555;margin-top:6px">
                <strong>Date:</strong> {date_str}
            </div>
        </div>
    </div>

    <div class="two-col">
        <div>
            <div class="to-lbl">To,</div>
            <div class="to-name">{cust_name}</div>
            <div class="to-addr">{cust_addr_html}</div>
        </div>
        <div class="box">
            <div class="box-lbl">Total Outstanding Balance</div>
            <div class="box-amt">
                {_fmt(total)}
                <span style="font-size:13px;font-weight:700;color:#c0392b">Dr</span>
            </div>
        </div>
    </div>

    <p class="intro">
        Dear Sir/Madam,<br>
        Given below is the detail of amounts outstanding against your name in our books as of {date_str}.
        We request you to take immediate steps for settling the overdue bills and oblige.
    </p>

    <table>
        <thead>
            <tr>
                <th rowspan="2" style="vertical-align:middle;width:10%">Invoice Date</th>
                <th rowspan="2" style="vertical-align:middle;width:13%">Invoice #</th>
                <th rowspan="2" style="vertical-align:middle;width:10%">Overdue By</th>
                <th colspan="6">Aging Breakdown (Amount in INR)</th>
            </tr>
            <tr>
                <th>&lt; 30 Days</th><th>30 – 60 Days</th><th>60 – 90 Days</th>
                <th>90 – 120 Days</th><th>120 – 180 Days</th><th>&gt; 180 Days</th>
            </tr>
        </thead>
        <tbody>
            {inv_rows_html}
            <tr class="tot">
                <td colspan="3" class="r">Total Aging Summary:</td>
                <td class="r">{_fmt(b30) if b30 else "-"}</td>
                <td class="r">{_fmt(b3060) if b3060 else "-"}</td>
                <td class="r">{_fmt(b6090) if b6090 else "-"}</td>
                <td class="r">{_fmt(b90120) if b90120 else "-"}</td>
                <td class="r">{_fmt(b120180) if b120180 else "-"}</td>
                <td class="r">{_fmt(bover) if bover else "-"}</td>
            </tr>
        </tbody>
    </table>

    <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-top:30px">
        <div class="bank">
            <div class="bank-hdr">Company's Bank Details for Remittance</div>
            <table style="margin-bottom:0">
                <tr>
                    <td style="color:#666;width:35%"><strong>Bank Name:</strong></td>
                    <td>HDFC Bank Ltd. (Mumbai)</td>
                </tr>
                <tr>
                    <td style="color:#666"><strong>A/c No:</strong></td>
                    <td><strong style="font-family:monospace;font-size:13px">50200023672503</strong></td>
                </tr>
                <tr>
                    <td style="color:#666"><strong>Branch:</strong></td>
                    <td>Mohamed Ali Road</td>
                </tr>
                <tr>
                    <td style="color:#666"><strong>IFS Code:</strong></td>
                    <td><strong style="font-family:monospace;color:#2e6da4">HDFC0000627</strong></td>
                </tr>
            </table>
        </div>
        <div class="sig">
            <div>Yours faithfully,<br><strong>For {co_name}</strong></div>
            <div class="sig-line">Authorized Signatory</div>
        </div>
    </div>
</div>
</body>
</html>"""
