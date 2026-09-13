# Copyright (c) 2026, CMID and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import nowtime, today

from bandhu_app.bandhu_app.baseline_test_fixtures import ensure_baseline_fixtures
from bandhu_app.bandhu_app.report.bandhu_clinic_report.bandhu_clinic_report import execute

EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = []


class IntegrationTestClinicReport(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		baseline = ensure_baseline_fixtures()
		cls.clinic = baseline["clinic"]
		cls.project = baseline["project"]
		cls.appointment_type = baseline["appointment_type"]
		cls.gender = frappe.get_all("Gender", limit=1, pluck="name")[0]

		cls.doctor = (
			frappe.get_doc(
				{
					"doctype": "Healthcare Practitioner",
					"first_name": "Clinic Report Doctor",
					"status": "Active",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def setUp(self):
		# Records from an earlier test are still visible to this one, so each test works
		# inside its own site and filters on it.
		self.location = frappe.get_doc(
			{
				"doctype": "Bandhu Location",
				"location_name": f"Clinic Report Location {frappe.generate_hash(length=6)}",
				"lsg": f"Clinic Report LSG {frappe.generate_hash(length=4)}",
				"district": "Ernakulam",
				"state": "Kerala",
			}
		).insert(ignore_permissions=True)

		self.site = (
			frappe.get_doc(
				{
					"doctype": "Site",
					"site_name": f"Clinic Report Worksite {frappe.generate_hash(length=6)}",
					"location": self.location.name,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _make_session(self, status="Completed"):
		return (
			frappe.get_doc(
				{
					"doctype": "Bandhu Clinic Session",
					"date": today(),
					"clinic": self.clinic,
					"site": self.site,
					"project": self.project,
					"assigned_doctor": self.doctor,
					"status": status,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _make_encounter(self, session):
		patient = (
			frappe.get_doc(
				{
					"doctype": "Patient",
					"first_name": f"Clinic Report Patient {frappe.generate_hash(length=8)}",
					"sex": self.gender,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

		return frappe.get_doc(
			{
				"doctype": "Patient Encounter",
				"patient": patient,
				"practitioner": self.doctor,
				"encounter_date": today(),
				"encounter_time": nowtime(),
				"appointment_type": self.appointment_type,
				"custom_clinic_session": session,
				"custom_workflow_state": "Completed",
			}
		).insert(ignore_permissions=True)

	def _run(self, **filters):
		filters.setdefault("from_date", today())
		filters.setdefault("to_date", today())
		filters.setdefault("group_by", "Clinic")
		filters.setdefault("site", self.site)
		return execute(filters)[1]

	def test_several_camps_collapse_into_one_row_per_clinic(self):
		for _unused in range(2):
			session = self._make_session()
			self._make_encounter(session)
			self._make_encounter(session)

		rows = self._run()
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["group"], self.clinic)
		self.assertEqual(rows[0]["camps_held"], 2)
		self.assertEqual(rows[0]["patients"], 4)

	def test_grouping_by_lsg_uses_the_sites_location(self):
		self._make_encounter(self._make_session())

		rows = self._run(group_by="LSG")
		self.assertEqual(rows[0]["group"], self.location.lsg)

	def test_planned_and_cancelled_camps_are_not_counted_as_held(self):
		self._make_session()
		self._make_session(status="Planned")
		self._make_session(status="Cancelled")

		row = self._run()[0]
		self.assertEqual(row["camps_planned"], 3)
		self.assertEqual(row["camps_held"], 1)
		self.assertEqual(row["camps_cancelled"], 1)

	def test_patients_per_camp_divides_by_camps_held_not_scheduled(self):
		session = self._make_session()
		self._make_encounter(session)
		self._make_encounter(session)
		self._make_session(status="Planned")

		self.assertEqual(self._run()[0]["patients_per_camp"], 2)

	def test_rejects_an_unknown_grouping(self):
		self.assertRaises(
			frappe.ValidationError,
			execute,
			{"from_date": today(), "to_date": today(), "group_by": "Vehicle"},
		)
