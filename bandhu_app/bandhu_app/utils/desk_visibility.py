import frappe

# Other apps ship their own Desktop Icons for the /desk grid with no role restriction, so
# every Desk user sees ERPNext's Accounting/Buying/Stock and friends whether or not they
# mean anything to a nurse. We don't own those apps' fixtures (never edit apps/frappe,
# apps/erpnext — lost on bench update), and each app's own `bench migrate` re-syncs its
# icons from its own JSON on every run, silently wiping a restriction set directly on the
# doc. Running this again after every migrate, via the after_migrate hook, is what makes it
# stick.
#
# Matched by rule rather than by name: an earlier hardcoded list ("Framework", "Quality",
# "Marley Health") missed every ERPNext icon and named one that does not exist on this
# site at all. Restricting the top-level icons is enough — children render under their
# parent, so hiding the parent hides the branch.
ALLOWED_ROLES = ["System Manager"]


def restrict_other_app_desktop_icons():
	"""Hide other apps' top-level desk icons from everyone but System Manager."""
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
	app_title = frappe.get_hooks("app_title", app_name="bandhu_app")[0]
	stale_app_tile = frappe.db.get_value("Desktop Icon", {"label": app_title, "icon_type": "App"}, "name")
	if stale_app_tile:
		frappe.delete_doc("Desktop Icon", stale_app_tile, ignore_permissions=True)

	workspaces = frappe.get_all(
		"Workspace", filters={"module": "Bandhu App", "public": 1}, fields=["name", "icon"]
	)
	for workspace in workspaces:
		icon_name = frappe.db.get_value("Desktop Icon", {"link_to": workspace.name, "icon_type": "Link"})
		if not icon_name:
			continue

		roles = frappe.get_all(
			"Has Role", filters={"parenttype": "Workspace", "parent": workspace.name}, pluck="role"
		)
		icon = frappe.get_doc("Desktop Icon", icon_name)
		roles_match = {row.role for row in icon.roles} == set(roles)
		icon_matches = icon.icon == workspace.icon
		if roles_match and icon_matches:
			continue

		icon.set("roles", [{"role": role} for role in sorted(roles)])
		icon.icon = workspace.icon
		icon.save(ignore_permissions=True)
