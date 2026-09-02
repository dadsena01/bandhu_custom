import frappe
from frappe.utils import create_batch

from bandhu_app.bandhu_app.utils.custom_qr_code import generate_qr_code_file

BATCH_SIZE = 200


def execute():
	"""QR images used to encode an API URL, which scans to a raw JSON page. Re-issue them
	against the bare Clinic ID so a scanner or a phone camera both read something usable."""
	patients = frappe.get_all(
		"Patient",
		filters={"custom_bandhu_id": ["is", "set"]},
		fields=["name", "custom_bandhu_id"],
	)
	if not patients:
		return

	# A QR render and a File write per patient would hold a large site in maintenance mode
	# for hours; the old images stay readable until the job replaces them.
	frappe.enqueue(
		"bandhu_app.patches.regenerate_patient_qr_codes.regenerate_qr_codes",
		queue="long",
		timeout=36000,
		enqueue_after_commit=True,
		now=frappe.in_test,
		patients=patients,
	)


def regenerate_qr_codes(patients: list) -> None:
	for batch in create_batch(patients, BATCH_SIZE):
		remove_qr_files([patient["name"] for patient in batch])

		for patient in batch:
			file_url = generate_qr_code_file(
				doc=frappe._dict(
					doctype="Patient",
					name=patient["name"],
					custom_bandhu_id=patient["custom_bandhu_id"],
				),
				data=patient["custom_bandhu_id"],
				field_name="custom_qr_code",
			)
			frappe.db.set_value("Patient", patient["name"], "custom_qr_code", file_url, update_modified=False)

		frappe.db.commit()


def remove_qr_files(patient_names: list) -> None:
	stale_files = frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": "Patient",
			"attached_to_name": ["in", patient_names],
			"attached_to_field": "custom_qr_code",
		},
		pluck="name",
	)
	for file_name in stale_files:
		frappe.delete_doc("File", file_name, force=True, ignore_permissions=True)
