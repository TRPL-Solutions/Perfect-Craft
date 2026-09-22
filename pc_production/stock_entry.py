# import frappe
# from frappe import _
# from frappe.utils import cint, flt, getdate


# AUTO_PREFIX = "Monthly Production Overhead |"


# def apply_monthly_production_overhead(doc, method=None):
#     """
#     Add monthly production overhead to Manufacture Stock Entry.

#     Match Monthly Production Setting dynamically using:
#         Company
#         Cost Center
#         Posting Date

#     No Company / Cost Center is hard-coded.
#     """

#     if doc.docstatus != 0:
#         return

#     sync_item_cost_centers(doc)

#     # Remove only our previous generated rows from drafts.
#     # Submitted entries must retain their persisted overhead rows.
#     remove_auto_overhead_rows(doc)

#     if doc.purpose != "Manufacture":
#         return

#     if not doc.company or not doc.posting_date:
#         return

#     finished_rows = get_finished_goods_rows(doc)

#     if not finished_rows:
#         # During incomplete draft, simply wait until
#         # Finished Good is selected.
#         return

#     if len(finished_rows) > 1:
#         frappe.throw(
#             _(
#                 "Monthly Production Overhead supports "
#                 "one Finished Good item per Manufacture Stock Entry."
#             )
#         )

#     finished_row = finished_rows[0]

#     # Stock UOM quantity.
#     finished_qty = flt(
#         finished_row.transfer_qty
#     )

#     if finished_qty <= 0:
#         finished_qty = (
#             flt(finished_row.qty)
#             * flt(
#                 finished_row.conversion_factor or 1
#             )
#         )

#     if finished_qty <= 0:
#         return

#     # Prefer parent Cost Center.
#     # If blank, use Finished Good row Cost Center.
#     cost_center = (
#         doc.cost_center
#         or finished_row.cost_center
#     )

#     setting = get_monthly_setting(
#         company=doc.company,
#         cost_center=cost_center,
#         posting_date=doc.posting_date,
#     )

#     expected_qty = flt(
#         setting.expected_qty
#     )

#     if expected_qty <= 0:
#         frappe.throw(
#             _(
#                 "Expected Qty must be greater than zero "
#                 "in Monthly Production Setting {0}."
#             ).format(
#                 frappe.bold(setting.name)
#             )
#         )

#     # If Cost Center was blank but exactly one setting
#     # resolved it, apply it to the document.
#     if not doc.cost_center:
#         doc.cost_center = setting.cost_center
#         sync_item_cost_centers(doc)

#     total_allocated = 0

#     for expense in setting.expenses:

#         if not expense.type_of_expense:
#             continue

#         expense_amount = flt(
#             expense.expense_amount
#         )

#         if expense_amount <= 0:
#             continue

#         # Expected expense cost per unit.
#         expense_per_qty = (
#             expense_amount /
#             expected_qty
#         )

#         # Amount allocated to THIS Manufacture entry.
#         allocated_amount = (
#             expense_per_qty *
#             finished_qty
#         )

#         doc.append(
#             "additional_costs",
#             {
#                 "expense_account":
#                     expense.type_of_expense,

#                 "description":
#                     (
#                         f"{AUTO_PREFIX} "
#                         f"{setting.name} | "
#                         f"{expense.type_of_expense}"
#                     ),

#                 "amount":
#                     allocated_amount,
#             },
#         )

#         total_allocated += (
#             allocated_amount
#         )

#     if total_allocated <= 0:
#         frappe.throw(
#             _(
#                 "No production overhead amount found in "
#                 "Monthly Production Setting {0}."
#             ).format(
#                 frappe.bold(setting.name)
#             )
#         )


# def get_finished_goods_rows(doc):
#     """
#     Use ERPNext's standard is_finished_item field.

#     Do NOT depend only on Item Group name.
#     """

#     finished_rows = []

#     for row in doc.get("items") or []:

#         if not row.item_code:
#             continue

