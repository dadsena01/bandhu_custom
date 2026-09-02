/* global bandhu */

const SESSION_UI_ASSET = "/assets/bandhu_app/js/session_ui.js";

let options = {};
let session = {};

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

function resetForm() {
	const defaults = options.defaults || {};
	session = {
		date: defaults.date,
		planned_start_time: defaults.planned_start_time,
		planned_end_time: defaults.planned_end_time,
		project: defaults.project,
	};
}

function requiredMark(required) {
	return required ? ' <span class="required-mark">*</span>' : "";
}

function selectField(field, label, choices, required) {
	const items = (choices || []).map((choice) =>
		typeof choice === "string" ? { value: choice, label: choice } : choice
	);
	const rows = items
		.map(
			(item) =>
				'<option value="' +
				frappe.utils.escape_html(item.value) +
				'"' +
				(session[field] === item.value ? " selected" : "") +
				">" +
				frappe.utils.escape_html(item.label || item.value) +
				"</option>"
		)
		.join("");

	return (
		'<div class="form-group"><label>' +
		frappe.utils.escape_html(label) +
		requiredMark(required) +
		"</label>" +
		'<select class="form-control new-session-field" data-field="' +
		field +
		'"><option value="">' +
		__("-- Select --") +
		"</option>" +
		rows +
		"</select></div>"
	);
}

function inputField(field, label, type, required) {
	return (
		'<div class="form-group"><label>' +
		frappe.utils.escape_html(label) +
		requiredMark(required) +
		"</label>" +
		'<input type="' +
		type +
		'" class="form-control new-session-field" data-field="' +
		field +
		'" value="' +
		frappe.utils.escape_html(session[field] || "") +
		'"></div>'
	);
}

function renderWhere() {
	// Hierarchy is Project > Site > Clinic > Unit: each field narrows the ones below it to
	// what has actually been run together before (see filteredByHistory), and Clinic is
	// additionally hard-filtered by Project since Clinic.project is a real schema link.
	const associations = options.associations || {};
	const sites = filteredByHistory(options.sites, associations.project_sites, session.project);

	let clinics = options.clinics || [];
	if (session.project) {
		clinics = clinics.filter((clinic) => clinic.project === session.project);
	}
	clinics = filteredByHistory(clinics, associations.site_clinics, session.site);

	const units = filteredByHistory(options.units, associations.clinic_units, session.clinic);

	return (
		'<div class="card"><div class="section-label">' +
		__("Where") +
		'</div><div class="field-grid">' +
		selectField("project", __("Project"), options.projects, true) +
		selectField("site", __("Site"), sites, true) +
		selectField("clinic", __("Clinic"), clinics, true) +
		selectField("unit", __("Unit"), units, false) +
		"</div></div>"
	);
}

function renderWhen() {
	return (
		'<div class="card"><div class="section-label">' +
		__("When") +
		'</div><div class="field-grid">' +
		inputField("date", __("Date"), "date", true) +
		inputField("planned_start_time", __("Starts at"), "time", false) +
		inputField("planned_end_time", __("Ends at"), "time", false) +
		"</div></div>"
	);
}

function renderWho() {
	return (
		'<div class="card"><div class="section-label">' +
		__("Who") +
		'</div><div class="field-grid">' +
		selectField("assigned_doctor", __("Doctor"), options.doctors, false) +
		selectField("assigned_nurse", __("Nurse"), options.nurses, false) +
		selectField("assigned_driver", __("Driver"), options.drivers, false) +
		selectField("vehicle", __("Vehicle"), options.vehicles, false) +
		"</div></div>"
	);
}

