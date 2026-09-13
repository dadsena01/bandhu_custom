# Copyright (c) 2026, CMID and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import today

from bandhu_app.bandhu_app.baseline_test_fixtures import ensure_baseline_fixtures
from bandhu_app.bandhu_app.page.new_session.new_session import (
	as_session_draft,
	check_clashes,
	create_session,
	get_form_options,
)

EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = []


def make_plain_user() -> str:
	email = "new-session-test-plain@example.com"
	if frappe.db.exists("User", email):
		return email
	return (
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "No Role",
				"send_welcome_email": 0,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


class IntegrationTestNewSession(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		baseline = ensure_baseline_fixtures()
		cls.clinic = baseline["clinic"]
		cls.project = frappe.db.get_value("Clinic", cls.clinic, "project")
		cls.site = baseline["site"]
		cls.unit = baseline["unit"]
		cls.doctor = baseline["doctor"]

	def session_values(self, **overrides):
		values = {
			"project": self.project,
			"site": self.site,
			"clinic": self.clinic,
			"unit": self.unit,
			"date": today(),
			"planned_start_time": "09:30:00",
			"planned_end_time": "13:30:00",
		}
		values.update(overrides)
		return frappe.as_json(values)

	def test_form_options_only_offer_practitioners_of_that_role(self):
		options = get_form_options()

		self.assertTrue(options["sites"])
		self.assertTrue(options["doctors"])
		roles = {
			frappe.db.get_value("Healthcare Practitioner", row["value"], "custom_role")
			for row in options["doctors"]
		}
		self.assertEqual(roles, {"Doctor"})

	def test_create_inserts_a_planned_ad_hoc_session(self):
		result = create_session(self.session_values())

		session = frappe.get_doc("Bandhu Clinic Session", result["name"])
		self.assertEqual(session.status, "Planned")
		self.assertEqual(str(session.date), today())
		self.assertIsNone(session.session_schedule)

	def test_create_rejects_a_payload_with_no_date(self):
		with self.assertRaises(frappe.ValidationError):
			create_session(self.session_values(date=""))

	def test_check_clashes_reports_a_doctor_already_booked_that_day(self):
		booked = create_session(self.session_values(assigned_doctor=self.doctor))
		self.assertTrue(frappe.db.exists("Bandhu Clinic Session", booked["name"]))

		clashes = check_clashes(self.session_values(assigned_doctor=self.doctor))

		self.assertEqual({clash["role"] for clash in clashes}, {"Doctor"})

	def test_check_clashes_reports_nothing_for_an_unassigned_session(self):
		self.assertEqual(check_clashes(self.session_values()), [])

	def test_payload_cannot_set_fields_the_form_does_not_own(self):
		draft = as_session_draft(
			frappe.as_json(
				{
					"site": self.site,
					"date": today(),
					"owner": "attacker@example.com",
					"name": "BCS-HIJACKED",
					"session_schedule": "SCH-00001",
				}
			)
		)

		self.assertNotEqual(draft.owner, "attacker@example.com")
		self.assertNotEqual(draft.name, "BCS-HIJACKED")
		self.assertIsNone(draft.session_schedule)

	def test_a_user_without_the_role_is_blocked(self):
		user = frappe.session.user
		try:
			frappe.set_user(make_plain_user())
			with self.assertRaises(frappe.PermissionError):
				get_form_options()
			with self.assertRaises(frappe.PermissionError):
				create_session(self.session_values())
		finally:
			frappe.set_user(user)
