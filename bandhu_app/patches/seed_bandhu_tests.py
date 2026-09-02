from bandhu_app.bandhu_app.utils.clinic_test import seed_default_tests


def execute():
	"""`after_install` only fires on a fresh install, and this app is already live on two
	sites. Same idempotent seed, so a site that has since retired or renamed a test keeps
	its own list."""
	seed_default_tests()
