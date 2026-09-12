/* global bandhu */

const SESSION_UI_ASSET = "/assets/bandhu_app/js/session_ui.js";
const MAX_PATIENTS_WITH_DOCTOR = 3;

let encountersByName = {};
let testOptions = null;
let doctorSession = null;
let doctorPage = null;

function chiefComplaintOf(encounter) {
	return (encountersByName[encounter] || {}).custom_chief_complaints || "";
}

function pastHistoryOf(encounter) {
	return (encountersByName[encounter] || {}).custom_past_history || "";
}

function allergyHistoryOf(encounter) {
	return (encountersByName[encounter] || {}).custom_allergy_history || "";
}

async function getPatientHistories(patients) {
	if (!patients.length) return {};
	const response = await frappe.call({
		method: "bandhu_app.bandhu_app.page.doctor_form.doctor_form.get_patient_histories",
		args: { patients },
	});
	return response.message || {};
}

async function loadDashboard(page) {
	bandhu.session_ui.freeze();
	let status;
	try {
		const response = await frappe.call({
			method: "bandhu_app.bandhu_app.page.doctor_form.doctor_form.get_session_status",
		});
		status = response.message || {};
	} finally {
		bandhu.session_ui.unfreeze();
	}

	if (!status.has_session) {
		doctorSession = null;
		const upcoming = await bandhu.session_ui.get_upcoming_sessions(
			"bandhu_app.bandhu_app.page.doctor_form.doctor_form.get_upcoming_sessions"
		);
		renderNoSession(page, status.message, upcoming);
		return;
	}

	doctorSession = status;
	await loadQueues(page);
}

function renderNoSession(page, message, upcoming) {
	page.main.html(
		'<div class="doctor-dash">' +
			bandhu.session_ui.format_welcome() +
			'<div class="empty-state">' +
			frappe.utils.icon("calendar-off", "xl", "", "", "current-color empty-state-icon") +
			'<span class="empty-state-text">' +
			frappe.utils.escape_html(message || __("No session available.")) +
			"</span></div>" +
			bandhu.session_ui.format_upcoming_sessions(upcoming) +
			"</div>"
	);
}

async function loadQueues(page) {
	bandhu.session_ui.freeze();
	let active, completed;
	try {
		const [activeResult, completedResult] = await Promise.all([
			frappe.call({
				method: "bandhu_app.bandhu_app.page.doctor_form.doctor_form.get_registered_patients",
			}),
			frappe.call({
				method: "bandhu_app.bandhu_app.page.doctor_form.doctor_form.get_completed_patients",
			}),
		]);
		active = activeResult.message || [];
		completed = completedResult.message || [];

		const patients = [
			...new Set(
				[...active, ...completed].map((encounter) => encounter.patient).filter(Boolean)
			),
		];
		const historyByPatient = await getPatientHistories(patients);

		active = active.map((encounter) => ({
			...encounter,
			history: historyByPatient[encounter.patient] || [],
		}));
		completed = completed.map((encounter) => ({
			...encounter,
			history: historyByPatient[encounter.patient] || [],
		}));
	} finally {
		bandhu.session_ui.unfreeze();
	}

	encountersByName = Object.fromEntries(
		[...active, ...completed].map((encounter) => [encounter.name, encounter])
	);
	renderDashboard(page, active, completed);
}

function splitQueues(active) {
	const inRoom = active
		.filter((encounter) => encounter.custom_called_at)
		.sort((one, other) => (one.custom_called_at < other.custom_called_at ? -1 : 1));
	const waiting = active.filter((encounter) => !encounter.custom_called_at);

	waiting.sort((one, other) => {
		const rank = (encounter) => WAITING_ORDER[encounter.custom_workflow_state] ?? 3;
		return rank(one) - rank(other) || (one.creation < other.creation ? -1 : 1);
	});

	return { inRoom, waiting };
}

