# Copyright (c) 2026, CMID and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, now, today

from bandhu_app.bandhu_app.doctype.patient_queue.patient_queue import PatientQueue
from bandhu_app.bandhu_app.utils.patient_encounter import sync_to_queue

EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = []


class IntegrationTestPatientQueue(IntegrationTestCase):
	def make_queue_row(self, patient: str, status: str, days_old: int) -> str:
		row = frappe.get_doc(
			{
				"doctype": "Patient Queue",
				"patient": patient,
				"current_stage": "Completed" if status == "Done" else "Waiting",
				"status": status,
				"created_on": now(),
				"last_updated": now(),
			}
		).insert(ignore_permissions=True)

		self.age_row(row.name, days_old)
		return row.name

	def age_row(self, queue_row: str, days_old: int) -> None:
		frappe.db.set_value(
			"Patient Queue",
			queue_row,
			"modified",
			add_days(now(), -days_old),
			update_modified=False,
		)

	def test_finished_rows_older_than_the_retention_window_are_cleared(self):
		stale_row = self.make_queue_row("QUEUE-TEST-STALE-DONE", "Done", days_old=120)

		PatientQueue.clear_old_logs(days=90)

		self.assertFalse(frappe.db.exists("Patient Queue", stale_row))

	def test_recent_and_unfinished_rows_survive(self):
		recent_done_row = self.make_queue_row("QUEUE-TEST-RECENT-DONE", "Done", days_old=10)
		stale_active_row = self.make_queue_row("QUEUE-TEST-STALE-ACTIVE", "Active", days_old=120)

		PatientQueue.clear_old_logs(days=90)

		self.assertTrue(frappe.db.exists("Patient Queue", recent_done_row))
		self.assertTrue(frappe.db.exists("Patient Queue", stale_active_row))

	def make_patient(self, first_name: str):
		return frappe.get_doc(
			{
				"doctype": "Patient",
				"first_name": first_name,
				"sex": frappe.get_all("Gender", limit=1, pluck="name")[0],
			}
		).insert(ignore_permissions=True)

	def make_practitioner(self, first_name: str) -> str:
		return (
			frappe.get_doc(
				{"doctype": "Healthcare Practitioner", "first_name": first_name, "status": "Active"}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_a_lost_race_on_the_unique_patient_row_is_recovered(self):
		"""A concurrent front desk wins the insert while this request is mid-flight.

		`Patient Queue.patient` is a unique field, so the loser gets UniqueValidationError, not
		the DuplicateEntryError a primary-key collision would raise. Missing the existing row
		once is what a real race does; the second lookup, inside the recovery, sees it.
		"""
		patient = self.make_patient("Queue Race Patient")
		encounter = frappe.get_doc(
			{
				"doctype": "Patient Encounter",
				"patient": patient.name,
				"practitioner": self.make_practitioner("Queue Race Practitioner"),
				"custom_workflow_state": "Waiting for Doctor",
				"encounter_date": today(),
			}
		).insert(ignore_permissions=True)

		winning_row = frappe.db.get_value("Patient Queue", {"patient": patient.name}, "name")
		self.assertTrue(winning_row)

		encounter.custom_workflow_state = "Awaiting Test"
		read_value = frappe.db.get_value
		queue_lookups = []

		def miss_the_queue_row_once(doctype, *args, **kwargs):
			if doctype == "Patient Queue":
				queue_lookups.append(doctype)
				if len(queue_lookups) == 1:
					return None
			return read_value(doctype, *args, **kwargs)

		with patch.object(frappe.db, "get_value", side_effect=miss_the_queue_row_once):
			sync_to_queue(encounter, "on_update")

		self.assertEqual(
			frappe.db.get_value("Patient Queue", winning_row, "current_stage"), "With Nurse (Test)"
		)
		self.assertEqual(frappe.db.count("Patient Queue", {"patient": patient.name}), 1)

	def test_clearing_a_board_row_leaves_the_encounter_it_projects(self):
		patient = self.make_patient("Queue Cleanup Patient")
		encounter = frappe.get_doc(
			{
				"doctype": "Patient Encounter",
				"patient": patient.name,
				"practitioner": self.make_practitioner("Queue Cleanup Practitioner"),
				"custom_workflow_state": "Completed",
				"encounter_date": today(),
			}
		).insert(ignore_permissions=True)

		queue_row = frappe.db.get_value("Patient Queue", {"patient": patient.name}, "name")
		self.assertTrue(queue_row)
		self.age_row(queue_row, 120)

		PatientQueue.clear_old_logs(days=90)

		self.assertFalse(frappe.db.exists("Patient Queue", queue_row))
		self.assertTrue(frappe.db.exists("Patient Encounter", encounter.name))
