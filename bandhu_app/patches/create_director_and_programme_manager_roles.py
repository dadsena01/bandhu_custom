import frappe

ROLES = ("Director", "Programme Manager")


def execute():
	"""No Director or Programme Manager role existed anywhere in the system, so the
	Dashboard workspace and every scope report were left System Manager-only — nobody
	CMID actually calls a director could see them. Desk access, same as Doctor/Nurse."""
	for role in ROLES:
		if frappe.db.exists("Role", role):
			continue
		frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(
			ignore_permissions=True
		)
