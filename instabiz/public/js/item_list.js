// "Generate Missing Barcodes" — one-shot backfill giving every enabled Item
// with no barcode a Code128 barcode equal to its own item_code (the key
// ib-stock-scan / IB Container Import already expect). Stock Manager /
// System Manager only. Runs a dry-run first, confirms the count, then writes.
frappe.listview_settings["Item"] = {
	onload(listview) {
		const allowed =
			frappe.user.has_role("Stock Manager") || frappe.user.has_role("System Manager");
		if (!allowed) return;

		listview.page.add_inner_button(__("Generate Missing Barcodes"), () => {
			frappe.call({
				method: "instabiz.overrides.item.backfill_missing_barcodes",
				args: { dry_run: 1 },
				freeze: true,
				freeze_message: __("Checking items…"),
				callback: (r) => {
					const d = r.message || {};
					if (!d.count) {
						frappe.msgprint(__("Every enabled Item already has a barcode."));
						return;
					}
					frappe.confirm(
						__(
							"{0} enabled Items have no barcode. Give each one a Code128 barcode equal to its item code?",
							[d.count],
						),
						() => {
							frappe.call({
								method: "instabiz.overrides.item.backfill_missing_barcodes",
								args: { dry_run: 0 },
								freeze: true,
								freeze_message: __("Generating barcodes…"),
								callback: (res) => {
									const out = res.message || {};
									let msg = __("{0} barcodes created.", [out.created || 0]);
									if (out.failed_count) {
										msg +=
											"<br>" +
											__("{0} failed:", [out.failed_count]) +
											"<br>" +
											(out.failed || [])
												.map((f) => `${f.item}: ${f.error}`)
												.join("<br>");
									}
									frappe.msgprint({
										title: __("Barcode Backfill"),
										message: msg,
										indicator: out.failed_count ? "orange" : "green",
									});
									listview.refresh();
								},
							});
						},
					);
				},
			});
		});
	},
};
