import frappe

# Healthcare's Patient.after_insert creates a Customer for every patient when this is on, so it
# can raise a Sales Invoice against them later. CMID's mobile clinics are free -- this site has
# 33 patients, 33 customers and no Sales Invoice at all -- and the only thing the front desk ever
# saw of it was a "Customer <name> created and linked to Patient" alert stacked on top of their
# own registration message. Turn it back on the day CMID starts billing; the 33 customers already
# created are left alone so that day needs no backfill.


def execute():
	frappe.db.set_single_value("Healthcare Settings", "link_customer_to_patient", 0)
