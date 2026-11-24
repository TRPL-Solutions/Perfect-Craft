# Copyright (c) 2026, TRPL Solutions and contributors
# For license information, please see license.txt

"""Recovery Report: money received from customers, grouped by sales person.

Amount        Cash actually received in the period. Only Payment Entries and Journal Entries
              that credit a customer on a Receivable account count, and only their Bank/Cash
              side: Payment Entry deductions (discounts, charges, tax withheld) are left out,
              refunds paid back to a customer reduce the amount, and credit notes, returns and
              write-offs never appear because they move no Bank/Cash account.
Sales person  From the invoice each payment is allocated to (Payment Ledger Entry), split by
              that invoice's Sales Team allocated_percentage. Unallocated/advance payments, and
              invoices without a Sales Team, use the customer's Sales Team, else "Unassigned".
Region / City Customer Territory / the customer's primary Address (sales_report helpers).
% of Recovery Row amount / grand total x 100 (share of total collections).
"""

from collections import defaultdict

import frappe
from frappe import _
from frappe.contacts.doctype.address.address import get_default_address
from frappe.utils import flt, getdate

from pc_production.pc_production.report.sales_person_target_achievement.sales_person_target_achievement import (
	get_filter_options as get_tree_filter_options,
)
from pc_production.pc_production.report.sales_person_target_achievement.sales_person_target_achievement import (
	get_fiscal_years,
)
from pc_production.pc_production.report.sales_report.sales_report import (
	UNASSIGNED,
	get_descendants,
	get_shares,
	set_customer_geography,
)

RECEIPT_VOUCHER_TYPES = ("Payment Entry", "Journal Entry")
CASH_ACCOUNT_TYPES = ("Bank", "Cash")
AMOUNT_TOLERANCE = 0.005


def execute(filters=None):
	filters = frappe._dict(filters or {})
	validate_filters(filters)

	currency = frappe.get_cached_value("Company", filters.company, "default_currency")
	receipts = get_receipts(filters)
	set_sales_person_shares(receipts, filters)
	return get_columns(), get_data(receipts, filters, currency)


def validate_filters(filters):
	for fieldname, label in (("company", "Company"), ("from_date", "From Date"), ("to_date", "To Date")):
		if not filters.get(fieldname):
			frappe.throw(_("{0} is mandatory").format(_(label)))

	filters.from_date, filters.to_date = getdate(filters.from_date), getdate(filters.to_date)
	if filters.from_date > filters.to_date:
		frappe.throw(_("From Date cannot be after To Date"))


# ============================================================
# RECEIPTS
# ============================================================


def get_receipts(filters):
	"""One row per (voucher, customer) with the cash received from that customer."""
	conditions = [
		"gle.is_cancelled = 0",
		"gle.company = %(company)s",
		"gle.posting_date between %(from_date)s and %(to_date)s",
		"gle.party_type = 'Customer'",
		"gle.voucher_type in %(voucher_types)s",
		"acc.account_type = 'Receivable'",
	]
	values = {
		"company": filters.company,
		"from_date": filters.from_date,
		"to_date": filters.to_date,
		"voucher_types": RECEIPT_VOUCHER_TYPES,
	}

	if filters.debtors_account:
		values["accounts"] = get_descendants("Account", filters.debtors_account)
		conditions.append("gle.account in %(accounts)s")

	if filters.customer:
		values["customer"] = filters.customer
		conditions.append("gle.party = %(customer)s")

	if filters.territory:
		values["territories"] = get_descendants("Territory", filters.territory)
		conditions.append("cust.territory in %(territories)s")

	receipts = frappe.db.sql(
		f"""
		select
			gle.voucher_type, gle.voucher_no, gle.party as customer,
			sum(gle.credit - gle.debit) as party_credit,
			coalesce(nullif(cust.customer_name, ''), gle.party) as customer_name,
			cust.territory, cust.customer_primary_address
		from `tabGL Entry` gle
		inner join `tabAccount` acc on acc.name = gle.account
		left join `tabCustomer` cust on cust.name = gle.party
		where {" and ".join(conditions)}
		group by gle.voucher_type, gle.voucher_no, gle.party
		""",
		values,
		as_dict=True,
	)

	if not receipts:
		return []

	party_totals, cash_totals = get_voucher_totals({r.voucher_no for r in receipts})

	result = []
	for row in receipts:
		key = (row.voucher_type, row.voucher_no)
		row.amount = flt(row.party_credit) * get_cash_factor(
			cash_totals.get(key, 0), party_totals.get(key, 0)
		)
		if abs(row.amount) > AMOUNT_TOLERANCE:
			result.append(row)

	return result


