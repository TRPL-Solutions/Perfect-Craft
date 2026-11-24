# Copyright (c) 2026, TRPL Solutions and contributors
# For license information, please see license.txt

"""Sales Person Target Achievement.

Target Qty   Sales Person -> Targets (Target Detail.target_qty, in cartons). The yearly
             target is prorated to the selected dates by its Monthly Distribution (equal
             1/12 per month when none) and by days for part months.
Achieved Qty Submitted Sales Invoices in the date range (credit notes negative), split by
             Sales Team allocated_percentage, converted to cartons through the item's
             "Carton" UOM. Matched to the most specific targeted Item Group.
Remarks      Payment status of the same invoices, from outstanding_amount (as of today).
"""

from collections import defaultdict
from itertools import groupby

import frappe
from frappe import _
from frappe.utils import add_days, date_diff, flt, get_first_day, get_last_day, getdate

from pc_production.pc_production.report.sales_report.sales_report import (
	UNASSIGNED,
	get_descendants,
	get_shares,
)

CARTON = "Carton"
GROUP_BY_SALES_PERSON = "Sales Person"
GROUP_BY_ITEM_GROUP = "Sales Person and Item Group"
RECEIVED, PARTIALLY_RECEIVED, NOT_RECEIVED = "Received", "Partially Received", "Not Received"
# Monthly Distribution stores English month names; strftime("%B") would follow the locale.
MONTHS = (
	"January",
	"February",
	"March",
	"April",
	"May",
	"June",
	"July",
	"August",
	"September",
	"October",
	"November",
	"December",
)
AMOUNT_TOLERANCE = 0.005


def execute(filters=None):
	filters = frappe._dict(filters or {})
	validate_filters(filters)

	currency = frappe.get_cached_value("Company", filters.company, "default_currency")
	by_item_group = filters.group_by == GROUP_BY_ITEM_GROUP
	tree = ItemGroupTree()

	targets = get_targets(filters, tree)
	lines = get_invoice_lines(filters, tree, currency)
	rows = build_rows(targets, lines, tree, by_item_group)

	has_unconverted = any(abs(row.unconverted_qty) > 1e-9 for row in rows)
	return get_columns(by_item_group, has_unconverted), get_data(rows, by_item_group, currency)


def validate_filters(filters):
	for fieldname, label in (("company", "Company"), ("from_date", "From Date"), ("to_date", "To Date")):
		if not filters.get(fieldname):
			frappe.throw(_("{0} is mandatory").format(_(label)))

	filters.from_date, filters.to_date = getdate(filters.from_date), getdate(filters.to_date)
	if filters.from_date > filters.to_date:
		frappe.throw(_("From Date cannot be after To Date"))

	if filters.fiscal_year:
		dates = frappe.db.get_value("Fiscal Year", filters.fiscal_year, ["year_start_date", "year_end_date"])
		if not dates:
			frappe.throw(_("Fiscal Year {0} does not exist").format(filters.fiscal_year))

		start, end = getdate(dates[0]), getdate(dates[1])
		if filters.from_date < start or filters.to_date > end:
			frappe.throw(
				_("From Date and To Date must be within Fiscal Year {0} ({1} to {2})").format(
					filters.fiscal_year, frappe.format(start, "Date"), frappe.format(end, "Date")
				)
			)

	if filters.group_by not in (GROUP_BY_SALES_PERSON, GROUP_BY_ITEM_GROUP):
		filters.group_by = GROUP_BY_SALES_PERSON


# ============================================================
# FILTER HELPERS
#
# The report is open to every desk user (no roles, ref_doctype Item Group), but most of
# them have no permission on Sales Person, Territory or Fiscal Year, so Link filters on
# those would fail to search and validate. These filters are Autocomplete fields fed by
# the names below: the same names the report itself shows.
# ============================================================

FILTER_DOCTYPES = ("Sales Person", "Territory", "Fiscal Year")


@frappe.whitelist()
def get_filter_options(doctype, txt="", **kwargs):
	if doctype not in FILTER_DOCTYPES:
		frappe.throw(_("Not allowed"), frappe.PermissionError)

	conditions = {"name": ["like", f"%{txt or ''}%"]}
	if doctype == "Fiscal Year":
		conditions["disabled"] = 0
		order_by = "year_start_date desc"
	elif doctype == "Sales Person":
		conditions["enabled"] = 1
		order_by = "lft asc"
	else:
		order_by = "lft asc"

	return frappe.get_all(doctype, filters=conditions, order_by=order_by, limit=50, pluck="name")


@frappe.whitelist()
def get_fiscal_year_dates(fiscal_year):
	dates = frappe.db.get_value(
		"Fiscal Year", fiscal_year, ["year_start_date", "year_end_date"], as_dict=True
	)
	return dates or {}


