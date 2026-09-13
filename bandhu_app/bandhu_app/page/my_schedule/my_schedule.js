/* global bandhu */

const SESSION_UI_ASSET = "/assets/bandhu_app/js/session_ui.js";

let schedulePage = null;

function daysFromToday(date) {
	return moment(date).startOf("day").diff(moment().startOf("day"), "days");
}

function formatRelativeDay(date) {
	const days = daysFromToday(date);
	if (days === 0) return __("Today");
	if (days === 1) return __("Tomorrow");
	if (days < 7) return __("in {0} days", [days]);
	if (days < 14) return __("next week");
	return __("in {0} weeks", [Math.round(days / 7)]);
}

function joinParts(parts) {
	return parts.filter(Boolean).join(", ");
}

function renderDetail(session) {
	// The three questions this row is opened to answer, in that order: where am I going, what is
	// coming with me, who is with me. Area/LSG/district are context for the site, not three facts
	// to be read one at a time, so they collapse into one muted line beneath it.
	const place =
		'<div class="detail-place"><div class="detail-site">' +
		frappe.utils.icon("map-pin", "sm", "", "", "current-color detail-site-icon") +
		frappe.utils.escape_html(session.site || "") +
		"</div>" +
		(joinParts([session.location, session.lsg, session.district, session.state])
			? '<div class="detail-where">' +
			  frappe.utils.escape_html(
					joinParts([session.location, session.lsg, session.district, session.state])
			  ) +
			  "</div>"
			: "") +
		// A referral destination, not part of the camp's identity — present, never competing.
		(session.phcchc
			? '<div class="detail-aside">' +
			  __("Nearest PHC / CHC") +
			  ": " +
			  frappe.utils.escape_html(session.phcchc) +
			  "</div>"
			: "") +
		"</div>";

	const kit = [
		[__("Clinic"), session.clinic],
		[__("Unit"), session.unit],
		[__("Vehicle"), session.vehicle],
	]
		.filter(([, value]) => value)
		.map(
			([label, value]) =>
				'<div class="detail-line"><span>' +
				frappe.utils.escape_html(label) +
				"</span><span>" +
				frappe.utils.escape_html(value) +
				"</span></div>"
		)
		.join("");

	const team = (session.team || [])
		.map((member) => {
			const contact = member.mobile
				? '<a class="detail-call" href="tel:' +
				  encodeURIComponent(member.mobile) +
				  '">' +
				  frappe.utils.icon("phone", "xs", "", "", "current-color detail-call-icon") +
				  frappe.utils.escape_html(member.mobile) +
				  "</a>"
				: '<span class="no-contact">' + __("No number on record") + "</span>";
			return (
				'<div class="detail-line"><span>' +
				frappe.utils.escape_html(__(member.role)) +
				" · " +
				frappe.utils.escape_html(member.name) +
				"</span><span>" +
				contact +
				"</span></div>"
			);
		})
		.join("");

	return (
		'<div class="sched-detail">' +
		place +
		(kit
			? '<div class="detail-group"><div class="detail-head">' +
			  __("Clinic and vehicle") +
			  "</div>" +
			  kit +
			  "</div>"
			: "") +
		(team
			? '<div class="detail-group"><div class="detail-head">' +
			  __("Team that day") +
			  "</div>" +
			  team +
			  "</div>"
			: "") +
		"</div>"
	);
}

function renderCard(session) {
	const days = daysFromToday(session.date);
	const isCancelled = session.status === "Cancelled";
	const badge = isCancelled
		? '<span class="sched-badge cancelled">' +
		  frappe.utils.icon("triangle-alert", "xs", "", "", "current-color sched-badge-icon") +
		  __("Cancelled — do not travel") +
		  "</span>"
		: days === 0
		? '<span class="sched-badge today">' + __("Today") + "</span>"
		: "";

	const state = isCancelled ? " is-cancelled" : days === 0 ? " is-today" : "";

	// The rail and its bullet live on the wrapper, not the card: the card clips its own overflow
	// to keep the expanded detail inside its rounded corners, which would cut a marker off.
	return (
		'<div class="sched-item' +
		state +
		'">' +
		'<div class="sched-card' +
		state +
		'">' +
		'<div class="sched-row">' +
		'<div class="sched-when">' +
		'<div class="sched-day">' +
		frappe.utils.escape_html(moment(session.date).format("ddd D MMM")) +
		"</div>" +
		'<div class="sched-rel">' +
		frappe.utils.escape_html(formatRelativeDay(session.date)) +
		"</div></div>" +
		'<div class="sched-where">' +
		'<div class="sched-site">' +
		frappe.utils.escape_html(session.site || __("Site not set")) +
		" " +
		badge +
		"</div>" +
		'<div class="sched-sub">' +
		frappe.utils.escape_html(joinParts([session.lsg, session.district])) +
		"</div></div>" +
		'<div class="sched-meta">' +
		frappe.utils.escape_html(
			bandhu.session_ui.format_planned_window(session) || __("Time not set")
		) +
		(session.unit ? "<br>" + frappe.utils.escape_html(session.unit) : "") +
		"</div>" +
		frappe.utils.icon("chevron-down", "sm", "", "", "current-color sched-caret") +
		"</div>" +
		renderDetail(session) +
		"</div></div>"
	);
}

function renderSchedule(sessions) {
	let currentMonth = null;
	return sessions
		.map((session) => {
			const month = moment(session.date).format("MMMM YYYY");
			const head =
				month === currentMonth
					? ""
					: '<div class="month-head">' + frappe.utils.escape_html(month) + "</div>";
			currentMonth = month;
			return head + renderCard(session);
		})
		.join("");
}

function renderEmpty(message) {
	return (
		'<div class="empty-state">' +
		frappe.utils.icon("calendar-off", "xl", "", "", "current-color empty-state-icon") +
		'<span class="empty-state-text">' +
		frappe.utils.escape_html(message || __("You have no clinic sessions scheduled.")) +
		"</span></div>"
	);
}

async function loadSchedule(page) {
	frappe.dom.freeze();
	let result;
	try {
		const response = await frappe.call({
			method: "bandhu_app.bandhu_app.page.my_schedule.my_schedule.get_my_schedule",
		});
		result = (response && response.message) || {};
	} finally {
		frappe.dom.unfreeze();
	}

	const sessions = result.sessions || [];
	page.main.html(
		'<div class="my-schedule">' +
			(sessions.length ? renderSchedule(sessions) : renderEmpty(result.message)) +
			"</div>"
	);

	// page.main survives re-render, so a stale delegated handler would fire twice.
	page.main.off("click");
	page.main.on("click", ".sched-row", function () {
		$(this).siblings(".sched-detail").toggle();
		$(this).find(".sched-caret").toggleClass("expanded");
	});
	page.main.on("click", ".sched-detail a", function (event) {
		event.stopPropagation();
	});
}

frappe.pages["my-schedule"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("My Schedule"),
		single_column: true,
	});

	page.set_secondary_action(__("Refresh"), refreshSchedule);

	schedulePage = page;
};

async function refreshSchedule() {
	await frappe.require(SESSION_UI_ASSET);
	await bandhu.session_ui.refresh_page(schedulePage, loadSchedule);
}

// Desk keeps this page's DOM alive, so a schedule cancelled while the user was on another page
// would still read as active on return. on_page_show also fires on the very first show
// (frappe/public/js/frappe/views/pageview.js:104-107), so it is the only loader needed.
frappe.pages["my-schedule"].on_page_show = refreshSchedule;
