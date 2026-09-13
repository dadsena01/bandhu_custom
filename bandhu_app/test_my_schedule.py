# Copyright (c) 2026, CMID and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from bandhu_app.bandhu_app.baseline_test_fixtures import ensure_baseline_fixtures
from bandhu_app.bandhu_app.page.my_schedule.my_schedule import get_my_schedule
from bandhu_app.bandhu_app.utils.session import SCHEDULE_MAX_DAYS, find_my_schedule

EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = []


class IntegrationTestMySchedule(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		baseline = ensure_baseline_fixtures()
		cls.clinic = baseline["clinic"]
		cls.site = baseline["site"]

		cls.doctor = cls.make_practitioner("Schedule Test Doctor", "Doctor", "9800000001")
		cls.nurse = cls.make_practitioner("Schedule Test Nurse", "Nurse", "9800000002")
		cls.driver = cls.make_practitioner("Schedule Test Driver", "Clinic Assistant cum Driver", None)
		cls.other_doctor = cls.make_practitioner("Schedule Other Doctor", "Doctor", "9800000003")

	@classmethod
	def make_practitioner(cls, first_name, custom_role, mobile_phone):
		return (
			frappe.get_doc(
				{
					"doctype": "Healthcare Practitioner",
					"first_name": first_name,
					"status": "Active",
					"custom_role": custom_role,
					"mobile_phone": mobile_phone,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def make_session(self, date, **overrides):
		values = {
			"doctype": "Bandhu Clinic Session",
			"date": date,
			"clinic": self.clinic,
			"site": self.site,
			"assigned_doctor": self.doctor,
			"assigned_nurse": self.nurse,
			"assigned_driver": self.driver,
		}
		values.update(overrides)
		return frappe.get_doc(values).insert(ignore_permissions=True)

	def dates_for(self, practitioner, **kwargs):
		return [row["date"] for row in find_my_schedule(practitioner, **kwargs)]

	def test_todays_session_is_included(self):
		self.make_session(today())

		self.assertIn(today(), self.dates_for(self.doctor))

	def test_yesterdays_session_is_dropped(self):
		self.make_session(add_days(today(), -1))

		self.assertNotIn(add_days(today(), -1), self.dates_for(self.doctor))

	def test_a_cancelled_session_still_shows(self):
		session = self.make_session(add_days(today(), 3))
		session.db_set("status", "Cancelled")

		row = next(r for r in find_my_schedule(self.doctor) if r["name"] == session.name)
		self.assertEqual(row["status"], "Cancelled")

	def test_nurse_and_driver_see_the_same_session(self):
		session = self.make_session(add_days(today(), 2))

		for practitioner in (self.nurse, self.driver):
			names = [row["name"] for row in find_my_schedule(practitioner)]
			self.assertIn(session.name, names)

	def test_someone_elses_session_is_not_listed(self):
		session = self.make_session(add_days(today(), 2))

		names = [row["name"] for row in find_my_schedule(self.other_doctor)]
		self.assertNotIn(session.name, names)

	def test_session_beyond_the_window_is_dropped(self):
		self.make_session(add_days(today(), 40))

		self.assertNotIn(add_days(today(), 40), self.dates_for(self.doctor, days=7))
		self.assertIn(add_days(today(), 40), self.dates_for(self.doctor, days=60))

	def test_window_is_capped(self):
		far = add_days(today(), SCHEDULE_MAX_DAYS + 30)
		self.make_session(far)

		self.assertNotIn(far, self.dates_for(self.doctor, days=SCHEDULE_MAX_DAYS + 60))

	def test_row_carries_the_site_location_and_team(self):
		session = self.make_session(add_days(today(), 1))
		location = frappe.db.get_value("Site", self.site, "location")
		expected = frappe.db.get_value(
			"Bandhu Location", location, ["lsg", "district", "phcchc"], as_dict=True
		)

		row = next(r for r in find_my_schedule(self.doctor) if r["name"] == session.name)

		self.assertEqual(row["lsg"], expected.lsg)
		self.assertEqual(row["district"], expected.district)
		self.assertEqual(row["phcchc"], expected.phcchc)

		team = {member["role"]: member for member in row["team"]}
		self.assertEqual(set(team), {"Doctor", "Nurse", "Driver"})
		self.assertEqual(team["Doctor"]["mobile"], "9800000001")
		# A driver without a number must still appear — the team list is not a contact list.
		self.assertIsNone(team["Driver"]["mobile"])

	def test_a_user_without_any_clinic_role_is_blocked(self):
		email = "my-schedule-test-plain@example.com"
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": "No Role",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)

		user = frappe.session.user
		try:
			frappe.set_user(email)
			with self.assertRaises(frappe.PermissionError):
				get_my_schedule()
		finally:
			frappe.set_user(user)

	def test_endpoint_reports_an_unlinked_account(self):
		user = frappe.session.user
		try:
			frappe.set_user("Administrator")
			result = get_my_schedule()
		finally:
			frappe.set_user(user)

		self.assertEqual(result["sessions"], [])
		self.assertTrue(result["message"])
