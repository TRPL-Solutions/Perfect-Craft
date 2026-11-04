# Copyright (c) 2026, TRPL Solutions and contributors
# For license information, please see license.txt

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, getdate

UNASSIGNED = "Unassigned"
NOT_AVAILABLE = "N/A"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	validate_filters(filters)

	currency = frappe.get_cached_value("Company", filters.company, "default_currency")
	items = get_invoice_items(filters)

	if filters.report_type == "Detail":
		return get_detail_columns(currency), get_detail_data(items, filters, currency)

	return get_summary_columns(currency), get_summary_data(items, filters, currency)


def validate_filters(filters):
	for fieldname, label in (("company", "Company"), ("from_date", "Date From"), ("to_date", "Date To")):
		if not filters.get(fieldname):
			frappe.throw(_("{0} is mandatory").format(_(label)))

	if getdate(filters.from_date) > getdate(filters.to_date):
		frappe.throw(_("Date From cannot be after Date To"))

	filters.report_type = filters.report_type or "Summary"
	filters.sort_by = filters.sort_by or "Name"
	filters.sort_order = filters.sort_order or "Ascending"
	filters.sales_basis = filters.sales_basis or "Net Sales"
	# The desk drops falsy filter values, so the UI sends "Yes"/"No"; 0 is accepted for API callers.
	filters.include_returns = 0 if filters.get("include_returns") in ("No", 0, "0", False) else 1


# ============================================================
# DATA COLLECTION
# ============================================================


def get_invoice_items(filters):
	"""One row per submitted invoice item, carrying its salesperson shares.

	`shares` is a list of (sales_person, factor) where the factors of an
	unfiltered row always add up to 1, so summary and detail reconcile.
	"""
	conditions = ["si.docstatus = 1", "si.company = %(company)s", "si.posting_date between %(from_date)s and %(to_date)s"]
	values = {"company": filters.company, "from_date": filters.from_date, "to_date": filters.to_date}

	if not filters.include_returns:
		conditions.append("si.is_return = 0")

	if filters.control_account:
		values["accounts"] = get_descendants("Account", filters.control_account)
		conditions.append("si.debit_to in %(accounts)s")

	if filters.customer:
		values["customer"] = filters.customer
		conditions.append("si.customer = %(customer)s")

	if filters.territory:
		values["territories"] = get_descendants("Territory", filters.territory)
		conditions.append("cust.territory in %(territories)s")

	if filters.sales_basis == "Gross Sales":
		amount_field, rate_field = "sii.base_amount", "sii.base_rate"
	else:
		amount_field, rate_field = "sii.base_net_amount", "sii.base_net_rate"

	items = frappe.db.sql(
		f"""
		select
			si.name as invoice, si.posting_date, si.posting_time, si.customer,
			coalesce(nullif(cust.customer_name, ''), si.customer_name, si.customer) as customer_name,
			cust.territory, cust.customer_primary_address,
			sii.idx, sii.item_code, sii.item_name, sii.qty,
			{rate_field} as rate, {amount_field} as amount
		from `tabSales Invoice` si
		inner join `tabSales Invoice Item` sii on sii.parent = si.name and sii.parenttype = 'Sales Invoice'
		left join `tabCustomer` cust on cust.name = si.customer
		where {" and ".join(conditions)}
		order by si.posting_date, si.posting_time, si.name, sii.idx
		""",
		values,
		as_dict=True,
	)

	if not items:
		return []

	set_customer_geography(items)
	items = [row for row in items if matches_geography(row, filters)]
	set_sales_person_shares(items, filters)

	return [row for row in items if row.shares]


def get_descendants(doctype, name):
	lft, rgt = frappe.db.get_value(doctype, name, ["lft", "rgt"]) or (None, None)
	if lft is None:
		return [name]

	return frappe.get_all(doctype, filters={"lft": [">=", lft], "rgt": ["<=", rgt]}, pluck="name")


def set_customer_geography(items):
	customers = {row.customer for row in items}
	address_map = get_customer_address_map(customers, items)
	has_area = frappe.get_meta("Address").has_field("custom_area")

	fields = ["name", "city"] + (["custom_area"] if has_area else [])
	addresses = {
		d.name: d
		for d in frappe.get_all(
			"Address", filters={"name": ["in", list(set(address_map.values()))]}, fields=fields
		)
	} if address_map else {}

	for row in items:
		address = addresses.get(address_map.get(row.customer)) or {}
		row.region = row.territory or NOT_AVAILABLE
		row.city = (address.get("city") or "").strip() or NOT_AVAILABLE
		row.area = (address.get("custom_area") or "").strip() or NOT_AVAILABLE


