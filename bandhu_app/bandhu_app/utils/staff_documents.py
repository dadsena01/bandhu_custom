import frappe
from frappe import _

MAX_STAFF_DOCUMENTS = 10


def validate_staff_documents(doc, method=None) -> None:
	rows = doc.get("custom_staff_documents") or []
	if len(rows) > MAX_STAFF_DOCUMENTS:
		frappe.throw(_("A staff member can hold at most {0} documents.").format(MAX_STAFF_DOCUMENTS))

	for row in rows:
		if not (row.document_name or "").strip():
			frappe.throw(_("Every document needs a name, so anyone reading the record knows what it is."))
		if not row.document_file:
			frappe.throw(_("{0} has no file attached.").format(row.document_name))

	make_documents_private(rows)


def make_documents_private(rows) -> None:
	for row in rows:
		if not (row.document_file or "").startswith("/files/"):
			continue

		file_name = frappe.db.get_value("File", {"file_url": row.document_file, "is_private": 0}, "name")
		if not file_name:
			continue

		file_doc = frappe.get_doc("File", file_name)
		file_doc.is_private = 1
		file_doc.save(ignore_permissions=True)
		row.document_file = file_doc.file_url
