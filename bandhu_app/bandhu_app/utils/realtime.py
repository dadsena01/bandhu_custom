import frappe

# The session's own room, not the site room, which reaches every System User.
BOARD_UPDATE_EVENT = "bandhu_board_update"

BOARD_UPDATE_DOCTYPE = "Bandhu Clinic Session"


def publish_board_update(clinic_session: str | None) -> None:
	if not clinic_session:
		return

	frappe.publish_realtime(
		BOARD_UPDATE_EVENT,
		# The actor has already refreshed; skipping them keeps their scroll position.
		{"clinic_session": clinic_session, "actor": frappe.session.user},
		doctype=BOARD_UPDATE_DOCTYPE,
		docname=clinic_session,
		# after_commit, or a board re-reads the queue before this write is visible.
		after_commit=True,
	)


def broadcast_encounter_change(doc, method=None) -> None:
	publish_board_update(doc.custom_clinic_session)
