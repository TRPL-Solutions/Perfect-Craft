import frappe
from frappe import _
from frappe.utils import flt


# ============================================================
# DELIVERY NOTE (shown to users as "Gate Pass")
#
# Delivery Note Item:
#     Carton Amount (custom_carton_amount) = Qty x Carton
#
# Delivery Note:
#     Delivery Charges (custom_delivery_charges) = sum of Carton Amount
#
# These values are informational only. They do not touch the
# standard item rate/amount, taxes, stock or GL entries.
# The transport Purchase Invoice is still created from
# Delivery Trip (pc_production.delivery_trip).
# ============================================================


# Required once a Transporter is selected. Mirrors the
# mandatory_depends_on Property Setters in custom/delivery_note.json,
# which Frappe only enforces in the browser.
TRANSPORT_FIELDS = ("driver", "driver_name", "vehicle_no", "lr_date")


def validate_carton_required(doc, method=None):
    """Carton is required on outgoing Gate Passes (not returns).

    Mirrors mandatory_depends_on in custom/delivery_note_item.json.
    Runs in before_validate because ERPNext's validate rounds all item
    floats and turns an empty Carton into 0.
    """

    if doc.get("is_return"):
        return

    for row in doc.get("items") or []:
        if row.get("custom_carton") in (None, ""):
            frappe.throw(
                _("Row {0}: Carton is required.").format(row.idx),
                frappe.MandatoryError,
            )


def calculate_delivery_charges(doc, method=None):
    """Recalculate carton amounts and Delivery Charges on every save."""

    total_delivery_charges = 0

    for row in doc.get("items") or []:

        carton = flt(row.get("custom_carton"))

        if carton < 0:
            frappe.throw(
                _("Row {0}: Carton cannot be negative.").format(row.idx)
            )

        row.custom_carton = carton

        row.custom_carton_amount = flt(
            flt(row.qty) * carton,
            row.precision("custom_carton_amount"),
        )

        total_delivery_charges += row.custom_carton_amount

    doc.custom_delivery_charges = flt(
        total_delivery_charges,
        doc.precision("custom_delivery_charges"),
    )


def validate_transport_details(doc, method=None):
    """Once a Transporter is selected, Driver, Driver Name, Vehicle No
    and Transport Receipt Date are required, and a selected Driver must
    belong to that Transporter (Driver.transporter)."""

    if not doc.get("transporter"):
        return

    missing = [
        _(doc.meta.get_label(fieldname))
        for fieldname in TRANSPORT_FIELDS
        if not doc.get(fieldname)
    ]

    if missing:
        frappe.throw(
            _("The following fields are mandatory when Transporter is set: {0}").format(
                ", ".join(missing)
            ),
            frappe.MandatoryError,
        )

    if doc.get("driver"):
        driver_transporter = frappe.db.get_value("Driver", doc.driver, "transporter")

        if driver_transporter != doc.transporter:
            frappe.throw(
                _("Driver {0} is not linked with Transporter {1}.").format(
                    frappe.bold(doc.get("driver_name") or doc.driver),
                    frappe.bold(doc.transporter),
                )
            )
