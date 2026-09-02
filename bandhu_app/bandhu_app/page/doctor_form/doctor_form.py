import frappe
from frappe import _
from frappe.core.doctype.access_log.access_log import make_access_log

from bandhu_app.bandhu_app.utils.clinic_test import get_enabled_tests
from bandhu_app.bandhu_app.utils.patient import compact_age
from bandhu_app.bandhu_app.utils.patient_details import get_patient_details, get_session_encounters
from bandhu_app.bandhu_app.utils.session import find_active_session, find_upcoming_sessions

REFERRAL_PRIORITIES = {"Low", "Medium", "High"}
REFERRAL_LETTER_PRINT_FORMAT = "Bandhu Referral Letter"


def require_doctor_access() -> None:
	roles = frappe.get_roles()
	if "Doctor" not in roles and "System Manager" not in roles:
		frappe.throw(
			_("You do not have permission to access this page."),
			frappe.PermissionError,
		)


def get_encounter_history(patient: str):
	return frappe.db.get_all(
		"Patient Encounter",
		filters={"patient": patient},
		fields=["name", "encounter_date"],
		order_by="encounter_date desc, creation desc",
	)


def get_doctor_practitioner():
	return frappe.db.get_value("Healthcare Practitioner", {"user_id": frappe.session.user}, "name")


def get_doctor_session():
	practitioner = get_doctor_practitioner()

	if not practitioner:
		return None

	session = find_active_session("assigned_doctor", practitioner)
	return session.name if session else None


@frappe.whitelist()
def get_session_status() -> dict:
	user = frappe.session.user

	roles = frappe.get_roles(user)
	if "Doctor" not in roles and "System Manager" not in roles:
		return {"has_session": False, "message": _("You do not have the Doctor role.")}

	practitioner = frappe.db.get_value(
		"Healthcare Practitioner",
		{"user_id": user},
		"name",
	)

	if not practitioner:
		return {"has_session": False, "message": _("No Healthcare Practitioner linked to your account.")}

	session = find_active_session("assigned_doctor", practitioner)

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
	require_doctor_access()
	practitioner = frappe.db.get_value("Healthcare Practitioner", {"user_id": frappe.session.user}, "name")
	if not practitioner:
		return []
	return find_upcoming_sessions("assigned_doctor", practitioner)


def load_owned_encounter(encounter: str):
	doc = frappe.get_doc("Patient Encounter", encounter)
	if "System Manager" not in frappe.get_roles():
		session = get_doctor_session()
		if not session or doc.custom_clinic_session != session:
			frappe.throw(
				_("You are not permitted to update this patient."),
				frappe.PermissionError,
			)
	return doc


@frappe.whitelist()
def get_registered_patients():
	require_doctor_access()
	session = get_doctor_session()
	if not session:
		return []
	return get_session_encounters(session, ["!=", "Completed"])


@frappe.whitelist()
def get_completed_patients():
	require_doctor_access()
	session = get_doctor_session()
	if not session:
		return []
	return get_session_encounters(session, "Completed")


def verify_patient_linked_to_my_session(patient: str) -> None:
	if "System Manager" in frappe.get_roles():
		return
	session = get_doctor_session()
	if not session:
		frappe.throw(_("You are not permitted to view this patient's details."), frappe.PermissionError)
	linked = frappe.db.get_value(
		"Patient Encounter",
		{"custom_clinic_session": session, "patient": patient},
		"name",
	)
	if not linked:
		frappe.throw(_("You are not permitted to view this patient's details."), frappe.PermissionError)


@frappe.whitelist()
def get_patient_history(patient: str):
	require_doctor_access()
	verify_patient_linked_to_my_session(patient)
	return get_encounter_history(patient)


