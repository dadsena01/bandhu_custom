# Copyright (c) 2026, CMID and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

MAX_HORIZON_DAYS = 730


class BandhuSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		disable_auto_session_generation: DF.Check
		session_horizon_days: DF.Int
	# end: auto-generated types

	def validate(self):
		# An unbounded horizon would have the nightly job create sessions for every
		# site until the end of time on its first run.
		if self.session_horizon_days and self.session_horizon_days > MAX_HORIZON_DAYS:
			frappe.throw(_("Sessions cannot be generated more than {0} days ahead.").format(MAX_HORIZON_DAYS))
