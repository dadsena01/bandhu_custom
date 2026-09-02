import base64
import io

import frappe
import qrcode
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers.pil import HorizontalBarsDrawer


def make_qr_image(data: str) -> bytes:
	qr = qrcode.QRCode(
		version=1,
		error_correction=qrcode.constants.ERROR_CORRECT_H,
		box_size=10,
		border=4,
	)
	qr.add_data(data)
	qr.make(fit=True)

	img = qr.make_image(image_factory=StyledPilImage, module_drawer=HorizontalBarsDrawer())

	output = io.BytesIO()
	img.save(output, format="PNG")
	return output.getvalue()


def generate_qr_code_file(doc, data: str, field_name="custom_qr_code"):
	qr_data = make_qr_image(data)

	file_doc = frappe.new_doc("File")
	file_doc.content = qr_data
	file_doc.attached_to_doctype = doc.doctype
	file_doc.attached_to_name = doc.name
	file_doc.attached_to_field = field_name
	file_doc.file_name = f"{doc.custom_bandhu_id}.png"
	# Clinic IDs are sequential, so a public /files/<clinic_id>.png is trivially enumerable
	# by an unauthenticated visitor. Keep patient QR images behind permission checks.
	file_doc.is_private = 1
	file_doc.insert()

	return file_doc.file_url


def get_qr_code_image_source(file_url: str) -> str:
	"""Return the QR image as a data URI for use in an <img src>.

	The QR file is private, and a browser fetches an <img src> in its own request
	authenticated as whoever is viewing — on the patient card that is the CAD user, who
	holds no Patient permission and would get a 403 with the QR silently missing.
	"""
	if not file_url:
		return ""

	file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not file_name:
		return ""

	content = frappe.get_doc("File", file_name).get_content()
	return f"data:image/png;base64,{base64.b64encode(content).decode()}"
