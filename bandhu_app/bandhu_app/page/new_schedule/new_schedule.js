/* global bandhu */

const SESSION_UI_ASSET = "/assets/bandhu_app/js/session_ui.js";

const STEPS = [__("Where"), __("When"), __("Who"), __("Check")];

const DAY_INITIALS = {
	Monday: "M",
	Tuesday: "T",
	Wednesday: "W",
	Thursday: "T",
	Friday: "F",
	Saturday: "S",
	Sunday: "S",
};

let options = {};
let schedule = {};
let preview = { dates: [], total: 0, clashes: [], next_4_weeks: [] };
let step = 0;
let previewTimer = null;

// No recorded history for a key is "nothing has run there yet", not "nothing is valid" —
// an empty or missing map entry must fall through to the full list, never to zero options.
function filteredByHistory(list, historyMap, key) {
	if (!key) return list;
	const allowed = (historyMap || {})[key];
	if (!allowed || !allowed.length) return list;
	const allowedSet = new Set(allowed);
	return list.filter((item) => allowedSet.has(item.value));
}

function historyAllows(historyMap, key, value) {
	const allowed = (historyMap || {})[key];
	return !allowed || !allowed.length || allowed.includes(value);
}

function resetWizard() {
	const defaults = options.defaults || {};
	schedule = {
		frequency: "Weekly",
		monthly_mode: "Day of Week",
		week_of_month: "First",
		weekdays: [],
		planned_start_time: defaults.planned_start_time,
		planned_end_time: defaults.planned_end_time,
		valid_from: defaults.valid_from,
		project: defaults.project,
		holiday_list: defaults.holiday_list,
	};
	preview = { dates: [], total: 0, clashes: [], next_4_weeks: [] };
	step = 0;
}

function requiredMark(required) {
	return required ? ' <span class="required-mark">*</span>' : "";
}

function selectField(field, label, choices, options_html_extra, required) {
	const items = (choices || []).map((choice) =>
		typeof choice === "string" ? { value: choice, label: choice } : choice
	);
	const rows = items
		.map(
			(item) =>
				'<option value="' +
				frappe.utils.escape_html(item.value) +
				'"' +
				(schedule[field] === item.value ? " selected" : "") +
				">" +
				frappe.utils.escape_html(item.label || item.value) +
				"</option>"
		)
		.join("");

	return (
		'<div class="form-group' +
		(options_html_extra || "") +
		'"><label>' +
		frappe.utils.escape_html(label) +
		requiredMark(required) +
		"</label>" +
		'<select class="form-control wizard-field" data-field="' +
		field +
		'"><option value="">' +
		__("-- Select --") +
		"</option>" +
		rows +
		"</select></div>"
	);
}

function inputField(field, label, type, extra, required) {
	return (
		'<div class="form-group"><label>' +
		frappe.utils.escape_html(label) +
		requiredMark(required) +
		"</label>" +
		'<input type="' +
		type +
		'" class="form-control wizard-field" data-field="' +
		field +
		'" value="' +
		frappe.utils.escape_html(schedule[field] || "") +
		'" ' +
		(extra || "") +
		"></div>"
	);
}

function renderWhere() {
	// Hierarchy is Project > Site > Clinic > Unit: each field narrows the ones below it to
	// what has actually been run together before (see filteredByHistory), and Clinic is
	// additionally hard-filtered by Project since Clinic.project is a real schema link.
	const associations = options.associations || {};
	const sites = filteredByHistory(options.sites, associations.project_sites, schedule.project);

	let clinics = options.clinics || [];
	if (schedule.project) {
		clinics = clinics.filter((clinic) => clinic.project === schedule.project);
	}
	clinics = filteredByHistory(clinics, associations.site_clinics, schedule.site);

	const units = filteredByHistory(options.units, associations.clinic_units, schedule.clinic);

	return (
		'<div class="card"><div class="field-grid">' +
		selectField("project", __("Project"), options.projects, " field-wide", true) +
		selectField("site", __("Site"), sites, "", true) +
		selectField("clinic", __("Clinic"), clinics, "", true) +
		selectField("unit", __("Unit"), units, "", true) +
		"</div></div>"
	);
}

