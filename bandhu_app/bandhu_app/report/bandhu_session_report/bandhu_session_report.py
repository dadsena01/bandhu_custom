import frappe
from frappe import _
from frappe.utils import cint, date_diff, flt, formatdate, get_datetime, getdate

from bandhu_app.bandhu_app.utils.clinic_stats import (
	count_encounters,
	count_medicines,
	count_new_patients,
	count_tests,
)
from bandhu_app.bandhu_app.utils.session import fetch_map


def execute(filters=None):
	filters = frappe._dict(filters or {})
	validate_filters(filters)

	sessions = fetch_sessions(filters)
	if not sessions:
		return get_columns(), []

	rows = build_rows(sessions)
	return get_columns(), rows, None, build_chart(rows), build_summary(rows)


MAX_REPORT_DAYS = 366


def validate_filters(filters):
	if not (filters.from_date and filters.to_date):
		frappe.throw(_("From Date and To Date are required."))

	if getdate(filters.from_date) > getdate(filters.to_date):
		frappe.throw(_("From Date cannot be after To Date."))

	if date_diff(filters.to_date, filters.from_date) > MAX_REPORT_DAYS:
		frappe.throw(_("Choose a period of {0} days or less.").format(MAX_REPORT_DAYS))


def fetch_sessions(filters) -> list:
	session_filters = {"date": ["between", [filters.from_date, filters.to_date]]}

	for fieldname in ("project", "site", "unit", "status", "clinic"):
		if filters.get(fieldname):
			session_filters[fieldname] = filters.get(fieldname)

	if filters.get("location"):
		sites = frappe.get_all("Site", filters={"location": filters.location}, pluck="name")
		if not sites:
			return []
		# A site filter typed by the user must survive the location narrowing.
		if session_filters.get("site") and session_filters["site"] not in sites:
			return []
		session_filters["site"] = session_filters.get("site") or ["in", sites]

	return frappe.get_all(
		"Bandhu Clinic Session",
		filters=session_filters,
		fields=[
			"name",
			"date",
			"status",
			"project",
			"site",
			"unit",
			"clinic",
			"assigned_doctor",
			"assigned_nurse",
			"planned_start_time",
			"start_time",
			"end_time",
		],
		order_by="date asc, planned_start_time asc",
	)


def build_rows(sessions: list) -> list:
	session_names = [session.name for session in sessions]

	sites = fetch_map(
		"Site", {session.site for session in sessions if session.site}, ["site_name", "location"]
	)
	locations = fetch_map(
		"Bandhu Location",
		{site.location for site in sites.values() if site.location},
		["location_name", "lsg", "district"],
	)
	units = fetch_map("Unit", {session.unit for session in sessions if session.unit}, ["unit_name"])
	practitioners = fetch_map(
		"Healthcare Practitioner",
		{session.assigned_doctor for session in sessions if session.assigned_doctor}
		| {session.assigned_nurse for session in sessions if session.assigned_nurse},
		["practitioner_name"],
	)

	encounter_counts = count_encounters(session_names)
	new_patient_counts = count_new_patients(session_names)
	test_counts = count_tests(session_names)
	medicine_counts = count_medicines(session_names)

	rows = []
	for session in sessions:
		site = sites.get(session.site) or frappe._dict()
		location = locations.get(site.location) or frappe._dict()
		counts = encounter_counts.get(session.name) or frappe._dict()
		tests = test_counts.get(session.name) or frappe._dict()
		medicines = medicine_counts.get(session.name) or frappe._dict()
		patients = cint(counts.patients)
		new_patients = new_patient_counts.get(session.name, 0)

		rows.append(
			{
				"date": session.date,
				"session": session.name,
				"status": session.status,
				"project": session.project,
				"site": site.site_name or session.site,
				"lsg": location.lsg,
				"district": location.district,
				"unit": (units.get(session.unit) or frappe._dict()).unit_name or session.unit,
				"doctor": practitioner_name(practitioners, session.assigned_doctor),
				"nurse": practitioner_name(practitioners, session.assigned_nurse),
				"opened_at": clock(session.start_time),
				"closed_at": clock(session.end_time),
				"hours_open": hours_between(session.start_time, session.end_time),
				"patients": patients,
				"new_patients": new_patients,
				"repeat_patients": patients - new_patients,
				"completed": cint(counts.completed),
				"tests_ordered": cint(tests.ordered),
				"tests_done": cint(tests.done),
				"medicines_prescribed": cint(medicines.prescribed),
				"medicines_dispensed": cint(medicines.dispensed),
			}
		)
	return rows


