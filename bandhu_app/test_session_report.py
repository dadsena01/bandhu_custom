# Copyright (c) 2026, CMID and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowtime, today

from bandhu_app.bandhu_app.baseline_test_fixtures import ensure_baseline_fixtures
from bandhu_app.bandhu_app.report.bandhu_session_report.bandhu_session_report import execute

EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = []


class IntegrationTestSessionReport(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		baseline = ensure_baseline_fixtures()
		cls.clinic = baseline["clinic"]
		cls.project = baseline["project"]
		cls.appointment_type = baseline["appointment_type"]
		cls.item = baseline["item"]
		cls.gender = frappe.get_all("Gender", limit=1, pluck="name")[0]

		cls.doctor = cls._make_practitioner("Test Report Doctor")

		cls.location = cls._make_location("Report Test Panchayat")
		cls.other_location = cls._make_location("Report Test Municipality")
		cls.site = cls._make_site("Report Test Worksite", cls.location)
		cls.other_site = cls._make_site("Report Test Quarry", cls.other_location)

	@classmethod
	def _make_practitioner(cls, first_name):
		return (
			frappe.get_doc(
				{"doctype": "Healthcare Practitioner", "first_name": first_name, "status": "Active"}
			)
			.insert(ignore_permissions=True)
			.name
		)

	@classmethod
	def _make_location(cls, lsg):
		return (
			frappe.get_doc(
				{
					"doctype": "Bandhu Location",
					"location_name": f"{lsg} {frappe.generate_hash(length=6)}",
					"lsg": lsg,
					"district": "Ernakulam",
					"state": "Kerala",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	@classmethod
	def _make_site(cls, site_name, location):
		return (
			frappe.get_doc(
				{
					"doctype": "Site",
					"site_name": f"{site_name} {frappe.generate_hash(length=6)}",
					"location": location,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _make_session(self, date, site=None, status="Completed"):
		return (
			frappe.get_doc(
				{
					"doctype": "Bandhu Clinic Session",
					"date": date,
					"clinic": self.clinic,
					"site": site or self.site,
					"project": self.project,
					"assigned_doctor": self.doctor,
					"status": status,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _make_patient(self):
		return (
			frappe.get_doc(
				{
					"doctype": "Patient",
					"first_name": f"Report Patient {frappe.generate_hash(length=8)}",
					"sex": self.gender,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _make_encounter(self, session, patient=None, tests=None, prescriptions=None, state="Completed"):
		return frappe.get_doc(
			{
				"doctype": "Patient Encounter",
				"patient": patient or self._make_patient(),
				"practitioner": self.doctor,
				"encounter_date": today(),
				"encounter_time": nowtime(),
				"appointment_type": self.appointment_type,
				"custom_clinic_session": session,
				"custom_workflow_state": state,
				"custom_test_instructions": tests or [],
				"custom_bandhu_prescription": prescriptions or [],
			}
		).insert(ignore_permissions=True)

	def _run(self, **filters):
		filters.setdefault("from_date", today())
		filters.setdefault("to_date", today())
		_columns, rows = execute(filters)[:2]
		return rows

	def _row_for(self, rows, session):
		return next(row for row in rows if row["session"] == session)

	def test_counts_patients_and_splits_new_from_repeat(self):
		returning_patient = self._make_patient()
		first_session = self._make_session(add_days(today(), -1))
		self._make_encounter(first_session, patient=returning_patient)

		session = self._make_session(today())
		self._make_encounter(session, patient=returning_patient)
		self._make_encounter(session)

		row = self._row_for(self._run(), session)
		self.assertEqual(row["patients"], 2)
		self.assertEqual(row["new_patients"], 1)
		self.assertEqual(row["repeat_patients"], 1)

	def test_counts_tests_and_medicines_ordered_versus_done(self):
		session = self._make_session(today())
		self._make_encounter(
			session,
			tests=[
				{"test_name": "Malaria", "result_type": "Negative"},
				{"test_name": "Dengue"},
			],
			prescriptions=[
				{"medicines": self.item, "quantity": 1, "dispensed": 1},
				{"medicines": self.item, "quantity": 1},
			],
		)

		row = self._row_for(self._run(), session)
		self.assertEqual(row["tests_ordered"], 2)
		self.assertEqual(row["tests_done"], 1)
		self.assertEqual(row["medicines_prescribed"], 2)
		self.assertEqual(row["medicines_dispensed"], 1)

	def test_date_filter_excludes_camps_outside_the_period(self):
		inside = self._make_session(today())
		outside = self._make_session(add_days(today(), 30))

		names = [row["session"] for row in self._run()]
		self.assertIn(inside, names)
		self.assertNotIn(outside, names)

	def test_location_filter_narrows_to_that_lsgs_sites(self):
		mine = self._make_session(today(), site=self.site)
		theirs = self._make_session(today(), site=self.other_site)

		names = [row["session"] for row in self._run(location=self.location)]
		self.assertIn(mine, names)
		self.assertNotIn(theirs, names)

	def test_site_column_shows_the_readable_name_not_the_record_id(self):
		session = self._make_session(today())
		row = self._row_for(self._run(), session)

		self.assertEqual(row["site"], frappe.db.get_value("Site", self.site, "site_name"))
		self.assertEqual(row["lsg"], "Report Test Panchayat")

	def test_rejects_a_period_that_runs_backwards(self):
		self.assertRaises(
			frappe.ValidationError,
			execute,
			{"from_date": today(), "to_date": add_days(today(), -1)},
		)
