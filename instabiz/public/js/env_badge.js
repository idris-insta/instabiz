// ── Environment badge ──────────────────────────────────────────────────────
// Purely client-side (same code/assets deploy to both dev and prod - there is
// no server-side config difference to key off other than the real hostname).
// This session hit several near-mix-ups between the dev box and the real
// production site (instabizerp.com) while working across both in parallel -
// this badge exists so it is visually unmistakable which one is currently
// open: a fixed top-right pill (PRØD in alert red, DËV in blue) plus a
// matching browser-tab-title prefix so it's visible even from a background
// tab. Never touches any doctype/business logic - display only.
(function () {
	const host = window.location.hostname || "";
	const isProd = /instabizerp\.com$/i.test(host);
	const label = isProd ? "PRØD" : "DËV";
	const bg = isProd ? "#c0392b" : "#2563eb";

	if (frappe.utils && frappe.utils.set_title_prefix) {
		frappe.utils.set_title_prefix(`[${label}]`);
	}

	function inject() {
		if (document.getElementById("ib-env-badge")) return;
		const el = document.createElement("div");
		el.id = "ib-env-badge";
		el.textContent = label;
		el.title = isProd
			? "LIVE production site - instabizerp.com"
			: "Development site";
		Object.assign(el.style, {
			position: "fixed",
			top: "6px",
			right: "8px",
			zIndex: 100000,
			background: bg,
			color: "#fff",
			fontFamily: "Arial, sans-serif",
			fontSize: "11px",
			fontWeight: "700",
			letterSpacing: "0.5px",
			padding: "3px 9px",
			borderRadius: "10px",
			boxShadow: "0 1px 4px rgba(0,0,0,.35)",
			pointerEvents: "none",
			userSelect: "none",
		});
		document.body.appendChild(el);
	}

	if (document.body) inject();
	else document.addEventListener("DOMContentLoaded", inject);
})();
