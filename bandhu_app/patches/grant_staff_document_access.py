import frappe
from frappe.permissions import add_permission, update_permission_property

DOCUMENT_ROLES = ("System Manager",)


def execute():
	for role in DOCUMENT_ROLES:
		add_permission("User", role, 1)
		update_permission_property("User", role, 1, "read", 1)
		update_permission_property("User", role, 1, "write", 1)
