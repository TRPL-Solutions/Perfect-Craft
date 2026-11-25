# Copyright (c) 2026, TRPL Solutions and contributors
# For license information, please see license.txt

"""Shared logic for the carton sales reports (City Wise Sales Report, SKU Wise Sales Analysis,
Customer Wise Discount Report, Sales Summary Report Brand Wise).

Period    From/To Year and From/To Month, like the client's Excel. Each year from From Year to
          To Year starts one period:
            From Month <= To Month: those months of that year (2025-2026, Jan-Feb = Jan+Feb 2025,
            Jan+Feb 2026).
            From Month >  To Month: a season over the year end (2025-2026, Jul-Feb = Jul 2025-
            Feb 2026 and Jul 2026-Feb 2027).
          Reports show one column/row per month NAME, summing that month over all periods.
Lines     Submitted Sales Invoice items in the period (or a plain date range); credit notes count
          negative. Cartons = stock_qty / the item's "Carton" UOM factor; items without one keep
          their stock qty in unconverted_qty.
Packing   Item "Packing Type" (custom_packing_type): Old (Hash) / New (Red) packing of the same
          brand and size as separate items; the Packing filter keeps only items of that packing.
Layout    get_brand_sku_layout: brands and SKUs to show, in Brand / SKU Sort Order (SKUs
          optionally descending, e.g. 14# to 6#).
Officers  The invoice's Sales Team. Quantities are split by allocated_percentage only when the
          Sales Officer filter is used; otherwise every line keeps its full quantity.
Options   get_filter_options: whitelisted filter suggestions for every desk user (the reports have
          no roles), instead of permission-checked link searches.
"""

import calendar

import frappe
from frappe import _
from frappe.utils import cint, flt, get_last_day, getdate

from pc_production.pc_production.report.recovery_report.recovery_report import (
	get_filter_options as get_recovery_filter_options,
)
from pc_production.pc_production.report.recovery_report.recovery_report import get_teams
from pc_production.pc_production.report.sales_person_target_achievement.sales_person_target_achievement import (
	get_carton_factors,
)
from pc_production.pc_production.report.sales_report.sales_report import (
	UNASSIGNED,
	get_descendants,
	get_shares,
	set_customer_geography,
)

MAX_YEARS = 10
MONTHS = list(calendar.month_name)[1:]
QTY_TOLERANCE = 0.0005
EN_DASH, TIMES, DIVIDE = "\u2013", "\u00d7", "\u00f7"
# Multi-select filters understood by get_invoice_lines.
LINE_FILTERS = ("city", "territory", "area", "sales_person", "brand", "sku", "item_group", "customer")
# Item "Packing Type" options (get_invoice_lines: filters.packing).
PACKING_TYPES = ("Old (Hash)", "New (Red)")
NO_BRAND = "(No Brand)"
NO_SKU = "(No SKU)"


# ============================================================
# FILTERS AND PERIOD
# ============================================================


def validate_period_filters(filters, multi_filters=LINE_FILTERS):
	if not filters.company:
		frappe.throw(_("Company is mandatory"))

	filters.from_year, filters.to_year = get_year(filters, "from_year"), get_year(filters, "to_year")
	if filters.from_year > filters.to_year:
		frappe.throw(_("From Year cannot be after To Year"))
	if filters.to_year - filters.from_year + 1 > MAX_YEARS:
		frappe.throw(_("Select at most {0} years").format(MAX_YEARS))

	filters.from_month_no = get_month(filters, "from_month")
	filters.to_month_no = get_month(filters, "to_month")

	for fieldname in multi_filters:
		filters[fieldname] = get_list(filters.get(fieldname))


def get_year(filters, fieldname):
	year = cint(filters.get(fieldname))
	if not 1900 < year < 3000:
		frappe.throw(_("{0} is mandatory").format(_(frappe.unscrub(fieldname))))
	return year


