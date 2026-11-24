# Copyright (c) 2026, TRPL Solutions and contributors
# For license information, please see license.txt

"""City Wise Sales Report: cartons sold per month name, by City or by Customer.

Period, invoice lines, cartons, Sales Officer split and filter options: see report_utils.

Columns       One per month NAME, summing that month over all selected years / seasons.
Rows          City (customer's primary Address) or Customer. Ranked by Total CTN, descending,
              ties by name; rows with nothing sold are hidden.
Brand / SKU   Item.brand / Item.custom_sku (filters only).
Per Month Avg Total CTN / number of months selected (month columns), like SKU Wise Sales
              Analysis. "Monthly Average" footer = month total / rows.
"""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, getdate

from pc_production.pc_production.report.recovery_report.recovery_report import get_report_header
from pc_production.pc_production.report.sales_report.sales_report import NOT_AVAILABLE
from pc_production.pc_production.report_utils import (
	DIVIDE,
	QTY_TOLERANCE,
	get_invoice_lines,
	get_period,
	plural,
	validate_period_filters,
)

CHART_TOP = 10


def execute(filters=None):
	filters = frappe._dict(filters or {})
	validate_filters(filters)

	period = get_period(filters)
	lines = get_invoice_lines(filters, period)
	rows = build_rows(lines, period, filters)
	has_unconverted = any(abs(row.unconverted_qty) > QTY_TOLERANCE for row in rows)

	columns = get_columns(period, filters, has_unconverted)
	data = get_data(rows, period, filters, has_unconverted)
	return columns, data, None, get_chart(rows, period, filters)


def validate_filters(filters):
	validate_period_filters(filters)

	filters.group_by = filters.group_by or "City"
	if filters.group_by not in ("City", "Customer"):
		frappe.throw(_("Group By must be City or Customer"))


def get_average_description(period):
	"""Same rule as SKU Wise Sales Analysis: divide by the month columns, not months x years."""
	months = len(period.months)
	return _("Total CTN {0} {1} {2} selected").format(DIVIDE, months, plural(months, "month", "months"))


# ============================================================
# DATA
# ============================================================


def build_rows(lines, period, filters):
	by_customer = filters.group_by == "Customer"
	rows = {}

	for line in lines:
		key = line.customer if by_customer else line.city
		row = rows.get(key)
		if not row:
			row = rows[key] = frappe._dict(
				name=line.customer_name if by_customer else line.city,
				customer=line.customer if by_customer else None,
				region=line.region,
				city=line.city,
				officers=set(),
				months=defaultdict(float),
				total=0,
				unconverted_qty=0,
			)

		cartons = line.cartons * line.factor
		row.months[f"m_{getdate(line.posting_date).month:02d}"] += cartons
		row.total += cartons
		row.unconverted_qty += line.unconverted_qty * line.factor
		row.officers.update(line.officers)

	visible = [
		row
		for row in rows.values()
		if abs(row.total) > QTY_TOLERANCE or abs(row.unconverted_qty) > QTY_TOLERANCE
	]
	visible.sort(key=lambda row: (row.name or "").lower())
	visible.sort(key=lambda row: -flt(row.total, 3))
	return visible


def get_data(rows, period, filters, has_unconverted):
	if not rows:
		return []

	by_customer = filters.group_by == "Customer"
	months = period.months
	data = []

	for rank, row in enumerate(rows, start=1):
		line = {
			"row_type": "row",
			"rank": rank,
			"name": row.name,
			**{month.fieldname: row.months.get(month.fieldname, 0) for month in months},
			"total": row.total,
			"average": row.total / len(period.months),
		}
		if by_customer:
			line.update(
				customer=row.customer,
				region=row.region,
				city=row.city,
				sales_officer=", ".join(sorted(row.officers, key=str.lower)) or NOT_AVAILABLE,
			)
		if has_unconverted:
			line["unconverted_qty"] = row.unconverted_qty
		data.append(line)

	totals = {month.fieldname: sum(row.months.get(month.fieldname, 0) for row in rows) for month in months}
	grand_total = sum(row.total for row in rows)
	unconverted = sum(row.unconverted_qty for row in rows)

	total_line = {
		"row_type": "month_total",
		"name": _("Month Wise Sale Total"),
		"bold": 1,
		**totals,
		"total": grand_total,
		"average": grand_total / len(period.months),
	}
	average_line = {
		"row_type": "monthly_average",
		"name": _("Monthly Average"),
		"bold": 1,
		**{fieldname: amount / len(rows) for fieldname, amount in totals.items()},
		"total": grand_total / len(rows),
		"average": grand_total / len(period.months) / len(rows),
		# Read by the print layout for its header and notes.
		**get_report_header(filters),
		"period_label": period.label,
		"average_description": get_average_description(period),
		"row_count": len(rows),
	}
	if has_unconverted:
		total_line["unconverted_qty"] = unconverted
		average_line["unconverted_qty"] = unconverted / len(rows)

	return [*data, total_line, average_line]


def get_columns(period, filters, has_unconverted):
	def qty(label, fieldname, width=80, **extra):
		# Whole cartons on screen and in print; values keep their decimals.
		return {
			"label": label,
			"fieldname": fieldname,
			"fieldtype": "Float",
			"precision": 0,
			"width": width,
			**extra,
		}

	columns = [{"label": _("Rank"), "fieldname": "rank", "fieldtype": "Int", "width": 50}]
	if filters.group_by == "Customer":
		columns += [
			{"label": _("A/c. Title"), "fieldname": "name", "fieldtype": "Data", "width": 220},
			{"label": _("Region"), "fieldname": "region", "fieldtype": "Data", "width": 130},
			{"label": _("City"), "fieldname": "city", "fieldtype": "Data", "width": 110},
			{"label": _("Sales Officer"), "fieldname": "sales_officer", "fieldtype": "Data", "width": 140},
		]
	else:
		columns.append({"label": _("City"), "fieldname": "name", "fieldtype": "Data", "width": 170})

	columns += [qty(_(month.label), month.fieldname) for month in period.months]
	columns += [
		qty(_("Total CTN"), "total", 100),
		qty(_("Per Month Avg"), "average", 110, description=get_average_description(period)),
	]
	if has_unconverted:
		# Items without a Carton UOM: stock UOM, not mixed into cartons.
		columns.append(qty(_("Qty without Carton UOM"), "unconverted_qty", 160))
	return columns


def get_chart(rows, period, filters):
	if not rows:
		return None

	if filters.chart == "Top 10":
		top = rows[:CHART_TOP]
		labels = [row.name for row in top]
		values = [flt(row.total, 0) for row in top]
		name = _("Top {0} by Total CTN").format(len(top))
	else:
		labels = [_(month.label) for month in period.months]
		values = [flt(sum(row.months.get(month.fieldname, 0) for row in rows), 0) for month in period.months]
		name = _("Cartons")

	return {
		"data": {"labels": labels, "datasets": [{"name": name, "values": values}]},
		"type": "bar",
		"colors": ["#2490ef"],
		"fieldtype": "Float",
		"barOptions": {"spaceRatio": 0.4},
	}
