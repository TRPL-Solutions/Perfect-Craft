// // ============================================================
// // PERFECT CRAFT
// // BOM RAW MATERIAL + SCRAP AUTOMATION
// //
// // Raw Material Qty + Scrap Qty = Qty
// //
// // Scrap Item / Qty from BOM Item is automatically copied
// // to standard BOM Scrap Items table.
// // ============================================================


// // ============================================================
// // CALCULATE ONE RAW MATERIAL ROW
// // ============================================================

// function pc_calculate_bom_item_qty(frm, cdt, cdn) {

//     const row = locals[cdt][cdn];

//     if (!row) {
//         return;
//     }


//     let raw_qty =
//         flt(row.custom_raw_material_qty);


//     let scrap_qty =
//         flt(row.custom_scrap_qty);


//     // --------------------------------------------------------
//     // LEGACY / EXISTING DRAFT BOM SUPPORT
//     // --------------------------------------------------------
//     //
//     // Existing BOM row has Qty but new Raw Material Qty
//     // is empty.
//     //
//     // Do this only when scrap customization has not yet
//     // been entered.
//     // --------------------------------------------------------

//     if (
//         raw_qty <= 0 &&
//         flt(row.qty) > 0 &&
//         !row.custom_scrap_item &&
//         scrap_qty <= 0
//     ) {

//         raw_qty = flt(row.qty);

//         frappe.model.set_value(
//             cdt,
//             cdn,
//             "custom_raw_material_qty",
//             raw_qty
//         );
//     }


//     // --------------------------------------------------------
//     // CALCULATE TOTAL
//     // --------------------------------------------------------

//     const total_qty =
//         flt(raw_qty) +
//         flt(scrap_qty);


//     frappe.model.set_value(
//         cdt,
//         cdn,
//         "qty",
//         total_qty
//     );
// }


// // ============================================================
// // BUILD SCRAP TABLE FROM RAW MATERIAL ROWS
// // ============================================================

// async function pc_sync_bom_scrap_items(frm) {

//     if (frm.__pc_scrap_sync_running) {
//         return;
//     }


//     frm.__pc_scrap_sync_running = true;


//     try {

//         const scrap_map = {};


//         // ----------------------------------------------------
//         // COLLECT SCRAP
//         // ----------------------------------------------------

//         (frm.doc.items || []).forEach(row => {

//             const scrap_item =
//                 row.custom_scrap_item;


//             const scrap_qty =
//                 flt(row.custom_scrap_qty);


//             if (
//                 scrap_item &&
//                 scrap_qty > 0
//             ) {

//                 if (!scrap_map[scrap_item]) {
//                     scrap_map[scrap_item] = 0;
//                 }


//                 scrap_map[scrap_item] +=
//                     scrap_qty;
//             }
//         });


//         // If none of the Perfect Craft scrap fields are used,
//         // do not disturb existing standard Scrap Items.

//         if (
//             Object.keys(scrap_map).length === 0
//         ) {
//             return;
//         }


//         // ----------------------------------------------------
//         // RAW MATERIAL ROWS ARE SOURCE OF TRUTH
//         // ----------------------------------------------------

//         frm.clear_table("scrap_items");


//         // ----------------------------------------------------
//         // CREATE STANDARD BOM SCRAP ITEMS
//         // ----------------------------------------------------

//         for (
//             const [
//                 scrap_item,
//                 scrap_qty
//             ]
//             of Object.entries(scrap_map)
//         ) {

//             const scrap_row =
//                 frm.add_child("scrap_items");


//             // Setting Item Code this way lets ERPNext's
//             // standard BOM Item handler fetch item details.

//             await frappe.model.set_value(
//                 scrap_row.doctype,
//                 scrap_row.name,
//                 "item_code",
//                 scrap_item
//             );


//             // IMPORTANT:
//             // BOM Scrap Item uses stock_qty as its Qty field.

//             await frappe.model.set_value(
//                 scrap_row.doctype,
//                 scrap_row.name,
//                 "stock_qty",
//                 flt(scrap_qty)
//             );
//         }


//         frm.refresh_field(
//             "scrap_items"
//         );


//     } finally {

//         frm.__pc_scrap_sync_running = false;
//     }
// }


// // ============================================================
// // UPDATE ALL ROWS
// // ============================================================

// async function pc_recalculate_all_bom_rows(frm) {

//     for (
//         const row
//         of (frm.doc.items || [])
//     ) {

