# Copyright (c) 2026, CMID and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today

from bandhu_app.bandhu_app.baseline_test_fixtures import ensure_baseline_fixtures
from bandhu_app.bandhu_app.utils.session import find_active_session

EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = []


class IntegrationTestBandhuClinicSession(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		baseline = ensure_baseline_fixtures()
		cls.clinic = baseline["clinic"]
		cls.site = baseline["site"]
		cls.project = baseline["project"]

		cls.doctor = cls._make_practitioner("Role Test Doctor", "Doctor")
		cls.nurse = cls._make_practitioner("Role Test Nurse", "Nurse")
		cls.driver = cls._make_practitioner("Role Test Driver", "Clinic Assistant cum Driver")

	@classmethod
	def _make_practitioner(cls, first_name, custom_role):
		return (
			frappe.get_doc(
				{
					"doctype": "Healthcare Practitioner",
					"first_name": first_name,
					"status": "Active",
					"custom_role": custom_role,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _session_fields(self, **overrides):
		fields = {
			"doctype": "Bandhu Clinic Session",
			"date": today(),
			"clinic": self.clinic,
			"site": self.site,
			"project": self.project,
		}
		fields.update(overrides)
		return fields

	def test_correct_role_assignment_saves(self):
		doc = frappe.get_doc(
			self._session_fields(
				assigned_doctor=self.doctor,
				assigned_nurse=self.nurse,
				assigned_driver=self.driver,
			)
		)
		doc.insert(ignore_permissions=True)
		self.assertTrue(doc.name)

	def test_wrong_role_as_doctor_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(self._session_fields(assigned_doctor=self.nurse)).insert(ignore_permissions=True)

	def test_wrong_role_as_nurse_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(self._session_fields(assigned_nurse=self.driver)).insert(ignore_permissions=True)

	def test_wrong_role_as_driver_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(self._session_fields(assigned_driver=self.doctor)).insert(ignore_permissions=True)

	def test_find_active_session_prefers_in_progress_over_planned(self):
		driver = self._make_practitioner("Priority Test Driver", "Clinic Assistant cum Driver")
		frappe.get_doc(self._session_fields(assigned_driver=driver, status="Planned")).insert(
			ignore_permissions=True
		)
		in_progress = frappe.get_doc(
			self._session_fields(assigned_driver=driver, status="In Progress")
		).insert(ignore_permissions=True)

		result = find_active_session("assigned_driver", driver)
		self.assertEqual(result.name, in_progress.name)
		self.assertEqual(result.status, "In Progress")

	def test_find_active_session_ignores_completed(self):
		driver = self._make_practitioner("Completed Test Driver", "Clinic Assistant cum Driver")
		frappe.get_doc(self._session_fields(assigned_driver=driver, status="Completed")).insert(
			ignore_permissions=True
		)

		result = find_active_session("assigned_driver", driver)
		self.assertIsNone(result)

	def test_find_active_session_returns_none_with_no_sessions(self):
		driver = self._make_practitioner("Idle Test Driver", "Clinic Assistant cum Driver")
		result = find_active_session("assigned_driver", driver)
		self.assertIsNone(result)

	def test_find_active_session_returns_the_readable_site_name(self):
		driver = self._make_practitioner("Site Label Test Driver", "Clinic Assistant cum Driver")
		# Site is autonamed SITE-.####, so a fresh record is guaranteed to have an id that
		# differs from its name — which is the whole thing being asserted.
		site = frappe.get_doc({"doctype": "Site", "site_name": "Site Label Test Camp"}).insert(
			ignore_permissions=True
		)
		self.assertNotEqual(site.name, site.site_name)

		frappe.get_doc(
			self._session_fields(assigned_driver=driver, status="In Progress", site=site.name)
		).insert(ignore_permissions=True)

		result = find_active_session("assigned_driver", driver)

		self.assertEqual(result.site, "Site Label Test Camp")
