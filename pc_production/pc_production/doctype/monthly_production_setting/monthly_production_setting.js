// Copyright (c) 2026, TRPL Solutions and contributors
// For license information, please see license.txt

// frappe.ui.form.on("Monthly Production Setting", {
// 	refresh(frm) {

// 	},
// });
frappe.ui.form.on("Monthly Production Setting", {
    setup(frm) {
        frm.set_query("expenses", "type_of_expense", () => {
            return {
                filters: {
                    is_group: 1
                }
            };
        });
    }
});