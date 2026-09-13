import frappe
from frappe.query_builder import Case
from frappe.query_builder.functions import Coalesce, Count, Sum
from frappe.utils import create_batch, cstr

COMPLETED_STATE = "Completed"

# MariaDB and Postgres both choke on very long IN (...) lists, so every session or
# patient list is fed to the database in slices.
BATCH_SIZE = 500


def count_encounters(session_names: list) -> dict:
	if not session_names:
		return {}

	encounter = frappe.qb.DocType("Patient Encounter")
	completed = Case().when(encounter.custom_workflow_state == COMPLETED_STATE, 1).else_(0)

	counts = {}
	for batch in create_batch(session_names, BATCH_SIZE):
		rows = (
			frappe.qb.from_(encounter)
			.select(
				encounter.custom_clinic_session.as_("session"),
				# One patient seen twice in a camp is one patient, not two.
				Count(encounter.patient).distinct().as_("patients"),
				Sum(completed).as_("completed"),
			)
			.where((encounter.docstatus < 2) & (encounter.custom_clinic_session.isin(batch)))
			.groupby(encounter.custom_clinic_session)
			.run(as_dict=True)
		)
		counts.update({row.session: row for row in rows})

	return counts


def count_new_patients(session_names: list) -> dict:
	"""A patient is new when this camp holds their first encounter anywhere in the system.

	First is decided on the clinical date, never on row-insert order: January's paper
	records back-entered in June must still make January the first visit and June's camp
	the repeat one.
	"""
	if not session_names:
		return {}

	patients = find_session_patients(session_names)
	if not patients:
		return {}

	first_session_by_patient = find_first_encounter_sessions(patients)

	wanted = set(session_names)
	counts = {}
	for session in first_session_by_patient.values():
		if session in wanted:
			counts[session] = counts.get(session, 0) + 1

	return counts


def find_session_patients(session_names: list) -> set:
	encounter = frappe.qb.DocType("Patient Encounter")

	patients = set()
	for batch in create_batch(session_names, BATCH_SIZE):
		rows = (
			frappe.qb.from_(encounter)
			.select(encounter.patient)
			.distinct()
			.where(
				(encounter.docstatus < 2)
				& (encounter.custom_clinic_session.isin(batch))
				& (Coalesce(encounter.patient, "") != "")
			)
			.run(as_dict=True)
		)
		patients.update(row.patient for row in rows)

	return patients


def find_first_encounter_sessions(patients: set) -> dict:
	"""The camp holding each patient's earliest encounter, over their whole history.

	Ranking in Python rather than SQL keeps this two flat queries instead of the
	per-row correlated subquery it used to be.
	"""
	encounter = frappe.qb.DocType("Patient Encounter")

	first_by_patient = {}
	for batch in create_batch(list(patients), BATCH_SIZE):
		rows = (
			frappe.qb.from_(encounter)
			.select(
				encounter.name,
				encounter.patient,
				encounter.encounter_date,
				encounter.custom_clinic_session.as_("session"),
			)
			.where((encounter.docstatus < 2) & (encounter.patient.isin(batch)))
			.run(as_dict=True)
		)

		for row in rows:
			# `name` is a string here but autoincrement naming would hand back an int,
			# and an undated encounter must never outrank a dated one.
			rank = (row.encounter_date is None, row.encounter_date, cstr(row.name))
			earliest = first_by_patient.get(row.patient)
			if not earliest or rank < earliest[0]:
				first_by_patient[row.patient] = (rank, row.session)

	return {patient: session for patient, (rank, session) in first_by_patient.items()}


def count_tests(session_names: list) -> dict:
	"""Tests live on the encounter's `custom_test_instructions` child table, not on the
	`Test Result` doctype — nothing in the clinic loop writes that doctype."""
	if not session_names:
		return {}

	test = frappe.qb.DocType("Test Instructions")
	encounter = frappe.qb.DocType("Patient Encounter")
	done = Case().when(Coalesce(test.result_type, "") != "", 1).else_(0)

	counts = {}
	for batch in create_batch(session_names, BATCH_SIZE):
		rows = (
			frappe.qb.from_(test)
			.inner_join(encounter)
			.on(encounter.name == test.parent)
			.select(
				encounter.custom_clinic_session.as_("session"),
				Count(test.name).as_("ordered"),
				Sum(done).as_("done"),
			)
			.where(
				(test.parenttype == "Patient Encounter")
				& (encounter.docstatus < 2)
				& (encounter.custom_clinic_session.isin(batch))
			)
			.groupby(encounter.custom_clinic_session)
			.run(as_dict=True)
		)
		counts.update({row.session: row for row in rows})

	return counts


def count_medicines(session_names: list) -> dict:
	if not session_names:
		return {}

	prescription = frappe.qb.DocType("Prescription")
	encounter = frappe.qb.DocType("Patient Encounter")
	dispensed = Case().when(prescription.dispensed == 1, 1).else_(0)

	counts = {}
	for batch in create_batch(session_names, BATCH_SIZE):
		rows = (
			frappe.qb.from_(prescription)
			.inner_join(encounter)
			.on(encounter.name == prescription.parent)
			.select(
				encounter.custom_clinic_session.as_("session"),
				Count(prescription.name).as_("prescribed"),
				Sum(dispensed).as_("dispensed"),
			)
			.where(
				(prescription.parenttype == "Patient Encounter")
				& (encounter.docstatus < 2)
				& (encounter.custom_clinic_session.isin(batch))
			)
			.groupby(encounter.custom_clinic_session)
			.run(as_dict=True)
		)
		counts.update({row.session: row for row in rows})

	return counts
