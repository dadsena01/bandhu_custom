import frappe

# Other apps re-sync their desk icons on every migrate, so after_migrate restricts them again.
# Administrator, not System Manager, because CMID's own admins hold System Manager.
ALLOWED_ROLES = ["Administrator"]

# Desktop Icon.icon_image renders an <img>; Workspace.icon only takes sprite names.
DESK_ICON_IMAGE_BY_WORKSPACE = {
	"CAD": "/assets/bandhu_app/images/desk_icons/cad.svg",
	"Doctor": "/assets/bandhu_app/images/desk_icons/doctor.svg",
	"Nurse": "/assets/bandhu_app/images/desk_icons/nurse.svg",
	"Admin": "/assets/bandhu_app/images/desk_icons/admin.svg",
}


def restrict_other_app_desktop_icons():
	# Desktop Icon.app is blank on our own icons, so match on link_to instead.
	bandhu_workspaces = frappe.get_all("Workspace", filters={"module": "Bandhu App"}, pluck="name")
	foreign_icons = frappe.get_all(
		"Desktop Icon",
		filters={
			"parent_icon": ["in", ["", None]],
			"link_to": ["not in", bandhu_workspaces or [""]],
		},
		pluck="name",
	)

	for icon_name in foreign_icons:
		icon = frappe.get_doc("Desktop Icon", icon_name)
		if {row.role for row in icon.roles} == set(ALLOWED_ROLES):
			continue

		icon.set("roles", [{"role": role} for role in ALLOWED_ROLES])
		try:
			icon.save()
		except Exception as error:
			# Another app's icon can point at a workspace that no longer exists (erpnext ships
			# "Subcontracting" that way here), and its save fails link validation. That is not
			# ours to repair, and it must not stop the icons after it in the list from being
			# hidden — which is exactly what happened before this was caught.
			frappe.log_error(title="Could not restrict desktop icon", message=f"{icon_name}: {error}")


def sync_bandhu_desktop_icons():
	"""Copy each Bandhu workspace's roles and icon onto its Desktop Icon, which Frappe seeds only once."""
	app_title = frappe.get_hooks("app_title", app_name="bandhu_app")[0]
	stale_app_tile = frappe.db.get_value("Desktop Icon", {"label": app_title, "icon_type": "App"}, "name")
	if stale_app_tile:
		frappe.delete_doc("Desktop Icon", stale_app_tile, ignore_permissions=True)

	# Workspace.app is unreliable on hand-made records; module comes from the fixture.
	workspaces = frappe.get_all(
		"Workspace", filters={"module": "Bandhu App", "public": 1}, fields=["name", "icon"]
	)
	any_icon_changed = False
	for workspace in workspaces:
		icon_name = frappe.db.get_value("Desktop Icon", {"link_to": workspace.name, "icon_type": "Link"})
		if not icon_name:
			continue

		roles = frappe.get_all(
			"Has Role", filters={"parenttype": "Workspace", "parent": workspace.name}, pluck="role"
		)
		icon = frappe.get_doc("Desktop Icon", icon_name)
		image_path = DESK_ICON_IMAGE_BY_WORKSPACE.get(workspace.name)
		roles_match = {row.role for row in icon.roles} == set(roles)
		icon_matches = icon.icon == workspace.icon
		image_matches = not image_path or icon.icon_image == image_path
		if roles_match and icon_matches and image_matches:
			continue

		icon.set("roles", [{"role": role} for role in sorted(roles)])
		icon.icon = workspace.icon
		if image_path:
			icon.icon_image = image_path
		icon.save(ignore_permissions=True)
		any_icon_changed = True

	if any_icon_changed:
		# Desktop Icon.on_update clears the shared cache only for standard icons.
		frappe.cache.delete_key("desktop_icons")
