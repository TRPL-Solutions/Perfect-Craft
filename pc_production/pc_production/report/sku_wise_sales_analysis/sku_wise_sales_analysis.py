# Copyright (c) 2026, TRPL Solutions and contributors
# For license information, please see license.txt

"""SKU Wise Sales Analysis: cartons sold per month, by Brand x SKU (client's "Item-wise" sheet).

Period, invoice lines, cartons, Sales Officer split and filter options: see report_utils.

Rows      One per selected month NAME, summing that month over all selected years / seasons.
          Every selected month is shown, also without sales.
Columns   Brand x SKU (Brand/SKU Sort Order, blank last). Ticked SKUs always show under every
          brand shown, even without sales; without a SKU filter only pairs that sold appear.
          Brands: the ticked ones, else those that sold. Then Total per SKU and the grand TOTAL.
          Items without a Carton UOM: "Qty without Carton UOM" (stock UOM), shown when not zero.
Footer    TOTAL, AVERAGE PER MONTH (total / months selected), MAX and MIN (over the month rows,
          zeros included), SHARE % (column total / grand total).
"""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt

from pc_production.pc_production.report.recovery_report.recovery_report import get_report_header
from pc_production.pc_production.report_utils import (
	DIVIDE,
	QTY_TOLERANCE,
	get_brand_sku_layout,
	get_invoice_lines,
	get_period,
	get_quality_notes,
	plural,
	validate_period_filters,
)

CHART_COLORS = ["#2490ef", "#f39c12", "#27ae60", "#8e44ad", "#e74c3c", "#16a085", "#7f8c8d"]
FOOTER_ROWS = ("total", "average", "max", "min", "share")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	validate_period_filters(filters)

	period = get_period(filters)
	lines = get_invoice_lines(filters, period)
	if not lines:
		return get_columns(period, [], [], False), [], _("No sales found for the selected filters."), None

	layout = get_layout(lines, filters)
	has_unconverted = any(abs(line.unconverted_qty) > QTY_TOLERANCE for line in lines)
	month_rows = get_month_rows(lines, period, layout)
	quality = get_quality_notes(lines)

	columns = get_columns(period, layout.combos, layout.skus, has_unconverted)
	data = get_data(month_rows, period, layout, has_unconverted, filters, quality)
	return columns, data, quality or None, get_chart(month_rows, period, layout, filters)


# ============================================================
# LAYOUT: which Brand x SKU columns
# ============================================================


def get_layout(lines, filters):
	order = get_brand_sku_layout(lines, filters)
	brand_info, brands, skus, sold_pairs = order.brand_info, order.brands, order.skus, order.sold_pairs

	if filters.sku:
		# Ticked SKUs always show, under every brand shown.
		pairs = [(brand, sku) for brand in brands for sku in skus]
	else:
		pairs = [(brand, sku) for brand in brands for sku in skus if (brand, sku) in sold_pairs]

	brand_index = {brand: idx for idx, brand in enumerate(brands)}
	sku_index = {sku: idx for idx, sku in enumerate(skus)}
	combos = []
	for brand, sku in pairs:
		info = brand_info.get(brand) or frappe._dict()
		combos.append(
			frappe._dict(
				key=(brand, sku),
				fieldname=f"c_{brand_index[brand]}_{sku_index[sku]}",
				brand=brand,
				brand_label=info.short_name or brand,
				brand_index=brand_index[brand],
				sku=sku,
				sku_fieldname=f"t_{sku_index[sku]}",
			)
		)

	return frappe._dict(
		combos=combos,
		brands=brands,
		brand_labels=order.brand_labels,
		skus=[frappe._dict(name=sku, fieldname=f"t_{idx}") for idx, sku in enumerate(skus)],
	)


# ============================================================
# DATA
# ============================================================


def get_month_rows(lines, period, layout):
	combo_fields = {combo.key: combo.fieldname for combo in layout.combos}
	sku_fields = {sku.name: sku.fieldname for sku in layout.skus}
	rows = {month.number: defaultdict(float) for month in period.months}

	for line in lines:
		row = rows[line.month]
		if line.unconverted_qty:
			row["unconverted_qty"] += line.unconverted_qty * line.factor
			continue
		fieldname = combo_fields.get((line.brand_key, line.sku_key))
		if not fieldname:
			continue
		cartons = line.cartons * line.factor
		row[fieldname] += cartons
		row[sku_fields[line.sku_key]] += cartons
		row["total"] += cartons

	return [(month, rows[month.number]) for month in period.months]


