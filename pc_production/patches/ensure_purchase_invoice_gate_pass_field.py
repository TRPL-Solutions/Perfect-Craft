import frappe


def execute():

	field_name = "Purchase Invoice-custom_gate_pass"

	values = {
		"dt": "Purchase Invoice",
		"fieldname": "custom_gate_pass",
		"label": "Gate Pass",
		"fieldtype": "Link",
		"options": "Gate Pass",
		"insert_after": "remarks",
		"read_only": 1,
		"no_copy": 1,
		"allow_on_submit": 1,
		"print_hide": 1,
		"in_standard_filter": 1,
	}

	if frappe.db.exists(
		"Custom Field",
		field_name
	):

		frappe.db.set_value(
			"Custom Field",
			field_name,
			values,
			update_modified=False,
		)

	else:

		custom_field = frappe.new_doc(
			"Custom Field"
		)

		custom_field.update(values)

		custom_field.name = field_name

		custom_field.insert(
			ignore_permissions=True
		)

	frappe.clear_cache(
		doctype="Purchase Invoice"
	)