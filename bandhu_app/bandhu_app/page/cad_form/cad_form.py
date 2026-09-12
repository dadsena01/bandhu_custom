import re

import frappe
from frappe import _
from frappe.core.doctype.access_log.access_log import make_access_log
from frappe.utils import flt, getdate, validate_phone_number

from bandhu_app.bandhu_app.utils.patient import compact_age, render_patient_card
from bandhu_app.bandhu_app.utils.patient_encounter import (
	ENCOUNTER_TO_QUEUE_STAGE,
	TERMINAL_WORKFLOW_STATES,
)
from bandhu_app.bandhu_app.utils.session import find_active_session


def require_cad_access() -> None:
	roles = frappe.get_roles()
	if "Clinic Assistant cum Driver" not in roles and "System Manager" not in roles:
		frappe.throw(
			_("You do not have permission to access this page."),
			frappe.PermissionError,
		)


def get_cad_practitioner():
	return frappe.db.get_value("Healthcare Practitioner", {"user_id": frappe.session.user}, "name")


def require_session_access(session_name: str) -> None:
	require_cad_access()
	if "System Manager" in frappe.get_roles():
		return
	practitioner = get_cad_practitioner()
	if not practitioner:
		frappe.throw(
			_("No Healthcare Practitioner linked to your account."),
			frappe.PermissionError,
		)
	assigned_driver = frappe.db.get_value("Bandhu Clinic Session", session_name, "assigned_driver")
	if not assigned_driver or assigned_driver != practitioner:
		frappe.throw(
			_("You are not assigned to this clinic session."),
			frappe.PermissionError,
		)


@frappe.whitelist()
def get_session_status() -> dict:
	require_cad_access()

	practitioner = get_cad_practitioner()
	if not practitioner:
		return {"has_session": False, "message": _("No Healthcare Practitioner linked to your account.")}

	session = find_active_session("assigned_driver", practitioner)

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


# India and Nepal are the two source countries CMID actually registers patients from; the
# form shows them as fixed quick-tap tabs rather than reading them from the Country master,
# which holds all 250 countries and has no "is common" flag of its own.
QUICK_COUNTRIES = ["India", "Nepal"]


@frappe.whitelist()
def get_form_options() -> dict:
	require_cad_access()
	major_states = frappe.get_all(
		"State", filters={"is_major_state": 1}, fields=["name"], order_by="name asc", pluck="name"
	)
	other_states = frappe.get_all(
		"State", filters={"is_major_state": 0}, fields=["name"], order_by="name asc", pluck="name"
	)
	major_sectors = frappe.get_all(
		"Sectors", filters={"is_major_sector": 1}, fields=["name"], order_by="name asc", pluck="name"
	)
	return {
		"major_states": major_states,
		"other_states": other_states,
		"major_sectors": major_sectors,
		"quick_countries": QUICK_COUNTRIES,
	}


SEARCH_LIMIT = 20

# A single character matches most of the patient master, and every row it returns is one tap
# away from being queued as the wrong person.
MIN_SEARCH_LENGTH = 2


@frappe.whitelist()
def search_patient(query: str) -> dict:
	require_cad_access()

	query = (query or "").strip()
	if not query:
		return {"results": [], "capped": False}

	if len(query) < MIN_SEARCH_LENGTH:
		frappe.throw(_("Type at least {0} characters to search.").format(MIN_SEARCH_LENGTH))

	like = f"%{query}%"
	results = frappe.get_all(
		"Patient",
		or_filters=[
			["custom_bandhu_id", "like", like],
			["custom_abha_id", "like", like],
			["mobile", "like", like],
			["patient_name", "like", like],
			["dob", "like", like],
		],
		fields=["name", "patient_name", "custom_bandhu_id", "sex", "dob"],
		# One past the limit, so the front desk can be told the list was cut rather than
		# assuming the patient they want is not registered.
		limit=SEARCH_LIMIT + 1,
	)
	capped = len(results) > SEARCH_LIMIT
	results = results[:SEARCH_LIMIT]

	for row in results:
		row["age"] = compact_age(row.dob)

	# The search reads the whole patient master by design (a CAD legitimately meets patients
	# registered at another site), so the term is recorded rather than the search being narrowed.
	# This is one row per deliberate search, not per keystroke — cad_form.js fires it on Enter or
	# the search button only (cad_form.js:322-327) — and make_access_log defers the insert, so it
	# costs the request nothing.
	make_access_log(doctype="Patient", method="CAD Patient Search", filters=query)

	return {"results": results, "capped": capped}


