# Copyright (c) 2026, CMID and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import today

from bandhu_app.bandhu_app.utils.session_schedule import (
	association_maps,
	clock_value,
	find_assignment_clashes,
	practitioners_by_role,
	require_scheduling_access,
)

ACCEPTED_FIELDS = (
	"date",
	"project",
	"site",
	"clinic",
	"unit",
	"planned_start_time",
	"planned_end_time",
	"assigned_doctor",
	"assigned_nurse",
	"assigned_driver",
	"vehicle",
)


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
		"doctors": practitioners_by_role("Doctor"),
		"nurses": practitioners_by_role("Nurse"),
		"drivers": practitioners_by_role("Clinic Assistant cum Driver"),
		"defaults": last_used_defaults(),
		"associations": association_maps(),
	}


def last_used_defaults() -> dict:
	"""Prefill from the most recently created session — the next ad hoc camp is usually run
	by the same team at the same time as the last one."""
	recent = frappe.get_all(
		"Bandhu Clinic Session",
		fields=["planned_start_time", "planned_end_time", "project"],
		order_by="creation desc",
		limit=1,
	)
	defaults = recent[0] if recent else {}
	return {
		"planned_start_time": clock_value(defaults.get("planned_start_time"), "09:30:00"),
		"planned_end_time": clock_value(defaults.get("planned_end_time"), "13:30:00"),
		"project": defaults.get("project"),
		"date": today(),
	}


def as_session_draft(values) -> "frappe.model.document.Document":
	"""Turn the form's payload into an unsaved session so the same clash check serves the
	live warning and the real save."""
	values = frappe.parse_json(values) or {}

	draft = frappe.new_doc("Bandhu Clinic Session")
	# Only the form's own fields are copied: passing the whole payload to update() let a
	# caller set name, owner or docstatus.
	draft.update({field: values[field] for field in ACCEPTED_FIELDS if values.get(field) not in (None, "")})
	return draft


@frappe.whitelist()
def check_clashes(values: str) -> list:
	require_scheduling_access()

	draft = as_session_draft(values)
	if not draft.date:
		return []
	return find_assignment_clashes(draft, [draft.date])


@frappe.whitelist(methods=["POST"])
def create_session(values: str) -> dict:
	require_scheduling_access()

	draft = as_session_draft(values)
	if not draft.date:
		frappe.throw(_("Pick a date for the session."))

	draft.status = "Planned"
	draft.insert()
	return {"name": draft.name}
