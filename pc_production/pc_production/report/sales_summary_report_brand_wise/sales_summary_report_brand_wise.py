# Copyright (c) 2026, TRPL Solutions and contributors
# For license information, please see license.txt

"""Sales Summary Report Brand Wise: the client's "3 BRAND WISE UPDATE" sheet.

Cartons sold per customer and brand in the date range, from submitted Sales Invoices (credit
notes negative). Lines, cartons, geography, the Packing filter and the Sales Officer split come
from report_utils.get_invoice_lines; with a Sales Person filter every quantity is that person's
share, as in the other carton reports.

Rows      Grouped by brand (Brand Sort Order): a brand heading, one row per customer that bought
          the brand (by A/C Code, natural order: 12-999 before 12-1000), then the brand's subtotal. A customer shows under every brand
          it bought. At the end: TOTAL CARTONS and AVERAGE / MONTH.
Columns   A/C Code (Customer "A/C Code", else the customer ID), A/C Title (customer name), Sales
          Person (the invoices' Sales Team, else the customer's), Customer (the owner: the
          Customer's Primary Contact, blank when none), City, Region, Area, Brand (short name),
          one column per SKU (14# to 6#: descending Sort Order within each Item Group), Total
          Carton and Avg/Month.
SKUs      The ticked ones; else every SKU of the selected Category (all SKUs without one), as the
          sheet always shows 14# to 6#, plus any other SKU that sold.
Avg/Month Total Carton / calendar months the date range touches (1-30 Nov = 1, Jul-Nov = 5,
          15 Oct-14 Nov = 2).
Not shown Items without a Carton UOM (listed in the data check under the table).
"""

import re
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, formatdate, getdate

from pc_production.pc_production.report_utils import (
	DIVIDE,
	NO_BRAND,
	NO_SKU,
	PACKING_TYPES,
	QTY_TOLERANCE,
	count_months,
	descendants_of,
	get_brand_sku_layout,
	get_invoice_lines,
	get_list,
	get_ordered_skus,
	get_sku_order,
	get_primary_contact_names,
	get_quality_notes,
	plural,
	set_customer_details,
)

MULTI_FILTERS = ("brand", "item_group", "sku", "city", "territory", "area", "sales_person")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	validate_filters(filters)
	months = count_months(filters.from_date, filters.to_date)

	lines = get_invoice_lines(filters)
	quality = get_quality_notes(lines, _("no Carton UOM (not counted)"))
	if not lines:
		return get_columns([]), [], _("No sales found for the selected filters.")

	layout = get_brand_sku_layout(lines, filters, descending_skus=True)
	skus = [frappe._dict(name=sku, fieldname=f"s_{idx}") for idx, sku in enumerate(get_sku_columns(layout, filters))]
	rows = get_rows(lines, skus)
	data = get_data(rows, layout, skus, months, filters, quality)
	return get_columns(skus), data, quality or None


def validate_filters(filters):
	for fieldname, label in (("company", "Company"), ("from_date", "From Date"), ("to_date", "To Date")):
		if not filters.get(fieldname):
			frappe.throw(_("{0} is mandatory").format(_(label)))

	filters.from_date, filters.to_date = getdate(filters.from_date), getdate(filters.to_date)
	if filters.from_date > filters.to_date:
		frappe.throw(_("From Date cannot be after To Date"))

	for fieldname in MULTI_FILTERS:
		filters[fieldname] = get_list(filters.get(fieldname))
	# Single customer (or all): get_invoice_lines takes a list.
	filters.customer = [filters.customer] if filters.get("customer") else []
	if filters.get("packing") not in PACKING_TYPES:
		filters.packing = None


def get_sku_columns(layout, filters):
	"""SKU columns: the ticked ones (layout.skus); else every SKU of the selected Category (all
	SKUs without one) plus any other that sold, from 14# down (descending Sort Order per group)."""
	if filters.sku:
		return layout.skus

	groups = set(descendants_of("Item Group", filters.item_group)) if filters.item_group else None
	skus = set(layout.skus) | {
		d.name for d in get_ordered_skus() if groups is None or d.item_group in groups
	}
	order = get_sku_order(descending=True)
	return sorted(skus, key=lambda n: (n == NO_SKU, order.get(n, len(order)), n.lower()))


def natural_key(value):
	"""'12-999' before '12-1000': digit runs compare as numbers."""
	return [(0, int(part), "") if part.isdigit() else (1, 0, part.lower()) for part in re.split(r"(\d+)", value or "")]


# ============================================================
# ROWS
# ============================================================


