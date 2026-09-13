# Copyright (c) 2026, CMID and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.query_builder import Interval
from frappe.query_builder.functions import Now


class PatientQueue(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		clinic_session: DF.Data | None
		completed_on: DF.Datetime | None
		created_on: DF.Autocomplete | None
		current_stage: DF.Literal[
			"Waiting", "With Doctor", "With Nurse (Test)", "With Nurse (Medicine)", "Completed"
		]
		encounter: DF.Link | None
		handled_by: DF.Link | None
		last_updated: DF.Autocomplete | None
		patient: DF.Data | None
		status: DF.Literal["Active", "Done"]
	# end: auto-generated types

	@staticmethod
	def clear_old_logs(days: int = 90) -> None:
		"""Drop board rows for visits that finished more than `days` ago.

		Patient Queue is a projection, not a record: Patient Encounter holds the clinical truth
		and sync_to_queue (utils/patient_encounter.py) rebuilds the row from the encounter on
		every save, so a deleted row costs nothing and comes back on the patient's next visit.
		The unique index on `patient` keeps exactly one row per patient alive, which is why the
		table otherwise grows for the life of the site and never shrinks.

		Registered with Frappe's Log Settings through `default_log_clearing_doctypes` in
		hooks.py rather than through a scheduled job of our own.
		"""
		# ponytail: only finished rows are cleared, so a camp a nurse never closed leaves its
		# Active rows on the board forever — clear those too once session close is enforced (F5).
		queue = frappe.qb.DocType("Patient Queue")
		frappe.db.delete(
			queue,
			filters=(queue.status == "Done") & (queue.modified < (Now() - Interval(days=days))),
		)
