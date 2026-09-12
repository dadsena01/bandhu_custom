import frappe
from frappe import _
from frappe.query_builder.functions import Count
from frappe.utils import flt

from bandhu_app.bandhu_app.utils.patient_details import get_patient_details, get_session_encounters
from bandhu_app.bandhu_app.utils.realtime import publish_board_update
from bandhu_app.bandhu_app.utils.session import find_active_session, find_upcoming_sessions


def require_session_access(session_name: str) -> None:
	user = frappe.session.user
	roles = frappe.get_roles(user)
	if "System Manager" in roles:
		return
	if "Nurse" not in roles:
		frappe.throw(
			_("You do not have permission to access this clinic session."),
			frappe.PermissionError,
		)
	practitioner = frappe.db.get_value("Healthcare Practitioner", {"user_id": user}, "name")
	if not practitioner:
		frappe.throw(
			_("No Healthcare Practitioner linked to your account."),
			frappe.PermissionError,
		)
	assigned_nurse = frappe.db.get_value("Bandhu Clinic Session", session_name, "assigned_nurse")
	if not assigned_nurse or assigned_nurse != practitioner:
		frappe.throw(
			_("You are not assigned to this clinic session."),
			frappe.PermissionError,
		)


def get_nurse_practitioner():
	return frappe.db.get_value("Healthcare Practitioner", {"user_id": frappe.session.user}, "name")


def load_session_encounter(encounter: str):
	doc = frappe.get_doc("Patient Encounter", encounter)
	require_session_access(doc.custom_clinic_session)
	return doc


@frappe.whitelist()
def get_session_status() -> dict:
	user = frappe.session.user

	roles = frappe.get_roles(user)
	if "Nurse" not in roles and "System Manager" not in roles:
		return {"has_session": False, "message": _("You do not have the Nurse role.")}

	practitioner = frappe.db.get_value(
		"Healthcare Practitioner",
		{"user_id": user},
		"name",
	)

	if not practitioner:
		return {"has_session": False, "message": _("No Healthcare Practitioner linked to your account.")}

	session = find_active_session("assigned_nurse", practitioner)

	if not session:
		return {
			"has_session": False,
			"message": _("No session scheduled for today. Please contact Programme Manager."),
		}

	return {
		"has_session": True,
		"session_name": session.name,
		"status": session.status,
		"clinic": session.clinic,
		"site": session.site,
	}


@frappe.whitelist()
def get_upcoming_sessions() -> list:
	roles = frappe.get_roles()
	if "Nurse" not in roles and "System Manager" not in roles:
		frappe.throw(
			_("You do not have permission to access this page."),
			frappe.PermissionError,
		)

	practitioner = get_nurse_practitioner()
	if not practitioner:
		return []
	return find_upcoming_sessions("assigned_nurse", practitioner)


def load_session_for_status_change(session_name: str) -> dict:
	require_session_access(session_name)
	# for_update makes a second open or close request wait and read the committed status.
	session_doc = frappe.db.get_value(
		"Bandhu Clinic Session",
		session_name,
		["status", "date"],
		as_dict=True,
		for_update=True,
	)
	if not session_doc:
		frappe.throw(_("Clinic session not found."))
	if session_doc.status == "Cancelled":
		frappe.throw(_("This session was cancelled. Do not travel to it."))

	return session_doc


@frappe.whitelist(methods=["POST"])
def start_session(session_name: str) -> None:
	session_doc = load_session_for_status_change(session_name)

	if session_doc.status == "In Progress":
		frappe.throw(_("This session is already open."))
	if session_doc.status == "Completed":
		frappe.throw(
			_("This session is already closed and cannot be reopened."),
		)
	if str(session_doc.date) != frappe.utils.today():
		frappe.throw(_("You can only open a session on the day it is scheduled."))

	frappe.db.set_value(
		"Bandhu Clinic Session",
		session_name,
		{"status": "In Progress", "start_time": frappe.utils.now_datetime()},
	)
	publish_board_update(session_name)


@frappe.whitelist(methods=["POST"])
def end_session(session_name: str) -> None:
	session_doc = load_session_for_status_change(session_name)

	if session_doc.status != "In Progress":
		frappe.throw(_("This session is not open, so it cannot be closed."))

	frappe.db.set_value(
		"Bandhu Clinic Session",
		session_name,
		{"status": "Completed", "end_time": frappe.utils.now_datetime()},
	)
	publish_board_update(session_name)


@frappe.whitelist()
def get_patients_for_tests(session_name: str) -> list:
	require_session_access(session_name)
	return get_session_encounters(session_name, "Awaiting Test")


@frappe.whitelist()
def get_patients_for_medicines(session_name: str) -> list:
	require_session_access(session_name)
	return get_session_encounters(session_name, "Awaiting Medicine")


@frappe.whitelist()
def get_completed_patients(session_name: str) -> list:
	require_session_access(session_name)
	return get_session_encounters(session_name, "Completed")


SESSION_PROGRESS_STATES = {
	"registered": "Waiting for Doctor",
	"with_doctor": "Awaiting Doctor Review",
	"for_tests": "Awaiting Test",
	"for_medicines": "Awaiting Medicine",
	"completed": "Completed",
}