@frappe.whitelist()
def get_patient_card_html(patient: str) -> str:
	require_cad_access()
	return render_patient_card(patient, "CAD Patient Card")


def require_running_session(session_name: str) -> dict:
	# Registration is gated on the session's status, not just the caller's role: the session
	# resolves the LSG and unit codes baked into the patient's permanent Clinic ID, and a
	# cancelled or not-yet-started session would stamp a location the patient was never seen at.
	session_doc = frappe.db.get_value(
		"Bandhu Clinic Session",
		session_name,
		["status", "assigned_doctor", "site"],
		as_dict=True,
	)
	if not session_doc:
		frappe.throw(_("Clinic session not found."))
	if session_doc.status == "Cancelled":
		frappe.throw(_("This clinic session was cancelled."))
	if session_doc.status == "Completed":
		frappe.throw(_("This clinic session is already completed."))
	if session_doc.status != "In Progress":
		frappe.throw(
			_("This clinic session hasn't started yet. Ask the nurse to start the session first."),
		)

	return session_doc


def resolve_registration_origin(session: str) -> tuple[str | None, str | None]:
	"""The LSG and unit whose numeric codes get baked into the patient's Clinic ID.

	Both are required here. make_clinic_id falls back to a reserved "unknown" code so a patient
	registered with no session context still gets a well-formed ID, but a session always has a
	site and a unit -- if either has no numeric code that is an unfilled master, and letting it
	through stamps "unknown location" into an identifier that is permanent and already printed
	on the patient's card by the time anyone notices.
	"""
	session_site, unit = frappe.db.get_value("Bandhu Clinic Session", session, ["site", "unit"])
	location = frappe.db.get_value("Site", session_site, "location") if session_site else None

	if not location:
		frappe.throw(
			_(
				"This session's site has no LSG set, so a Clinic ID cannot be issued. Ask an administrator to set it."
			)
		)
	if not frappe.db.get_value("Bandhu Location", location, "lsg_numeric_code"):
		frappe.throw(
			_(
				"{0} has no LSG number yet, so a Clinic ID cannot be issued. Ask an administrator to set it."
			).format(location)
		)
	if not unit:
		frappe.throw(
			_(
				"This session has no unit set, so a Clinic ID cannot be issued. Ask an administrator to set it."
			)
		)
	if not frappe.db.get_value("Unit", unit, "unit_numeric_code"):
		frappe.throw(
			_(
				"{0} has no unit number yet, so a Clinic ID cannot be issued. Ask an administrator to set it."
			).format(unit)
		)

	return location, unit


MAX_PLAUSIBLE_AGE = 120


def resolve_dob(dob: str | None, age: float | None) -> str:
	"""Field registration often can't get an exact birth date out of a migrant worker who knows
	their age but not their birthday. Jan 1 of the birth year marks the DOB as an estimate rather
	than today's month and day, which would read as a real recorded birthday it isn't. An explicit
	DOB always wins over a derived one."""
	dob = (dob or "").strip()
	if dob:
		return dob

	if age is None:
		frappe.throw(_("Date of birth or age is required."))
	if flt(age) < 0 or flt(age) > MAX_PLAUSIBLE_AGE:
		frappe.throw(_("Age must be between 0 and {0}.").format(MAX_PLAUSIBLE_AGE))

	return f"{getdate().year - int(flt(age))}-01-01"


