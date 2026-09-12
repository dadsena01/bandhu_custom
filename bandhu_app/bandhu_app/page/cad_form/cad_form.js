/* global bandhu */

const SESSION_UI_ASSET = "/assets/bandhu_app/js/session_ui.js";

let cadSession = null;
let cadPage = null;
let formOptions = { major_states: [], other_states: [], major_sectors: [] };

const QUICK_COUNTRIES = ["India", "Nepal"];

// Matches MAX_PLAUSIBLE_AGE in cad_form.py.
const MAX_PLAUSIBLE_AGE = 120;

// Matches MIN_SEARCH_LENGTH in cad_form.py.
const MIN_SEARCH_LENGTH = 2;

const NAME_FIELD = {
	name: "full_name",
	label: __("Full Name"),
	type: "text",
	wide: true,
	required: true,
};

const AGE_AND_DOB_FIELDS = [
	{
		name: "age",
		label: __("Age (Years)"),
		type: "number",
		attrs: 'min="0" max="' + MAX_PLAUSIBLE_AGE + '" step="1" inputmode="numeric"',
	},
	{ name: "dob", label: __("Date of Birth"), type: "date" },
];

const MEASUREMENT_FIELDS = [
	{
		name: "height_cm",
		label: __("Height (cm)"),
		type: "number",
		attrs: 'min="0" step="0.1" inputmode="decimal"',
	},
	{
		name: "weight_kg",
		label: __("Weight (kg)"),
		type: "number",
		attrs: 'min="0" step="0.1" inputmode="decimal"',
	},
];

const CONTACT_FIELDS = [
	{ name: "company_name", label: __("Name of Company"), type: "text" },
	{
		name: "mobile",
		label: __("Mobile Number"),
		type: "tel",
		attrs: 'inputmode="numeric" maxlength="10"',
	},
	{ name: "abha_id", label: __("ABHA ID"), type: "text", wide: true },
];

async function loadDashboard(page) {
	bandhu.session_ui.freeze();
	let statusResult;
	try {
		statusResult = await frappe.call({
			method: "bandhu_app.bandhu_app.page.cad_form.cad_form.get_session_status",
		});
	} finally {
		bandhu.session_ui.unfreeze();
	}

	const data = statusResult.message || {};

	if (!data.has_session) {
		renderNoSession(page, data);
		return;
	}

	cadSession = data;

	if (data.status === "Completed") {
		renderCompleted(page, data);
		return;
	}

	if (data.status === "Planned") {
		renderWaitingForNurse(page, data);
		return;
	}

	const optionsResult = await frappe.call({
		method: "bandhu_app.bandhu_app.page.cad_form.cad_form.get_form_options",
	});
	formOptions = optionsResult.message || {
		major_states: [],
		other_states: [],
		major_sectors: [],
	};

	await renderFrontDesk(page, data);
}

function renderNoSession(page, data) {
	page.main.html(
		'<div class="cad-dash">' +
			bandhu.session_ui.format_welcome() +
			'<div class="empty-state">' +
			frappe.utils.icon("calendar-off", "xl", "", "", "current-color empty-state-icon") +
			'<span class="empty-state-text">' +
			frappe.utils.escape_html(data.message || __("No session available.")) +
			"</span></div></div>"
	);
}

function renderWaitingForNurse(page, data) {
	page.main.html(
		'<div class="cad-dash">' +
			bandhu.session_ui.format_welcome() +
			bandhu.session_ui.format_session_info(data) +
			'<div class="empty-state">' +
			frappe.utils.icon("hourglass", "xl", "", "", "current-color empty-state-icon") +
			'<span class="empty-state-text">' +
			__(
				"Waiting for the nurse to start this clinic session. Patients can't be registered yet."
			) +
			"</span></div></div>"
	);
}

function renderCompleted(page, data) {
	page.main.html(
		'<div class="cad-dash">' +
			bandhu.session_ui.format_welcome() +
			bandhu.session_ui.format_session_info(data) +
			'<div class="empty-state">' +
			frappe.utils.icon(
				"circle-check",
				"xl",
				"",
				"",
				"current-color empty-state-icon done"
			) +
			'<span class="empty-state-text">' +
			__("Session completed. No further patients can be registered.") +
			"</span></div></div>"
	);
}

