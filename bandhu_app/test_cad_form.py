# Copyright (c) 2026, CMID and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import getdate, today

from bandhu_app.bandhu_app.baseline_test_fixtures import ensure_baseline_fixtures
from bandhu_app.bandhu_app.page.cad_form.cad_form import (
	cancel_visit,
	create_encounter,
	get_form_options,
	get_patient_card_html,
	get_session_status,
	get_today_queue,
	register_patient,
	search_patient,
)

EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = []


class IntegrationTestCadForm(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		baseline = ensure_baseline_fixtures()
		cls.clinic = baseline["clinic"]
		cls.site = baseline["site"]
		cls.project = baseline["project"]
		cls.gender = frappe.get_all("Gender", limit=1, pluck="name")[0]

		cls.cad_practitioner = cls._make_practitioner("Test CAD Alpha", "Clinic Assistant cum Driver")
		cls.doctor_practitioner = cls._make_practitioner("Test Doctor For CAD", "Doctor")

		cls.cad_user = cls._make_user(
			"test.cad.alpha@bandhuapp.test", cls.cad_practitioner, ["Clinic Assistant cum Driver"]
		)
		cls.no_role_user = cls._make_user("test.cad.norole@bandhuapp.test", None, [])

		cls.session = cls._make_session(cls.cad_practitioner, cls.doctor_practitioner)

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
	def _make_session(cls, assigned_driver, assigned_doctor, status="In Progress"):
		doc = frappe.get_doc(
			{
				"doctype": "Bandhu Clinic Session",
				"date": today(),
				"clinic": cls.clinic,
				"site": cls.site,
				"project": cls.project,
				"assigned_driver": assigned_driver,
				"assigned_doctor": assigned_doctor,
				"status": status,
			}
		).insert(ignore_permissions=True)
		return doc.name

	def _make_patient(self, first_name):
		return frappe.get_doc(
			{
				"doctype": "Patient",
				"first_name": first_name,
				"sex": self.gender,
			}
		).insert(ignore_permissions=True)

	def test_search_patient_finds_by_bandhu_id(self):
		patient = self._make_patient("Test Search Patient")
		bandhu_id = frappe.db.get_value("Patient", patient.name, "custom_bandhu_id")
		self.assertTrue(bandhu_id)

		frappe.set_user(self.cad_user)
		try:
			results = search_patient(bandhu_id)
		finally:
			frappe.set_user("Administrator")

		self.assertIn(patient.name, [r["name"] for r in results])

	def test_register_patient_creates_patient_with_custom_fields(self):
		frappe.set_user(self.cad_user)
		try:
			patient_name = register_patient(
				full_name="Test Register Patient",
				dob="1990-05-15",
				sex=self.gender,
				mobile="9876543210",
				height_cm=170,
				weight_kg=68,
				native_district="Ernakulam",
				company_name="Acme Textiles",
				abha_id="ABHA-TEST-001",
			)
		finally:
			frappe.set_user("Administrator")

		doc = frappe.get_doc("Patient", patient_name)
		self.assertEqual(doc.patient_name, "Test Register Patient")
		self.assertEqual(doc.sex, self.gender)
		self.assertEqual(str(doc.dob), "1990-05-15")
		self.assertEqual(doc.mobile, "9876543210")
		self.assertAlmostEqual(doc.custom_height_m, 1.70, places=2)
		self.assertEqual(doc.custom_weight_kg, 68)
		self.assertEqual(doc.custom_native_district, "Ernakulam")
		self.assertEqual(doc.custom_name_of_company, "Acme Textiles")
		self.assertEqual(doc.custom_abha_id, "ABHA-TEST-001")
		self.assertTrue(doc.custom_bandhu_id)

	def test_register_patient_estimates_dob_from_age_when_dob_unknown(self):
		frappe.set_user(self.cad_user)
		try:
			patient_name = register_patient(
				full_name="Test Age Only Patient",
				sex=self.gender,
				age=40,
			)
		finally:
			frappe.set_user("Administrator")

		doc = frappe.get_doc("Patient", patient_name)
		# Jan 1 of the birth year, not today's month/day minus 40 years — a migrant worker who
		# only knows their age didn't just have a birthday today, so that would be a fake date.
		self.assertEqual(str(doc.dob), f"{getdate().year - 40}-01-01")

	def test_register_patient_prefers_explicit_dob_over_age(self):
		frappe.set_user(self.cad_user)
		try:
			patient_name = register_patient(
				full_name="Test Dob Wins Patient",
				dob="1990-05-15",
				sex=self.gender,
				age=40,
			)
		finally:
			frappe.set_user("Administrator")

		doc = frappe.get_doc("Patient", patient_name)
		self.assertEqual(str(doc.dob), "1990-05-15")

	def test_register_patient_rejects_missing_dob_and_age(self):
		frappe.set_user(self.cad_user)
		try:
			with self.assertRaises(frappe.ValidationError):
				register_patient(full_name="Test No Dob No Age Patient", sex=self.gender)
		finally:
			frappe.set_user("Administrator")

	def test_register_patient_rejects_implausible_age(self):
		frappe.set_user(self.cad_user)
		try:
			with self.assertRaises(frappe.ValidationError):
				register_patient(full_name="Test Implausible Age Patient", sex=self.gender, age=200)
		finally:
			frappe.set_user("Administrator")

	def test_register_patient_stores_country_and_specified_sector(self):
		frappe.set_user(self.cad_user)
		try:
			patient_name = register_patient(
				full_name="Test Country Sector Patient",
				dob="1990-05-15",
				sex=self.gender,
				native_country="Nepal",
				occupation="Other",
				specify_sector="Street vendor",
			)
		finally:
			frappe.set_user("Administrator")

		doc = frappe.get_doc("Patient", patient_name)
		self.assertEqual(doc.custom_native_country, "Nepal")
		self.assertEqual(doc.custom_sector_of_employment, "Other")
		self.assertEqual(doc.custom_specify_employment_sector, "Street vendor")

	def test_register_patient_rejects_negative_height(self):
		frappe.set_user(self.cad_user)
		try:
			with self.assertRaises(frappe.ValidationError):
				register_patient(
					full_name="Negative Height Patient",
					dob="1990-05-15",
					sex=self.gender,
					height_cm=-170,
				)
		finally:
			frappe.set_user("Administrator")

	def test_register_patient_rejects_negative_weight(self):
		frappe.set_user(self.cad_user)
		try:
			with self.assertRaises(frappe.ValidationError):
				register_patient(
					full_name="Negative Weight Patient",
					dob="1990-05-15",
					sex=self.gender,
					weight_kg=-68,
				)
		finally:
			frappe.set_user("Administrator")

	def test_register_patient_rejects_malformed_mobile(self):
		frappe.set_user(self.cad_user)
		try:
			with self.assertRaises(frappe.ValidationError):
				register_patient(
					full_name="Bad Mobile Patient",
					dob="1990-05-15",
					sex=self.gender,
					mobile="12345",
				)
		finally:
			frappe.set_user("Administrator")

	def test_get_form_options_returns_real_state_and_sector_masters(self):
		frappe.set_user(self.cad_user)
		try:
			options = get_form_options()
		finally:
			frappe.set_user("Administrator")

		self.assertIn("Kerala", options["other_states"])
		self.assertIn("Bihar", options["major_states"])
		self.assertNotIn("Kerala", options["major_states"])
		self.assertIn("Construction", options["major_sectors"])
		self.assertIn("India", options["quick_countries"])
		self.assertIn("Nepal", options["quick_countries"])
		self.assertNotIn("India", options["other_countries"])

	def test_register_patient_rejects_state_not_in_master(self):
		frappe.set_user(self.cad_user)
		try:
			with self.assertRaises(frappe.exceptions.LinkValidationError):
				register_patient(
					full_name="Bad State Patient",
					dob="1990-05-15",
					sex=self.gender,
					native_state="Not A Real State",
				)
		finally:
			frappe.set_user("Administrator")

	def test_create_encounter_sets_workflow_state_and_syncs_queue(self):
		patient = self._make_patient("Test Encounter Patient")

		frappe.set_user(self.cad_user)
		try:
			encounter_name = create_encounter(patient.name, self.session)
		finally:
			frappe.set_user("Administrator")

		encounter = frappe.get_doc("Patient Encounter", encounter_name)
		self.assertEqual(encounter.custom_workflow_state, "Waiting for Doctor")
		self.assertEqual(encounter.practitioner, self.doctor_practitioner)

		queue_row = frappe.db.get_value(
			"Patient Queue",
			{"encounter": encounter_name},
			["current_stage", "status"],
			as_dict=True,
		)
		self.assertEqual(queue_row.current_stage, "Waiting")
		self.assertEqual(queue_row.status, "Active")

	def test_create_encounter_rejects_session_not_yet_started(self):
		patient = self._make_patient("Test Not Started Patient")
		planned_session = self._make_session(
			self.cad_practitioner, self.doctor_practitioner, status="Planned"
		)

		frappe.set_user(self.cad_user)
		try:
			with self.assertRaises(frappe.ValidationError):
				create_encounter(patient.name, planned_session)
		finally:
			frappe.set_user("Administrator")

		self.assertFalse(frappe.db.exists("Patient Encounter", {"patient": patient.name}))

	def test_cancel_visit_ends_the_encounter_and_clears_the_queue_row(self):
		patient = self._make_patient("Test Walkout Patient")

		frappe.set_user(self.cad_user)
		try:
			encounter_name = create_encounter(patient.name, self.session)
			cancel_visit(encounter_name, self.session)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(
			frappe.db.get_value("Patient Encounter", encounter_name, "custom_workflow_state"),
			"Cancelled",
		)

		queue_row = frappe.db.get_value(
			"Patient Queue",
			{"encounter": encounter_name},
			["current_stage", "status"],
			as_dict=True,
		)
		self.assertEqual(queue_row.current_stage, "Cancelled")
		self.assertEqual(queue_row.status, "Done")

	def test_cancel_visit_rejects_an_encounter_from_another_session(self):
		patient = self._make_patient("Test Cross Session Patient")
		other_session = self._make_session(self.cad_practitioner, self.doctor_practitioner)

		frappe.set_user(self.cad_user)
		try:
			encounter_name = create_encounter(patient.name, self.session)
			with self.assertRaises(frappe.ValidationError):
				cancel_visit(encounter_name, other_session)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(
			frappe.db.get_value("Patient Encounter", encounter_name, "custom_workflow_state"),
			"Waiting for Doctor",
		)

	def test_cancel_visit_cannot_be_repeated(self):
		patient = self._make_patient("Test Double Cancel Patient")

		frappe.set_user(self.cad_user)
		try:
			encounter_name = create_encounter(patient.name, self.session)
			cancel_visit(encounter_name, self.session)
			with self.assertRaises(frappe.ValidationError):
				cancel_visit(encounter_name, self.session)
		finally:
			frappe.set_user("Administrator")

	# A patient who left and came back the same day must be registerable again; the cancelled
	# encounter used to satisfy create_encounter's "already registered" lookup and be handed back.
	def test_a_cancelled_visit_does_not_block_re_registration(self):
		patient = self._make_patient("Test Returning Patient")

		frappe.set_user(self.cad_user)
		try:
			first = create_encounter(patient.name, self.session)
			cancel_visit(first, self.session)
			second = create_encounter(patient.name, self.session)
		finally:
			frappe.set_user("Administrator")

		self.assertNotEqual(first, second)
		self.assertEqual(
			frappe.db.get_value("Patient Encounter", second, "custom_workflow_state"),
			"Waiting for Doctor",
		)

	def test_get_today_queue_carries_the_encounter_for_each_row(self):
		patient = self._make_patient("Test Queue Encounter Patient")

		frappe.set_user(self.cad_user)
		try:
			encounter_name = create_encounter(patient.name, self.session)
			rows = get_today_queue(self.session)
		finally:
			frappe.set_user("Administrator")

		row = next(row for row in rows if row["patient"] == patient.name)
		self.assertEqual(row["encounter"], encounter_name)

	def test_get_patient_card_html_renders_for_cad_without_patient_permission(self):
		patient = self._make_patient("Test Card Patient")
		clinic_id = frappe.db.get_value("Patient", patient.name, "custom_bandhu_id")

		frappe.set_user(self.cad_user)
		try:
			self.assertFalse(frappe.has_permission("Patient", "print"))
			card_html = get_patient_card_html(patient.name)
		finally:
			frappe.set_user("Administrator")

		self.assertIn("bandhu-card", card_html)
		self.assertIn(clinic_id, card_html.replace(" ", ""))
		self.assertFalse(frappe.flags.ignore_print_permissions)

	def test_get_patient_card_html_rejects_unknown_patient(self):
		frappe.set_user(self.cad_user)
		try:
			self.assertRaises(frappe.DoesNotExistError, get_patient_card_html, "No Such Patient")
		finally:
			frappe.set_user("Administrator")

	def test_register_patient_rejects_a_cancelled_session(self):
		cancelled_session = self._make_session(
			self.cad_practitioner, self.doctor_practitioner, status="Cancelled"
		)

		frappe.set_user(self.cad_user)
		try:
			with self.assertRaises(frappe.ValidationError):
				register_patient(
					full_name="Cancelled Camp Patient",
					dob="1990-01-01",
					sex=self.gender,
					session=cancelled_session,
				)
		finally:
			frappe.set_user("Administrator")

		self.assertFalse(frappe.db.exists("Patient", {"patient_name": "Cancelled Camp Patient"}))

	def test_register_patient_rejects_a_session_that_has_not_started(self):
		planned_session = self._make_session(
			self.cad_practitioner, self.doctor_practitioner, status="Planned"
		)

		frappe.set_user(self.cad_user)
		try:
			with self.assertRaises(frappe.ValidationError):
				register_patient(
					full_name="Planned Camp Patient",
					dob="1990-01-01",
					sex=self.gender,
					session=planned_session,
				)
		finally:
			frappe.set_user("Administrator")

		self.assertFalse(frappe.db.exists("Patient", {"patient_name": "Planned Camp Patient"}))

	def test_unprivileged_user_is_blocked(self):
		patient = self._make_patient("Test Blocked Patient")

		frappe.set_user(self.no_role_user)
		try:
			self.assertRaises(frappe.PermissionError, get_session_status)
			self.assertRaises(frappe.PermissionError, search_patient, "x")
			self.assertRaises(
				frappe.PermissionError,
				register_patient,
				full_name="Blocked Patient",
				dob="1990-01-01",
				sex=self.gender,
			)
			self.assertRaises(frappe.PermissionError, create_encounter, patient.name, self.session)
			self.assertRaises(frappe.PermissionError, get_today_queue, self.session)
			self.assertRaises(frappe.PermissionError, get_patient_card_html, patient.name)
		finally:
			frappe.set_user("Administrator")

	def test_search_patient_is_recorded_in_the_access_log(self):
		patient = self._make_patient("Test Audited Search Patient")
		bandhu_id = frappe.db.get_value("Patient", patient.name, "custom_bandhu_id")

		frappe.set_user(self.cad_user)
		try:
			search_patient(bandhu_id)
		finally:
			frappe.set_user("Administrator")

		self.assertTrue(
			frappe.db.exists(
				"Access Log",
				{
					"user": self.cad_user,
					"export_from": "Patient",
					"method": "CAD Patient Search",
					"filters": bandhu_id,
				},
			)
		)

	def test_patient_card_render_is_recorded_against_the_patient(self):
		patient = self._make_patient("Test Audited Card Patient")

		frappe.set_user(self.cad_user)
		try:
			get_patient_card_html(patient.name)
		finally:
			frappe.set_user("Administrator")

		self.assertTrue(
			frappe.db.exists(
				"Access Log",
				{
					"user": self.cad_user,
					"export_from": "Patient",
					"method": "CAD Patient Card",
					"reference_document": patient.name,
				},
			)
		)

	def test_a_blocked_card_render_leaves_no_access_log_row(self):
		patient = self._make_patient("Test Unlogged Card Patient")

		frappe.set_user(self.no_role_user)
		try:
			self.assertRaises(frappe.PermissionError, get_patient_card_html, patient.name)
		finally:
			frappe.set_user("Administrator")

		self.assertFalse(frappe.db.exists("Access Log", {"reference_document": patient.name}))