function renderWhen() {
	const frequencies = (options.frequencies || [])
		.map(
			(choice) =>
				'<div class="choice wizard-frequency' +
				(schedule.frequency === choice.value ? " selected" : "") +
				'" data-value="' +
				choice.value +
				'">' +
				frappe.utils.escape_html(__(choice.label)) +
				"</div>"
		)
		.join("");

	const chips = (options.weekdays || [])
		.map(
			(day) =>
				'<button type="button" class="day-chip wizard-day' +
				(schedule.weekdays.includes(day) ? " selected" : "") +
				'" data-day="' +
				day +
				'" title="' +
				frappe.utils.escape_html(__(day)) +
				'">' +
				DAY_INITIALS[day] +
				"</button>"
		)
		.join("");

	const usesDayOfMonth =
		schedule.frequency === "Monthly" && schedule.monthly_mode === "Day of Month";

	const monthlyExtra =
		schedule.frequency !== "Monthly"
			? ""
			: '<div class="section-label">' +
			  __("Which day of the month") +
			  "</div>" +
			  '<div class="choice-row">' +
			  ["Day of Week", "Day of Month"]
					.map(
						(mode) =>
							'<div class="choice wizard-monthly-mode' +
							(schedule.monthly_mode === mode ? " selected" : "") +
							'" data-value="' +
							mode +
							'">' +
							(mode === "Day of Week"
								? __("A weekday, e.g. first Monday")
								: __("A date, e.g. the 15th")) +
							"</div>"
					)
					.join("") +
			  "</div>" +
			  '<div class="field-grid field-grid-spaced">' +
			  (usesDayOfMonth
					? inputField(
							"day_of_month",
							__("Date in the month"),
							"number",
							'min="1" max="31"',
							true
					  )
					: selectField("week_of_month", __("Which week"), [
							"First",
							"Second",
							"Third",
							"Fourth",
							"Last",
					  ])) +
			  "</div>";

	return (
		'<div class="card">' +
		'<div class="section-label">' +
		__("How often") +
		"</div>" +
		'<div class="choice-row">' +
		frequencies +
		"</div>" +
		monthlyExtra +
		(usesDayOfMonth
			? ""
			: '<div class="section-label">' +
			  __("Which days") +
			  requiredMark(true) +
			  '</div><div class="day-chips">' +
			  chips +
			  "</div>") +
		'<div class="section-label">' +
		__("Timing") +
		"</div>" +
		'<div class="field-grid">' +
		inputField("planned_start_time", __("Starts at"), "time") +
		inputField("planned_end_time", __("Ends at"), "time") +
		inputField("valid_from", __("Runs from"), "date", "", true) +
		inputField("valid_upto", __("Runs until (optional)"), "date") +
		"</div>" +
		'<div class="section-label">' +
		__("Holidays") +
		"</div>" +
		'<div class="field-grid">' +
		selectField("holiday_list", __("Skip dates in"), options.holiday_lists) +
		"</div></div>"
	);
}

function renderWho() {
	return (
		'<div class="card"><div class="field-grid">' +
		selectField("assigned_doctor", __("Doctor"), options.doctors, "", true) +
		selectField("assigned_nurse", __("Nurse"), options.nurses, "", true) +
		selectField("assigned_driver", __("Driver"), options.drivers, "", true) +
		selectField("vehicle", __("Vehicle"), options.vehicles, "", true) +
		"</div></div>"
	);
}

function labelFor(list, value) {
	const match = (list || []).find((item) => (item.value || item) === value);
	if (!match) return value || "";
	return match.label || match.value || match;
}

function clock_label(value) {
	const [hours, minutes] = String(value).split(":");
	const hour = parseInt(hours, 10);
	const hour12 = hour % 12 === 0 ? 12 : hour % 12;
	return hour12 + ":" + (minutes || "00") + (hour < 12 ? " AM" : " PM");
}