async function renderFrontDesk(page, data) {
	const html =
		'<div class="cad-dash">' +
		bandhu.session_ui.format_welcome() +
		bandhu.session_ui.format_session_info(data) +
		renderSearchSection() +
		renderRegisterSection() +
		'<div class="cad-queue-section">' +
		'<h4 class="queue-head">' +
		__("Today's Queue") +
		'<span class="queue-meta cad-queue-count"></span>' +
		"</h4>" +
		'<div class="table-wrap">' +
		'<table class="table">' +
		"<thead><tr>" +
		"<th>" +
		__("Patient") +
		"</th>" +
		"<th>" +
		__("Clinic ID") +
		"</th>" +
		"<th>" +
		__("Stage") +
		"</th>" +
		"<th>" +
		__("In session") +
		"</th>" +
		"<th></th>" +
		"</tr></thead>" +
		'<tbody class="cad-queue-body"></tbody>' +
		"</table></div></div>" +
		"</div>";

	page.main.html(html);
	bindSearchEvents(page);
	bindRegisterEvents(page);
	await loadQueue(page);
	focus_scan_input(page);
}

// A USB barcode scanner is a keyboard: it types the Clinic ID and presses Enter. That only
// reaches the search box if the box already holds focus when the card is scanned.
function focus_scan_input(page) {
	page.main.find(".cad-search-input").trigger("focus");
}

// The CAD role holds no print permission on Patient, so /printview would refuse. The card
// comes back through the page's own role-gated endpoint instead.
async function print_patient_card(patient) {
	if (!patient) return;

	frappe.dom.freeze();
	let card_html;
	try {
		const response = await frappe.call({
			method: "bandhu_app.bandhu_app.page.cad_form.cad_form.get_patient_card_html",
			args: { patient },
		});
		card_html = response.message;
	} finally {
		frappe.dom.unfreeze();
	}

	if (!card_html) return;

	const card_window = window.open("", "_blank");
	if (!card_window) {
		frappe.msgprint(__("Allow pop-ups for this site to print the patient card."));
		return;
	}

	card_window.document.write(card_html);
	card_window.document.close();
	card_window.focus();
	card_window.print();
}

function renderSearchSection() {
	return (
		'<div class="cad-search-section">' +
		'<h4 class="queue-head">' +
		__("Find Existing Patient") +
		"</h4>" +
		'<div class="search-row">' +
		'<div class="search-field">' +
		frappe.utils.icon("search", "sm", "", "", "current-color search-field-icon") +
		'<input type="text" class="form-control cad-search-input" placeholder="' +
		frappe.utils.escape_html(
			__("Scan the patient's card, or search by Clinic ID, ABHA ID, Mobile, Name or DOB")
		) +
		'"></div>' +
		'<button class="btn btn-default cad-search-btn">' +
		__("Search") +
		"</button>" +
		'<button class="btn btn-default cad-scan-btn" title="' +
		frappe.utils.escape_html(__("Scan the patient's card with the camera")) +
		'">' +
		frappe.utils.icon("camera", "xs", "", "", "current-color") +
		__("Scan") +
		"</button>" +
		"</div>" +
		'<div class="cad-search-results"></div>' +
		"</div>"
	);
}

function renderRegisterSection() {
	return (
		'<div class="cad-register-section">' +
		'<button class="btn btn-primary cad-register-toggle-btn">' +
		frappe.utils.icon("user-plus", "xs", "", "", "current-color") +
		__("Register New Patient") +
		"</button>" +
		'<div class="cad-register-form">' +
		renderRegisterForm() +
		"</div>" +
		"</div>"
	);
}

function requiredMark(required) {
	return required ? ' <span class="required-mark">*</span>' : "";
}

function renderField(field) {
	const input =
		'<input type="' +
		field.type +
		'" class="form-control cad-field" data-field="' +
		field.name +
		'" ' +
		(field.attrs || "") +
		">";
	return (
		'<div class="form-group' +
		(field.wide ? " field-wide" : "") +
		'">' +
		"<label>" +
		frappe.utils.escape_html(field.label) +
		requiredMark(field.required) +
		"</label>" +
		input +
		"</div>"
	);
}

function renderFields(fields) {
	return fields.map(renderField).join("");
}