class ItemGroupTree:
	def __init__(self):
		self.nodes = {
			d.name: (d.lft, d.rgt) for d in frappe.get_all("Item Group", fields=["name", "lft", "rgt"])
		}
		self.root = min(self.nodes, key=lambda name: self.nodes[name][0]) if self.nodes else None

	def contains(self, ancestor, item_group):
		"""True if item_group is ancestor or one of its descendants."""
		if ancestor == item_group:
			return True

		parent, node = self.nodes.get(ancestor), self.nodes.get(item_group)
		return bool(parent and node and parent[0] <= node[0] and node[1] <= parent[1])

	def most_specific(self, item_group, candidates):
		"""The deepest candidate group that contains item_group, or None."""
		matches = [c for c in candidates if self.contains(c, item_group)]
		return max(matches, key=lambda c: self.nodes.get(c, (0, 0))[0]) if matches else None


def get_sales_person_scope(filters):
	return set(get_descendants("Sales Person", filters.sales_person)) if filters.sales_person else None


# ============================================================
# TARGETS
# ============================================================


def get_targets(filters, tree):
	"""{(sales_person, item_group): target qty prorated to the date range}.

	A target without an Item Group covers every group and is keyed on the root group.
	"""
	fiscal_years = get_fiscal_years(filters)
	if not fiscal_years:
		return {}

	conditions = {"parenttype": "Sales Person", "fiscal_year": ["in", list(fiscal_years)]}
	scope = get_sales_person_scope(filters)
	if scope is not None:
		conditions["parent"] = ["in", list(scope)]

	details = frappe.get_all(
		"Target Detail",
		filters=conditions,
		fields=["parent", "item_group", "fiscal_year", "target_qty", "distribution_id"],
	)

	if filters.item_group:
		# A target for all groups (or a parent group) cannot be split down to the filtered group.
		details = [d for d in details if d.item_group and tree.contains(filters.item_group, d.item_group)]

	distributions = get_distributions({d.distribution_id for d in details if d.distribution_id})
	targets = defaultdict(float)

	for d in details:
		year_start, year_end = fiscal_years[d.fiscal_year]
		share = get_period_share(
			max(filters.from_date, year_start),
			min(filters.to_date, year_end),
			distributions.get(d.distribution_id) if d.distribution_id else None,
		)
		targets[(d.parent, d.item_group or tree.root)] += flt(d.target_qty) * share

	return targets


def get_fiscal_years(filters):
	"""Fiscal years of the company that overlap the date range: {name: (start, end)}."""
	years = frappe.db.sql(
		"""
		select fy.name, fy.year_start_date, fy.year_end_date
		from `tabFiscal Year` fy
		where fy.disabled = 0
			and fy.year_start_date <= %(to_date)s and fy.year_end_date >= %(from_date)s
			and (
				not exists (select 1 from `tabFiscal Year Company` fyc where fyc.parent = fy.name)
				or exists (
					select 1 from `tabFiscal Year Company` fyc
					where fyc.parent = fy.name and fyc.company = %(company)s
				)
			)
		""",
		{"from_date": filters.from_date, "to_date": filters.to_date, "company": filters.company},
		as_dict=True,
	)

	if filters.fiscal_year:
		years = [fy for fy in years if fy.name == filters.fiscal_year]

	return {fy.name: (getdate(fy.year_start_date), getdate(fy.year_end_date)) for fy in years}


def get_distributions(names):
	"""{distribution: {month name: percentage}}"""
	if not names:
		return {}

	distributions = {name: defaultdict(float) for name in names}
	for d in frappe.get_all(
		"Monthly Distribution Percentage",
		filters={"parenttype": "Monthly Distribution", "parent": ["in", list(names)]},
		fields=["parent", "month", "percentage_allocation"],
	):
		distributions[d.parent][(d.month or "").strip().title()] += flt(d.percentage_allocation)

	return distributions


def get_period_share(start, end, percentages=None):
	"""Fraction of a yearly target that falls between start and end (both inclusive).

	Each month contributes its Monthly Distribution percentage (100/12 without one),
	scaled by the share of its days inside the range.
	"""
	share = 0.0
	month_start = get_first_day(start)

	while month_start <= end:
		month_end = get_last_day(month_start)
		days = date_diff(min(end, month_end), max(start, month_start)) + 1
		if percentages is None:
			month_percentage = 100 / 12
		else:
			month_percentage = percentages.get(MONTHS[month_start.month - 1], 0)

		share += month_percentage / 100 * days / month_end.day
		month_start = add_days(month_end, 1)

	return share