@frappe.whitelist()
def get_session_progress(session_name: str) -> dict:
	require_session_access(session_name)

	# v16 rejects an aggregate string in `fields`, so use the query builder.
	encounter = frappe.qb.DocType("Patient Encounter")
	counts = (
		frappe.qb.from_(encounter)
		.select(encounter.custom_workflow_state, Count("*").as_("total"))
		.where(encounter.custom_clinic_session == session_name)
		.groupby(encounter.custom_workflow_state)
	).run(as_dict=True)
	by_state = {row.custom_workflow_state: row.total for row in counts}

	return {key: by_state.get(state, 0) for key, state in SESSION_PROGRESS_STATES.items()}


@frappe.whitelist()
def get_patient_registration_details(encounter: str) -> dict:
	doc = load_session_encounter(encounter)
	return get_patient_details(doc.patient)


@frappe.whitelist(methods=["POST"])
def submit_test_results(encounter: str, results: list | str) -> None:
	doc = load_session_encounter(encounter)
	if doc.custom_workflow_state != "Awaiting Test":
		frappe.throw(_("This patient is not awaiting a test."))

	results = frappe.parse_json(results)
	rows_by_name = {row.name: row for row in doc.custom_test_instructions}
	for result in results:
		row = rows_by_name.get(result.get("name"))
		if not row:
			frappe.throw(_("Unknown test row."))
		row.result_type = result.get("result_type")
		row.result_value = result.get("result_value")

	for row in doc.custom_test_instructions:
		if not row.result_type:
			frappe.throw(
				_("{0} has no result. Choose Not Done if the test could not be run.").format(row.test_name)
			)
		if row.result_type == "Value" and not (row.result_value or "").strip():
			frappe.throw(_("{0} is a value test and needs a reading.").format(row.test_name))

	doc.custom_workflow_state = "Awaiting Doctor Review"
	doc.save(ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
def record_vitals(
	encounter: str,
	height_cm: float | None = None,
	weight_kg: float | None = None,
	temperature: float | None = None,
	pulse_rate: int | None = None,
	spo2: int | None = None,
	bp_systolic: int | None = None,
	bp_diastolic: int | None = None,
) -> None:
	doc = load_session_encounter(encounter)
	if doc.custom_workflow_state not in ("Awaiting Test", "Awaiting Medicine"):
		frappe.throw(_("Vitals can only be recorded while the patient is with the nurse."))

	measurements = [
		(_("Height"), height_cm, 30, 250),
		(_("Weight"), weight_kg, 1, 300),
		(_("Temperature"), temperature, 90, 110),
		(_("Pulse"), pulse_rate, 20, 250),
		(_("SpO2"), spo2, 50, 100),
		(_("BP systolic"), bp_systolic, 50, 300),
		(_("BP diastolic"), bp_diastolic, 30, 200),
	]
	if not any(value is not None for _label, value, _low, _high in measurements):
		frappe.throw(_("Enter at least one vital sign."))

	for label, value, low, high in measurements:
		if value is None:
			continue
		if flt(value) <= 0:
			frappe.throw(_("Vital signs must be positive numbers."))
		if not low <= flt(value) <= high:
			frappe.throw(
				_("{0} of {1} is outside what a person can record. Check the entry.").format(label, value)
			)

	if (bp_systolic is None) != (bp_diastolic is None):
		frappe.throw(_("Blood pressure needs both the systolic and the diastolic number."))
	if bp_systolic is not None and flt(bp_diastolic) >= flt(bp_systolic):
		frappe.throw(_("The systolic number has to be the higher of the two."))

	if height_cm is not None:
		doc.custom_height = height_cm
	if weight_kg is not None:
		doc.custom_weight = weight_kg
	if temperature is not None:
		doc.custom_temperature = temperature
	if pulse_rate is not None:
		doc.custom_pulse_rate = pulse_rate
	if spo2 is not None:
		doc.custom_spo2 = spo2
	if bp_systolic is not None and bp_diastolic is not None:
		doc.custom_blood_pressure = f"{bp_systolic}/{bp_diastolic}"

	if doc.custom_height and doc.custom_weight:
		height_m = flt(doc.custom_height) / 100
		doc.custom_bmi = round(flt(doc.custom_weight) / (height_m * height_m), 2)

	doc.save(ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
def dispense_medicine(encounter: str, dispensed_rows: list | str | None = None) -> None:
	doc = load_session_encounter(encounter)
	if doc.custom_workflow_state != "Awaiting Medicine":
		frappe.throw(_("This patient is not awaiting medicine."))

	practitioner = get_nurse_practitioner()
	dispensed_set = set(frappe.parse_json(dispensed_rows) or [])
	rows_by_name = {row.name: row for row in doc.custom_bandhu_prescription}
	for row_name in dispensed_set:
		row = rows_by_name.get(row_name)
		if not row:
			frappe.throw(_("Unknown prescription row."))
		row.dispensed = 1
		row.dispensed_by = practitioner

	doc.custom_workflow_state = "Completed"
	doc.save(ignore_permissions=True)
