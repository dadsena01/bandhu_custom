# Copyright (c) 2026, CMID and Contributors
# See license.txt

"""The HTTP boundary of the clinic endpoints.

Every test here goes through `frappe.handler.execute_cmd` with a form_dict, which is the
path a browser's `frappe.call` actually takes: whitelist check, HTTP-method check, argument
coercion against the type annotations, then the in-function role gate. Calling the Python
function directly — what the rest of the suite does — hands the code arguments that are
already the right type and skips all four, and that is exactly how the blank-number-input
crash of 2026-08-10 reached a live camp.
"""

from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.exceptions import FrappeTypeError
from frappe.handler import execute_cmd
from frappe.tests import IntegrationTestCase
from frappe.utils import set_request, today

from bandhu_app.bandhu_app.baseline_test_fixtures import ensure_baseline_fixtures
from bandhu_app.bandhu_app.page.cad_form import cad_form

CAD = "bandhu_app.bandhu_app.page.cad_form.cad_form"
DOCTOR = "bandhu_app.bandhu_app.page.doctor_form.doctor_form"
NURSE = "bandhu_app.bandhu_app.page.nurse_form.nurse_form"


@contextmanager
def browser_request(method: str):
	"""A request context that leaves frappe.local as it found it.

	A leaked request or form_dict is picked up by whichever test runs next, so the restore
	matters more than the setup.
	"""
	had_request = hasattr(frappe.local, "request")
	original_request = getattr(frappe.local, "request", None)
	original_form_dict = frappe.local.form_dict

	set_request(method=method, path="/api/method/call")
	try:
		yield
	finally:
		frappe.local.form_dict = original_form_dict
		if had_request:
			frappe.local.request = original_request
		elif hasattr(frappe.local, "request"):
			delattr(frappe.local, "request")


def call_over_http(cmd: str, method: str = "POST", **args):
	"""Invoke a whitelisted method the way the page's `frappe.call` does.

	`cmd` rides in the form_dict alongside the arguments, exactly as it does on the wire —
	dropping it is `get_newargs`'s job, not the caller's.
	"""
	with browser_request(method):
		frappe.local.form_dict = frappe._dict(cmd=cmd, **args)
		return execute_cmd(cmd)


