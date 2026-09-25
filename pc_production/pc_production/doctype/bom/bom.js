// ============================================================
// PERFECT CRAFT
// BOM RAW MATERIAL + SCRAP AUTOMATION
//
// Raw Material Qty + Scrap Qty = Qty
//
// Scrap Item / Qty from BOM Item is automatically copied
// to standard BOM Scrap Items table.
// ============================================================


// ============================================================
// CALCULATE ONE RAW MATERIAL ROW
// ============================================================

function pc_calculate_bom_item_qty(frm, cdt, cdn) {

    const row = locals[cdt][cdn];

    if (!row) {
        return;
    }


    let raw_qty =
        flt(row.custom_raw_material_qty);


    let scrap_qty =
        flt(row.custom_scrap_qty);


    // --------------------------------------------------------
    // LEGACY / EXISTING DRAFT BOM SUPPORT
    // --------------------------------------------------------
    //
    // Existing BOM row has Qty but new Raw Material Qty
    // is empty.
    //
    // Do this only when scrap customization has not yet
    // been entered.
    // --------------------------------------------------------

    if (
        raw_qty <= 0 &&
        flt(row.qty) > 0 &&
        !row.custom_scrap_item &&
        scrap_qty <= 0
    ) {

        raw_qty = flt(row.qty);

        frappe.model.set_value(
            cdt,
            cdn,
            "custom_raw_material_qty",
            raw_qty
        );
    }


    // --------------------------------------------------------
    // CALCULATE TOTAL
    // --------------------------------------------------------

    const total_qty =
        flt(raw_qty) +
        flt(scrap_qty);


    frappe.model.set_value(
        cdt,
        cdn,
        "qty",
        total_qty
    );
}


// ============================================================
// BUILD SCRAP TABLE FROM RAW MATERIAL ROWS
// ============================================================

async function pc_sync_bom_scrap_items(frm) {

    if (frm.__pc_scrap_sync_running) {
        return;
    }


    frm.__pc_scrap_sync_running = true;


    try {

        const scrap_map = {};


        // ----------------------------------------------------
        // COLLECT SCRAP
        // ----------------------------------------------------

        (frm.doc.items || []).forEach(row => {

            const scrap_item =
                row.custom_scrap_item;


            const scrap_qty =
                flt(row.custom_scrap_qty);


            if (
                scrap_item &&
                scrap_qty > 0
            ) {

                if (!scrap_map[scrap_item]) {
                    scrap_map[scrap_item] = 0;
                }


                scrap_map[scrap_item] +=
                    scrap_qty;
            }
        });


        // If none of the Perfect Craft scrap fields are used,
        // do not disturb existing standard Scrap Items.

        if (
            Object.keys(scrap_map).length === 0
        ) {
            return;
        }


        // ----------------------------------------------------
        // RAW MATERIAL ROWS ARE SOURCE OF TRUTH
        // ----------------------------------------------------

        frm.clear_table("scrap_items");


        // ----------------------------------------------------
        // CREATE STANDARD BOM SCRAP ITEMS
        // ----------------------------------------------------

        for (
            const [
                scrap_item,
                scrap_qty
            ]
            of Object.entries(scrap_map)
        ) {

            const scrap_row =
                frm.add_child("scrap_items");


            // Setting Item Code this way lets ERPNext's
            // standard BOM Item handler fetch item details.

            await frappe.model.set_value(
                scrap_row.doctype,
                scrap_row.name,
                "item_code",
                scrap_item
            );


            // IMPORTANT:
            // BOM Scrap Item uses stock_qty as its Qty field.

            await frappe.model.set_value(
                scrap_row.doctype,
                scrap_row.name,
                "stock_qty",
                flt(scrap_qty)
            );
        }


        frm.refresh_field(
            "scrap_items"
        );


    } finally {

        frm.__pc_scrap_sync_running = false;
    }
}


// ============================================================
// UPDATE ALL ROWS
// ============================================================

async function pc_recalculate_all_bom_rows(frm) {

    for (
        const row
        of (frm.doc.items || [])
    ) {

        pc_calculate_bom_item_qty(
            frm,
            row.doctype,
            row.name
        );
    }


    await pc_sync_bom_scrap_items(frm);
}


// ============================================================
// BOM PARENT
// ============================================================

frappe.ui.form.on("BOM", {

    setup(frm) {

        // Scrap Item should only allow enabled stock items.

        frm.set_query(
            "custom_scrap_item",
            "items",
            function () {

                return {
                    filters: {
                        disabled: 0,
                        is_stock_item: 1
                    }
                };
            }
        );
    },


    refresh(frm) {

        // ----------------------------------------------------
        // KEEP STANDARD QTY READ ONLY
        // ----------------------------------------------------

        if (
            frm.fields_dict.items &&
            frm.fields_dict.items.grid
        ) {

            frm.fields_dict.items.grid
                .update_docfield_property(
                    "qty",
                    "read_only",
                    1
                );


            frm.fields_dict.items.grid
                .reset_grid();
        }
    },


    async validate(frm) {

        await pc_recalculate_all_bom_rows(
            frm
        );
    }

});


// ============================================================
// BOM ITEM CHILD TABLE
// ============================================================

frappe.ui.form.on("BOM Item", {


    // --------------------------------------------------------
    // RAW MATERIAL QTY
    // --------------------------------------------------------

    async custom_raw_material_qty(
        frm,
        cdt,
        cdn
    ) {

        const row =
            locals[cdt][cdn];


        if (
            flt(
                row.custom_raw_material_qty
            ) < 0
        ) {

            await frappe.model.set_value(
                cdt,
                cdn,
                "custom_raw_material_qty",
                0
            );

            frappe.msgprint(
                __("Raw Material Qty cannot be negative.")
            );

            return;
        }


        pc_calculate_bom_item_qty(
            frm,
            cdt,
            cdn
        );


        await pc_sync_bom_scrap_items(
            frm
        );
    },


    // --------------------------------------------------------
    // SCRAP ITEM
    // --------------------------------------------------------

    async custom_scrap_item(
        frm,
        cdt,
        cdn
    ) {

        const row =
            locals[cdt][cdn];


        // Scrap Item removed -> clear Scrap Qty too.

        if (
            !row.custom_scrap_item &&
            flt(row.custom_scrap_qty) > 0
        ) {

            await frappe.model.set_value(
                cdt,
                cdn,
                "custom_scrap_qty",
                0
            );
        }


        pc_calculate_bom_item_qty(
            frm,
            cdt,
            cdn
        );


        await pc_sync_bom_scrap_items(
            frm
        );
    },


    // --------------------------------------------------------
    // SCRAP QTY
    // --------------------------------------------------------

    async custom_scrap_qty(
        frm,
        cdt,
        cdn
    ) {

        const row =
            locals[cdt][cdn];


        if (
            flt(
                row.custom_scrap_qty
            ) < 0
        ) {

            await frappe.model.set_value(
                cdt,
                cdn,
                "custom_scrap_qty",
                0
            );


            frappe.msgprint(
                __("Scrap Qty cannot be negative.")
            );

            return;
        }


        pc_calculate_bom_item_qty(
            frm,
            cdt,
            cdn
        );


        await pc_sync_bom_scrap_items(
            frm
        );
    },


    // --------------------------------------------------------
    // RAW MATERIAL ROW REMOVED
    // --------------------------------------------------------

    async items_remove(frm) {

        await pc_sync_bom_scrap_items(
            frm
        );
    }

});