// Per-user override (User default "custom_home_route", set via
// frappe.defaults.set_user_default) — blank for everyone except whoever
// explicitly needs a different landing page. Falls back to the user's own
// default_workspace (same field/slug logic Frappe's native router uses,
// see frappe/public/js/frappe/router.js) instead of a hardcoded workspace —
// a hardcoded '/app/instabiz' sent every non-Sales role into a workspace
// their role can't even see.
function _ib_home_route() {
    const defaults = frappe.boot && frappe.boot.user && frappe.boot.user.defaults;
    const override = defaults && defaults.custom_home_route;
    if (override) return override;
    const default_workspace = frappe.boot.user && frappe.boot.user.default_workspace;
    if (default_workspace && default_workspace.name) {
        return '/app/' + frappe.router.slug(default_workspace.name);
    }
    return '/app/selling';
}

frappe.router.on('change', () => {
    // If the user lands exactly on /app or #modules
    if (window.location.pathname === '/app/home' && !frappe.get_route_str()) {
        window.location.href = _ib_home_route();
    }
});

// Also fallback to a standard click event listener once the DOM is ready
$(document).ready(() => {
    $('body').on('click', '.app-logo', function(e) {
        e.preventDefault();
        window.location.href = _ib_home_route();
    });
});