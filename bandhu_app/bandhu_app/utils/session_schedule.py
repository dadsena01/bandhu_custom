# Copyright (c) 2026, CMID and contributors
# For license information, please see license.txt

from collections import defaultdict
from datetime import date, timedelta

import frappe
from frappe import _
from frappe.utils import add_days, create_batch, getdate, today

from bandhu_app.bandhu_app.utils.session import label_sites

WEEKDAY_INDEX = {
	"Monday": 0,
	"Tuesday": 1,
	"Wednesday": 2,
	"Thursday": 3,
	"Friday": 4,
	"Saturday": 5,
	"Sunday": 6,
}

WEEK_OF_MONTH_OFFSET = {"First": 0, "Second": 1, "Third": 2, "Fourth": 3}

DEFAULT_HORIZON_DAYS = 56
SESSION_BATCH_SIZE = 500
PREVIEW_LIMIT = 10

SESSION_FIELDS_FROM_SCHEDULE = (
	"site",
	"clinic",
	"project",
	"unit",
	"planned_start_time",
	"planned_end_time",
	"assigned_doctor",
	"assigned_nurse",
	"assigned_driver",
	"vehicle",
)


def require_scheduling_access() -> None:
	"""Shared by the New Schedule wizard and the New Session quick-create — both write
	Bandhu Clinic Session rows and neither has a role of its own to gate on."""
	if "System Manager" not in frappe.get_roles():
		frappe.throw(
			_("You do not have permission to create clinic schedules."),
			frappe.PermissionError,
		)


def practitioners_by_role(custom_role: str) -> list:
	return frappe.get_all(
		"Healthcare Practitioner",
		filters={"custom_role": custom_role, "status": "Active"},
		fields=["name as value", "practitioner_name as label"],
		order_by="practitioner_name asc",
	)


def association_maps() -> dict:
	"""Project/Site/Clinic/Unit pairings actually run before, so a form's dropdowns can
	narrow to what makes sense instead of every master in the system. Only Clinic.project is
	a real schema link — Site and Unit have no FK to Project or Clinic — so this is derived
	from history, not the doctypes, and an empty map for a key means "no history yet",
	which callers must treat as "don't filter" rather than "nothing is valid"."""
	combos = frappe.get_all("Bandhu Clinic Session", fields=["project", "site", "clinic", "unit"])

	project_sites = defaultdict(set)
	site_clinics = defaultdict(set)
	clinic_units = defaultdict(set)
	for combo in combos:
		if combo.project and combo.site:
			project_sites[combo.project].add(combo.site)
		if combo.site and combo.clinic:
			site_clinics[combo.site].add(combo.clinic)
		if combo.clinic and combo.unit:
			clinic_units[combo.clinic].add(combo.unit)

	return {
		"project_sites": {key: sorted(value) for key, value in project_sites.items()},
		"site_clinics": {key: sorted(value) for key, value in site_clinics.items()},
		"clinic_units": {key: sorted(value) for key, value in clinic_units.items()},
	}


def clock_value(value, fallback: str) -> str:
	"""`<input type="time">` silently renders empty unless the value is zero-padded, and
	Frappe hands a Time back as `9:30:00`."""
	if value in (None, ""):
		return fallback
	hours, minutes, seconds = [*str(value).split(":"), "00", "00"][:3]
	return f"{int(hours):02d}:{minutes:0>2}:{seconds[:2]:0>2}"


def week_start(day: date) -> date:
	return day - timedelta(days=day.weekday())


def first_day_of_next_month(day: date) -> date:
	if day.month == 12:
		return date(day.year + 1, 1, 1)
	return date(day.year, day.month + 1, 1)


def last_day_of_month(day: date) -> date:
	return first_day_of_next_month(day) - timedelta(days=1)


def selected_weekday_indexes(schedule) -> set:
	return {WEEKDAY_INDEX[row.weekday] for row in schedule.weekdays if row.weekday}


