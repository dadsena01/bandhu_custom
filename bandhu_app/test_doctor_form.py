# Copyright (c) 2026, CMID and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from bandhu_app.bandhu_app.baseline_test_fixtures import ensure_baseline_fixtures
from bandhu_app.bandhu_app.page.doctor_form.doctor_form import (
	call_patient,
	complete_encounter,
	get_patient_registration_details,
	get_referral_letter_html,
	get_registered_patients,
	get_session_status,
	get_test_options,
	order_test,
	prescribe_medicine,
	release_patient,
)
from bandhu_app.bandhu_app.utils.clinic_test import seed_default_tests
from bandhu_app.bandhu_app.utils.patient_details import get_clinical_details_by_encounter


class TestDoctorForm(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		baseline = ensure_baseline_fixtures()
		cls.appointment_type = baseline["appointment_type"]
		cls.project = baseline["project"]
		cls.site = baseline["site"]
		cls.unit = baseline["unit"]
		cls.clinic = baseline["clinic"]
		cls.item = baseline["item"]

	def setUp(self):
		self.today = frappe.utils.today()

		self.patient = self._make_patient("Doctor Form Test Patient")
		self.doctor_user_1 = self._make_user("doctor-form-test-1@example.com", ["Doctor"])
		self.doctor_user_2 = self._make_user("doctor-form-test-2@example.com", ["Doctor"])
		self.plain_user = self._make_user("doctor-form-test-plain@example.com", [])

		self.practitioner_1 = self._make_practitioner("Doc One", self.doctor_user_1)
		self.practitioner_2 = self._make_practitioner("Doc Two", self.doctor_user_2)

		self.session_1 = self._make_session(self.practitioner_1)
		self.session_2 = self._make_session(self.practitioner_2)

		self.encounter = self._make_encounter(self.session_1, "Waiting for Doctor")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def _make_patient(self, first_name):
		return frappe.get_doc(
			{
				"doctype": "Patient",
				"first_name": first_name,
				"sex": "Male",
				"custom_height_m": 1.7,
				"custom_weight_kg": 65,
			}
		).insert(ignore_permissions=True)

	def _make_user(self, email, roles):
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
		return user.name

	def _make_practitioner(self, first_name, user_id, custom_role="Doctor"):
		return frappe.get_doc(
			{
				"doctype": "Healthcare Practitioner",
				"first_name": first_name,
				"user_id": user_id,
				"custom_role": custom_role,
			}
		).insert(ignore_permissions=True)

	def _make_session(self, practitioner):
		return frappe.get_doc(
			{
				"doctype": "Bandhu Clinic Session",
				"date": self.today,
				"project": self.project,
				"site": self.site,
				"unit": self.unit,
				"clinic": self.clinic,
				"status": "In Progress",
				"assigned_doctor": practitioner.name,
			}
		).insert(ignore_permissions=True)

	def _make_encounter(self, session, workflow_state):
		return frappe.get_doc(
			{
				"doctype": "Patient Encounter",
				"patient": self.patient.name,
				"practitioner": session.assigned_doctor,
				"encounter_date": self.today,
				"encounter_time": frappe.utils.nowtime(),
				"appointment_type": self.appointment_type,
				"custom_clinic_session": session.name,
				"custom_workflow_state": workflow_state,
			}
		).insert(ignore_permissions=True)

	def test_order_test_writes_rows_and_advances_state(self):
		frappe.set_user(self.doctor_user_1)
		order_test(self.encounter.name, ["Malaria", "Hb"], notes="Fasting sample")

		self.encounter.reload()
		self.assertEqual(self.encounter.custom_workflow_state, "Awaiting Test")
		self.assertEqual(len(self.encounter.custom_test_instructions), 2)
		self.assertEqual({r.test_name for r in self.encounter.custom_test_instructions}, {"Malaria", "Hb"})
		self.assertEqual(self.encounter.custom_test_instructions[0].notes, "Fasting sample")

		stage = frappe.db.get_value("Patient Queue", {"encounter": self.encounter.name}, "current_stage")
		self.assertEqual(stage, "With Nurse (Test)")

	def test_order_test_stamps_one_note_on_every_row_and_the_payload_reports_it_once(self):
		"""order_test copies the doctor's single note onto each row it appends. Without the
		payload saying so, the Patient Details dialog prints the same sentence once per test."""
		frappe.set_user(self.doctor_user_1)
		order_test(self.encounter.name, ["Malaria", "Hb"], notes="Fever 3 days")

		frappe.set_user("Administrator")
		details = get_clinical_details_by_encounter([self.encounter.name])[self.encounter.name]

		self.assertEqual([row.notes for row in details["tests"]], ["Fever 3 days", "Fever 3 days"])
		self.assertEqual(details["shared_test_note"], "Fever 3 days")

	def test_order_test_rejects_unknown_test_name(self):
		frappe.set_user(self.doctor_user_1)
		with self.assertRaises(frappe.ValidationError):
			order_test(self.encounter.name, ["Not A Real Test"])

	def test_order_test_rejects_a_test_that_is_not_an_enabled_master_record(self):
		seed_default_tests()
		frappe.db.set_value("Bandhu Test", "Leptospirosis", "enabled", 0)
		# Rollback only happens once the class finishes, so restore it for the next test.
		self.addCleanup(frappe.db.set_value, "Bandhu Test", "Leptospirosis", "enabled", 1)

		frappe.set_user(self.doctor_user_1)
		with self.assertRaises(frappe.ValidationError):
			order_test(self.encounter.name, ["Leptospirosis"])

	def test_a_disabled_test_leaves_the_options_without_breaking_an_encounter_holding_it(self):
		seed_default_tests()
		frappe.set_user(self.doctor_user_1)
		order_test(self.encounter.name, ["Leptospirosis"])

		frappe.db.set_value("Bandhu Test", "Leptospirosis", "enabled", 0)
		# Rollback only happens once the class finishes, so restore it for the next test.
		self.addCleanup(frappe.db.set_value, "Bandhu Test", "Leptospirosis", "enabled", 1)

		self.assertNotIn("Leptospirosis", [test["name"] for test in get_test_options()])

		self.encounter.reload()
		self.assertEqual(
			[row.test_name for row in self.encounter.custom_test_instructions], ["Leptospirosis"]
		)
		# The nurse still has to be able to save a result against the row the doctor ordered
		# before the test was retired.
		self.encounter.custom_test_instructions[0].result_type = "Negative"
		self.encounter.save(ignore_permissions=True)

	def test_test_options_carry_the_unit_for_a_value_test(self):
		seed_default_tests()
		frappe.set_user(self.doctor_user_1)
		labels = {test["name"]: test["label"] for test in get_test_options()}

		self.assertEqual(labels["Hb"], "Hb (g/dL)")
		self.assertEqual(labels["Malaria"], "Malaria")

	def test_order_test_rejects_empty_list(self):
		frappe.set_user(self.doctor_user_1)
		with self.assertRaises(frappe.ValidationError):
			order_test(self.encounter.name, [])

	def test_prescribe_medicine_writes_rows_and_advances_state(self):
		frappe.set_user(self.doctor_user_1)
		prescribe_medicine(
			self.encounter.name,
			[{"medicines": self.item, "dosage_frequency": "BD", "duration_days": 5, "quantity": 10}],
		)

		self.encounter.reload()
		self.assertEqual(self.encounter.custom_workflow_state, "Awaiting Medicine")
		self.assertEqual(len(self.encounter.custom_bandhu_prescription), 1)
		row = self.encounter.custom_bandhu_prescription[0]
		self.assertEqual(row.medicines, self.item)
		self.assertEqual(row.dosage_frequency, "BD")
		self.assertFalse(row.dispensed)

	def test_prescribe_medicine_does_not_stamp_the_prescriber_as_the_dispenser(self):
		"""dispensed_by is a nurse-only field (link_filters on Prescription), but left unset it
		takes the prescribing doctor's own User Permission as a default — recording a dispenser
		for medicine nobody has handed over yet."""
		frappe.set_user(self.doctor_user_1)
		prescribe_medicine(
			self.encounter.name,
			[{"medicines": self.item, "dosage_frequency": "BD", "duration_days": 5, "quantity": 10}],
		)

		self.encounter.reload()
		self.assertFalse(self.encounter.custom_bandhu_prescription[0].dispensed_by)

	def test_prescribe_medicine_rejects_row_without_medicine(self):
		frappe.set_user(self.doctor_user_1)
		with self.assertRaises(frappe.ValidationError):
			prescribe_medicine(self.encounter.name, [{"dosage_frequency": "BD"}])

	def test_order_test_records_chief_complaint(self):
		frappe.set_user(self.doctor_user_1)
		order_test(self.encounter.name, ["Malaria"], chief_complaint="Fever for 3 days")

		self.encounter.reload()
		self.assertEqual(self.encounter.custom_chief_complaints, "Fever for 3 days")

	def test_prescribe_medicine_records_chief_complaint(self):
		frappe.set_user(self.doctor_user_1)
		prescribe_medicine(
			self.encounter.name,
			[{"medicines": self.item, "dosage_frequency": "BD", "duration_days": 5, "quantity": 10}],
			chief_complaint="Joint pain",
		)

		self.encounter.reload()
		self.assertEqual(self.encounter.custom_chief_complaints, "Joint pain")

	def test_complete_encounter_records_chief_complaint(self):
		frappe.set_user(self.doctor_user_1)
		complete_encounter(self.encounter.name, chief_complaint="Cough")

		self.encounter.reload()
		self.assertEqual(self.encounter.custom_chief_complaints, "Cough")

	def test_order_test_records_past_and_allergy_history(self):
		frappe.set_user(self.doctor_user_1)
		order_test(
			self.encounter.name,
			["Malaria"],
			past_history="Diabetes",
			allergy_history="Penicillin",
		)

		self.encounter.reload()
		self.assertEqual(self.encounter.custom_past_history, "Diabetes")
		self.assertEqual(self.encounter.custom_allergy_history, "Penicillin")

	def test_prescribe_medicine_records_past_and_allergy_history(self):
		frappe.set_user(self.doctor_user_1)
		prescribe_medicine(
			self.encounter.name,
			[{"medicines": self.item, "dosage_frequency": "BD", "duration_days": 5, "quantity": 10}],
			past_history="Hypertension",
			allergy_history="Sulfa drugs",
		)

		self.encounter.reload()
		self.assertEqual(self.encounter.custom_past_history, "Hypertension")
		self.assertEqual(self.encounter.custom_allergy_history, "Sulfa drugs")

	def test_complete_encounter_records_past_and_allergy_history(self):
		frappe.set_user(self.doctor_user_1)
		complete_encounter(self.encounter.name, past_history="Asthma", allergy_history="Dust")

		self.encounter.reload()
		self.assertEqual(self.encounter.custom_past_history, "Asthma")
		self.assertEqual(self.encounter.custom_allergy_history, "Dust")

	def test_an_omitted_chief_complaint_does_not_erase_one_already_recorded(self):
		frappe.set_user(self.doctor_user_1)
		order_test(self.encounter.name, ["Malaria"], chief_complaint="Fever for 3 days")

		frappe.db.set_value(
			"Patient Encounter", self.encounter.name, "custom_workflow_state", "Awaiting Doctor Review"
		)
		prescribe_medicine(
			self.encounter.name,
			[{"medicines": self.item, "dosage_frequency": "BD", "duration_days": 5, "quantity": 10}],
		)

		self.encounter.reload()
		self.assertEqual(self.encounter.custom_chief_complaints, "Fever for 3 days")

	def test_clearing_an_allergy_actually_clears_it(self):
		frappe.set_user(self.doctor_user_1)
		order_test(self.encounter.name, ["Malaria"], allergy_history="Penicillin")

		frappe.db.set_value(
			"Patient Encounter", self.encounter.name, "custom_workflow_state", "Awaiting Doctor Review"
		)
		complete_encounter(self.encounter.name, allergy_history="")

		self.encounter.reload()
		self.assertFalse(self.encounter.custom_allergy_history)

	def test_prescribe_medicine_rejects_the_same_medicine_twice_in_one_prescription(self):
		frappe.set_user(self.doctor_user_1)
		with self.assertRaises(frappe.ValidationError):
			prescribe_medicine(
				self.encounter.name,
				[
					{"medicines": self.item, "dosage_frequency": "BD", "quantity": 10},
					{"medicines": self.item, "dosage_frequency": "OD", "quantity": 5},
				],
			)

	def test_prescribe_medicine_rejects_a_medicine_already_on_the_encounter(self):
		frappe.set_user(self.doctor_user_1)
		prescribe_medicine(self.encounter.name, [{"medicines": self.item, "quantity": 10}])

		frappe.db.set_value(
			"Patient Encounter", self.encounter.name, "custom_workflow_state", "Awaiting Doctor Review"
		)
		with self.assertRaises(frappe.ValidationError):
			prescribe_medicine(self.encounter.name, [{"medicines": self.item, "quantity": 5}])

	def test_prescribe_medicine_rejects_a_negative_quantity(self):
		frappe.set_user(self.doctor_user_1)
		with self.assertRaises(frappe.ValidationError):
			prescribe_medicine(self.encounter.name, [{"medicines": self.item, "quantity": -5}])

	def test_prescribe_medicine_rejects_negative_days(self):
		frappe.set_user(self.doctor_user_1)
		with self.assertRaises(frappe.ValidationError):
			prescribe_medicine(self.encounter.name, [{"medicines": self.item, "duration_days": -3}])

	def test_complete_encounter_records_diagnosis(self):
		frappe.set_user(self.doctor_user_1)
		complete_encounter(self.encounter.name, diagnosis="Viral fever", clinical_notes="Rest advised")

		self.encounter.reload()
		self.assertEqual(self.encounter.custom_workflow_state, "Completed")
		self.assertEqual(len(self.encounter.custom_bandhu_diagnosis), 1)
		self.assertEqual(self.encounter.custom_bandhu_diagnosis[0].diagnosis_name, "Viral fever")
		self.assertEqual(self.encounter.custom_bandhu_clinical_notes, "Rest advised")

	def test_complete_encounter_without_diagnosis_is_allowed(self):
		frappe.set_user(self.doctor_user_1)
		complete_encounter(self.encounter.name)
		self.encounter.reload()
		self.assertEqual(self.encounter.custom_workflow_state, "Completed")

	def test_complete_encounter_creates_a_referral(self):
		frappe.set_user(self.doctor_user_1)
		complete_encounter(
			self.encounter.name,
			referred_to="Ernakulam General Hospital",
			referred_to_practitioner=self.practitioner_2.name,
			referral_reason="Suspected fracture, needs an X-ray",
			referral_priority="High",
		)

		self.encounter.reload()
		self.assertTrue(self.encounter.custom_has_referral)

		referral = frappe.get_last_doc("Referral", filters={"patient_encounter": self.encounter.name})
		self.assertEqual(referral.patient, self.patient.name)
		self.assertEqual(referral.referred_to, "Ernakulam General Hospital")
		self.assertEqual(referral.referred_to_practitioner, self.practitioner_2.name)
		self.assertEqual(referral.reason, "Suspected fracture, needs an X-ray")
		self.assertEqual(referral.priority, "High")
		self.assertEqual(referral.status, "Pending")
		self.assertTrue(referral.helpline_flag)
		self.assertEqual(referral.project, self.project)
		self.assertEqual(referral.clinic_session, self.session_1.name)
		self.assertEqual(referral.referral_by_source, self.practitioner_1.name)

	def test_complete_encounter_referral_defaults_to_medium_priority(self):
		frappe.set_user(self.doctor_user_1)
		complete_encounter(
			self.encounter.name,
			referred_to="Ernakulam General Hospital",
			referral_reason="Follow-up care",
		)

		referral = frappe.get_last_doc("Referral", filters={"patient_encounter": self.encounter.name})
		self.assertEqual(referral.priority, "Medium")

	def test_complete_encounter_rejects_a_referral_missing_the_reason(self):
		frappe.set_user(self.doctor_user_1)
		with self.assertRaises(frappe.ValidationError):
			complete_encounter(self.encounter.name, referred_to="Ernakulam General Hospital")

	def test_complete_encounter_without_referral_fields_creates_no_referral(self):
		frappe.set_user(self.doctor_user_1)
		complete_encounter(self.encounter.name, diagnosis="Viral fever")

		self.encounter.reload()
		self.assertFalse(self.encounter.custom_has_referral)
		self.assertEqual(frappe.db.count("Referral", {"patient_encounter": self.encounter.name}), 0)

	def test_referral_letter_renders_for_a_referred_patient(self):
		frappe.set_user(self.doctor_user_1)
		complete_encounter(
			self.encounter.name,
			referred_to="Ernakulam General Hospital",
			referral_reason="Suspected fracture",
		)

		html = get_referral_letter_html(self.encounter.name)
		self.assertIn("Ernakulam General Hospital", html)
		self.assertIn("Suspected fracture", html)

	def test_referral_letter_escapes_injected_referral_fields(self):
		frappe.set_user(self.doctor_user_1)
		complete_encounter(
			self.encounter.name,
			referred_to="<img src=x onerror=alert(1)>",
			referral_reason="<script>alert(1)</script>",
		)

		html = get_referral_letter_html(self.encounter.name)
		self.assertNotIn("alert(1)", html)
		self.assertNotIn("onerror=", html)

	def test_referral_letter_rejects_a_patient_with_no_referral(self):
		frappe.set_user(self.doctor_user_1)
		complete_encounter(self.encounter.name, diagnosis="Viral fever")

		with self.assertRaises(frappe.DoesNotExistError):
			get_referral_letter_html(self.encounter.name)

	def test_call_patient_marks_who_is_in_the_room(self):
		frappe.set_user(self.doctor_user_1)
		call_patient(self.encounter.name)

		self.assertIsNotNone(
			frappe.db.get_value("Patient Encounter", self.encounter.name, "custom_called_at")
		)

	def test_three_patients_can_be_with_the_doctor_at_once(self):
		others = [self._make_encounter(self.session_1, "Waiting for Doctor") for _ in range(2)]

		frappe.set_user(self.doctor_user_1)
		call_patient(self.encounter.name)
		for other in others:
			call_patient(other.name)

		self.assertEqual(
			frappe.db.count(
				"Patient Encounter",
				{"custom_clinic_session": self.session_1.name, "custom_called_at": ["is", "set"]},
			),
			3,
		)

	def test_a_fourth_patient_is_refused_until_one_leaves(self):
		others = [self._make_encounter(self.session_1, "Waiting for Doctor") for _ in range(3)]

		frappe.set_user(self.doctor_user_1)
		call_patient(self.encounter.name)
		call_patient(others[0].name)
		call_patient(others[1].name)

		with self.assertRaises(frappe.ValidationError):
			call_patient(others[2].name)

		release_patient(self.encounter.name)
		call_patient(others[2].name)

		self.assertIsNotNone(frappe.db.get_value("Patient Encounter", others[2].name, "custom_called_at"))

	def test_calling_the_same_patient_twice_does_not_take_a_second_place(self):
		others = [self._make_encounter(self.session_1, "Waiting for Doctor") for _ in range(2)]

		frappe.set_user(self.doctor_user_1)
		call_patient(self.encounter.name)
		call_patient(self.encounter.name)
		for other in others:
			call_patient(other.name)

		self.assertEqual(
			frappe.db.count(
				"Patient Encounter",
				{"custom_clinic_session": self.session_1.name, "custom_called_at": ["is", "set"]},
			),
			3,
		)

	def test_a_full_room_does_not_block_another_doctor(self):
		mine = [self._make_encounter(self.session_1, "Waiting for Doctor") for _ in range(2)]
		theirs = self._make_encounter(self.session_2, "Waiting for Doctor")

		frappe.set_user(self.doctor_user_1)
		call_patient(self.encounter.name)
		for one in mine:
			call_patient(one.name)

		frappe.set_user(self.doctor_user_2)
		call_patient(theirs.name)

		self.assertIsNotNone(frappe.db.get_value("Patient Encounter", theirs.name, "custom_called_at"))

	def test_a_cancelled_patient_leaves_the_doctors_queue(self):
		cancelled = self._make_encounter(self.session_1, "Cancelled")

		frappe.set_user(self.doctor_user_1)
		names = [row["name"] for row in get_registered_patients()]

		self.assertNotIn(cancelled.name, names)
		self.assertIn(self.encounter.name, names)

	def test_call_patient_rejects_a_patient_the_nurse_holds(self):
		with_nurse = self._make_encounter(self.session_1, "Awaiting Test")

		frappe.set_user(self.doctor_user_1)
		with self.assertRaises(frappe.ValidationError):
			call_patient(with_nurse.name)

	def test_call_patient_blocks_another_doctors_patient(self):
		frappe.set_user(self.doctor_user_2)
		with self.assertRaises(frappe.PermissionError):
			call_patient(self.encounter.name)

	def test_release_patient_empties_the_room(self):
		frappe.set_user(self.doctor_user_1)
		call_patient(self.encounter.name)
		release_patient(self.encounter.name)

		self.assertIsNone(frappe.db.get_value("Patient Encounter", self.encounter.name, "custom_called_at"))

	def test_ordering_a_test_sends_the_patient_out_of_the_room(self):
		frappe.set_user(self.doctor_user_1)
		call_patient(self.encounter.name)
		order_test(self.encounter.name, ["Malaria"])

		self.assertIsNone(frappe.db.get_value("Patient Encounter", self.encounter.name, "custom_called_at"))

	def test_completing_a_patient_sends_them_out_of_the_room(self):
		frappe.set_user(self.doctor_user_1)
		call_patient(self.encounter.name)
		complete_encounter(self.encounter.name)

		self.assertIsNone(frappe.db.get_value("Patient Encounter", self.encounter.name, "custom_called_at"))

	def test_prescribing_sends_the_patient_out_of_the_room(self):
		frappe.set_user(self.doctor_user_1)
		call_patient(self.encounter.name)
		prescribe_medicine(self.encounter.name, [{"medicines": self.item}])

		self.assertIsNone(frappe.db.get_value("Patient Encounter", self.encounter.name, "custom_called_at"))

	def test_doctor_cannot_act_on_another_doctors_patient(self):
		frappe.set_user(self.doctor_user_2)
		with self.assertRaises(frappe.PermissionError):
			order_test(self.encounter.name, ["Malaria"])

	def test_plain_user_is_blocked(self):
		frappe.set_user(self.plain_user)
		with self.assertRaises(frappe.PermissionError):
			order_test(self.encounter.name, ["Malaria"])

	def test_get_patient_registration_details_returns_cad_fields(self):
		frappe.set_user(self.doctor_user_1)
		details = get_patient_registration_details(self.encounter.name)
		self.assertEqual(details.custom_height_m, 1.7)
		self.assertEqual(details.custom_weight_kg, 65)

	def test_get_patient_registration_details_returns_the_stored_date_of_birth(self):
		"""The dialog formats dob with frappe.datetime.str_to_user, so the endpoint has to hand
		back the stored date. A pre-formatted string would be re-parsed and printed wrong."""
		frappe.db.set_value("Patient", self.patient.name, "dob", "1992-02-14")

		frappe.set_user(self.doctor_user_1)
		details = get_patient_registration_details(self.encounter.name)

		self.assertEqual(str(details.dob), "1992-02-14")

	def test_get_patient_registration_details_blocks_unowned_encounter(self):
		frappe.set_user(self.doctor_user_2)
		with self.assertRaises(frappe.PermissionError):
			get_patient_registration_details(self.encounter.name)

	def test_get_session_status_returns_active_session(self):
		frappe.set_user(self.doctor_user_1)
		status = get_session_status()
		self.assertTrue(status["has_session"])
		self.assertEqual(status["session_name"], self.session_1.name)
		self.assertEqual(status["status"], "In Progress")

	def test_get_session_status_no_practitioner_linked(self):
		user = self._make_user("doctor-form-test-no-practitioner@example.com", ["Doctor"])
		frappe.set_user(user)
		try:
			status = get_session_status()
		finally:
			frappe.set_user("Administrator")
		self.assertFalse(status["has_session"])
		self.assertEqual(status["message"], "No Healthcare Practitioner linked to your account.")

	def test_get_session_status_no_session_scheduled(self):
		user = self._make_user("doctor-form-test-no-session@example.com", ["Doctor"])
		self._make_practitioner("Doc No Session", user)
		frappe.set_user(user)
		try:
			status = get_session_status()
		finally:
			frappe.set_user("Administrator")
		self.assertFalse(status["has_session"])
		self.assertEqual(
			status["message"], "No session scheduled for today. Please contact Programme Manager."
		)

	def test_get_session_status_blocks_non_doctor_role(self):
		frappe.set_user(self.plain_user)
		try:
			status = get_session_status()
		finally:
			frappe.set_user("Administrator")
		self.assertFalse(status["has_session"])
		self.assertEqual(status["message"], "You do not have the Doctor role.")
