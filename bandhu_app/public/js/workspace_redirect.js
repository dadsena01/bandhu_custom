// Clicking the CAD / Doctor / Nurse workspace icon in the Desk sidebar
// used to land on the generic Workspace shortcut screen (Patient/Vehicle
// list shortcuts), forcing field staff to hunt for the actual working
// page. Bounce straight into the real Desk Page instead.
const WORKSPACE_REDIRECTS = {
	cad: { page: "cad-form", role: "Clinic Assistant cum Driver" },
	doctor: { page: "doctor-form", role: "Doctor" },
	nurse: { page: "nurse-form", role: "Nurse" },
};

frappe.router.on("change", () => {
	const route = frappe.get_route();
	if (route[0] !== "Workspaces") {
		return;
	}

	const redirect = WORKSPACE_REDIRECTS[frappe.router.slug(route[1] || "")];

	// Only bounce the staff whose daily work lives on that page. Redirecting everyone left the
	// workspace configs unreachable for the System Manager who has to maintain them.
	if (!redirect || !frappe.user_roles.includes(redirect.role)) {
		return;
	}

	// replace_route so the workspace never lands in history -- otherwise Back from the working
	// page returns to the workspace, which immediately redirects forward again and the gesture
	// looks frozen (frappe/public/js/frappe/router.js:529-536).
	frappe.route_flags.replace_route = true;
	frappe.set_route(redirect.page);
});