function renderFieldNote(text) {
	return (
		'<div class="form-group field-wide field-note">' +
		frappe.utils.escape_html(text) +
		"</div>"
	);
}

function renderDistrictField() {
	return (
		'<div class="form-group field-wide">' +
		"<label>" +
		frappe.utils.escape_html(__("Native District")) +
		"</label>" +
		'<select class="form-control cad-field district-select" data-field="native_district" disabled>' +
		'<option value="">' +
		frappe.utils.escape_html(__("-- Select a native state first --")) +
		"</option>" +
		"</select>" +
		"</div>"
	);
}

function renderOtherPicker(options, placeholderLabel) {
	const optionHtml = options
		.map(
			(option) =>
				'<option value="' +
				frappe.utils.escape_html(option) +
				'">' +
				frappe.utils.escape_html(option) +
				"</option>"
		)
		.join("");
	return (
		'<select class="form-control other-picker" hidden>' +
		'<option value="">' +
		frappe.utils.escape_html(placeholderLabel) +
		"</option>" +
		optionHtml +
		"</select>"
	);
}

function renderTabGroup(config) {
	const buttons = config.options
		.map((option) => {
			const isDefault = option === config.defaultValue;
			return (
				'<button type="button" class="btn btn-default tab-btn' +
				(isDefault ? " is-selected" : "") +
				'" data-value="' +
				frappe.utils.escape_html(option) +
				'">' +
				frappe.utils.escape_html(__(option)) +
				"</button>"
			);
		})
		.join("");
	return (
		'<div class="form-group tab-group-wrap" data-mode="' +
		config.mode +
		'">' +
		"<label>" +
		frappe.utils.escape_html(config.label) +
		requiredMark(config.required) +
		"</label>" +
		'<input type="hidden" class="cad-field" data-field="' +
		config.field +
		'" value="' +
		frappe.utils.escape_html(config.defaultValue || "") +
		'">' +
		'<div class="tab-btn-group">' +
		buttons +
		"</div>" +
		(config.otherPickerHtml || "") +
		(config.detailFieldHtml || "") +
		"</div>"
	);
}

function renderSexGroup() {
	return renderTabGroup({
		field: "sex",
		label: __("Sex"),
		options: ["Male", "Female", "Other"],
		mode: "direct",
		required: true,
	});
}

function renderCountryGroup() {
	return renderTabGroup({
		field: "native_country",
		label: __("Country"),
		options: QUICK_COUNTRIES.concat(["Other"]),
		mode: "picker",
		defaultValue: "India",
		detailFieldHtml:
			'<input type="text" class="form-control cad-field detail-field" data-field="specify_native_country" placeholder="' +
			frappe.utils.escape_html(__("Specify country")) +
			'" hidden>',
	});
}

function renderStateGroup() {
	return renderTabGroup({
		field: "native_state",
		label: __("Native State"),
		options: (formOptions.major_states || []).concat(["Other"]),
		mode: "picker",
		otherPickerHtml: renderOtherPicker(
			formOptions.other_states || [],
			__("-- Select State --")
		),
	});
}

function renderSectorGroup() {
	return renderTabGroup({
		field: "occupation",
		label: __("Sector of Employment"),
		options: (formOptions.major_sectors || []).concat(["Other"]),
		mode: "direct",
		detailFieldHtml:
			'<input type="text" class="form-control cad-field detail-field" data-field="specify_sector" placeholder="' +
			frappe.utils.escape_html(__("Specify sector")) +
			'" hidden>',
	});
}

function renderRegisterForm() {
	return (
		'<div class="register-grid">' +
		renderField(NAME_FIELD) +
		renderSexGroup() +
		renderFields(AGE_AND_DOB_FIELDS) +
		renderFieldNote(__("Age or Date of Birth is required.")) +
		renderFields(MEASUREMENT_FIELDS) +
		renderCountryGroup() +
		renderStateGroup() +
		renderDistrictField() +
		renderSectorGroup() +
		renderFields(CONTACT_FIELDS) +
		"</div>" +
		'<div class="register-actions">' +
		'<button class="btn btn-primary btn-lg cad-register-submit">' +
		__("Register & Add to Queue") +
		"</button>" +
		"</div>"
	);
}

