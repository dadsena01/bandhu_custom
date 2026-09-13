# Copyright (c) 2026, CMID and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from bandhu_app.patches.show_practitioner_name_in_links import DOCTYPE, PROPERTY, execute


class IntegrationTestShowPractitionerNameInLinks(IntegrationTestCase):
	def property_setters(self):
		return frappe.get_all(
			"Property Setter",
			filters={"doc_type": DOCTYPE, "property": PROPERTY, "doctype_or_field": "DocType"},
			pluck="name",
		)

	def clear_setting(self):
		"""The patch has already run on this site, so every test starts from the pre-patch state."""
		for name in self.property_setters():
			frappe.delete_doc("Property Setter", name, force=True)
		frappe.clear_cache(doctype=DOCTYPE)

	def test_patch_makes_practitioner_links_render_the_name(self):
		self.clear_setting()
		self.assertFalse(frappe.get_meta(DOCTYPE).show_title_field_in_link)

		execute()

		self.assertEqual(len(self.property_setters()), 1)
		meta = frappe.get_meta(DOCTYPE)
		self.assertTrue(meta.show_title_field_in_link)
		# Without a title field to show, the flag would make Desk render nothing.
		self.assertEqual(meta.title_field, "practitioner_name")

	def test_patch_is_idempotent(self):
		self.clear_setting()

		execute()
		execute()
		execute()

		self.assertEqual(len(self.property_setters()), 1)