#         # Primary ERPNext method.
#         if cint(row.is_finished_item):
#             finished_rows.append(row)

#     if finished_rows:
#         return finished_rows

#     # Safe fallback for older/manually prepared Manufacture
#     # Stock Entries:
#     #
#     # Incoming row, not scrap, no source warehouse.
#     for row in doc.get("items") or []:

#         if not row.item_code:
#             continue

#         if not row.t_warehouse:
#             continue

#         if row.s_warehouse:
#             continue

#         if cint(row.is_scrap_item):
#             continue

#         finished_rows.append(row)

#     return finished_rows


# def get_monthly_setting(
#     company,
#     cost_center,
#     posting_date,
# ):
#     """
#     Match Monthly Production Setting dynamically.

#     Company and Cost Center can be anything.
#     """

#     posting_date = getdate(
#         posting_date
#     )

#     filters = {
#         "company": company,
#         "docstatus": 1,
#         "from_date": (
#             "<=",
#             posting_date,
#         ),
#         "to_date": (
#             ">=",
#             posting_date,
#         ),
#     }

#     if cost_center:
#         filters["cost_center"] = (
#             cost_center
#         )

#     settings = frappe.get_all(
#         "Monthly Production Setting",
#         filters=filters,
#         fields=[
#             "name",
#             "cost_center",
#         ],
#         order_by="creation desc",
#         limit_page_length=2,
#     )

#     if not settings:
#         if cost_center:
#             frappe.throw(
#                 _(
#                     "No submitted Monthly Production Setting found "
#                     "for Company {0}, Cost Center {1} "
#                     "and Posting Date {2}."
#                 ).format(
#                     frappe.bold(company),
#                     frappe.bold(cost_center),
#                     frappe.bold(posting_date),
#                 )
#             )

#         frappe.throw(
#             _(
#                 "No submitted Monthly Production Setting found "
#                 "for Company {0} and Posting Date {1}."
#             ).format(
#                 frappe.bold(company),
#                 frappe.bold(posting_date),
#             )
#         )

#     if len(settings) > 1:
#         if not cost_center:
#             frappe.throw(
#                 _(
#                     "Multiple Monthly Production Settings exist "
#                     "for Company {0} on {1}. "
#                     "Please select the required Cost Center "
#                     "on Stock Entry."
#                 ).format(
#                     frappe.bold(company),
#                     frappe.bold(posting_date),
#                 )
#             )

#         frappe.throw(
#             _(
#                 "Multiple submitted Monthly Production Settings "
#                 "found for Company {0}, Cost Center {1} "
#                 "and Posting Date {2}."
#             ).format(
#                 frappe.bold(company),
#                 frappe.bold(cost_center),
#                 frappe.bold(posting_date),
#             )
#         )

#     return frappe.get_doc(
#         "Monthly Production Setting",
#         settings[0].name,
#     )


# def remove_auto_overhead_rows(doc):
#     """
#     Remove previously generated Monthly Production Overhead rows
#     before recalculating.

#     Manual Additional Cost rows remain untouched.
#     """

#     manual_rows = []

#     for row in doc.get(
#         "additional_costs"
#     ) or []:

#         description = (
#             row.description or ""
#         )

#         if not description.startswith(
#             AUTO_PREFIX
#         ):
#             manual_rows.append(row)

#     doc.set(
#         "additional_costs",
#         manual_rows,
#     )


# def sync_item_cost_centers(doc):
#     """Apply the Stock Entry Cost Center to every item row."""

#     if not doc.cost_center:
#         return

#     for row in doc.get("items") or []:
#         row.cost_center = doc.cost_center






from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from erpnext.accounts.general_ledger import process_gl_map
from erpnext.stock.doctype.stock_entry.stock_entry import (
    StockEntry as ERPNextStockEntry,
)


AUTO_PREFIX = "Monthly Production Overhead |"


