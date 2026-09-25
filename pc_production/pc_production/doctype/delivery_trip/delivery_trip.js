// ============================================================
// PERFECT CRAFT - DELIVERY TRIP
//
// Delivery Note -> Qty
// Qty x Per Carton Charges -> Amount
// Sum Amount -> Delivery Charges
// ============================================================


// ============================================================
// FIELD PROPERTIES
// ============================================================

function pc_setup_delivery_trip_fields(frm) {

    // Parent total is automatic.
    frm.set_df_property(
        "custom_delivery_charges",
        "read_only",
        1
    );

    frm.set_df_property(
        "custom_delivery_charges",
        "reqd",
        0
    );


    const grid =
        frm.fields_dict.delivery_stops?.grid;


    if (!grid) {
        return;
    }


    // Qty fetched from Delivery Note
    grid.update_docfield_property(
        "custom_qty",
        "read_only",
        1
    );


    // User enters this
    grid.update_docfield_property(
        "custom_per_carton_charges",
        "read_only",
        0
    );


    // Automatic calculation
    grid.update_docfield_property(
        "custom_amount",
        "read_only",
        1
    );


    grid.reset_grid();
}


// ============================================================
// SAFE CHILD FIELD SETTER
// ============================================================

async function pc_set_child_value(
    cdt,
    cdn,
    fieldname,
    value
) {

    const row =
        locals[cdt][cdn];


    if (!row) {
        return;
    }


    const old_value =
        flt(
            row[fieldname]
        );


    const new_value =
        flt(
            value
        );


    if (
        old_value !== new_value
    ) {

        await frappe.model.set_value(
            cdt,
            cdn,
            fieldname,
            new_value
        );
    }
}


// ============================================================
// DELIVERY CHARGES TOTAL
// ============================================================

async function pc_calculate_delivery_charges_total(
    frm
) {

    let total = 0;


    (
        frm.doc.delivery_stops || []
    ).forEach((row) => {

        total += flt(
            row.custom_amount
        );

    });


    total =
        flt(
            total,
            2
        );


    if (
        flt(
            frm.doc.custom_delivery_charges
        ) !== total
    ) {

        await frm.set_value(
            "custom_delivery_charges",
            total
        );
    }
}


// ============================================================
// ROW AMOUNT
// ============================================================

async function pc_calculate_delivery_stop_amount(
    frm,
    cdt,
    cdn
) {

    const row =
        locals[cdt][cdn];


    if (!row) {
        return;
    }


    const qty =
        flt(
            row.custom_qty
        );


    const per_carton_charges =
        flt(
            row.custom_per_carton_charges
        );


    const amount =
        flt(
            qty * per_carton_charges,
            2
        );


    await pc_set_child_value(
        cdt,
        cdn,
        "custom_amount",
        amount
    );


    await pc_calculate_delivery_charges_total(
        frm
    );
}


// ============================================================
// FETCH DELIVERY NOTE TOTAL QTY
// ============================================================

async function pc_fetch_delivery_note_qty(
    frm,
    cdt,
    cdn
) {

    const row =
        locals[cdt][cdn];


    if (!row) {
        return;
    }


    // --------------------------------------------------------
    // No Delivery Note
    // --------------------------------------------------------

    if (!row.delivery_note) {

        await pc_set_child_value(
            cdt,
            cdn,
            "custom_qty",
            0
        );


        await pc_set_child_value(
            cdt,
            cdn,
            "custom_amount",
            0
        );


        await pc_calculate_delivery_charges_total(
            frm
        );


        return;
    }


    // --------------------------------------------------------
    // Fetch linked Delivery Note
    // --------------------------------------------------------

    try {

        const response =
            await frappe.db.get_value(
                "Delivery Note",
                row.delivery_note,
                [
                    "total_qty",
                    "docstatus"
                ]
            );


        const delivery_note =
            response?.message || {};


        // ----------------------------------------------------
        // Only submitted Delivery Notes
        // ----------------------------------------------------

        if (
            Number(
                delivery_note.docstatus || 0
            ) !== 1
        ) {

            frappe.msgprint(
                __(
                    "Delivery Note {0} must be submitted.",
                    [
                        row.delivery_note
                    ]
                )
            );


            await pc_set_child_value(
                cdt,
                cdn,
                "custom_qty",
                0
            );


            await pc_set_child_value(
                cdt,
                cdn,
                "custom_amount",
                0
            );


            await pc_calculate_delivery_charges_total(
                frm
            );


            return;
        }


        // ----------------------------------------------------
        // Qty = Delivery Note Total Quantity
        // ----------------------------------------------------

        await pc_set_child_value(
            cdt,
            cdn,
            "custom_qty",
            flt(
                delivery_note.total_qty
            )
        );


        // ----------------------------------------------------
        // Amount = Qty x Per Carton Charges
        // ----------------------------------------------------

        await pc_calculate_delivery_stop_amount(
            frm,
            cdt,
            cdn
        );


    } catch (error) {

        console.error(
            "Perfect Craft: unable to fetch Delivery Note quantity",
            error
        );
    }
}


// ============================================================
// REFRESH ALL DELIVERY STOPS
// ============================================================

async function pc_refresh_delivery_trip_calculations(
    frm
) {

    for (
        const row
        of (
            frm.doc.delivery_stops || []
        )
    ) {

        if (
            row.delivery_note
        ) {

            await pc_fetch_delivery_note_qty(
                frm,
                row.doctype,
                row.name
            );

        } else {

            await pc_set_child_value(
                row.doctype,
                row.name,
                "custom_qty",
                0
            );


            await pc_set_child_value(
                row.doctype,
                row.name,
                "custom_amount",
                0
            );
        }
    }


    await pc_calculate_delivery_charges_total(
        frm
    );
}


// ============================================================
// DELIVERY TRIP
// ============================================================

frappe.ui.form.on(
    "Delivery Trip",
    {

        async refresh(frm) {

            pc_setup_delivery_trip_fields(
                frm
            );


            if (
                frm.doc.docstatus === 0
            ) {

                await pc_refresh_delivery_trip_calculations(
                    frm
                );
            }
        },


        async validate(frm) {

            await pc_refresh_delivery_trip_calculations(
                frm
            );


            pc_setup_delivery_trip_fields(
                frm
            );
        }

    }
);


// ============================================================
// STANDARD DELIVERY STOP CHILD TABLE
// ============================================================

frappe.ui.form.on(
    "Delivery Stop",
    {

        // Delivery Note selected / changed
        async delivery_note(
            frm,
            cdt,
            cdn
        ) {

            await pc_fetch_delivery_note_qty(
                frm,
                cdt,
                cdn
            );
        },


        // User enters Per Carton Charges
        async custom_per_carton_charges(
            frm,
            cdt,
            cdn
        ) {

            const row =
                locals[cdt][cdn];


            if (!row) {
                return;
            }


            if (
                flt(
                    row.custom_per_carton_charges
                ) < 0
            ) {

                await frappe.model.set_value(
                    cdt,
                    cdn,
                    "custom_per_carton_charges",
                    0
                );


                frappe.msgprint(
                    __(
                        "Per Carton Charges cannot be negative."
                    )
                );


                return;
            }


            await pc_calculate_delivery_stop_amount(
                frm,
                cdt,
                cdn
            );
        },


        async delivery_stops_add(
            frm
        ) {

            await pc_calculate_delivery_charges_total(
                frm
            );
        },


        async delivery_stops_remove(
            frm
        ) {

            await pc_calculate_delivery_charges_total(
                frm
            );
        }

    }
);