// Copyright (c) 2026, CMID and contributors
// For license information, please see license.txt

frappe.ui.form.on("Bandhu Session Schedule", {
	refresh: function (frm) {
		// Stays top-level: it is the only read-only check of "does this pattern produce the
		// dates I meant", it is the only button available on an unsaved schedule, and it is
		// the one you reach for repeatedly while building the pattern.
		frm.add_custom_button(__("Preview Next Dates"), () => preview_next_dates(frm));

		if (frm.is_new()) return;

		frm.add_custom_button(
			__("Generate Sessions Now"),
			() => generate_sessions_now(frm),
			__("Sessions")
		);
		frm.add_custom_button(
			__("Rebuild Future Sessions"),
			() => rebuild_future_sessions(frm),
			__("Sessions")
		);
		frm.add_custom_button(
			__("View Sessions"),
			() => {
				frappe.set_route("List", "Bandhu Clinic Session", {
					session_schedule: frm.doc.name,
				});
			},
			__("Sessions")
		);
		frm.add_custom_button(__("Copy This Schedule"), () => copy_schedule(frm), __("Create"));
	},
});

async function preview_next_dates(frm) {
	const response = await frappe.call({
		method: "bandhu_app.bandhu_app.utils.session_schedule.preview_occurrences",
		args: { schedule: JSON.stringify(frm.doc) },
	});
	if (!response || !response.message) return;

	const dates = response.message;
	if (!dates.length) {
		frappe.msgprint({
			title: __("Next Dates"),
			message: __("This pattern produces no dates in the generation window."),
			indicator: "orange",
		});
		return;
	}

	const rows = dates
		.map((day) => `<li>${frappe.datetime.str_to_user(day)} &mdash; ${weekday_label(day)}</li>`)
		.join("");
	frappe.msgprint({
		title: __("Next Dates"),
		message: `<ol>${rows}</ol>`,
		indicator: "blue",
	});
}

async function generate_sessions_now(frm) {
	const response = await frappe.call({
		method: "bandhu_app.bandhu_app.utils.session_schedule.generate_now",
		args: { schedule: frm.doc.name },
	});
	if (!response) return;

	const created = response.message || [];
	frappe.show_alert({
		message: created.length
			? __("{0} session(s) created.", [created.length])
			: __("Every session in the window already exists."),
		indicator: created.length ? "green" : "blue",
	});
	frm.reload_doc();
}

async function rebuild_future_sessions(frm) {
	const confirmed = await new Promise((resolve) => {
		frappe.confirm(
			__(
				"Future sessions that are still Planned and have no patients will be deleted and recreated from the current pattern. Sessions in progress, completed or cancelled are left alone."
			),
			() => resolve(true),
			() => resolve(false)
		);
	});
	if (!confirmed) return;

	const response = await frappe.call({
		method: "bandhu_app.bandhu_app.doctype.bandhu_session_schedule.bandhu_session_schedule.regenerate_future_sessions",
		args: { schedule: frm.doc.name },
	});
	if (!response || !response.message) return;

	const { removed, created } = response.message;
	frappe.msgprint({
		title: __("Future Sessions Rebuilt"),
		message: __("{0} removed, {1} created.", [removed, created]),
		indicator: "green",
	});
	frm.reload_doc();
}

function copy_schedule(frm) {
	const copy = frappe.model.copy_doc(frm.doc);
	// The copy covers a different site, so its own generation history is meaningless.
	copy.last_generated_upto = null;
	frappe.set_route("Form", copy.doctype, copy.name);
}

function weekday_label(day) {
	return frappe.datetime.str_to_obj(day).toLocaleDateString(undefined, { weekday: "long" });
}