class CustomStockEntry(ERPNextStockEntry):
    """
    Perfect Craft Stock Entry extension.

    Estimated production expenses:
    - are fetched from Monthly Production Setting
    - stay separate from standard Additional Costs
    - are capitalized into Manufacture FG valuation
    - are posted to GL using ERPNext v15.118.1-compatible logic
    """

    def validate(self):
        # Parent Cost Center -> all Item rows.
        sync_item_cost_centers(self)

        # Keep complete standard ERPNext validation/calculation.
        super().validate()

        # Perfect Craft final validation.
        validate_cost_centers(self)

    def _get_pc_incoming_items_and_basic_total(self):
        """
        ERPNext v15.118.1-compatible allocation.

        For Manufacture/Repack, Additional Cost is allocated
        only to Finished Good rows using basic_amount.
        """

        if self.purpose in ("Manufacture", "Repack"):
            incoming_items = [
                row
                for row in (self.get("items") or [])
                if cint(row.is_finished_item)
            ]
        else:
            incoming_items = [
                row
                for row in (self.get("items") or [])
                if row.t_warehouse
            ]

        total_basic_amount = sum(
            flt(row.basic_amount)
            for row in incoming_items
        )

        return incoming_items, total_basic_amount

    def distribute_additional_costs(self):
        """
        1. Preserve ERPNext manual Additional Costs.
        2. Add MPS estimated expenses separately into FG valuation.
        """

        # Standard ERPNext Additional Costs stay fully functional.
        super().distribute_additional_costs()

        if self.purpose != "Manufacture":
            return

        if not self.meta.has_field("custom_expenses"):
            return

        estimated_total = get_estimated_expense_total(self)

        if self.meta.has_field(
            "custom_total_estimated_expenses"
        ):
            self.custom_total_estimated_expenses = (
                estimated_total
            )

        if estimated_total <= 0:
            return

        (
            incoming_items,
            total_basic_amount,
        ) = self._get_pc_incoming_items_and_basic_total()

        if not incoming_items:
            frappe.throw(
                _(
                    "Estimated production expenses cannot be "
                    "allocated because no Finished Good row "
                    "was found."
                )
            )

        if total_basic_amount <= 0:
            frappe.throw(
                _(
                    "Estimated production expenses cannot be "
                    "allocated because the Finished Good "
                    "basic amount is zero."
                )
            )

        for row in incoming_items:
            allocated_amount = (
                flt(row.basic_amount)
                / flt(total_basic_amount)
                * flt(estimated_total)
            )

            # ERPNext update_valuation_rate() runs after this method,
            # therefore this amount becomes part of FG valuation.
            row.additional_cost = (
                flt(row.additional_cost)
                + flt(allocated_amount)
            )

    def get_gl_entries(self, warehouse_account):
        """
        Keep normal ERPNext Stock Entry GL entries first.

        Then post custom estimated Expenses using the same
        accounting pattern ERPNext v15.118.1 uses for
        Additional Costs.
        """

        gl_entries = super().get_gl_entries(
            warehouse_account
        )

        if self.purpose != "Manufacture":
            return gl_entries

        if not self.meta.has_field("custom_expenses"):
            return gl_entries

        expense_rows = [
            row
            for row in (
                self.get("custom_expenses")
                or []
            )
            if (
                row.expense_account
                and flt(row.estimated_amount)
            )
        ]

        if not expense_rows:
            return gl_entries

        (
            incoming_items,
            total_basic_amount,
        ) = self._get_pc_incoming_items_and_basic_total()

        if (
            not incoming_items
            or total_basic_amount <= 0
        ):
            return gl_entries

        item_account_wise_expense = defaultdict(
            lambda: defaultdict(float)
        )

        for expense in expense_rows:
            for item in incoming_items:

                allocated_amount = (
                    flt(expense.estimated_amount)
                    * flt(item.basic_amount)
                    / flt(total_basic_amount)
                )

                item_account_wise_expense[
                    (
                        item.item_code,
                        item.name,
                    )
                ][
                    expense.expense_account
                ] += allocated_amount

        precision = (
            self.get_debit_field_precision()
        )

        for item in (
            self.get("items")
            or []
        ):

            account_amounts = (
                item_account_wise_expense.get(
                    (
                        item.item_code,
                        item.name,
                    ),
                    {},
                )
            )

            for (
                expense_account,
                amount,
            ) in account_amounts.items():

                amount = flt(
                    amount,
                    precision,
                )

                if not amount:
                    continue

                if not item.expense_account:
                    frappe.throw(
                        _(
                            "Row {0}: Expense Account is "
                            "required for Finished Item {1} "
                            "before estimated production "
                            "expenses can be posted."
                        ).format(
                            item.idx,
                            frappe.bold(
                                item.item_code
                            ),
                        )
                    )

                cost_center = (
                    item.cost_center
                    or self.cost_center
                )

                remarks = (
                    self.get("remarks")
                    or _(
                        "Accounting Entry for "
                        "Estimated Production Expense"
                    )
                )

                # Credit selected Monthly Production Setting
                # Expense Account.
                gl_entries.append(
                    self.get_gl_dict(
                        {
                            "account":
                                expense_account,

                            "against":
                                item.expense_account,

                            "cost_center":
                                cost_center,

                            "remarks":
                                remarks,

                            "credit_in_account_currency":
                                amount,

                            "credit":
                                amount,
                        },
                        item=item,
                    )
                )

                # Debit item's Stock Adjustment /
                # Difference Expense Account.
                #
                # ERPNext expresses debit here as
                # negative credit.
                gl_entries.append(
                    self.get_gl_dict(
                        {
                            "account":
                                item.expense_account,

                            "against":
                                expense_account,

                            "cost_center":
                                cost_center,

                            "remarks":
                                remarks,

                            "credit":
                                -1 * amount,
                        },
                        item=item,
                    )
                )

        return process_gl_map(
            gl_entries,
            from_repost=(
                frappe.flags
                .through_repost_item_valuation
            ),
        )


