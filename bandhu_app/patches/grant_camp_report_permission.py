import frappe
from frappe.permissions import add_permission, update_permission_property

# A Number Card runs through the report engine, so `read` on the doctype is not enough -- a role
# without `report` gets a blocking "You don't have permission to get a report on ..." dialog the
# moment it opens the Dashboard. Both roles already hold read here, so this grants no data they
# could not already see.
SESSION_REPORT_ROLES = ("Director", "Programme Manager")


def execute():
	for role in SESSION_REPORT_ROLES:
		if not frappe.db.exists("Role", role):
			continue
		add_permission("Bandhu Clinic Session", role, 0)
		update_permission_property("Bandhu Clinic Session", role, 0, "report", 1)
