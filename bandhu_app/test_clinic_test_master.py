import frappe
from frappe.tests import IntegrationTestCase

from bandhu_app.bandhu_app.utils.clinic_test import (
	DEFAULT_TESTS,
	get_enabled_test_names,
	get_enabled_tests,
	seed_default_tests,
)
from bandhu_app.patches.seed_bandhu_tests import execute as run_seed_patch


class TestClinicTestMaster(IntegrationTestCase):
	def setUp(self):
		# IntegrationTestCase rolls back only once the class finishes, so a test that retires
		# a test or adds one is still visible to the next test in this class.
		seed_default_tests()
		seeded = [test["test_name"] for test in DEFAULT_TESTS]
		for name in frappe.get_all("Bandhu Test", filters={"name": ["not in", seeded]}, pluck="name"):
			frappe.delete_doc("Bandhu Test", name, force=True)
		frappe.db.set_value("Bandhu Test", {"name": ["in", seeded]}, "enabled", 1)

	def test_seed_patch_is_idempotent(self):
		run_seed_patch()
		first = frappe.get_all("Bandhu Test", pluck="name")

		run_seed_patch()
		run_seed_patch()

		self.assertEqual(sorted(frappe.get_all("Bandhu Test", pluck="name")), sorted(first))

	def test_seed_ships_the_five_tests_with_their_result_shapes(self):
		seed_default_tests()
		seeded = {
			test.name: test
			for test in frappe.get_all(
				"Bandhu Test",
				filters={"name": ["in", [test["test_name"] for test in DEFAULT_TESTS]]},
				fields=["name", "result_shape", "unit", "enabled"],
			)
		}

		self.assertEqual(seeded["Malaria"].result_shape, "Positive / Negative")
		self.assertIsNone(seeded["Malaria"].unit)
		self.assertEqual(seeded["Hb"].result_shape, "Value")
		self.assertEqual(seeded["Hb"].unit, "g/dL")
		self.assertEqual(seeded["GRBS"].unit, "mg/dL")
		self.assertTrue(all(test.enabled for test in seeded.values()))

	def test_reseeding_does_not_resurrect_a_retired_test(self):
		seed_default_tests()
		frappe.db.set_value("Bandhu Test", "Leptospirosis", "enabled", 0)

		run_seed_patch()

		self.assertEqual(frappe.db.get_value("Bandhu Test", "Leptospirosis", "enabled"), 0)

	def test_a_unit_is_dropped_when_a_test_stops_being_a_value_test(self):
		doc = frappe.new_doc("Bandhu Test")
		doc.update({"test_name": "Widal", "result_shape": "Value", "unit": "titre"})
		doc.insert()

		doc.result_shape = "Positive / Negative"
		doc.save()

		self.assertIsNone(doc.unit)

	def test_disabled_test_leaves_the_options_but_its_history_still_reads(self):
		seed_default_tests()
		self.assertIn("Dengue", get_enabled_test_names())

		frappe.db.set_value("Bandhu Test", "Dengue", "enabled", 0)

		self.assertNotIn("Dengue", get_enabled_test_names())
		# The master record survives, so every encounter already linked to it still resolves.
		self.assertTrue(frappe.db.exists("Bandhu Test", "Dengue"))

	def test_options_come_back_in_display_order(self):
		seed_default_tests()
		ordered = [test.name for test in get_enabled_tests()]

		self.assertLess(ordered.index("Malaria"), ordered.index("Hb"))
		self.assertLess(ordered.index("Dengue"), ordered.index("GRBS"))