function bindSearchEvents(page) {
	page.main
		.off("click", ".cad-search-btn")
		.on("click", ".cad-search-btn", () => searchPatients(page));

	page.main.off("keypress", ".cad-search-input").on("keypress", ".cad-search-input", (event) => {
		if (event.which === 13) searchPatients(page);
	});

	page.main
		.off("click", ".cad-scan-btn")
		.on("click", ".cad-scan-btn", () => openCardScanner(page));

	// bound before the row handler so printing a card does not also queue the patient
	page.main.off("click", ".pr-print-btn").on("click", ".pr-print-btn", function (event) {
		event.stopPropagation();
		print_patient_card($(this).data("patient"));
	});

	// bound before the row handler so the explicit button and a stray row tap do not both fire
	page.main.off("click", ".pr-queue-btn").on("click", ".pr-queue-btn", function (event) {
		event.stopPropagation();
		confirm_add_to_queue(page, $(this).data("patient"));
	});

	page.main.off("click", ".patient-result-row").on("click", ".patient-result-row", function () {
		confirm_add_to_queue(page, $(this).data("patient"));
	});

	page.main.off("click", ".cad-search-clear").on("click", ".cad-search-clear", function () {
		clearSearchResults(page);
	});

	page.main.off("click", ".queue-print-card").on("click", ".queue-print-card", function (event) {
		event.preventDefault();
		print_patient_card($(this).data("patient"));
	});

	page.main
		.off("click", ".queue-cancel-visit")
		.on("click", ".queue-cancel-visit", function (event) {
			event.preventDefault();
			cancel_queued_visit(page, $(this).data("encounter"), $(this).data("patient-name"));
		});
}

function confirm_add_to_queue(page, patient) {
	frappe.confirm(__("Add this patient to today's queue?"), async () => {
		await addPatientToQueue(page, patient, () => {
			clearSearchResults(page);
		});
	});
}

// A patient who walks out before being seen has to leave the boards, but deleting the queue row
// would only bring it back on the encounter's next save — sync_to_queue rebuilds it from the
// encounter, so the encounter is what has to end.
function cancel_queued_visit(page, encounter, patient_name) {
	frappe.confirm(
		__("End {0}'s visit without treatment? They will drop off the doctor and nurse boards.", [
			frappe.utils.escape_html(patient_name || __("this patient")),
		]),
		async () => {
			frappe.dom.freeze();
			try {
				await frappe.call({
					method: "bandhu_app.bandhu_app.page.cad_form.cad_form.cancel_visit",
					args: { encounter: encounter, session: cadSession.session_name },
				});
			} finally {
				frappe.dom.unfreeze();
			}
			await loadQueue(page);
		}
	);
}

// A USB scanner is a keyboard and needs no code here (see focus_scan_input above); this is
// for staff without one — decode the card's QR through the device camera instead.
function openCardScanner(page) {
	// frappe.ui.Scanner fails silently to the console on a denied or unsupported camera;
	// catching it here up front is what tells the CAD why nothing opened.
	if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)) {
		frappe.msgprint(
			__("Camera scanning needs a supported browser over HTTPS. Type the Clinic ID instead.")
		);
		return;
	}

	new frappe.ui.Scanner({
		dialog: true,
		multiple: false,
		on_scan(data) {
			const clinicId = data && data.result && data.result.text;
			if (!clinicId) return;

			page.main.find(".cad-search-input").val(clinicId);
			searchPatients(page);
		},
	});
}

async function searchPatients(page) {
	const query = (page.main.find(".cad-search-input").val() || "").trim();
	if (!query) return;

	if (query.length < MIN_SEARCH_LENGTH) {
		frappe.msgprint(__("Type at least {0} characters to search.", [MIN_SEARCH_LENGTH]));
		return;
	}

	let found;
	frappe.dom.freeze();
	try {
		const response = await frappe.call({
			method: "bandhu_app.bandhu_app.page.cad_form.cad_form.search_patient",
			args: { query },
		});
		found = response.message || {};
	} finally {
		frappe.dom.unfreeze();
	}

	const results = found.results || [];
	const scanned = match_scanned_card(query, results);
	if (scanned) {
		queue_scanned_patient(page, scanned);
		return;
	}

	renderSearchResults(page, results, found.capped);
}

function clearSearchResults(page) {
	page.main.find(".cad-search-results").empty();
	page.main.find(".cad-search-input").val("");
	focus_scan_input(page);
}

