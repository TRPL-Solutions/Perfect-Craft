import frappe
from frappe import _


# ============================================================
# ITEM WAREHOUSE DEFAULTS
# ============================================================

@frappe.whitelist()
def get_item_warehouse_defaults(item_code=None, company=None):
    """
    Get Work Order warehouse defaults from Production Item.

    Item Default:
        default_warehouse
            -> Work Order Target Warehouse

        custom_scrap_warehouse
            -> Work Order Scrap Warehouse
    """

    if not item_code or not company:
        return {
            "target_warehouse": None,
            "scrap_warehouse": None,
        }


    item_default = frappe.db.get_value(
        "Item Default",
        {
            "parent": item_code,
            "parenttype": "Item",
            "company": company,
        },
        [
            "default_warehouse",
            "custom_scrap_warehouse",
        ],
        as_dict=True,
    )


    if not item_default:
        return {
            "target_warehouse": None,
            "scrap_warehouse": None,
        }


    return {
        "target_warehouse": item_default.default_warehouse,
        "scrap_warehouse": item_default.custom_scrap_warehouse,
    }


# ============================================================
# WORK ORDER AUTO FETCH
# ============================================================

def set_work_order_warehouses(doc, method=None):
    """
    Automatically set Target Warehouse and Scrap Warehouse
    from the selected Production Item's Item Defaults.

    On a new Work Order:
        Item Default.default_warehouse
            -> fg_warehouse

        Item Default.custom_scrap_warehouse
            -> scrap_warehouse

    On an existing Work Order:
        only fill a warehouse if it is blank, so an intentional
        manual override is not overwritten on every save.
    """

    if not doc.production_item or not doc.company:
        return


    defaults = get_item_warehouse_defaults(
        item_code=doc.production_item,
        company=doc.company,
    )


    target_warehouse = defaults.get(
        "target_warehouse"
    )

    scrap_warehouse = defaults.get(
        "scrap_warehouse"
    )


    # ========================================================
    # TARGET WAREHOUSE
    # ========================================================

    if doc.is_new() or not doc.fg_warehouse:
        if target_warehouse:
            doc.fg_warehouse = target_warehouse


    # ========================================================
    # SCRAP WAREHOUSE
    # ========================================================

    if doc.is_new() or not doc.scrap_warehouse:
        if scrap_warehouse:
            doc.scrap_warehouse = scrap_warehouse