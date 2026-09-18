frappe.query_reports["IB Collections Priority"] = {
	filters: [
		{ fieldname: "territory", label: __("State"), fieldtype: "Link", options: "Territory" },
		{
			fieldname: "sales_person_user",
			label: __("Sales Person"),
			fieldtype: "Link",
			options: "User",
			get_query() { return { filters: { enabled: 1 } }; },
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "oldest_age") {
			const age = data.oldest_age || 0;
			const cls = age > 90 ? "red" : age > 60 ? "orange" : age > 30 ? "yellow" : "green";
			return `<span class="indicator-pill ${cls} no-indicator-dot">${value}</span>`;
		}
		if (column.fieldname === "health" && data.health) {
			const cls = { Red: "red", Amber: "orange", Green: "green" }[data.health] || "gray";
			return `<span class="indicator-pill ${cls} no-indicator-dot">${frappe.utils.escape_html(data.health)}</span>`;
		}
		if (column.fieldname === "reminder" && data.mobile) {
			let phone = String(data.mobile).replace(/\D/g, "");
			if (phone.length === 10) phone = "91" + phone;
			const amt = format_currency(data.outstanding, "INR", 0);
			const msg =
				`Dear ${data.customer_name || data.customer}, a gentle reminder that ${amt} is outstanding ` +
				`with Instabiz Solutions (oldest item ${data.oldest_age} days). ` +
				`Could you please share the payment date? Thank you.`;
			const url = `https://wa.me/${phone}?text=${encodeURIComponent(msg)}`;
			return `<a href="${url}" target="_blank" rel="noopener">${__("Send reminder")}</a>`;
		}
		return value;
	},
};
