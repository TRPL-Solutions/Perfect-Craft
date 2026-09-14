import frappe
from frappe import _
from frappe.utils import flt, today


TRANSPORT_CHARGES_ITEM = "Transport Charges"


def _get_transport_charges_item():
    items = frappe.db.sql(
        """
        SELECT name
        FROM `tabItem`
        WHERE LOWER(TRIM(item_name)) = LOWER(TRIM(%s))
        ORDER BY disabled ASC, name ASC
        LIMIT 1
        """,
        (TRANSPORT_CHARGES_ITEM,),
        as_dict=True,
    )

    if not items:
        frappe.throw(
            _(
                "No Item was found with Item Name {0}. Create a service item "
                "with this name before submitting a Delivery Trip."
            ).format(frappe.bold(TRANSPORT_CHARGES_ITEM))
        )

    return items[0].name


def _get_purchase_invoice(delivery_trip):
    if not delivery_trip.get("custom_purchase_invoice"):
        return None

    return frappe.get_doc(
        "Purchase Invoice",
        delivery_trip.custom_purchase_invoice,
    )


def _validate_delivery_trip(delivery_trip):
    missing = []
    transporter = delivery_trip.get("custom_transporter")
    delivery_charges = delivery_trip.get("custom_delivery_charges")

    if not delivery_trip.company:
        missing.append(_("Company"))

    if not transporter:
        missing.append(_("Transporter"))

    if flt(delivery_charges) <= 0:
        frappe.throw(_("Delivery Charges must be greater than zero."))

    if missing:
        frappe.throw(
            _("The following fields are mandatory: {0}").format(
                ", ".join(missing)
            )
        )

def create_purchase_invoice(delivery_trip, method=None):
    """Create and submit one transport-charge invoice per Delivery Trip."""
    if delivery_trip.get("custom_purchase_invoice"):
        frappe.throw(
            _(
                "Purchase Invoice {0} is already linked with this Delivery Trip."
            ).format(frappe.bold(delivery_trip.custom_purchase_invoice))
        )

    _validate_delivery_trip(delivery_trip)
    transport_item_code = _get_transport_charges_item()

    invoice = frappe.new_doc("Purchase Invoice")
    invoice.supplier = delivery_trip.get("custom_transporter")
    invoice.company = delivery_trip.company
    invoice.posting_date = delivery_trip.get("custom_gate_pass_date") or today()
    invoice.remarks = _("Generated from Delivery Trip {0}.").format(
        delivery_trip.name
    )
    invoice.append(
        "items",
        {
            "item_code": transport_item_code,
            "qty": 1,
            "rate": flt(delivery_trip.get("custom_delivery_charges")),
        },
    )
    invoice.insert(ignore_permissions=True)
    invoice.submit()

    delivery_trip.db_set(
        "custom_purchase_invoice",
        invoice.name,
        update_modified=False,
    )


def cancel_purchase_invoice(delivery_trip, method=None):
    invoice = _get_purchase_invoice(delivery_trip)

    if not invoice:
        return

    if invoice.docstatus == 1:
        invoice.cancel()
    elif invoice.docstatus != 2:
        frappe.throw(
            _(
                "Purchase Invoice {0} must be submitted or cancelled before "
                "the Delivery Trip can be cancelled."
            ).format(frappe.bold(invoice.name))
        )


def delete_purchase_invoice(delivery_trip, method=None):
    invoice = _get_purchase_invoice(delivery_trip)

    if not invoice:
        return

    if delivery_trip.docstatus != 2 or invoice.docstatus != 2:
        frappe.throw(
            _(
                "Delivery Trip and its Purchase Invoice must both be cancelled "
                "before deletion."
            )
        )

    frappe.delete_doc(
        "Purchase Invoice",
        invoice.name,
        ignore_permissions=True,
        force=True,
    )