function summarySentence() {
	const days = schedule.weekdays.map((day) => __(day)).join(", ");
	const when =
		schedule.frequency === "Monthly"
			? schedule.monthly_mode === "Day of Month"
				? __("on day {0} of every month", [schedule.day_of_month || "?"])
				: __("on the {0} {1} of every month", [__(schedule.week_of_month), days || "?"])
			: schedule.frequency === "Fortnightly"
			? __("every two weeks on {0}", [days || "?"])
			: __("every week on {0}", [days || "?"]);

	const time =
		schedule.planned_start_time && schedule.planned_end_time
			? __("from {0} to {1}", [
					clock_label(schedule.planned_start_time),
					clock_label(schedule.planned_end_time),
			  ])
			: "";

	const team = [
		schedule.assigned_doctor ? labelFor(options.doctors, schedule.assigned_doctor) : null,
		schedule.assigned_nurse ? labelFor(options.nurses, schedule.assigned_nurse) : null,
		schedule.assigned_driver ? labelFor(options.drivers, schedule.assigned_driver) : null,
	].filter(Boolean);

	return (
		"<b>" +
		frappe.utils.escape_html(labelFor(options.sites, schedule.site)) +
		"</b>, " +
		frappe.utils.escape_html(when) +
		" " +
		frappe.utils.escape_html(time) +
		(schedule.unit
			? ", " + frappe.utils.escape_html(labelFor(options.units, schedule.unit))
			: "") +
		(team.length ? ". " + __("Team") + ": " + frappe.utils.escape_html(team.join(", ")) : "") +
		". " +
		__("{0} camps will be created now.", [preview.total || 0])
	);
}

function renderCheck() {
	return (
		'<div class="card card-plain"><div class="summary">' +
		summarySentence() +
		"</div>" +
		renderNextFourWeeks() +
		"</div>"
	);
}

function renderNextFourWeeks() {
	const dates = preview.next_4_weeks || [];

	if (!dates.length) {
		return '<div class="preview-empty">' + __("No camps fall in the next 4 weeks.") + "</div>";
	}

	const site = labelFor(options.sites, schedule.site);
	const clinic = labelFor(options.clinics, schedule.clinic);
	const unit = schedule.unit ? labelFor(options.units, schedule.unit) : "";
	const time =
		schedule.planned_start_time && schedule.planned_end_time
			? clock_label(schedule.planned_start_time) +
			  " - " +
			  clock_label(schedule.planned_end_time)
			: "";

	const rows = dates
		.map(
			(day) =>
				"<tr><td>" +
				frappe.utils.escape_html(moment(day).format("ddd, D MMM")) +
				"</td><td>" +
				frappe.utils.escape_html(site) +
				"</td><td>" +
				frappe.utils.escape_html(clinic) +
				"</td><td>" +
				frappe.utils.escape_html(unit) +
				"</td><td>" +
				frappe.utils.escape_html(time) +
				"</td></tr>"
		)
		.join("");

	return (
		'<div class="table-wrap table-wrap-tall"><table class="table"><thead><tr><th>' +
		__("Date") +
		"</th><th>" +
		__("Site") +
		"</th><th>" +
		__("Clinic") +
		"</th><th>" +
		__("Unit") +
		"</th><th>" +
		__("Time") +
		"</th></tr></thead><tbody>" +
		rows +
		"</tbody></table></div>"
	);
}

function renderClashes() {
	if (!preview.clashes.length) return "";
	const rows = preview.clashes
		.map(
			(clash) =>
				"<tr><td>" +
				frappe.utils.escape_html(clash.role) +
				"</td><td>" +
				frappe.utils.escape_html(clash.who) +
				"</td><td>" +
				frappe.utils.escape_html(clash.site || "") +
				"</td><td>" +
				frappe.utils.escape_html(frappe.datetime.str_to_user(clash.date)) +
				"</td></tr>"
		)
		.join("");
	return (
		'<div class="clash"><b>' +
		__("Already assigned elsewhere") +
		"</b>" +
		'<table class="clash-table"><thead><tr><th>' +
		__("Role") +
		"</th><th>" +
		__("Name") +
		"</th><th>" +
		__("Site") +
		"</th><th>" +
		__("Date") +
		"</th></tr></thead><tbody>" +
		rows +
		"</tbody></table></div>"
	);
}

