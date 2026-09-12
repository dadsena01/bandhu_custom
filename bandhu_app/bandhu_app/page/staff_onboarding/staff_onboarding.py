import re

import frappe
from frappe import _
from frappe.utils import validate_email_address, validate_phone_number

PROVISIONABLE_ROLES = ["Doctor", "Nurse", "Clinic Assistant cum Driver"]

# Gender records come from the setup wizard, which a bench-created site never runs.
OFFERED_GENDERS = ["Male", "Female", "Other"]


def seed_default_genders() -> None:
	existing = set(frappe.get_all("Gender", pluck="name"))

	for gender in OFFERED_GENDERS:
		if gender in existing:
			continue

		frappe.get_doc({"doctype": "Gender", "gender": gender}).insert(ignore_permissions=True)


def require_system_manager() -> None:
	if "System Manager" not in frappe.get_roles():
		frappe.throw(
			_("You do not have permission to access this page."),
			frappe.PermissionError,
		)


@frappe.whitelist()
def get_form_options() -> dict:
	require_system_manager()
	# Offer only what the master actually holds, so the form can never post a value that
	# fails Link validation on save.
	existing = set(frappe.get_all("Gender", pluck="name"))
	genders = [gender for gender in OFFERED_GENDERS if gender in existing]
	return {"roles": PROVISIONABLE_ROLES, "genders": genders}


@frappe.whitelist(methods=["POST"])
def provision_staff_member(
	first_name: str,
	email: str,
	role: str,
	last_name: str | None = None,
	mobile_phone: str | None = None,
	gender: str | None = None,
) -> dict:
	require_system_manager()

	first_name = (first_name or "").strip()
	last_name = (last_name or "").strip() or None
	email = (email or "").strip()
	role = (role or "").strip()
	mobile_phone = (mobile_phone or "").strip() or None
	gender = (gender or "").strip() or None

	if not first_name:
		frappe.throw(_("First name is required."))
	if not email:
		frappe.throw(_("Email is required."))
	validate_email_address(email, throw=True)
	if role not in PROVISIONABLE_ROLES:
		frappe.throw(_("{0} is not a role this tool can provision.").format(role))
	if frappe.db.exists("User", email):
		frappe.throw(_("A user with email {0} already exists.").format(email))
	if mobile_phone:
		validate_phone_number(mobile_phone, throw=True)
		if not re.fullmatch(r"\d{10}", mobile_phone):
			frappe.throw(_("Mobile number must be exactly 10 digits."))

	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": first_name,
			"last_name": last_name,
			"mobile_no": mobile_phone,
			"send_welcome_email": 0,
			"roles": [{"role": role}],
		}
	).insert()

	practitioner = frappe.get_doc(
		{
			"doctype": "Healthcare Practitioner",
			"first_name": first_name,
			"last_name": last_name,
			"gender": gender,
			"mobile_phone": mobile_phone,
			"custom_role": role,
			"user_id": user.name,
			"status": "Active",
		}
	).insert(ignore_permissions=True)

	email_sent = True
	try:
		user._reset_password(send_email=True)
	except frappe.OutgoingEmailError:
		frappe.clear_last_message()
		frappe.log_error(title="Staff onboarding: set-password email failed", message=frappe.get_traceback())
		email_sent = False

	return {"user": user.name, "practitioner": practitioner.name, "email_sent": email_sent}


@frappe.whitelist(methods=["POST"])
def save_staff_documents(user: str, documents: list | str) -> int:
	require_system_manager()

	if not frappe.db.exists("User", user):
		frappe.throw(_("Staff member not found."))

	documents = frappe.parse_json(documents) or []

	doc = frappe.get_doc("User", user)
	doc.set("custom_staff_documents", [])
	for row in documents:
		doc.append(
			"custom_staff_documents",
			{
				"document_name": (row.get("document_name") or "").strip(),
				"document_file": row.get("document_file"),
			},
		)
	doc.save(ignore_permissions=True)

	return len(doc.custom_staff_documents)


@frappe.whitelist()
def get_staff_documents(user: str) -> list:
	require_system_manager()
	return frappe.get_all(
		"Bandhu Staff Document",
		filters={"parent": user, "parenttype": "User"},
		fields=["name", "document_name", "document_file"],
		order_by="idx asc",
	)
