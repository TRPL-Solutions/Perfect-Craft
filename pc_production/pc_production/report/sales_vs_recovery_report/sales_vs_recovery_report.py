# Copyright (c) 2026, TRPL Solutions and contributors
# For license information, please see license.txt

"""Sales Vs Recovery Report: per sales person and customer, money received next to sales.

Recovery      Exactly as Recovery Report (its get_receipts / set_sales_person_shares).
Sales         Submitted Sales Invoices in the period, credit notes included (they reduce
              sales). Each invoice's base_grand_total (with taxes) is spread over its lines by
              net amount and split by the invoice's Sales Team (Sales Report's get_invoice_items).
Rows          One per sales person + customer; shown when either amount is not zero.
Region / City / Area
              Customer Territory / the customer's primary Address city / its Area (custom_area).
% columns     Row amount / grand total x 100, separately for recovery and sales.
"""

import frappe
from frappe import _
from frappe.utils import flt

from pc_production.pc_production.report.recovery_report.recovery_report import (
	AMOUNT_TOLERANCE,
	get_receipts,
	get_report_header,
	set_sales_person_shares,
	validate_filters,
)
from pc_production.pc_production.report.sales_report.sales_report import (
	GRAND_TOTAL_BASIS,
	UNASSIGNED,
	get_invoice_items,
	set_customer_geography,
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	validate_filters(filters)

	currency = frappe.get_cached_value("Company", filters.company, "default_currency")
	return get_columns(), get_data(get_recovery(filters), get_sales(filters), filters, currency)


def get_recovery(filters):
	receipts = get_receipts(filters)
	set_sales_person_shares(receipts, filters)
	receipts = [r for r in receipts if r.shares]
	if receipts:
		set_customer_geography(receipts)
	return receipts


def get_sales(filters):
	"""Invoice lines with geography and Sales Team shares already set by Sales Report."""
	return get_invoice_items(
		frappe._dict(
			company=filters.company,
			from_date=filters.from_date,
			to_date=filters.to_date,
			customer=filters.customer,
			territory=filters.territory,
			sales_person=filters.sales_person,
			control_account=filters.debtors_account,
			include_returns=1,
			sales_basis=GRAND_TOTAL_BASIS,
		)
	)


def get_data(receipts, invoice_lines, filters, currency):
	groups = {}

	def add(row, field):
		for sales_person, factor in row.shares:
			group = groups.setdefault(
				sales_person, frappe._dict(name=sales_person, customers={}, recovery=0, sales=0)
			)
			customer = group.customers.setdefault(
				row.customer,
				frappe._dict(
					customer=row.customer,
					customer_name=row.customer_name,
					region=row.region,
					city=row.city,
					area=row.area,
					recovery=0,
					sales=0,
				),
			)
			amount = flt(row.amount) * factor
			customer[field] += amount
			group[field] += amount

	for row in receipts:
		add(row, "recovery")
	for row in invoice_lines:
		add(row, "sales")

	grand = frappe._dict(
		recovery=sum(g.recovery for g in groups.values()), sales=sum(g.sales for g in groups.values())
	)

	def percentage(amount, field):
		return flt(amount * 100 / grand[field], 2) if grand[field] else 0

	def amounts(record):
		return {
			"recovery_amount": record.recovery,
			"recovery_percentage": percentage(record.recovery, "recovery"),
			"sales_amount": record.sales,
			"sales_percentage": percentage(record.sales, "sales"),
			"currency": currency,
		}

	ordered = sorted((g for name, g in groups.items() if name != UNASSIGNED), key=lambda g: g.name.lower())
	if UNASSIGNED in groups:
		ordered.append(groups[UNASSIGNED])

	data, sno = [], 0
	for group in ordered:
		customers = [
			c
			for c in sorted(group.customers.values(), key=lambda c: (c.customer_name or "").lower())
			if abs(c.recovery) > AMOUNT_TOLERANCE or abs(c.sales) > AMOUNT_TOLERANCE
		]
		if not customers:
			continue

		data.append(
			{"row_type": "sales_person", "sales_person": group.name, "customer_name": group.name, "bold": 1}
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
					**amounts(customer),
				}
			)
		data.append(
			{
				"row_type": "sales_person_total",
				"sales_person": group.name,
				"customer_name": _("{0} Total:").format(group.name),
				"bold": 1,
				**amounts(group),
			}
		)

	if not data:
		return []

	data.append(
		{
			"row_type": "grand_total",
			"customer_name": _("Grand Total:"),
			"bold": 1,
			**amounts(grand),
			"recovery_percentage": 100 if grand.recovery else 0,
			"sales_percentage": 100 if grand.sales else 0,
			# Read by the print layout for its title lines.
			**get_report_header(filters),
		}
	)
	return data


def get_columns():
	def currency(label, fieldname):
		return {
			"label": label,
			"fieldname": fieldname,
			"fieldtype": "Currency",
			"options": "currency",
			"width": 150,
		}

	return [
		{"label": _("S. #"), "fieldname": "sno", "fieldtype": "Data", "width": 60},
		{"label": _("A/c. Title"), "fieldname": "customer_name", "fieldtype": "Data", "width": 250},
		{"label": _("Region"), "fieldname": "region", "fieldtype": "Data", "width": 140},
		{"label": _("City"), "fieldname": "city", "fieldtype": "Data", "width": 110},
		{"label": _("Area"), "fieldname": "area", "fieldtype": "Data", "width": 120},
		currency(_("Total Rcvd Amount"), "recovery_amount"),
		{
			"label": _("% of Recovery"),
			"fieldname": "recovery_percentage",
			"fieldtype": "Percent",
			"width": 110,
		},
		currency(_("Total Sales Amount"), "sales_amount"),
		{"label": _("% of Sales"), "fieldname": "sales_percentage", "fieldtype": "Percent", "width": 100},
	]
