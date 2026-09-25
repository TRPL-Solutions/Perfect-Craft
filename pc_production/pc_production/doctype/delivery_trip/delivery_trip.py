import frappe
from frappe import _
from frappe.utils import flt


# ============================================================
# OLD WRONG CUSTOMIZATION CLEANUP
# ============================================================

def cleanup_old_customizations():
    """
    Remove custom fields created by previous incorrect versions.

    Correct implementation:
        Delivery Stop fields are maintained by delivery_trip.json.

    Delivery Note must not contain:
        custom_per_carton_charges
        custom_delivery_amount

    Old Delivery Stop field custom_carton must also not exist.
    """

    # --------------------------------------------------------
    # Remove wrong Delivery Note fields
    # --------------------------------------------------------

    for fieldname in (
        "custom_per_carton_charges",
        "custom_delivery_amount",
    ):

        custom_field_name = frappe.db.get_value(
            "Custom Field",
            {
                "dt": "Delivery Note",
                "fieldname": fieldname,
            },
            "name",
        )

        if custom_field_name:

            frappe.delete_doc(
                "Custom Field",
                custom_field_name,
                force=True,
                ignore_permissions=True,
            )


    # --------------------------------------------------------
    # Remove old wrong Carton field
    # --------------------------------------------------------

    old_carton_field = frappe.db.get_value(
        "Custom Field",
        {
            "dt": "Delivery Stop",
            "fieldname": "custom_carton",
        },
        "name",
    )

    if old_carton_field:

        frappe.delete_doc(
            "Custom Field",
            old_carton_field,
            force=True,
            ignore_permissions=True,
        )


# ============================================================
# DELIVERY STOP SCHEMA
# ============================================================

def sync_delivery_stop_schema():
    """
    delivery_trip.json contains Delivery Stop child fields.

    Explicit schema sync is required for the child DocType.
    """

    frappe.clear_cache(
        doctype="Delivery Stop"
    )

    frappe.db.updatedb(
        "Delivery Stop"
    )

    frappe.clear_cache(
        doctype="Delivery Stop"
    )


def after_migrate():

    cleanup_old_customizations()

    sync_delivery_stop_schema()

    frappe.clear_cache(
        doctype="Delivery Note"
    )

    frappe.clear_cache(
        doctype="Delivery Trip"
    )


# ============================================================
# DELIVERY NOTE QUANTITY
# ============================================================

def get_delivery_note_qty(delivery_note):
    """
    Get Total Quantity from submitted Delivery Note.
    """

    if not delivery_note:
        return 0


    delivery_note_data = frappe.db.get_value(
        "Delivery Note",
        delivery_note,
        [
            "total_qty",
            "docstatus",
        ],
        as_dict=True,
    )


    if not delivery_note_data:

        frappe.throw(
            _(
                "Delivery Note {0} does not exist."
            ).format(
                frappe.bold(delivery_note)
            )
        )


    if delivery_note_data.docstatus != 1:

        frappe.throw(
            _(
                "Delivery Note {0} must be submitted."
            ).format(
                frappe.bold(delivery_note)
            )
        )


    return flt(
        delivery_note_data.total_qty
    )


# ============================================================
# DELIVERY TRIP CALCULATION
# ============================================================

def calculate_delivery_charges(doc, method=None):
    """
    Delivery Trip calculation.

    For each Delivery Stop:

        Qty =
            linked Delivery Note Total Quantity

        Amount =
            Qty x Per Carton Charges

    Delivery Trip:

        Delivery Charges =
            sum of all row Amount values
    """

    total_delivery_charges = 0


    for row in doc.get("delivery_stops") or []:

        # ----------------------------------------------------
        # Qty
        # ----------------------------------------------------

        qty = 0

        if row.get("delivery_note"):

            qty = get_delivery_note_qty(
                row.delivery_note
            )


        row.custom_qty = flt(
            qty
        )


        # ----------------------------------------------------
        # Per Carton Charges
        # ----------------------------------------------------

        per_carton_charges = flt(
            row.get(
                "custom_per_carton_charges"
            )
        )


        if per_carton_charges < 0:

            frappe.throw(
                _(
                    "Row {0}: Per Carton Charges cannot be negative."
                ).format(
                    row.idx
                )
            )


        # ----------------------------------------------------
        # Amount
        # ----------------------------------------------------

        amount = flt(
            qty * per_carton_charges,
            2
        )


        row.custom_amount = amount


        # ----------------------------------------------------
        # Delivery Charges
        # ----------------------------------------------------

        total_delivery_charges += amount


    doc.custom_delivery_charges = flt(
        total_delivery_charges,
        2
    )