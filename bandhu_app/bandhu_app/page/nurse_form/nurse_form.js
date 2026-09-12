/* global bandhu */

const SESSION_UI_ASSET = "/assets/bandhu_app/js/session_ui.js";

let nurseSession = null;
let encountersByName = {};
let nursePage = null;

async function loadDashboard(page) {
	bandhu.session_ui.freeze();
	let data;
	try {
		const response = await frappe.call({
			method: "bandhu_app.bandhu_app.page.nurse_form.nurse_form.get_session_status",
		});
		data = response.message || {};
	} finally {
		bandhu.session_ui.unfreeze();
	}

	if (!data.has_session) {
		const upcoming = await bandhu.session_ui.get_upcoming_sessions(
			"bandhu_app.bandhu_app.page.nurse_form.nurse_form.get_upcoming_sessions"
		);
		page.main.html(
			'<div class="nurse-dash">' +
				bandhu.session_ui.format_welcome() +
				'<div class="empty-state">' +
				frappe.utils.icon("calendar-off", "xl", "", "", "current-color empty-state-icon") +
				'<span class="empty-state-text">' +
				frappe.utils.escape_html(data.message) +
				"</span></div>" +
				bandhu.session_ui.format_upcoming_sessions(upcoming) +
				"</div>"
		);
		return;
	}

	nurseSession = data;

	if (data.status === "Planned") {
		page.main.html(
			'<div class="nurse-dash">' +
				bandhu.session_ui.format_welcome() +
				bandhu.session_ui.format_session_info(data) +
				'<div class="start-session-bar">' +
				'<button class="btn btn-primary btn-lg nurse-start-session">' +
				frappe.utils.icon("circle-play", "xs", "", "", "current-color") +
				__("Start Session") +
				"</button></div></div>"
		);

		page.main.off("click").on("click", ".nurse-start-session", () => startSession(page));
	} else if (data.status === "In Progress") {
		await loadQueues(page);
	} else if (data.status === "Completed") {
		page.main.html(
			'<div class="nurse-dash">' +
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
				__("Session completed. Great work!") +
				"</span></div></div>"
		);
	}
}

async function startSession(page) {
	frappe.dom.freeze();
	try {
		await frappe.call({
			method: "bandhu_app.bandhu_app.page.nurse_form.nurse_form.start_session",
			args: { session_name: nurseSession.session_name },
		});
	} finally {
		frappe.dom.unfreeze();
	}

	frappe.show_alert({ message: __("Session started"), indicator: "green" });
	await loadDashboard(page);
}

function endSession(page) {
	frappe.confirm(__("End the current session?"), async () => {
		frappe.dom.freeze();
		try {
			await frappe.call({
				method: "bandhu_app.bandhu_app.page.nurse_form.nurse_form.end_session",
				args: { session_name: nurseSession.session_name },
			});
		} finally {
			frappe.dom.unfreeze();
		}

		frappe.show_alert({ message: __("Session ended"), indicator: "green" });
		await loadDashboard(page);
	});
}

async function loadQueues(page) {
	bandhu.session_ui.freeze();
	const sessionName = nurseSession.session_name;
	let tests, medicines, completed, progressCounts;
	try {
		[tests, medicines, completed, progressCounts] = await Promise.all([
			frappe.call({
				method: "bandhu_app.bandhu_app.page.nurse_form.nurse_form.get_patients_for_tests",
				args: { session_name: sessionName },
			}),
			frappe.call({
				method: "bandhu_app.bandhu_app.page.nurse_form.nurse_form.get_patients_for_medicines",
				args: { session_name: sessionName },
			}),
			frappe.call({
				method: "bandhu_app.bandhu_app.page.nurse_form.nurse_form.get_completed_patients",
				args: { session_name: sessionName },
			}),
			frappe.call({
				method: "bandhu_app.bandhu_app.page.nurse_form.nurse_form.get_session_progress",
				args: { session_name: sessionName },
			}),
		]);
	} finally {
		bandhu.session_ui.unfreeze();
	}

	const testRows = tests.message || [];
	const medicineRows = medicines.message || [];
	const completedRows = completed.message || [];
	const progress = progressCounts.message || {};
	encountersByName = Object.fromEntries(
		[...testRows, ...medicineRows, ...completedRows].map((encounter) => [
			encounter.name,
			encounter,
		])
	);

	page.main.html(
		'<div class="nurse-dash">' +
			bandhu.session_ui.format_welcome() +
			bandhu.session_ui.format_session_info(nurseSession) +
			renderSessionProgress(progress) +
			renderEndSessionButton() +
			renderQueueSection(__("Patients for Tests"), testRows, "test") +
			renderQueueSection(__("Patients for Medicines"), medicineRows, "medicine") +
			renderQueueSection(__("Completed Patients"), completedRows, null) +
			"</div>"
	);

	page.main.off("click");

	page.main.on("click", ".nurse-end-session", () => endSession(page));

	page.main.on("click", ".nurse-queue-row", function () {
		frappe.set_route("Form", "Patient Encounter", $(this).data("name"));
	});

	page.main.on("click", ".nurse-action-btn", function (event) {
		event.stopPropagation();
		const encounter = $(this).data("encounter");
		const action = $(this).data("action");
		dispatchNurseAction(page, encounter, action);
	});
}

