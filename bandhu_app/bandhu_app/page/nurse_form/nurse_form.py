import frappe
from frappe import _
from frappe.utils import flt

from bandhu_app.bandhu_app.utils.patient_details import get_patient_details, get_session_encounters
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
	# for_update locks the row for the rest of this transaction, so a second request opening or
	# closing the same camp waits here and then reads the committed status — without it both
	# requests read Planned, both pass the guards below, and the second write silently replaces
	# the first camp's start_time, which is what Session Report and "Camps Late To Open" read.
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
		frappe.throw(_("This camp was cancelled. Do not travel to it."))

	return session_doc


@frappe.whitelist(methods=["POST"])
def start_session(session_name: str) -> None:
	session_doc = load_session_for_status_change(session_name)

	if session_doc.status == "In Progress":
		frappe.throw(_("This camp is already open."))
	# Reopening a closed camp would let patients be registered against it hours or days
	# later, with nothing in the record showing the camp had already been signed off.
	if session_doc.status == "Completed":
		frappe.throw(
			_("This camp is already closed and cannot be reopened."),
		)
	# A camp opened on the wrong date counts as running today on every board and dashboard.
	if str(session_doc.date) != frappe.utils.today():
		frappe.throw(_("You can only open a camp on the day it is scheduled."))

	frappe.db.set_value(
		"Bandhu Clinic Session",
		session_name,
		{"status": "In Progress", "start_time": frappe.utils.now_datetime()},
	)


@frappe.whitelist(methods=["POST"])
def end_session(session_name: str) -> None:
	session_doc = load_session_for_status_change(session_name)

	if session_doc.status != "In Progress":
		frappe.throw(_("This camp is not open, so it cannot be closed."))

	frappe.db.set_value(
		"Bandhu Clinic Session",
		session_name,
		{"status": "Completed", "end_time": frappe.utils.now_datetime()},
	)


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

	values = [height_cm, weight_kg, temperature, pulse_rate, spo2, bp_systolic, bp_diastolic]
	if not any(value is not None for value in values):
		frappe.throw(_("Enter at least one vital sign."))
	for value in values:
		if value is not None and flt(value) <= 0:
			frappe.throw(_("Vital signs must be positive numbers."))

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
