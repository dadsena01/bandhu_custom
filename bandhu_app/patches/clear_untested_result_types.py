import frappe
from frappe.query_builder.functions import Coalesce
from frappe.utils import create_batch

BATCH_SIZE = 500


def execute():
	"""Tests that were only ordered are stored as `result_type = "Positive"`.

	`Test Instructions.result_type` had no blank first option, so Frappe filled every
	newly ordered test row with the first Select value. A malaria test nobody has run
	yet therefore reads as positive on any board or report. The schema now starts the
	options with a blank; this clears the rows the old schema mislabelled.

	Only rows whose encounter is still awaiting its test are touched — once the nurse
	has submitted, `result_type` is the value they chose and must not be rewritten.
	"""
	# post_model_sync runs before sync_customizations, so on a site upgrading across the
	# commit that added the custom field the column is not there yet — and there is
	# nothing to clean up until it is.
	if not frappe.db.has_column("Patient Encounter", "custom_workflow_state"):
		return

	test = frappe.qb.DocType("Test Instructions")
	encounter = frappe.qb.DocType("Patient Encounter")

	mislabelled = (
		frappe.qb.from_(test)
		.inner_join(encounter)
		.on(encounter.name == test.parent)
		.select(test.name)
		.where(
			(test.parenttype == "Patient Encounter")
			& (encounter.custom_workflow_state == "Awaiting Test")
			& (Coalesce(test.result_value, "") == "")
		)
		.run(pluck=True)
	)
	if not mislabelled:
		return

	for batch in create_batch(mislabelled, BATCH_SIZE):
		frappe.qb.update(test).set(test.result_type, "").where(test.name.isin(batch)).run()
