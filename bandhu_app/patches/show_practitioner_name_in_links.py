import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

DOCTYPE = "Healthcare Practitioner"
PROPERTY = "show_title_field_in_link"


def execute():
	"""Every Link to a practitioner rendered the id (`HLC-PRAC-2026-00004`) instead of the name.

	`Healthcare Practitioner` is autonamed from a naming series and declares
	`title_field: practitioner_name`, but the healthcare app never sets
	`show_title_field_in_link`, so Desk falls back to the id in link inputs, list
	columns and the link title cache. A scheduler assigning a doctor to a camp has
	nothing to verify against.

	Fixed with a Property Setter rather than by editing the healthcare app's JSON:
	files in other apps are overwritten on every `bench update`.
	"""
	if frappe.get_meta(DOCTYPE).get(PROPERTY):
		return

	if frappe.db.exists(
		"Property Setter", {"doc_type": DOCTYPE, "property": PROPERTY, "doctype_or_field": "DocType"}
	):
		return

	make_property_setter(DOCTYPE, None, PROPERTY, "1", "Check", for_doctype=True)
	frappe.clear_cache(doctype=DOCTYPE)