def practitioner_name(practitioners: dict, name: str | None) -> str | None:
	if not name:
		return None
	return (practitioners.get(name) or frappe._dict()).practitioner_name or name


def clock(value) -> str | None:
	if not value:
		return None
	return get_datetime(value).strftime("%H:%M")


def hours_between(start, end) -> float:
	if not (start and end):
		return 0.0
	seconds = (get_datetime(end) - get_datetime(start)).total_seconds()
	return flt(seconds / 3600, 2) if seconds > 0 else 0.0


def build_chart(rows: list) -> dict:
	by_date = {}
	for row in rows:
		day = by_date.setdefault(row["date"], {"patients": 0, "new_patients": 0})
		day["patients"] += row["patients"]
		day["new_patients"] += row["new_patients"]

	days = sorted(by_date)

	return {
		"data": {
			"labels": [formatdate(day, "d MMM") for day in days],
			"datasets": [
				{"name": _("Patients Seen"), "values": [by_date[day]["patients"] for day in days]},
				{"name": _("New Patients"), "values": [by_date[day]["new_patients"] for day in days]},
			],
		},
		"type": "bar",
		"barOptions": {"stacked": False},
	}


def build_summary(rows: list) -> list:
	patients = sum(row["patients"] for row in rows)
	sessions_held = len([row for row in rows if row["status"] in ("In Progress", "Completed")])

	return [
		{"label": _("Sessions Held"), "value": sessions_held, "datatype": "Int"},
		{"label": _("Patients Seen"), "value": patients, "datatype": "Int"},
		{
			"label": _("New Patients"),
			"value": sum(row["new_patients"] for row in rows),
			"datatype": "Int",
		},
		{
			"label": _("Avg Patients per Session"),
			"value": flt(patients / sessions_held, 1) if sessions_held else 0,
			"datatype": "Float",
		},
		{
			"label": _("Medicines Dispensed"),
			"value": sum(row["medicines_dispensed"] for row in rows),
			"datatype": "Int",
		},
	]


def get_columns() -> list:
	return [
		{"fieldname": "date", "label": _("Date"), "fieldtype": "Date", "width": 100},
		{
			"fieldname": "session",
			"label": _("Session"),
			"fieldtype": "Link",
			"options": "Bandhu Clinic Session",
			"width": 150,
		},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 100},
		{"fieldname": "site", "label": _("Site"), "fieldtype": "Data", "width": 180},
		{"fieldname": "lsg", "label": _("LSG"), "fieldtype": "Data", "width": 130},
		{"fieldname": "district", "label": _("District"), "fieldtype": "Data", "width": 110},
		{
			"fieldname": "project",
			"label": _("Project"),
			"fieldtype": "Link",
			"options": "Bandhu Projects",
			"width": 130,
		},
		{"fieldname": "unit", "label": _("Unit"), "fieldtype": "Data", "width": 110},
		{"fieldname": "doctor", "label": _("Doctor"), "fieldtype": "Data", "width": 140},
		{"fieldname": "nurse", "label": _("Nurse"), "fieldtype": "Data", "width": 140},
		{"fieldname": "opened_at", "label": _("Opened"), "fieldtype": "Data", "width": 80},
		{"fieldname": "closed_at", "label": _("Closed"), "fieldtype": "Data", "width": 80},
		{"fieldname": "hours_open", "label": _("Hours"), "fieldtype": "Float", "width": 70},
		{"fieldname": "patients", "label": _("Patients"), "fieldtype": "Int", "width": 90},
		{"fieldname": "new_patients", "label": _("New"), "fieldtype": "Int", "width": 70},
		{"fieldname": "repeat_patients", "label": _("Repeat"), "fieldtype": "Int", "width": 80},
		{"fieldname": "completed", "label": _("Completed"), "fieldtype": "Int", "width": 100},
		{"fieldname": "tests_ordered", "label": _("Tests Ordered"), "fieldtype": "Int", "width": 110},
		{"fieldname": "tests_done", "label": _("Tests Done"), "fieldtype": "Int", "width": 100},
		{
			"fieldname": "medicines_prescribed",
			"label": _("Medicines Prescribed"),
			"fieldtype": "Int",
			"width": 150,
		},
		{
			"fieldname": "medicines_dispensed",
			"label": _("Medicines Dispensed"),
			"fieldtype": "Int",
			"width": 150,
		},
	]
