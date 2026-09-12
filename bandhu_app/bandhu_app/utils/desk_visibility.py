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
# site at all. Restricting the top-level icons is enough — get_desktop_icons drops any child
# whose parent did not pass its own permission check, so hiding the parent hides the branch.
#
# Administrator rather than System Manager: CMID's own administrators hold System Manager, and
# an ERPNext install puts twenty tiles they never open (Accounting, Buying, Manufacturing,
# Selling, Stock, Subcontracting, Quality, Assets, Projects) on the same grid as the four
# screens they do. The built-in Administrator login is the only holder of this role, so every
# module stays one click away for us without being in their way.
ALLOWED_ROLES = ["Administrator"]

# Custom desk-icon artwork, keyed by Workspace name. CAD/Doctor/Nurse get a role-colored
# glyph — plain circle, no name, no photo, so the same image is correct for every
# practitioner in that role. Admin isn't a role, so it gets the same neutral badge shape in a
# plain grey, not a role color. Frappe's own Icon fieldtype only picks from its bundled sprite set;
# Desktop Icon.icon_image (Attach) is the one field that renders a plain <img> instead
# (frappe/public/js/frappe/ui/desktop_icon.html), which is why this targets Desktop Icon
# and not Workspace.icon.
DESK_ICON_IMAGE_BY_WORKSPACE = {
	"CAD": "/assets/bandhu_app/images/desk_icons/cad.svg",
	"Doctor": "/assets/bandhu_app/images/desk_icons/doctor.svg",
	"Nurse": "/assets/bandhu_app/images/desk_icons/nurse.svg",
	"Admin": "/assets/bandhu_app/images/desk_icons/admin.svg",
}


def restrict_other_app_desktop_icons():
	"""Hide other apps' top-level desk icons from everyone but Administrator."""
	# Desktop Icon.app carries the exact same landmine sync_bandhu_desktop_icons already
	# works around on Workspace.app: it is only as good as whatever app was active in the
	# Desk UI at creation time, and every one of this app's own 9 icons has it blank. Filtering
	# on it here undid sync_bandhu_desktop_icons's own fix on every single after_migrate run —
	# CAD, Doctor and Nurse's tiles got locked back to System Manager only immediately after
	# being unlocked. link_to against this app's own workspace names is the reliable check.
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
	"""Give each of our workspace's own Desktop Icon the roles and icon its Workspace has.

	Frappe seeds one `Desktop Icon` (icon_type Link) per public workspace via
	`create_desktop_icons_from_workspace`, but that seeding only ever runs once, at the
	moment the Desktop Icon row is first created — it never re-copies the workspace's own
	`roles` table or `icon` afterward. Every one of them had roles set to System Manager
	only, so CAD/Doctor/Nurse landed on `/desk` with no tile at all for their own board.
	CAD's workspace had no `icon` set at the time its Desktop Icon was seeded, and setting
	one on the Workspace later (`cad.json`) never reached the frozen Desktop Icon row — the
	tile kept rendering blank until this started also comparing `icon`.

	An earlier version of this function tried to work around that with a single shared "App"
	tile instead of fixing the per-icon roles — icon_type "App" only knows how to open a
	submenu of `child_icons` or fall through to Frappe's own "Icon is not correctly
	configured" message, and no children were ever created, so every CAD/Doctor/Nurse user
	hit that dead end. Deleting that tile here cleans up the leftover row from before this fix.
	"""
	app_title = frappe.get_hooks("app_title", app_name="bandhu_app")[0]
	stale_app_tile = frappe.db.get_value("Desktop Icon", {"label": app_title, "icon_type": "App"}, "name")
	if stale_app_tile:
		frappe.delete_doc("Desktop Icon", stale_app_tile, ignore_permissions=True)

	# `app` on Workspace is only as good as whatever app was active in the Desk UI at the
	# moment someone created the record by hand — Doctor, Nurse and four others were created
	# with `app` left on "frappe", so filtering on it silently dropped them from this loop.
	# `module` comes from each workspace's own fixture and is correct for all of them.
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
		# Desktop Icon.on_update only busts the *global* "desktop_icons" cache for
		# standard=1 icons (frappe/desk/doctype/desktop_icon/desktop_icon.py) — for
		# everyone else, including ours, it clears only the saving icon's own `owner`
		# from the per-user cache. That leaves every other viewer's cached copy stale:
		# a CAD/Doctor/Nurse tile change was invisible to Administrator's own `/desk`
		# until they happened to also be the `owner`. Clearing the whole hash matches
		# what Frappe itself does for standard icons.
		frappe.cache.delete_key("desktop_icons")