function renderPreview() {
	if (!preview.dates.length) {
		return (
			'<div class="preview"><div class="preview-title">' +
			__("Next dates") +
			'</div><div class="preview-empty">' +
			__("Pick days to see the dates.") +
			"</div></div>"
		);
	}

	const rows = preview.dates
		.map(
			(day) =>
				'<div class="timeline-item">' +
				frappe.utils.escape_html(moment(day).format("ddd D MMM")) +
				"</div>"
		)
		.join("");

	return (
		'<div class="preview"><div class="preview-title">' +
		__("Next dates") +
		'</div><div class="timeline">' +
		rows +
		"</div>" +
		(preview.total > preview.dates.length
			? '<div class="preview-empty preview-empty-spaced">' +
			  __("{0} in total", [preview.total]) +
			  "</div>"
			: "") +
		"</div>"
	);
}

function render(page) {
	const body = [renderWhere, renderWhen, renderWho, renderCheck][step]();

	page.main.html(
		'<div class="sched-wizard">' +
			'<div class="stepper">' +
			STEPS.map(
				(label, index) =>
					'<div class="stepper-step' +
					(index === step ? " active" : index < step ? " done" : "") +
					'"><div class="stepper-node">' +
					(index < step ? "&#10003;" : String(index + 1)) +
					'</div><div class="stepper-label">' +
					frappe.utils.escape_html(label) +
					"</div></div>"
			).join("") +
			"</div>" +
			'<div class="panels' +
			(step === STEPS.length - 1 ? " panels-single" : "") +
			'"><div>' +
			body +
			'<div class="actions">' +
			'<button class="btn btn-default wizard-back"' +
			(step === 0 ? " disabled" : "") +
			">" +
			__("Back") +
			"</button>" +
			(step === STEPS.length - 1
				? '<button class="btn btn-primary wizard-create">' +
				  __("Create Schedule") +
				  "</button>"
				: '<button class="btn btn-primary wizard-next">' + __("Next") + "</button>") +
			"</div></div>" +
			(step === STEPS.length - 1 ? "" : renderPreview()) +
			"</div>" +
			// Full width, below the two-column layout — the 280px sidebar column is too
			// narrow for a Role/Who/Where/Date table once more than one person clashes.
			// Only relevant while staff is actually being picked, so it only shows there.
			(step === 2 ? renderClashes() : "") +
			"</div>"
	);

	bind(page);
}

function bind(page) {
	// page.main outlives every render, so a stale delegated handler would fire twice.
	page.main.off("click").off("change").off("input");

	page.main.on("change", ".wizard-field", function () {
		const field = $(this).data("field");
		applyFieldChange(field, $(this).val());
		// Project/Site/Clinic sit above other fields in the hierarchy and narrow their
		// options, so they need an immediate repaint; anything else would just steal
		// focus from the field being edited.
		if (["project", "site", "clinic"].includes(field)) render(page);
		schedulePreview(page);
	});

	page.main.on("click", ".wizard-frequency", function () {
		schedule.frequency = $(this).data("value");
		render(page);
		schedulePreview(page);
	});

	page.main.on("click", ".wizard-monthly-mode", function () {
		schedule.monthly_mode = $(this).data("value");
		render(page);
		schedulePreview(page);
	});

	page.main.on("click", ".wizard-day", function () {
		const day = $(this).data("day");
		schedule.weekdays = schedule.weekdays.includes(day)
			? schedule.weekdays.filter((selected) => selected !== day)
			: [...schedule.weekdays, day];
		render(page);
		schedulePreview(page);
	});

	page.main.on("click", ".wizard-back", () => {
		step = Math.max(0, step - 1);
		render(page);
	});

	page.main.on("click", ".wizard-next", () => goNext(page));
	page.main.on("click", ".wizard-create", () => createSchedule(page));
}

