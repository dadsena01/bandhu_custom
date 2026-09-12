/* global bandhu */

// Shared session/queue UI for the CAD, Doctor, Nurse and My Schedule desk pages.
//
// Desk page scripts run inside `new Function(...)` (frappe/public/js/frappe/dom.js:30), so they
// cannot see each other's helpers. Each page pulls this file in with `frappe.require` before it
// renders; frappe.assets caches it, so only the first page of a session pays for the fetch.

frappe.provide("bandhu.session_ui");

(function () {
	// frappe.call REJECTS on network failure (frappe/public/js/frappe/request.js:32-41). Without
	// this wrapper the rejection escapes unhandled and page.main is never written, leaving staff
	// on a weak session signal staring at a blank screen with no message and no way to retry.
	async function refresh_page(page, load) {
		try {
			await load(page);
		} catch (error) {
			page.main.html(format_load_error());
			page.main.off("click", ".load-error-retry");
			page.main.on("click", ".load-error-retry", () => refresh_page(page, load));
		}
	}

	// Server side, bandhu_app.bandhu_app.utils.realtime pushes this whenever a session moves, into
	// that session's own document room. Each board answers it by re-reading its own queues.
	const BOARD_UPDATE_EVENT = "bandhu_board_update";
	const BOARD_UPDATE_DOCTYPE = "Bandhu Clinic Session";

	// A doctor completing three patients in a row is one re-read for everyone else, not three.
	const BOARD_UPDATE_DELAY = 500;

	let background_refresh_depth = 0;
	const subscribed_routes = new Set();
	const subscribed_rooms = new Map();

	// The loaders freeze the screen so a tap during a slow fetch cannot land on a queue that is
	// about to be replaced. A refresh nobody asked for must not do that -- a grey overlay every
	// time somebody else acts is worse than the stale row it would prevent.
	function freeze() {
		if (!background_refresh_depth) frappe.dom.freeze();
	}

	function unfreeze() {
		if (!background_refresh_depth) frappe.dom.unfreeze();
	}

	// `refresh` is the page's own loader; `route` is its desk route. Desk keeps a page's DOM and
	// module state alive after routing away, so a board nobody is looking at leaves the work to
	// on_page_show instead of fetching for a hidden screen.
	// The push goes to the session's own document room, so a board has to join that room and leave
	// it again when the session changes. Called on every render, not once, for that reason.
	function join_session_room(route, session) {
		if (subscribed_rooms.get(route) === session) return;

		const previous = subscribed_rooms.get(route);
		if (previous) frappe.realtime.doc_unsubscribe(BOARD_UPDATE_DOCTYPE, previous);
		if (session) frappe.realtime.doc_subscribe(BOARD_UPDATE_DOCTYPE, session);

		subscribed_rooms.set(route, session);
	}

	function subscribe_to_board_updates(route, current_session, refresh) {
		join_session_room(route, current_session());

		// This file loads through frappe.require, so a page can only subscribe once it is already
		// rendering -- which is every time it is shown, not once at load.
		if (subscribed_routes.has(route)) return;
		subscribed_routes.add(route);

		let timer = null;
		let deferred = false;

		async function apply() {
			timer = null;
			// Re-rendering underneath an open dialog throws away whatever is half-entered in it.
			if (frappe.get_route_str() !== route || $(".modal:visible").length) {
				deferred = true;
				return;
			}

			deferred = false;
			background_refresh_depth += 1;
			try {
				await refresh();
			} finally {
				background_refresh_depth -= 1;
			}
		}

		function schedule(message) {
			if (message && message.actor === frappe.session.user) return;

			const session = current_session();
			if (session && message && message.clinic_session !== session) return;
			if (timer) return;
			timer = setTimeout(apply, BOARD_UPDATE_DELAY);
		}

		frappe.realtime.on(BOARD_UPDATE_EVENT, schedule);
		$(document).on("hidden.bs.modal", () => {
			if (deferred) schedule();
		});
	}

	function format_load_error() {
		return (
			'<div class="bandhu-load-error">' +
			frappe.utils.icon("triangle-alert", "xl", "", "", "current-color load-error-icon") +
			'<span class="load-error-text">' +
			__("Could not load this page. Check the network connection and try again.") +
			"</span>" +
			'<button type="button" class="btn btn-primary load-error-retry">' +
			__("Retry") +
			"</button></div>"
		);
	}

	function format_welcome() {
		return (
			'<div class="welcome"><h3>' +
			__("Welcome, {0}", [frappe.utils.escape_html(frappe.user_info().fullname)]) +
			"</h3></div>"
		);
	}

	// Desk's own icon group in the page header, which is where every other Desk page puts
	// refresh. Called from on_page_load, so it survives the re-renders that replace page.main.
	function add_refresh_icon(page, refresh) {
		if (page.bandhu_refresh_icon) return;
		page.bandhu_refresh_icon = page.add_action_icon(
			"refresh",
			() => refresh(),
			"",
			__("Refresh")
		);
	}

	// A session that is over and a session that is running have to be told apart across a phone screen
	// in daylight, so the status is a labelled badge rather than a coloured dot: colour alone is
	// the one signal that fails both a colour-blind reader and a washed-out outdoor screen.
	const SESSION_STATUS_BADGES = {
		"In Progress": { theme: "green", variant: "subtle" },
		Planned: { theme: "blue", variant: "subtle" },
		Cancelled: { theme: "red", variant: "subtle" },
	};

	function format_session_info(session) {
		const badge = SESSION_STATUS_BADGES[session.status] || { variant: "subtle" };
		return (
			'<div class="session-bar">' +
			frappe.utils.icon("hospital", "sm", "", "", "current-color") +
			frappe.utils.escape_html(session.clinic || "") +
			'<span class="session-sep">|</span>' +
			frappe.utils.icon("map-pin", "sm", "", "", "current-color") +
			frappe.utils.escape_html(session.site || "") +
			'<span class="session-sep">|</span>' +
			format_badge(session.status, badge.theme, badge.variant) +
			"</div>"
		);
	}

	// A Time field arrives as "9:30:00", not "09:30:00", so it cannot simply be truncated.
	function format_clock_time(value) {
		if (!value) return "";
		const [hours, minutes] = String(value).split(":");
		const hour = parseInt(hours, 10);
		const suffix = hour < 12 ? __("AM") : __("PM");
		const hour_12 = hour % 12 === 0 ? 12 : hour % 12;
		return hour_12 + ":" + (minutes || "00").padStart(2, "0") + " " + suffix;
	}

	function format_planned_window(session) {
		if (!session.planned_start_time) return "";
		const start = format_clock_time(session.planned_start_time);
		return session.planned_end_time
			? start + " – " + format_clock_time(session.planned_end_time)
			: start;
	}

	async function get_upcoming_sessions(method) {
		try {
			const response = await frappe.call({ method });
			return (response && response.message) || [];
		} catch (error) {
			// The upcoming list is informational; failing to load it must not blank the page.
			return [];
		}
	}

	function format_upcoming_sessions(sessions) {
		if (!sessions || !sessions.length) return "";

		const rows = sessions
			.map(
				(session) =>
					'<div class="upcoming-row">' +
					'<span class="upcoming-date">' +
					frappe.utils.escape_html(frappe.datetime.str_to_user(session.date)) +
					"</span>" +
					'<span class="upcoming-site">' +
					frappe.utils.escape_html(session.site || "") +
					"</span>" +
					'<span class="upcoming-time">' +
					frappe.utils.escape_html(format_planned_window(session)) +
					"</span></div>"
			)
			.join("");

		return (
			'<div class="upcoming-card"><div class="upcoming-title">' +
			__("Your Upcoming Sessions") +
			"</div>" +
			rows +
			"</div>"
		);
	}

	// Desk's own read-only field shape — a small label above its value, laid out in the grid and
	// typography classes the desk bundle already ships. Nothing here is page CSS of ours, so the
	// dialog keeps following Desk across a Frappe upgrade instead of drifting. The label carries
	// the weight and the glyph because it is what a nurse scans the column for; the value is read
	// only once the right label has been found.
	function format_detail_field(label, value, icon_name, fixed_width) {
		if (value === null || value === undefined || value === "") return "";
		return (
			'<div class="col-6 col-md-4 bandhu-detail">' +
			// The glyph hangs in its own gutter so the label and the value it belongs to keep a
			// single left edge. Inline, it indented the label off the value beneath it and gave
			// every field two ragged edges.
			(icon_name
				? frappe.utils.icon(icon_name, "sm", "", "", "current-color bandhu-detail-icon")
				: "") +
			'<div class="bandhu-detail-text">' +
			'<div class="bandhu-detail-label">' +
			frappe.utils.escape_html(label) +
			"</div>" +
			'<div class="bandhu-detail-value' +
			(fixed_width ? " bandhu-fixed-width" : "") +
			'">' +
			frappe.utils.escape_html(String(value)) +
			"</div></div></div>"
		);
	}

	function format_detail_row(fields) {
		return fields ? '<div class="row">' + fields + "</div>" : "";
	}

	// Split out of one flat nine-field grid: who the patient is, what was measured today, and
	// where they came from are three different questions, and reading order used to depend on
	// counting across columns to find the one being asked.
	function format_identity_details(patient) {
		return format_detail_row(
			format_detail_field(__("Clinic ID"), patient.custom_bandhu_id, "id-card", true) +
				format_detail_field(__("ABHA ID"), patient.custom_abha_id, "badge-check", true) +
				format_detail_field(__("Mobile Number"), patient.mobile, "phone", true) +
				// The endpoint returns the stored date; every other Bandhu screen shows dates
				// in the user's own format, so printing it raw here is the odd one out.
				format_detail_field(
					__("Date of Birth"),
					patient.dob ? frappe.datetime.str_to_user(patient.dob) : "",
					"calendar"
				)
		);
	}

	// One field labelled "Vitals" inside a section headed "Vitals" said the word twice and then
	// crammed three separate measurements into a single middot-joined cell. Each reading is its
	// own field, so each gets its own column and a nurse can find one without parsing a string.
	//
	// Height/weight/BMI/temperature can come from two places: what the patient carried in from
	// registration, and what the nurse measured this visit. The visit's own reading is what is
	// clinically true right now, so it wins whenever the nurse has recorded one.
	function format_vitals_details(patient, encounter) {
		const height = encounter.custom_height
			? encounter.custom_height + " cm"
			: patient.custom_height_m
			? patient.custom_height_m + " m"
			: "";
		const weight = encounter.custom_weight
			? encounter.custom_weight + " kg"
			: patient.custom_weight_kg
			? patient.custom_weight_kg + " kg"
			: "";
		const bmi = encounter.custom_bmi || patient.custom_bmi;
		const temperature = encounter.custom_temperature || patient.custom_temperature;

		return format_detail_row(
			format_detail_field(__("Height"), height, "ruler") +
				format_detail_field(__("Weight"), weight, "weight") +
				format_detail_field(__("BMI"), bmi, "gauge") +
				format_detail_field(__("Temperature"), temperature, "thermometer") +
				format_detail_field(__("Pulse"), encounter.custom_pulse_rate, "heart-pulse") +
				format_detail_field(__("SpO2"), encounter.custom_spo2, "activity") +
				format_detail_field(__("Blood Pressure"), encounter.custom_blood_pressure, "gauge")
		);
	}

	function format_origin_details(patient) {
		return format_detail_row(
			// State and District took the same map-pin, which told a reader nothing about which
			// of the two they were looking at.
			format_detail_field(__("Native State"), patient.custom_native_state, "map") +
				format_detail_field(
					__("Native District"),
					patient.custom_native_district,
					"map-pin"
				) +
				format_detail_field(
					__("Sector of Employment"),
					patient.custom_sector_of_employment,
					"briefcase"
				) +
				format_detail_field(__("Company"), patient.custom_name_of_company, "building-2")
		);
	}

	// An omitted theme is deliberate: .es-badge's own default is gray, and there is no
	// [data-theme="gray"] rule to name, so a closed session gets the neutral badge by leaving it off.
	function format_badge(label, theme, variant) {
		return (
			'<span class="es-badge"' +
			(theme ? ' data-theme="' + theme + '"' : "") +
			' data-variant="' +
			variant +
			'">' +
			frappe.utils.escape_html(label) +
			"</span>"
		);
	}

	// Positive is the one result a nurse must not walk past, so it is the only solid badge.
	const TEST_RESULT_BADGES = {
		Positive: { theme: "red", variant: "solid" },
		Negative: { theme: "green", variant: "subtle" },
	};

	// The Bandhu Test master decides whether a result reads as a measurement or an indicator;
	// the row cannot, because an ordered-but-untested row carries no result_type at all.
	function format_test_result(test) {
		if (test.result_shape === "Value" || test.result_type === "Value") {
			return test.result_value
				? format_badge(format_measurement(test), "blue", "subtle")
				: format_badge(__("Pending"), "amber", "subtle");
		}

		const badge = TEST_RESULT_BADGES[test.result_type];
		return badge
			? format_badge(test.result_type, badge.theme, badge.variant)
			: format_badge(__("Pending"), "amber", "subtle");
	}

	// Results entered before the master carried a unit already have it typed into the value.
	function format_measurement(test) {
		const reading = String(test.result_value);
		return test.unit && !reading.includes(test.unit) ? reading + " " + test.unit : reading;
	}

	function format_note(note) {
		return (
			'<div class="bandhu-detail-note">' +
			__("Note") +
			": " +
			frappe.utils.escape_html(note) +
			"</div>"
		);
	}

	function format_row_open() {
		return '<div class="bandhu-line">';
	}

	// `shared_note` is the doctor's one ordering note when it covers every row (see
	// utils/patient_details.shared_test_note); those rows drop it so it prints once, above.
	function format_test_rows(tests, shared_note) {
		return (tests || [])
			.map((test) => {
				const own_note = (test.notes || "").trim();
				return (
					format_row_open() +
					'<div class="bandhu-line-main"><div class="bandhu-line-title">' +
					frappe.utils.escape_html(test.test_name) +
					"</div>" +
					(own_note && own_note !== shared_note ? format_note(own_note) : "") +
					'</div><div class="bandhu-line-side">' +
					format_test_result(test) +
					"</div></div>"
				);
			})
			.join("");
	}

	function format_prescription_rows(prescriptions) {
		return (prescriptions || [])
			.map((prescription) => {
				const schedule = [
					prescription.dosage_frequency,
					prescription.duration_days ? prescription.duration_days + "d" : null,
					prescription.quantity ? "x" + prescription.quantity : null,
				]
					.filter(Boolean)
					.join(" ");
				return (
					format_row_open() +
					'<div class="bandhu-line-main"><div class="bandhu-line-title">' +
					frappe.utils.escape_html(prescription.medicines) +
					(schedule
						? '<span class="bandhu-line-schedule">' +
						  frappe.utils.escape_html(schedule) +
						  "</span>"
						: "") +
					"</div>" +
					(prescription.instructions ? format_note(prescription.instructions) : "") +
					'</div><div class="bandhu-line-side">' +
					(prescription.dispensed
						? format_badge(__("Dispensed"), "green", "subtle")
						: format_badge(__("Pending"), "amber", "subtle")) +
					"</div></div>"
				);
			})
			.join("");
	}

	function format_diagnosis_rows(diagnosis) {
		return (diagnosis || [])
			.map(
				(entry) =>
					'<div class="bandhu-line"><div class="bandhu-line-title">' +
					frappe.utils.escape_html(entry.diagnosis_name) +
					"</div>" +
					(entry.notes ? format_note(entry.notes) : "") +
					"</div>"
			)
			.join("");
	}

	function format_section(title, body, lead) {
		if (!body) return "";
		return (
			'<div class="bandhu-section"><div class="bandhu-section-title">' +
			frappe.utils.escape_html(title) +
			"</div>" +
			(lead ? '<div class="bandhu-section-lead">' + lead + "</div>" : "") +
			body +
			"</div>"
		);
	}

	// The nurse queue rows carry no diagnosis, so that section simply renders empty for them.
	function format_patient_details(patient, encounter) {
		const shared_note = (encounter.shared_test_note || "").trim();
		return (
			'<div class="bandhu-details">' +
			format_section(__("Registration Details"), format_identity_details(patient)) +
			format_section(__("Vitals"), format_vitals_details(patient, encounter)) +
			format_section(__("Origin & Work"), format_origin_details(patient)) +
			format_section(
				__("Patient Complaints"),
				encounter.custom_chief_complaints
					? '<div class="bandhu-section-text">' +
							frappe.utils.escape_html(encounter.custom_chief_complaints) +
							"</div>"
					: ""
			) +
			format_section(
				__("Past History"),
				encounter.custom_past_history
					? '<div class="bandhu-section-text">' +
							frappe.utils.escape_html(encounter.custom_past_history) +
							"</div>"
					: ""
			) +
			format_section(
				__("Allergy History"),
				encounter.custom_allergy_history
					? '<div class="bandhu-section-text">' +
							frappe.utils.escape_html(encounter.custom_allergy_history) +
							"</div>"
					: ""
			) +
			format_section(
				__("Tests"),
				format_test_rows(encounter.tests, shared_note),
				shared_note ? __("Note") + ": " + frappe.utils.escape_html(shared_note) : ""
			) +
			format_section(
				__("Prescriptions"),
				format_prescription_rows(encounter.prescriptions)
			) +
			format_section(__("Diagnosis"), format_diagnosis_rows(encounter.diagnosis)) +
			"</div>"
		);
	}

	async function open_patient_details_dialog(method, encounter_name, encounter) {
		frappe.dom.freeze();
		let patient;
		try {
			const response = await frappe.call({ method, args: { encounter: encounter_name } });
			patient = response.message || {};
		} finally {
			frappe.dom.unfreeze();
		}

		const dialog = new frappe.ui.Dialog({
			title: __("Patient Details"),
			size: "large",
			fields: [{ fieldtype: "HTML", fieldname: "details_html" }],
		});
		dialog.fields_dict.details_html.$wrapper.html(format_patient_details(patient, encounter));
		// The queue rows used to navigate here on click; the dialog is now what a row opens, so
		// this is the only remaining way to reach the underlying record.
		dialog.set_secondary_action_label(__("Open Record"));
		dialog.set_secondary_action(() => {
			dialog.hide();
			frappe.set_route("Form", "Patient Encounter", encounter_name);
		});
		dialog.show();
	}

	function format_action_button(button_class, encounter_name, action, label, is_primary) {
		return (
			'<button type="button" class="btn btn-sm ' +
			(is_primary ? "btn-primary" : "btn-default") +
			" queue-action-btn " +
			button_class +
			'" data-encounter="' +
			frappe.utils.escape_html(encounter_name) +
			'" data-action="' +
			frappe.utils.escape_html(action) +
			'">' +
			frappe.utils.escape_html(label) +
			"</button>"
		);
	}

	// Ten digits in one run are hard to read off a screen and repeat back to a patient.
	function group_clinic_id(clinic_id) {
		if (!clinic_id) return "";
		if (!/^\d{10}$/.test(clinic_id)) return clinic_id;

		return (
			clinic_id.slice(0, 2) +
			" " +
			clinic_id[2] +
			" " +
			clinic_id.slice(3, 5) +
			" " +
			clinic_id.slice(5)
		);
	}

	Object.assign(bandhu.session_ui, {
		refresh_page,
		subscribe_to_board_updates,
		freeze,
		unfreeze,
		format_load_error,
		format_welcome,
		add_refresh_icon,
		format_session_info,
		format_clock_time,
		format_planned_window,
		get_upcoming_sessions,
		format_upcoming_sessions,
		format_badge,
		format_patient_details,
		open_patient_details_dialog,
		format_action_button,
		group_clinic_id,
	});
})();
