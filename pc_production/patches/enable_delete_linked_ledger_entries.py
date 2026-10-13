import frappe


def execute():
	# Gate Pass (Delivery Note) deletion also deletes its cancelled transport
	# Purchase Invoice. ERPNext only allows deleting cancelled transactions
	# when it may remove their cancelled ledger entries as well.
	frappe.db.set_single_value(
		"Accounts Settings",
		"delete_linked_ledger_entries",
		1,
	)
