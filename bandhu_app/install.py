from bandhu_app.bandhu_app.page.staff_onboarding.staff_onboarding import seed_default_genders
from bandhu_app.bandhu_app.utils.clinic_test import seed_default_tests
from bandhu_app.bandhu_app.utils.patient_encounter import seed_default_appointment_type
from bandhu_app.patches.seed_indian_states import execute as seed_indian_states
from bandhu_app.patches.seed_major_sectors import execute as seed_major_sectors


def after_install() -> None:
	seed_default_tests()
	seed_default_genders()
	seed_default_appointment_type()
	# Patches don't run on a fresh install, only on migrate, so call these directly too.
	seed_indian_states()
	seed_major_sectors()
