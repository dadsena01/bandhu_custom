# Copyright (c) 2026, CMID and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document


class BandhuLocation(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		district: DF.Data | None
		location_name: DF.Data | None
		lsg: DF.Data | None
		lsg_code: DF.Data | None
		lsg_numeric_code: DF.Data | None
		phcchc: DF.Data | None
		state: DF.Data | None
	# end: auto-generated types

	def validate(self):
		if self.lsg_numeric_code and not re.fullmatch(r"\d{2}", self.lsg_numeric_code):
			frappe.throw(_("LSG Numeric Code must be exactly two digits, for example 01."))

		self.block_code_change_once_issued()

	def block_code_change_once_issued(self):
		# Every Clinic ID issued here embeds this code. Changing it would make those
		# already-printed cards decode to a different location.
		if self.is_new():
			return

		previous_code = self.get_doc_before_save()
		if not previous_code or previous_code.lsg_numeric_code == self.lsg_numeric_code:
			return

		if frappe.db.exists("Patient", {"custom_registered_lsg": self.name}):
			frappe.throw(
				_(
					"Clinic IDs have already been issued at this location, so its numeric code can no longer be changed."
				)
			)
