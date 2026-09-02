import frappe
from frappe.utils import add_days, today

from bandhu_app.bandhu_app.utils.patient_encounter import (
	DEFAULT_APPOINTMENT_TYPE,
	seed_default_appointment_type,
)

# A fresh site has none of Clinic/Site/Unit/Bandhu Projects/Appointment Type/State. Every
# test class here calls this in setUpClass instead of assuming that data exists.


def ensure_baseline_fixtures() -> dict[str, str]:
	"""Idempotent: reuses what exists, creates only what's missing."""
	state = _get_or_create_state()
	location = _get_or_create_location(state)
	project = _get_or_create_project()
	clinic = _get_or_create_clinic(project)
	site = _get_or_create_site(location)
	unit = _get_or_create_unit()
	appointment_type = _get_or_create_appointment_type()
	doctor = _get_or_create_practitioner("Doctor")
	nurse = _get_or_create_practitioner("Nurse")
	driver = _get_or_create_practitioner("Clinic Assistant cum Driver")
	item = _get_or_create_item()
	# Needed so this survives a caller's own per-test frappe.db.rollback().
	frappe.db.commit()  # nosemgrep: frappe-manual-commit

	return {
		"state": state,
		"location": location,
		"project": project,
		"clinic": clinic,
		"site": site,
		"unit": unit,
		"appointment_type": appointment_type,
		"doctor": doctor,
		"nurse": nurse,
		"driver": driver,
		"item": item,
	}


def _first_or_none(doctype: str) -> str | None:
	existing = frappe.get_all(doctype, limit=1, pluck="name")
	return existing[0] if existing else None


def _get_or_create_state() -> str:
	return (
		_first_or_none("State")
		or frappe.get_doc(
			{"doctype": "State", "state_name": "Test Baseline State", "country": "India", "is_major_state": 1}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _get_or_create_location(state: str) -> str:
	existing = _first_or_none("Bandhu Location")
	if existing:
		return existing
	return (
		frappe.get_doc(
			{
				"doctype": "Bandhu Location",
				"location_name": "Test Baseline Location",
				"lsg": "Test Baseline LSG",
				"district": "Test Baseline District",
				"state": state,
				"lsg_numeric_code": "01",
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _get_or_create_project() -> str:
	existing = _first_or_none("Bandhu Projects")
	if existing:
		return existing
	return (
		frappe.get_doc(
			{
				"doctype": "Bandhu Projects",
				"project": "Test Baseline Project",
				"start_date": today(),
				"end_date": add_days(today(), 365),
				"status": "Active",
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _get_or_create_clinic(project: str) -> str:
	existing = _first_or_none("Clinic")
	if existing:
		return existing
	return (
		frappe.get_doc({"doctype": "Clinic", "clinic_name": "Test Baseline Clinic", "project": project})
		.insert(ignore_permissions=True)
		.name
	)


def _get_or_create_site(location: str) -> str:
	existing = _first_or_none("Site")
	if existing:
		return existing
	return (
		frappe.get_doc({"doctype": "Site", "site_name": "Test Baseline Site", "location": location})
		.insert(ignore_permissions=True)
		.name
	)


def _get_or_create_unit() -> str:
	existing = _first_or_none("Unit")
	if existing:
		return existing
	return (
		frappe.get_doc({"doctype": "Unit", "unit_name": "Test Baseline Unit", "unit_numeric_code": "1"})
		.insert(ignore_permissions=True)
		.name
	)


def _get_or_create_appointment_type() -> str:
	seed_default_appointment_type()
	return DEFAULT_APPOINTMENT_TYPE


def _get_or_create_item() -> str:
	existing = _first_or_none("Item")
	if existing:
		return existing

	item_group = (
		_first_or_none("Item Group")
		or frappe.get_doc(
			{"doctype": "Item Group", "item_group_name": "Test Baseline Item Group", "is_group": 0}
		)
		.insert(ignore_permissions=True)
		.name
	)

	uom = (
		_first_or_none("UOM")
		or frappe.get_doc({"doctype": "UOM", "uom_name": "Test Baseline Unit Of Measure"})
		.insert(ignore_permissions=True)
		.name
	)

	return (
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": "Test Baseline Medicine",
				"item_group": item_group,
				"stock_uom": uom,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _get_or_create_practitioner(custom_role: str) -> str:
	existing = frappe.get_all(
		"Healthcare Practitioner", filters={"custom_role": custom_role}, limit=1, pluck="name"
	)
	if existing:
		return existing[0]
	return (
		frappe.get_doc(
			{
				"doctype": "Healthcare Practitioner",
				"first_name": f"Test Baseline {custom_role}",
				"status": "Active",
				"custom_role": custom_role,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)
