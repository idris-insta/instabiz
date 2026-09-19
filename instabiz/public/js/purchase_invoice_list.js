frappe.listview_settings["Purchase Invoice"] = {
	button: {
		show: (doc) => doc.status !== "Cancelled",
		get_label: () => __("Print"),
		get_description: () => __("Print Preview"),
		action(doc) {
			window.open(
				"/printview?doctype=Purchase%20Invoice&name=" + encodeURIComponent(doc.name) +
				"&format=IB%20Purchase%20Invoice&no_letterhead=1&letterhead=No%20Letterhead&settings=%7B%7D",
				"_blank"
			);
		},
	},

	get_indicator(doc) {
		const map = {
			Draft:                "red",
			Unpaid:               "orange",
			Overdue:              "red",
			Paid:                 "green",
			"Return Issued":      "grey",
			"Debit Note Issued":  "grey",
			Cancelled:            "red",
		};
		return [__(doc.status), map[doc.status] || "grey"];
	},

	formatters: {
		name(value, df, doc) {
			const date = frappe.datetime.str_to_user(
				(doc.creation || "").split(" ")[0]
			);
			return `<span title="${value}">${date ? date + "<br>" : ""}<strong>${value}</strong></span>`;
		},
	},

	onload(listview) {
		// Photo / PDF of a supplier bill → OCR → draft Purchase Invoice (IB Document Intake)
		listview.page.add_inner_button(__("Scan Bill"), () =>
			frappe.new_doc("IB Document Intake", { intake_type: "Purchase Invoice" }));
		ib_setup_list_print(listview, "Purchase Invoice");
		ib_hide_sidebar();
		ib_setup_list_autocomplete_filter(listview, "Purchase Invoice", "title", "Title");
		ib_setup_status_multiselect(listview, "Purchase Invoice", [
			"Draft", "Unpaid", "Overdue", "Paid", "Return Issued", "Debit Note Issued", "Cancelled",
		]);
		ib_setup_list_date_filter(listview, "Purchase Invoice", "posting_date", []);
		// Filter row order = column order. Live columns: Title, Status, Grand
		// Total, Outstanding Amount, Posting Date, ID (Grand Total / Outstanding
		// have no filter). Title's native filter was a plain text box — now an
		// autocomplete suggesting distinct title values (the supplier name).
		// The date-range control sits at the Posting Date slot. ID moves out of
		// Frappe's default first slot to sit last in the column-matched group.
		// Supplier/Company/Location aren't visible columns, so they trail after.
		ib_reorder_filter_row(listview, [
			$(".ib-purchase-invoice-title-filter"),
			$(".ib-purchase-invoice-status-multi-filter"),
			$(".ib-purchase-invoice-date-range-filter"),
			listview.page.fields_dict.name && listview.page.fields_dict.name.$wrapper,
			listview.page.fields_dict.supplier && listview.page.fields_dict.supplier.$wrapper,
			listview.page.fields_dict.company && listview.page.fields_dict.company.$wrapper,
			listview.page.fields_dict.custom_location && listview.page.fields_dict.custom_location.$wrapper,
		]);
		const _orig_render_list = listview.render_list.bind(listview);
		listview.render_list = function () {
			_orig_render_list();
			ib_disable_status_click_filter(listview);
		};
	},
};