@frappe.whitelist()
def get_patient_histories(patients: list | str) -> dict:
	"""Return the encounter history for a whole queue in one call.

	The page used to ask per patient, so a 40-patient camp fired 40 parallel requests and
	saturated the browser's connection pool on the weak links these camps run on.
	"""
	require_doctor_access()
	patients = frappe.parse_json(patients)

	if not patients:
		return {}

	# One ownership check for the queue rather than one per patient: everything the doctor may
	# read is an encounter in their own session, so the session's patient set is the allow-list.
	if "System Manager" in frappe.get_roles():
		permitted = set(patients)
	else:
		session = get_doctor_session()
		if not session:
			frappe.throw(_("You are not permitted to view this patient's details."), frappe.PermissionError)
		permitted = set(
			frappe.get_all(
				"Patient Encounter",
				filters={"custom_clinic_session": session, "patient": ["in", patients]},
				pluck="patient",
				distinct=True,
			)
		)
		if set(patients) - permitted:
			frappe.throw(_("You are not permitted to view this patient's details."), frappe.PermissionError)

	histories = {patient: [] for patient in permitted}
	for row in frappe.get_all(
		"Patient Encounter",
		filters={"patient": ["in", list(permitted)]},
		fields=["name", "encounter_date", "patient"],
		order_by="encounter_date desc, creation desc",
	):
		histories[row.pop("patient")].append(row)

	return histories


@frappe.whitelist()
def get_patient_registration_details(encounter: str):
	require_doctor_access()
	doc = load_owned_encounter(encounter)
	return get_patient_details(doc.patient)


@frappe.whitelist()
def get_test_options() -> list[dict]:
	"""The order-test checkboxes. A value test carries its unit in the label so the doctor
	knows what the nurse will be asked to measure."""
	require_doctor_access()

	return [
		{
			"name": test.name,
			"label": f"{test.test_name} ({test.unit})" if test.unit else test.test_name,
		}
		for test in get_enabled_tests()
	]