def get_month(filters, fieldname):
	value = filters.get(fieldname)
	if value in MONTHS:
		return MONTHS.index(value) + 1
	if 1 <= cint(value) <= 12:
		return cint(value)
	frappe.throw(_("{0} is mandatory").format(_(frappe.unscrub(fieldname))))


def get_list(value):
	"""MultiSelectList values arrive as a list, or as JSON / a plain string from the API."""
	if not value:
		return []
	if isinstance(value, str):
		value = frappe.parse_json(value) if value.lstrip().startswith("[") else [value]
	return [v for v in value if v]


def get_period(filters):
	"""Selected months in display order, the periods' (year, month) pairs and labels.

	Sets filters.from_date / to_date to the first and last day covered (used by the header).
	"""
	start, end = filters.from_month_no, filters.to_month_no
	wraps = start > end
	numbers = [*range(start, 13), *range(1, end + 1)] if wraps else list(range(start, end + 1))
	years = list(range(filters.from_year, filters.to_year + 1))

	year_months = [
		(year + 1 if wraps and month < start else year, month) for year in years for month in numbers
	]
	first, last = year_months[0], year_months[-1]
	filters.from_date = getdate(f"{first[0]}-{first[1]:02d}-01")
	filters.to_date = get_last_day(f"{last[0]}-{last[1]:02d}-01")

	return frappe._dict(
		months=[
			frappe._dict(
				number=n,
				fieldname=f"m_{n:02d}",
				label=calendar.month_abbr[n],
				full_label=calendar.month_name[n],
			)
			for n in numbers
		],
		numbers=numbers,
		years=years,
		wraps=wraps,
		year_months=year_months,
		count=len(year_months),
		label=get_period_label(numbers, years, wraps),
	)


def get_period_label(numbers, years, wraps=False):
	"""e.g. "Jul-Nov, 2025-2026", "Aug, 2026", "Jul 2025-Feb 2026",
	"Jul-Feb, seasons 2025-26 to 2026-27" (with en dashes)."""
	first, last = calendar.month_abbr[numbers[0]], calendar.month_abbr[numbers[-1]]
	if wraps:
		if len(years) == 1:
			return f"{first} {years[0]} {EN_DASH} {last} {years[0] + 1}"
		return _("{0}{1}{2}, seasons {3} to {4}").format(
			first, EN_DASH, last, season_label(years[0]), season_label(years[-1])
		)

	month_part = first if first == last else f"{first}{EN_DASH}{last}"
	year_part = str(years[0]) if len(years) == 1 else f"{years[0]}{EN_DASH}{years[-1]}"
	return f"{month_part}, {year_part}"


def count_months(from_date, to_date):
	"""Calendar months the date range touches: 1-30 Nov = 1, 15 Oct-14 Nov = 2, Jul-Nov = 5."""
	start, end = getdate(from_date), getdate(to_date)
	return max((end.year - start.year) * 12 + end.month - start.month + 1, 1)


def season_label(year):
	return f"{year}-{str(year + 1)[2:]}"


def plural(count, singular, plural_form):
	return _(singular) if count == 1 else _(plural_form)


# ============================================================
# INVOICE LINES
# ============================================================


