import frappe


def execute():
	"""`Test Instructions.test_name` became a Link to `Bandhu Test`. The old Select held the
	same five strings and `Bandhu Test` is named by test name, so the values map by identity
	and no row is rewritten.

	A row whose value has no master record is left exactly as it is — deleting or blanking it
	would silently destroy a clinical record. It is logged instead so someone can create the
	missing master, after which the row is valid again with no further migration."""
	recorded = set(frappe.get_all("Test Instructions", pluck="test_name", distinct=True))
	known = set(frappe.get_all("Bandhu Test", pluck="name"))
	unmapped = {name for name in recorded if name} - known

	if not unmapped:
		return

	counts = [(name, frappe.db.count("Test Instructions", {"test_name": name})) for name in sorted(unmapped)]
	frappe.log_error(
		title="Test Instructions rows with no Bandhu Test master",
		message="\n".join(f"{name}: {rows} row(s)" for name, rows in counts),
	)