@frappe.whitelist(methods=["POST"])
def order_test(
	encounter: str,
	tests: list | str,
	notes: str | None = None,
	chief_complaint: str | None = None,
	past_history: str | None = None,
	allergy_history: str | None = None,
) -> None:
	require_doctor_access()
	tests = frappe.parse_json(tests)

	if not tests:
		frappe.throw(_("Select at least one test."))
	invalid = set(tests) - {test.name for test in get_enabled_tests()}
	if invalid:
		frappe.throw(_("Unknown test(s): {0}").format(", ".join(invalid)))

	doc = load_owned_encounter(encounter)
	if doc.custom_workflow_state != "Waiting for Doctor":
		frappe.throw(_("Tests can only be ordered for a patient waiting for the doctor."))

	for test_name in tests:
		doc.append("custom_test_instructions", {"test_name": test_name, "notes": notes})

	if chief_complaint:
		doc.custom_chief_complaints = chief_complaint
	if past_history:
		doc.custom_past_history = past_history
	if allergy_history:
		doc.custom_allergy_history = allergy_history

	doc.custom_workflow_state = "Awaiting Test"
	doc.save(ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
def prescribe_medicine(
	encounter: str,
	prescriptions: list | str,
	chief_complaint: str | None = None,
	past_history: str | None = None,
	allergy_history: str | None = None,
) -> None:
	require_doctor_access()
	prescriptions = frappe.parse_json(prescriptions)

	if not prescriptions:
		frappe.throw(_("Add at least one medicine."))

	doc = load_owned_encounter(encounter)
	if doc.custom_workflow_state not in ("Waiting for Doctor", "Awaiting Doctor Review"):
		frappe.throw(
			_("Medicine can only be prescribed for a patient waiting for or under doctor review."),
		)

	for row in prescriptions:
		medicine = (row.get("medicines") or "").strip()
		if not medicine:
			frappe.throw(_("Every prescription row needs a medicine."))
		doc.append(
			"custom_bandhu_prescription",
			{
				"medicines": medicine,
				"dosage_frequency": row.get("dosage_frequency"),
				"duration_days": row.get("duration_days"),
				"quantity": row.get("quantity"),
				"instructions": row.get("instructions"),
				# Left unset, Frappe fills this from the prescriber's own User Permission on
				# Healthcare Practitioner, stamping the doctor as the dispenser before anyone has
				# dispensed anything — and the field's own link_filters say it must be a nurse.
				# It has to be "" rather than None: update_if_missing only skips a key whose value
				# is not None (frappe/model/base_document.py:349), so None still takes the default.
				"dispensed_by": "",
			},
		)

	if chief_complaint:
		doc.custom_chief_complaints = chief_complaint
	if past_history:
		doc.custom_past_history = past_history
	if allergy_history:
		doc.custom_allergy_history = allergy_history

	doc.custom_workflow_state = "Awaiting Medicine"
	doc.save(ignore_permissions=True)


def create_referral(
	doc,
	referred_to: str,
	referred_to_practitioner: str | None,
	reason: str,
	priority: str | None,
) -> None:
	session = frappe.db.get_value(
		"Bandhu Clinic Session", doc.custom_clinic_session, ["project", "name"], as_dict=True
	)
	dob = frappe.db.get_value("Patient", doc.patient, "dob")

	frappe.get_doc(
		{
			"doctype": "Referral",
			"patient": doc.patient,
			"patient_encounter": doc.name,
			"referral_by_source": get_doctor_practitioner(),
			"referred_to": referred_to,
			"referred_to_practitioner": referred_to_practitioner,
			"reason": reason,
			"priority": priority if priority in REFERRAL_PRIORITIES else "Medium",
			"status": "Pending",
			"helpline_flag": 1,
			"created_by": frappe.utils.get_fullname(frappe.session.user),
			"created_on": frappe.utils.now_datetime(),
			"project": session.project if session else None,
			"clinic_session": session.name if session else None,
			"age": compact_age(dob) if dob else None,
		}
	).insert(ignore_permissions=True)

	doc.custom_has_referral = 1


@frappe.whitelist(methods=["POST"])
def complete_encounter(
	encounter: str,
	diagnosis: str | None = None,
	clinical_notes: str | None = None,
	chief_complaint: str | None = None,
	past_history: str | None = None,
	allergy_history: str | None = None,
	referred_to: str | None = None,
	referred_to_practitioner: str | None = None,
	referral_reason: str | None = None,
	referral_priority: str | None = None,
) -> None:
	require_doctor_access()

	doc = load_owned_encounter(encounter)
	if doc.custom_workflow_state not in ("Waiting for Doctor", "Awaiting Doctor Review"):
		frappe.throw(
			_("This patient cannot be marked complete from their current state."),
		)

	if diagnosis:
		doc.append("custom_bandhu_diagnosis", {"diagnosis_name": diagnosis})
	if clinical_notes:
		doc.custom_bandhu_clinical_notes = clinical_notes
	if chief_complaint:
		doc.custom_chief_complaints = chief_complaint
	if past_history:
		doc.custom_past_history = past_history
	if allergy_history:
		doc.custom_allergy_history = allergy_history

	if referred_to or referral_reason:
		if not (referred_to and referral_reason):
			frappe.throw(_("A referral needs both where the patient is being referred to and why."))
		create_referral(doc, referred_to, referred_to_practitioner, referral_reason, referral_priority)

	doc.custom_workflow_state = "Completed"
	doc.save(ignore_permissions=True)


@frappe.whitelist()
def get_referral_letter_html(encounter: str) -> str:
	"""Render the printable referral letter for one encounter.

	Referral is System Manager only in DocType permissions, so this crosses that boundary the
	same way get_patient_card_html does on the CAD page: load_owned_encounter already proves
	the caller may see this patient, and the print render carries only what that grants.
	"""
	doc = load_owned_encounter(encounter)

	referral = frappe.db.get_value("Referral", {"patient_encounter": doc.name}, "name")
	if not referral:
		frappe.throw(_("This patient has no referral on record."), frappe.DoesNotExistError)

	make_access_log(doctype="Referral", document=referral, method="Doctor Referral Letter")

	frappe.flags.ignore_print_permissions = True
	try:
		return frappe.get_print(
			"Referral",
			referral,
			print_format=REFERRAL_LETTER_PRINT_FORMAT,
			no_letterhead=True,
		)
	finally:
		frappe.flags.ignore_print_permissions = False