def holiday_dates(holiday_list: str | None) -> set:
	if not holiday_list:
		return set()
	return set(frappe.get_all("Holiday", filters={"parent": holiday_list}, pluck="holiday_date"))


def nth_weekday_of_month(year: int, month: int, weekday: int, week_of_month: str) -> date | None:
	first = date(year, month, 1)
	first_match = first + timedelta(days=(weekday - first.weekday()) % 7)

	if week_of_month == "Last":
		last = last_day_of_month(first)
		occurrence = first_match
		while occurrence + timedelta(days=7) <= last:
			occurrence += timedelta(days=7)
		return occurrence

	occurrence = first_match + timedelta(days=7 * WEEK_OF_MONTH_OFFSET.get(week_of_month, 0))
	# A fifth Tuesday does not exist in every month; the month is skipped, not shifted.
	return occurrence if occurrence.month == month else None


def weekly_dates(schedule, start: date, end: date) -> list:
	weekdays = selected_weekday_indexes(schedule)
	if not weekdays:
		return []

	anchor_week = week_start(getdate(schedule.valid_from))
	dates = []
	current = start
	while current <= end:
		if current.weekday() in weekdays:
			is_on_week = (week_start(current) - anchor_week).days // 7 % 2 == 0
			if schedule.frequency != "Fortnightly" or is_on_week:
				dates.append(current)
		current += timedelta(days=1)
	return dates


def monthly_weekday_dates(schedule, start: date, end: date) -> list:
	weekdays = selected_weekday_indexes(schedule)
	if not weekdays:
		return []

	dates = []
	month = date(start.year, start.month, 1)
	while month <= end:
		for weekday in weekdays:
			occurrence = nth_weekday_of_month(
				month.year, month.month, weekday, schedule.week_of_month or "First"
			)
			if occurrence and start <= occurrence <= end:
				dates.append(occurrence)
		month = first_day_of_next_month(month)
	return sorted(dates)


def monthly_day_of_month_dates(schedule, start: date, end: date) -> list:
	day_of_month = int(schedule.day_of_month or 0)
	if not 1 <= day_of_month <= 31:
		return []

	dates = []
	month = date(start.year, start.month, 1)
	while month <= end:
		if day_of_month <= last_day_of_month(month).day:
			occurrence = date(month.year, month.month, day_of_month)
			if start <= occurrence <= end:
				dates.append(occurrence)
		month = first_day_of_next_month(month)
	return dates


def occurrence_dates(schedule, from_date, to_date) -> list:
	start = max(getdate(from_date), getdate(schedule.valid_from))
	end = getdate(to_date)
	if schedule.valid_upto:
		end = min(end, getdate(schedule.valid_upto))
	if start > end:
		return []

	if schedule.frequency == "Monthly" and schedule.monthly_mode == "Day of Month":
		dates = monthly_day_of_month_dates(schedule, start, end)
	elif schedule.frequency == "Monthly":
		dates = monthly_weekday_dates(schedule, start, end)
	else:
		dates = weekly_dates(schedule, start, end)

	holidays = holiday_dates(schedule.holiday_list)
	return [day for day in dates if day not in holidays]


def horizon_days() -> int:
	configured = frappe.db.get_single_value("Bandhu Settings", "session_horizon_days")
	return int(configured or DEFAULT_HORIZON_DAYS)


def is_auto_generation_enabled() -> bool:
	# Phrased as an opt-out because a Single stores nothing until it is first saved,
	# and an unread Check comes back as 0 — indistinguishable from "switched off".
	return not frappe.db.get_single_value("Bandhu Settings", "disable_auto_session_generation")


def build_session(schedule, day: date):
	session = frappe.new_doc("Bandhu Clinic Session")
	session.session_schedule = schedule.name
	session.date = day
	session.status = "Planned"
	for fieldname in SESSION_FIELDS_FROM_SCHEDULE:
		session.set(fieldname, schedule.get(fieldname))
	return session