def get_invoice_lines(filters, period=None):
	"""Submitted invoice items in the period with geography, brand/SKU, cartons and officers.

	period: the months from get_period; without it, every date from filters.from_date to
	filters.to_date (date range reports such as Customer Wise Discount Report).
	filters.packing: one of PACKING_TYPES keeps only items of that Packing Type.

	Each line: invoice, posting_date, month (number), customer, customer_name, region, city,
	area, item_code, item_name, item_group, brand, sku, cartons, unconverted_qty, factor
	(share counted, 1 without a Sales Officer filter) and officers. Also the invoice line's
	prices and amounts in company currency (item_row, is_return, sales_invoice_item, qty, uom,
	base_price_list_rate, margin_type, base_rate_with_margin, base_rate, base_amount,
	base_net_amount, pricing_rules), unscaled by factor.
	"""
	conditions = [
		"si.docstatus = 1",
		"si.company = %(company)s",
		"si.posting_date between %(from_date)s and %(to_date)s",
	]
	values = {
		"company": filters.company,
		"from_date": filters.from_date,
		"to_date": filters.to_date,
	}
	if period:
		conditions.append("(year(si.posting_date) * 100 + month(si.posting_date)) in %(year_months)s")
		values["year_months"] = [year * 100 + month for year, month in period.year_months]

	if filters.customer:
		values["customers"] = filters.customer
		conditions.append("si.customer in %(customers)s")

	if filters.territory:
		values["territories"] = descendants_of("Territory", filters.territory)
		conditions.append("cust.territory in %(territories)s")

	if filters.brand:
		values["brands"] = filters.brand
		conditions.append("item.brand in %(brands)s")

	if filters.sku:
		values["skus"] = filters.sku
		conditions.append("item.custom_sku in %(skus)s")

	if filters.item_group:
		values["item_groups"] = descendants_of("Item Group", filters.item_group)
		conditions.append("item.item_group in %(item_groups)s")

	if filters.get("packing") in PACKING_TYPES:
		values["packing"] = filters.packing
		conditions.append("item.custom_packing_type = %(packing)s")

	lines = frappe.db.sql(
		f"""
		select
			si.name as invoice, si.posting_date, si.customer,
			coalesce(nullif(cust.customer_name, ''), si.customer_name, si.customer) as customer_name,
			cust.territory, cust.customer_primary_address,
			sii.item_code, coalesce(item.item_name, sii.item_name) as item_name, item.item_group,
			nullif(item.brand, '') as brand, nullif(item.custom_sku, '') as sku, sii.stock_qty,
			sii.name as item_row, si.is_return, sii.sales_invoice_item, sii.qty, sii.uom,
			sii.base_price_list_rate, sii.margin_type, sii.base_rate_with_margin, sii.base_rate,
			sii.base_amount, sii.base_net_amount, sii.pricing_rules
		from `tabSales Invoice` si
		inner join `tabSales Invoice Item` sii on sii.parent = si.name and sii.parenttype = 'Sales Invoice'
		left join `tabItem` item on item.name = sii.item_code
		left join `tabCustomer` cust on cust.name = si.customer
		where {" and ".join(conditions)}
		""",
		values,
		as_dict=True,
	)
	if not lines:
		return []

	set_customer_geography(lines)
	lines = [line for line in lines if matches_geography(line, filters)]
	if not lines:
		return []

	factors = get_carton_factors({line.item_code for line in lines})
	for line in lines:
		line.month = getdate(line.posting_date).month
		factor = factors.get(line.item_code)
		line.cartons = flt(line.stock_qty) / factor if factor else 0
		line.unconverted_qty = 0 if factor else flt(line.stock_qty)

	set_sales_officers(lines, filters)
	return [line for line in lines if line.factor]


def descendants_of(doctype, names):
	return list({d for name in names for d in get_descendants(doctype, name)})


def matches_geography(line, filters):
	if filters.city and line.city.lower() not in {c.strip().lower() for c in filters.city}:
		return False
	if filters.area and line.area.lower() not in {a.strip().lower() for a in filters.area}:
		return False
	return True


def set_sales_officers(lines, filters):
	"""line.officers: sales persons on the invoice; line.factor: share of the qty counted."""
	teams = get_teams("Sales Invoice", {line.invoice for line in lines})
	allowed = set(descendants_of("Sales Person", filters.sales_person)) if filters.sales_person else None

	for line in lines:
		shares = get_shares(teams.get(line.invoice, []))
		if allowed is None:
			line.factor = 1
			line.officers = [sp for sp, _factor in shares if sp != UNASSIGNED]
		else:
			kept = [(sp, factor) for sp, factor in shares if sp in allowed]
			line.factor = sum(factor for _sp, factor in kept)
			line.officers = [sp for sp, _factor in kept]