function renderDashboard(page, active, completed) {
	const { inRoom, waiting } = splitQueues(active);

	page.main.html(
		'<div class="doctor-dash">' +
			bandhu.session_ui.format_welcome() +
			(doctorSession ? bandhu.session_ui.format_session_info(doctorSession) : "") +
			renderFilterBar(active.length + completed.length) +
			renderRoomSection(inRoom, waiting) +
			renderWaitingSection(waiting) +
			renderDoneSection(completed) +
			"</div>"
	);

	page.main.off("click");

	page.main.on("input", ".queue-filter-input", () => applyQueueFilter(page));

	page.main.on("click", ".call-patient", function (event) {
		event.stopPropagation();
		callPatient(page, $(this).data("encounter"));
	});

	page.main.on("click", ".release-patient", function (event) {
		event.stopPropagation();
		releasePatient(page, $(this).data("encounter"));
	});

	page.main.on("click", ".visit-tag.repeat", function (event) {
		event.stopPropagation();
		const target = $(this).closest(".room-card").find(".history-list");
		const indicator = $(this).find(".history-expand-indicator");
		if (target.length) {
			target.toggle();
			indicator.toggleClass("expanded");
		}
	});

	page.main.on("click", ".queue-row .row-name", function () {
		dispatchDoctorAction(page, $(this).closest(".queue-row").data("name"), "details");
	});

	page.main.on("click", ".rail-more .print-referral", function (event) {
		event.stopPropagation();
		printReferralLetter($(this).data("name"));
	});

	page.main.on("click", ".rail-more .print-card", function (event) {
		event.stopPropagation();
		printPatientCard($(this).data("name"));
	});

	page.main.on("click", ".history-list a", function (event) {
		event.stopPropagation();
		frappe.set_route("Form", "Patient Encounter", $(this).data("name"));
	});

	page.main.on("click", ".doctor-action-btn", function (event) {
		event.stopPropagation();
		const encounter = $(this).data("encounter");
		const action = $(this).data("action");
		dispatchDoctorAction(page, encounter, action);
	});
}

async function callPatient(page, encounter) {
	await submitDoctorAction(page, "call_patient", { encounter }, "");
}

async function releasePatient(page, encounter) {
	await submitDoctorAction(page, "release_patient", { encounter }, "");
}

async function dispatchDoctorAction(page, encounter, action) {
	switch (action) {
		case "details":
			bandhu.session_ui.open_patient_details_dialog(
				"bandhu_app.bandhu_app.page.doctor_form.doctor_form.get_patient_registration_details",
				encounter,
				encountersByName[encounter] || {}
			);
			break;
		case "order_test":
			await openOrderTestDialog(page, encounter);
			break;
		case "prescribe":
			openPrescribeDialog(page, encounter);
			break;
		case "complete":
			openCompleteDialog(page, encounter);
			break;
	}
}

// The clinic's test list is a master, so the checkboxes cannot be a constant. Fetched once
// per page load rather than per dialog — it changes when an admin edits the master, not
// between two patients.
async function getTestOptions() {
	if (!testOptions) {
		const response = await frappe.call({
			method: "bandhu_app.bandhu_app.page.doctor_form.doctor_form.get_test_options",
		});
		testOptions = (response.message || []).map((test) => ({
			label: test.label,
			value: test.name,
		}));
	}
	return testOptions;
}

function historyFields(encounter) {
	return [
		{ fieldtype: "Section Break", label: __("History"), collapsible: 1 },
		{
			fieldtype: "Small Text",
			fieldname: "chief_complaint",
			label: __("Patient Complaints"),
			default: chiefComplaintOf(encounter),
		},
		{
			fieldtype: "Small Text",
			fieldname: "past_history",
			label: __("Past History"),
			default: pastHistoryOf(encounter),
		},
		{
			fieldtype: "Small Text",
			fieldname: "allergy_history",
			label: __("Allergy History"),
			default: allergyHistoryOf(encounter),
		},
	];
}

function allergyWarningFields(encounter) {
	const allergy = allergyHistoryOf(encounter);
	if (!allergy) return [];

	return [
		{
			fieldtype: "HTML",
			options:
				'<div class="bandhu-allergy">' +
				frappe.utils.icon("triangle-alert", "sm", "", "", "current-color") +
				"<span><b>" +
				__("Allergy") +
				"</b> " +
				frappe.utils.escape_html(allergy) +
				"</span></div>",
		},
	];
}