def apply_monthly_production_overhead(
    doc,
    method=None,
):
    """
    Fetch estimated production expenses from
    Monthly Production Setting.

    Match:
        Company
        Cost Center
        Posting Date

    Calculation:
        Expense Per Qty
            = Monthly Expense Amount / Expected Qty

        Estimated Amount
            = Expense Per Qty * Finished Qty

    IMPORTANT:
        MPS-generated expenses go ONLY into custom_expenses.

        They are NOT inserted into standard additional_costs.
    """

    if doc.docstatus != 0:
        return

    # ---------------------------------------------------------
    # OLD LOGIC PRESERVED:
    # Parent Cost Center -> all Item rows
    # ---------------------------------------------------------

    sync_item_cost_centers(doc)

    # ---------------------------------------------------------
    # OLD LOGIC PRESERVED:
    # Remove only our OLD auto-generated Additional Cost rows.
    #
    # Manual Additional Costs must remain untouched.
    # ---------------------------------------------------------

    remove_legacy_auto_overhead_rows(doc)

    # ---------------------------------------------------------
    # Rebuild only generated Expenses.
    # ---------------------------------------------------------

    if doc.meta.has_field(
        "custom_expenses"
    ):
        doc.set(
            "custom_expenses",
            [],
        )

    if doc.meta.has_field(
        "custom_total_estimated_expenses"
    ):
        doc.custom_total_estimated_expenses = 0

    # ---------------------------------------------------------
    # OLD LOGIC PRESERVED:
    # Only Manufacture
    # ---------------------------------------------------------

    if doc.purpose != "Manufacture":
        return

    if not doc.meta.has_field(
        "custom_expenses"
    ):
        frappe.throw(
            _(
                "Stock Entry Expenses customization "
                "is missing. Run bench migrate for "
                "the pc_production app."
            )
        )

    # ---------------------------------------------------------
    # OLD LOGIC PRESERVED
    # ---------------------------------------------------------

    if (
        not doc.company
        or not doc.posting_date
    ):
        return

    # ---------------------------------------------------------
    # Find Finished Good
    # ---------------------------------------------------------

    finished_rows = (
        get_finished_goods_rows(doc)
    )

    if not finished_rows:
        # Allow incomplete Draft until FG exists.
        return

    if len(finished_rows) > 1:
        frappe.throw(
            _(
                "Monthly Production Setting estimated "
                "expenses support one Finished Good "
                "item per Manufacture Stock Entry."
            )
        )

    finished_row = (
        finished_rows[0]
    )

    # ---------------------------------------------------------
    # OLD LOGIC PRESERVED:
    # Use Stock UOM quantity.
    # ---------------------------------------------------------

    finished_qty = flt(
        finished_row.transfer_qty
    )

    if finished_qty <= 0:
        finished_qty = (
            flt(finished_row.qty)
            * flt(
                finished_row.conversion_factor
                or 1
            )
        )

    if finished_qty <= 0:
        return

    # ---------------------------------------------------------
    # OLD LOGIC PRESERVED:
    # Prefer Parent Cost Center.
    # Otherwise use Finished Good row Cost Center.
    # ---------------------------------------------------------

    cost_center = (
        doc.cost_center
        or finished_row.cost_center
    )

    # ---------------------------------------------------------
    # OLD LOGIC PRESERVED:
    # Fetch correct Monthly Production Setting.
    # ---------------------------------------------------------

    setting = get_monthly_setting(
        company=
            doc.company,

        cost_center=
            cost_center,

        posting_date=
            doc.posting_date,
    )

    expected_qty = flt(
        setting.expected_qty
    )

    if expected_qty <= 0:
        frappe.throw(
            _(
                "Expected Qty must be greater "
                "than zero in Monthly Production "
                "Setting {0}."
            ).format(
                frappe.bold(
                    setting.name
                )
            )
        )

    # ---------------------------------------------------------
    # OLD LOGIC PRESERVED:
    # If Stock Entry Cost Center was blank but MPS resolved it,
    # apply MPS Cost Center to parent + Items.
    # ---------------------------------------------------------

    if not doc.cost_center:
        doc.cost_center = (
            setting.cost_center
        )

        sync_item_cost_centers(doc)

    total_estimated = 0

    # ---------------------------------------------------------
    # OLD LOGIC PRESERVED:
    # Each MPS expense is calculated separately.
    # ---------------------------------------------------------

    for expense in (
        setting.get("expenses")
        or []
    ):

        if not expense.type_of_expense:
            continue

        monthly_amount = flt(
            expense.expense_amount
        )

        if monthly_amount <= 0:
            continue

        validate_estimated_expense_account(
            expense.type_of_expense,
            doc.company,
        )

        # -----------------------------------------------------
        # EXACT OLD FORMULA:
        #
        # Monthly Expense / Expected Qty
        # -----------------------------------------------------

        expense_per_qty = (
            monthly_amount
            / expected_qty
        )

        # -----------------------------------------------------
        # EXACT OLD FORMULA:
        #
        # Expense Per Qty * THIS Stock Entry Finished Qty
        # -----------------------------------------------------

        allocated_amount = (
            expense_per_qty
            * finished_qty
        )

        # -----------------------------------------------------
        # ONLY REQUIRED CHANGE:
        #
        # OLD:
        #     additional_costs
        #
        # NEW:
        #     custom_expenses
        # -----------------------------------------------------

        doc.append(
            "custom_expenses",
            {
                "expense_account":
                    expense.type_of_expense,

                "description":
                    (
                        f"{AUTO_PREFIX} "
                        f"{setting.name} | "
                        f"{expense.type_of_expense}"
                    ),

                "estimated_amount":
                    allocated_amount,

                "monthly_production_setting":
                    setting.name,
            },
        )

        total_estimated += (
            allocated_amount
        )

    if total_estimated <= 0:
        frappe.throw(
            _(
                "No estimated production expense "
                "amount found in Monthly Production "
                "Setting {0}."
            ).format(
                frappe.bold(
                    setting.name
                )
            )
        )

    if doc.meta.has_field(
        "custom_total_estimated_expenses"
    ):
        doc.custom_total_estimated_expenses = (
            total_estimated
        )


