import frappe

# The five tests CMID's camps have always run. They ship as data so the clinic can add a
# sixth without a deploy; these are only the out-of-the-box seed, not a source of truth.
DEFAULT_TESTS = (
	{"test_name": "Malaria", "result_shape": "Positive / Negative", "display_order": 10},
	{"test_name": "Dengue", "result_shape": "Positive / Negative", "display_order": 20},
	{"test_name": "Leptospirosis", "result_shape": "Positive / Negative", "display_order": 30},
	{"test_name": "Hb", "result_shape": "Value", "unit": "g/dL", "display_order": 40},
	{"test_name": "GRBS", "result_shape": "Value", "unit": "mg/dL", "display_order": 50},
)


def get_enabled_tests() -> list[dict]:
	"""Every enabled test, in display order. One query — call it once per request and pass
	the list down, never per encounter."""
	return frappe.get_all(
		"Bandhu Test",
		filters={"enabled": 1},
		fields=["name", "test_name", "result_shape", "unit", "display_order"],
		order_by="display_order asc, test_name asc",
	)


def get_enabled_test_names() -> set[str]:
	return {test.name for test in get_enabled_tests()}


def seed_default_tests() -> None:
	"""Idempotent: an existing record is left exactly as the clinic edited it, including a
	test they retired with `enabled = 0`. Re-seeding must never resurrect that."""
	existing = set(frappe.get_all("Bandhu Test", pluck="name"))

	for test in DEFAULT_TESTS:
		if test["test_name"] in existing:
			continue

		doc = frappe.new_doc("Bandhu Test")
		doc.update(test)
		doc.insert(ignore_permissions=True)
