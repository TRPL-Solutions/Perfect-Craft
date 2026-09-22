frappe.ui.form.on("Stock Entry", {
    setup(frm) {
        make_cost_center_mandatory(frm);
    },

    refresh(frm) {
        make_cost_center_mandatory(frm);

        if (frm.doc.docstatus === 0) {
            sync_item_cost_centers(frm);
        }
    },

    cost_center(frm) {
        if (frm.doc.docstatus === 0) {
            sync_item_cost_centers(frm);
        }
    },
});


frappe.ui.form.on("Stock Entry Detail", {
    items_add(frm, cdt, cdn) {
        set_row_cost_center(frm, cdt, cdn);
    },

    item_code(frm, cdt, cdn) {
        set_row_cost_center(frm, cdt, cdn);
    },

    cost_center(frm, cdt, cdn) {
        set_row_cost_center(frm, cdt, cdn);
    },
});


function make_cost_center_mandatory(frm) {
    frm.set_df_property(
        "cost_center",
        "reqd",
        1
    );

    if (
        frm.fields_dict.items &&
        frm.fields_dict.items.grid
    ) {
        frm.fields_dict.items.grid.update_docfield_property(
            "cost_center",
            "reqd",
            1
        );
    }
}


function sync_item_cost_centers(frm) {
    if (!frm.doc.cost_center) {
        return;
    }

    (frm.doc.items || []).forEach((row) => {
        if (
            row.cost_center !==
            frm.doc.cost_center
        ) {
            frappe.model.set_value(
                row.doctype,
                row.name,
                "cost_center",
                frm.doc.cost_center
            );
        }
    });

    frm.refresh_field("items");
}


function set_row_cost_center(
    frm,
    cdt,
    cdn
) {
    if (
        frm.doc.docstatus !== 0 ||
        !frm.doc.cost_center
    ) {
        return;
    }

    const row = locals[cdt][cdn];

    if (
        row.cost_center !==
        frm.doc.cost_center
    ) {
        frappe.model.set_value(
            cdt,
            cdn,
            "cost_center",
            frm.doc.cost_center
        );
    }
}