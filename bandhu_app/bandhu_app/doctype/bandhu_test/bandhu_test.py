# Copyright (c) 2026, CMID and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class BandhuTest(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		display_order: DF.Int
		enabled: DF.Check
		result_shape: DF.Literal["Positive / Negative", "Value"]
		test_name: DF.Data
		unit: DF.Data | None
	# end: auto-generated types

	def validate(self):
		# A unit left behind after a test is flipped back to Positive/Negative would print
		# "Negative g/dL" on the nurse's board.
		if self.result_shape != "Value":
			self.unit = None