def get_value_fields(layout, has_unconverted):
	fields = [combo.fieldname for combo in layout.combos] + [sku.fieldname for sku in layout.skus] + ["total"]
	return [*fields, "unconverted_qty"] if has_unconverted else fields


def get_data(month_rows, period, layout, has_unconverted, filters, quality):
	fields = get_value_fields(layout, has_unconverted)
	data = []
	for sr, (month, values) in enumerate(month_rows, start=1):
		data.append(
			{
				"row_type": "month",
				"sr": sr,
				"month": _(month.full_label),
				**{field: values.get(field, 0) for field in fields},
			}
		)

	def column(field):
		return [row[field] for row in data]

	totals = {field: sum(column(field)) for field in fields}
	grand_total = totals["total"]
	month_count = len(period.months)

	footer = {
		"total": (_("TOTAL"), totals),
		"average": (_("AVERAGE PER MONTH"), {f: totals[f] / month_count for f in fields}),
		"max": (_("MAX"), {f: max(column(f)) for f in fields}),
		"min": (_("MIN"), {f: min(column(f)) for f in fields}),
		"share": (
			_("SHARE %"),
			{
				f: (totals[f] * 100 / grand_total if grand_total else 0)
				for f in fields
				if f != "unconverted_qty"
			},
		),
	}
	for row_type in FOOTER_ROWS:
		label, values = footer[row_type]
		data.append({"row_type": row_type, "month": label, "bold": 1, **values})

	# Read by the print layout for its header and notes.
	data[-1].update(
		{
			**get_report_header(filters),
			"period_label": period.label,
			"average_description": get_average_description(period),
			"quality_notes": quality,
		}
	)
	return data


def get_average_description(period):
	months = len(period.months)
	return _("Total {0} {1} {2} selected").format(DIVIDE, months, plural(months, "month", "months"))


# ============================================================
# COLUMNS AND CHART
# ============================================================


def get_columns(period, combos, skus, has_unconverted):
	def qty(label, fieldname, width=90, **extra):
		# Whole cartons on screen and in print; values keep their decimals.
		return {
			"label": label,
			"fieldname": fieldname,
			"fieldtype": "Float",
			"precision": 0,
			"width": width,
			**extra,
		}

	columns = [
		{"label": _("SR"), "fieldname": "sr", "fieldtype": "Int", "width": 50},
		{"label": _("Month"), "fieldname": "month", "fieldtype": "Data", "width": 170},
	]
	columns += [
		qty(
			f"{combo.brand_label} {combo.sku}",
			combo.fieldname,
			# Two-level print header: brand above SKU.
			group_label=combo.brand_label,
			sub_label=combo.sku,
			brand_index=combo.brand_index,
			description=f"{combo.brand} {combo.sku}",
		)
		for combo in combos
	]
	columns += [
		qty(
			_("Total {0}").format(sku.name),
			sku.fieldname,
			100,
			group_label=_("Total by SKU"),
			sub_label=sku.name,
			description=_("All brands, SKU {0}").format(sku.name),
		)
		for sku in skus
	]
	columns.append(qty(_("TOTAL"), "total", 100, description=_("All shown Brand x SKU columns, in cartons")))
	if has_unconverted:
		columns.append(
			qty(
				_("Qty without Carton UOM"),
				"unconverted_qty",
				160,
				description=_("Items without a Carton UOM, in their stock UOM (not in the totals)"),
			)
		)
	return columns


def get_chart(month_rows, period, layout, filters):
	if not layout.combos:
		return None

	if filters.chart == "By SKU":
		labels = [sku.name for sku in layout.skus]
		datasets = [
			{
				"name": _("Cartons"),
				"values": [
					flt(sum(values.get(sku.fieldname, 0) for _m, values in month_rows), 0)
					for sku in layout.skus
				],
			}
		]
		return {"data": {"labels": labels, "datasets": datasets}, "type": "bar", "colors": CHART_COLORS[:1]}

	# Stacked bar: cartons per month, one colour per brand.
	datasets = []
	for brand in layout.brands:
		fields = [combo.fieldname for combo in layout.combos if combo.brand == brand]
		datasets.append(
			{
				"name": layout.brand_labels[brand],
				"values": [flt(sum(values.get(f, 0) for f in fields), 0) for _m, values in month_rows],
			}
		)
	return {
		"data": {"labels": [_(month.label) for month in period.months], "datasets": datasets},
		"type": "bar",
		"colors": CHART_COLORS[: len(datasets)],
		"barOptions": {"stacked": 1, "spaceRatio": 0.4},
	}