def get_customer_address_map(customers, items):
	"""Customer primary address, falling back to a linked primary/any address."""
	address_map = {row.customer: row.customer_primary_address for row in items if row.customer_primary_address}

	missing = [c for c in customers if c not in address_map]
	if missing:
		linked = frappe.db.sql(
			"""
			select dl.link_name, addr.name
			from `tabDynamic Link` dl
			inner join `tabAddress` addr on addr.name = dl.parent
			where dl.parenttype = 'Address' and dl.link_doctype = 'Customer'
				and dl.link_name in %(customers)s and addr.disabled = 0
			order by addr.is_primary_address desc, addr.creation
			""",
			{"customers": missing},
		)
		for customer, address in linked:
			address_map.setdefault(customer, address)

	return address_map


def matches_geography(row, filters):
	if filters.city and row.city.lower() != filters.city.strip().lower():
		return False

	if filters.area and row.area.lower() != filters.area.strip().lower():
		return False

	return True


def set_sales_person_shares(items, filters):
	invoices = list({row.invoice for row in items})
	team_map = defaultdict(list)

	for d in frappe.get_all(
		"Sales Team",
		filters={"parenttype": "Sales Invoice", "parent": ["in", invoices]},
		fields=["parent", "sales_person", "allocated_percentage"],
		order_by="idx asc",
	):
		team_map[d.parent].append((d.sales_person, flt(d.allocated_percentage)))

	allowed = set(get_descendants("Sales Person", filters.sales_person)) if filters.sales_person else None
	share_cache = {}

	for row in items:
		if row.invoice not in share_cache:
			shares = get_shares(team_map.get(row.invoice, []))
			if allowed is not None:
				shares = [(sp, factor) for sp, factor in shares if sp in allowed]
			share_cache[row.invoice] = shares

		row.shares = share_cache[row.invoice]


def get_shares(team):
	team = [(sp, pct) for sp, pct in team if pct > 0]
	total = sum(pct for _sp, pct in team)

	if total > 100:
		# Corrupt allocations: scale down so the invoice is never counted twice.
		team = [(sp, pct * 100 / total) for sp, pct in team]
		total = 100

	shares = [(sp, pct / 100) for sp, pct in team]
	if 100 - total > 0.0001:
		shares.append((UNASSIGNED, (100 - total) / 100))

	return shares


# ============================================================
# DETAIL REPORT
# ============================================================


