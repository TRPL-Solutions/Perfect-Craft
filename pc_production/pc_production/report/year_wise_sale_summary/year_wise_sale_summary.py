# Copyright (c) 2026, TRPL Solutions and contributors
# For license information, please see license.txt

"""Year Wise Sale Summary: the client's sheet "8" (e.g. "TALHA H/W MULTAN - BRAND WISE SALES").

Cartons sold per month and brand, from submitted Sales Invoices (credit notes negative); lines,
cartons, geography and the Sales Person split come from report_utils.get_invoice_lines (with a
Sales Person filter every quantity is that person's share, as in the other carton reports).

Period   ONE continuous range: From Year + From Month to To Year + To Month (Jul 2025 - Jul 2026 =
         13 months). Not report_utils.get_period, which repeats the same months in each year.
Rows     One per month in the range (months without sales show 0).
Columns  One per brand (Brand Sort Order; the ticked brands, else those that sold), a brand with
         Packing Types split into "<Brand> (New)" (New (Red)) and "<Brand>#" (Old (Hash)); then
         Total CTN; then % per brand column = brand / month total.
Footer   TOTAL CTN     sums; % = brand total / grand total (the shares add up to 100%).
         AVERAGE PER MONTH  total / months in the range (zero months included); % as TOTAL.
         MAX CTN / MIN CTN  highest / lowest month (zero months included); % = highest / lowest
                       monthly share among months with sales.
         (The client sheet's 99% / 89% came from Total CTN = B24 + C23 and from averaging and
         maxing over its own footer rows.)
Title    With a Customer: "<CUSTOMER NAME> <CITY> - BRAND WISE SALES (JUL 2025 - JUL 2026)" and
         "S/O: <the customer's Sales Team>"; else "BRAND WISE SALES (...)" and the selected
         Sales Persons. Carried on the TOTAL CTN row for the print (no message on screen).
Not shown Items without a Carton UOM (listed in the print notes).
"""

import calendar
from collections import defaultdict
from datetime import date

import frappe
from frappe import _
from frappe.utils import flt

from pc_production.pc_production.report.recovery_report.recovery_report import get_teams
from pc_production.pc_production.report.sales_report.sales_report import (
	UNASSIGNED,
	get_shares,
	set_customer_geography,
)
from pc_production.pc_production.report_utils import (
	EN_DASH,
	MAX_YEARS,
	NO_BRAND,
	PACKING_TYPES,
	QTY_TOLERANCE,
	get_brand_sku_layout,
	get_invoice_lines,
	get_list,
	get_month,
	get_quality_notes,
	get_year,
)

MULTI_FILTERS = ("city", "territory", "area", "sales_person", "brand", "sku")
OLD_PACKING, NEW_PACKING = PACKING_TYPES  # "Old (Hash)", "New (Red)"
# Column order within a brand, as in the sheet: New, then # (Old), then items without a packing.
PACKING_ORDER = {NEW_PACKING: 0, OLD_PACKING: 1, None: 2}
FOOTER = ("total", "average", "max", "min")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	months = validate_filters(filters)

	lines = get_invoice_lines(filters)
	if not lines:
		return get_columns([]), []

	quality = get_quality_notes(lines, _("no Carton UOM (not counted)"))
	heading = get_heading(filters)

	set_packing(lines)
	layout = get_brand_sku_layout(lines, filters)
	brand_cols = get_brand_columns(lines, layout)
	data = get_data(lines, brand_cols, months, heading, quality)
	return get_columns(brand_cols), data