def get_finished_goods_rows(doc):
    """
    Preserve old Perfect Craft logic.

    Priority:
    1. ERPNext is_finished_item
    2. Work Order / BOM item safety check
    3. Incoming non-scrap fallback
    """

    rows = (
        doc.get("items")
        or []
    )

    # ---------------------------------------------------------
    # ORIGINAL PRIMARY METHOD
    # ---------------------------------------------------------

    finished_rows = []

    for row in rows:

        if not row.item_code:
            continue

        if cint(
            row.is_finished_item
        ):
            finished_rows.append(
                row
            )

    if finished_rows:
        return finished_rows

    # ---------------------------------------------------------
    # Extra safe lookup using Work Order / BOM.
    # This does not remove original behavior.
    # ---------------------------------------------------------

    production_item = None

    if doc.work_order:
        production_item = (
            frappe.get_cached_value(
                "Work Order",
                doc.work_order,
                "production_item",
            )
        )

    if (
        not production_item
        and doc.bom_no
    ):
        production_item = (
            frappe.get_cached_value(
                "BOM",
                doc.bom_no,
                "item",
            )
        )

    if production_item:

        matched_rows = [
            row
            for row in rows
            if (
                row.item_code
                == production_item

                and row.t_warehouse

                and not row.s_warehouse

                and not cint(
                    row.is_scrap_item
                )
            )
        ]

        if matched_rows:
            return matched_rows

    # ---------------------------------------------------------
    # ORIGINAL FALLBACK
    #
    # Incoming row
    # No source warehouse
    # Not scrap
    # ---------------------------------------------------------

    finished_rows = []

    for row in rows:

        if not row.item_code:
            continue

        if not row.t_warehouse:
            continue

        if row.s_warehouse:
            continue

        if cint(
            row.is_scrap_item
        ):
            continue

        finished_rows.append(
            row
        )

    return finished_rows


