# Copyright (c) 2026, TRPL Solutions and contributors
# For license information, please see license.txt

"""Customer Wise Discount Report: the client's "2- DISCOUNT REPORT" sheet.

One row per customer, from submitted Sales Invoices in the date range (credit notes negative),
amounts in company currency before tax. Lines, cartons, geography and the Sales Officer split
come from report_utils.get_invoice_lines; with a Sales Officer filter every amount is that
officer's share, as in the other carton reports.

TOTAL NET SALE AMOUNT  Sale before discount: price before discount x qty, the price being the
                       line's price list rate (or rate with margin when it has a margin).
PROMOTION AMOUNT       Discount from Customer Referral pricing rules only: price before discount
                       x qty - billed amount, on lines whose pricing rule belongs to a Customer
                       Referral. A credit note made from an invoice loses its pricing rules, so
                       it uses the rules of the original invoice line (and reverses that
                       discount). Rate-type referral rules overwrite the price list rate, so
                       their discount is not on the invoice: such lines are listed in a note,
                       never guessed.
OTHER DISCOUNT         Every other discount (manual price cuts, the invoice's Additional
                       Discount): TOTAL NET SALE AMOUNT - PROMOTION AMOUNT - AFTER DISCOUNT.
                       Column shown only when it is not zero.
AFTER DISCOUNT         What was billed, before tax (base_net_amount).
DISCOUNT PER CTN       PROMOTION AMOUNT / cartons of the lines that got the promotion
                       (a weighted average when items have different rates).
CREDIT DAYS            Longest credit days of the customer's payment terms template (the
                       customer's, else its customer group's).
CREDIT LIMIT           ERPNext's credit limit for the customer and company (blank = none).
AC/CODE                Customer "A/C Code" (custom_ac_code), else the customer ID.
"""

import json

import frappe
from erpnext.accounts.party import get_payment_terms_template
from erpnext.selling.doctype.customer.customer import get_credit_limit
from frappe import _
from frappe.utils import cint, flt, getdate

from pc_production.pc_production.report.recovery_report.recovery_report import get_teams
from pc_production.pc_production.report.sales_report.sales_report import (
	UNASSIGNED,
	get_shares,
	set_customer_geography,
)
from pc_production.pc_production.report_utils import (
	EN_DASH,
	QTY_TOLERANCE,
	descendants_of,
	get_invoice_lines,
	get_list,
	matches_geography,
)
from pc_production.pc_production.report_utils import (
	set_customer_details as set_code_and_officers,
)

MULTI_FILTERS = ("sales_person", "territory", "city", "area")
AMOUNT_TOLERANCE = 0.005
REFERRAL_FIELD = "custom_customer_referral"
NOTE_LIMIT = 15


def execute(filters=None):
	filters = frappe._dict(filters or {})
	validate_filters(filters)

	lines = get_invoice_lines(filters)
	referral_rules = get_referral_rules()
	set_original_rules(lines)

	rows, notes = get_customer_rows(lines, referral_rules)
	if cint(filters.include_customers_without_sales):
		add_customers_without_sales(rows, filters)

	set_customer_details(rows, filters)
	data = get_data(rows, notes, filters.company)
	show_other = any(abs(flt(row.get("other_discount"))) > AMOUNT_TOLERANCE for row in data)
	return get_columns(show_other), data, get_message(notes)


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


# ============================================================
# PRICING RULES
# ============================================================


def get_referral_rules():
	"""{pricing rule name: rate_or_discount} of the rules created by Customer Referrals."""
	return {
		d.name: d.rate_or_discount
		for d in frappe.get_all(
			"Pricing Rule",
			filters={REFERRAL_FIELD: ["is", "set"]},
			fields=["name", "rate_or_discount"],
		)
	}


def set_original_rules(lines):
	"""Credit notes made from an invoice: pricing rules of the original invoice line."""
	originals = {line.sales_invoice_item for line in lines if line.is_return and line.sales_invoice_item}
	rules = {}
	if originals:
		rules = dict(
			frappe.get_all(
				"Sales Invoice Item",
				filters={"name": ["in", list(originals)]},
				fields=["name", "pricing_rules"],
				as_list=True,
			)
		)

	for line in lines:
		source = line.pricing_rules
		if not source and line.is_return and line.sales_invoice_item:
			source = rules.get(line.sales_invoice_item)
		line.rules = parse_rules(source)


