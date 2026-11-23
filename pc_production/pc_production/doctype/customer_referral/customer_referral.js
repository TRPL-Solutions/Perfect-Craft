// Copyright (c) 2026, TRPL Solutions and contributors
// For license information, please see license.txt

frappe.ui.form.on("Customer Referral", {
	setup(frm) {
		frm.set_query("referred_customer", "referred_customers", () => {
			const filters = {};
			if (frm.doc.customer) {
				filters.name = ["!=", frm.doc.customer];
			}
			return { filters };
		});

		frm.set_query("item_code", "items", () => {
			return {
				filters: {
					is_sales_item: 1,
					disabled: 0,
				},
			};
		});
	},

	onload(frm) {
		if (frm.is_new() && !frm.doc.company) {
			const company = frappe.defaults.get_user_default("Company");
			if (company) {
				frm.set_value("company", company);
			}
		}
	},

	refresh(frm) {
		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(
				__("Pricing Rules"),
				() => {
					frappe.set_route("List", "Pricing Rule", {
						custom_customer_referral: frm.doc.name,
					});
				},
				__("View")
			);
		}
	},
});
