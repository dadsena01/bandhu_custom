# Copyright (c) 2026, CMID and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document


class Unit(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		cad: DF.Link | None
		doctor: DF.Link | None
		nurse: DF.Link | None
		unit_code: DF.Data | None
		unit_name: DF.Data | None
		unit_numeric_code: DF.Data | None
	# end: auto-generated types

	def validate(self):
		if self.unit_numeric_code and not re.fullmatch(r"\d", self.unit_numeric_code):
			frappe.throw(_("Unit Numeric Code must be exactly one digit, for example 1."))

		self.block_code_change_once_issued()

	def block_code_change_once_issued(self):
		# Every Clinic ID issued by this unit embeds this digit. Changing it would make
		# those already-printed cards decode to a different unit.
		if self.is_new():
			return

		previous_unit = self.get_doc_before_save()
		if not previous_unit or previous_unit.unit_numeric_code == self.unit_numeric_code:
			return

		if frappe.db.exists("Patient", {"custom_registered_unit": self.name}):
			frappe.throw(
				_(
					"Clinic IDs have already been issued by this unit, so its numeric code can no longer be changed."
				)
			)