def validate_filters(filters):
	"""Sets from_date / to_date of the continuous range; returns its months [(year, month)]."""
	if not filters.get("company"):
		frappe.throw(_("{0} is mandatory").format(_("Company")))

	start = (get_year(filters, "from_year"), get_month(filters, "from_month"))
	end = (get_year(filters, "to_year"), get_month(filters, "to_month"))
	if start > end:
		frappe.throw(_("From Year / Month cannot be after To Year / Month"))

	months = []
	year, month = start
	while (year, month) <= end:
		months.append((year, month))
		year, month = (year + 1, 1) if month == 12 else (year, month + 1)
	if len(months) > MAX_YEARS * 12:
		frappe.throw(_("Select at most {0} years").format(MAX_YEARS))

	filters.from_date = date(*start, 1)
	filters.to_date = date(*end, calendar.monthrange(*end)[1])
	for fieldname in MULTI_FILTERS:
		filters[fieldname] = get_list(filters.get(fieldname))
	# Single customer (or all): get_invoice_lines takes a list.
	filters.customer = [filters.customer] if filters.get("customer") else []
	return months


def month_label(year, month):
	return f"{calendar.month_abbr[month]} {year}"


# ============================================================
# HEADING (title + sales person)
# ============================================================


def get_heading(filters):
	period = f"{month_label(filters.from_date.year, filters.from_date.month)} {EN_DASH} " \
		f"{month_label(filters.to_date.year, filters.to_date.month)}"
	title = _("BRAND WISE SALES ({0})").format(period.upper())

	if filters.customer:
		customer = frappe.db.get_value(
			"Customer", filters.customer[0], ["name as customer", "customer_name", "territory", "customer_primary_address"],
			as_dict=True,
		)
		if customer:
			set_customer_geography([customer])
			name = customer.customer_name or customer.customer
			city = customer.city if customer.city and customer.city != "N/A" else ""
			if city and city.lower() not in name.lower():
				name = f"{name} {city}"
			title = f"{name.upper()} {EN_DASH} {title}"
			team = get_teams("Customer", {customer.customer}).get(customer.customer, [])
			officers = [sp for sp, _f in get_shares(team) if sp != UNASSIGNED] or [sp for sp, _p in team]
			sales_person = ", ".join(dict.fromkeys(officers))
		else:
			sales_person = ""
	else:
		sales_person = ", ".join(filters.sales_person)

	return frappe._dict(title=title, sales_person=sales_person, period=period)


# ============================================================
# BRAND COLUMNS
# ============================================================


def set_packing(lines):
	"""line.packing: the item's Packing Type (Old (Hash) / New (Red)), else None."""
	packing = dict(
		frappe.get_all(
			"Item",
			filters={"name": ["in", list({line.item_code for line in lines})]},
			fields=["name", "custom_packing_type"],
			as_list=True,
		)
	)
	for line in lines:
		value = packing.get(line.item_code)
		line.packing = value if value in PACKING_TYPES else None


def get_brand_columns(lines, layout):
	"""[{key: (brand, packing), fieldname, label, short, pct_fieldname}] in brand / packing order."""
	sold = defaultdict(set)
	for line in lines:
		if not line.unconverted_qty:
			sold[line.brand_key].add(line.packing)

	columns = []
	for brand in layout.brands:
		packings = sorted(sold.get(brand) or {None}, key=lambda p: PACKING_ORDER[p])
		name = _(NO_BRAND) if brand == NO_BRAND else brand
		short = layout.brand_labels.get(brand, brand)
		for packing in packings:
			suffix = {NEW_PACKING: " (New)", OLD_PACKING: "#"}.get(packing, "")
			idx = len(columns)
			columns.append(
				frappe._dict(
					key=(brand, packing),
					fieldname=f"b_{idx}",
					pct_fieldname=f"p_{idx}",
					label=f"{name}{suffix}",
					short=f"{_(NO_BRAND) if brand == NO_BRAND else short}{suffix}",
				)
			)
	return columns


# ============================================================
# DATA
# ============================================================


