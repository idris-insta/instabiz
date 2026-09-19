frappe.query_reports["IB Statutory Returns"] = {
	filters: [
		{ fieldname: "return_type", label: __("Return"), fieldtype: "Select", options: "PF ECR\nESIC", default: "PF ECR", reqd: 1 },
		{ fieldname: "month", label: __("Salary Month"), fieldtype: "Date", default: frappe.datetime.add_months(frappe.datetime.month_start(), -1), reqd: 1 },
	],
	onload(report) {
		report.page.add_inner_button(__("Download"), () => {
			const v = report.get_values();
			const rows = (report.data || []).filter((r) => r.employee);
			if (!rows.length) return frappe.msgprint(__("Nothing for this month."));
			let content, name, type;
			if (v.return_type === "PF ECR") {
				content = rows.map((r) => [r.uan || "", (r.name || "").toUpperCase(), r.gross, r.epf_wages, r.eps_wages, r.edli_wages,
					r.epf_ee, r.eps, r.diff, r.ncp, 0].join("#~#")).join("\n");
				name = `ECR_${v.month}.txt`;
				type = "text/plain";
			} else {
				const head = "IP Number,IP Name,No of Days for which wages paid/payable during the month,Total Monthly Wages,Reason Code for Zero workings days,Last Working Day";
				content = head + "\n" + rows.map((r) => [r.ip || "", `"${(r.name || "").replace(/"/g, "")}"`, r.days, r.wages, r.days ? "" : 0, ""].join(",")).join("\n");
				name = `ESIC_${v.month}.csv`;
				type = "text/csv";
			}
			const a = document.createElement("a");
			a.href = URL.createObjectURL(new Blob([content], { type }));
			a.download = name;
			a.click();
		}).addClass("btn-primary");
	},
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "missing" && data && data.missing) value = `<span class="text-danger">${value}</span>`;
		return value;
	},
};
