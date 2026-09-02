import frappe

# The CAD registration form now shows quick-tap tabs for these sectors, per CMID's
# explicit list, and reveals a full picker only for "Other". The pre-existing master
# used different wording ("Seafood Processing", "Plywood and Timber") that never
# matched what the client asked for on the tabs, so those two are renamed in place
# (rename_doc, not delete+recreate) to carry forward any patient already linked to them.
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

	# "Other" is a real, selectable Sectors record (not a UI-only placeholder) so that
	# tapping the form's "Other" tab still stores a valid Link value; it is deliberately
	# not a major sector, since the form always appends it as the last tab regardless.
	if not frappe.db.exists("Sectors", "Other"):
		frappe.get_doc({"doctype": "Sectors", "employment_sector_name": "Other"}).insert(
			ignore_permissions=True
		)