def get_rows(lines, skus):
	"""{(brand_key, customer): row} with cartons per SKU column, from lines with a Carton UOM."""
	sku_fields = {sku.name: sku.fieldname for sku in skus}
	rows = {}
	for line in lines:
		fieldname = sku_fields.get(line.sku_key)
		if line.unconverted_qty or not fieldname:
			continue
		key = (line.brand_key, line.customer)
		row = rows.get(key)
		if not row:
			row = rows[key] = frappe._dict(
				brand=line.brand_key,
				customer=line.customer,
				customer_name=line.customer_name,
				city=line.city,
				region=line.region,
				area=line.area,
				officers=set(),
				cartons=defaultdict(float),
			)
		row.officers.update(line.officers)
		cartons = line.cartons * flt(line.factor)
		row.cartons[fieldname] += cartons
		row.cartons["total"] += cartons

	set_customer_details(list(rows.values()))
	owners = get_primary_contact_names({row.customer for row in rows.values()})
	for row in rows.values():
		row.owner = owners.get(row.customer, "")
	return rows


# ============================================================
# OUTPUT
# ============================================================


def get_data(rows, layout, skus, months, filters, quality):
	fields = [sku.fieldname for sku in skus] + ["total"]
	by_brand = defaultdict(list)
	for row in rows.values():
		by_brand[row.brand].append(row)

	def figures(values):
		result = {field: flt(values.get(field)) for field in fields}
		result["average"] = result["total"] / months
		return result

	data = []
	grand = defaultdict(float)
	for index, brand in enumerate(b for b in layout.brands if by_brand.get(b)):
		short = layout.brand_labels.get(brand, brand)
		brand_name = _(NO_BRAND) if brand == NO_BRAND else brand
		data.append(
			{
				"row_type": "brand",
				"customer_name": f"{brand_name} ({short})" if short != brand else brand_name,
				"brand": short,
				"brand_index": index,
				"bold": 1,
			}
		)

		subtotal = defaultdict(float)
		for row in sorted(by_brand[brand], key=lambda r: (natural_key(r.ac_code), r.customer)):
			data.append(
				{
					"row_type": "line",
					"customer": row.customer,
					"ac_code": row.ac_code,
					"customer_name": row.customer_name,
					"sales_person": row.sales_person,
					"owner": row.owner,
					"city": row.city,
					"region": row.region,
					"area": row.area,
					"brand": short,
					**figures(row.cartons),
				}
			)
			for field in fields:
				subtotal[field] += row.cartons[field]

		data.append(
			{
				"row_type": "subtotal",
				"customer_name": _("{0} Total").format(short),
				"brand": short,
				"brand_index": index,
				"bold": 1,
				**figures(subtotal),
			}
		)
		for field in fields:
			grand[field] += subtotal[field]

	if not data:
		return []

	month_label = plural(months, "month", "months")
	average = {field: grand[field] / months for field in fields}
	data.append({"row_type": "total", "customer_name": _("TOTAL CARTONS"), "bold": 1, **figures(grand)})
	data.append(
		{
			"row_type": "average",
			"customer_name": _("AVERAGE / MONTH ({0} {1} {2})").format(DIVIDE, months, month_label),
			"bold": 1,
			**average,
			# Read by the print template: divisor and notes under the table.
			"months": months,
			"average_description": _("Total Carton {0} {1} {2} ({3} to {4}, calendar months touched)").format(
				DIVIDE,
				months,
				month_label,
				formatdate(filters.from_date, "dd-MMM-yyyy"),
				formatdate(filters.to_date, "dd-MMM-yyyy"),
			),
			"quality_notes": quality,
		}
	)
	return [round_tiny(row) for row in data]


def round_tiny(row):
	"""-0.0000001 cartons (a sale fully returned) shows as 0."""
	for key, value in row.items():
		if isinstance(value, float) and abs(value) < QTY_TOLERANCE:
			row[key] = 0.0
	return row


def get_columns(skus):
	def text(label, fieldname, width):
		return {"label": label, "fieldname": fieldname, "fieldtype": "Data", "width": width}

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

	columns = [
		text(_("A/C Code"), "ac_code", 100),
		text(_("A/C Title"), "customer_name", 220),
		text(_("Sales Person"), "sales_person", 140),
		text(_("Customer"), "owner", 140),
		text(_("City"), "city", 100),
		text(_("Region"), "region", 120),
		text(_("Area"), "area", 100),
		text(_("Brand"), "brand", 70),
	]
	columns += [
		qty(
			sku.name,
			sku.fieldname,
			# Two-level print header: "SKU Wise Cartons" over the SKUs.
			group_label=_("SKU Wise Cartons"),
			sub_label=sku.name,
			description=_("SKU Wise Cartons: {0}").format(sku.name),
		)
		for sku in skus
	]
	columns.append(qty(_("Total Carton"), "total", 100))
	columns.append(
		qty(
			_("Avg/Month"),
			"average",
			90,
			precision=1,
			description=_("Total Carton / calendar months in the date range"),
		)
	)
	return columns