# Deliberately a warning the front desk answers, not a rule the server enforces: migrant workers
# routinely share one mobile number between brothers, and two people can carry the same name and
# birth year. What must not happen silently is a second permanent Clinic ID and a second printed
# card for someone already registered.
@frappe.whitelist()
def find_possible_duplicate(
	full_name: str,
	dob: str | None = None,
	age: float | None = None,
	mobile: str | None = None,
	abha_id: str | None = None,
) -> dict | None:
	require_cad_access()

	full_name = (full_name or "").strip()
	mobile = (mobile or "").strip()
	abha_id = (abha_id or "").strip()
	if not full_name:
		return None

	# Strongest identifier first: ABHA is one person nationally, a mobile can be shared, and a
	# name with a birth date is the weakest of the three.
	candidates = []
	if abha_id:
		candidates.append((_("the same ABHA ID"), {"custom_abha_id": abha_id}))
	if mobile:
		candidates.append((_("the same mobile number"), {"mobile": mobile}))
	candidates.append(
		(_("the same name and date of birth"), {"patient_name": full_name, "dob": resolve_dob(dob, age)})
	)

	for matched_on, filters in candidates:
		match = frappe.get_all(
			"Patient",
			filters=filters,
			fields=["name", "patient_name", "custom_bandhu_id", "dob"],
			limit=1,
		)
		if match:
			row = match[0]
			return {
				"name": row.name,
				"patient_name": row.patient_name,
				"clinic_id": row.custom_bandhu_id,
				"age": compact_age(row.dob),
				"matched_on": matched_on,
			}

	return None


@frappe.whitelist(methods=["POST"])
def register_patient(
	full_name: str,
	sex: str,
	dob: str | None = None,
	age: float | None = None,
	session: str | None = None,
	mobile: str | None = None,
	height_cm: float | None = None,
	weight_kg: float | None = None,
	native_country: str | None = None,
	specify_native_country: str | None = None,
	native_state: str | None = None,
	native_district: str | None = None,
	occupation: str | None = None,
	specify_sector: str | None = None,
	company_name: str | None = None,
	abha_id: str | None = None,
) -> str:
	# Gate on the session rather than the role alone: the session decides which LSG and
	# unit codes end up in the patient's permanent Clinic ID.
	session = (session or "").strip() or None
	if session:
		require_session_access(session)
		require_running_session(session)
	else:
		require_cad_access()

	full_name = (full_name or "").strip()
	dob = (dob or "").strip()
	sex = (sex or "").strip()

	if not full_name:
		frappe.throw(_("Full name is required."))
	if not sex:
		frappe.throw(_("Sex is required."))

	dob = resolve_dob(dob, age)

	if height_cm is not None and flt(height_cm) < 0:
		frappe.throw(_("Height cannot be negative."))
	if weight_kg is not None and flt(weight_kg) < 0:
		frappe.throw(_("Weight cannot be negative."))

	mobile = (mobile or "").strip() or None
	if mobile:
		validate_phone_number(mobile, throw=True)
		if not re.fullmatch(r"\d{10}", mobile):
			frappe.throw(_("Mobile number must be exactly 10 digits."))

	abha_id = (abha_id or "").strip() or None
	if abha_id and frappe.db.exists("Patient", {"custom_abha_id": abha_id}):
		frappe.throw(_("Another patient is already registered with this ABHA ID."))

	name_parts = full_name.split(None, 1)
	first_name = name_parts[0]
	last_name = name_parts[1] if len(name_parts) > 1 else None

	registered_lsg, registered_unit = resolve_registration_origin(session) if session else (None, None)

	patient_fields = {
		"doctype": "Patient",
		"custom_registered_lsg": registered_lsg,
		"custom_registered_unit": registered_unit,
		"first_name": first_name,
		"last_name": last_name,
		"sex": sex,
		"dob": dob,
		"mobile": mobile,
		"custom_native_country": native_country or None,
		"custom_specify_native_country": specify_native_country or None,
		"custom_native_state": native_state or None,
		"custom_native_district": native_district or None,
		"custom_sector_of_employment": occupation or None,
		"custom_specify_employment_sector": specify_sector or None,
		"custom_name_of_company": company_name or None,
		"custom_abha_id": abha_id or None,
	}
	if height_cm:
		patient_fields["custom_height_m"] = flt(height_cm) / 100
	if weight_kg:
		patient_fields["custom_weight_kg"] = flt(weight_kg)

	patient = frappe.get_doc(patient_fields)
	patient.insert(ignore_permissions=True)

	return patient.name


