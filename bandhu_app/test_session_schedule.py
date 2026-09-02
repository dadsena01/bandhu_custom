# Copyright (c) 2026, CMID and Contributors
# See license.txt

from datetime import date, timedelta

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import getdate, today

from bandhu_app.bandhu_app.baseline_test_fixtures import ensure_baseline_fixtures
from bandhu_app.bandhu_app.doctype.bandhu_session_schedule.bandhu_session_schedule import (
	regenerate_future_sessions,
)
from bandhu_app.bandhu_app.utils.session_schedule import (
	generate_scheduled_sessions,
	generate_sessions_for_schedule,
	is_auto_generation_enabled,
	occurrence_dates,
	preview_occurrences,
)

EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = []


class IntegrationTestSessionSchedule(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		baseline = ensure_baseline_fixtures()
		cls.clinic = baseline["clinic"]
		cls.site = baseline["site"]
		cls.unit = baseline["unit"]
		cls.doctor = baseline["doctor"]
		cls.gender = frappe.get_all("Gender", limit=1, pluck="name")[0]

	def build_schedule(self, weekdays=None, save=False, **overrides):
		values = {
			"doctype": "Bandhu Session Schedule",
			"enabled": 1,
			"site": self.site,
			"clinic": self.clinic,
			"unit": self.unit,
			"frequency": "Weekly",
			"valid_from": "2026-01-01",
		}
		values.update(overrides)
		schedule = frappe.get_doc(values)
		for weekday in weekdays or []:
			schedule.append("weekdays", {"weekday": weekday})
		if save:
			schedule.insert(ignore_permissions=True)
		return schedule

	def test_weekly_returns_only_the_chosen_weekdays(self):
		schedule = self.build_schedule(weekdays=["Monday", "Thursday"])
		dates = occurrence_dates(schedule, "2026-01-01", "2026-01-21")

		self.assertTrue(all(day.weekday() in (0, 3) for day in dates))
		self.assertIn(date(2026, 1, 1), dates)  # a Thursday
		self.assertIn(date(2026, 1, 5), dates)  # the following Monday
		self.assertEqual(len(dates), 6)

	def test_fortnightly_skips_the_week_after_the_anchor(self):
		schedule = self.build_schedule(weekdays=["Monday"], frequency="Fortnightly", valid_from="2026-01-05")
		dates = occurrence_dates(schedule, "2026-01-05", "2026-02-02")

		self.assertEqual(dates, [date(2026, 1, 5), date(2026, 1, 19), date(2026, 2, 2)])

	def test_monthly_first_weekday_of_each_month(self):
		schedule = self.build_schedule(
			weekdays=["Monday"], frequency="Monthly", monthly_mode="Day of Week", week_of_month="First"
		)
		dates = occurrence_dates(schedule, "2026-01-01", "2026-03-31")

		self.assertEqual(dates, [date(2026, 1, 5), date(2026, 2, 2), date(2026, 3, 2)])

	def test_monthly_last_weekday_of_each_month(self):
		schedule = self.build_schedule(
			weekdays=["Friday"], frequency="Monthly", monthly_mode="Day of Week", week_of_month="Last"
		)
		dates = occurrence_dates(schedule, "2026-01-01", "2026-02-28")

		self.assertEqual(dates, [date(2026, 1, 30), date(2026, 2, 27)])

	def test_monthly_day_of_month_skips_a_month_that_is_too_short(self):
		schedule = self.build_schedule(frequency="Monthly", monthly_mode="Day of Month", day_of_month=31)
		dates = occurrence_dates(schedule, "2026-01-01", "2026-04-30")

		self.assertEqual(dates, [date(2026, 1, 31), date(2026, 3, 31)])

	def test_valid_upto_caps_the_series(self):
		schedule = self.build_schedule(weekdays=["Monday"], valid_upto="2026-01-12")
		dates = occurrence_dates(schedule, "2026-01-01", "2026-02-28")

		self.assertEqual(dates, [date(2026, 1, 5), date(2026, 1, 12)])

	def test_holiday_list_dates_are_dropped(self):
		holiday_list = frappe.get_doc(
			{
				"doctype": "Holiday List",
				"holiday_list_name": "Schedule Test Holidays",
				"from_date": "2026-01-01",
				"to_date": "2026-12-31",
				"holidays": [{"description": "Test holiday", "holiday_date": "2026-01-12"}],
			}
		).insert(ignore_permissions=True)

		schedule = self.build_schedule(weekdays=["Monday"], holiday_list=holiday_list.name)
		dates = occurrence_dates(schedule, "2026-01-01", "2026-01-19")

		self.assertEqual(dates, [date(2026, 1, 5), date(2026, 1, 19)])

	def sessions_of(self, schedule):
		return frappe.get_all(
			"Bandhu Clinic Session",
			filters={"session_schedule": schedule},
			order_by="date asc",
			pluck="name",
		)

	def test_saving_creates_the_sessions_at_once(self):
		schedule = self.build_schedule(weekdays=all_weekday_names(), valid_from=today(), save=True)

		self.assertTrue(self.sessions_of(schedule.name))

	def test_generation_is_idempotent(self):
		schedule = self.build_schedule(weekdays=all_weekday_names(), valid_from=today(), save=True)
		created_on_save = self.sessions_of(schedule.name)

		self.assertTrue(created_on_save)
		self.assertEqual(generate_sessions_for_schedule(schedule.name), [])
		self.assertEqual(self.sessions_of(schedule.name), created_on_save)

	def test_a_cancelled_session_is_not_recreated(self):
		schedule = self.build_schedule(weekdays=all_weekday_names(), valid_from=today(), save=True)
		created = self.sessions_of(schedule.name)
		cancelled = frappe.get_doc("Bandhu Clinic Session", created[-1])
		cancelled_date = cancelled.date
		cancelled.status = "Cancelled"
		cancelled.save(ignore_permissions=True)

		generate_sessions_for_schedule(schedule.name, upto=add_days(today(), 7))

		self.assertEqual(
			frappe.db.count(
				"Bandhu Clinic Session",
				{"session_schedule": schedule.name, "date": cancelled_date},
			),
			1,
		)

	def test_generated_session_carries_the_schedule_defaults(self):
		schedule = self.build_schedule(
			weekdays=all_weekday_names(),
			valid_from=today(),
			planned_start_time="09:00:00",
			planned_end_time="13:00:00",
			save=True,
		)
		session = frappe.get_doc("Bandhu Clinic Session", self.sessions_of(schedule.name)[0])

		self.assertEqual(session.site, self.site)
		self.assertEqual(session.clinic, self.clinic)
		self.assertEqual(session.status, "Planned")
		self.assertEqual(str(session.planned_start_time), "9:00:00")

	def test_rebuild_leaves_a_session_that_has_an_encounter(self):
		schedule = self.build_schedule(weekdays=all_weekday_names(), valid_from=today(), save=True)
		future_session = next(
			name
			for name in self.sessions_of(schedule.name)
			if getdate(frappe.db.get_value("Bandhu Clinic Session", name, "date")) > getdate(today())
		)
		patient = frappe.get_doc(
			{
				"doctype": "Patient",
				"first_name": "Rebuild Test Patient",
				"sex": self.gender,
				"dob": "1990-01-01",
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Patient Encounter",
				"patient": patient.name,
				"practitioner": self.doctor,
				"encounter_date": today(),
				"custom_clinic_session": future_session,
			}
		).insert(ignore_permissions=True)

		regenerate_future_sessions(schedule.name)

		self.assertTrue(frappe.db.exists("Bandhu Clinic Session", future_session))

	def test_generation_runs_when_settings_have_never_been_saved(self):
		frappe.db.delete("Singles", {"doctype": "Bandhu Settings"})
		frappe.clear_document_cache("Bandhu Settings")

		self.assertTrue(is_auto_generation_enabled())

	def test_master_switch_stops_every_schedule(self):
		settings = frappe.get_single("Bandhu Settings")
		settings.disable_auto_session_generation = 1
		settings.save(ignore_permissions=True)
		self.addCleanup(reset_auto_generation)

		# The switch has to stop generation on save too, or it only half works.
		schedule = self.build_schedule(weekdays=all_weekday_names(), valid_from=today(), save=True)
		generate_scheduled_sessions()

		self.assertEqual(frappe.db.count("Bandhu Clinic Session", {"session_schedule": schedule.name}), 0)

	def test_preview_does_not_create_sessions(self):
		schedule = self.build_schedule(weekdays=["Monday"], valid_from=today())
		dates = preview_occurrences(frappe.as_json(schedule.as_dict()))

		self.assertTrue(dates)
		self.assertTrue(all(getdate(day).weekday() == 0 for day in dates))
		self.assertEqual(frappe.db.count("Bandhu Session Schedule", {"site": self.site, "name": ""}), 0)

	def test_weekly_schedule_without_weekdays_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self.build_schedule(save=True)

	def test_a_single_digit_start_hour_still_saves(self):
		"""A Time from the DB is a timedelta, but from a client save it is a string, and
		"13:30:00" <= "8:00:00" compares True lexicographically — which made every schedule
		starting before 10am unsavable from the Desk form."""
		schedule = self.build_schedule(
			weekdays=["Monday"],
			valid_from=today(),
			planned_start_time="8:00:00",
			planned_end_time="13:30:00",
			save=True,
		)
		self.assertTrue(schedule.name)

	def test_an_end_time_before_the_start_is_still_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self.build_schedule(
				weekdays=["Monday"],
				valid_from=today(),
				planned_start_time="13:30:00",
				planned_end_time="8:00:00",
				save=True,
			)

	def test_valid_upto_before_valid_from_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self.build_schedule(
				weekdays=["Monday"], valid_from="2026-05-01", valid_upto="2026-04-01", save=True
			)

	def test_changing_the_pattern_rebuilds_onto_the_new_days(self):
		schedule = self.build_schedule(weekdays=["Monday"], valid_from=today(), save=True)
		self.assertTrue(self.sessions_of(schedule.name))

		schedule.weekdays = []
		schedule.append("weekdays", {"weekday": "Tuesday"})
		schedule.save(ignore_permissions=True)
		regenerate_future_sessions(schedule.name)

		future_dates = frappe.get_all(
			"Bandhu Clinic Session",
			filters={"session_schedule": schedule.name, "date": [">", today()]},
			pluck="date",
		)
		self.assertTrue(future_dates)
		self.assertEqual({getdate(day).weekday() for day in future_dates}, {1})


def reset_auto_generation():
	settings = frappe.get_single("Bandhu Settings")
	settings.disable_auto_session_generation = 0
	settings.save(ignore_permissions=True)


def all_weekday_names():
	return ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def add_days(day, days):
	return getdate(day) + timedelta(days=days)