// Ten digits is the current Clinic ID; BMC-##### is the format issued before this one and
// still printed on cards in circulation.
const CLINIC_ID_PATTERN = /^(?:\d{10}|BMC-\d+)$/i;

function match_scanned_card(query, results) {
	if (!CLINIC_ID_PATTERN.test(query)) return null;

	const exact = results.filter(
		(patient) => (patient.custom_bandhu_id || "").toUpperCase() === query.toUpperCase()
	);

	// Anything other than a single exact hit goes to the normal list, so the CAD sees the
	// ambiguity rather than having the screen pick a patient for them.
	return exact.length === 1 ? exact[0] : null;
}

function queue_scanned_patient(page, patient) {
	// frappe.confirm appends its message as HTML (frappe/public/js/frappe/ui/messages.js:48) and
	// __() substitutes {0} verbatim, so a patient name is an injection point until it is escaped.
	frappe.confirm(
		__("Add {0} ({1}) to today's queue?", [
			frappe.utils.escape_html(patient.patient_name || ""),
			frappe.utils.escape_html(patient.custom_bandhu_id || ""),
		]),
		async () => {
			await addPatientToQueue(page, patient.name, () => {
				clearSearchResults(page);
			});
		},
		() => {
			page.main.find(".cad-search-input").val("").trigger("focus");
		}
	);
}

function renderSearchResults(page, results, capped) {
	const container = page.main.find(".cad-search-results");
	if (!results.length) {
		container.html(
			'<div class="empty-state"><span class="empty-state-text">' +
				__("No matching patients.") +
				"</span></div>"
		);
		return;
	}

	const rows = results
		.map((patient) => {
			const meta = [
				bandhu.session_ui.group_clinic_id(patient.custom_bandhu_id),
				patient.sex,
				patient.age,
			]
				.filter(Boolean)
				.map(frappe.utils.escape_html)
				.join(" &bull; ");
			return (
				'<div class="patient-result-row" data-patient="' +
				frappe.utils.escape_html(patient.name) +
				'">' +
				'<div class="pr-info">' +
				'<span class="pr-name">' +
				frappe.utils.escape_html(patient.patient_name || "") +
				"</span>" +
				'<span class="pr-meta">' +
				meta +
				"</span>" +
				"</div>" +
				'<div class="pr-actions">' +
				'<button class="btn btn-xs btn-default pr-print-btn" data-patient="' +
				frappe.utils.escape_html(patient.name) +
				'">' +
				__("Print Card") +
				"</button>" +
				'<button class="btn btn-xs btn-default pr-queue-btn" data-patient="' +
				frappe.utils.escape_html(patient.name) +
				'">' +
				__("Add to Queue") +
				"</button>" +
				"</div>" +
				"</div>"
			);
		})
		.join("");

	const heading = capped
		? __("First {0} matches. Narrow the search if the patient is not here.", [results.length])
		: __("{0} matching patients", [results.length]);

	container.html(
		'<div class="pr-summary">' +
			'<span class="pr-summary-text">' +
			frappe.utils.escape_html(heading) +
			"</span>" +
			'<button type="button" class="btn btn-xs btn-default cad-search-clear">' +
			__("Clear") +
			"</button></div>" +
			rows
	);
}