class TestApiBoundary(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		baseline = ensure_baseline_fixtures()
		cls.clinic = baseline["clinic"]
		cls.site = baseline["site"]
		cls.project = baseline["project"]
		cls.gender = frappe.get_all("Gender", limit=1, pluck="name")[0]

	def setUp(self):
		# Rollback is per class, so every test builds its own camp and asserts against that
		# camp only. Sharing one would make each test read the previous test's rows.
		self.suffix = frappe.generate_hash(length=8)
		self.driver = self.make_practitioner("Clinic Assistant cum Driver")
		self.doctor = self.make_practitioner("Doctor")
		self.nurse = self.make_practitioner("Nurse")
		self.cad_user = self.make_user(self.driver, ["Clinic Assistant cum Driver"])
		self.doctor_user = self.make_user(self.doctor, ["Doctor"])
		self.nurse_user = self.make_user(self.nurse, ["Nurse"])
		self.session = self.make_session()

	def tearDown(self):
		frappe.set_user("Administrator")

	def make_practitioner(self, custom_role: str) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "Healthcare Practitioner",
					"first_name": f"Boundary {custom_role} {self.suffix}",
					"status": "Active",
					"custom_role": custom_role,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def make_user(self, practitioner: str | None, roles: list) -> str:
		email = f"boundary.{frappe.generate_hash(length=10)}@bandhuapp.test"
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
		if practitioner:
			frappe.db.set_value("Healthcare Practitioner", practitioner, "user_id", email)
		return email

	def make_session(self, status: str = "In Progress", date: str | None = None) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "Bandhu Clinic Session",
					"date": date or today(),
					"clinic": self.clinic,
					"site": self.site,
					"project": self.project,
					"assigned_driver": self.driver,
					"assigned_doctor": self.doctor,
					"assigned_nurse": self.nurse,
					"status": status,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def make_patient(self) -> str:
		return (
			frappe.get_doc(
				{"doctype": "Patient", "first_name": f"Boundary Patient {self.suffix}", "sex": self.gender}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def make_encounter(self, session: str, workflow_state: str = "Waiting for Doctor") -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "Patient Encounter",
					"patient": self.make_patient(),
					"practitioner": self.doctor,
					"encounter_date": today(),
					"custom_clinic_session": session,
					"custom_workflow_state": workflow_state,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def patients_registered_here(self) -> int:
		return frappe.db.count("Patient", {"first_name": ["like", f"%{self.suffix}%"]})

	def register_args(self, **overrides) -> dict:
		args = {
			"full_name": f"Wire Patient {self.suffix}",
			"dob": "1990-05-15",
			"sex": self.gender,
			"session": self.session,
		}
		args.update(overrides)
		return args

	# --- argument coercion -------------------------------------------------------------

	def test_register_patient_accepts_the_string_numerics_a_number_input_sends(self):
		"""`<input type="number">.value` is a string, so `float | None` never sees a float."""
		frappe.set_user(self.cad_user)
		patient = call_over_http(
			f"{CAD}.register_patient", **self.register_args(height_cm="170.5", weight_kg="68")
		)

		doc = frappe.get_doc("Patient", patient)
		self.assertAlmostEqual(doc.custom_height_m, 1.705, places=3)
		self.assertEqual(doc.custom_weight_kg, 68)

	def test_register_patient_refuses_the_empty_string_a_blank_number_input_sends(self):
		"""The 2026-08-10 crash, pinned as a contract.

		A blank optional number must be omitted from the args, not sent as "". If this ever
		stops raising, the annotation was widened and the page can start storing "" as a
		measurement.
		"""
		frappe.set_user(self.cad_user)
		with self.assertRaises(FrappeTypeError):
			call_over_http(f"{CAD}.register_patient", **self.register_args(height_cm="", weight_kg=""))

		self.assertEqual(self.patients_registered_here(), 0)

	def test_register_patient_accepts_optional_keys_being_absent_altogether(self):
		frappe.set_user(self.cad_user)
		patient = call_over_http(f"{CAD}.register_patient", **self.register_args())

		doc = frappe.get_doc("Patient", patient)
		self.assertFalse(doc.custom_height_m)
		self.assertFalse(doc.mobile)

	def test_create_encounter_refuses_a_null_where_a_string_is_required(self):
		frappe.set_user(self.cad_user)
		with self.assertRaises(FrappeTypeError):
			call_over_http(f"{CAD}.create_encounter", patient=None, session=self.session)

	def test_create_encounter_refuses_a_request_missing_a_required_argument(self):
		"""A page that forgets a key must fail, not fall through on a default."""
		patient = self.make_patient()
		frappe.set_user(self.cad_user)
		with self.assertRaises(TypeError):
			call_over_http(f"{CAD}.create_encounter", patient=patient)

		self.assertEqual(frappe.db.count("Patient Encounter", {"patient": patient}), 0)

	def test_order_test_reads_the_json_string_the_browser_puts_on_the_wire(self):
		"""`frappe.call` serialises an array to JSON, so `tests` arrives as a string."""
		encounter = self.make_encounter(self.session)
		frappe.set_user(self.doctor_user)
		call_over_http(f"{DOCTOR}.order_test", encounter=encounter, tests='["Malaria", "Hb"]')

		doc = frappe.get_doc("Patient Encounter", encounter)
		self.assertEqual(sorted(row.test_name for row in doc.custom_test_instructions), ["Hb", "Malaria"])
		self.assertEqual(doc.custom_workflow_state, "Awaiting Test")

	def test_order_test_rejects_a_test_name_that_only_the_client_believes_in(self):
		"""The endpoint names the bad test itself.

		The child table's Select options would refuse "Ebola" too, but only after the row is
		built and with a message about a field the doctor never saw. The message is asserted
		so this stays a test of the endpoint's own allow-list, not of the schema behind it.
		"""
		encounter = self.make_encounter(self.session)
		frappe.set_user(self.doctor_user)
		with self.assertRaisesRegex(frappe.ValidationError, "Unknown test"):
			call_over_http(f"{DOCTOR}.order_test", encounter=encounter, tests='["Ebola"]')

		doc = frappe.get_doc("Patient Encounter", encounter)
		self.assertEqual(doc.custom_workflow_state, "Waiting for Doctor")
		self.assertEqual(doc.custom_test_instructions, [])

	def test_the_cache_busting_keys_the_client_adds_are_dropped_not_fatal(self):
		"""`frappe.call` ships `cmd`, `_` and friends; none of them are function arguments.

		The registration origin is asserted alongside, so a signature whose parameter names
		drift away from the wire keys fails here instead of silently registering the patient
		with no camp behind them.
		"""
		frappe.set_user(self.cad_user)
		patient = call_over_http(
			f"{CAD}.register_patient", _="1755000000000", freeze="true", **self.register_args()
		)

		expected_lsg = frappe.db.get_value("Site", self.site, "location")
		self.assertEqual(frappe.db.get_value("Patient", patient, "custom_registered_lsg"), expected_lsg)

	# --- transport gates ---------------------------------------------------------------

	def test_a_write_endpoint_is_unreachable_over_get(self):
		"""`methods=["POST"]` is only enforced when there is a real request to inspect."""
		frappe.set_user(self.cad_user)
		with self.assertRaises(frappe.PermissionError):
			call_over_http(f"{CAD}.register_patient", method="GET", **self.register_args())

		self.assertEqual(self.patients_registered_here(), 0)

	def test_guest_is_turned_away_before_the_endpoint_body_runs(self):
		"""The in-function role gate would also refuse a Guest, so the outcome alone proves
		nothing. What is asserted here is the layer: `is_whitelisted` rejects the call before
		any app code — and therefore any query — is reached."""
		frappe.set_user("Guest")
		with patch.object(cad_form, "require_cad_access") as gate:
			with self.assertRaises(frappe.PermissionError):
				call_over_http(f"{CAD}.get_today_queue", method="GET", session=self.session)

		gate.assert_not_called()

	# --- role and session gates, reached the way the browser reaches them ---------------

	def test_the_cad_session_gate_fires_over_http_for_another_drivers_camp(self):
		other_driver = self.make_practitioner("Clinic Assistant cum Driver")
		other_camp = (
			frappe.get_doc(
				{
					"doctype": "Bandhu Clinic Session",
					"date": today(),
					"clinic": self.clinic,
					"site": self.site,
					"project": self.project,
					"assigned_driver": other_driver,
					"assigned_doctor": self.doctor,
					"status": "In Progress",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

		frappe.set_user(self.cad_user)
		with self.assertRaises(frappe.PermissionError):
			call_over_http(f"{CAD}.register_patient", **self.register_args(session=other_camp))

		self.assertEqual(self.patients_registered_here(), 0)

	def test_registration_over_http_is_refused_for_a_cancelled_camp(self):
		cancelled = self.make_session(status="Cancelled")
		frappe.set_user(self.cad_user)
		with self.assertRaises(frappe.ValidationError):
			call_over_http(f"{CAD}.register_patient", **self.register_args(session=cancelled))

		self.assertEqual(self.patients_registered_here(), 0)

	def test_a_closed_camp_cannot_be_reopened_over_http(self):
		closed = self.make_session(status="Completed")
		frappe.set_user(self.nurse_user)
		with self.assertRaises(frappe.ValidationError):
			call_over_http(f"{NURSE}.start_session", session_name=closed)

		self.assertEqual(frappe.db.get_value("Bandhu Clinic Session", closed, "status"), "Completed")

	def test_a_doctor_cannot_advance_another_doctors_patient_over_http(self):
		encounter = self.make_encounter(self.session)
		stranger = self.make_practitioner("Doctor")
		stranger_user = self.make_user(stranger, ["Doctor"])

		frappe.set_user(stranger_user)
		with self.assertRaises(frappe.PermissionError):
			call_over_http(f"{DOCTOR}.complete_encounter", encounter=encounter)

		self.assertEqual(
			frappe.db.get_value("Patient Encounter", encounter, "custom_workflow_state"),
			"Waiting for Doctor",
		)