async function openOrderTestDialog(page, encounter) {
	const options = await getTestOptions();
	if (!options.length) {
		frappe.msgprint(__("No tests are configured. Ask an administrator to add one."));
		return;
	}

	const dialog = new frappe.ui.Dialog({
		title: __("Order Tests"),
		fields: [
			{
				fieldtype: "MultiCheck",
				fieldname: "tests",
				label: __("Tests"),
				options,
				// The master's display_order is the clinic's chosen order; MultiCheck
				// re-sorts alphabetically unless told not to.
				sort_options: false,
				columns: 2,
			},
			{ fieldtype: "Small Text", fieldname: "notes", label: __("Instructions for Nurse") },
			...historyFields(encounter),
		],
		primary_action_label: __("Order Tests"),
		primary_action: async (values) => {
			if (!values.tests || !values.tests.length) {
				frappe.msgprint(__("Select at least one test."));
				return;
			}
			dialog.hide();
			await submitDoctorAction(page, "order_test", {
				encounter,
				tests: values.tests,
				notes: values.notes,
				chief_complaint: values.chief_complaint,
				past_history: values.past_history,
				allergy_history: values.allergy_history,
			});
		},
	});
	dialog.show();
}

function openPrescribeDialog(page, encounter) {
	const dialog = new frappe.ui.Dialog({
		title: __("Prescribe Medicine"),
		size: "large",
		fields: [
			...allergyWarningFields(encounter),
			{
				fieldtype: "Table",
				fieldname: "prescriptions",
				label: __("Medicines"),
				cannot_add_rows: false,
				in_place_edit: false,
				reqd: 1,
				fields: [
					{
						fieldtype: "Link",
						fieldname: "medicines",
						options: "Item",
						label: __("Medicine"),
						in_list_view: 1,
						reqd: 1,
						get_query: () => ({ filters: { item_group: "Drug" } }),
					},
					{
						fieldtype: "Select",
						fieldname: "dosage_frequency",
						label: __("Frequency"),
						options: "\nOD\nBD\nTID\nQID",
						in_list_view: 1,
					},
					{
						fieldtype: "Int",
						fieldname: "duration_days",
						label: __("Days"),
						in_list_view: 1,
					},
					{ fieldtype: "Int", fieldname: "quantity", label: __("Qty"), in_list_view: 1 },
					{
						fieldtype: "Small Text",
						fieldname: "instructions",
						label: __("Instructions"),
					},
				],
				data: [{}],
			},
			...historyFields(encounter),
		],
		primary_action_label: __("Prescribe"),
		primary_action: async (values) => {
			const rows = (values.prescriptions || []).filter((row) => row.medicines);
			if (!rows.length) {
				frappe.msgprint(__("Add at least one medicine."));
				return;
			}
			dialog.hide();
			await submitDoctorAction(page, "prescribe_medicine", {
				encounter,
				prescriptions: rows,
				chief_complaint: values.chief_complaint,
				past_history: values.past_history,
				allergy_history: values.allergy_history,
			});
		},
	});
	dialog.show();
}

function openCompleteDialog(page, encounter) {
	const dialog = new frappe.ui.Dialog({
		title: __("Mark Complete"),
		fields: [
			{ fieldtype: "Data", fieldname: "diagnosis", label: __("Diagnosis (optional)") },
			{
				fieldtype: "Small Text",
				fieldname: "clinical_notes",
				label: __("Observations and Notes on Examination"),
			},
			{ fieldtype: "Section Break" },
			{ fieldtype: "Check", fieldname: "refer_patient", label: __("Refer this patient") },
			{
				fieldtype: "Data",
				fieldname: "referred_to",
				label: __("Referred To"),
				depends_on: "eval:doc.refer_patient",
				mandatory_depends_on: "eval:doc.refer_patient",
			},
			{
				fieldtype: "Link",
				fieldname: "referred_to_practitioner",
				options: "Healthcare Practitioner",
				label: __("Referred Practitioner (optional)"),
				depends_on: "eval:doc.refer_patient",
			},
			{
				fieldtype: "Select",
				fieldname: "referral_priority",
				label: __("Priority"),
				options: "Low\nMedium\nHigh",
				default: "Medium",
				depends_on: "eval:doc.refer_patient",
			},
			{
				fieldtype: "Small Text",
				fieldname: "referral_reason",
				label: __("Referral Reason"),
				depends_on: "eval:doc.refer_patient",
				mandatory_depends_on: "eval:doc.refer_patient",
			},
			...historyFields(encounter),
		],
		primary_action_label: __("Mark Complete"),
		primary_action: async (values) => {
			if (values.refer_patient && (!values.referred_to || !values.referral_reason)) {
				frappe.msgprint(__("A referral needs both where the patient is going and why."));
				return;
			}
			dialog.hide();
			await submitDoctorAction(page, "complete_encounter", {
				encounter,
				diagnosis: values.diagnosis,
				clinical_notes: values.clinical_notes,
				chief_complaint: values.chief_complaint,
				past_history: values.past_history,
				allergy_history: values.allergy_history,
				referred_to: values.refer_patient ? values.referred_to : null,
				referred_to_practitioner: values.refer_patient
					? values.referred_to_practitioner
					: null,
				referral_reason: values.refer_patient ? values.referral_reason : null,
				referral_priority: values.refer_patient ? values.referral_priority : null,
			});
		},
	});
	dialog.show();
}