function bindRegisterEvents(page) {
	page.main
		.off("click", ".cad-register-toggle-btn")
		.on("click", ".cad-register-toggle-btn", function () {
			const form = page.main.find(".cad-register-form").toggle();
			$(this)
				.toggleClass("btn-primary", !form.is(":visible"))
				.toggleClass("btn-default", form.is(":visible"));
		});

	page.main
		.off("input", '.cad-field[data-field="age"]')
		.on("input", '.cad-field[data-field="age"]', function () {
			const dobField = page.main.find('.cad-field[data-field="dob"]');
			const age = parseInt($(this).val(), 10);

			if (!Number.isInteger(age) || age < 0 || age > MAX_PLAUSIBLE_AGE) {
				if (dobField.val() && dobField.val() === dobField.data("derived")) {
					dobField.val("").removeData("derived");
				}
				return;
			}

			const derived = new Date().getFullYear() - age + "-01-01";
			dobField.val(derived).data("derived", derived);
		});

	page.main
		.off("input", '.cad-field[data-field="dob"]')
		.on("input", '.cad-field[data-field="dob"]', function () {
			const ageField = page.main.find('.cad-field[data-field="age"]');
			const age = years_since($(this).val());

			if (age === null || age > MAX_PLAUSIBLE_AGE) {
				if (ageField.val() && ageField.val() === ageField.data("derived")) {
					ageField.val("").removeData("derived");
				}
				return;
			}

			ageField.val(age).data("derived", String(age));
		});

	page.main.off("click", ".tab-btn").on("click", ".tab-btn", function () {
		const wrap = $(this).closest(".tab-group-wrap");
		wrap.find(".tab-btn").removeClass("is-selected");
		$(this).addClass("is-selected");

		const value = $(this).data("value");
		const isOther = value === "Other";
		const hiddenField = wrap.find("input.cad-field");

		if (wrap.data("mode") === "picker") {
			hiddenField.val(isOther ? "" : value);
			wrap.find(".other-picker").prop("hidden", !isOther).val("");
		} else {
			hiddenField.val(value);
		}
		wrap.find(".detail-field").prop("hidden", !isOther).val("");

		if (hiddenField.data("field") === "native_state")
			loadDistrictSuggestions(page, hiddenField.val());
	});

	page.main.off("change", ".other-picker").on("change", ".other-picker", function () {
		const wrap = $(this).closest(".tab-group-wrap");
		const hiddenField = wrap.find("input.cad-field");
		hiddenField.val($(this).val());

		if (hiddenField.data("field") === "native_state")
			loadDistrictSuggestions(page, hiddenField.val());
	});

	page.main
		.off("click", ".cad-register-submit")
		.on("click", ".cad-register-submit", () => submitRegistration(page));
}

async function loadDistrictSuggestions(page, state) {
	const select = page.main.find(".district-select");
	select
		.empty()
		.append(
			'<option value="">' +
				frappe.utils.escape_html(__("-- Select District --")) +
				"</option>"
		)
		.prop("disabled", true);
	if (!state) return;

	const response = await frappe.call({
		method: "bandhu_app.bandhu_app.utils.state_districts.get_districts",
		args: { state },
	});
	const districts = (response && response.message) || [];
	select.append(
		districts
			.map(
				(district) =>
					'<option value="' +
					frappe.utils.escape_html(district) +
					'">' +
					frappe.utils.escape_html(district) +
					"</option>"
			)
			.join("")
	);
	select.prop("disabled", false);
}

function years_since(date_string) {
	// Parse the parts: Date() reads yyyy-mm-dd as UTC and shifts the day in IST.
	const parts = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date_string || "");
	if (!parts) return null;

	const [birth_year, birth_month, birth_day] = parts.slice(1).map(Number);
	const today = new Date();
	let age = today.getFullYear() - birth_year;
	const before_birthday =
		today.getMonth() + 1 < birth_month ||
		(today.getMonth() + 1 === birth_month && today.getDate() < birth_day);
	if (before_birthday) age -= 1;

	return age < 0 ? null : age;
}