def get_quality_notes(lines, no_carton_label=None):
	"""Items in the result that are missing a brand, SKU or Carton UOM (listed, never hidden).

	no_carton_label: what the report does with items without a Carton UOM.
	"""
	missing = {
		_("no Brand"): {line.item_code for line in lines if not line.brand},
		_("no SKU"): {line.item_code for line in lines if not line.sku},
		no_carton_label or _("no Carton UOM (shown in stock UOM)"): {
			line.item_code for line in lines if line.unconverted_qty
		},
	}
	notes = [
		_("{0} {1} {2}: {3}").format(
			len(items), plural(len(items), "item has", "items have"), label, ", ".join(sorted(items))
		)
		for label, items in missing.items()
		if items
	]
	return "; ".join(notes)


# ============================================================
# BRAND / SKU LAYOUT
# ============================================================


def get_brand_sku_layout(lines, filters, descending_skus=False):
	"""Brands and SKUs to show, in Brand / SKU Sort Order (blank Sort Order, then (No Brand) /
	(No SKU) last).

	Brands: the ticked ones, else those that sold. SKUs: the ticked ones, else those that sold.
	descending_skus: SKUs from the highest Sort Order down within each Item Group (14# to 6#,
	then Wire 14 No to Wire 10 No); the groups keep their order.
	Sets line.brand_key / line.sku_key (NO_BRAND / NO_SKU when missing). Only lines with cartons
	(a Carton UOM) count as sold.

	Returns brands, skus (names), brand_info ({name: brand with short_name}), brand_labels
	({name: short name, else name}) and sold_pairs ({(brand_key, sku_key)}).
	"""
	brand_info = {d.name: d for d in get_ordered_brands()}
	brand_order = {name: idx for idx, name in enumerate(brand_info)}
	sku_order = get_sku_order(descending_skus)

	def ordered(names, order, missing_label):
		return sorted(names, key=lambda n: (n == missing_label, order.get(n, len(order)), n.lower()))

	for line in lines:
		line.brand_key = line.brand or NO_BRAND
		line.sku_key = line.sku or NO_SKU

	sold_pairs = {(line.brand_key, line.sku_key) for line in lines if not line.unconverted_qty}
	brands = ordered(
		set(filters.brand) if filters.brand else {brand for brand, _sku in sold_pairs}, brand_order, NO_BRAND
	)
	skus = ordered(
		set(filters.sku) if filters.sku else {sku for _brand, sku in sold_pairs}, sku_order, NO_SKU
	)

	return frappe._dict(
		brands=brands,
		skus=skus,
		brand_info=brand_info,
		brand_labels={
			brand: (brand_info.get(brand) or frappe._dict()).short_name or brand for brand in brands
		},
		sold_pairs=sold_pairs,
	)


def get_sku_order(descending=False):
	"""{SKU: position}: Sort Order, or (descending) highest first within each Item Group."""
	skus = get_ordered_skus()
	if descending:
		group_rank = {}
		for d in skus:
			group_rank.setdefault(d.item_group or "", len(group_rank))
		skus = [
			d
			for _rank, block in sorted(
				(rank, [d for d in skus if (d.item_group or "") == group])
				for group, rank in group_rank.items()
			)
			for d in reversed(block)
		]
	return {d.name: idx for idx, d in enumerate(skus)}


# ============================================================
# CUSTOMER DETAILS
# ============================================================


def set_customer_details(rows):
	"""rows: dicts with customer and officers (set of sales persons from the invoices).

	Sets ac_code (Customer "A/C Code", else the customer ID) and sales_person (the officers,
	else the customer's own Sales Team when its invoices had none).
	"""
	if not rows:
		return

	customers = list({row.customer for row in rows})
	codes = dict(
		frappe.get_all(
			"Customer", filters={"name": ["in", customers]}, fields=["name", "custom_ac_code"], as_list=True
		)
	)
	teams = get_teams("Customer", {row.customer for row in rows if not row.officers})

	for row in rows:
		row.ac_code = (codes.get(row.customer) or "").strip() or row.customer
		if not row.officers:
			row.officers = {sp for sp, _f in get_shares(teams.get(row.customer, [])) if sp != UNASSIGNED}
		row.sales_person = ", ".join(sorted(row.officers, key=str.lower))