async function submitDoctorAction(page, method, args, alertMessage = __("Saved")) {
	frappe.dom.freeze();
	try {
		await frappe.call({
			method: "bandhu_app.bandhu_app.page.doctor_form.doctor_form." + method,
			args,
		});
	} finally {
		frappe.dom.unfreeze();
	}

	if (alertMessage) {
		frappe.show_alert({ message: alertMessage, indicator: "green" });
	}
	await bandhu.session_ui.refresh_page(page, loadQueues);
}

const WAITING_ORDER = {
	"Awaiting Doctor Review": 0,
	"Waiting for Doctor": 1,
	"Awaiting Test": 2,
	"Awaiting Medicine": 2,
};

const WAITING_NOTES = {
	"Awaiting Test": __("with nurse"),
	"Awaiting Medicine": __("at pharmacy"),
	"Awaiting Doctor Review": __("back from nurse"),
};

function renderRoomActions(encounter) {
	const buttons = [];

	if (encounter.custom_workflow_state === "Waiting for Doctor") {
		buttons.push(
			bandhu.session_ui.format_action_button(
				"doctor-action-btn",
				encounter.name,
				"order_test",
				__("Order Test"),
				false
			)
		);
	}

	buttons.push(
		bandhu.session_ui.format_action_button(
			"doctor-action-btn",
			encounter.name,
			"prescribe",
			__("Prescribe Medicine"),
			false
		)
	);

	return (
		'<div class="room-actions">' +
		buttons.join("") +
		'<span class="room-actions-gap"></span>' +
		bandhu.session_ui.format_action_button(
			"doctor-action-btn room-details",
			encounter.name,
			"details",
			__("Details"),
			false
		) +
		renderOverflowMenu(encounter) +
		bandhu.session_ui.format_action_button(
			"doctor-action-btn room-complete",
			encounter.name,
			"complete",
			__("Mark Complete"),
			false
		) +
		"</div>"
	);
}

function renderOverflowMenu(encounter) {
	return (
		'<div class="dropdown rail-more">' +
		'<button type="button" class="btn btn-sm btn-default rail-more-btn" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false" title="' +
		frappe.utils.escape_html(__("More")) +
		'">' +
		frappe.utils.icon("ellipsis", "sm", "", "", "current-color") +
		"</button>" +
		'<ul class="dropdown-menu dropdown-menu-right" role="menu">' +
		(encounter.custom_has_referral
			? '<li><a class="dropdown-item print-referral" data-name="' +
			  frappe.utils.escape_html(encounter.name) +
			  '">' +
			  __("Print Referral Letter") +
			  "</a></li>"
			: "") +
		'<li><a class="dropdown-item print-card" data-name="' +
		frappe.utils.escape_html(encounter.name) +
		'">' +
		__("Print Patient Card") +
		"</a></li>" +
		"</ul></div>"
	);
}

async function printPatientCard(encounter) {
	await printThroughEndpoint(
		"get_patient_card_html",
		encounter,
		__("Allow pop-ups for this site to print the patient card.")
	);
}

// Referral is System Manager only, so the letter comes from a gated endpoint, not /printview.
async function printReferralLetter(encounter) {
	await printThroughEndpoint(
		"get_referral_letter_html",
		encounter,
		__("Allow pop-ups for this site to print the referral letter.")
	);
}

async function printThroughEndpoint(method, encounter, popup_blocked_message) {
	if (!encounter) return;

	frappe.dom.freeze();
	let printable_html;
	try {
		const response = await frappe.call({
			method: "bandhu_app.bandhu_app.page.doctor_form.doctor_form." + method,
			args: { encounter },
		});
		printable_html = response.message;
	} finally {
		frappe.dom.unfreeze();
	}

	if (!printable_html) return;

	const print_window = window.open("", "_blank");
	if (!print_window) {
		frappe.msgprint(popup_blocked_message);
		return;
	}

	print_window.document.write(printable_html);
	print_window.document.close();
	print_window.focus();
	print_window.print();
}

