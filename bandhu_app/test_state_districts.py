# Copyright (c) 2026, CMID and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from bandhu_app.bandhu_app.utils.state_districts import get_districts

EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = []


class IntegrationTestStateDistricts(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.cad_user = cls._make_user("test.districts.cad@bandhuapp.test", ["Clinic Assistant cum Driver"])
		cls.no_role_user = cls._make_user("test.districts.norole@bandhuapp.test", [])

	@classmethod
	def _make_user(cls, email, roles):
		if frappe.db.exists("User", email):
			user = frappe.get_doc("User", email)
		else:
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": email.split("@")[0],
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)

		if roles:
			user.add_roles(*roles)

		return email

	def _make_state(self, state_name):
		existing = frappe.db.get_value("State", {"state_name": state_name}, "name")
		if existing:
			return existing

		return (
			frappe.get_doc({"doctype": "State", "state_name": state_name})
			.insert(ignore_permissions=True)
			.name
		)

	def test_cad_gets_the_district_list_the_registration_form_needs(self):
		state = self._make_state("Bihar")

		frappe.set_user(self.cad_user)
		try:
			districts = get_districts(state=state)
			filtered = get_districts(txt="pat", state=state)
		finally:
			frappe.set_user("Administrator")

		self.assertIn("Patna", districts)
		self.assertEqual(filtered, ["Patna"])

	def test_user_without_the_cad_role_is_blocked(self):
		state = self._make_state("Bihar")

		frappe.set_user(self.no_role_user)
		try:
			self.assertRaises(frappe.PermissionError, get_districts, "", state)
		finally:
			frappe.set_user("Administrator")