# ============================================================
# ACHIEVED (SALES INVOICES)
# ============================================================


def get_invoice_lines(filters, tree, currency):
	"""Submitted invoice items with carton qty, payment amounts and salesperson shares."""
	conditions = [
		"si.docstatus = 1",
		"si.company = %(company)s",
		"si.posting_date between %(from_date)s and %(to_date)s",
	]
	values = {"company": filters.company, "from_date": filters.from_date, "to_date": filters.to_date}

	if filters.territory:
		values["territories"] = get_descendants("Territory", filters.territory)
		conditions.append("si.territory in %(territories)s")

	lines = frappe.db.sql(
		f"""
		select
			si.name as invoice, si.party_account_currency, si.conversion_rate,
			si.grand_total, si.rounded_total, si.base_grand_total, si.base_rounded_total,
			si.base_net_total, si.outstanding_amount,
			sii.item_code, sii.item_group, sii.stock_qty, sii.base_net_amount
		from `tabSales Invoice` si
		inner join `tabSales Invoice Item` sii on sii.parent = si.name and sii.parenttype = 'Sales Invoice'
		where {" and ".join(conditions)}
		order by si.posting_date, si.name, sii.idx
		""",
		values,
		as_dict=True,
	)

	if not lines:
		return []

	# Counted before the Item Group filter, so a line's payment share stays the same.
	line_count = defaultdict(int)
	for line in lines:
		line_count[line.invoice] += 1

	if filters.item_group:
		lines = [line for line in lines if tree.contains(filters.item_group, line.item_group)]

	shares = get_invoice_shares({line.invoice for line in lines}, get_sales_person_scope(filters))
	factors = get_carton_factors({line.item_code for line in lines})

	result = []
	for line in lines:
		line.shares = shares.get(line.invoice)
		if not line.shares:
			continue

		factor = factors.get(line.item_code)
		line.cartons = flt(line.stock_qty) / factor if factor else 0
		line.unconverted_qty = 0 if factor else flt(line.stock_qty)

		payable, outstanding = get_invoice_payable(line, currency)
		if flt(line.base_net_total):
			portion = flt(line.base_net_amount) / flt(line.base_net_total)
		else:
			portion = 1 / line_count[line.invoice]
		line.invoiced = payable * portion
		line.outstanding = outstanding * portion
		result.append(line)

	return result


def get_invoice_payable(invoice, currency):
	"""(amount payable, outstanding) in company currency.

	outstanding_amount is kept in the party account currency against the rounded total
	(grand total when rounding is disabled).
	"""
	if invoice.party_account_currency and invoice.party_account_currency != currency:
		rate = flt(invoice.conversion_rate) or 1
		payable = flt(invoice.rounded_total) or flt(invoice.grand_total)
		return payable * rate, flt(invoice.outstanding_amount) * rate

	payable = flt(invoice.base_rounded_total) or flt(invoice.base_grand_total)
	return payable, flt(invoice.outstanding_amount)


def get_invoice_shares(invoices, scope):
	"""{invoice: [(sales_person, factor)]} without the unassigned part."""
	if not invoices:
		return {}

	teams = defaultdict(list)
	for d in frappe.get_all(
		"Sales Team",
		filters={"parenttype": "Sales Invoice", "parent": ["in", list(invoices)]},
		fields=["parent", "sales_person", "allocated_percentage"],
		order_by="idx asc",
	):
		teams[d.parent].append((d.sales_person, flt(d.allocated_percentage)))

	shares = {}
	for invoice in invoices:
		shares[invoice] = [
			(sp, factor)
			for sp, factor in get_shares(teams.get(invoice, []))
			if sp != UNASSIGNED and (scope is None or sp in scope)
		]

	return shares


def get_carton_factors(item_codes):
	"""{item_code: stock units per Carton} for items that have a Carton UOM."""
	if not item_codes:
		return {}

	factors = {
		d.parent: flt(d.conversion_factor)
		for d in frappe.get_all(
			"UOM Conversion Detail",
			filters={"parenttype": "Item", "parent": ["in", list(item_codes)], "uom": CARTON},
			fields=["parent", "conversion_factor"],
		)
		if flt(d.conversion_factor) > 0
	}
	for item_code in frappe.get_all(
		"Item", filters={"name": ["in", list(item_codes)], "stock_uom": CARTON}, pluck="name"
	):
		factors[item_code] = 1

	return factors


# ============================================================
# ROWS
# ============================================================


