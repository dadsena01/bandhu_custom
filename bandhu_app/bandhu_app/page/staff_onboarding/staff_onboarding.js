/* global bandhu */

const SESSION_UI_ASSET = "/assets/bandhu_app/js/session_ui.js";

let formOptions = { roles: [], genders: [] };

function renderSelectField(name, label, optionsKey, required) {
	const options = formOptions[optionsKey] || [];
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
		'<div class="form-group">' +
		"<label>" +
		frappe.utils.escape_html(label) +
		"</label>" +
		'<select class="form-control onboarding-field" data-field="' +
		name +
		'" ' +
		(required ? "required" : "") +
		">" +
		'<option value="">' +
		__("-- Select --") +
		"</option>" +
		optionHtml +
		"</select></div>"
	);
}

function renderTextField(name, label, type, required, attrs) {
	return (
		'<div class="form-group">' +
		"<label>" +
		frappe.utils.escape_html(label) +
		"</label>" +
		'<input type="' +
		type +
		'" class="form-control onboarding-field" data-field="' +
		name +
		'" ' +
		(required ? "required" : "") +
		" " +
		(attrs || "") +
		"></div>"
	);
}

function renderForm(page) {
	const html =
		'<div class="staff-onboarding-dash">' +
		'<div class="onboarding-form">' +
		'<div class="onboarding-grid">' +
		renderTextField("first_name", __("First Name"), "text", true) +
		renderTextField("last_name", __("Last Name"), "text", false) +
		renderTextField("email", __("Email"), "email", true) +
		renderTextField(
			"mobile_phone",
			__("Mobile Number"),
			"tel",
			false,
			'inputmode="numeric" maxlength="10"'
		) +
		renderSelectField("role", __("Role"), "roles", true) +
		renderSelectField("gender", __("Gender"), "genders", false) +
		"</div>" +
		'<div class="onboarding-actions">' +
		'<button class="btn btn-primary btn-lg onboarding-submit">' +
		__("Create Account") +
		"</button>" +
		"</div>" +
		"</div>" +
		'<div class="onboarding-done"></div>' +
		"</div>";

	page.main.html(html);
	page.main
		.off("click", ".onboarding-submit")
		.on("click", ".onboarding-submit", () => submitOnboarding(page));

	page.main
		.off("click", ".onboarding-add-document")
		.on("click", ".onboarding-add-document", () => pickDocument(page));

	page.main
		.off("click", ".onboarding-remove-document")
		.on("click", ".onboarding-remove-document", function () {
			pendingDocuments.splice($(this).closest(".onboarding-document-row").data("index"), 1);
			markDocumentsChanged(page);
		});

	page.main
		.off("change", ".onboarding-document-name")
		.on("change", ".onboarding-document-name", function () {
			const row =
				pendingDocuments[$(this).closest(".onboarding-document-row").data("index")];
			if (!row) return;
			row.document_name = $(this).val();
			markDocumentsChanged(page);
		});

	page.main
		.off("click", ".onboarding-save-documents")
		.on("click", ".onboarding-save-documents", () => saveDocuments(page));

	page.main
		.off("click", ".onboarding-restart")
		.on("click", ".onboarding-restart", () => renderForm(page));
}

function readFormValues(page) {
	const values = {};
	page.main.find(".onboarding-field").each(function () {
		values[$(this).data("field")] = $(this).val();
	});
	return values;
}

async function submitOnboarding(page) {
	const values = readFormValues(page);

	if (!values.first_name || !values.first_name.trim()) {
		frappe.msgprint(__("First name is required."));
		return;
	}
	if (!values.email || !values.email.trim()) {
		frappe.msgprint(__("Email is required."));
		return;
	}
	if (!values.role) {
		frappe.msgprint(__("Please select a role."));
		return;
	}
	if (values.mobile_phone && !/^\d{10}$/.test(values.mobile_phone.trim())) {
		frappe.msgprint(__("Mobile number must be 10 digits."));
		return;
	}

	const args = {
		first_name: values.first_name.trim(),
		email: values.email.trim(),
		role: values.role,
	};
	if (values.last_name) args.last_name = values.last_name.trim();
	if (values.mobile_phone) args.mobile_phone = values.mobile_phone.trim();
	if (values.gender) args.gender = values.gender;

	frappe.dom.freeze();
	let result;
	try {
		const response = await frappe.call({
			method: "bandhu_app.bandhu_app.page.staff_onboarding.staff_onboarding.provision_staff_member",
			args,
		});
		result = response.message;
	} finally {
		frappe.dom.unfreeze();
	}

	if (!result) return;

	renderCreated(page, result, values);
}

const MAX_STAFF_DOCUMENTS = 10;

let pendingDocuments = [];
let documentsSaved = true;

function renderCreated(page, result, values) {
	pendingDocuments = [];
	documentsSaved = true;

	const fullName = [values.first_name, values.last_name]
		.map((part) => (part || "").trim())
		.filter(Boolean)
		.join(" ");
	const emailLine = result.email_sent
		? __("A set-password email has been sent to them.")
		: __("The set-password email could not be sent. Set a password for them manually.");

	page.main.find(".onboarding-form").hide();
	page.main
		.find(".onboarding-done")
		.data("staff-user", result.user)
		.show()
		.html(
			'<div class="onboarding-created">' +
				frappe.utils.icon(
					"solid-success",
					"lg",
					"",
					"",
					"current-color onboarding-created-icon"
				) +
				"<div><strong>" +
				__("{0} can now sign in", [frappe.utils.escape_html(fullName)]) +
				'</strong><div class="onboarding-created-detail">' +
				frappe.utils.escape_html(result.user) +
				" &middot; " +
				frappe.utils.escape_html(result.practitioner) +
				"<br>" +
				emailLine +
				"</div></div></div>" +
				'<div class="onboarding-documents"></div>' +
				'<div class="onboarding-done-actions"></div>'
		);

	renderDocumentsPanel(page);
	renderDoneActions(page);
}

