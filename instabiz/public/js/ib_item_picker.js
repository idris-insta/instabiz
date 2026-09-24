/**
 * ib_item_picker.js
 * One item-search dropdown, everywhere an item can be added.
 *
 * Quotation and Sales Order have used instabiz.overrides.item.item_query since
 * the start — multi-word search ("blue 1200" matches both, in any order),
 * barcode lookup, and the colour and liner on the description line:
 *
 *     IS-57145V-1.0GYBBBL
 *     BUTYL REINFORCE ALUMINIUM FOIL TAPE BB, GREY, BLACK LINER
 *
 * Every other form was on the stock ERPNext search, which puts the item group
 * there instead — "BUTYL REINFORCE ALUMINIUM FOIL TAPE BB, FOIL" — so the same
 * roll was identifiable on a quote and anonymous on the purchase order for it.
 *
 * Registered on `refresh`, deliberately. ERPNext sets its own item_code query
 * in setup() (selling_common, buying, Material Request) and in onload() (Stock
 * Reconciliation); whichever handler runs last wins, so registering in setup()
 * only wins by luck and loses outright wherever ERPNext uses onload. refresh
 * runs after both. set_query just stores a function on the form, so repeating
 * it on every refresh costs nothing.
 *
 * Each form keeps its own is_sales_item / is_purchase_item filter — that is the
 * form's business, not the search's, and dropping it would start offering
 * sell-only items to buyers.
 */

const IB_ITEM_QUERY = "instabiz.overrides.item.item_query";

// doctype -> { table, party: fieldname on the parent, flag: item-type filter }
const IB_ITEM_FORMS = {
	"Quotation":               { table: "items", party: "party_name", flag: "is_sales_item" },
	"Sales Order":             { table: "items", party: "customer",   flag: "is_sales_item" },
	"Delivery Note":           { table: "items", party: "customer",   flag: "is_sales_item" },
	"Sales Invoice":           { table: "items", party: "customer",   flag: "is_sales_item" },
	"Supplier Quotation":      { table: "items", party: "supplier",   flag: "is_purchase_item" },
	"Purchase Order":          { table: "items", party: "supplier",   flag: "is_purchase_item" },
	"Purchase Receipt":        { table: "items", party: "supplier",   flag: "is_purchase_item" },
	"Purchase Invoice":        { table: "items", party: "supplier",   flag: "is_purchase_item" },
	"Subcontracting Order":    { table: "items", party: "supplier",   flag: "is_purchase_item" },
	"Subcontracting Receipt":  { table: "items", party: "supplier",   flag: "is_purchase_item" },
	"Material Request":        { table: "items" },
	"Stock Entry":             { table: "items" },
	"Stock Reconciliation":    { table: "items" },
	"BOM":                     { table: "items" },
	"Work Order":              { table: "required_items" },
};

function ib_apply_item_query(frm, cfg) {
	if (!frm.fields_dict || !frm.fields_dict[cfg.table]) return;
	frm.set_query("item_code", cfg.table, () => {
		const filters = {};
		// item_query reads customer / supplier to apply Party Specific Item
		// rules, then drops the key before it reaches the SQL filters.
		if (cfg.party && frm.doc[cfg.party]) {
			filters[cfg.party === "supplier" ? "supplier" : "customer"] = frm.doc[cfg.party];
		}
		if (cfg.flag) filters[cfg.flag] = 1;
		return { query: IB_ITEM_QUERY, filters, page_length: 30 };
	});
}

Object.entries(IB_ITEM_FORMS).forEach(([doctype, cfg]) => {
	frappe.ui.form.on(doctype, {
		refresh(frm) {
			ib_apply_item_query(frm, cfg);
		},
		// A form opened straight from a route renders before some controllers
		// finish their own setup; re-applying here costs nothing and closes
		// the gap if one of them lands late.
		onload_post_render(frm) {
			ib_apply_item_query(frm, cfg);
		},
	});
});
