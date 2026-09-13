import frappe
from frappe import _

from bandhu_app.bandhu_app.utils.patient import attach_patient_display_fields

PATIENT_DETAIL_FIELDS = [
	"patient_name",
	"sex",
	"dob",
	"mobile",
	"custom_bandhu_id",
	"custom_abha_id",
	"custom_height_m",
	"custom_weight_kg",
	"custom_bmi",
	"custom_temperature",
	"custom_native_state",
	"custom_native_district",
	"custom_native_country",
	"custom_sector_of_employment",
	"custom_specify_employment_sector",
	"custom_name_of_company",
]

ENCOUNTER_LIST_FIELDS = [
	"name",
	"patient",
	"patient_name",
	"patient_age",
	"patient_sex",
	"encounter_date",
	"custom_workflow_state",
	"custom_chief_complaints",
	"custom_past_history",
	"custom_allergy_history",
	"custom_height",
	"custom_weight",
	"custom_bmi",
	"custom_temperature",
	"custom_pulse_rate",
	"custom_spo2",
	"custom_blood_pressure",
	"custom_has_referral",
]

ENCOUNTER_CLINICAL_TABLES = {
	"tests": ("Test Instructions", ["name", "test_name", "notes", "result_type", "result_value"]),
	"prescriptions": (
		"Prescription",
		[
			"name",
			"medicines",
			"dosage_frequency",
			"duration_days",
			"quantity",
			"instructions",
			"dispensed",
		],
	),
	"diagnosis": ("Bandhu Diagnosis", ["diagnosis_name", "notes"]),
}


def get_patient_details(patient: str) -> dict:
	if not frappe.db.exists("Patient", patient):
		frappe.throw(_("Patient not found."))
	return frappe.db.get_value("Patient", patient, PATIENT_DETAIL_FIELDS, as_dict=True)


def attach_test_shapes(tests: list) -> None:
	"""Carry each row's result shape and unit down from the Bandhu Test master.

	The boards need the shape to know whether a result is a measurement or an indicator, and
	the row itself cannot say: an ordered-but-untested row has no `result_type` at all.
	"""
	test_names = {test.test_name for test in tests if test.test_name}
	if not test_names:
		return

	masters = {
		master.name: master
		for master in frappe.get_all(
			"Bandhu Test",
			filters={"name": ["in", list(test_names)]},
			fields=["name", "result_shape", "unit"],
		)
	}

	for test in tests:
		master = masters.get(test.test_name)
		test.result_shape = master.result_shape if master else None
		test.unit = master.unit if master else None


def shared_test_note(tests: list) -> str | None:
	"""The single note that covers the whole test order, or None when the rows disagree.

	`order_test` stamps the doctor's one note onto every row it appends, so the boards would
	otherwise print the same sentence once per test. Reporting it here keeps the per-row notes
	intact for the rows that genuinely carry their own.
	"""
	if not tests:
		return None

	notes = {(test.get("notes") or "").strip() for test in tests}
	if len(notes) > 1:
		return None

	return notes.pop() or None


def get_clinical_details_by_encounter(encounter_names: list) -> dict:
	"""Tests, prescriptions and diagnosis for a whole queue in one query per child table.
	Row by row this was three queries a patient, on a camp board a nurse reloads all day."""
	if not encounter_names:
		return {}

	details = {name: {key: [] for key in ENCOUNTER_CLINICAL_TABLES} for name in encounter_names}

	for key, (child_doctype, fields) in ENCOUNTER_CLINICAL_TABLES.items():
		rows = frappe.get_all(
			child_doctype,
			# Prescription rows also hang off Bandhu Medication Dispense, so the parent name
			# alone can pull in another doctype's rows.
			filters={"parent": ["in", encounter_names], "parenttype": "Patient Encounter"},
			fields=["parent", *fields],
			order_by="parent asc, idx asc",
		)
		for row in rows:
			details[row.pop("parent")][key].append(row)

	attach_test_shapes([test for encounter in details.values() for test in encounter["tests"]])

	for encounter_details in details.values():
		encounter_details["shared_test_note"] = shared_test_note(encounter_details["tests"])

	return details


def get_session_encounters(clinic_session: str, workflow_state) -> list:
	encounters = frappe.get_all(
		"Patient Encounter",
		filters={
			"custom_clinic_session": clinic_session,
			# An encounter created outside the Bandhu forms has no workflow state at all.
			# A bare `!=` would drop it, but frappe wraps the operator in IFNULL — keep it
			# going through the query builder rather than hand-writing the comparison.
			"custom_workflow_state": workflow_state,
		},
		fields=ENCOUNTER_LIST_FIELDS,
		order_by="encounter_date desc, creation desc",
	)

	clinical_details = get_clinical_details_by_encounter([encounter.name for encounter in encounters])
	for encounter in encounters:
		encounter.update(clinical_details[encounter.name])

	return attach_patient_display_fields(encounters)
