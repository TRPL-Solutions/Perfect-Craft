import frappe
from frappe import _
from frappe.utils import flt


# ============================================================
# SCHEMA SYNC
# ============================================================

def sync_bom_item_schema():
    """
    Required because Perfect Craft keeps BOM Item custom fields
    inside custom/bom.json instead of a separate bom_item.json.

    Frappe syncs the Custom Field metadata, but the physical
    columns must also be created in `tabBOM Item`.
    """

    frappe.clear_cache(doctype="BOM Item")

    frappe.db.updatedb("BOM Item")

    frappe.clear_cache(doctype="BOM Item")


def after_migrate():
    """
    Runs after bench migrate.

    At this stage custom/bom.json has already been synced,
    therefore Custom Field records exist and updatedb can
    safely create/update the BOM Item database columns.
    """

    sync_bom_item_schema()


# ============================================================
# BOM RAW MATERIAL + SCRAP AUTOMATION
# ============================================================

def sync_raw_material_and_scrap(doc, method=None):
    """
    Perfect Craft BOM automation.

    Raw Material Qty + Scrap Qty = Qty

    Example:

        Raw Material Qty = 100
        Scrap Qty        = 10
        Qty              = 110

    Scrap Item / Scrap Qty entered in BOM Item are copied
    automatically to the standard BOM Scrap Items table.
    """

    items = doc.get("items") or []

    if not items:
        return


    scrap_totals = {}


    # ========================================================
    # RAW MATERIAL ROWS
    # ========================================================

    for row in items:

        raw_qty = flt(
            row.get("custom_raw_material_qty")
        )

        scrap_qty = flt(
            row.get("custom_scrap_qty")
        )

        scrap_item = row.get(
            "custom_scrap_item"
        )


        # ====================================================
        # EXISTING BOM SUPPORT
        # ====================================================
        #
        # Existing BOMs already have standard Qty.
        #
        # If Raw Material Qty has not yet been populated,
        # preserve the existing Qty as Raw Material Qty.
        # ====================================================

        if (
            raw_qty <= 0
            and flt(row.qty) > 0
            and not scrap_item
            and scrap_qty <= 0
        ):

            raw_qty = flt(row.qty)

            row.custom_raw_material_qty = raw_qty


        # ====================================================
        # VALIDATION
        # ====================================================

        if raw_qty < 0:

            frappe.throw(
                _(
                    "Row {0}: Raw Material Qty cannot be negative."
                ).format(row.idx)
            )


        if scrap_qty < 0:

            frappe.throw(
                _(
                    "Row {0}: Scrap Qty cannot be negative."
                ).format(row.idx)
            )


        if scrap_qty > 0 and not scrap_item:

            frappe.throw(
                _(
                    "Row {0}: Please select Scrap Item."
                ).format(row.idx)
            )


        if scrap_item and scrap_qty <= 0:

            frappe.throw(
                _(
                    "Row {0}: Please enter Scrap Qty for Scrap Item {1}."
                ).format(
                    row.idx,
                    frappe.bold(scrap_item)
                )
            )


        if (
            (scrap_item or scrap_qty > 0)
            and raw_qty <= 0
        ):

            frappe.throw(
                _(
                    "Row {0}: Please enter Raw Material Qty."
                ).format(row.idx)
            )


        # ====================================================
        # FINAL RAW MATERIAL CONSUMPTION
        # ====================================================
        #
        # Qty = Raw Material Qty + Scrap Qty
        # ====================================================

        if raw_qty > 0 or scrap_qty > 0:

            row.qty = flt(
                raw_qty + scrap_qty,
                row.precision("qty")
            )


        # ====================================================
        # COLLECT SCRAP
        # ====================================================

        if scrap_item and scrap_qty > 0:

            scrap_totals[scrap_item] = (
                flt(
                    scrap_totals.get(
                        scrap_item,
                        0
                    )
                )
                + scrap_qty
            )


    # ========================================================
    # STANDARD BOM SCRAP TABLE
    #
    # Scrap & Process Loss table is generated automatically.
    # User does not maintain it manually.
    # ========================================================

    doc.set(
        "scrap_items",
        []
    )


    for scrap_item, scrap_qty in scrap_totals.items():

        if not scrap_item:
            continue


        if flt(scrap_qty) <= 0:
            continue


        scrap_row = doc.append(
            "scrap_items",
            {}
        )


        scrap_row.item_code = scrap_item


        # ERPNext v15 BOM Scrap Item quantity field.
        scrap_row.stock_qty = flt(
            scrap_qty
        )