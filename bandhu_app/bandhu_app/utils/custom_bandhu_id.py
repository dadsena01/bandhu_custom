import frappe
from frappe import _
from frappe.model.naming import getseries
from frappe.utils import now_datetime

SERIAL_DIGITS = 5
SERIAL_CEILING = 10**SERIAL_DIGITS - 1

# Registrations that reach us without session context still need a well-formed ID.
# These reserved codes make such records findable later instead of silently
# borrowing some real location's or unit's code.
UNKNOWN_LSG_CODE = "00"
UNKNOWN_UNIT_CODE = "0"


def set_bandhu_id(doc, method):
	if doc.custom_bandhu_id:
		return

	doc.custom_bandhu_id = make_clinic_id(doc.custom_registered_lsg, doc.custom_registered_unit)


def make_clinic_id(location: str | None, unit: str | None) -> str:
	"""LSG(2) + Unit(1) + Year(2) + Serial(5). Ten digits, permanent once issued."""
	lsg_code = (
		frappe.db.get_value("Bandhu Location", location, "lsg_numeric_code") if location else None
	) or UNKNOWN_LSG_CODE
	unit_code = (
		frappe.db.get_value("Unit", unit, "unit_numeric_code") if unit else None
	) or UNKNOWN_UNIT_CODE

	year = now_datetime().strftime("%y")

	return f"{lsg_code}{unit_code}{year}{next_serial(year)}"


def next_serial(year: str) -> str:
	# The serial deliberately resets per year and runs global across every LSG and unit.
	# Scoping it by LSG or unit would tie a permanent identifier to attributes that get
	# corrected and reorganised, so a later correction would force the ID to change.
	serial = getseries(f"BANDHU-CLINIC-ID-{year}", SERIAL_DIGITS)

	if int(serial) > SERIAL_CEILING:
		frappe.throw(
			_(
				"Clinic ID serial numbers for {0} are exhausted; the format cannot represent more than {1} patients in one year."
			).format(year, SERIAL_CEILING)
		)

	return serial
