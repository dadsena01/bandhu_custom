# Copyright (c) 2026, CMID and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, add_years, nowtime, today

from bandhu_app.bandhu_app.baseline_test_fixtures import ensure_baseline_fixtures
from bandhu_app.bandhu_app.report.bandhu_tests_report.bandhu_tests_report import execute

EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = []


class IntegrationTestTestsReport(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		baseline = ensure_baseline_fixtures()
		cls.clinic = baseline["clinic"]
		cls.project = baseline["project"]
		cls.appointment_type = baseline["appointment_type"]
		cls.state = baseline["state"]

		cls.doctor = (
			frappe.get_doc(
				{
					"doctype": "Healthcare Practitioner",
					"first_name": "Tests Report Doctor",
					"status": "Active",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

		cls.location = (
			frappe.get_doc(
				{
					"doctype": "Bandhu Location",
					"location_name": f"Tests Report Location {frappe.generate_hash(length=6)}",
					"lsg": "Tests Report Panchayat",
					"district": "Ernakulam",
					"state": "Kerala",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def setUp(self):
		# Every test filters on its own site: records created by one test are still
		# visible to the next, so a shared site would make the row counts cumulative.
		self.site = (
			frappe.get_doc(
				{
					"doctype": "Site",
					"site_name": f"Tests Report Worksite {frappe.generate_hash(length=6)}",
					"location": self.location,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _make_session(self, date=None):
		return (
			frappe.get_doc(
				{
					"doctype": "Bandhu Clinic Session",
					"date": date or today(),
					"clinic": self.clinic,
					"site": self.site,
					"project": self.project,
					"assigned_doctor": self.doctor,
					"status": "In Progress",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _make_patient(self, sex="Male", age_years=35):
		return (
			frappe.get_doc(
				{
					"doctype": "Patient",
					"first_name": f"Tests Report Patient {frappe.generate_hash(length=8)}",
					"sex": sex,
					"dob": add_years(today(), -age_years),
					"custom_native_state": self.state,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _make_encounter(self, session, tests, patient=None):
		return frappe.get_doc(
			{
				"doctype": "Patient Encounter",
				"patient": patient or self._make_patient(),
				"practitioner": self.doctor,
				"encounter_date": today(),
				"encounter_time": nowtime(),
				"appointment_type": self.appointment_type,
				"custom_clinic_session": session,
				"custom_workflow_state": "Awaiting Test",
				"custom_test_instructions": tests,
			}
		).insert(ignore_permissions=True)

	def _run(self, **filters):
		filters.setdefault("from_date", today())
		filters.setdefault("to_date", today())
		filters.setdefault("site", self.site)
		return execute(filters)[1]

	def test_one_row_per_test_with_the_patient_resolved(self):
		session = self._make_session()
		patient = self._make_patient(sex="Female", age_years=20)
		self._make_encounter(
			session,
			[{"test_name": "Malaria", "result_type": "Positive"}, {"test_name": "Hb"}],
			patient=patient,
		)

		rows = self._run()
		self.assertEqual(len(rows), 2)
		self.assertEqual({row["test_name"] for row in rows}, {"Malaria", "Hb"})

		malaria = next(row for row in rows if row["test_name"] == "Malaria")
		self.assertEqual(malaria["sex"], "Female")
		self.assertEqual(malaria["age_group"], "15-29")
		self.assertEqual(malaria["native_state"], self.state)
		self.assertEqual(malaria["lsg"], "Tests Report Panchayat")

	def test_a_test_with_no_result_reads_as_pending(self):
		session = self._make_session()
		self._make_encounter(session, [{"test_name": "Dengue"}])

		row = self._run()[0]
		self.assertEqual(row["result"], "Pending")

	def test_result_filter_separates_pending_from_done(self):
		session = self._make_session()
		self._make_encounter(
			session, [{"test_name": "Malaria", "result_type": "Negative"}, {"test_name": "Dengue"}]
		)

		self.assertEqual([row["test_name"] for row in self._run(result="Pending")], ["Dengue"])
		self.assertEqual([row["test_name"] for row in self._run(result="Negative")], ["Malaria"])

	def test_test_filter_narrows_to_one_test_type(self):
		session = self._make_session()
		self._make_encounter(session, [{"test_name": "Malaria"}, {"test_name": "Dengue"}])

		rows = self._run(test_name="Malaria")
		self.assertEqual([row["test_name"] for row in rows], ["Malaria"])

	def test_camps_outside_the_period_are_excluded(self):
		self._make_encounter(self._make_session(add_days(today(), -10)), [{"test_name": "Hb"}])

		self.assertEqual(self._run(), [])

	def test_summary_counts_ordered_done_and_positive(self):
		session = self._make_session()
		self._make_encounter(
			session,
			[
				{"test_name": "Malaria", "result_type": "Positive"},
				{"test_name": "Dengue", "result_type": "Negative"},
				{"test_name": "Hb"},
			],
		)

		summary = {
			card["label"]: card["value"]
			for card in execute(
				{
					"from_date": today(),
					"to_date": today(),
					"site": self.site,
				}
			)[4]
		}
		self.assertEqual(summary["Tests Ordered"], 3)
		self.assertEqual(summary["Tests Done"], 2)
		self.assertEqual(summary["Positive"], 1)
		self.assertEqual(summary["Awaiting Result"], 1)
		self.assertEqual(summary["Patients Tested"], 1)
