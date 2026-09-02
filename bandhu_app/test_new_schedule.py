# Copyright (c) 2026, CMID and Contributors
# See license.txt

from datetime import timedelta

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from bandhu_app.bandhu_app.baseline_test_fixtures import ensure_baseline_fixtures
from bandhu_app.bandhu_app.page.new_schedule.new_schedule import (
	as_draft,
	clock_value,
	create_schedule,
	get_form_options,
	preview_schedule,
)

EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = []


def make_plain_user() -> str:
	email = "new-schedule-test-plain@example.com"
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


class IntegrationTestNewSchedule(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		baseline = ensure_baseline_fixtures()
		cls.clinic = baseline["clinic"]
		cls.site = baseline["site"]
		cls.unit = baseline["unit"]
		cls.doctor = baseline["doctor"]

	def wizard_values(self, **overrides):
		values = {
			"site": self.site,
			"clinic": self.clinic,
			"unit": self.unit,
			"frequency": "Weekly",
			"weekdays": ["Monday", "Thursday"],
			"planned_start_time": "09:30:00",
			"planned_end_time": "13:30:00",
			"valid_from": today(),
			"valid_upto": add_days(today(), 21),
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

	def test_time_defaults_are_zero_padded(self):
		# An unpadded value makes the browser's time input render blank.
		self.assertEqual(clock_value(timedelta(seconds=34200), "09:30:00"), "09:30:00")
		self.assertEqual(clock_value(None, "09:30:00"), "09:30:00")

	def test_preview_returns_dates_without_creating_anything(self):
		before = frappe.db.count("Bandhu Session Schedule")

		result = preview_schedule(self.wizard_values())

		self.assertTrue(result["dates"])
		self.assertTrue(all(day >= today() for day in result["dates"]))
		self.assertEqual(frappe.db.count("Bandhu Session Schedule"), before)

	def test_preview_of_an_impossible_pattern_is_empty(self):
		result = preview_schedule(self.wizard_values(weekdays=[]))

		self.assertEqual(result["dates"], [])
		self.assertEqual(result["total"], 0)

	def test_create_builds_every_camp_the_wizard_promised(self):
		result = create_schedule(self.wizard_values())

		self.assertTrue(frappe.db.exists("Bandhu Session Schedule", result["name"]))
		self.assertTrue(result["scheduled"])
		# `scheduled` is read off the pattern because the camps are built by a background job.
		# It still has to match what that job goes on to create.
		self.assertEqual(
			result["scheduled"],
			frappe.db.count("Bandhu Clinic Session", {"session_schedule": result["name"]}),
		)

	def test_preview_reports_a_doctor_already_booked_elsewhere(self):
		booked = create_schedule(self.wizard_values(assigned_doctor=self.doctor))
		self.assertTrue(booked["scheduled"])

		result = preview_schedule(self.wizard_values(assigned_doctor=self.doctor))

		self.assertTrue(result["clashes"])
		self.assertEqual({clash["role"] for clash in result["clashes"]}, {"Doctor"})

	def test_payload_cannot_set_fields_the_wizard_does_not_own(self):
		draft = as_draft(
			frappe.as_json(
				{
					"site": self.site,
					"weekdays": ["Monday"],
					"owner": "attacker@example.com",
					"name": "SCH-HIJACKED",
					"last_generated_upto": "2099-01-01",
				}
			)
		)

		self.assertNotEqual(draft.owner, "attacker@example.com")
		self.assertNotEqual(draft.name, "SCH-HIJACKED")
		self.assertIsNone(draft.last_generated_upto)

	def test_a_user_without_the_role_is_blocked(self):
		user = frappe.session.user
		try:
			frappe.set_user(make_plain_user())
			with self.assertRaises(frappe.PermissionError):
				get_form_options()
			with self.assertRaises(frappe.PermissionError):
				create_schedule(self.wizard_values())
		finally:
			frappe.set_user(user)

	def test_preview_reports_no_clash_for_an_unassigned_pattern(self):
		result = preview_schedule(self.wizard_values())

		self.assertEqual(result["clashes"], [])
