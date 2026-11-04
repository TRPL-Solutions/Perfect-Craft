// Copyright (c) 2026, TRPL Solutions and contributors
// For license information, please see license.txt

// frappe.ui.form.on("Monthly Production Setting", {
// 	refresh(frm) {

// 	},
// });
frappe.ui.form.on("Monthly Production Setting", {
    setup(frm) {
        // set_query(link_field, child_table_field, ...): only ledger accounts of the selected company.
        frm.set_query("type_of_expense", "expenses", () => {
            return {
                filters: {
                    is_group: 0,
                    company: frm.doc.company
                }
            };
        });
    }
});