import frappe
from frappe import _
from frappe.query_builder import Case
from frappe.query_builder.functions import Coalesce, Count, Sum
from frappe.utils import cint, date_diff, getdate

from bandhu_app.bandhu_app.utils.session import fetch_map

MAX_REPORT_DAYS = 366

# Beyond this many bars the medicine names on the axis overlap and nothing is readable.
CHART_MEDICINE_LIMIT = 10


def execute(filters=None):
	filters = frappe._dict(filters or {})
	validate_filters(filters)

	usage = fetch_usage(filters)
	if not usage:
		return get_columns(), []

	rows = build_rows(usage)
	return get_columns(), rows, None, build_chart(rows), build_summary(rows)


def validate_filters(filters):
	if not (filters.from_date and filters.to_date):
		frappe.throw(_("From Date and To Date are required."))

	if getdate(filters.from_date) > getdate(filters.to_date):
		frappe.throw(_("From Date cannot be after To Date."))

	if date_diff(filters.to_date, filters.from_date) > MAX_REPORT_DAYS:
		frappe.throw(_("Choose a period of {0} days or less.").format(MAX_REPORT_DAYS))


def fetch_usage(filters) -> list:
	prescription = frappe.qb.DocType("Prescription")
	encounter = frappe.qb.DocType("Patient Encounter")
	session = frappe.qb.DocType("Bandhu Clinic Session")
	site = frappe.qb.DocType("Site")
	location = frappe.qb.DocType("Bandhu Location")

	quantity = Coalesce(prescription.quantity, 0)
	dispensed = prescription.dispensed == 1

	query = (
		frappe.qb.from_(prescription)
		.inner_join(encounter)
		.on(encounter.name == prescription.parent)
		.inner_join(session)
		.on(session.name == encounter.custom_clinic_session)
		# A session's site may have no location yet; its medicines still count, under no district.
		.left_join(site)
		.on(site.name == session.site)
		.left_join(location)
		.on(location.name == site.location)
		.select(
			prescription.medicines.as_("medicine"),
			session.unit,
			location.district,
			Count(session.name).distinct().as_("sessions"),
			Count(encounter.patient).distinct().as_("patients"),
			Count(prescription.name).as_("times_prescribed"),
			Sum(quantity).as_("quantity_prescribed"),
			Sum(Case().when(dispensed, 1).else_(0)).as_("times_dispensed"),
			Sum(Case().when(dispensed, quantity).else_(0)).as_("quantity_dispensed"),
		)
		.where(
			(prescription.parenttype == "Patient Encounter")
			& (prescription.parentfield == "custom_bandhu_prescription")
			& (encounter.docstatus < 2)
			& (session.date[filters.from_date : filters.to_date])
			& (Coalesce(prescription.medicines, "") != "")
		)
		.groupby(prescription.medicines, session.unit, location.district)
	)

	if filters.get("medicine"):
		query = query.where(prescription.medicines == filters.medicine)
	if filters.get("unit"):
		query = query.where(session.unit == filters.unit)
	if filters.get("project"):
		query = query.where(session.project == filters.project)
	if filters.get("district"):
		query = query.where(location.district == filters.district)

	return query.run(as_dict=True)


def build_rows(usage: list) -> list:
	items = fetch_map("Item", {entry.medicine for entry in usage}, ["item_name", "stock_uom"])
	units = fetch_map("Unit", {entry.unit for entry in usage if entry.unit}, ["unit_name"])

	rows = []
	for entry in usage:
		item = items.get(entry.medicine) or frappe._dict()
		quantity_prescribed = cint(entry.quantity_prescribed)
		quantity_dispensed = cint(entry.quantity_dispensed)

		rows.append(
			{
				"medicine": entry.medicine,
				"medicine_name": item.item_name or entry.medicine,
				"uom": item.stock_uom,
				"unit": (units.get(entry.unit) or frappe._dict()).unit_name or entry.unit,
				"district": entry.district,
				"sessions": cint(entry.sessions),
				"patients": cint(entry.patients),
				"times_prescribed": cint(entry.times_prescribed),
				"quantity_prescribed": quantity_prescribed,
				"times_dispensed": cint(entry.times_dispensed),
				"quantity_dispensed": quantity_dispensed,
				"quantity_not_dispensed": quantity_prescribed - quantity_dispensed,
			}
		)

	rows.sort(key=lambda row: (row["medicine_name"], row["unit"] or "", row["district"] or ""))
	return rows