def parse_rules(value):
	if not value:
		return []
	try:
		rules = json.loads(value)
	except ValueError:
		rules = value.split(",")
	return [rule.strip() for rule in (rules if isinstance(rules, list) else [rules]) if rule and rule.strip()]


# ============================================================
# ROWS
# ============================================================


def get_customer_rows(lines, referral_rules):
	rows = {}
	notes = frappe._dict(rate_rules=[], negative_rates=[], no_carton=[])

	for line in lines:
		row = rows.get(line.customer)
		if not row:
			row = rows[line.customer] = new_row(line)
		row.officers.update(line.officers)

		factor = flt(line.factor)
		price = get_price_before_discount(line)
		before = price * flt(line.qty)
		discount = before - flt(line.base_amount)
		referral_types = {referral_rules[rule] for rule in line.rules if rule in referral_rules}

		row.cartons += line.cartons * factor
		row.before += before * factor
		row.after += flt(line.base_net_amount) * factor

		if "Rate" in referral_types:
			notes.rate_rules.append(line)
		elif referral_types and abs(discount) > AMOUNT_TOLERANCE:
			row.promotion += discount * factor
			row.promoted_cartons += line.cartons * factor
			if not line.cartons:
				notes.no_carton.append(line)

		if flt(line.base_rate) < 0:
			notes.negative_rates.append(line)

	return rows, notes


def get_price_before_discount(line):
	if line.margin_type and flt(line.base_rate_with_margin):
		return flt(line.base_rate_with_margin)
	# No price list rate (item without a price): nothing to compare against, no discount.
	return flt(line.base_price_list_rate) or flt(line.base_rate)


def new_row(line):
	return frappe._dict(
		customer=line.customer,
		customer_name=line.customer_name,
		region=line.region,
		city=line.city,
		officers=set(),
		cartons=0,
		promoted_cartons=0,
		promotion=0,
		before=0,
		after=0,
	)


def add_customers_without_sales(rows, filters):
	"""Enabled customers matching the filters that have no row yet (zero sales)."""
	customer_filters = {"disabled": 0, "name": ["not in", list(rows) or [""]]}
	if filters.customer:
		customer_filters["name"] = ["in", [c for c in filters.customer if c not in rows] or [""]]
	if filters.territory:
		customer_filters["territory"] = ["in", descendants_of("Territory", filters.territory)]

	customers = frappe.get_all(
		"Customer",
		filters=customer_filters,
		fields=["name as customer", "customer_name", "territory", "customer_primary_address"],
	)
	if not customers:
		return

	set_customer_geography(customers)
	customers = [c for c in customers if matches_geography(c, filters)]
	teams = get_teams("Customer", {c.customer for c in customers})
	allowed = set(descendants_of("Sales Person", filters.sales_person)) if filters.sales_person else None

	for customer in customers:
		officers = {sp for sp, _factor in get_shares(teams.get(customer.customer, [])) if sp != UNASSIGNED}
		if allowed is not None and not officers & allowed:
			continue
		row = rows[customer.customer] = new_row(customer)
		row.customer_name = customer.customer_name or customer.customer
		row.officers = officers if allowed is None else officers & allowed


def set_customer_details(rows, filters):
	# A/C code; officers, else the customer's own Sales Team (report_utils).
	set_code_and_officers(list(rows.values()))
	for customer, row in rows.items():
		row.credit_days = get_credit_days(customer, filters.company)
		# 0 = no credit limit in ERPNext: shown blank.
		row.credit_limit = flt(get_credit_limit(customer, filters.company)) or None


def get_credit_days(customer, company):
	template = get_payment_terms_template(customer, "Customer", company)
	if not template:
		return None
	days = frappe.get_all(
		"Payment Terms Template Detail",
		filters={"parent": template, "parenttype": "Payment Terms Template"},
		pluck="credit_days",
	)
	return max((cint(d) for d in days), default=0)


# ============================================================
# OUTPUT
# ============================================================


