// ============================================================
// PERFECT CRAFT - WORK ORDER
//
// Production Item Item Defaults:
//
// Default Warehouse
//      -> Target Warehouse
//
// Scrap Warehouse
//      -> Work Order Scrap Warehouse
// ============================================================


// ============================================================
// FETCH ITEM WAREHOUSE DEFAULTS
// ============================================================

async function pc_fetch_work_order_warehouses(
    frm,
    force = false
) {

    if (
        !frm.doc.production_item ||
        !frm.doc.company
    ) {
        return;
    }


    try {

        const response = await frappe.call({
            method:
                "pc_production.pc_production.doctype.work_order.work_order.get_item_warehouse_defaults",

            args: {
                item_code:
                    frm.doc.production_item,

                company:
                    frm.doc.company
            }
        });


        const defaults =
            response.message || {};


        const target_warehouse =
            defaults.target_warehouse || "";


        const scrap_warehouse =
            defaults.scrap_warehouse || "";


        // ====================================================
        // TARGET WAREHOUSE
        //
        // Item Default.default_warehouse
        //      -> Work Order.fg_warehouse
        // ====================================================

        if (
            force ||
            !frm.doc.fg_warehouse
        ) {

            await frm.set_value(
                "fg_warehouse",
                target_warehouse
            );
        }


        // ====================================================
        // SCRAP WAREHOUSE
        //
        // Item Default.custom_scrap_warehouse
        //      -> Work Order.scrap_warehouse
        // ====================================================

        if (
            force ||
            !frm.doc.scrap_warehouse
        ) {

            await frm.set_value(
                "scrap_warehouse",
                scrap_warehouse
            );
        }


    } catch (error) {

        console.error(
            "Perfect Craft: unable to fetch Work Order warehouses",
            error
        );
    }
}


// ============================================================
// WORK ORDER EVENTS
// ============================================================

frappe.ui.form.on(
    "Work Order",
    {

        // ----------------------------------------------------
        // Refresh
        // ----------------------------------------------------

        async refresh(frm) {

            if (
                frm.doc.docstatus !== 0
            ) {
                return;
            }


            if (
                !frm.doc.production_item ||
                !frm.doc.company
            ) {
                return;
            }


            /*
             * New Work Order:
             * Always use selected Item defaults.
             *
             * Existing Draft:
             * Only fill blank values.
             */
            await pc_fetch_work_order_warehouses(
                frm,
                frm.is_new()
            );
        },


        // ----------------------------------------------------
        // Production Item changed
        // ----------------------------------------------------

        async production_item(frm) {

            if (
                !frm.doc.production_item
            ) {

                await frm.set_value(
                    "fg_warehouse",
                    ""
                );

                await frm.set_value(
                    "scrap_warehouse",
                    ""
                );

                return;
            }


            /*
             * Item changed, therefore previous warehouses
             * must not remain.
             */
            await pc_fetch_work_order_warehouses(
                frm,
                true
            );
        },


        // ----------------------------------------------------
        // Company changed
        // ----------------------------------------------------

        async company(frm) {

            if (
                !frm.doc.production_item ||
                !frm.doc.company
            ) {
                return;
            }


            /*
             * Item Defaults are company-specific.
             */
            await pc_fetch_work_order_warehouses(
                frm,
                true
            );
        }

    }
);