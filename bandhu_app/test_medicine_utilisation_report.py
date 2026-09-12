# Copyright (c) 2026, CMID and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, nowtime, today

from bandhu_app.bandhu_app.baseline_test_fixtures import ensure_baseline_fixtures
from bandhu_app.bandhu_app.report.bandhu_medicine_utilisation_report.bandhu_medicine_utilisation_report import (
	execute,
)

EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = []


class IntegrationTestMedicineUtilisationReport(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()

		baseline = ensure_baseline_fixtures()
		cls.clinic = baseline["clinic"]
		cls.project = baseline["project"]
		cls.appointment_type = baseline["appointment_type"]
		cls.item = baseline["item"]
		cls.unit = baseline["unit"]
		cls.gender = frappe.get_all("Gender", limit=1, pluck="name")[0]

		cls.doctor = (
			frappe.get_doc(
				{
					"doctype": "Healthcare Practitioner",
					"first_name": "Medicine Report Doctor",
					"status": "Active",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		cls.other_unit = (
			frappe.get_doc(
				{"doctype": "Unit", "unit_name": f"Medicine Report Unit {frappe.generate_hash(length=6)}"}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def setUp(self):
		# Rows created by one test stay visible to the next, so every test reads only its own
		# districts; a shared one would make the quantities cumulative.
		self.district = f"Medicine Report District {frappe.generate_hash(length=6)}"
		self.other_district = f"Medicine Report District {frappe.generate_hash(length=6)}"
		self.site = self.make_site(self.district)
		self.other_site = self.make_site(self.other_district)

	def make_site(self, district):
		location = frappe.get_doc(
			{
				"doctype": "Bandhu Location",
				"location_name": f"Medicine Report Location {frappe.generate_hash(length=6)}",
				"lsg": "Medicine Report Panchayat",
				"district": district,
				"state": "Kerala",
			}
		).insert(ignore_permissions=True)

		return (
			frappe.get_doc(
				{
					"doctype": "Site",
					"site_name": f"Medicine Report Worksite {frappe.generate_hash(length=6)}",
					"location": location.name,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def make_session(self, date=None, site=None, unit=None):
		return (
			frappe.get_doc(
				{
					"doctype": "Bandhu Clinic Session",
					"date": date or today(),
					"clinic": self.clinic,
					"site": site or self.site,
					"unit": unit or self.unit,
					"project": self.project,
					"assigned_doctor": self.doctor,
					"status": "Completed",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def make_patient(self):
		return (
			frappe.get_doc(
				{
					"doctype": "Patient",
					"first_name": f"Medicine Report Patient {frappe.generate_hash(length=8)}",
					"sex": self.gender,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def make_encounter(self, session, prescriptions, patient=None):
		return frappe.get_doc(
			{
				"doctype": "Patient Encounter",
				"patient": patient or self.make_patient(),
				"practitioner": self.doctor,
				"encounter_date": today(),
				"encounter_time": nowtime(),
				"appointment_type": self.appointment_type,
				"custom_clinic_session": session,
				"custom_workflow_state": "Completed",
				"custom_bandhu_prescription": prescriptions,
			}
		).insert(ignore_permissions=True)

	def run_report(self, **filters):
		filters.setdefault("from_date", today())
		filters.setdefault("to_date", today())
		filters.setdefault("district", self.district)
		_columns, rows = execute(filters)[:2]
		return rows

	def test_sums_quantity_prescribed_against_quantity_dispensed(self):
		patient = self.make_patient()
		first_session = self.make_session()
		second_session = self.make_session()
		self.make_encounter(
			first_session,
			[
				{"medicines": self.item, "quantity": 10, "dispensed": 1},
				{"medicines": self.item, "quantity": 4},
			],
			patient=patient,
		)
		self.make_encounter(second_session, [{"medicines": self.item, "quantity": 6, "dispensed": 1}])

		[row] = self.run_report()
		self.assertEqual(row["sessions"], 2)
		self.assertEqual(row["patients"], 2)
		self.assertEqual(row["times_prescribed"], 3)
		self.assertEqual(row["quantity_prescribed"], 20)
		self.assertEqual(row["times_dispensed"], 2)
		self.assertEqual(row["quantity_dispensed"], 16)
		self.assertEqual(row["quantity_not_dispensed"], 4)

	def test_counts_a_dispense_with_no_quantity_recorded(self):
		self.make_encounter(self.make_session(), [{"medicines": self.item, "dispensed": 1}])

		[row] = self.run_report()
		self.assertEqual(row["times_dispensed"], 1)
		self.assertEqual(row["quantity_dispensed"], 0)

	def test_splits_the_same_medicine_by_unit(self):
		self.make_encounter(self.make_session(), [{"medicines": self.item, "quantity": 3}])
		self.make_encounter(
			self.make_session(unit=self.other_unit), [{"medicines": self.item, "quantity": 5}]
		)

		quantity_by_unit = {row["unit"]: row["quantity_prescribed"] for row in self.run_report()}
		self.assertEqual(
			quantity_by_unit,
			{
				frappe.db.get_value("Unit", self.unit, "unit_name"): 3,
				frappe.db.get_value("Unit", self.other_unit, "unit_name"): 5,
			},
		)

	def test_district_filter_leaves_out_other_districts(self):
		self.make_encounter(self.make_session(), [{"medicines": self.item, "quantity": 3}])
		self.make_encounter(
			self.make_session(site=self.other_site), [{"medicines": self.item, "quantity": 5}]
		)

		self.assertEqual([row["quantity_prescribed"] for row in self.run_report()], [3])
		self.assertEqual(
			[row["quantity_prescribed"] for row in self.run_report(district=self.other_district)], [5]
		)

	def test_leaves_out_sessions_outside_the_period(self):
		self.make_encounter(self.make_session(), [{"medicines": self.item, "quantity": 3}])
		self.make_encounter(
			self.make_session(date=add_days(today(), -40)), [{"medicines": self.item, "quantity": 7}]
		)

		self.assertEqual([row["quantity_prescribed"] for row in self.run_report()], [3])

	def test_medicine_filter_leaves_out_other_medicines(self):
		baseline_item = frappe.db.get_value("Item", self.item, ["item_group", "stock_uom"], as_dict=True)
		other_item = (
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": f"Medicine Report Tablet {frappe.generate_hash(length=6)}",
					"item_group": baseline_item.item_group,
					"stock_uom": baseline_item.stock_uom,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		self.make_encounter(
			self.make_session(),
			[
				{"medicines": self.item, "quantity": 3},
				{"medicines": other_item, "quantity": 5},
			],
		)

		self.assertEqual(len(self.run_report()), 2)
		[row] = self.run_report(medicine=other_item)
		self.assertEqual(row["medicine"], other_item)
		self.assertEqual(row["quantity_prescribed"], 5)

	def test_rejects_a_period_that_runs_backwards(self):
		self.assertRaises(
			frappe.ValidationError,
			execute,
			{"from_date": today(), "to_date": add_days(today(), -1)},
		)

	def test_rejects_a_period_longer_than_a_year(self):
		self.assertRaises(
			frappe.ValidationError,
			execute,
			{"from_date": add_days(today(), -400), "to_date": today()},
		)