function renderClashes(clashes) {
	if (!clashes || !clashes.length) return "";
	const rows = clashes
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

function render(page, clashes) {
	page.main.html(
		'<div class="new-session-form">' +
			renderWhere() +
			renderWhen() +
			renderWho() +
			renderClashes(clashes) +
			"</div>"
	);
	bind(page);
}

function bind(page) {
	// page.main outlives every render, so a stale delegated handler would fire twice.
	page.main.off("change").off("input");

	page.main.on("change", ".new-session-field", function () {
		const field = $(this).data("field");
		applyFieldChange(field, $(this).val());
		// Project/Site/Clinic sit above other fields in the hierarchy and narrow their
		// options, so they need an immediate repaint; anything else can render lazily once
		// the clash check comes back.
		if (["project", "site", "clinic"].includes(field)) {
			render(page);
		}
		scheduleClashCheck(page);
	});
}

function applyFieldChange(field, value) {
	session[field] = value;

	// Clinic is the only master that already knows its project and vehicle.
	if (field === "clinic") {
		const clinic = (options.clinics || []).find((item) => item.value === value);
		if (clinic) {
			session.project = clinic.project || session.project;
			session.vehicle = clinic.vehicle || session.vehicle;
		}
	}

	// Project and Site sit above Clinic and Unit in the hierarchy — a value the field
	// below no longer offers must be cleared, not left selected but invisible.
	const associations = options.associations || {};
	if (field === "project") {
		const clinic = (options.clinics || []).find((item) => item.value === session.clinic);
		if (clinic && value && clinic.project !== value) {
			session.clinic = "";
			session.unit = "";
		}
		if (session.site && !historyAllows(associations.project_sites, value, session.site)) {
			session.site = "";
		}
	}
	if (field === "site" && session.clinic) {
		if (!historyAllows(associations.site_clinics, value, session.clinic)) {
			session.clinic = "";
			session.unit = "";
		}
	}
	if (field === "clinic" && session.unit) {
		if (!historyAllows(associations.clinic_units, value, session.unit)) {
			session.unit = "";
		}
	}
}

let clashTimer = null;

function scheduleClashCheck(page) {
	clearTimeout(clashTimer);
	clashTimer = setTimeout(() => loadClashes(page), 300);
}

async function loadClashes(page) {
	if (!session.date) return;

	let clashes = [];
	try {
		const response = await frappe.call({
			method: "bandhu_app.bandhu_app.page.new_session.new_session.check_clashes",
			args: { values: JSON.stringify(session) },
		});
		clashes = (response && response.message) || [];
	} catch (error) {
		// The clash warning is guidance; losing it must not block the form.
		return;
	}
	render(page, clashes);
}

function missingField() {
	if (!session.project) return __("Pick a project.");
	if (!session.site) return __("Pick a site.");
	if (!session.clinic) return __("Pick a clinic.");
	if (!session.date) return __("Set the session date.");
	return null;
}

async function createSession(page) {
	const missing = missingField();
	if (missing) {
		frappe.show_alert({ message: missing, indicator: "orange" });
		return;
	}

	frappe.dom.freeze();
	let result;
	try {
		const response = await frappe.call({
			method: "bandhu_app.bandhu_app.page.new_session.new_session.create_session",
			args: { values: JSON.stringify(session) },
		});
		result = response && response.message;
	} finally {
		frappe.dom.unfreeze();
	}
	if (!result) return;

	frappe.show_alert({ message: __("Session created."), indicator: "green" });
	frappe.set_route("Form", "Bandhu Clinic Session", result.name);
}

async function loadOptions(page) {
	frappe.dom.freeze();
	try {
		const response = await frappe.call({
			method: "bandhu_app.bandhu_app.page.new_session.new_session.get_form_options",
		});
		options = (response && response.message) || {};
	} finally {
		frappe.dom.unfreeze();
	}

	resetForm();
	render(page);
}

frappe.pages["new-session"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("New Session"),
		single_column: true,
	});

	page.set_primary_action(__("Create Session"), () => createSession(page));
	page.set_secondary_action(__("Reset"), () => {
		resetForm();
		render(page);
	});

	// No on_page_show reload here: this page holds a half-filled form, and re-running the
	// load on every return would throw away whatever the admin had already entered.
	(async () => {
		await frappe.require(SESSION_UI_ASSET);
		await bandhu.session_ui.refresh_page(page, loadOptions);
	})();
};