async function submitRegistration(page) {
	const values = {};
	page.main.find(".cad-field").each(function () {
		values[$(this).data("field")] = $(this).val();
	});

	if (!values.full_name || !values.full_name.trim()) {
		frappe.msgprint(__("Full name is required."));
		return;
	}
	// 0 is a valid age for a newborn, so check presence, not truthiness.
	const hasAge = values.age !== undefined && values.age !== "";
	if (!values.dob && !hasAge) {
		frappe.msgprint(__("Enter the date of birth, or an approximate age if it isn't known."));
		return;
	}
	if (!values.sex) {
		frappe.msgprint(__("Please select sex."));
		return;
	}
	if (values.mobile && !/^\d{10}$/.test(values.mobile.trim())) {
		frappe.msgprint(__("Mobile number must be 10 digits."));
		return;
	}
	if (values.height_cm && flt(values.height_cm) < 0) {
		frappe.msgprint(__("Height cannot be negative."));
		return;
	}
	if (values.weight_kg && flt(values.weight_kg) < 0) {
		frappe.msgprint(__("Weight cannot be negative."));
		return;
	}

	const args = {
		full_name: values.full_name.trim(),
		sex: values.sex,
		session: cadSession.session_name,
	};
	if (values.dob) args.dob = values.dob;
	if (hasAge) args.age = values.age;
	if (values.mobile) args.mobile = values.mobile;
	if (values.height_cm) args.height_cm = values.height_cm;
	if (values.weight_kg) args.weight_kg = values.weight_kg;
	if (values.native_country) args.native_country = values.native_country;
	if (values.specify_native_country) args.specify_native_country = values.specify_native_country;
	if (values.native_state) args.native_state = values.native_state;
	if (values.native_district) args.native_district = values.native_district;
	if (values.occupation) args.occupation = values.occupation;
	if (values.specify_sector) args.specify_sector = values.specify_sector;
	if (values.company_name) args.company_name = values.company_name;
	if (values.abha_id) args.abha_id = values.abha_id;

	const existing = await findPossibleDuplicate(args);
	if (existing && !(await confirmRegisterAnyway(page, existing))) return;

	frappe.dom.freeze();
	let patient;
	try {
		const response = await frappe.call({
			method: "bandhu_app.bandhu_app.page.cad_form.cad_form.register_patient",
			args,
		});
		patient = response.message;
	} finally {
		frappe.dom.unfreeze();
	}

	if (!patient) return;

	await addPatientToQueue(page, patient, () => {
		page.main.find(".cad-register-form").hide().html(renderRegisterForm());
		focus_scan_input(page);
	});

	// No print prompt here. The patient's row in the queue carries its own Print Card
	// button, so the card can be printed now or at any point during the visit without a
	// dialog interrupting the next registration.
	frappe.show_alert({ message: __("Patient registered."), indicator: "green" });
}

async function findPossibleDuplicate(args) {
	const response = await frappe.call({
		method: "bandhu_app.bandhu_app.page.cad_form.cad_form.find_possible_duplicate",
		args: {
			full_name: args.full_name,
			dob: args.dob,
			age: args.age,
			mobile: args.mobile,
			abha_id: args.abha_id,
		},
	});
	return response.message;
}

function confirmRegisterAnyway(page, existing) {
	return new Promise((resolve) => {
		const label = [
			existing.patient_name,
			bandhu.session_ui.group_clinic_id(existing.clinic_id),
			existing.age,
		]
			.filter(Boolean)
			.join(" · ");

		const dialog = new frappe.ui.Dialog({
			title: __("Already registered?"),
			fields: [
				{
					fieldtype: "HTML",
					options:
						"<p>" +
						__("{0} is already on the patient list, with {1}.", [
							"<b>" + frappe.utils.escape_html(label) + "</b>",
							frappe.utils.escape_html(existing.matched_on),
						]) +
						"</p><p>" +
						__(
							"Registering again gives this person a second Clinic ID and a second card."
						) +
						"</p>",
				},
			],
			primary_action_label: __("Add to queue"),
			primary_action: async () => {
				dialog.hide();
				resolve(false);
				await addPatientToQueue(page, existing.name, () => {
					page.main.find(".cad-register-form").hide().html(renderRegisterForm());
					focus_scan_input(page);
				});
			},
			secondary_action_label: __("Register as new"),
			secondary_action: () => {
				dialog.hide();
				resolve(true);
			},
		});

		dialog.$wrapper.on("hidden.bs.modal", () => resolve(false));
		dialog.show();
	});
}

async function addPatientToQueue(page, patient, onQueued) {
	frappe.dom.freeze();
	try {
		await frappe.call({
			method: "bandhu_app.bandhu_app.page.cad_form.cad_form.create_encounter",
			args: { patient, session: cadSession.session_name },
		});
	} finally {
		frappe.dom.unfreeze();
	}

	onQueued();
	await loadQueue(page);
}

async function loadQueue(page) {
	const response = await frappe.call({
		method: "bandhu_app.bandhu_app.page.cad_form.cad_form.get_today_queue",
		args: { session: cadSession.session_name },
	});
	renderQueueTable(page, response.message || []);
}

