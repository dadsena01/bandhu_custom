import frappe


def execute():
	"""`site_name` is a new fetch field, and fetch_from only fires on save — every existing
	camp would keep showing the raw `SITE-0002` id as its title until someone edited it."""
	sessions = frappe.get_all(
		"Bandhu Clinic Session", filters={"site": ["is", "set"]}, fields=["name", "site"]
	)
	if not sessions:
		return

	site_names = dict(
		frappe.get_all(
			"Site",
			filters={"name": ["in", {session.site for session in sessions}]},
			fields=["name", "site_name"],
			as_list=True,
		)
	)

	for session in sessions:
		site_name = site_names.get(session.site)
		if site_name:
			frappe.db.set_value(
				"Bandhu Clinic Session", session.name, "site_name", site_name, update_modified=False
			)