def get_voucher_totals(vouchers):
	"""Per voucher: net credit to all customers, and net debit to Bank/Cash accounts."""
	totals = frappe.db.sql(
		"""
		select
			gle.voucher_type, gle.voucher_no,
			sum(case when gle.party_type = 'Customer' and acc.account_type = 'Receivable'
				then gle.credit - gle.debit else 0 end) as party_credit,
			sum(case when acc.account_type in %(cash_types)s
				then gle.debit - gle.credit else 0 end) as cash
		from `tabGL Entry` gle
		inner join `tabAccount` acc on acc.name = gle.account
		where gle.is_cancelled = 0 and gle.voucher_no in %(vouchers)s
			and gle.voucher_type in %(voucher_types)s
		group by gle.voucher_type, gle.voucher_no
		""",
		{
			"vouchers": list(vouchers),
			"voucher_types": RECEIPT_VOUCHER_TYPES,
			"cash_types": CASH_ACCOUNT_TYPES,
		},
		as_dict=True,
	)

	party_totals = {(d.voucher_type, d.voucher_no): flt(d.party_credit) for d in totals}
	cash_totals = {(d.voucher_type, d.voucher_no): flt(d.cash) for d in totals}
	return party_totals, cash_totals


def get_cash_factor(cash, party_credit):
	"""Share of the customer credit that was really received in cash (0..1).

	Payment Entry with a deduction: customer credited 10,000, bank 9,800 -> 0.98.
	Refund to a customer: both negative -> 1. No Bank/Cash movement -> 0.
	Bank side larger than the customer credit (other parties in the same voucher) -> 1.
	"""
	if not party_credit:
		return 0

	return min(max(cash / party_credit, 0), 1)


# ============================================================
# SALES PERSONS
# ============================================================


def set_sales_person_shares(receipts, filters):
	if not receipts:
		return

	allocations = get_allocations({r.voucher_no for r in receipts})
	invoices = {
		against
		for weights in allocations.values()
		for (against_type, against), _weight in weights.items()
		if against_type == "Sales Invoice"
	}
	invoice_teams = get_teams("Sales Invoice", invoices)
	customer_teams = get_teams("Customer", {r.customer for r in receipts})
	allowed = set(get_descendants("Sales Person", filters.sales_person)) if filters.sales_person else None

	for row in receipts:
		weights = allocations.get((row.voucher_type, row.voucher_no, row.customer)) or {(None, None): 1}
		customer_team = customer_teams.get(row.customer, [])
		shares = defaultdict(float)

		for (against_type, against), weight in weights.items():
			team = []
			if against_type == "Sales Invoice" and against != row.voucher_no:
				team = invoice_teams.get(against, [])
			for sales_person, factor in get_shares(team or customer_team):
				shares[sales_person] += weight * factor

		row.shares = [
			(sp, factor)
			for sp, factor in shares.items()
			if abs(factor) > 1e-9 and (allowed is None or sp in allowed)
		]


def get_allocations(vouchers):
	"""{(voucher_type, voucher_no, customer): {(against_type, against_no): weight}}, weights sum to 1.

	Payment Ledger Entry holds the current allocation, including later reconciliation. An
	unallocated (advance) part points at the payment itself.
	"""
	amounts = defaultdict(lambda: defaultdict(float))
	for d in frappe.get_all(
		"Payment Ledger Entry",
		filters={
			"voucher_no": ["in", list(vouchers)],
			"voucher_type": ["in", RECEIPT_VOUCHER_TYPES],
			"party_type": "Customer",
			"account_type": "Receivable",
			"delinked": 0,
		},
		fields=[
			"voucher_type",
			"voucher_no",
			"party",
			"against_voucher_type",
			"against_voucher_no",
			"amount",
		],
	):
		amounts[(d.voucher_type, d.voucher_no, d.party)][(d.against_voucher_type, d.against_voucher_no)] += (
			flt(d.amount)
		)

	allocations = {}
	for key, against in amounts.items():
		total = sum(against.values())
		if abs(total) > 1e-9:
			allocations[key] = {k: amount / total for k, amount in against.items()}

	return allocations


def get_teams(parenttype, parents):
	teams = defaultdict(list)
	if not parents:
		return teams

	for d in frappe.get_all(
		"Sales Team",
		filters={"parenttype": parenttype, "parent": ["in", list(parents)]},
		fields=["parent", "sales_person", "allocated_percentage"],
		order_by="idx asc",
	):
		teams[d.parent].append((d.sales_person, flt(d.allocated_percentage)))

	return teams


# ============================================================
# OUTPUT
# ============================================================