function renderQueueTable(page, rows) {
	page.main.find(".cad-queue-count").text(" (" + rows.length + ")");
	const body = page.main.find(".cad-queue-body");

	if (!rows.length) {
		body.html(
			'<tr><td colspan="5" class="queue-empty">' +
				__("No patients in queue yet.") +
				"</td></tr>"
		);
		return;
	}

	const html = rows
		.map(
			(row) =>
				"<tr>" +
				"<td>" +
				frappe.utils.escape_html(row.patient_name || "") +
				"</td>" +
				'<td class="queue-clinic-id">' +
				frappe.utils.escape_html(bandhu.session_ui.group_clinic_id(row.clinic_id)) +
				"</td>" +
				"<td>" +
				format_stage_badge(row.current_stage) +
				"</td>" +
				'<td class="queue-in-session">' +
				format_time_in_session(row) +
				"</td>" +
				'<td class="queue-row-actions">' +
				renderRowMenu(row) +
				"</td>" +
				"</tr>"
		)
		.join("");

	body.html(html);
}

// Every row carries the menu, including finished ones, so the actions column keeps a single
// shape down the table. Print Card lives in it rather than beside it: the queue is the screen
// the front desk reads, and a button on every row competed with the patient names for it.
function renderRowMenu(row) {
	const canCancel = row.encounter && !QUEUE_TERMINAL_STAGES.has(row.current_stage);
	return (
		'<div class="dropdown queue-more">' +
		'<button type="button" class="btn btn-sm btn-default queue-more-btn" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false" title="' +
		frappe.utils.escape_html(__("More actions")) +
		'">' +
		frappe.utils.icon("ellipsis", "sm", "", "", "current-color") +
		"</button>" +
		'<ul class="dropdown-menu dropdown-menu-right" role="menu">' +
		'<li><a class="dropdown-item queue-print-card" data-patient="' +
		frappe.utils.escape_html(row.patient || "") +
		'">' +
		__("Print Card") +
		"</a></li>" +
		(canCancel
			? '<li><a class="dropdown-item text-danger queue-cancel-visit" data-encounter="' +
			  frappe.utils.escape_html(row.encounter || "") +
			  '" data-patient-name="' +
			  frappe.utils.escape_html(row.patient_name || "") +
			  '">' +
			  __("Cancel Visit") +
			  "</a></li>"
			: "") +
		"</ul></div>"
	);
}

function format_time_in_session(row) {
	if (!row.queued_at || QUEUE_TERMINAL_STAGES.has(row.current_stage)) return "";

	// comment_when returns markup, so it is not escaped.
	return frappe.datetime.comment_when(row.queued_at, true);
}

// Status was a second column that only ever restated the stage (Completed reads Done, every
// other stage reads Active), so the badge carries both: colour for how the visit ended,
// wording for where the patient is.
const QUEUE_TERMINAL_STAGES = new Set(["Completed", "Cancelled"]);

const QUEUE_STAGE_BADGES = {
	Waiting: { theme: "amber", variant: "subtle" },
	"With Doctor": { theme: "blue", variant: "subtle" },
	"With Nurse (Test)": { theme: "blue", variant: "subtle" },
	"With Nurse (Medicine)": { theme: "blue", variant: "subtle" },
	Completed: { theme: "green", variant: "subtle" },
	Cancelled: { theme: "red", variant: "subtle" },
};

function format_stage_badge(stage) {
	if (!stage) return "";
	const badge = QUEUE_STAGE_BADGES[stage] || { theme: "", variant: "subtle" };
	return bandhu.session_ui.format_badge(__(stage), badge.theme, badge.variant);
}

frappe.pages["cad-form"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("CAD"),
		single_column: true,
	});

	page.set_secondary_action(
		__("My Schedule"),
		() => frappe.set_route("my-schedule"),
		"calendar"
	);

	cadPage = page;
};

// Desk keeps this page's DOM and module state alive across route changes, so the queue would
// otherwise still show the state it had when the CAD left the page. Only the queue is reloaded
// when the front desk is already up -- a full re-render would wipe a half-typed registration.
async function refreshBoard() {
	await frappe.require(SESSION_UI_ASSET);
	bandhu.session_ui.add_refresh_icon(cadPage, refreshBoard);
	const load = cadPage.main.find(".cad-queue-body").length ? loadQueue : loadDashboard;
	await bandhu.session_ui.refresh_page(cadPage, load);
	// Join the session room only after the load says which session this is.
	bandhu.session_ui.subscribe_to_board_updates(
		"cad-form",
		() => (cadSession ? cadSession.session_name : null),
		refreshBoard
	);
}

frappe.pages["cad-form"].on_page_show = refreshBoard;
