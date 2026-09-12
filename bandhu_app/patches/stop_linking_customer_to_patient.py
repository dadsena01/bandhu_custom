import frappe

# The clinics do not bill, and each new Customer raised an alert on registration.


def execute():
	frappe.db.set_single_value("Healthcare Settings", "link_customer_to_patient", 0)