function applyFieldChange(field, value) {
	schedule[field] = value;

	// Clinic is the only master that already knows its project and vehicle.
	if (field === "clinic") {
		const clinic = (options.clinics || []).find((item) => item.value === value);
		if (clinic) {
			schedule.project = clinic.project || schedule.project;
			schedule.vehicle = clinic.vehicle || schedule.vehicle;
		}
	}

	// Project and Site sit above Clinic and Unit in the hierarchy — a value the field
	// below no longer offers must be cleared, not left selected but invisible.
	const associations = options.associations || {};
	if (field === "project") {
		const clinic = (options.clinics || []).find((item) => item.value === schedule.clinic);
		if (clinic && value && clinic.project !== value) {
			schedule.clinic = "";
			schedule.unit = "";
		}
		if (schedule.site && !historyAllows(associations.project_sites, value, schedule.site)) {
			schedule.site = "";
		}
	}
	if (field === "site" && schedule.clinic) {
		if (!historyAllows(associations.site_clinics, value, schedule.clinic)) {
			schedule.clinic = "";
			schedule.unit = "";
		}
	}
	if (field === "clinic" && schedule.unit) {
		if (!historyAllows(associations.clinic_units, value, schedule.unit)) {
			schedule.unit = "";
		}
	}
}

function missingForStep() {
	if (step === 0) {
		if (!schedule.project) return __("Pick a project.");
		if (!schedule.site) return __("Pick a site.");
		if (!schedule.clinic) return __("Pick a clinic.");
		if (!schedule.unit) return __("Pick a unit.");
		return null;
	}
	if (step === 1) {
		const usesDayOfMonth =
			schedule.frequency === "Monthly" && schedule.monthly_mode === "Day of Month";
		if (usesDayOfMonth && !schedule.day_of_month) return __("Set the date in the month.");
		if (!usesDayOfMonth && !schedule.weekdays.length) return __("Pick at least one day.");
		if (!schedule.valid_from) return __("Set the date this schedule starts from.");
		if (!preview.total)
			return __("This pattern produces no dates. Check the days and the start date.");
	}
	if (step === 2) {
		if (!schedule.assigned_doctor) return __("Assign a doctor.");
		if (!schedule.assigned_nurse) return __("Assign a nurse.");
		if (!schedule.assigned_driver) return __("Assign a driver.");
		if (!schedule.vehicle) return __("Assign a vehicle.");
	}
	return null;
}

function goNext(page) {
	const missing = missingForStep();
	if (missing) {
		frappe.show_alert({ message: missing, indicator: "orange" });
		return;
	}
	step = Math.min(STEPS.length - 1, step + 1);
	render(page);
	schedulePreview(page);
}

function schedulePreview(page) {
	clearTimeout(previewTimer);
	previewTimer = setTimeout(() => loadPreview(page), 300);
}

async function loadPreview(page) {
	if (!schedule.valid_from) return;

	try {
		const response = await frappe.call({
			method: "bandhu_app.bandhu_app.page.new_schedule.new_schedule.preview_schedule",
			args: { values: JSON.stringify(schedule) },
		});
		preview = (response && response.message) || {
			dates: [],
			total: 0,
			clashes: [],
			next_4_weeks: [],
		};
	} catch (error) {
		// The preview is guidance; losing it must not block the wizard.
		return;
	}
	render(page);
}

async function createSchedule(page) {
	frappe.dom.freeze();
	let result;
	try {
		const response = await frappe.call({
			method: "bandhu_app.bandhu_app.page.new_schedule.new_schedule.create_schedule",
			args: { values: JSON.stringify(schedule) },
		});
		result = response && response.message;
	} finally {
		frappe.dom.unfreeze();
	}
	if (!result) return;

	frappe.show_alert({
		message: __("Schedule created. {0} camp(s) are being added in the background.", [
			result.scheduled,
		]),
		indicator: "green",
	});
	frappe.set_route("Form", "Bandhu Session Schedule", result.name);
}

async function loadOptions(page) {
	frappe.dom.freeze();
	try {
		const response = await frappe.call({
			method: "bandhu_app.bandhu_app.page.new_schedule.new_schedule.get_form_options",
		});
		options = (response && response.message) || {};
	} finally {
		frappe.dom.unfreeze();
	}

	resetWizard();
	render(page);
}

frappe.pages["new-schedule"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("New Schedule"),
		single_column: true,
	});

	page.set_secondary_action(__("Start Over"), () => {
		resetWizard();
		render(page);
	});

	// No on_page_show reload here: this page holds a half-filled wizard, and re-running the load
	// on every return would throw away whatever the planner had already entered.
	(async () => {
		await frappe.require(SESSION_UI_ASSET);
		await bandhu.session_ui.refresh_page(page, loadOptions);
	})();
};
