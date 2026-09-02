import frappe
from frappe.utils import add_days, getdate, today

from bandhu_app.bandhu_app.utils.session_schedule import (
	ACCEPTED_FIELDS,
	PREVIEW_LIMIT,
	WEEKDAYS,
	as_draft,
	association_maps,
	clock_value,
	find_assignment_clashes,
	horizon_days,
	occurrence_dates,
	practitioners_by_role,
	require_scheduling_access,
)

FREQUENCY_CHOICES = [
	{"value": "Weekly", "label": "Every week"},
	{"value": "Fortnightly", "label": "Every two weeks"},
	{"value": "Monthly", "label": "Once a month"},
]


PRACTITIONER_FIELD_BY_ROLE = {
	"assigned_doctor": "Doctor",
	"assigned_nurse": "Nurse",
	"assigned_driver": "Clinic Assistant cum Driver",
}


@frappe.whitelist()
def get_form_options() -> dict:
	require_scheduling_access()

	sites = frappe.get_all("Site", fields=["name as value", "site_name as label"], order_by="site_name asc")
	clinics = frappe.get_all("Clinic", fields=["name as value", "clinic_name as label", "project", "vehicle"])

	return {
		"sites": sites,
		"clinics": clinics,
		"projects": frappe.get_all("Bandhu Projects", pluck="name"),
		"units": frappe.get_all("Unit", fields=["name as value", "unit_name as label"]),
		"vehicles": frappe.get_all("Vehicle", pluck="name"),
		"holiday_lists": frappe.get_all("Holiday List", pluck="name"),
		"doctors": practitioners_by_role("Doctor"),
		"nurses": practitioners_by_role("Nurse"),
		"drivers": practitioners_by_role("Clinic Assistant cum Driver"),
		"frequencies": FREQUENCY_CHOICES,
		"weekdays": WEEKDAYS,
		"defaults": last_used_defaults(),
		"associations": association_maps(),
	}


def last_used_defaults() -> dict:
	"""Prefill from the most recent schedule — the second schedule of a round is nearly
	always the same times as the first."""
	recent = frappe.get_all(
		"Bandhu Session Schedule",
		fields=["planned_start_time", "planned_end_time", "project", "holiday_list"],
		order_by="creation desc",
		limit=1,
	)
	defaults = recent[0] if recent else {}
	return {
		"planned_start_time": clock_value(defaults.get("planned_start_time"), "09:30:00"),
		"planned_end_time": clock_value(defaults.get("planned_end_time"), "13:30:00"),
		"project": defaults.get("project"),
		"holiday_list": defaults.get("holiday_list"),
		"valid_from": today(),
	}


@frappe.whitelist()
def preview_schedule(values: str) -> dict:
	require_scheduling_access()

	draft = as_draft(values)
	if not draft.valid_from:
		draft.valid_from = today()

	dates = occurrence_dates(draft, today(), add_days(today(), horizon_days()))
	four_weeks_out = getdate(add_days(today(), 28))

	return {
		# Every date the pattern produces — the panel scrolls, so there is nothing to gain by
		# hiding them. Clash lookup stays capped: it is a query per date, the dates are not.
		"dates": [str(day) for day in dates],
		"total": len(dates),
		"clashes": find_assignment_clashes(draft, dates[:PREVIEW_LIMIT]),
		"next_4_weeks": [str(day) for day in dates if day <= four_weeks_out],
	}


@frappe.whitelist(methods=["POST"])
def create_schedule(values: str) -> dict:
	require_scheduling_access()

	draft = as_draft(values)
	draft.enabled = 1
	# The Who step has already shown these clashes and the user pressed Create anyway; the form's
	# own warning would only repeat them in a modal.
	draft.flags.clashes_already_shown = True
	draft.insert()

	# The camps themselves are built by a background job, so counting rows here would report
	# zero. The pattern is what the wizard can promise: a new schedule owns none of its dates
	# yet, so every occurrence in the horizon becomes a camp.
	scheduled = occurrence_dates(draft, today(), add_days(today(), horizon_days()))
	return {"name": draft.name, "scheduled": len(scheduled)}