function formatTestLine(tests) {
	const pending = tests.filter((test) => !test.result_type);
	const done = tests.filter((test) => test.result_type);
	const parts = [];

	if (done.length) {
		parts.push(
			done
				.map((test) =>
					test.result_type === "Value"
						? test.test_name + " " + (test.result_value || "")
						: test.test_name + " " + test.result_type
				)
				.join(", ")
		);
	}
	if (pending.length) {
		parts.push(__("awaiting") + " " + pending.map((test) => test.test_name).join(", "));
	}

	return parts.join(" \u00b7 ");
}

// A doctor reads what was ordered and what came back, not how many rows a child table holds --
// "2 test(s) done" says nothing they can act on.
function renderClinicalSummary(encounter) {
	const tests = encounter.tests || [];
	const prescriptions = encounter.prescriptions || [];
	const lines = [];

	if (tests.length) {
		lines.push(__("Tests") + ": " + formatTestLine(tests));
	}
	if (prescriptions.length) {
		const dispensed = prescriptions.filter((prescription) => prescription.dispensed).length;
		const medicines = prescriptions
			.map((prescription) => prescription.medicines)
			.filter(Boolean)
			.join(", ");
		lines.push(
			__("Rx") +
				": " +
				medicines +
				(dispensed === prescriptions.length
					? " \u00b7 " + __("dispensed")
					: " \u00b7 " + __("awaiting pharmacy"))
		);
	}

	if (!lines.length) {
		// On a completed patient an empty summary is a fact, not something still owed.
		return encounter.custom_workflow_state === "Completed"
			? '<span class="muted">' + __("No tests or medicines") + "</span>"
			: '<span class="pending">' + __("Nothing recorded yet") + "</span>";
	}

	return lines.map(frappe.utils.escape_html).join("<br>");
}

function renderVisitTag(encounter) {
	const visitCount = encounter.history.length;
	if (visitCount <= 1) return '<span class="visit-tag">' + __("First visit") + "</span>";

	return (
		'<span class="visit-tag repeat" data-patient="' +
		frappe.utils.escape_html(encounter.patient) +
		'">' +
		__("Repeat") +
		" &times; " +
		visitCount +
		'<span class="history-expand-indicator">' +
		frappe.utils.icon("chevron-down", "xs", "", "", "current-color") +
		"</span></span>"
	);
}

function renderHistoryList(encounter) {
	if (encounter.history.length <= 1) return "";

	const items = encounter.history
		.map((visit) => {
			const visitDate = frappe.datetime.str_to_user(visit.encounter_date);
			return (
				"<li><a data-name='" +
				frappe.utils.escape_html(visit.name) +
				"'>" +
				frappe.utils.escape_html(visitDate) +
				"</a></li>"
			);
		})
		.join("");

	return '<ul class="history-list">' + items + "</ul>";
}

const FILTER_BAR_MIN_PATIENTS = 8;

function renderFilterBar(patientCount) {
	if (patientCount < FILTER_BAR_MIN_PATIENTS) return "";

	return (
		'<div class="queue-filter">' +
		frappe.utils.icon("search", "sm", "", "", "current-color queue-filter-icon") +
		'<input type="text" class="form-control queue-filter-input" placeholder="' +
		frappe.utils.escape_html(__("Find a patient by name or Clinic ID")) +
		'">' +
		"</div>"
	);
}

function applyQueueFilter(page) {
	const term = (page.main.find(".queue-filter-input").val() || "").trim().toLowerCase();

	page.main.find(".queue-section").each(function () {
		const section = $(this);
		if (!section.find(".queue-row").length) return;

		let shown = 0;

		section.find(".queue-row").each(function () {
			const matches = !term || ($(this).data("search") || "").indexOf(term) !== -1;
			$(this).toggle(matches);
			if (matches) shown += 1;
		});

		const count = section.find(".section-count");
		const total = count.data("total") ?? count.text();
		count.data("total", total);
		count.text(term ? __("{0} of {1}", [shown, total]) : total);
	});
}