//         pc_calculate_bom_item_qty(
//             frm,
//             row.doctype,
//             row.name
//         );
//     }


//     await pc_sync_bom_scrap_items(frm);
// }


// // ============================================================
// // BOM PARENT
// // ============================================================

// frappe.ui.form.on("BOM", {

//     setup(frm) {

//         // Scrap Item should only allow enabled stock items.

//         frm.set_query(
//             "custom_scrap_item",
//             "items",
//             function () {

//                 return {
//                     filters: {
//                         disabled: 0,
//                         is_stock_item: 1
//                     }
//                 };
//             }
//         );
//     },


//     refresh(frm) {

//         // ----------------------------------------------------
//         // KEEP STANDARD QTY READ ONLY
//         // ----------------------------------------------------

//         if (
//             frm.fields_dict.items &&
//             frm.fields_dict.items.grid
//         ) {

//             frm.fields_dict.items.grid
//                 .update_docfield_property(
//                     "qty",
//                     "read_only",
//                     1
//                 );


//             frm.fields_dict.items.grid
//                 .reset_grid();
//         }
//     },


//     async validate(frm) {

//         await pc_recalculate_all_bom_rows(
//             frm
//         );
//     }

// });


// // ============================================================
// // BOM ITEM CHILD TABLE
// // ============================================================

// frappe.ui.form.on("BOM Item", {


//     // --------------------------------------------------------
//     // RAW MATERIAL QTY
//     // --------------------------------------------------------

//     async custom_raw_material_qty(
//         frm,
//         cdt,
//         cdn
//     ) {

//         const row =
//             locals[cdt][cdn];


//         if (
//             flt(
//                 row.custom_raw_material_qty
//             ) < 0
//         ) {

//             await frappe.model.set_value(
//                 cdt,
//                 cdn,
//                 "custom_raw_material_qty",
//                 0
//             );

//             frappe.msgprint(
//                 __("Raw Material Qty cannot be negative.")
//             );

//             return;
//         }


//         pc_calculate_bom_item_qty(
//             frm,
//             cdt,
//             cdn
//         );


//         await pc_sync_bom_scrap_items(
//             frm
//         );
//     },


//     // --------------------------------------------------------
//     // SCRAP ITEM
//     // --------------------------------------------------------

//     async custom_scrap_item(
//         frm,
//         cdt,
//         cdn
//     ) {

//         const row =
//             locals[cdt][cdn];


//         // Scrap Item removed -> clear Scrap Qty too.

//         if (
//             !row.custom_scrap_item &&
//             flt(row.custom_scrap_qty) > 0
//         ) {

//             await frappe.model.set_value(
//                 cdt,
//                 cdn,
//                 "custom_scrap_qty",
//                 0
//             );
//         }


//         pc_calculate_bom_item_qty(
//             frm,
//             cdt,
//             cdn
//         );


//         await pc_sync_bom_scrap_items(
//             frm
//         );
//     },


//     // --------------------------------------------------------
//     // SCRAP QTY
//     // --------------------------------------------------------

//     async custom_scrap_qty(
//         frm,
//         cdt,
//         cdn
//     ) {

//         const row =
//             locals[cdt][cdn];


//         if (
//             flt(
//                 row.custom_scrap_qty
//             ) < 0
//         ) {

//             await frappe.model.set_value(
//                 cdt,
//                 cdn,
//                 "custom_scrap_qty",
//                 0
//             );


//             frappe.msgprint(
//                 __("Scrap Qty cannot be negative.")
//             );

//             return;
//         }


//         pc_calculate_bom_item_qty(
//             frm,
//             cdt,
//             cdn
//         );


//         await pc_sync_bom_scrap_items(
//             frm
//         );
//     },


//     // --------------------------------------------------------
//     // RAW MATERIAL ROW REMOVED
//     // --------------------------------------------------------

//     async items_remove(frm) {

//         await pc_sync_bom_scrap_items(
//             frm
//         );
//     }

// });

// ============================================================
// BOM CHILD TABLES: SHOW ITEM NAME INSTEAD OF ITEM CODE
//
// Item link fields in the Items, Scrap Items and Exploded Items
// tables of a BOM display the Item Name. The saved value is
// still the Item Code; only what the user sees changes.
//
// Only rows whose parent is a BOM are affected. Other doctypes
// keep ERPNext's default "Item Code: Item Name" display.
// ============================================================

