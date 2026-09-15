app_name = "pc_production"
app_title = "PC Production"
app_publisher = "TRPL Solutions"
app_description = "Perfect Craft Production Costing"
app_email = "jaweriabibi098@gmail.com"
app_license = "mit"

auto_cancel_exempted_doctypes = ["Purchase Invoice"]


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


doctype_js = {
    "Stock Reconciliation":
        "public/js/stock_reconciliation.js"
}


doc_events = {
    "Delivery Trip": {
        "on_submit":
            "pc_production.delivery_trip.create_purchase_invoice",
        "on_cancel":
            "pc_production.delivery_trip.cancel_purchase_invoice",
        "on_trash":
            "pc_production.delivery_trip.delete_purchase_invoice",
    },

    "Stock Entry": {
        "before_validate":
            "pc_production.stock_entry.apply_monthly_production_overhead"
    },

    "Stock Reconciliation": {
        "before_validate":
            "pc_production.stock_reconciliation.apply_stock_reconciliation_calculation",

        "before_submit":
            "pc_production.stock_reconciliation.validate_stock_reconciliation",
    },
}


# Perfect Craft custom print formats
jinja = {
    "methods": [
        "pc_production.print_utils.get_sales_order_print_context",
        "pc_production.print_utils.get_delivery_trip_print_context",
        "pc_production.sales_invoice_print.get_sales_invoice_print_context",
    ]
}

after_migrate = [
    "pc_production.print_utils.ensure_sales_order_print_format",
    "pc_production.print_utils.ensure_delivery_trip_print_format",
    "pc_production.sales_invoice_print.ensure_sales_invoice_print_format",
]