function renderSectionHead(title, count, trailing) {
	return (
		'<h4 class="section-head">' +
		frappe.utils.escape_html(title) +
		(count === undefined ? "" : '<span class="section-count">' + count + "</span>") +
		(trailing || "") +
		"</h4>"
	);
}

function searchKey(encounter) {
	return [encounter.patient_name, encounter.clinic_id].filter(Boolean).join(" ").toLowerCase();
}

function renderIdentity(encounter) {
	return [encounter.patient_age, encounter.patient_sex]
		.filter(Boolean)
		.map(frappe.utils.escape_html)
		.concat(
			encounter.clinic_id
				? '<span class="clinic-id">' +
						frappe.utils.escape_html(
							bandhu.session_ui.group_clinic_id(encounter.clinic_id)
						) +
						"</span>"
				: []
		)
		.join(" &middot; ");
}

function renderRoomSection(inRoom, waiting) {
	return (
		'<div class="queue-section">' +
		renderSectionHead(__("With you"), inRoom.length || undefined) +
		(inRoom.length
			? '<div class="room-cards">' + inRoom.map(renderRoomCard).join("") + "</div>"
			: "") +
		renderCallStrip(inRoom, waiting) +
		"</div>"
	);
}

function renderCallStrip(inRoom, waiting) {
	const callable = waiting.filter(isCallable);
	const full = inRoom.length >= MAX_PATIENTS_WITH_DOCTOR;

	if (!callable.length && inRoom.length) return "";

	const line = !callable.length
		? __("Nobody is waiting for you.")
		: full
		? __("{0} more waiting. Finish one before calling another.", [callable.length])
		: inRoom.length
		? __("{0} more waiting.", [callable.length])
		: __("Nobody is with you. {0} waiting.", [callable.length]);

	return (
		'<div class="call-strip' +
		(inRoom.length ? " is-slim" : "") +
		'">' +
		'<span class="call-strip-text">' +
		frappe.utils.escape_html(line) +
		"</span>" +
		(callable.length && !full
			? '<button type="button" class="btn btn-primary call-patient" data-encounter="' +
			  frappe.utils.escape_html(callable[0].name) +
			  '">' +
			  __("Call next patient") +
			  "</button>"
			: "") +
		"</div>"
	);
}

function renderRoomCard(encounter) {
	return (
		'<article class="room-card" data-name="' +
		frappe.utils.escape_html(encounter.name) +
		'">' +
		'<div class="room-head">' +
		'<span class="room-name">' +
		frappe.utils.escape_html(encounter.patient_name || "") +
		"</span>" +
		'<span class="room-identity">' +
		renderIdentity(encounter) +
		"</span>" +
		renderVisitTag(encounter) +
		'<button type="button" class="btn btn-sm btn-default release-patient" title="' +
		frappe.utils.escape_html(__("Back to waiting")) +
		'" aria-label="' +
		frappe.utils.escape_html(__("Back to waiting")) +
		'" data-encounter="' +
		frappe.utils.escape_html(encounter.name) +
		'">' +
		frappe.utils.icon("undo-2", "sm", "", "", "current-color") +
		"</button>" +
		"</div>" +
		'<div class="room-body">' +
		'<div class="room-clinical">' +
		renderClinicalSummary(encounter) +
		"</div>" +
		renderAllergy(encounter) +
		renderComplaint(encounter) +
		renderHistoryList(encounter) +
		"</div>" +
		renderRoomActions(encounter) +
		"</article>"
	);
}

function renderAllergy(encounter) {
	if (!encounter.custom_allergy_history) return "";

	return (
		'<div class="bandhu-allergy">' +
		frappe.utils.icon("triangle-alert", "sm", "", "", "current-color") +
		"<span><b>" +
		__("Allergy") +
		"</b> " +
		frappe.utils.escape_html(encounter.custom_allergy_history) +
		"</span></div>"
	);
}

function renderComplaint(encounter) {
	if (!encounter.custom_chief_complaints) return "";

	return (
		'<div class="room-complaint">' +
		'<span class="room-complaint-label">' +
		__("Complaint") +
		"</span>" +
		frappe.utils.escape_html(encounter.custom_chief_complaints) +
		"</div>"
	);
}

function isCallable(encounter) {
	return (
		encounter.custom_workflow_state === "Waiting for Doctor" ||
		encounter.custom_workflow_state === "Awaiting Doctor Review"
	);
}

