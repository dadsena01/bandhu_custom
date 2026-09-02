# Copyright (c) 2026, CMID and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

ASSIGNMENT_ROLE_BY_FIELD = {
	"assigned_doctor": "Doctor",
	"assigned_nurse": "Nurse",
	"assigned_driver": "Clinic Assistant cum Driver",
}


class BandhuClinicSession(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		arrival_time: DF.Time | None
		assigned_doctor: DF.Link | None
		assigned_driver: DF.Link | None
		assigned_nurse: DF.Link | None
		clinic: DF.Link
		date: DF.Date
		departure_time: DF.Time | None
		distance_travelled_km: DF.Data | None
		end_time: DF.Datetime | None
		notes: DF.SmallText | None
		planned_end_time: DF.Time | None
		planned_start_time: DF.Time | None
		project: DF.Link
		session_schedule: DF.Link | None
		site: DF.Link
		start_time: DF.Datetime | None
		status: DF.Literal["Planned", "In Progress", "Completed", "Cancelled"]
		unit: DF.Link | None
		vehicle: DF.Link | None
	# end: auto-generated types

	def validate(self):
		self.validate_assignment_roles()

	def validate_assignment_roles(self):
		for fieldname, required_role in ASSIGNMENT_ROLE_BY_FIELD.items():
			practitioner = self.get(fieldname)
			if not practitioner:
				continue
			actual_role = frappe.get_cached_value("Healthcare Practitioner", practitioner, "custom_role")
			if actual_role != required_role:
				frappe.throw(
					_("{0} must be a Healthcare Practitioner with role {1}, but {2} has role {3}.").format(
						self.meta.get_field(fieldname).label,
						required_role,
						practitioner,
						actual_role or _("(none)"),
					),
				)
