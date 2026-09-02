import frappe
from frappe import _

# custom/patient_encounter.json defaults appointment_type to this via a Property Setter,
# so it has to exist or every encounter insert fails.
DEFAULT_APPOINTMENT_TYPE = "Walk-In"


def seed_default_appointment_type() -> None:
	if frappe.db.exists("Appointment Type", DEFAULT_APPOINTMENT_TYPE):
		return
	frappe.get_doc({"doctype": "Appointment Type", "appointment_type": DEFAULT_APPOINTMENT_TYPE}).insert(
		ignore_permissions=True
	)


VALID_WORKFLOW_STATES = {
	"Waiting for Doctor",
	"Awaiting Test",
	"Awaiting Doctor Review",
	"Awaiting Medicine",
	"Completed",
	"Cancelled",
}

# Cancelled is reachable from every live state and exits to none: a patient who leaves before
# being seen can do so at any point in the loop, and letting the visit resume afterwards would
# put an untreated patient back on a board the front desk has already cleared.
ALLOWED_TRANSITIONS = {
	"Waiting for Doctor": {"Awaiting Test", "Awaiting Medicine", "Completed", "Cancelled"},
	"Awaiting Test": {"Awaiting Doctor Review", "Cancelled"},
	"Awaiting Doctor Review": {"Awaiting Medicine", "Completed", "Cancelled"},
	"Awaiting Medicine": {"Completed", "Cancelled"},
	"Completed": set(),
	"Cancelled": set(),
}

TERMINAL_WORKFLOW_STATES = {"Completed", "Cancelled"}

ENCOUNTER_TO_QUEUE_STAGE = {
	"Waiting for Doctor": "Waiting",
	"Awaiting Test": "With Nurse (Test)",
	"Awaiting Doctor Review": "With Doctor",
	"Awaiting Medicine": "With Nurse (Medicine)",
	"Completed": "Completed",
	"Cancelled": "Cancelled",
}


def validate_workflow_state(doc, method):
	state = doc.custom_workflow_state
	if not state:
		return

	if state not in VALID_WORKFLOW_STATES:
		frappe.throw(
			_("Invalid workflow state: {0}").format(state),
		)

	if doc.is_new():
		return

	before = doc.get_doc_before_save()
	old_state = before.custom_workflow_state if before else None
	if not old_state or old_state == state:
		return

	if old_state in TERMINAL_WORKFLOW_STATES:
		frappe.throw(
			_("This encounter is already {0} and cannot be reopened.").format(_(old_state.lower())),
		)

	if state not in ALLOWED_TRANSITIONS.get(old_state, set()):
		frappe.throw(
			_("Cannot move patient from {0} to {1} directly.").format(old_state, state),
		)


def sync_to_queue(doc, method):
	stage = ENCOUNTER_TO_QUEUE_STAGE.get(doc.custom_workflow_state)
	if not stage:
		return

	existing = frappe.db.get_value("Patient Queue", {"patient": doc.patient}, "name")
	values = {
		"encounter": doc.name,
		"patient": doc.patient,
		"clinic_session": doc.custom_clinic_session,
		"current_stage": stage,
		"status": "Done" if doc.custom_workflow_state in TERMINAL_WORKFLOW_STATES else "Active",
		"last_updated": frappe.utils.now(),
	}
	if doc.custom_workflow_state in TERMINAL_WORKFLOW_STATES:
		values["completed_on"] = frappe.utils.now()

	if existing:
		frappe.db.set_value("Patient Queue", existing, values)
		return

	values["created_on"] = frappe.utils.now()

	# Patient Queue.patient carries a unique index, so two front desks registering the same
	# patient at once both miss the lookup above and the loser's insert fails. Without the
	# savepoint the whole registration rolls back and that patient is never created.
	frappe.db.savepoint("patient_queue_insert")
	try:
		frappe.get_doc({"doctype": "Patient Queue", **values}).insert(ignore_permissions=True)
	except (frappe.UniqueValidationError, frappe.DuplicateEntryError):
		# `patient` is a unique field, not the primary key, so the loser of the race comes out of
		# base_document.show_unique_validation_message() as UniqueValidationError
		# (frappe/model/base_document.py:917). DuplicateEntryError is only raised for a name
		# collision (base_document.py:837) and is kept because the row is named by a dated series
		# that two same-second inserts can still collide on.
		frappe.db.rollback(save_point="patient_queue_insert")
		existing = frappe.db.get_value("Patient Queue", {"patient": doc.patient}, "name")
		if not existing:
			raise
		# The unique violation already queued a "Patient must be unique" msgprint. The race is
		# handled, so showing it would report a failure the front desk did not have.
		frappe.clear_last_message()
		frappe.db.set_value("Patient Queue", existing, values)
