# Copyright (c) 2026, TRPL Solutions and contributors
# For license information, please see license.txt

"""City Wise Sales Report: cartons sold per month name, by City or by Customer.

Period        From/To Year and From/To Month, like the client's Excel: every selected month in
              every selected calendar year. 2025-2026, Jan-Feb = Jan 2025, Feb 2025, Jan 2026,
              Feb 2026. From Month after To Month wraps over the year end (Jul-Feb = Jul..Dec,
              Jan, Feb of each selected year).
Columns       One per month NAME, summing that month over all selected years.
Source        Submitted Sales Invoices; credit notes count negative.
Cartons       stock_qty / the item's "Carton" UOM factor (Sales Person Target Achievement's
              get_carton_factors). Items without a Carton UOM go to "Qty without Carton UOM"
              (stock UOM), shown only when not zero.
Rows          City (customer's primary Address) or Customer. Ranked by Total CTN, descending,
              ties by name; rows with nothing sold are hidden.
Sales Officer The invoice's Sales Team. Quantities are split by allocated_percentage only when
              the Sales Officer filter is used; otherwise every row keeps its full quantity.
Brand / SKU   Item.brand / Item.custom_sku (filters only).
Per Month Avg Total CTN / months covered (months x years). "Monthly Average" footer = month
              total / rows.
"""

import calendar
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from pc_production.pc_production.report.recovery_report.recovery_report import (
	get_filter_options as get_recovery_filter_options,
)
from pc_production.pc_production.report.recovery_report.recovery_report import (
	get_report_header,
	get_teams,
)
from pc_production.pc_production.report.sales_person_target_achievement.sales_person_target_achievement import (
	get_carton_factors,
)
from pc_production.pc_production.report.sales_report.sales_report import (
	NOT_AVAILABLE,
	UNASSIGNED,
	get_descendants,
	get_shares,
	set_customer_geography,
)

MAX_YEARS = 10
MONTHS = list(calendar.month_name)[1:]
MULTI_FILTERS = ("city", "territory", "area", "sales_person", "brand", "sku", "customer")
CHART_TOP = 10
QTY_TOLERANCE = 0.0005
EN_DASH, TIMES, DIVIDE = "\u2013", "\u00d7", "\u00f7"


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


# ============================================================
# FILTERS AND PERIOD
# ============================================================


def validate_filters(filters):
	if not filters.company:
		frappe.throw(_("Company is mandatory"))

	filters.group_by = filters.group_by or "City"
	if filters.group_by not in ("City", "Customer"):
		frappe.throw(_("Group By must be City or Customer"))

	filters.from_year, filters.to_year = get_year(filters, "from_year"), get_year(filters, "to_year")
	if filters.from_year > filters.to_year:
		frappe.throw(_("From Year cannot be after To Year"))
	if filters.to_year - filters.from_year + 1 > MAX_YEARS:
		frappe.throw(_("Select at most {0} years").format(MAX_YEARS))

	filters.from_month_no = get_month(filters, "from_month")
	filters.to_month_no = get_month(filters, "to_month")

	for fieldname in MULTI_FILTERS:
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
	"""Selected month numbers in column order (wrapping over the year end) and the years."""
	start, end = filters.from_month_no, filters.to_month_no
	numbers = list(range(start, end + 1)) if start <= end else [*range(start, 13), *range(1, end + 1)]
	years = list(range(filters.from_year, filters.to_year + 1))
	months = [frappe._dict(number=n, fieldname=f"m_{n:02d}", label=calendar.month_abbr[n]) for n in numbers]
	period = frappe._dict(
		months=months,
		numbers=numbers,
		years=years,
		count=len(numbers) * len(years),
		label=get_period_label(numbers, years),
	)
	# Header (company / fiscal year lookup) spans the selected calendar years.
	filters.from_date = getdate(f"{years[0]}-01-01")
	filters.to_date = getdate(f"{years[-1]}-12-31")
	return period


def get_period_label(numbers, years):
	"""e.g. "Jul-Nov, 2025-2026" (with en dashes), "Aug, 2026"."""
	first, last = calendar.month_abbr[numbers[0]], calendar.month_abbr[numbers[-1]]
	month_part = first if first == last else f"{first}{EN_DASH}{last}"
	year_part = str(years[0]) if len(years) == 1 else f"{years[0]}{EN_DASH}{years[-1]}"
	return f"{month_part}, {year_part}"


def get_average_description(period):
	months, years = len(period.numbers), len(period.years)
	return _("Total CTN {0} {1} months covered ({2} {3} {4} {5} {6})").format(
		DIVIDE,
		period.count,
		months,
		_("month") if months == 1 else _("months"),
		TIMES,
		years,
		_("year") if years == 1 else _("years"),
	)


# ============================================================
# DATA
# ============================================================


def get_invoice_lines(filters, period):
	conditions = [
		"si.docstatus = 1",
		"si.company = %(company)s",
		"si.posting_date between %(from_date)s and %(to_date)s",
		"month(si.posting_date) in %(months)s",
	]
	values = {
		"company": filters.company,
		"from_date": filters.from_date,
		"to_date": filters.to_date,
		"months": period.numbers,
	}

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

	lines = frappe.db.sql(
		f"""
		select
			si.name as invoice, si.posting_date, si.customer,
			coalesce(nullif(cust.customer_name, ''), si.customer_name, si.customer) as customer_name,
			cust.territory, cust.customer_primary_address,
			sii.item_code, sii.stock_qty
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
			"average": row.total / period.count,
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
		"average": grand_total / period.count,
	}
	average_line = {
		"row_type": "monthly_average",
		"name": _("Monthly Average"),
		"bold": 1,
		**{fieldname: amount / len(rows) for fieldname, amount in totals.items()},
		"total": grand_total / len(rows),
		"average": grand_total / period.count / len(rows),
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


# ============================================================
# FILTER OPTIONS
#
# Open to every desk user (no roles, ref_doctype Item Group) like the other pc_production
# reports, so filter options come from this whitelisted method, not permission-checked
# link searches.
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

	if doctype in ("Area", "Brand"):
		return frappe.get_all(
			doctype, filters={"name": ["like", f"%{txt}%"]}, pluck="name", order_by="name asc", limit=50
		)

	return get_recovery_filter_options(doctype, txt, company=company, **kwargs)


def get_sku_options(txt, item_group=None):
	"""SKUs labelled with their Item Group; typing "Wire" finds the wire SKUs.

	With item_group, only SKUs of that group (or its sub-groups) and SKUs without a group.
	"""
	conditions = []
	if item_group:
		conditions.append(["item_group", "in", [*get_descendants("Item Group", item_group), ""]])

	skus = frappe.get_all(
		"SKU",
		filters=conditions,
		or_filters={"name": ["like", f"%{txt}%"], "item_group": ["like", f"%{txt}%"]},
		fields=["name", "item_group"],
		order_by="item_group asc, name asc",
		limit=50,
	)
	if item_group:
		# "in [..., ""]" does not match NULL item groups.
		skus += [
			d
			for d in frappe.get_all(
				"SKU",
				filters={"item_group": ["is", "not set"], "name": ["like", f"%{txt}%"]},
				fields=["name", "item_group"],
			)
			if d not in skus
		]
	return [{"value": d.name, "label": d.item_group or ""} for d in skus]
