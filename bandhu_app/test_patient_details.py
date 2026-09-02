# Copyright (c) 2026, CMID and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from bandhu_app.bandhu_app.utils.clinic_test import seed_default_tests
from bandhu_app.bandhu_app.utils.patient_details import attach_test_shapes, shared_test_note


class TestPatientDetails(IntegrationTestCase):
	def test_shared_test_note_is_the_note_when_every_row_carries_it(self):
		self.assertEqual(
			shared_test_note([{"notes": "Fever 3 days"}, {"notes": "Fever 3 days"}]),
			"Fever 3 days",
		)

	def test_shared_test_note_is_none_when_one_row_disagrees(self):
		self.assertIsNone(shared_test_note([{"notes": "Fever 3 days"}, {"notes": "Pallor"}]))

	def test_shared_test_note_is_none_when_only_some_rows_carry_it(self):
		self.assertIsNone(shared_test_note([{"notes": "Fever 3 days"}, {"notes": None}]))

	def test_shared_test_note_is_none_when_nobody_wrote_one(self):
		self.assertIsNone(shared_test_note([{"notes": ""}, {"notes": None}]))

	def test_shared_test_note_is_none_for_a_patient_with_no_tests(self):
		self.assertIsNone(shared_test_note([]))

	def test_attach_test_shapes_carries_the_masters_shape_and_unit(self):
		"""A value test has to print its number and unit; the row alone cannot say which
		shape it is, because an ordered-but-untested row has no result_type."""
		seed_default_tests()
		tests = [frappe._dict({"test_name": "Hb"}), frappe._dict({"test_name": "Malaria"})]

		attach_test_shapes(tests)

		self.assertEqual((tests[0].result_shape, tests[0].unit), ("Value", "g/dL"))
		self.assertEqual(tests[1].result_shape, "Positive / Negative")

	def test_attach_test_shapes_leaves_a_row_without_a_master_blank(self):
		tests = [frappe._dict({"test_name": "Retired Test"})]

		attach_test_shapes(tests)

		self.assertIsNone(tests[0].result_shape)