def build_chart(rows: list) -> dict:
	by_medicine = {}
	for row in rows:
		totals = by_medicine.setdefault(
			row["medicine"], {"label": row["medicine_name"], "prescribed": 0, "dispensed": 0}
		)
		totals["prescribed"] += row["quantity_prescribed"]
		totals["dispensed"] += row["quantity_dispensed"]

	top_medicines = sorted(by_medicine.values(), key=lambda totals: totals["dispensed"], reverse=True)[
		:CHART_MEDICINE_LIMIT
	]

	return {
		"data": {
			"labels": [totals["label"] for totals in top_medicines],
			"datasets": [
				{
					"name": _("Quantity Prescribed"),
					"values": [totals["prescribed"] for totals in top_medicines],
				},
				{
					"name": _("Quantity Dispensed"),
					"values": [totals["dispensed"] for totals in top_medicines],
				},
			],
		},
		"type": "bar",
		"barOptions": {"stacked": False},
	}


def build_summary(rows: list) -> list:
	medicines_dispensed = {row["medicine"] for row in rows if row["times_dispensed"]}

	return [
		{"label": _("Medicines Dispensed"), "value": len(medicines_dispensed), "datatype": "Int"},
		{
			"label": _("Quantity Prescribed"),
			"value": sum(row["quantity_prescribed"] for row in rows),
			"datatype": "Int",
		},
		{
			"label": _("Quantity Dispensed"),
			"value": sum(row["quantity_dispensed"] for row in rows),
			"datatype": "Int",
		},
		{
			"label": _("Quantity Not Dispensed"),
			"value": sum(row["quantity_not_dispensed"] for row in rows),
			"datatype": "Int",
			"indicator": "Orange",
		},
	]


def get_columns() -> list:
	return [
		{
			"fieldname": "medicine",
			"label": _("Medicine"),
			"fieldtype": "Link",
			"options": "Item",
			"width": 120,
		},
		{"fieldname": "medicine_name", "label": _("Medicine Name"), "fieldtype": "Data", "width": 180},
		{"fieldname": "uom", "label": _("UOM"), "fieldtype": "Data", "width": 70},
		{"fieldname": "unit", "label": _("Unit"), "fieldtype": "Data", "width": 120},
		{"fieldname": "district", "label": _("District"), "fieldtype": "Data", "width": 120},
		{"fieldname": "sessions", "label": _("Sessions"), "fieldtype": "Int", "width": 90},
		{"fieldname": "patients", "label": _("Patients"), "fieldtype": "Int", "width": 90},
		{
			"fieldname": "times_prescribed",
			"label": _("Times Prescribed"),
			"fieldtype": "Int",
			"width": 130,
		},
		{
			"fieldname": "quantity_prescribed",
			"label": _("Quantity Prescribed"),
			"fieldtype": "Int",
			"width": 150,
		},
		{
			"fieldname": "times_dispensed",
			"label": _("Times Dispensed"),
			"fieldtype": "Int",
			"width": 130,
		},
		{
			"fieldname": "quantity_dispensed",
			"label": _("Quantity Dispensed"),
			"fieldtype": "Int",
			"width": 150,
		},
		{
			"fieldname": "quantity_not_dispensed",
			"label": _("Quantity Not Dispensed"),
			"fieldtype": "Int",
			"width": 170,
		},
	]
