/* global bandhu */

const SESSION_UI_ASSET = "/assets/bandhu_app/js/session_ui.js";

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

// One call for the whole queue. Fetching per patient meant a 40-patient camp fired 40 parallel
// requests, saturating the browser connection pool on a weak link.
async function getPatientHistories(patients) {
	if (!patients.length) return {};
	const response = await frappe.call({
		method: "bandhu_app.bandhu_app.page.doctor_form.doctor_form.get_patient_histories",
		args: { patients },
	});
	return response.message || {};
}

async function loadDashboard(page) {
	frappe.dom.freeze();
	let status;
	try {
		const response = await frappe.call({
			method: "bandhu_app.bandhu_app.page.doctor_form.doctor_form.get_session_status",
		});
		status = response.message || {};
	} finally {
		frappe.dom.unfreeze();
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
	frappe.dom.freeze();
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
		frappe.dom.unfreeze();
	}

	encountersByName = Object.fromEntries(
		[...active, ...completed].map((encounter) => [encounter.name, encounter])
	);
	renderDashboard(page, active, completed);
}

function renderDashboard(page, active, completed) {
	const html =
		'<div class="doctor-dash">' +
		bandhu.session_ui.format_welcome() +
		(doctorSession ? bandhu.session_ui.format_session_info(doctorSession) : "") +
		renderQueue(__("Active Patients"), active) +
		renderCompletedQueue(__("Completed Today"), completed) +
		"</div>";
	page.main.html(html);

	page.main.off("click");

	// The card body is the Details affordance -- a dedicated Details button sat as a fourth
	// coequal action next to three clinical ones and wrapped the row.
	page.main.on("click", ".patient-card-body", function () {
		const encounter = $(this).closest(".patient-card").data("name");
		dispatchDoctorAction(page, encounter, "details");
	});

	page.main.on("click", ".visit-tag.repeat", function (event) {
		event.stopPropagation();
		const target = $(this).closest(".patient-card").find(".history-list");
		const indicator = $(this).find(".history-expand-indicator");
		if (target.length) {
			target.toggle();
			indicator.toggleClass("expanded");
		}
	});

	page.main.on("click", ".completed-row", function (event) {
		if ($(event.target).closest(".completed-actions").length) return;
		dispatchDoctorAction(page, $(this).data("name"), "details");
	});

	page.main.on("click", ".rail-more .open-record", function (event) {
		event.stopPropagation();
		frappe.set_route("Form", "Patient Encounter", $(this).data("name"));
	});

	page.main.on("click", ".rail-more .print-referral", function (event) {
		event.stopPropagation();
		printReferralLetter($(this).data("name"));
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
				fieldtype: "Small Text",
				fieldname: "chief_complaint",
				label: __("Chief Complaint"),
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
			{
				fieldtype: "Small Text",
				fieldname: "chief_complaint",
				label: __("Chief Complaint"),
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
				data: [],
			},
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
			{
				fieldtype: "Small Text",
				fieldname: "chief_complaint",
				label: __("Chief Complaint"),
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
			{ fieldtype: "Data", fieldname: "diagnosis", label: __("Diagnosis (optional)") },
			{
				fieldtype: "Small Text",
				fieldname: "clinical_notes",
				label: __("Clinical Notes (optional)"),
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

async function submitDoctorAction(page, method, args) {
	frappe.dom.freeze();
	try {
		await frappe.call({
			method: "bandhu_app.bandhu_app.page.doctor_form.doctor_form." + method,
			args,
		});
	} finally {
		frappe.dom.unfreeze();
	}

	frappe.show_alert({ message: __("Saved"), indicator: "green" });
	await bandhu.session_ui.refresh_page(page, loadQueues);
}

const WAITING_NOTES = {
	"Awaiting Test": __("Waiting on nurse"),
	"Awaiting Medicine": __("Waiting on pharmacy"),
	Completed: __("Seen today"),
	Cancelled: __("Cancelled"),
};

// Every card carries this rail, action or not. A band that appeared only on the cards with
// something to do put a step between neighbouring cards and broke the queue's rhythm.
function renderActionRail(encounter) {
	const actions = [];

	if (encounter.custom_workflow_state === "Waiting for Doctor") {
		actions.push(["order_test", __("Order Test"), false]);
	}
	if (
		encounter.custom_workflow_state === "Waiting for Doctor" ||
		encounter.custom_workflow_state === "Awaiting Doctor Review"
	) {
		actions.push(["prescribe", __("Prescribe Medicine"), false]);
		actions.push(["complete", __("Mark Complete"), true]);
	}

	const body = actions.length
		? actions
				.map(([action, label, is_primary]) =>
					bandhu.session_ui.format_action_button(
						"doctor-action-btn",
						encounter.name,
						action,
						label,
						is_primary
					)
				)
				.join("")
		: '<span class="rail-note">' +
		  frappe.utils.escape_html(
				WAITING_NOTES[encounter.custom_workflow_state] || __("No action yet")
		  ) +
		  "</span>";

	return (
		'<div class="patient-card-actions">' +
		'<div class="rail-primary">' +
		body +
		"</div>" +
		'<div class="rail-secondary">' +
		bandhu.session_ui.format_action_button(
			"doctor-action-btn rail-details",
			encounter.name,
			"details",
			__("Details"),
			false
		) +
		renderOverflowMenu(encounter) +
		"</div></div>"
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
		'<li><a class="dropdown-item open-record" data-name="' +
		frappe.utils.escape_html(encounter.name) +
		'">' +
		__("Open Record") +
		"</a></li>" +
		"</ul></div>"
	);
}

// Referral is System Manager only in DocType permissions, same reason cad_form.js cannot use
// /printview for the patient card — the letter comes back through this page's own gated
// endpoint instead.
async function printReferralLetter(encounter) {
	if (!encounter) return;

	frappe.dom.freeze();
	let letter_html;
	try {
		const response = await frappe.call({
			method: "bandhu_app.bandhu_app.page.doctor_form.doctor_form.get_referral_letter_html",
			args: { encounter },
		});
		letter_html = response.message;
	} finally {
		frappe.dom.unfreeze();
	}

	if (!letter_html) return;

	const letter_window = window.open("", "_blank");
	if (!letter_window) {
		frappe.msgprint(__("Allow pop-ups for this site to print the referral letter."));
		return;
	}

	letter_window.document.write(letter_html);
	letter_window.document.close();
	letter_window.focus();
	letter_window.print();
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

// What the doctor needs first is whether this patient is theirs to act on right now or is
// sitting with the nurse -- the visit count they were reading before is background.
const QUEUE_STATES = {
	"Waiting for Doctor": { label: __("Ready for doctor"), tone: "ready" },
	"Awaiting Test": { label: __("With nurse"), tone: "waiting" },
	"Awaiting Doctor Review": { label: __("Results back"), tone: "review" },
	"Awaiting Medicine": { label: __("With nurse"), tone: "waiting" },
	Completed: { label: __("Completed"), tone: "done" },
};

function renderStatusPill(encounter) {
	const state = QUEUE_STATES[encounter.custom_workflow_state] || {
		label: encounter.custom_workflow_state || __("Unknown"),
		tone: "waiting",
	};
	// Which of the two the nurse holds is already in the clinical line below; spelling it out
	// here as well wrapped the pill onto a second line in a two-up card.
	return (
		'<span class="status-pill" data-tone="' +
		state.tone +
		'"><span class="status-dot"></span>' +
		frappe.utils.escape_html(state.label) +
		"</span>"
	);
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

function renderPatientCard(encounter) {
	const identity = [encounter.patient_age, encounter.patient_sex]
		.concat(bandhu.session_ui.group_clinic_id(encounter.clinic_id) || [])
		.filter(Boolean)
		.map(frappe.utils.escape_html)
		.join(" &middot; ");

	const state = QUEUE_STATES[encounter.custom_workflow_state] || {};

	return (
		'<article class="patient-card" data-tone="' +
		(state.tone || "waiting") +
		'" data-name="' +
		frappe.utils.escape_html(encounter.name) +
		'">' +
		'<div class="patient-card-main">' +
		'<div class="patient-card-status">' +
		renderStatusPill(encounter) +
		renderVisitTag(encounter) +
		"</div>" +
		'<div class="patient-card-body">' +
		'<div class="patient-card-head">' +
		'<span class="patient-name">' +
		frappe.utils.escape_html(encounter.patient_name || "") +
		"</span>" +
		'<span class="patient-meta">' +
		identity +
		"</span>" +
		"</div>" +
		'<div class="patient-clinical">' +
		renderClinicalSummary(encounter) +
		"</div>" +
		renderHistoryList(encounter) +
		"</div></div>" +
		renderActionRail(encounter) +
		"</article>"
	);
}

// Nothing on a completed patient is actionable, so a card each is a card's worth of space for
// a line of reference. The table keeps a 40-patient camp on one screen.
function renderCompletedQueue(title, encounters) {
	const count = '<span class="queue-meta"> (' + encounters.length + ")</span>";
	const head = '<h4 class="queue-head">' + frappe.utils.escape_html(title) + count + "</h4>";

	if (!encounters.length) {
		return (
			'<div class="queue-section">' +
			head +
			'<div class="empty-state">' +
			frappe.utils.icon("inbox", "xl", "", "", "current-color empty-state-icon small") +
			'<span class="empty-state-text">' +
			__("No patients.") +
			"</span>" +
			"</div></div>"
		);
	}

	const rows = encounters
		.map(
			(encounter) =>
				'<tr class="completed-row" data-name="' +
				frappe.utils.escape_html(encounter.name) +
				'">' +
				"<td>" +
				frappe.utils.escape_html(encounter.patient_name || "") +
				"</td>" +
				"<td>" +
				frappe.utils.escape_html(
					[encounter.patient_age, encounter.patient_sex].filter(Boolean).join(" \u00b7 ")
				) +
				"</td>" +
				'<td class="completed-clinic-id">' +
				frappe.utils.escape_html(
					bandhu.session_ui.group_clinic_id(encounter.clinic_id) || ""
				) +
				"</td>" +
				'<td class="completed-summary">' +
				renderClinicalSummary(encounter) +
				"</td>" +
				'<td class="completed-actions">' +
				bandhu.session_ui.format_action_button(
					"doctor-action-btn rail-details",
					encounter.name,
					"details",
					__("Details"),
					false
				) +
				renderOverflowMenu(encounter) +
				"</td></tr>"
		)
		.join("");

	return (
		'<div class="queue-section">' +
		head +
		'<div class="table-wrap"><table class="table"><thead><tr>' +
		"<th>" +
		__("Patient") +
		"</th><th>" +
		__("Age / Sex") +
		"</th><th>" +
		__("Clinic ID") +
		"</th><th>" +
		__("Seen for") +
		"</th><th></th>" +
		"</tr></thead><tbody>" +
		rows +
		"</tbody></table></div></div>"
	);
}

function renderQueue(title, encounters) {
	const count = '<span class="queue-meta"> (' + encounters.length + ")</span>";
	const head = '<h4 class="queue-head">' + frappe.utils.escape_html(title) + count + "</h4>";

	if (!encounters.length) {
		return (
			'<div class="queue-section">' +
			head +
			'<div class="empty-state">' +
			frappe.utils.icon("inbox", "xl", "", "", "current-color empty-state-icon small") +
			'<span class="empty-state-text">' +
			__("No patients.") +
			"</span>" +
			"</div></div>"
		);
	}

	return (
		'<div class="queue-section">' +
		head +
		'<div class="patient-cards">' +
		encounters.map(renderPatientCard).join("") +
		"</div></div>"
	);
}

frappe.pages["doctor-form"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Doctor"),
		single_column: true,
	});

	page.set_secondary_action(__("Refresh"), refreshDashboard);
	page.set_primary_action(__("My Schedule"), () => frappe.set_route("my-schedule"), "calendar");

	doctorPage = page;
};

async function refreshDashboard() {
	await frappe.require(SESSION_UI_ASSET);
	await bandhu.session_ui.refresh_page(doctorPage, loadDashboard);
}

// Desk keeps this page's DOM and module state alive, so returning from a Patient Encounter would
// otherwise show the queue exactly as it was before the encounter was edited -- a doctor could
// prescribe again for a patient they had just completed. on_page_show also fires on the very first
// show (frappe/public/js/frappe/views/pageview.js:104-107), so it is the only loader needed.
frappe.pages["doctor-form"].on_page_show = refreshDashboard;