function dispatchNurseAction(page, encounter, action) {
	switch (action) {
		case "details":
			bandhu.session_ui.open_patient_details_dialog(
				"bandhu_app.bandhu_app.page.nurse_form.nurse_form.get_patient_registration_details",
				encounter,
				encountersByName[encounter] || {}
			);
			break;
		case "enter_results":
			openTestResultsDialog(page, encounter);
			break;
		case "dispense":
			openDispenseDialog(page, encounter);
			break;
		case "vitals":
			openVitalsDialog(page, encounter);
			break;
	}
}

// Both nurse queues are empty for most of a session -- the patients are with the front desk or the
// doctor -- and the page said nothing about any of them.
function renderSessionProgress(progress) {
	const stages = [
		[__("with doctor"), (progress.registered || 0) + (progress.with_doctor || 0)],
		[__("for tests"), progress.for_tests || 0],
		[__("for medicines"), progress.for_medicines || 0],
		[__("done"), progress.completed || 0],
	];

	return (
		'<div class="session-progress">' +
		stages
			.map(
				([label, count]) =>
					'<span class="session-progress-item"><b>' +
					count +
					"</b> " +
					frappe.utils.escape_html(label) +
					"</span>"
			)
			.join("") +
		"</div>"
	);
}

function renderEndSessionButton() {
	return (
		'<div class="end-session-bar">' +
		'<button class="btn btn-default btn-sm nurse-end-session">' +
		frappe.utils.icon("circle-stop", "xs", "", "", "current-color") +
		__("End Session") +
		"</button></div>"
	);
}

function openTestResultsDialog(page, encounter) {
	const row = encountersByName[encounter];
	if (!row) return;

	const dialog = new frappe.ui.Dialog({
		title: __("Enter Test Results"),
		size: "large",
		fields: [
			{
				fieldtype: "Table",
				fieldname: "results",
				label: __("Tests"),
				cannot_add_rows: true,
				cannot_delete_rows: true,
				in_place_edit: false,
				fields: [
					{
						fieldtype: "Data",
						fieldname: "test_name",
						label: __("Test"),
						in_list_view: 1,
						read_only: 1,
					},
					{
						fieldtype: "Select",
						fieldname: "result_type",
						label: __("Result"),
						options: "\nPositive\nNegative\nValue\nNot Done",
						in_list_view: 1,
					},
					{
						fieldtype: "Data",
						fieldname: "result_value",
						label: __("Value"),
						in_list_view: 1,
					},
					{
						fieldtype: "Small Text",
						fieldname: "notes",
						label: __("Doctor's Notes"),
						read_only: 1,
					},
				],
				data: (row.tests || []).map((test) => ({ ...test })),
			},
		],
		primary_action_label: __("Save Results"),
		primary_action: async (values) => {
			const blank = (values.results || []).find((result) => !result.result_type);
			if (blank) {
				frappe.msgprint(
					__("{0} has no result. Choose Not Done if the test could not be run.", [
						blank.test_name,
					])
				);
				return;
			}

			dialog.hide();
			await submitNurseAction(page, "submit_test_results", {
				encounter,
				results: values.results,
			});
		},
	});
	dialog.show();
}

