# Copyright (c) 2026, TRPL Solutions and contributors
# For license information, please see license.txt

"""Interior Sindh City Wise Sales: the client's "INTERIOR SINDH CITY WISE SALES" sheet.

A thin wrapper: City Wise Sales Report with Group By = Customer (Rank, A/c. Title, Region, City,
Sales Officer, one column per month, Total CTN, Per Month Avg; Month Wise Sale Total and Monthly
Average footers). All calculation lives in City Wise Sales Report / report_utils. The Region
filter defaults to "Interior Sindh" in the .js; the print layout is City Wise's template.
"""

import frappe

from pc_production.pc_production.report.city_wise_sales_report.city_wise_sales_report import (
	execute as city_wise_execute,
)

# "Interior Sindh - City Wise Sales" with an en dash (same text as print_title in the .js).
REPORT_TITLE = "Interior Sindh \u2013 City Wise Sales"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	filters.group_by = "Customer"

	columns, data, message, chart = city_wise_execute(filters)
	if data:
		# Report title on the data (the print title itself is print_title in the .js).
		data[-1]["report_title"] = REPORT_TITLE
	return columns, data, message, chart