def get_data(rows, notes, company):
	data = []
	total = frappe._dict(cartons=0, promotion=0, before=0, other=0, after=0)

	ordered = sorted(
		rows.values(),
		key=lambda r: (not r.sales_person, r.sales_person.lower(), (r.customer_name or "").lower()),
	)
	for row in ordered:
		other = row.before - row.promotion - row.after
		data.append(
			{
				"row_type": "customer",
				"customer": row.customer,
				"ac_code": row.ac_code,
				"customer_name": row.customer_name,
				"sales_person": row.sales_person,
				"region": row.region,
				"city": row.city,
				"cartons": row.cartons,
				"credit_days": row.credit_days,
				"credit_limit": row.credit_limit,
				"discount_per_ctn": row.promotion / row.promoted_cartons
				if abs(row.promoted_cartons) > QTY_TOLERANCE
				else None,
				"promotion": row.promotion,
				"sale_before_discount": row.before,
				"other_discount": other,
				"after_discount": row.after,
			}
		)
		total.cartons += row.cartons
		total.promotion += row.promotion
		total.before += row.before
		total.other += other
		total.after += row.after

	if not data:
		return []

	currency = frappe.get_cached_value("Company", company, "default_currency")
	data.append(
		{
			"row_type": "total",
			"customer_name": _("Grand Total"),
			"cartons": total.cartons,
			"promotion": total.promotion,
			"sale_before_discount": total.before,
			"other_discount": total.other,
			"after_discount": total.after,
			"bold": 1,
			# Read by the print template: notes under the table.
			"notes": get_note_lines(notes),
		}
	)
	for row in data:
		row["currency"] = currency
	return data


def get_note_lines(notes):
	def describe(line, extra=""):
		return f"{line.customer_name} {EN_DASH} {line.item_code} {EN_DASH} {line.invoice}{extra}"

	lines = []
	if notes.rate_rules:
		lines.append(
			_("Rate-type referral price, discount not on the invoice (not counted in Promotion): {0}").format(
				"; ".join(describe(line) for line in notes.rate_rules[:NOTE_LIMIT])
				+ (" …" if len(notes.rate_rules) > NOTE_LIMIT else "")
			)
		)
	if notes.negative_rates:
		lines.append(
			_("Negative rate: {0}").format(
				"; ".join(
					describe(line, f" ({flt(line.base_rate):,.2f})")
					for line in notes.negative_rates[:NOTE_LIMIT]
				)
				+ (" …" if len(notes.negative_rates) > NOTE_LIMIT else "")
			)
		)
	if notes.no_carton:
		lines.append(
			_("Promotion on items without a Carton UOM (in Promotion, not in Discount per CTN): {0}").format(
				"; ".join(describe(line) for line in notes.no_carton[:NOTE_LIMIT])
			)
		)
	return lines


def get_message(notes):
	note_lines = get_note_lines(notes)
	if not note_lines:
		return None
	items = "".join(f"<li>{frappe.utils.escape_html(text)}</li>" for text in note_lines)
	return f"<div class='text-muted small'><b>{_('Check')}:</b><ul class='mb-0'>{items}</ul></div>"


def get_columns(show_other):
	currency = {"fieldtype": "Currency", "options": "currency", "width": 140}
	columns = [
		{"label": _("AC/CODE"), "fieldname": "ac_code", "fieldtype": "Data", "width": 110},
		{"label": _("A/C TITLE"), "fieldname": "customer_name", "fieldtype": "Data", "width": 220},
		{"label": _("SALE PERSON"), "fieldname": "sales_person", "fieldtype": "Data", "width": 150},
		{"label": _("REGION"), "fieldname": "region", "fieldtype": "Data", "width": 130},
		{"label": _("CITY NAME"), "fieldname": "city", "fieldtype": "Data", "width": 110},
		{"label": _("CTN QTY"), "fieldname": "cartons", "fieldtype": "Float", "precision": 2, "width": 100},
		{"label": _("CREDIT DAYS"), "fieldname": "credit_days", "fieldtype": "Int", "width": 100},
		{"label": _("CREDIT LIMIT"), "fieldname": "credit_limit", **currency},
		{
			"label": _("DISCOUNT PER CTN"),
			"fieldname": "discount_per_ctn",
			**currency,
			"description": _("Promotion Amount / cartons that got the promotion"),
		},
		{"label": _("PROMOTION AMOUNT"), "fieldname": "promotion", **currency},
		{
			"label": _("TOTAL NET SALE AMOUNT"),
			"fieldname": "sale_before_discount",
			**currency,
			"width": 170,
			"description": _("Sale before discount (price list rate x qty), before tax"),
		},
	]
	if show_other:
		columns.append(
			{
				"label": _("OTHER DISCOUNT"),
				"fieldname": "other_discount",
				**currency,
				"description": _("Manual price cuts and invoice discounts (not from Customer Referral)"),
			}
		)
	columns.append(
		{
			"label": _("AFTER DISCOUNT"),
			"fieldname": "after_discount",
			**currency,
			"description": _("Billed amount, before tax"),
		}
	)
	return columns
