import frappe
from frappe.tests import IntegrationTestCase

from bandhu_app.bandhu_app.page.staff_onboarding.staff_onboarding import (
	PROVISIONABLE_ROLES,
	get_form_options,
	provision_staff_member,
	save_staff_documents,
)
from bandhu_app.bandhu_app.utils.staff_documents import MAX_STAFF_DOCUMENTS

EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = []


class IntegrationTestStaffOnboarding(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.system_manager_user = cls._make_user("test.onboard.admin@bandhuapp.test", ["System Manager"])
		cls.no_role_user = cls._make_user("test.onboard.norole@bandhuapp.test", [])

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

	def _as_system_manager(self, fn, *args, **kwargs):
		frappe.set_user(self.system_manager_user)
		try:
			return fn(*args, **kwargs)
		finally:
			frappe.set_user("Administrator")

	def test_non_system_manager_blocked(self):
		frappe.set_user(self.no_role_user)
		try:
			self.assertRaises(frappe.PermissionError, get_form_options)
			self.assertRaises(
				frappe.PermissionError,
				provision_staff_member,
				first_name="Blocked",
				last_name=None,
				email="test.onboard.blocked@bandhuapp.test",
				role="Doctor",
			)
		finally:
			frappe.set_user("Administrator")

	def test_get_form_options_returns_real_masters(self):
		options = self._as_system_manager(get_form_options)
		self.assertEqual(set(options["roles"]), set(PROVISIONABLE_ROLES))
		# The Gender master holds seven; the form offers the three the paper forms use.
		self.assertEqual(options["genders"], ["Male", "Female", "Other"])

	def test_provision_creates_linked_user_and_practitioner(self):
		email = "test.onboard.newdoctor@bandhuapp.test"
		self.addCleanup(self._cleanup_provisioned, email)

		result = self._as_system_manager(
			provision_staff_member,
			first_name="Test",
			last_name="Onboard Doctor",
			email=email,
			role="Doctor",
			mobile_phone="9876543210",
			gender="Male",
		)

		user = frappe.get_doc("User", result["user"])
		self.assertIn("Doctor", [r.role for r in user.roles])
		self.assertTrue(user.reset_password_key)

		practitioner = frappe.get_doc("Healthcare Practitioner", result["practitioner"])
		self.assertEqual(practitioner.user_id, email)
		self.assertEqual(practitioner.custom_role, "Doctor")
		self.assertEqual(practitioner.status, "Active")

	def test_provision_works_without_a_last_name(self):
		frappe.set_user(self.system_manager_user)
		try:
			result = provision_staff_member(
				first_name="Onename",
				email="test.onboard.onename@bandhuapp.test",
				role="Nurse",
			)
		finally:
			frappe.set_user("Administrator")

		self.assertTrue(frappe.db.exists("Healthcare Practitioner", result["practitioner"]))

	def test_documents_are_saved_against_the_staff_member(self):
		staff_user = self._provision("test.onboard.docs@bandhuapp.test")

		frappe.set_user(self.system_manager_user)
		try:
			saved = save_staff_documents(
				staff_user,
				[{"document_name": "Nursing registration", "document_file": "/private/files/a.pdf"}],
			)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(saved, 1)
		doc = frappe.get_doc("User", staff_user)
		self.assertEqual(doc.custom_staff_documents[0].document_name, "Nursing registration")

	def test_documents_are_capped(self):
		staff_user = self._provision("test.onboard.manydocs@bandhuapp.test")
		too_many = [
			{"document_name": f"Paper {index}", "document_file": f"/private/files/{index}.pdf"}
			for index in range(MAX_STAFF_DOCUMENTS + 1)
		]

		frappe.set_user(self.system_manager_user)
		try:
			self.assertRaises(frappe.ValidationError, save_staff_documents, staff_user, too_many)
		finally:
			frappe.set_user("Administrator")

	def test_a_document_without_a_name_is_rejected(self):
		staff_user = self._provision("test.onboard.unnamed@bandhuapp.test")

		frappe.set_user(self.system_manager_user)
		try:
			self.assertRaises(
				frappe.ValidationError,
				save_staff_documents,
				staff_user,
				[{"document_name": "   ", "document_file": "/private/files/b.pdf"}],
			)
		finally:
			frappe.set_user("Administrator")

	def test_a_public_upload_is_forced_private(self):
		staff_user = self._provision("test.onboard.publicfile@bandhuapp.test")
		public_file = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "staff-id.txt",
				"content": "scan",
				"is_private": 0,
			}
		).insert(ignore_permissions=True)

		frappe.set_user(self.system_manager_user)
		try:
			save_staff_documents(
				staff_user,
				[{"document_name": "ID proof", "document_file": public_file.file_url}],
			)
		finally:
			frappe.set_user("Administrator")

		self.assertTrue(frappe.db.get_value("File", public_file.name, "is_private"))

	def _provision(self, email):
		frappe.set_user(self.system_manager_user)
		try:
			return provision_staff_member(first_name=email.split("@")[0], email=email, role="Nurse")["user"]
		finally:
			frappe.set_user("Administrator")

	def test_provision_rejects_non_provisionable_role(self):
		with self.assertRaises(frappe.ValidationError):
			self._as_system_manager(
				provision_staff_member,
				first_name="Test",
				last_name=None,
				email="test.onboard.helpline@bandhuapp.test",
				role="Helpline Staff",
			)
		self.assertFalse(frappe.db.exists("User", "test.onboard.helpline@bandhuapp.test"))

	def test_provision_rejects_duplicate_email(self):
		with self.assertRaises(frappe.ValidationError):
			self._as_system_manager(
				provision_staff_member,
				first_name="Test",
				last_name=None,
				email=self.system_manager_user,
				role="Doctor",
			)

	def test_provision_rejects_malformed_email(self):
		with self.assertRaises(frappe.ValidationError):
			self._as_system_manager(
				provision_staff_member,
				first_name="Test",
				last_name=None,
				email="not-an-email",
				role="Doctor",
			)

	def test_provision_rejects_short_mobile_number(self):
		email = "test.onboard.badmobile@bandhuapp.test"
		with self.assertRaises(frappe.ValidationError):
			self._as_system_manager(
				provision_staff_member,
				first_name="Test",
				last_name=None,
				email=email,
				role="Nurse",
				mobile_phone="12345",
			)
		self.assertFalse(frappe.db.exists("User", email))

	def _cleanup_provisioned(self, email):
		practitioner = frappe.db.get_value("Healthcare Practitioner", {"user_id": email}, "name")
		if practitioner:
			frappe.delete_doc("Healthcare Practitioner", practitioner, force=True, ignore_permissions=True)
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=True, ignore_permissions=True)