function openDispenseDialog(page, encounter) {
	const row = encountersByName[encounter];
	if (!row) return;

	const dialog = new frappe.ui.Dialog({
		title: __("Dispense Medicine"),
		size: "large",
		fields: [
			{
				fieldtype: "Table",
				fieldname: "prescriptions",
				label: __("Medicines"),
				cannot_add_rows: true,
				cannot_delete_rows: true,
				in_place_edit: false,
				fields: [
					{
						fieldtype: "Data",
						fieldname: "medicines",
						label: __("Medicine"),
						in_list_view: 1,
						read_only: 1,
					},
					{
						fieldtype: "Data",
						fieldname: "dosage_frequency",
						label: __("Frequency"),
						in_list_view: 1,
						read_only: 1,
					},
					{
						fieldtype: "Int",
						fieldname: "duration_days",
						label: __("Days"),
						in_list_view: 1,
						read_only: 1,
					},
					{
						fieldtype: "Int",
						fieldname: "quantity",
						label: __("Qty"),
						in_list_view: 1,
						read_only: 1,
					},
					{
						fieldtype: "Small Text",
						fieldname: "instructions",
						label: __("Instructions"),
						read_only: 1,
					},
					// Not pre-ticked. This is the record of what was physically handed over, and
					// it is what the donor-fund and stock reporting will count.
					{
						fieldtype: "Check",
						fieldname: "dispensed",
						label: __("Dispensed"),
						in_list_view: 1,
					},
				],
				data: (row.prescriptions || []).map((prescription) => ({ ...prescription })),
			},
		],
		primary_action_label: __("Complete"),
		primary_action: async (values) => {
			const dispensedRows = (values.prescriptions || [])
				.filter((prescription) => prescription.dispensed)
				.map((prescription) => prescription.name);

			// Completing with nothing ticked is legitimate -- the medicine can be out of stock --
			// but it should be a decision, not what happens when the nurse taps straight through.
			if (!dispensedRows.length) {
				frappe.confirm(
					__("Nothing is ticked. Finish this visit with no medicine handed over?"),
					async () => {
						dialog.hide();
						await submitNurseAction(page, "dispense_medicine", {
							encounter,
							dispensed_rows: [],
						});
					}
				);
				return;
			}

			dialog.hide();
			await submitNurseAction(page, "dispense_medicine", {
				encounter,
				dispensed_rows: dispensedRows,
			});
		},
	});
	dialog.show();
}

function openVitalsDialog(page, encounter) {
	const row = encountersByName[encounter] || {};
	const [bpSystolic, bpDiastolic] = (row.custom_blood_pressure || "").split("/");

	const dialog = new frappe.ui.Dialog({
		title: __("Record Vitals"),
		fields: [
			{
				fieldtype: "Float",
				fieldname: "height_cm",
				label: __("Height (cm)"),
				default: row.custom_height,
			},
			{
				fieldtype: "Float",
				fieldname: "weight_kg",
				label: __("Weight (kg)"),
				default: row.custom_weight,
			},
			{ fieldtype: "Column Break" },
			{
				fieldtype: "Float",
				fieldname: "temperature",
				label: __("Temperature (°F)"),
				default: row.custom_temperature,
			},
			{
				fieldtype: "Int",
				fieldname: "spo2",
				label: __("SpO2 (%)"),
				default: row.custom_spo2,
			},
			{ fieldtype: "Section Break" },
			{
				fieldtype: "Int",
				fieldname: "pulse_rate",
				label: __("Pulse (bpm)"),
				default: row.custom_pulse_rate,
			},
			{
				fieldtype: "Int",
				fieldname: "bp_systolic",
				label: __("BP Systolic"),
				default: bpSystolic || null,
			},
			{ fieldtype: "Column Break" },
			{
				fieldtype: "Int",
				fieldname: "bp_diastolic",
				label: __("BP Diastolic"),
				default: bpDiastolic || null,
			},
		],
		primary_action_label: __("Save Vitals"),
		primary_action: async (values) => {
			dialog.hide();
			await submitNurseAction(page, "record_vitals", {
				encounter,
				height_cm: values.height_cm || null,
				weight_kg: values.weight_kg || null,
				temperature: values.temperature || null,
				pulse_rate: values.pulse_rate || null,
				spo2: values.spo2 || null,
				bp_systolic: values.bp_systolic || null,
				bp_diastolic: values.bp_diastolic || null,
			});
		},
	});
	dialog.show();
}

async function submitNurseAction(page, method, args) {
	frappe.dom.freeze();
	try {
		await frappe.call({
			method: "bandhu_app.bandhu_app.page.nurse_form.nurse_form." + method,
			args,
		});
	} finally {
		frappe.dom.unfreeze();
	}

	frappe.show_alert({ message: __("Saved"), indicator: "green" });
	await bandhu.session_ui.refresh_page(page, loadQueues);
}

