import frappe
from frappe import _
from frappe.core.doctype.access_log.access_log import make_access_log
from frappe.utils import flt, getdate, today

PATIENT_CARD_PRINT_FORMAT = "Bandhu Patient Card"


def render_patient_card(patient: str, access_method: str) -> str:
	"""Callers must check access first: this renders with print permissions ignored."""
	patient = (patient or "").strip()
	if not frappe.db.exists("Patient", patient):
		frappe.throw(_("Patient not found."), frappe.DoesNotExistError)

	make_access_log(doctype="Patient", document=patient, method=access_method)

	frappe.flags.ignore_print_permissions = True
	try:
		return frappe.get_print(
			"Patient",
			patient,
			print_format=PATIENT_CARD_PRINT_FORMAT,
			no_letterhead=True,
		)
	finally:
		frappe.flags.ignore_print_permissions = False


def compact_age(dob) -> str:
	# Healthcare's own get_age() returns "47 Year(s) 6 Month(s) 15 Day(s)", which wraps to
	# three lines in a queue row. Infants still need months and days to be clinically useful.
	if not dob:
		return ""

	dob = getdate(dob)
	reference = getdate(today())
	if dob > reference:
		return ""

	years = reference.year - dob.year - ((reference.month, reference.day) < (dob.month, dob.day))
	if years >= 1:
		return f"{years}y"

	months = (reference.year - dob.year) * 12 + reference.month - dob.month - (reference.day < dob.day)
	if months >= 1:
		return f"{months}mo"

	return f"{(reference - dob).days}d"


def attach_patient_display_fields(encounters: list) -> list:
	"""Overwrite each row's `patient_age` with the display form and carry the Clinic ID down,
	in one query for the whole batch."""
	patients = {encounter.patient for encounter in encounters if encounter.get("patient")}
	if not patients:
		return encounters

	patient_details = {
		row.name: row
		for row in frappe.get_all(
			"Patient",
			filters={"name": ["in", list(patients)]},
			fields=["name", "dob", "custom_bandhu_id"],
		)
	}
	for encounter in encounters:
		details = patient_details.get(encounter.patient) or {}
		encounter.patient_age = compact_age(details.get("dob"))
		encounter.clinic_id = details.get("custom_bandhu_id") or ""

	return encounters


def validate_bmi(doc, method):
	h = flt(doc.custom_height_m)
	w = flt(doc.custom_weight_kg)
	if h > 0 and w > 0:
		doc.custom_bmi = round(w / (h * h), 2)
	else:
		doc.custom_bmi = None


AGE_GROUPS = ((15, "0-14"), (30, "15-29"), (45, "30-44"), (60, "45-59"))


def age_group(dob, reference=None) -> str:
	"""Bucket used by the scope's reports. Bands are our own until CMID confirms theirs."""
	if not dob:
		return "Unknown"

	dob = getdate(dob)
	reference = getdate(reference or today())
	if dob > reference:
		return "Unknown"

	years = reference.year - dob.year - ((reference.month, reference.day) < (dob.month, dob.day))
	for upper_bound, label in AGE_GROUPS:
		if years < upper_bound:
			return label

	return "60+"