def get_detail_columns(currency):
	return [
		{"label": _("Inv. Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
		{"label": _("Inv. No."), "fieldname": "invoice", "fieldtype": "Link", "options": "Sales Invoice", "width": 160},
		{"label": _("Customer Name"), "fieldname": "customer_name", "fieldtype": "Data", "width": 240},
		{"label": _("Sales Man"), "fieldname": "sales_person", "fieldtype": "Data", "width": 140},
		{"label": _("Region"), "fieldname": "region", "fieldtype": "Data", "width": 130},
		{"label": _("City Name"), "fieldname": "city", "fieldtype": "Data", "width": 120},
		{"label": _("Item Description"), "fieldname": "item_name", "fieldtype": "Data", "width": 250},
		{"label": _("Qty"), "fieldname": "qty", "fieldtype": "Float", "precision": 2, "width": 90},
		{"label": _("Price"), "fieldname": "rate", "fieldtype": "Currency", "options": "currency", "width": 110},
		{"label": _("Amount"), "fieldname": "amount", "fieldtype": "Currency", "options": "currency", "width": 130},
	]


def get_detail_data(items, filters, currency):
	invoices = {}
	for row in items:
		factor = sum(f for _sp, f in row.shares)
		row.qty = flt(row.qty) * factor
		row.amount = flt(row.amount) * factor

		invoice = invoices.setdefault(row.invoice, frappe._dict(rows=[], qty=0, amount=0, first=row))
		invoice.rows.append(row)
		invoice.qty += row.qty
		invoice.amount += row.amount

	ordered = sort_records(
		list(invoices.values()),
		filters,
		name_key=lambda inv: (inv.first.customer_name or "").lower(),
		amount_key=lambda inv: inv.amount,
		date_key=lambda inv: (inv.first.posting_date, str(inv.first.posting_time), inv.first.invoice),
	)

	data, total_qty, total_amount = [], 0, 0
	for invoice in ordered:
		first = invoice.first
		for i, row in enumerate(invoice.rows):
			line = {
				"row_type": "item",
				"invoice_ref": row.invoice,
				"item_code": row.item_code,
				"item_name": row.item_name,
				"qty": row.qty,
				"rate": row.rate,
				"amount": row.amount,
				"currency": currency,
			}
			if i == 0:
				line.update(
					{
						"posting_date": first.posting_date,
						"invoice": first.invoice,
						"customer": first.customer,
						"customer_name": first.customer_name,
						"sales_person": format_sales_persons(first.shares),
						"region": first.region,
						"city": first.city,
						"area": first.area,
					}
				)
			data.append(line)

		data.append(
			{
				"row_type": "invoice_total",
				"invoice_ref": invoice.first.invoice,
				"item_name": _("Invoice Total:"),
				"qty": invoice.qty,
				"amount": invoice.amount,
				"currency": currency,
				"bold": 1,
			}
		)
		total_qty += invoice.qty
		total_amount += invoice.amount

	if data:
		data.append(
			{
				"row_type": "grand_total",
				"item_name": _("Grand Total:"),
				"qty": total_qty,
				"amount": total_amount,
				"currency": currency,
				"bold": 1,
			}
		)

	return data


def format_sales_persons(shares):
	if len(shares) == 1:
		return shares[0][0]

	return ", ".join(f"{sp} ({flt(factor * 100, 2):g}%)" for sp, factor in shares)


# ============================================================
# SUMMARY REPORT
# ============================================================


def get_summary_columns(currency):
	return [
		{"label": _("S. #"), "fieldname": "sno", "fieldtype": "Data", "width": 60},
		{"label": _("A/c. Title"), "fieldname": "customer_name", "fieldtype": "Data", "width": 280},
		{"label": _("Region"), "fieldname": "region", "fieldtype": "Data", "width": 140},
		{"label": _("City"), "fieldname": "city", "fieldtype": "Data", "width": 130},
		{"label": _("Area"), "fieldname": "area", "fieldtype": "Data", "width": 130},
		{"label": _("Total Quantity"), "fieldname": "qty", "fieldtype": "Float", "precision": 2, "width": 120},
		{
			"label": _("Total Sales Amount"),
			"fieldname": "amount",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 150,
		},
		{"label": _("%age of Sales"), "fieldname": "percentage", "fieldtype": "Percent", "width": 110},
	]


def get_summary_data(items, filters, currency):
	groups = {}
	for row in items:
		for sales_person, factor in row.shares:
			group = groups.setdefault(sales_person, frappe._dict(name=sales_person, customers={}, qty=0, amount=0))
			customer = group.customers.setdefault(
				row.customer,
				frappe._dict(
					customer=row.customer,
					customer_name=row.customer_name,
					region=row.region,
					city=row.city,
					area=row.area,
					first_date=row.posting_date,
					qty=0,
					amount=0,
				),
			)
			qty, amount = flt(row.qty) * factor, flt(row.amount) * factor
			customer.qty += qty
			customer.amount += amount
			group.qty += qty
			group.amount += amount

	grand_qty = sum(g.qty for g in groups.values())
	grand_amount = sum(g.amount for g in groups.values())

	def percentage(amount):
		return flt(amount * 100 / grand_amount, 2) if grand_amount else 0

	assigned = [g for name, g in groups.items() if name != UNASSIGNED]
	ordered_groups = sort_records(
		assigned,
		filters,
		name_key=lambda g: g.name.lower(),
		amount_key=lambda g: g.amount,
		date_key=lambda g: g.name.lower(),
	)
	if UNASSIGNED in groups:
		ordered_groups.append(groups[UNASSIGNED])

	data, sno = [], 0
	for group in ordered_groups:
		data.append({"row_type": "sales_person", "sales_person": group.name, "customer_name": group.name, "bold": 1})

		customers = sort_records(
			list(group.customers.values()),
			filters,
			name_key=lambda c: (c.customer_name or "").lower(),
			amount_key=lambda c: c.amount,
			date_key=lambda c: (c.first_date, (c.customer_name or "").lower()),
		)
		for customer in customers:
			sno += 1
			data.append(
				{
					"row_type": "customer",
					"sno": str(sno),
					"sales_person": group.name,
					"customer": customer.customer,
					"customer_name": customer.customer_name,
					"region": customer.region,
					"city": customer.city,
					"area": customer.area,
					"qty": customer.qty,
					"amount": customer.amount,
					"percentage": percentage(customer.amount),
					"currency": currency,
				}
			)

		data.append(
			{
				"row_type": "sales_person_total",
				"sales_person": group.name,
				"customer_name": _("{0} Total:").format(group.name),
				"qty": group.qty,
				"amount": group.amount,
				"percentage": percentage(group.amount),
				"currency": currency,
				"bold": 1,
			}
		)

	if data:
		data.append(
			{
				"row_type": "grand_total",
				"customer_name": _("Grand Total:"),
				"qty": grand_qty,
				"amount": grand_amount,
				"percentage": 100 if grand_amount else 0,
				"currency": currency,
				"bold": 1,
			}
		)

	return data


def sort_records(records, filters, name_key, amount_key, date_key):
	key = {"Amount": amount_key, "Date": date_key}.get(filters.sort_by, name_key)

	# Pre-sort by name so ties keep name order in either direction (sorted is stable).
	records = sorted(records, key=name_key)
	return sorted(records, key=key, reverse=filters.sort_order == "Descending")
