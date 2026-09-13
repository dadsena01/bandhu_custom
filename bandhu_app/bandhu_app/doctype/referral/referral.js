// Copyright (c) 2026, CMID and contributors
// For license information, please see license.txt

frappe.ui.form.on("Referral", {
	onload: function (frm) {
		// Stamping these on an already-saved referral marked the form dirty the moment it opened,
		// so simply reading one raised "Not Saved" and a leave-page prompt.
		if (!frm.is_new()) return;

		frm.set_value("created_by", frm.doc.owner);
		frm.set_value("created_on", frappe.datetime.now_datetime());
	},
});

frappe.ui.form.on("Referral Followup", {
	status_update: function (frm, cdt, cdn) {
		let row = locals[cdt][cdn];

		frappe.model.set_value(cdt, cdn, "followup_date", frappe.datetime.get_today());

		if (row.status_update === "Completed") {
			frm.set_value("status", "Completed");
		} else {
			frm.set_value("status", "In Progress");
		}

		frm.refresh_field("referral_followup");
	},
});
