# Copyright (c) 2026, CMID and Contributors
# See license.txt

"""What happens when two requests reach the same encounter at once.

Two field staff on the same patient, and one tap that fires twice, are the shapes this app
has actually hit in production. The suite calls each endpoint once and in order, so neither
was covered. These tests drive the second request either by firing the endpoint twice, or —
where a real interleave is needed — by handing the second call a document it read before the
first one wrote, which is what a concurrent request is holding.
"""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today

from bandhu_app.bandhu_app.baseline_test_fixtures import ensure_baseline_fixtures
from bandhu_app.bandhu_app.page.doctor_form import doctor_form
from bandhu_app.bandhu_app.page.nurse_form import nurse_form
from bandhu_app.test_api_boundary import CAD, DOCTOR, NURSE, call_over_http


class TestEncounterConcurrency(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		baseline = ensure_baseline_fixtures()
		cls.clinic = baseline["clinic"]
		cls.site = baseline["site"]
		cls.project = baseline["project"]
		cls.item = baseline["item"]
		cls.gender = frappe.get_all("Gender", limit=1, pluck="name")[0]

	def setUp(self):
		# Rollback is per class: a shared camp would let each test count the previous test's
		# encounters.
		self.suffix = frappe.generate_hash(length=8)
		self.driver = self.make_practitioner("Clinic Assistant cum Driver")
		self.doctor = self.make_practitioner("Doctor")
		self.nurse = self.make_practitioner("Nurse")
		self.cad_user = self.make_user(self.driver, ["Clinic Assistant cum Driver"])
		self.doctor_user = self.make_user(self.doctor, ["Doctor"])
		self.nurse_user = self.make_user(self.nurse, ["Nurse"])
		self.session = self.make_session()

	def tearDown(self):
		frappe.set_user("Administrator")

	def make_practitioner(self, custom_role: str) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "Healthcare Practitioner",
					"first_name": f"Race {custom_role} {self.suffix}",
					"status": "Active",
					"custom_role": custom_role,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def make_user(self, practitioner: str, roles: list) -> str:
		email = f"race.{frappe.generate_hash(length=10)}@bandhuapp.test"
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": email.split("@")[0],
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
		user.add_roles(*roles)
		frappe.db.set_value("Healthcare Practitioner", practitioner, "user_id", email)
		return email

	def make_session(self, status: str = "In Progress") -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "Bandhu Clinic Session",
					"date": today(),
					"clinic": self.clinic,
					"site": self.site,
					"project": self.project,
					"assigned_driver": self.driver,
					"assigned_doctor": self.doctor,
					"assigned_nurse": self.nurse,
					"status": status,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def make_patient(self) -> str:
		return (
			frappe.get_doc(
				{"doctype": "Patient", "first_name": f"Race Patient {self.suffix}", "sex": self.gender}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def make_encounter(self, workflow_state: str = "Waiting for Doctor") -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "Patient Encounter",
					"patient": self.make_patient(),
					"practitioner": self.doctor,
					"encounter_date": today(),
					"custom_clinic_session": self.session,
					"custom_workflow_state": workflow_state,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def state_of(self, encounter: str) -> str:
		return frappe.db.get_value("Patient Encounter", encounter, "custom_workflow_state")

	def test_the_loser_of_two_concurrent_saves_is_told_so(self):
		"""Audit finding F2 claims this transition is last-write-wins and drops child rows.

		It is not. Both requests hold a copy read at the same `modified`; the second save
		hits `Document.check_if_latest` and raises, so the first request's prescription is
		still there and the second doctor is told to refresh rather than quietly losing work.
		"""
		encounter = self.make_encounter()
		first_request = frappe.get_doc("Patient Encounter", encounter)
		second_request = frappe.get_doc("Patient Encounter", encounter)

		first_request.append("custom_test_instructions", {"test_name": "Malaria"})
		first_request.custom_workflow_state = "Awaiting Test"
		first_request.save(ignore_permissions=True)

		second_request.append("custom_bandhu_diagnosis", {"diagnosis_name": "Race Diagnosis"})
		second_request.custom_workflow_state = "Completed"
		with self.assertRaises(frappe.TimestampMismatchError):
			second_request.save(ignore_permissions=True)

		stored = frappe.get_doc("Patient Encounter", encounter)
		self.assertEqual(stored.custom_workflow_state, "Awaiting Test")
		self.assertEqual([row.test_name for row in stored.custom_test_instructions], ["Malaria"])
		self.assertEqual(stored.custom_bandhu_diagnosis, [])

	def test_a_second_doctor_request_holding_a_stale_encounter_cannot_overwrite_the_first(self):
		"""The interleave the endpoints cannot see.

		Both requests pass their own state guard because both read "Waiting for Doctor"
		before either wrote. Nothing in `complete_encounter` re-checks after the read, so the
		only thing standing between the two is the framework's timestamp check — this asserts
		it holds for the endpoint, not just for a bare `doc.save()`.
		"""
		encounter = self.make_encounter()
		frappe.set_user(self.doctor_user)
		in_flight_copy = doctor_form.load_owned_encounter(encounter)

		call_over_http(f"{DOCTOR}.order_test", encounter=encounter, tests='["Hb"]')

		with patch.object(doctor_form, "load_owned_encounter", return_value=in_flight_copy):
			with self.assertRaises(frappe.TimestampMismatchError):
				call_over_http(
					f"{DOCTOR}.complete_encounter", encounter=encounter, diagnosis="Stale Diagnosis"
				)

		stored = frappe.get_doc("Patient Encounter", encounter)
		self.assertEqual(stored.custom_workflow_state, "Awaiting Test")
		self.assertEqual(stored.custom_bandhu_diagnosis, [])

	def test_a_double_fired_order_test_orders_the_tests_once(self):
		"""The 2026-08-10 stacked-click-handler bug, at the endpoint it fired against."""
		encounter = self.make_encounter()
		frappe.set_user(self.doctor_user)

		call_over_http(f"{DOCTOR}.order_test", encounter=encounter, tests='["Malaria", "Hb"]')
		with self.assertRaises(frappe.ValidationError):
			call_over_http(f"{DOCTOR}.order_test", encounter=encounter, tests='["Malaria", "Hb"]')

		stored = frappe.get_doc("Patient Encounter", encounter)
		self.assertEqual(len(stored.custom_test_instructions), 2)
		self.assertEqual(stored.custom_workflow_state, "Awaiting Test")

	def test_a_double_fired_dispense_completes_the_patient_once(self):
		encounter = self.make_encounter("Awaiting Medicine")
		doc = frappe.get_doc("Patient Encounter", encounter)
		doc.append("custom_bandhu_prescription", {"medicines": self.item, "quantity": 1})
		doc.save(ignore_permissions=True)
		prescription_row = doc.custom_bandhu_prescription[0].name

		frappe.set_user(self.nurse_user)
		call_over_http(
			f"{NURSE}.dispense_medicine",
			encounter=encounter,
			dispensed_rows=frappe.as_json([prescription_row]),
		)
		with self.assertRaises(frappe.ValidationError):
			call_over_http(
				f"{NURSE}.dispense_medicine",
				encounter=encounter,
				dispensed_rows=frappe.as_json([prescription_row]),
			)

		stored = frappe.get_doc("Patient Encounter", encounter)
		self.assertEqual(stored.custom_workflow_state, "Completed")
		self.assertEqual(len(stored.custom_bandhu_prescription), 1)
		self.assertEqual(stored.custom_bandhu_prescription[0].dispensed, 1)

	def test_a_stale_nurse_request_cannot_reopen_a_camp_the_first_one_closed(self):
		"""Two nurses on the camp controls: the loser must not resurrect a closed camp."""
		frappe.set_user(self.nurse_user)
		first_read = nurse_form.load_session_for_status_change(self.session)
		self.assertEqual(first_read.status, "In Progress")

		call_over_http(f"{NURSE}.end_session", session_name=self.session)
		closed = frappe.db.get_value(
			"Bandhu Clinic Session", self.session, ["status", "start_time", "end_time"], as_dict=True
		)

		with patch.object(nurse_form, "load_session_for_status_change", return_value=first_read):
			with self.assertRaises(frappe.ValidationError):
				call_over_http(f"{NURSE}.start_session", session_name=self.session)

		after = frappe.db.get_value(
			"Bandhu Clinic Session", self.session, ["status", "start_time", "end_time"], as_dict=True
		)
		self.assertEqual(after.status, "Completed")
		self.assertEqual(after.start_time, closed.start_time)
		self.assertEqual(after.end_time, closed.end_time)

	def test_a_double_submitted_registration_queues_the_patient_once(self):
		"""Two taps on Add to Queue must not put the same patient on the board twice."""
		patient = self.make_patient()
		frappe.set_user(self.cad_user)

		first = call_over_http(f"{CAD}.create_encounter", patient=patient, session=self.session)
		second = call_over_http(f"{CAD}.create_encounter", patient=patient, session=self.session)

		self.assertEqual(first, second)
		self.assertEqual(
			frappe.db.count("Patient Encounter", {"patient": patient, "custom_clinic_session": self.session}),
			1,
		)
		self.assertEqual(frappe.db.count("Patient Queue", {"patient": patient}), 1)
