/**
 * Todo52 — soft UI hints for vehicle + outbound scan on Delivery Note / Gate Pass / SI.
 * Enforced server-side in gate_locks.py (before_submit throw for vehicle; soft warn for scan).
 *
 * Prefer Client Script ensure from ensure_todo52_setup / deploy; doctype_js optional.
 */
frappe.ui.form.on("Delivery Note", {
	refresh(frm) {
		_todo52_hint(frm);
	},
	validate(frm) {
		_todo52_client_soft_scan(frm);
	},
});

frappe.ui.form.on("IB Gate Pass", {
	refresh(frm) {
		_todo52_hint(frm);
	},
	validate(frm) {
		_todo52_client_soft_scan(frm);
	},
});

frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		_todo52_hint(frm);
	},
});

function _todo52_vehicle_field(frm) {
	const cands = [
		"custom_vehicle_no",
		"vehicle_no",
		"custom_vehicle_number",
		"vehicle_number",
		"vehicle",
	];
	for (const f of cands) {
		if (frm.fields_dict[f]) return f;
	}
	return null;
}

function _todo52_scan_field(frm) {
	const cands = [
		"custom_scan_units",
		"custom_scanned_serials",
		"custom_carton_serials",
		"scanned_serials",
		"scan_units",
	];
	for (const f of cands) {
		if (frm.fields_dict[f]) return f;
	}
	return null;
}

function _todo52_hint(frm) {
	const vf = _todo52_vehicle_field(frm);
	if (vf && frm.fields_dict[vf] && frm.fields_dict[vf].df) {
		frm.fields_dict[vf].df.description =
			__("Compulsory before submit (Todo52). Container No stays optional.");
		frm.refresh_field(vf);
	}
}

function _todo52_client_soft_scan(frm) {
	if (!["Delivery Note", "IB Gate Pass"].includes(frm.doctype)) return;
	const sf = _todo52_scan_field(frm);
	if (!sf) return;
	const raw = (frm.doc[sf] || "").toString().trim();
	if (raw) return;
	frappe.show_alert({
		message: __(
			"Outbound carton scan checklist is empty — soft warning only (submit still allowed)."
		),
		indicator: "orange",
	});
}
