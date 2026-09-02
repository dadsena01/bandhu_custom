# Copyright (c) 2026, CMID and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, flt, nowtime, today

from bandhu_app.bandhu_app.baseline_test_fixtures import ensure_baseline_fixtures
from bandhu_app.bandhu_app.page.nurse_form.nurse_form import (
	dispense_medicine,
	end_session,
	get_patient_registration_details,
	record_vitals,
	start_session,
	submit_test_results,
)

EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = []


class IntegrationTestNurseForm(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		baseline = ensure_baseline_fixtures()
		cls.clinic = baseline["clinic"]
		cls.site = baseline["site"]
		cls.project = baseline["project"]
		cls.appointment_type = baseline["appointment_type"]
		cls.item = baseline["item"]
		cls.gender = frappe.get_all("Gender", limit=1, pluck="name")[0]

		cls.nurse_practitioner = cls._make_practitioner("Test Nurse Alpha", "Nurse")
		cls.other_practitioner = cls._make_practitioner("Test Nurse Beta", "Nurse")

		cls.nurse_user = cls._make_user("test.nurse.alpha@bandhuapp.test", cls.nurse_practitioner, ["Nurse"])
		cls.other_nurse_user = cls._make_user(
			"test.nurse.beta@bandhuapp.test", cls.other_practitioner, ["Nurse"]
		)
		cls.no_role_user = cls._make_user("test.norole@bandhuapp.test", None, [])

		cls.session = cls._make_session(cls.nurse_practitioner)
		cls.other_session = cls._make_session(cls.other_practitioner)

	@classmethod
	def _make_practitioner(cls, first_name, custom_role=None):
		doc = frappe.get_doc(
			{
				"doctype": "Healthcare Practitioner",
				"first_name": first_name,
				"status": "Active",
				"custom_role": custom_role,
			}
		).insert(ignore_permissions=True)
		return doc.name

	@classmethod
	def _make_user(cls, email, practitioner, roles):
		if frappe.db.exists("User", email):
			user = frappe.get_doc("User", email)
		else:
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": email.split("@")[0],
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)

		if roles:
			user.add_roles(*roles)

		if practitioner:
			frappe.db.set_value("Healthcare Practitioner", practitioner, "user_id", email)

		return email

	@classmethod
	def _make_session(cls, assigned_nurse):
		doc = frappe.get_doc(
			{
				"doctype": "Bandhu Clinic Session",
				"date": today(),
				"clinic": cls.clinic,
				"site": cls.site,
				"project": cls.project,
				"assigned_nurse": assigned_nurse,
				"status": "In Progress",
			}
		).insert(ignore_permissions=True)
		return doc.name

	@classmethod
	def _make_patient(cls, first_name, **fields):
		doc = frappe.get_doc(
			{
				"doctype": "Patient",
				"first_name": first_name,
				"sex": cls.gender,
				**fields,
			}
		).insert(ignore_permissions=True)
		return doc.name

	def _make_encounter(
		self, session, workflow_state, practitioner=None, tests=None, prescriptions=None, patient_fields=None
	):
		patient = self._make_patient(
			f"Test Patient {frappe.generate_hash(length=8)}", **(patient_fields or {})
		)
		doc = frappe.get_doc(
			{
				"doctype": "Patient Encounter",
				"patient": patient,
				"practitioner": practitioner or self.nurse_practitioner,
				"encounter_date": today(),
				"encounter_time": nowtime(),
				"appointment_type": self.appointment_type,
				"custom_clinic_session": session,
				"custom_workflow_state": workflow_state,
				"custom_test_instructions": tests or [],
				"custom_bandhu_prescription": prescriptions or [],
			}
		).insert(ignore_permissions=True)
		return doc

	def test_submit_test_results_writes_results_and_advances_state(self):
		encounter = self._make_encounter(
			self.session, "Awaiting Test", tests=[{"test_name": "Malaria", "notes": "Fasting"}]
		)
		row_name = encounter.custom_test_instructions[0].name

		frappe.set_user(self.nurse_user)
		try:
			submit_test_results(
				encounter.name, [{"name": row_name, "result_type": "Negative", "result_value": ""}]
			)
		finally:
			frappe.set_user("Administrator")

		encounter.reload()
		self.assertEqual(encounter.custom_workflow_state, "Awaiting Doctor Review")
		self.assertEqual(encounter.custom_test_instructions[0].result_type, "Negative")
		self.assertEqual(
			frappe.db.get_value("Patient Queue", {"encounter": encounter.name}, "current_stage"),
			"With Doctor",
		)

	def test_submit_test_results_rejects_wrong_state(self):
		encounter = self._make_encounter(self.session, "Waiting for Doctor", tests=[{"test_name": "Malaria"}])
		row_name = encounter.custom_test_instructions[0].name

		frappe.set_user(self.nurse_user)
		try:
			self.assertRaises(
				frappe.ValidationError,
				submit_test_results,
				encounter.name,
				[{"name": row_name, "result_type": "Negative"}],
			)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(
			frappe.db.get_value("Patient Encounter", encounter.name, "custom_workflow_state"),
			"Waiting for Doctor",
		)

	def test_record_vitals_writes_fields_and_computes_bmi(self):
		encounter = self._make_encounter(self.session, "Awaiting Test", tests=[{"test_name": "Malaria"}])

		frappe.set_user(self.nurse_user)
		try:
			record_vitals(
				encounter.name,
				height_cm=170,
				weight_kg=68,
				temperature=98.6,
				pulse_rate=76,
				spo2=98,
				bp_systolic=120,
				bp_diastolic=80,
			)
		finally:
			frappe.set_user("Administrator")

		encounter.reload()
		self.assertEqual(flt(encounter.custom_height), 170)
		self.assertEqual(flt(encounter.custom_weight), 68)
		self.assertEqual(encounter.custom_blood_pressure, "120/80")
		self.assertEqual(flt(encounter.custom_bmi), 23.53)
		# The workflow state is untouched: recording vitals is not a queue transition.
		self.assertEqual(encounter.custom_workflow_state, "Awaiting Test")

	def test_record_vitals_rejects_empty_call(self):
		encounter = self._make_encounter(self.session, "Awaiting Test", tests=[{"test_name": "Malaria"}])

		frappe.set_user(self.nurse_user)
		try:
			self.assertRaises(frappe.ValidationError, record_vitals, encounter.name)
		finally:
			frappe.set_user("Administrator")

	def test_record_vitals_rejects_a_patient_not_with_the_nurse(self):
		encounter = self._make_encounter(self.session, "Waiting for Doctor")

		frappe.set_user(self.nurse_user)
		try:
			self.assertRaises(frappe.ValidationError, record_vitals, encounter.name, weight_kg=68)
		finally:
			frappe.set_user("Administrator")

	def test_dispense_medicine_marks_rows_and_completes(self):
		encounter = self._make_encounter(
			self.session,
			"Awaiting Medicine",
			prescriptions=[{"medicines": self.item, "dosage_frequency": "OD", "quantity": 5}],
		)
		row_name = encounter.custom_bandhu_prescription[0].name

		frappe.set_user(self.nurse_user)
		try:
			dispense_medicine(encounter.name, [row_name])
		finally:
			frappe.set_user("Administrator")

		encounter.reload()
		self.assertEqual(encounter.custom_workflow_state, "Completed")
		self.assertTrue(encounter.custom_bandhu_prescription[0].dispensed)
		self.assertEqual(encounter.custom_bandhu_prescription[0].dispensed_by, self.nurse_practitioner)

		queue_row = frappe.db.get_value(
			"Patient Queue", {"encounter": encounter.name}, ["current_stage", "status"], as_dict=True
		)
		self.assertEqual(queue_row.current_stage, "Completed")
		self.assertEqual(queue_row.status, "Done")

	def test_dispense_medicine_allows_partial_dispense(self):
		encounter = self._make_encounter(
			self.session,
			"Awaiting Medicine",
			prescriptions=[
				{"medicines": self.item, "dosage_frequency": "OD", "quantity": 5},
				{"medicines": self.item, "dosage_frequency": "BD", "quantity": 3},
			],
		)
		dispensed_row = encounter.custom_bandhu_prescription[0].name

		frappe.set_user(self.nurse_user)
		try:
			dispense_medicine(encounter.name, [dispensed_row])
		finally:
			frappe.set_user("Administrator")

		encounter.reload()
		self.assertTrue(encounter.custom_bandhu_prescription[0].dispensed)
		self.assertFalse(encounter.custom_bandhu_prescription[1].dispensed)

	def test_unprivileged_user_is_blocked(self):
		test_encounter = self._make_encounter(self.session, "Awaiting Test", tests=[{"test_name": "Hb"}])
		medicine_encounter = self._make_encounter(
			self.session, "Awaiting Medicine", prescriptions=[{"medicines": self.item}]
		)

		frappe.set_user(self.no_role_user)
		try:
			self.assertRaises(
				frappe.PermissionError,
				submit_test_results,
				test_encounter.name,
				[{"name": test_encounter.custom_test_instructions[0].name, "result_type": "Negative"}],
			)
			self.assertRaises(
				frappe.PermissionError,
				dispense_medicine,
				medicine_encounter.name,
				[medicine_encounter.custom_bandhu_prescription[0].name],
			)
		finally:
			frappe.set_user("Administrator")

	def test_nurse_not_assigned_to_session_is_blocked(self):
		encounter = self._make_encounter(
			self.other_session,
			"Awaiting Test",
			practitioner=self.other_practitioner,
			tests=[{"test_name": "Hb"}],
		)

		frappe.set_user(self.nurse_user)
		try:
			self.assertRaises(
				frappe.PermissionError,
				submit_test_results,
				encounter.name,
				[{"name": encounter.custom_test_instructions[0].name, "result_type": "Negative"}],
			)
		finally:
			frappe.set_user("Administrator")

	def test_get_patient_registration_details_returns_cad_fields(self):
		encounter = self._make_encounter(
			self.session, "Awaiting Test", patient_fields={"custom_height_m": 1.6, "custom_weight_kg": 55}
		)

		frappe.set_user(self.nurse_user)
		try:
			details = get_patient_registration_details(encounter.name)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(details.custom_height_m, 1.6)
		self.assertEqual(details.custom_weight_kg, 55)

	def _make_session_with(self, status, date):
		doc = frappe.get_doc(
			{
				"doctype": "Bandhu Clinic Session",
				"date": date,
				"clinic": self.clinic,
				"site": self.site,
				"project": self.project,
				"assigned_nurse": self.nurse_practitioner,
				"status": status,
			}
		).insert(ignore_permissions=True)
		return doc.name

	def test_closed_camp_cannot_be_reopened(self):
		session = self._make_session_with("Completed", today())

		frappe.set_user(self.nurse_user)
		try:
			with self.assertRaises(frappe.ValidationError):
				start_session(session)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(frappe.db.get_value("Bandhu Clinic Session", session, "status"), "Completed")

	def test_camp_cannot_be_opened_on_another_day(self):
		session = self._make_session_with("Planned", add_days(today(), 7))

		frappe.set_user(self.nurse_user)
		try:
			with self.assertRaises(frappe.ValidationError):
				start_session(session)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(frappe.db.get_value("Bandhu Clinic Session", session, "status"), "Planned")

	def test_cancelled_camp_cannot_be_opened_or_closed(self):
		session = self._make_session_with("Cancelled", today())

		frappe.set_user(self.nurse_user)
		try:
			self.assertRaises(frappe.ValidationError, start_session, session)
			self.assertRaises(frappe.ValidationError, end_session, session)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(frappe.db.get_value("Bandhu Clinic Session", session, "status"), "Cancelled")

	def test_camp_that_is_not_open_cannot_be_closed(self):
		session = self._make_session_with("Planned", today())

		frappe.set_user(self.nurse_user)
		try:
			with self.assertRaises(frappe.ValidationError):
				end_session(session)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(frappe.db.get_value("Bandhu Clinic Session", session, "status"), "Planned")

	def test_todays_planned_camp_opens_and_closes(self):
		session = self._make_session_with("Planned", today())

		frappe.set_user(self.nurse_user)
		try:
			start_session(session)
			self.assertEqual(frappe.db.get_value("Bandhu Clinic Session", session, "status"), "In Progress")
			end_session(session)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(frappe.db.get_value("Bandhu Clinic Session", session, "status"), "Completed")