// Shared across re-runs of this script (Frappe re-runs doctype JS
// on every form setup, but the patches below are applied once).
frappe.pc_bom_item_names = frappe.pc_bom_item_names || {
    // item_code -> item_name
    names: {},
    // item_code -> pending request
    requests: {},
};

const PC_BOM_CHILD_DOCTYPES = ["BOM Item", "BOM Scrap Item", "BOM Explosion Item"];
const PC_BOM_CHILD_TABLES = ["items", "scrap_items", "exploded_items"];
const PC_BOM_ITEM_LINK_FIELDS = ["item_code", "custom_scrap_item", "original_item"];


function pc_is_bom_child_item_link(doc, link_doctype) {
    return (
        link_doctype === "Item" &&
        !!doc &&
        doc.parenttype === "BOM" &&
        PC_BOM_CHILD_DOCTYPES.includes(doc.doctype)
    );
}


function pc_get_known_item_name(item_code, row) {
    const names = frappe.pc_bom_item_names.names;

    if (names[item_code]) {
        return names[item_code];
    }

    if (row && row.item_code === item_code && row.item_name) {
        return row.item_name;
    }

    return null;
}


function pc_fetch_item_name(item_code) {
    const cache = frappe.pc_bom_item_names;

    if (cache.names[item_code]) {
        return Promise.resolve(cache.names[item_code]);
    }

    if (!cache.requests[item_code]) {
        cache.requests[item_code] = frappe.db
            .get_value("Item", item_code, "item_name")
            .then((r) => {
                const item_name = (r && r.message && r.message.item_name) || item_code;
                cache.names[item_code] = item_name;
                return item_name;
            })
            .catch(() => item_code)
            .finally(() => {
                delete cache.requests[item_code];
            });
    }

    return cache.requests[item_code];
}


// Load names for every item used in this BOM in one call, then
// redraw the tables so the grid shows names instead of codes.
async function pc_load_bom_item_names(frm) {
    const names = frappe.pc_bom_item_names.names;
    const missing = new Set();

    PC_BOM_CHILD_TABLES.forEach((table) => {
        (frm.doc[table] || []).forEach((row) => {
            PC_BOM_ITEM_LINK_FIELDS.forEach((fieldname) => {
                const item_code = row[fieldname];

                if (item_code && !names[item_code]) {
                    missing.add(item_code);
                }
            });
        });
    });

    if (!missing.size) {
        return;
    }

    const items = await frappe.db.get_list("Item", {
        filters: { name: ["in", Array.from(missing)] },
        fields: ["name", "item_name"],
        limit: missing.size,
    });

    (items || []).forEach((item) => {
        names[item.name] = item.item_name || item.name;
    });

    PC_BOM_CHILD_TABLES.forEach((table) => frm.refresh_field(table));
}


// ------------------------------------------------------------
// Read-only display (grid cells, submitted BOM)
// ------------------------------------------------------------

if (!frappe.pc_bom_item_names.formatter_patched) {
    const erpnext_item_formatter = frappe.form.link_formatters["Item"];

    frappe.form.link_formatters["Item"] = function (value, doc, docfield) {
        if (value && pc_is_bom_child_item_link(doc, "Item")) {
            const item_name = pc_get_known_item_name(value, doc);

            if (item_name) {
                return item_name;
            }
        }

        return erpnext_item_formatter
            ? erpnext_item_formatter(value, doc, docfield)
            : value;
    };

    frappe.pc_bom_item_names.formatter_patched = true;
}


// ------------------------------------------------------------
// Input box while a row is being edited
//
// Same approach Frappe uses for "Show Title in Link Fields", but
// only for these controls: the input shows the Item Name and
// maps it back to the Item Code, so the saved value is unchanged.
// ------------------------------------------------------------

if (!frappe.pc_bom_item_names.control_patched) {
    const original_set_link_title = frappe.ui.form.ControlLink.prototype.set_link_title;

    frappe.ui.form.ControlLink.prototype.set_link_title = async function (value) {
        if (value && pc_is_bom_child_item_link(this.doc, this.get_options())) {
            const item_name = await pc_fetch_item_name(value);

            // skip if the field changed while the name was loading
            if (this.value === value) {
                this.translate_and_set_input_value(item_name, value);
            }

            return;
        }

        return original_set_link_title.call(this, value);
    };

    frappe.pc_bom_item_names.control_patched = true;
}


frappe.ui.form.on("BOM", {
    refresh(frm) {
        pc_load_bom_item_names(frm);
    },
});