def get_data(lines, brand_cols, months, heading, quality):
	field_by_key = {col.key: col.fieldname for col in brand_cols}
	fields = [col.fieldname for col in brand_cols]
	cartons = defaultdict(lambda: defaultdict(float))
	for line in lines:
		fieldname = field_by_key.get((line.brand_key, line.packing))
		if line.unconverted_qty or not fieldname:
			continue
		posted = frappe.utils.getdate(line.posting_date)
		qty = line.cartons * flt(line.factor)
		cartons[(posted.year, posted.month)][fieldname] += qty
		cartons[(posted.year, posted.month)]["total"] += qty

	def shares(values):
		total = flt(values.get("total"))
		if abs(total) < QTY_TOLERANCE:
			return {col.pct_fieldname: None for col in brand_cols}
		return {col.pct_fieldname: flt(values.get(col.fieldname)) / total * 100 for col in brand_cols}

	data = []
	for year, month in months:
		values = {field: flt(cartons[(year, month)].get(field)) for field in fields + ["total"]}
		data.append({"row_type": "month", "month": month_label(year, month), **values, **shares(values)})

	month_rows = list(data)
	count = len(month_rows)
	sums = {field: sum(r[field] for r in month_rows) for field in fields + ["total"]}
	selling = [r for r in month_rows if abs(r["total"]) >= QTY_TOLERANCE]

	def pick(fn):
		values = {field: fn(r[field] for r in month_rows) for field in fields + ["total"]}
		pct = {
			col.pct_fieldname: fn(r[col.pct_fieldname] for r in selling) if selling else None for col in brand_cols
		}
		return {**values, **pct}

	data.append(
		{
			"row_type": "total",
			"month": _("TOTAL CTN"),
			"bold": 1,
			**sums,
			**shares(sums),
			# Read by the print: title, sales person, period and notes.
			"report_title": heading.title,
			"sales_person": heading.sales_person,
			"period_label": heading.period,
			"quality_notes": quality,
		}
	)
	average = {field: sums[field] / count for field in fields + ["total"]}
	data.append({"row_type": "average", "month": _("AVERAGE PER MONTH"), "bold": 1, **average, **shares(average)})
	data.append({"row_type": "max", "month": _("MAX CTN"), "bold": 1, **pick(max)})
	data.append({"row_type": "min", "month": _("MIN CTN"), "bold": 1, **pick(min)})
	return [round_tiny(row) for row in data]


def round_tiny(row):
	"""-0.0000001 cartons (a sale fully returned) shows as 0."""
	for key, value in row.items():
		if isinstance(value, float) and abs(value) < QTY_TOLERANCE:
			row[key] = 0.0
	return row


def get_columns(brand_cols):
	def qty(label, fieldname, width=100):
		# Whole cartons on screen and in print, averages included (see the formatter).
		return {"label": label, "fieldname": fieldname, "fieldtype": "Float", "precision": 0, "width": width}

	columns = [{"label": _("Month"), "fieldname": "month", "fieldtype": "Data", "width": 140}]
	columns += [qty(col.label, col.fieldname, 130) for col in brand_cols]
	columns.append(qty(_("Total CTN"), "total", 100))
	columns += [
		{
			"label": f"% {col.short}",
			"fieldname": col.pct_fieldname,
			"fieldtype": "Percent",
			"precision": 1,
			"width": 90,
			"description": _("{0} / Total CTN").format(col.label),
		}
		for col in brand_cols
	]
	return columns


@frappe.whitelist()
def get_customer_options(txt=""):
	"""Customer filter: search A/C Code, ID or name; label "A/C Code: Customer Name"."""
	txt = (txt or "").strip()
	customers = frappe.get_all(
		"Customer",
		filters={"disabled": 0},
		or_filters={
			"name": ["like", f"%{txt}%"],
			"customer_name": ["like", f"%{txt}%"],
			"custom_ac_code": ["like", f"%{txt}%"],
		},
		fields=["name", "customer_name", "custom_ac_code"],
		order_by="customer_name asc",
		limit=50,
	)
	return [
		{
			"value": c.name,
			"label": f"{(c.custom_ac_code or '').strip() or c.name}: {c.customer_name or c.name}",
		}
		for c in customers
	]