def generate_sessions_for_schedule(schedule, upto=None) -> list:
	"""Create the schedule's missing sessions from the last generated date up to the horizon."""
	if isinstance(schedule, str):
		schedule = frappe.get_doc("Bandhu Session Schedule", schedule)

	start = getdate(today())
	end = getdate(upto) if upto else start + timedelta(days=horizon_days())
	# Everything up to the watermark has already been walked, so a resave only pays for the
	# days the horizon has rolled onto since. A pattern change clears it and starts over.
	if schedule.last_generated_upto:
		start = max(start, add_days(getdate(schedule.last_generated_upto), 1))
	if start > end:
		return []

	dates = occurrence_dates(schedule, start, end)
	if not dates:
		schedule.db_set("last_generated_upto", end, update_modified=False)
		return []

	# A date already carrying a session is never regenerated, whatever its status —
	# that is what stops a session cancelled for a holiday from reappearing tonight.
	already_generated = set(
		frappe.get_all(
			"Bandhu Clinic Session",
			filters={"session_schedule": schedule.name, "date": ["in", dates]},
			pluck="date",
		)
	)

	created = []
	for day in dates:
		if day in already_generated:
			continue
		session = build_session(schedule, day)
		session.insert()
		created.append(session.name)

	schedule.db_set("last_generated_upto", end, update_modified=False)
	return created


def generate_scheduled_sessions():
	"""Nightly entry point. Registered in hooks.py under scheduler_events."""
	if not is_auto_generation_enabled():
		return

	schedules = frappe.get_all("Bandhu Session Schedule", filters={"enabled": 1}, pluck="name")
	for index, name in enumerate(schedules):
		savepoint = f"session_schedule_{index}"
		frappe.db.savepoint(savepoint)
		try:
			generate_sessions_for_schedule(name)
		except Exception:
			# One malformed schedule must not cost every other schedule its sessions.
			frappe.db.rollback(save_point=savepoint)
			frappe.log_error(title=f"Session generation failed for {name}")


ASSIGNMENT_LABELS = {
	"assigned_doctor": "Doctor",
	"assigned_nurse": "Nurse",
	"assigned_driver": "Driver",
	"vehicle": "Vehicle",
}

CLASH_CHECK_DATES = 10


def find_assignment_clashes(schedule, dates: list) -> list:
	"""Staff or a vehicle already committed to another camp on one of these dates.
	Reported, never blocked — a genuine double-booking is sometimes intentional."""
	if not dates:
		return []

	assigned = {field: schedule.get(field) for field in ASSIGNMENT_LABELS if schedule.get(field)}
	if not assigned:
		return []

	sessions = frappe.get_all(
		"Bandhu Clinic Session",
		filters={"date": ["in", dates], "status": ["!=", "Cancelled"]},
		or_filters=assigned,
		fields=["name", "date", "site", "session_schedule", *ASSIGNMENT_LABELS],
	)

	practitioner_names = dict(
		frappe.get_all(
			"Healthcare Practitioner",
			filters={"name": ["in", list(assigned.values())]},
			fields=["name", "practitioner_name"],
			as_list=True,
		)
	)

	# Staff read these rows to decide whether to reassign, so they carry the readable site
	# name for the same reason the boards and My Schedule do.
	label_sites(sessions)

	clashes = []
	for session in sessions:
		if schedule.get("name") and session.session_schedule == schedule.get("name"):
			continue
		for field, value in assigned.items():
			if session.get(field) != value:
				continue
			clashes.append(
				{
					"date": str(session.date),
					"role": ASSIGNMENT_LABELS[field],
					"who": practitioner_names.get(value, value),
					"site": session.site,
					"session": session.name,
				}
			)
	return clashes


WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


ACCEPTED_FIELDS = (
	"site",
	"clinic",
	"project",
	"unit",
	"vehicle",
	"frequency",
	"monthly_mode",
	"week_of_month",
	"day_of_month",
	"planned_start_time",
	"planned_end_time",
	"valid_from",
	"valid_upto",
	"holiday_list",
	"assigned_doctor",
	"assigned_nurse",
	"assigned_driver",
)