def get_primary_contact_names(customers):
	"""{customer: full name of its Primary Contact} (customers without one are left out)."""
	if not customers:
		return {}
	contacts = frappe.db.sql(
		"""
		select cust.name, ct.full_name, ct.first_name, ct.middle_name, ct.last_name
		from `tabCustomer` cust
		inner join `tabContact` ct on ct.name = cust.customer_primary_contact
		where cust.name in %(customers)s
		""",
		{"customers": list(customers)},
		as_dict=True,
	)
	names = {}
	for d in contacts:
		name = (d.full_name or "").strip() or " ".join(
			p.strip() for p in (d.first_name, d.middle_name, d.last_name) if p and p.strip()
		)
		if name:
			names[d.name] = name
	return names


# ============================================================
# FILTER OPTIONS
# ============================================================


@frappe.whitelist()
def get_filter_options(doctype, txt="", company=None, item_group=None, **kwargs):
	txt = (txt or "").strip()

	if doctype == "City":
		cities = frappe.db.sql(
			"""
			select distinct trim(addr.city)
			from `tabAddress` addr
			inner join `tabDynamic Link` dl on dl.parent = addr.name and dl.parenttype = 'Address'
			where dl.link_doctype = 'Customer' and addr.disabled = 0
				and ifnull(trim(addr.city), '') != '' and addr.city like %(txt)s
			order by 1
			limit 50
			""",
			{"txt": f"%{txt}%"},
		)
		return [city for (city,) in cities]

	if doctype == "SKU":
		return get_sku_options(txt, item_group)

	if doctype == "Brand":
		return [{"value": d.name, "label": d.short_name or ""} for d in get_ordered_brands(txt)]

	if doctype == "Area":
		return frappe.get_all(
			doctype, filters={"name": ["like", f"%{txt}%"]}, pluck="name", order_by="name asc", limit=50
		)

	if doctype == "Item Group":
		return frappe.get_all(
			"Item Group", filters={"name": ["like", f"%{txt}%"]}, pluck="name", order_by="lft asc", limit=50
		)

	return get_recovery_filter_options(doctype, txt, company=company, **kwargs)


def get_sku_options(txt, item_group=None):
	"""SKUs labelled with their Item Group, in SKU order; typing "Wire" finds the wire SKUs.

	With item_group (one or several, e.g. the report's Item Group filter), only SKUs of those
	groups (or their sub-groups) and SKUs without a group.
	"""
	selected = get_list(item_group)
	groups = descendants_of("Item Group", selected) if selected else None
	txt = txt.lower()
	return [
		{"value": d.name, "label": d.item_group or ""}
		for d in get_ordered_skus()
		if (txt in d.name.lower() or txt in (d.item_group or "").lower())
		and (groups is None or not d.item_group or d.item_group in groups)
	][:50]


def get_ordered_skus():
	"""All SKUs by Sort Order (blank last), then name."""
	skus = frappe.get_all("SKU", fields=["name", "item_group", "sort_order"])
	return sorted(skus, key=lambda d: (not cint(d.sort_order), cint(d.sort_order), d.name.lower()))


def get_ordered_brands(txt=""):
	"""Brands by Sort Order (blank last), then name, with their short names."""
	has_fields = frappe.get_meta("Brand").has_field("custom_sort_order")
	fields = ["name"] + (
		["custom_short_name as short_name", "custom_sort_order as sort_order"] if has_fields else []
	)
	brands = frappe.get_all("Brand", filters={"name": ["like", f"%{txt}%"]}, fields=fields)
	return sorted(brands, key=lambda d: (not cint(d.sort_order), cint(d.sort_order), d.name.lower()))
