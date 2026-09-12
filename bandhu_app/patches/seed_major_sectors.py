import frappe

# rename_doc, not delete and recreate, so linked patients follow.
MAJOR_SECTORS = ["Construction", "Plywood", "Fish processing", "Waste collection", "Manufacturing"]
RENAMES = {
	"Seafood Processing": "Fish processing",
	"Plywood and Timber": "Plywood",
}


def execute():
	if not frappe.db.has_column("Sectors", "is_major_sector"):
		return

	for old_name, new_name in RENAMES.items():
		if frappe.db.exists("Sectors", old_name) and not frappe.db.exists("Sectors", new_name):
			frappe.rename_doc("Sectors", old_name, new_name)

	for sector_name in MAJOR_SECTORS:
		if frappe.db.exists("Sectors", sector_name):
			frappe.db.set_value("Sectors", sector_name, "is_major_sector", 1)
		else:
			frappe.get_doc(
				{
					"doctype": "Sectors",
					"employment_sector_name": sector_name,
					"is_major_sector": 1,
				}
			).insert(ignore_permissions=True)

	if not frappe.db.exists("Sectors", "Other"):
		frappe.get_doc({"doctype": "Sectors", "employment_sector_name": "Other"}).insert(
			ignore_permissions=True
		)