function renderQueueActionButtons(encounter, action) {
	const buttons = [
		bandhu.session_ui.format_action_button(
			"nurse-action-btn",
			encounter.name,
			"details",
			__("Details"),
			false
		),
	];
	if (action === "test" || action === "medicine") {
		buttons.push(
			bandhu.session_ui.format_action_button(
				"nurse-action-btn",
				encounter.name,
				"vitals",
				__("Vitals"),
				false
			)
		);
	}
	if (action === "test") {
		buttons.push(
			bandhu.session_ui.format_action_button(
				"nurse-action-btn",
				encounter.name,
				"enter_results",
				__("Enter Results"),
				false
			)
		);
	} else if (action === "medicine") {
		buttons.push(
			bandhu.session_ui.format_action_button(
				"nurse-action-btn",
				encounter.name,
				"dispense",
				__("Dispense"),
				false
			)
		);
	}
	return '<div class="nurse-action-btns">' + buttons.join("") + "</div>";
}

// What the doctor actually asked for. It is already in the payload, and reading it off the row
// saves opening a dialog for every patient just to find out which test to run.
function renderQueueOrder(encounter, action) {
	const items =
		action === "test"
			? (encounter.tests || []).map((test) => test.test_name)
			: (encounter.prescriptions || []).map((prescription) => prescription.medicines);
	const named = items.filter(Boolean);
	if (!named.length) return "";

	return '<span class="queue-order">' + frappe.utils.escape_html(named.join(", ")) + "</span>";
}

// Time since the patient registered, not since the doctor sent them: no state change is
// timestamped, so this is the honest number -- and who has been in the session longest is what
// the nurse needs anyway.
function renderTimeInSession(encounter) {
	if (!encounter.creation) return "";

	// The column heading already says what this is, so the cell is just the duration.
	return frappe.datetime.comment_when(encounter.creation, true);
}

function renderQueueSection(title, encounters, action) {
	const count = '<span class="queue-meta"> (' + encounters.length + ")</span>";

	if (!encounters.length) {
		return (
			'<div class="queue-section">' +
			'<h4 class="queue-head">' +
			frappe.utils.escape_html(title) +
			count +
			"</h4>" +
			'<div class="queue-empty">' +
			__("No patients in queue.") +
			"</div></div>"
		);
	}

	const rows = encounters
		.map(
			(encounter) =>
				'<tr class="nurse-queue-row" data-name="' +
				frappe.utils.escape_html(encounter.name) +
				'">' +
				'<td class="patient-cell">' +
				frappe.utils.escape_html(encounter.patient_name || "") +
				renderQueueOrder(encounter, action) +
				"</td>" +
				'<td class="age-cell">' +
				frappe.utils.escape_html(encounter.patient_age || "") +
				"</td>" +
				'<td class="sex-cell">' +
				frappe.utils.escape_html(encounter.patient_sex || "") +
				"</td>" +
				(action
					? '<td class="waited-cell">' + renderTimeInSession(encounter) + "</td>"
					: "") +
				'<td class="action-cell">' +
				renderQueueActionButtons(encounter, action) +
				"</td>" +
				"</tr>"
		)
		.join("");

	return (
		'<div class="queue-section">' +
		'<h4 class="queue-head">' +
		frappe.utils.escape_html(title) +
		count +
		"</h4>" +
		'<div class="table-wrap">' +
		'<table class="table">' +
		"<thead><tr>" +
		"<th>" +
		__("Patient Name") +
		"</th>" +
		"<th>" +
		__("Age") +
		"</th>" +
		"<th>" +
		__("Sex") +
		"</th>" +
		(action ? "<th>" + __("In session") + "</th>" : "") +
		"<th>" +
		__("Actions") +
		"</th>" +
		"</tr></thead>" +
		"<tbody>" +
		rows +
		"</tbody>" +
		"</table></div></div>"
	);
}

frappe.pages["nurse-form"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Nurse"),
		single_column: true,
	});

	page.set_secondary_action(
		__("My Schedule"),
		() => frappe.set_route("my-schedule"),
		"calendar"
	);

	nursePage = page;
};

async function refreshDashboard() {
	await frappe.require(SESSION_UI_ASSET);
	bandhu.session_ui.add_refresh_icon(nursePage, refreshDashboard);
	await bandhu.session_ui.refresh_page(nursePage, loadDashboard);
	// After the load, not before: the session's room can only be joined once the page knows which
	// session it is showing.
	bandhu.session_ui.subscribe_to_board_updates(
		"nurse-form",
		() => (nurseSession ? nurseSession.session_name : null),
		refreshDashboard
	);
}

// Desk keeps this page's DOM and module state alive, so returning from a Patient Encounter would
// otherwise show the queues exactly as they were before the encounter was edited. on_page_show
// also fires on the very first show (frappe/public/js/frappe/views/pageview.js:104-107), so it is
// the only loader needed.
frappe.pages["nurse-form"].on_page_show = refreshDashboard;
