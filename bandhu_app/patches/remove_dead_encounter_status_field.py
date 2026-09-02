import frappe


def execute():
	"""custom_encounter_status was never written by app code — only its own Select default
	filled it, so all 41 live encounters read "Registered" regardless of their real state.
	The field definition is already gone from custom/patient_encounter.json; this drops the
	now-orphaned Custom Field record and the column itself."""
	field_name = "Patient Encounter-custom_encounter_status"
	if frappe.db.exists("Custom Field", field_name):
		frappe.delete_doc("Custom Field", field_name, ignore_permissions=True)

	# Frappe's own schema sync only ever adds columns, never drops one — deleting the
	# Custom Field record alone leaves the column orphaned in the table indefinitely.
	# has_column reads a Redis-cached column list that survives across processes, so a
	# stale cache from before this patch's own drop would otherwise re-run the DDL and
	# throw on a second pass.
	frappe.clear_cache(doctype="Patient Encounter")
	if frappe.db.has_column("Patient Encounter", "custom_encounter_status"):
		frappe.db.sql_ddl("alter table `tabPatient Encounter` drop column `custom_encounter_status`")
		frappe.clear_cache(doctype="Patient Encounter")