def as_draft(values) -> "frappe.model.document.Document":
	"""Turn the wizard's payload into an unsaved schedule so the same date maths and
	clash check serve the preview and the real save."""
	values = frappe.parse_json(values) or {}
	weekdays = values.get("weekdays") or []

	draft = frappe.new_doc("Bandhu Session Schedule")
	# Only the wizard's own fields are copied: passing the whole payload to update() let a
	# caller set name, owner or last_generated_upto.
	draft.update({field: values[field] for field in ACCEPTED_FIELDS if values.get(field) not in (None, "")})
	# The wizard posts weekdays as plain strings; an existing schedule's as_dict() posts them as
	# child rows. Preview is reached from both, so normalise rather than trusting one shape.
	for weekday in weekdays:
		if isinstance(weekday, dict):
			weekday = weekday.get("weekday")
		if weekday in WEEKDAYS:
			draft.append("weekdays", {"weekday": weekday})
	return draft


@frappe.whitelist()
def preview_occurrences(schedule: str) -> list:
	"""Next few dates for a schedule the user is still editing, so the pattern is
	visible before it creates anything."""
	frappe.has_permission("Bandhu Session Schedule", "read", throw=True)

	draft = as_draft(schedule)
	if not draft.valid_from:
		frappe.throw(_("Set Valid From before previewing dates."))

	start = getdate(today())
	end = start + timedelta(days=horizon_days())
	return [str(day) for day in occurrence_dates(draft, start, end)[:PREVIEW_LIMIT]]


def remove_unused_future_sessions(schedule: str) -> list:
	"""Drop the schedule's future sessions that nobody has used yet, so the current pattern
	can rebuild them. A camp carrying clinical data is never destroyed."""
	candidates = frappe.get_all(
		"Bandhu Clinic Session",
		filters={"session_schedule": schedule, "status": "Planned", "date": [">", today()]},
		pluck="name",
	)
	if not candidates:
		return []

	with_encounters = set()
	for batch in create_batch(candidates, SESSION_BATCH_SIZE):
		with_encounters.update(
			frappe.get_all(
				"Patient Encounter",
				filters={"custom_clinic_session": ["in", batch]},
				pluck="custom_clinic_session",
				distinct=True,
			)
		)

	removed = [session for session in candidates if session not in with_encounters]
	for session in removed:
		frappe.delete_doc("Bandhu Clinic Session", session, ignore_permissions=True)

	# The removed dates are behind the watermark, so without this they would never come back.
	frappe.db.set_value(
		"Bandhu Session Schedule", schedule, "last_generated_upto", None, update_modified=False
	)
	return removed


def rebuild_sessions(schedule: str, regenerate: bool = False) -> None:
	"""Background entry point for session generation on save."""
	if regenerate:
		remove_unused_future_sessions(schedule)
	generate_sessions_for_schedule(schedule)


def enqueue_session_generation(schedule: str, regenerate: bool = False) -> None:
	# A daily schedule against the 730-day horizon ceiling is 730 inserts, each taking the
	# naming series lock — far too much to hang off the user's save request.
	# Deliberately not deduplicated: frappe.enqueue answers a duplicate job_id by dropping the
	# new call outright, which would silently discard a regenerate=True save queued behind a
	# plain one. Both jobs are idempotent, so paying for the second is the cheaper mistake.
	frappe.enqueue(
		"bandhu_app.bandhu_app.utils.session_schedule.rebuild_sessions",
		queue="long",
		enqueue_after_commit=True,
		now=frappe.in_test,
		schedule=schedule,
		regenerate=regenerate,
	)


@frappe.whitelist(methods=["POST"])
def generate_now(schedule: str) -> list:
	frappe.has_permission("Bandhu Session Schedule", "write", doc=schedule, throw=True)
	return generate_sessions_for_schedule(schedule)
