app_name = "pc_production"
app_title = "PC Production"
app_publisher = "TRPL Solutions"
app_description = "Perfect Craft Production Costing"
app_email = "jaweriabibi098@gmail.com"
app_license = "mit"


auto_cancel_exempted_doctypes = [
    "Purchase Invoice"
]


# ============================================================
# FIXTURES
# ============================================================

fixtures = [

    {
        "dt": "Custom Field",
        "filters": [
            [
                "dt",
                "in",
                [
                    "Stock Reconciliation",
                    "Stock Reconciliation Item",
                    "Delivery Trip",
                ],
            ],
            [
                "fieldname",
                "in",
                [
                    "custom_expected_per_qty_amount",
                    "custom_actual_qty",
                    "custom_adjustment_per_qty",
                    "custom_production_expenses",
                    "custom_item_valuation_rate",
                    "custom_transporter",
                    "custom_supplier_name",
                    "custom_address",
                    "custom_gate_pass_date",
                    "custom_remarks",
                    "custom_delivery_charges",
                    "custom_purchase_invoice",
                ],
            ],
        ],
    },


    # ------------------------------------------------------------
    # Purchase Invoice -> Gate Pass reference
    # ------------------------------------------------------------

    {
        "dt": "Custom Field",
        "filters": [
            [
                "dt",
                "=",
                "Purchase Invoice",
            ],
            [
                "fieldname",
                "=",
                "custom_gate_pass",
            ],
        ],
    },


    # ------------------------------------------------------------
    # Stock Reconciliation Item - Valuation Rate label
    # ------------------------------------------------------------

    {
        "dt": "Property Setter",
        "filters": [
            [
                "doc_type",
                "=",
                "Stock Reconciliation Item",
            ],
            [
                "field_name",
                "=",
                "valuation_rate",
            ],
            [
                "property",
                "=",
                "label",
            ],
        ],
    },

]


# ============================================================
# DOCTYPE JAVASCRIPT
# ============================================================

doctype_js = {

    "Stock Entry":
        "public/js/stock_entry.js",

    "Stock Reconciliation":
        "public/js/stock_reconciliation.js",

    "BOM":
        "pc_production/doctype/bom/bom.js",

}


# ============================================================
# DOCTYPE CLASS OVERRIDES
# ============================================================

override_doctype_class = {

    "Stock Entry":
        "pc_production.stock_entry.CustomStockEntry",

}


# ============================================================
# DOCUMENT EVENTS
# ============================================================

doc_events = {

    # --------------------------------------------------------
    # Delivery Trip
    # --------------------------------------------------------

    "Delivery Trip": {

        "on_submit":
            "pc_production.delivery_trip.create_purchase_invoice",

        "on_cancel":
            "pc_production.delivery_trip.cancel_purchase_invoice",

        "on_trash":
            "pc_production.delivery_trip.delete_purchase_invoice",

    },


    # --------------------------------------------------------
    # Stock Entry
    # --------------------------------------------------------

    "Stock Entry": {

        "before_validate":
            "pc_production.stock_entry.apply_monthly_production_overhead",

    },


    # --------------------------------------------------------
    # Stock Reconciliation
    # --------------------------------------------------------

    "Stock Reconciliation": {

        "before_validate":
            "pc_production.stock_reconciliation.apply_stock_reconciliation_calculation",

        "before_submit":
            "pc_production.stock_reconciliation.validate_stock_reconciliation",

    },


    # --------------------------------------------------------
    # BOM
    #
    # Raw Material Qty + Scrap Qty = Qty
    # Scrap Item / Qty -> auto Scrap Items table
    # --------------------------------------------------------

    "BOM": {

        "before_validate":
            "pc_production.pc_production.doctype.bom.bom.sync_raw_material_and_scrap",

    },

}


# ============================================================
# PERFECT CRAFT CUSTOM PRINT FORMATS
# ============================================================

jinja = {

    "methods": [

        "pc_production.print_utils.get_sales_order_print_context",

        "pc_production.print_utils.get_delivery_trip_print_context",

        "pc_production.print_utils.get_gate_pass_print_context",

        "pc_production.sales_invoice_print.get_sales_invoice_print_context",

    ]

}


# ============================================================
# AFTER MIGRATE
# ============================================================
#
# IMPORTANT:
#
# custom/bom.json contains BOM Item custom fields.
#
# Frappe first syncs customizations during migrate.
# After that we explicitly update the BOM Item DB schema so
# columns such as:
#
# custom_raw_material_qty
# custom_scrap_item
# custom_scrap_qty
#
# exist in `tabBOM Item`.
#
# ============================================================

after_migrate = [

    # --------------------------------------------------------
    # BOM Item schema sync
    # --------------------------------------------------------

    "pc_production.pc_production.doctype.bom.bom.after_migrate",


    # --------------------------------------------------------
    # Print Formats
    # --------------------------------------------------------

    "pc_production.print_utils.ensure_sales_order_print_format",

    "pc_production.print_utils.ensure_delivery_trip_print_format",

    "pc_production.print_utils.ensure_gate_pass_print_format",

    "pc_production.sales_invoice_print.ensure_sales_invoice_print_format",

]