// ============================================================
// PERFECT CRAFT - DELIVERY NOTE (shown as "Gate Pass")
//
// Qty x Carton -> Carton Amount (custom_carton_amount)
// Sum Carton Amount -> Delivery Charges (custom_delivery_charges)
//
// Server recalculates the same values on validate:
// pc_production.pc_production.doctype.delivery_note.delivery_note
// ============================================================


// ============================================================
// DELIVERY CHARGES TOTAL
// ============================================================

function pc_calculate_dn_delivery_charges(frm) {

    let total = 0;

    (frm.doc.items || []).forEach((row) => {
        total += flt(row.custom_carton_amount);
    });

    total = flt(
        total,
        precision("custom_delivery_charges")
    );

    if (flt(frm.doc.custom_delivery_charges) !== total) {
        frm.set_value("custom_delivery_charges", total);
    }
}


// ============================================================
// ROW AMOUNT
// ============================================================

function pc_get_dn_row_amount(row) {

    return flt(
        flt(row.qty) * flt(row.custom_carton),
        precision("custom_carton_amount", row)
    );
}


function pc_calculate_dn_row_amount(row) {

    const amount = pc_get_dn_row_amount(row);

    // Set directly: the field has no handler, and the total is
    // recalculated by the caller once for all affected rows.
    if (flt(row.custom_carton_amount) !== amount) {
        row.custom_carton_amount = amount;
        return true;
    }

    return false;
}


function pc_refresh_dn_delivery_charges(frm) {

    let changed = false;

    (frm.doc.items || []).forEach((row) => {
        changed = pc_calculate_dn_row_amount(row) || changed;
    });

    if (changed) {
        frm.refresh_field("items");
        frm.dirty();
    }

    pc_calculate_dn_delivery_charges(frm);
}


// ============================================================
// TRANSPORTER / DRIVER
// ============================================================

// ERPNext core filters Driver by { transporter: doc.transporter }.
// When Transporter is "" (cleared, or loaded from a saved draft)
// that matches only drivers WITHOUT a transporter, hiding valid ones.
// Filter by transporter only when one is selected.
function pc_get_driver_filters(doc) {

    const filters = { status: "Active" };

    if (doc.transporter) {
        filters.transporter = doc.transporter;
    }

    return filters;
}


async function pc_clear_driver_if_invalid(frm) {

    // Link control caches results by search text, not by filter.
    const driver_field = frm.fields_dict.driver;
    if (driver_field && driver_field.$input) {
        driver_field.$input.cache = {};
    }

    if (!frm.doc.driver || !frm.doc.transporter) {
        return;
    }

    const { message } = await frappe.db.get_value(
        "Driver",
        frm.doc.driver,
        "transporter"
    );

    if ((message && message.transporter) !== frm.doc.transporter) {
        await frm.set_value({ driver: "", driver_name: "" });

        frappe.show_alert({
            message: __("Driver cleared: not linked with Transporter {0}.", [
                frm.doc.transporter,
            ]),
            indicator: "orange",
        });
    }
}


// ============================================================
// DELIVERY NOTE
// ============================================================

frappe.ui.form.on("Delivery Note", {

    setup(frm) {
        // ERPNext core limits Transporter to suppliers with
        // "Is Transporter" ticked. Perfect Craft selects any active
        // Supplier, same as Delivery Trip's Transporter field.
        frm.set_query("transporter", () => ({
            filters: { disabled: 0 },
        }));

        frm.set_query("driver", (doc) => ({
            filters: pc_get_driver_filters(doc),
        }));
    },

    transporter(frm) {
        return pc_clear_driver_if_invalid(frm);
    },

    refresh(frm) {
        if (frm.doc.docstatus === 0) {
            pc_refresh_dn_delivery_charges(frm);
        }
    },

    validate(frm) {
        pc_refresh_dn_delivery_charges(frm);
    },

});


// ============================================================
// DELIVERY NOTE ITEM
// ============================================================

async function pc_on_dn_item_change(frm, cdt, cdn) {

    const row = locals[cdt][cdn];

    if (!row) {
        return;
    }

    const amount = pc_get_dn_row_amount(row);

    if (flt(row.custom_carton_amount) !== amount) {
        await frappe.model.set_value(cdt, cdn, "custom_carton_amount", amount);
    }

    pc_calculate_dn_delivery_charges(frm);
}


frappe.ui.form.on("Delivery Note Item", {

    qty: pc_on_dn_item_change,

    custom_carton(frm, cdt, cdn) {

        const row = locals[cdt][cdn];

        if (row && flt(row.custom_carton) < 0) {
            frappe.model.set_value(cdt, cdn, "custom_carton", 0);
            frappe.msgprint(__("Carton cannot be negative."));
            return;
        }

        pc_on_dn_item_change(frm, cdt, cdn);
    },

    items_add: pc_on_dn_item_change,

    // Row add/remove events are triggered against the child DocType.
    items_remove(frm) {
        pc_calculate_dn_delivery_charges(frm);
    },

    // "Delete all rows" only triggers items_delete.
    items_delete(frm) {
        pc_calculate_dn_delivery_charges(frm);
    },

});