def build_rows(targets, lines, tree, by_item_group):
	rows = {}
	targeted_groups = defaultdict(list)

	def get_row(sales_person, item_group):
		key = (sales_person, item_group if by_item_group else None)
		if key not in rows:
			rows[key] = frappe._dict(
				sales_person=sales_person,
				item_group=key[1],
				target_qty=0,
				achieved_qty=0,
				unconverted_qty=0,
				invoiced=0,
				outstanding=0,
				invoices=set(),
			)
		return rows[key]

	for (sales_person, item_group), qty in targets.items():
		get_row(sales_person, item_group).target_qty += qty
		targeted_groups[sales_person].append(item_group)

	for line in lines:
		for sales_person, factor in line.shares:
			item_group = tree.most_specific(line.item_group, targeted_groups.get(sales_person, []))
			row = get_row(sales_person, item_group or line.item_group)
			row.achieved_qty += line.cartons * factor
			row.unconverted_qty += line.unconverted_qty * factor
			row.invoiced += line.invoiced * factor
			row.outstanding += line.outstanding * factor
			row.invoices.add(line.invoice)

	return sorted(rows.values(), key=lambda r: (r.sales_person.lower(), (r.item_group or "").lower()))


def get_data(rows, by_item_group, currency):
	data = []
	total = new_totals()

	for sales_person, group in groupby(rows, key=lambda r: r.sales_person):
		group = list(group)
		subtotal = new_totals()

		for row in group:
			data.append(make_line(row, "item_group" if by_item_group else "sales_person", currency))
			add_to(subtotal, row)
			add_to(total, row)

		if by_item_group:
			subtotal.sales_person = _("{0} Total").format(sales_person)
			data.append(make_line(subtotal, "sales_person_total", currency, bold=1))

	if data:
		total.sales_person = _("Total")
		data.append(make_line(total, "grand_total", currency, bold=1))

	return data


def new_totals():
	return frappe._dict(
		sales_person=None,
		item_group=None,
		target_qty=0,
		achieved_qty=0,
		unconverted_qty=0,
		invoiced=0,
		outstanding=0,
		invoices=set(),
	)


def add_to(totals, row):
	for field in ("target_qty", "achieved_qty", "unconverted_qty", "invoiced", "outstanding"):
		totals[field] += row[field]
	totals.invoices |= row.invoices


def make_line(row, row_type, currency, bold=0):
	line = {
		"row_type": row_type,
		"sales_person": row.sales_person,
		"item_group": row.item_group,
		"target_qty": row.target_qty,
		"achieved_qty": row.achieved_qty,
		"achievement": flt(row.achieved_qty * 100 / row.target_qty, 2) if row.target_qty else None,
		"invoiced_amount": row.invoiced,
		"received_amount": row.invoiced - row.outstanding,
		"outstanding_amount": row.outstanding,
		"remarks": get_remarks(row),
		"unconverted_qty": row.unconverted_qty,
		"currency": currency,
	}
	if bold:
		line["bold"] = 1
	return line


def get_remarks(row):
	if not row.invoices:
		return ""

	if row.outstanding <= AMOUNT_TOLERANCE:
		return _(RECEIVED)
	if row.outstanding >= row.invoiced - AMOUNT_TOLERANCE:
		return _(NOT_RECEIVED)
	return _(PARTIALLY_RECEIVED)


def get_columns(by_item_group, has_unconverted):
	columns = [{"label": _("Sales Person"), "fieldname": "sales_person", "fieldtype": "Data", "width": 200}]

	if by_item_group:
		columns.append(
			{"label": _("Item Group"), "fieldname": "item_group", "fieldtype": "Data", "width": 180}
		)

	columns += [
		{
			"label": _("Target Qty (Ctn)"),
			"fieldname": "target_qty",
			"fieldtype": "Float",
			"precision": 2,
			"width": 130,
		},
		{
			"label": _("Achieved Qty (Ctn)"),
			"fieldname": "achieved_qty",
			"fieldtype": "Float",
			"precision": 2,
			"width": 140,
		},
		{"label": _("Achievement %"), "fieldname": "achievement", "fieldtype": "Percent", "width": 120},
		{
			"label": _("Invoiced Amount"),
			"fieldname": "invoiced_amount",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 140,
		},
		{
			"label": _("Received Amount"),
			"fieldname": "received_amount",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 140,
		},
		{
			"label": _("Outstanding"),
			"fieldname": "outstanding_amount",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 140,
		},
		{"label": _("Remarks"), "fieldname": "remarks", "fieldtype": "Data", "width": 150},
	]

	if has_unconverted:
		# Items without a Carton UOM: shown in stock UOM instead of being mixed into cartons.
		columns.append(
			{
				"label": _("Qty without Carton UOM"),
				"fieldname": "unconverted_qty",
				"fieldtype": "Float",
				"precision": 2,
				"width": 170,
			}
		)

	return columns