def get_monthly_setting(
    company,
    cost_center,
    posting_date,
):
    """
    OLD LOGIC PRESERVED.

    Match submitted Monthly Production Setting by:

        Company
        Cost Center
        Posting Date
    """

    posting_date = getdate(
        posting_date
    )

    filters = {
        "company":
            company,

        "docstatus":
            1,

        "from_date":
            (
                "<=",
                posting_date,
            ),

        "to_date":
            (
                ">=",
                posting_date,
            ),
    }

    if cost_center:
        filters[
            "cost_center"
        ] = cost_center

    settings = frappe.get_all(
        "Monthly Production Setting",

        filters=
            filters,

        fields=[
            "name",
            "cost_center",
        ],

        order_by=
            "creation desc",

        limit_page_length=
            2,
    )

    if not settings:

        if cost_center:
            frappe.throw(
                _(
                    "No submitted Monthly Production "
                    "Setting found for Company {0}, "
                    "Cost Center {1} and Posting Date {2}."
                ).format(
                    frappe.bold(
                        company
                    ),

                    frappe.bold(
                        cost_center
                    ),

                    frappe.bold(
                        posting_date
                    ),
                )
            )

        frappe.throw(
            _(
                "No submitted Monthly Production "
                "Setting found for Company {0} "
                "and Posting Date {1}."
            ).format(
                frappe.bold(
                    company
                ),

                frappe.bold(
                    posting_date
                ),
            )
        )

    if len(settings) > 1:

        if not cost_center:
            frappe.throw(
                _(
                    "Multiple Monthly Production "
                    "Settings exist for Company {0} "
                    "on {1}. Please select the required "
                    "Cost Center on Stock Entry."
                ).format(
                    frappe.bold(
                        company
                    ),

                    frappe.bold(
                        posting_date
                    ),
                )
            )

        frappe.throw(
            _(
                "Multiple submitted Monthly Production "
                "Settings found for Company {0}, "
                "Cost Center {1} and Posting Date {2}."
            ).format(
                frappe.bold(
                    company
                ),

                frappe.bold(
                    cost_center
                ),

                frappe.bold(
                    posting_date
                ),
            )
        )

    return frappe.get_doc(
        "Monthly Production Setting",
        settings[0].name,
    )


