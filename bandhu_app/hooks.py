app_name = "bandhu_app"
app_title = "Bandhu App"
app_publisher = "CMID"
app_description = "CMID"
app_email = "adypatanwar07@gmail.com"
app_license = "mit"

# Apps
# ------------------

required_apps = ["erpnext", "healthcare"]

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "bandhu_app",
# 		"logo": "/assets/bandhu_app/logo.png",
# 		"title": "Bandhu App",
# 		"route": "/bandhu_app",
# 		"has_permission": "bandhu_app.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# Raw asset paths are not versioned by Frappe's include_script/include_style —
# bump ?v= on every edit or browsers keep the old file.
app_include_css = ["/assets/bandhu_app/css/desk.css?v=2"]
app_include_js = [
	"/assets/bandhu_app/js/session_ui.js?v=2",
	"/assets/bandhu_app/js/workspace_redirect.js?v=2",
]

# include js, css files in header of web template
# web_include_css = "/assets/bandhu_app/css/bandhu_app.css"
# web_include_js = "/assets/bandhu_app/js/bandhu_app.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "bandhu_app/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {"Patient": "public/js/patient.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "bandhu_app/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
jinja = {"methods": ["bandhu_app.bandhu_app.utils.custom_qr_code.get_qr_code_image_source"]}

# Installation
# ------------

# before_install = "bandhu_app.install.before_install"
after_install = "bandhu_app.install.after_install"

# Migration
# ------------

after_migrate = [
	"bandhu_app.bandhu_app.utils.desk_visibility.sync_bandhu_desktop_icons",
	"bandhu_app.bandhu_app.utils.desk_visibility.restrict_other_app_desktop_icons",
	"bandhu_app.bandhu_app.page.staff_onboarding.staff_onboarding.seed_default_genders",
	"bandhu_app.bandhu_app.utils.patient_encounter.seed_default_appointment_type",
]

# Uninstallation
# ------------

# before_uninstall = "bandhu_app.uninstall.before_uninstall"
# after_uninstall = "bandhu_app.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "bandhu_app.utils.before_app_install"
# after_app_install = "bandhu_app.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "bandhu_app.utils.before_app_uninstall"
# after_app_uninstall = "bandhu_app.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "bandhu_app.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

scheduler_events = {
	"daily": [
		"bandhu_app.bandhu_app.utils.session_schedule.generate_scheduled_sessions",
	],
}

# Testing
# -------

# before_tests = "bandhu_app.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "bandhu_app.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "bandhu_app.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "bandhu_app.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["bandhu_app.utils.before_request"]
# after_request = ["bandhu_app.utils.after_request"]

# Job Events
# ----------
# before_job = ["bandhu_app.utils.before_job"]
# after_job = ["bandhu_app.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"bandhu_app.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
export_python_type_annotations = True

# Require all whitelisted methods to have type annotations
require_type_annotated_api_methods = True

default_log_clearing_doctypes = {
	"Patient Queue": 90,
	# The CAD patient-search/card audit trail (page/cad_form/cad_form.py). Frappe ships
	# clear_old_logs on Access Log but does not register it, so without this line the table
	# grows for the life of the site.
	"Access Log": 30,
}

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

# fixtures = [
#     {"doctype": "Client Script"},
#     {"doctype": "Server Script"},
#     {"doctype": "Workflow"}
# ]

doc_events = {
	"Patient": {
		"before_insert": "bandhu_app.bandhu_app.utils.custom_bandhu_id.set_bandhu_id",
		"after_insert": "bandhu_app.bandhu_app.utils.patient_qr.create_patient_qr",
		"validate": "bandhu_app.bandhu_app.utils.patient.validate_bmi",
	},
	"Patient Encounter": {
		"validate": "bandhu_app.bandhu_app.utils.patient_encounter.validate_workflow_state",
		"on_update": "bandhu_app.bandhu_app.utils.patient_encounter.sync_to_queue",
	},
}
