// Print button on every row of every list whose documents can be printed
// (Salary Slip, Payment Entry, Journal Entry, Stock Entry, Customer, Employee,
// IB Gate Pass, ...) — same as the print icon inside the document. Lists that
// already set their own row button (Quotation, Sales Order, Delivery Note, ...)
// keep it. Opens the print preview in the document's default print format.
(function () {
	function print_format(meta) {
		if (meta.default_print_format) return meta.default_print_format;
		const custom = (frappe.meta.get_print_formats(meta.name) || []).filter((f) => f !== "Standard");
		return custom[0] || "Standard";
	}

	function printable(doctype) {
		const meta = frappe.get_meta(doctype);
		if (!meta || meta.istable || meta.issingle || meta.is_virtual || !frappe.model.can_print(doctype)) return null;
		return meta;
	}

	function patch() {
		const LV = frappe.views && frappe.views.ListView;
		if (!LV || LV.prototype.__ib_row_print) return;
		LV.prototype.__ib_row_print = true;
		const orig = LV.prototype.setup_defaults;
		LV.prototype.setup_defaults = function () {
			const out = orig.apply(this, arguments);
			const add = () => {
				if (this.settings.button) return;
				const meta = printable(this.doctype);
				if (!meta) return;
				this.settings.button = {
					show: (doc) => doc.docstatus !== 2,
					get_label: () => __("Print"),
					get_description: () => __("Print Preview"),
					action: (doc) => {
						window.open(
							"/printview?doctype=" + encodeURIComponent(this.doctype)
							+ "&name=" + encodeURIComponent(doc.name)
							+ "&format=" + encodeURIComponent(print_format(meta))
							+ "&trigger_print=0",
							"_blank"
						);
					},
				};
			};
			return out && out.then ? out.then((r) => { add(); return r; }) : (add(), out);
		};
	}

	patch();
	$(document).on("app_ready", patch);
})();
