import frappe


def execute():
	"""Clear dispensed_by on prescription rows nobody has dispensed yet.

	prescribe_medicine appended the row without the field, so Frappe filled it from the
	prescribing doctor's own User Permission on Healthcare Practitioner — a doctor recorded
	as the dispenser of medicine that was never handed over, against the field's own
	link_filters (nurses only). Rows already marked dispensed carry the real nurse and are
	left alone.
	"""
	prescription = frappe.qb.DocType("Prescription")
	frappe.qb.update(prescription).set(prescription.dispensed_by, "").where(
		(prescription.dispensed == 0) & (prescription.dispensed_by != "")
	).run()