function renderWaitingSection(encounters) {
	return (
		'<div class="queue-section">' +
		renderSectionHead(__("Waiting"), encounters.length) +
		(encounters.length
			? '<div class="queue-rows">' + encounters.map(renderWaitingRow).join("") + "</div>"
			: renderEmptyList(__("Nobody is waiting."))) +
		"</div>"
	);
}

function renderWaitingRow(encounter) {
	const note =
		WAITING_NOTES[encounter.custom_workflow_state] ||
		(isCallable(encounter) ? "" : encounter.custom_workflow_state || __("no state"));
	const back = encounter.custom_workflow_state === "Awaiting Doctor Review";

	return (
		'<div class="queue-row' +
		(back ? " is-back" : "") +
		'" data-name="' +
		frappe.utils.escape_html(encounter.name) +
		'" data-search="' +
		frappe.utils.escape_html(searchKey(encounter)) +
		'">' +
		'<span class="row-name">' +
		'<span class="row-head">' +
		'<span class="row-patient">' +
		frappe.utils.escape_html(encounter.patient_name || "") +
		"</span>" +
		'<span class="row-identity">' +
		renderIdentity(encounter) +
		"</span></span>" +
		'<span class="row-clinical">' +
		renderClinicalSummary(encounter) +
		"</span>" +
		"</span>" +
		'<span class="row-right">' +
		(note
			? '<span class="row-note' +
			  (back ? " is-back" : "") +
			  '">' +
			  frappe.utils.escape_html(note) +
			  "</span>"
			: "") +
		'<span class="row-waited">' +
		__("waiting {0}", [frappe.datetime.comment_when(encounter.creation, true)]) +
		"</span>" +
		(isCallable(encounter)
			? '<button type="button" class="btn btn-sm btn-default call-patient" data-encounter="' +
			  frappe.utils.escape_html(encounter.name) +
			  '">' +
			  __("Call") +
			  "</button>"
			: "") +
		"</span></div>"
	);
}

function renderDoneSection(encounters) {
	return (
		'<div class="queue-section is-done">' +
		renderSectionHead(__("Done today"), encounters.length) +
		(encounters.length
			? '<div class="queue-rows">' + encounters.map(renderDoneRow).join("") + "</div>"
			: renderEmptyList(__("Nobody finished yet."))) +
		"</div>"
	);
}

function renderDoneRow(encounter) {
	return (
		'<div class="queue-row" data-name="' +
		frappe.utils.escape_html(encounter.name) +
		'" data-search="' +
		frappe.utils.escape_html(searchKey(encounter)) +
		'">' +
		'<span class="row-name">' +
		'<span class="row-head">' +
		'<span class="row-patient">' +
		frappe.utils.escape_html(encounter.patient_name || "") +
		"</span>" +
		'<span class="row-identity">' +
		renderIdentity(encounter) +
		"</span></span>" +
		'<span class="row-clinical">' +
		renderClinicalSummary(encounter) +
		"</span>" +
		"</span>" +
		'<span class="row-right">' +
		renderOverflowMenu(encounter) +
		"</span></div>"
	);
}

function renderEmptyList(message) {
	return '<div class="queue-empty">' + frappe.utils.escape_html(message) + "</div>";
}

frappe.pages["doctor-form"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Doctor"),
		single_column: true,
	});

	page.set_secondary_action(
		__("My Schedule"),
		() => frappe.set_route("my-schedule"),
		"calendar"
	);

	doctorPage = page;
};

async function refreshDashboard() {
	await frappe.require(SESSION_UI_ASSET);
	bandhu.session_ui.add_refresh_icon(doctorPage, refreshDashboard);
	await bandhu.session_ui.refresh_page(doctorPage, loadDashboard);
	// Join the session room only after the load says which session this is.
	bandhu.session_ui.subscribe_to_board_updates(
		"doctor-form",
		() => (doctorSession ? doctorSession.session_name : null),
		refreshDashboard
	);
}

// Desk keeps this page's DOM and module state alive, so returning from a Patient Encounter would
// otherwise show the queue exactly as it was before the encounter was edited -- a doctor could
// prescribe again for a patient they had just completed. on_page_show also fires on the very first
// show (frappe/public/js/frappe/views/pageview.js:104-107), so it is the only loader needed.
frappe.pages["doctor-form"].on_page_show = refreshDashboard;
