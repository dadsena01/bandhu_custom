import frappe


def execute():
	"""fetch_from only fires on save, so fill site_name on existing sessions."""
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