function renderDocumentsPanel(page) {
	page.main
		.find(".onboarding-documents")
		.html(
			'<h4 class="onboarding-documents-head">' +
				__("Documents") +
				"</h4>" +
				'<p class="onboarding-documents-note">' +
				__(
					"Optional. Up to {0} files. Name each one so anyone reading the record knows what it is.",
					[MAX_STAFF_DOCUMENTS]
				) +
				"</p>" +
				'<div class="onboarding-document-rows"></div>' +
				'<button type="button" class="btn btn-default onboarding-add-document">' +
				frappe.utils.icon("upload", "xs", "", "", "current-color") +
				__("Add a document") +
				"</button>"
		);

	renderDocumentRows(page);
}

function renderDocumentRows(page) {
	const rows = pendingDocuments
		.map(
			(entry, index) =>
				'<div class="onboarding-document-row" data-index="' +
				index +
				'">' +
				'<input type="text" class="form-control onboarding-document-name" placeholder="' +
				frappe.utils.escape_html(__("What is this file?")) +
				'" value="' +
				frappe.utils.escape_html(entry.document_name || "") +
				'">' +
				'<span class="onboarding-document-file">' +
				frappe.utils.escape_html(entry.file_label) +
				"</span>" +
				'<button type="button" class="btn btn-sm btn-default onboarding-remove-document" aria-label="' +
				frappe.utils.escape_html(__("Remove")) +
				'">' +
				frappe.utils.icon("close", "xs", "", "", "current-color") +
				"</button></div>"
		)
		.join("");

	page.main.find(".onboarding-document-rows").html(rows);
	page.main
		.find(".onboarding-add-document")
		.text(pendingDocuments.length ? __("Add another document") : __("Add a document"))
		.prop("disabled", false)
		.toggle(pendingDocuments.length < MAX_STAFF_DOCUMENTS);
}

function pickDocument(page) {
	const staffUser = page.main.find(".onboarding-done").data("staff-user");

	new frappe.ui.FileUploader({
		doctype: "User",
		docname: staffUser,
		disable_file_browser: true,
		allow_multiple: false,
		restrictions: { max_file_size: 5 * 1024 * 1024 },
		on_success: (file) => {
			pendingDocuments.push({
				document_name: file.file_name || "",
				document_file: file.file_url,
				file_label: file.file_name || file.file_url,
			});
			markDocumentsChanged(page);
		},
	});
}

function markDocumentsChanged(page) {
	documentsSaved = false;
	renderDocumentRows(page);
	renderDoneActions(page);
}

function renderDoneActions(page) {
	const save = documentsSaved
		? ""
		: '<button type="button" class="btn btn-primary onboarding-save-documents">' +
		  __("Save documents") +
		  "</button>";
	const restart =
		'<button type="button" class="btn ' +
		(documentsSaved ? "btn-primary" : "btn-default") +
		' onboarding-restart">' +
		__("Onboard another staff member") +
		"</button>";
	const saved =
		documentsSaved && pendingDocuments.length
			? '<span class="onboarding-saved-note">' +
			  (pendingDocuments.length === 1
					? __("1 document saved.")
					: __("{0} documents saved.", [pendingDocuments.length])) +
			  "</span>"
			: "";

	page.main.find(".onboarding-done-actions").html(save + restart + saved);
}

async function saveDocuments(page) {
	const staffUser = page.main.find(".onboarding-done").data("staff-user");
	const unnamed = pendingDocuments.find((entry) => !(entry.document_name || "").trim());
	if (unnamed) {
		frappe.msgprint(
			__("Name every document before saving, so the record says what each file is.")
		);
		return;
	}

	frappe.dom.freeze();
	try {
		await frappe.call({
			method: "bandhu_app.bandhu_app.page.staff_onboarding.staff_onboarding.save_staff_documents",
			args: {
				user: staffUser,
				documents: pendingDocuments.map((entry) => ({
					document_name: entry.document_name.trim(),
					document_file: entry.document_file,
				})),
			},
		});
	} finally {
		frappe.dom.unfreeze();
	}

	documentsSaved = true;
	renderDoneActions(page);
	frappe.show_alert({ message: __("Documents saved"), indicator: "green" });
}

async function loadDashboard(page) {
	const optionsResult = await frappe.call({
		method: "bandhu_app.bandhu_app.page.staff_onboarding.staff_onboarding.get_form_options",
	});
	formOptions = optionsResult.message || formOptions;
	renderForm(page);
}

frappe.pages["staff-onboarding"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Onboard New Staff Member"),
		single_column: true,
	});

	// No on_page_show reload here: this page holds a half-filled form, and re-running the load on
	// every return would throw away whatever the admin had already entered.
	(async () => {
		await frappe.require(SESSION_UI_ASSET);
		await bandhu.session_ui.refresh_page(page, loadDashboard);
	})();
};
