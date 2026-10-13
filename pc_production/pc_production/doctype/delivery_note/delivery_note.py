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
# These values do not touch the standard item rate/amount, taxes,
# stock or GL entries of the Delivery Note itself.
#
# On submit, Delivery Charges are invoiced to the Transporter through
# one Purchase Invoice per Gate Pass (see TRANSPORT PURCHASE INVOICE).
# Delivery Trip keeps its own, separate transport invoice
# (pc_production.delivery_trip) - approved as an independent service.
# ============================================================


# Required once a Transporter is selected. Mirrors the
# mandatory_depends_on Property Setters in custom/delivery_note.json,
# which Frappe only enforces in the browser.
TRANSPORT_FIELDS = ("driver", "driver_name", "vehicle_no", "lr_date")

# Referenced by exact Item Code: two Items share the name
# "Transport Charges" (codes "PC" and "Transport Charges").
TRANSPORT_ITEM_CODE = "Transport Charges"


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
    and Transport Receipt Date are required."""

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


# ============================================================
# TRANSPORT PURCHASE INVOICE
#
# Ownership: Purchase Invoice.custom_delivery_note (read-only,
# no_copy) is set only here and identifies the Gate Pass an invoice
# belongs to. Duplicate checks and cancellation use only this field.
# ============================================================


def _requires_transport_invoice(doc):
    return not doc.get("is_return") and flt(doc.get("custom_delivery_charges")) > 0



def _validate_not_already_invoiced(doc):
    """Draft or submitted invoices count; cancelled ones do not."""

    existing = frappe.get_all(
        "Purchase Invoice",
        filters={"custom_delivery_note": doc.name, "docstatus": ["<", 2]},
        pluck="name",
    )

    if existing:
        frappe.throw(
            _("Purchase Invoice {0} already exists for this Gate Pass.").format(
                frappe.bold(existing[0])
            )
        )


def validate_transport_invoice(doc, method=None):
    """before_submit: fail before any stock/GL posting if the
    transport invoice cannot be created."""

    if not _requires_transport_invoice(doc):
        return

    if not doc.get("transporter"):
        frappe.throw(
            _("Transporter is required when Delivery Charges are greater than zero."),
            frappe.MandatoryError,
        )

    supplier = frappe.db.get_value(
        "Supplier", doc.transporter, ["name", "disabled"], as_dict=True
    )

    if not supplier:
        frappe.throw(_("Transporter {0} does not exist.").format(frappe.bold(doc.transporter)))

    if supplier.disabled:
        frappe.throw(_("Transporter {0} is disabled.").format(frappe.bold(doc.transporter)))

    item = frappe.db.get_value(
        "Item",
        TRANSPORT_ITEM_CODE,
        ["disabled", "is_purchase_item", "is_stock_item"],
        as_dict=True,
    )

    if not item or item.disabled or not item.is_purchase_item or item.is_stock_item:
        frappe.throw(
            _(
                "Item {0} must exist as an enabled, non-stock purchase item "
                "to invoice Delivery Charges."
            ).format(frappe.bold(TRANSPORT_ITEM_CODE))
        )

    _validate_not_already_invoiced(doc)


def create_transport_purchase_invoice(doc, method=None):
    """on_submit: create and submit one transport Purchase Invoice for
    the Gate Pass Delivery Charges, in the same transaction."""

    if not _requires_transport_invoice(doc):
        return

    # Serialise concurrent attempts for the same Gate Pass.
    frappe.db.get_value("Delivery Note", doc.name, "name", for_update=True)

    _validate_not_already_invoiced(doc)

    invoice = frappe.new_doc("Purchase Invoice")
    invoice.supplier = doc.transporter
    invoice.company = doc.company
    invoice.set_posting_time = 1
    invoice.posting_date = doc.posting_date
    invoice.custom_delivery_note = doc.name
    invoice.remarks = _("Transport charges for Gate Pass {0}.").format(doc.name)
    invoice.append(
        "items",
        {
            "item_code": TRANSPORT_ITEM_CODE,
            "qty": 1,
            "rate": flt(doc.custom_delivery_charges),
            "cost_center": doc.get("cost_center"),
        },
    )
    invoice.insert(ignore_permissions=True)
    invoice.submit()

    doc.db_set(
        "custom_transport_purchase_invoice",
        invoice.name,
        update_modified=False,
    )


def cancel_transport_purchase_invoice(doc, method=None):
    """on_cancel: cancel only the invoice(s) owned by this Gate Pass.
    Standard Purchase Invoice cancel permissions and checks apply."""

    for name in frappe.get_all(
        "Purchase Invoice",
        filters={"custom_delivery_note": doc.name, "docstatus": 1},
        pluck="name",
    ):
        frappe.get_doc("Purchase Invoice", name).cancel()

    # Amend copies this link; a link to a cancelled invoice would fail
    # link validation on the amended Gate Pass. The cancelled invoice
    # still references this Gate Pass via custom_delivery_note.
    if doc.get("custom_transport_purchase_invoice"):
        doc.db_set("custom_transport_purchase_invoice", None, update_modified=False)


def delete_transport_purchase_invoice(doc, method=None):
    """on_trash: delete the cancelled invoice(s) owned by this Gate Pass.

    frappe.delete_doc runs on_trash before its incoming-link check, so
    removing the owned invoice here lets that check pass. Standard delete
    permissions and the invoice's own link checks still apply; any
    failure aborts the whole Gate Pass deletion (same transaction).
    """

    invoices = frappe.get_all(
        "Purchase Invoice",
        filters={"custom_delivery_note": doc.name},
        fields=["name", "docstatus"],
    )

    active = [d.name for d in invoices if d.docstatus != 2]

    # A deletable Gate Pass is draft or cancelled; an owned invoice that is
    # not cancelled (or any owned invoice on a draft) is inconsistent data.
    if active or (invoices and doc.docstatus == 0):
        frappe.throw(
            _(
                "Gate Pass {0} cannot be deleted: its transport Purchase Invoice {1} "
                "is not in a consistent state. Please review it first."
            ).format(
                frappe.bold(doc.name),
                ", ".join(frappe.bold(name) for name in (active or [d.name for d in invoices])),
            )
        )

    if doc.get("custom_transport_purchase_invoice"):
        doc.db_set("custom_transport_purchase_invoice", None, update_modified=False)

    for invoice in invoices:
        frappe.delete_doc("Purchase Invoice", invoice.name)
