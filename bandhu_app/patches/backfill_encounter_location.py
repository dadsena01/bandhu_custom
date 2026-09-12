import frappe

LOCATION_FIELDS = ("lsg", "district", "state")


def execute():
	encounters = frappe.get_all(
		"Patient Encounter",
		filters={"custom_location": ["is", "not set"], "custom_clinic_session": ["is", "set"]},
		fields=["name", "custom_clinic_session"],
	)
	if not encounters:
		return

	sessions = {row.custom_clinic_session for row in encounters}
	site_by_session = dict(
		frappe.get_all(
			"Bandhu Clinic Session",
			filters={"name": ["in", list(sessions)]},
			fields=["name", "site"],
			as_list=True,
		)
	)
	location_by_site = dict(
		frappe.get_all(
			"Site",
			filters={"name": ["in", list({site for site in site_by_session.values() if site})]},
			fields=["name", "location"],
			as_list=True,
		)
	)
	details_by_location = {
		row.name: row
		for row in frappe.get_all(
			"Bandhu Location",
			filters={"name": ["in", list({loc for loc in location_by_site.values() if loc})]},
			fields=["name", *LOCATION_FIELDS],
		)
	}

	for row in encounters:
		location = location_by_site.get(site_by_session.get(row.custom_clinic_session))
		details = details_by_location.get(location)
		if not details:
			continue

		# db.set_value, not save, so completed visits do not re-run workflow hooks.
		frappe.db.set_value(
			"Patient Encounter",
			row.name,
			{
				"custom_location": location,
				**{f"custom_{field}": details.get(field) for field in LOCATION_FIELDS},
			},
			update_modified=False,
		)