@frappe.whitelist(methods=["POST"])
def create_encounter(patient: str, session: str) -> str:
	require_session_access(session)

	if not frappe.db.exists("Patient", patient):
		frappe.throw(_("Patient not found."))

	session_doc = require_running_session(session)
	if not session_doc.assigned_doctor:
		frappe.throw(
			_("No doctor is assigned to this clinic session yet. Cannot register patient."),
		)

	existing = frappe.db.get_value(
		"Patient Encounter",
		{
			"patient": patient,
			"custom_clinic_session": session,
			"custom_workflow_state": ["not in", list(TERMINAL_WORKFLOW_STATES)],
		},
		"name",
	)
	if existing:
		return existing

	patient_doc = frappe.get_doc("Patient", patient)

	encounter = frappe.get_doc(
		{
			"doctype": "Patient Encounter",
			"patient": patient,
			"patient_name": patient_doc.patient_name,
			"patient_sex": patient_doc.sex,
			"patient_age": patient_doc.get_age(),
			"practitioner": session_doc.assigned_doctor,
			"custom_clinic_session": session,
			# LSG, district and state on the encounter all fetch from this one link, and nothing
			# had ever set it -- which is why all three read empty on every visit ever recorded.
			"custom_location": frappe.db.get_value("Site", session_doc.site, "location")
			if session_doc.site
			else None,
			"custom_workflow_state": "Waiting for Doctor",
			"encounter_date": frappe.utils.today(),
		}
	)
	encounter.insert(ignore_permissions=True)

	return encounter.name


@frappe.whitelist()
def get_today_queue(session: str) -> list:
	require_session_access(session)

	# Read the encounters, not Patient Queue. That table holds one row per patient, overwritten
	# on every visit, so as soon as a patient attends a later session their row moves with them and
	# this session quietly loses them. The encounter is the visit.
	rows = frappe.get_all(
		"Patient Encounter",
		filters={"custom_clinic_session": session, "docstatus": ["<", 2]},
		fields=["name as encounter", "patient", "custom_workflow_state", "creation"],
		order_by="creation asc",
	)
	if not rows:
		return []

	patient_names = {row.patient for row in rows if row.patient}
	patients = frappe.get_all(
		"Patient",
		filters={"name": ["in", list(patient_names)]},
		fields=["name", "patient_name", "custom_bandhu_id"],
	)
	patient_by_name = {p.name: p for p in patients}

	return [
		{
			"patient": row.patient,
			"encounter": row.encounter,
			"patient_name": patient_by_name.get(row.patient, {}).get("patient_name", ""),
			"clinic_id": patient_by_name.get(row.patient, {}).get("custom_bandhu_id", ""),
			"current_stage": ENCOUNTER_TO_QUEUE_STAGE.get(row.custom_workflow_state, ""),
			"status": "Done" if row.custom_workflow_state in TERMINAL_WORKFLOW_STATES else "Active",
			"queued_at": row.creation,
		}
		for row in rows
	]


@frappe.whitelist(methods=["POST"])
def cancel_visit(encounter: str, session: str) -> None:
	"""End a visit the patient walked out of, so it leaves the doctor and nurse boards."""
	require_session_access(session)
	require_running_session(session)

	encounter_doc = frappe.get_doc("Patient Encounter", encounter)
	if encounter_doc.custom_clinic_session != session:
		frappe.throw(_("This encounter does not belong to the current clinic session."))

	if encounter_doc.custom_workflow_state in TERMINAL_WORKFLOW_STATES:
		frappe.throw(_("This visit has already ended."))

	encounter_doc.custom_workflow_state = "Cancelled"
	encounter_doc.save(ignore_permissions=True)