def validate_estimated_expense_account(
    account,
    company,
):
    """
    Validate Monthly Production Setting expense account
    before GL posting.
    """

    account_data = (
        frappe.get_cached_value(
            "Account",

            account,

            [
                "company",
                "is_group",
                "account_currency",
                "disabled",
            ],

            as_dict=True,
        )
    )

    if not account_data:
        frappe.throw(
            _(
                "Expense Account {0} "
                "does not exist."
            ).format(
                frappe.bold(
                    account
                )
            )
        )

    if (
        account_data.company
        != company
    ):
        frappe.throw(
            _(
                "Expense Account {0} does not "
                "belong to Company {1}."
            ).format(
                frappe.bold(
                    account
                ),

                frappe.bold(
                    company
                ),
            )
        )

    if cint(
        account_data.is_group
    ):
        frappe.throw(
            _(
                "Expense Account {0} is a Group "
                "Account. Select a ledger account "
                "in Monthly Production Setting."
            ).format(
                frappe.bold(
                    account
                )
            )
        )

    if cint(
        account_data.disabled
    ):
        frappe.throw(
            _(
                "Expense Account {0} "
                "is disabled."
            ).format(
                frappe.bold(
                    account
                )
            )
        )

    company_currency = (
        frappe.get_cached_value(
            "Company",
            company,
            "default_currency",
        )
    )

    if (
        account_data.account_currency
        and company_currency
        and (
            account_data.account_currency
            != company_currency
        )
    ):
        frappe.throw(
            _(
                "Estimated production expense "
                "account {0} must use Company "
                "currency {1}."
            ).format(
                frappe.bold(
                    account
                ),

                frappe.bold(
                    company_currency
                ),
            )
        )


def remove_legacy_auto_overhead_rows(doc):
    """
    OLD LOGIC PRESERVED.

    Remove only OLD Perfect Craft generated
    Monthly Production Overhead rows from
    standard Additional Costs.

    Manual Additional Costs remain untouched.
    """

    manual_rows = []

    for row in (
        doc.get("additional_costs")
        or []
    ):

        description = (
            row.description
            or ""
        )

        if not description.startswith(
            AUTO_PREFIX
        ):
            manual_rows.append(
                row
            )

    doc.set(
        "additional_costs",
        manual_rows,
    )


def sync_item_cost_centers(doc):
    """
    OLD LOGIC PRESERVED.

    Parent Stock Entry Cost Center
    -> every Item child row.
    """

    if not doc.cost_center:
        return

    for row in (
        doc.get("items")
        or []
    ):
        row.cost_center = (
            doc.cost_center
        )


def validate_cost_centers(doc):
    """
    Cost Center is mandatory.

    Every Item row must use the parent
    Stock Entry Cost Center.
    """

    if not doc.cost_center:
        frappe.throw(
            _(
                "Cost Center is mandatory "
                "on Stock Entry."
            )
        )

    sync_item_cost_centers(
        doc
    )

    for row in (
        doc.get("items")
        or []
    ):

        if (
            row.item_code
            and not row.cost_center
        ):
            frappe.throw(
                _(
                    "Row {0}: Cost Center "
                    "is mandatory for Item {1}."
                ).format(
                    row.idx,

                    frappe.bold(
                        row.item_code
                    ),
                )
            )


def get_estimated_expense_total(doc):
    """
    Total estimated production expense
    generated from Monthly Production Setting.
    """

    if not doc.meta.has_field(
        "custom_expenses"
    ):
        return 0

    return sum(
        flt(
            row.estimated_amount
        )
        for row in (
            doc.get("custom_expenses")
            or []
        )
    )