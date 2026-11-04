// Copyright (c) 2026, TRPL Solutions and contributors
// For license information, please see license.txt

// frappe.ui.form.on("Monthly Production Setting", {
// 	refresh(frm) {

// 	},
// });
frappe.ui.form.on("Monthly Production Setting", {
    setup(frm) {
        // set_query(link_field, child_table_field, ...): enabled Expense Account ledgers
        // of the selected company. Company is read on every lookup, so changing it
        // refreshes the options for existing and new rows.
        frm.set_query("type_of_expense", "expenses", () => {
            return {
                filters: {
                    company: frm.doc.company,
                    account_type: "Expense Account",
                    is_group: 0,
                    disabled: 0
                }
            };
        });
    }
});