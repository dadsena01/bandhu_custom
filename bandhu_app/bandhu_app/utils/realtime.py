import frappe

# Sent to the session's own document room, so it reaches the people working that session rather than
# every System User on the site. Each board answers it by re-reading its own queues.
BOARD_UPDATE_EVENT = "bandhu_board_update"

BOARD_UPDATE_DOCTYPE = "Bandhu Clinic Session"


def publish_board_update(clinic_session: str | None) -> None:
	if not clinic_session:
		return

	frappe.publish_realtime(
		BOARD_UPDATE_EVENT,
		# The person who made the change has already refreshed their own board by the time this
		# lands; without the actor they would re-render a second time and lose their scroll place.
		{"clinic_session": clinic_session, "actor": frappe.session.user},
		doctype=BOARD_UPDATE_DOCTYPE,
		docname=clinic_session,
		# Without after_commit a board re-reads the queue before the write it is reacting to is
		# visible, and paints the state the staff just changed away from.
		after_commit=True,
	)


def broadcast_encounter_change(doc, method=None) -> None:
	publish_board_update(doc.custom_clinic_session)