def get_data(receipts, filters, currency):
	receipts = [r for r in receipts if r.shares]
	if not receipts:
		return []

	set_customer_geography(receipts)

	groups = {}
	for row in receipts:
		for sales_person, factor in row.shares:
			group = groups.setdefault(sales_person, frappe._dict(name=sales_person, customers={}, amount=0))
			customer = group.customers.setdefault(
				row.customer,
				frappe._dict(
					customer=row.customer,
					customer_name=row.customer_name,
					region=row.region,
					city=row.city,
					amount=0,
				),
			)
			amount = row.amount * factor
			customer.amount += amount
			group.amount += amount

	grand_total = sum(g.amount for g in groups.values())

	def percentage(amount):
		return flt(amount * 100 / grand_total, 2) if grand_total else 0

	ordered = sorted((g for name, g in groups.items() if name != UNASSIGNED), key=lambda g: g.name.lower())
	if UNASSIGNED in groups:
		ordered.append(groups[UNASSIGNED])

	data, sno = [], 0
	for group in ordered:
		data.append(
			{"row_type": "sales_person", "sales_person": group.name, "customer_name": group.name, "bold": 1}
		)

		for customer in sorted(group.customers.values(), key=lambda c: (c.customer_name or "").lower()):
			if abs(customer.amount) <= AMOUNT_TOLERANCE:
				continue
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
				"amount": group.amount,
				"percentage": percentage(group.amount),
				"currency": currency,
				"bold": 1,
			}
		)

	data.append(
		{
			"row_type": "grand_total",
			"customer_name": _("Grand Total:"),
			"amount": grand_total,
			"percentage": 100 if grand_total else 0,
			"currency": currency,
			"bold": 1,
			# Read by the print layout for its title lines.
			**get_report_header(filters),
		}
	)
	return data


def get_report_header(filters):
	"""Print title parts: company name, its fiscal year(s), the city of its address and a
	location line "<Area>, <City>" (e.g. "SITE, Karachi"; just the city without an Area)."""
	address = get_default_address("Company", filters.company)
	fields = ["city"] + (["custom_area"] if frappe.get_meta("Address").has_field("custom_area") else [])
	values = frappe.db.get_value("Address", address, fields, as_dict=True) if address else None
	city = ((values or {}).get("city") or "").strip()
	area = ((values or {}).get("custom_area") or "").strip()
	return {
		"company_name": frappe.get_cached_value("Company", filters.company, "company_name")
		or filters.company,
		"company_city": city,
		"company_location": ", ".join(part for part in (area, city) if part),
		"fiscal_year": get_fiscal_year_label(filters),
	}


def get_fiscal_year_label(filters):
	years = get_fiscal_years(frappe._dict(filters, fiscal_year=None))
	return " / ".join(sorted(years, key=lambda name: years[name][0]))


def get_columns():
	return [
		{"label": _("S. #"), "fieldname": "sno", "fieldtype": "Data", "width": 60},
		{"label": _("A/c. Title"), "fieldname": "customer_name", "fieldtype": "Data", "width": 280},
		{"label": _("Region"), "fieldname": "region", "fieldtype": "Data", "width": 160},
		{"label": _("City"), "fieldname": "city", "fieldtype": "Data", "width": 130},
		{
			"label": _("Total Credit Amount"),
			"fieldname": "amount",
			"fieldtype": "Currency",
			"options": "currency",
			"width": 160,
		},
		{"label": _("% of Recovery"), "fieldname": "percentage", "fieldtype": "Percent", "width": 120},
	]


# ============================================================
# FILTER HELPERS
#
# Open to every desk user (no roles, ref_doctype Item Group) like Sales Person Target
# Achievement, so filters on doctypes most users cannot read are Autocomplete fields.
# ============================================================


@frappe.whitelist()
def get_filter_options(doctype, txt="", company=None, **kwargs):
	txt = txt or ""

	if doctype in ("Sales Person", "Territory"):
		return get_tree_filter_options(doctype, txt)

	if doctype == "Customer":
		customers = frappe.get_all(
			"Customer",
			filters={"disabled": 0},
			or_filters={"name": ["like", f"%{txt}%"], "customer_name": ["like", f"%{txt}%"]},
			fields=["name", "customer_name"],
			order_by="customer_name asc",
			limit=50,
		)
		return [
			{
				"value": c.name,
				"label": c.name if c.customer_name in (None, "", c.name) else f"{c.name}: {c.customer_name}",
			}
			for c in customers
		]

	if doctype == "Account":
		# Receivable accounts and the groups above them (the report includes sub-accounts).
		filters = {"disabled": 0}
		if company:
			filters["company"] = company
		accounts = frappe.get_all("Account", filters=filters, fields=["name", "lft", "rgt", "account_type"])
		receivable = [a for a in accounts if a.account_type == "Receivable"]
		txt = txt.lower()
		return [
			a.name
			for a in sorted(accounts, key=lambda a: a.lft)
			if txt in a.name.lower() and any(a.lft <= r.lft and r.rgt <= a.rgt for r in receivable)
		][:50]

	frappe.throw(_("Not allowed"), frappe.PermissionError)
