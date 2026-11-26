# Copyright (c) 2026, TRPL Solutions and contributors
# For license information, please see license.txt

"""Print Customer List: the client's "SALESMAN CUSTOMER LIST" (sheet "4-SO CUSTOMER WISE").

One row per enabled Customer matching the filters, sorted by Sale Person, then A/C Code.

AC/CODE      Customer "A/C Code" (custom_ac_code), else the customer ID.
SALE PERSON  The customer's Sales Team (with a Sale Person filter: only the matching ones).
REGION       Territory.  CITY / AREA: the customer's primary Address (city / custom_area).
DISCOUNT     Per-carton discount on the customer's Customer Referral active today (submitted,
             same company, valid_from/valid_upto around today): its "Discount Amount" item
             rows converted to one Carton (a Nos row x Nos per Carton). Different amounts per
             item show as a range (100-150). Discount Percentage / Rate rows are ignored
             (discounts are per carton). Items without a Carton UOM: listed in a note.
BALANCE      Receivable balance up to today: debit - credit of the customer's GL entries in
             the company. A credit balance (we owe the customer) shows with "CR": 56,000 CR.
"""

import re

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import flt, fmt_money, getdate, today

from pc_production.pc_production.report.recovery_report.recovery_report import get_teams
from pc_production.pc_production.report.sales_person_target_achievement.sales_person_target_achievement import (
	get_carton_factors,
)
from pc_production.pc_production.report.sales_report.sales_report import set_customer_geography
from pc_production.pc_production.report_utils import (
	EN_DASH,
	descendants_of,
	get_list,
	matches_geography,
)

MULTI_FILTERS = ("city", "sales_person", "territory", "area")
AMOUNT_TOLERANCE = 0.005


def execute(filters=None):
	filters = frappe._dict(filters or {})
	validate_filters(filters)

	rows = get_customers(filters)
	if not rows:
		return get_columns(), [], _("No customers found for the selected filters.")

	notes = set_discounts(rows, filters.company)
	set_balances(rows, filters.company)
	data = sorted(rows, key=lambda r: (not r.sales_person, r.sales_person.lower(), natural_key(r.ac_code)))
	if notes:
		# Read by the print template: notes under the table.
		data[0]["notes"] = notes
	return get_columns(), data, "; ".join(notes) or None


def validate_filters(filters):
	if not filters.get("company"):
		frappe.throw(_("{0} is mandatory").format(_("Company")))
	for fieldname in MULTI_FILTERS:
		filters[fieldname] = get_list(filters.get(fieldname))


def natural_key(value):
	"""'12-999' before '12-1000': digit runs compare as numbers."""
	return [(0, int(part), "") if part.isdigit() else (1, 0, part.lower()) for part in re.split(r"(\d+)", value or "")]


# ============================================================
# CUSTOMERS
# ============================================================


def get_customers(filters):
	customer_filters = {"disabled": 0}
	if filters.territory:
		customer_filters["territory"] = ["in", descendants_of("Territory", filters.territory)]

	customers = frappe.get_all(
		"Customer",
		filters=customer_filters,
		fields=["name as customer", "customer_name", "territory", "customer_primary_address", "custom_ac_code"],
	)
	if not customers:
		return []

	set_customer_geography(customers)
	customers = [c for c in customers if matches_geography(c, filters)]

	teams = get_teams("Customer", {c.customer for c in customers})
	allowed = set(descendants_of("Sales Person", filters.sales_person)) if filters.sales_person else None

	rows = []
	for c in customers:
		officers = list(dict.fromkeys(sp for sp, _pct in teams.get(c.customer, [])))
		if allowed is not None:
			officers = [sp for sp in officers if sp in allowed]
			if not officers:
				continue
		rows.append(
			frappe._dict(
				customer=c.customer,
				ac_code=(c.custom_ac_code or "").strip() or c.customer,
				customer_name=c.customer_name or c.customer,
				sales_person=", ".join(sorted(officers, key=str.lower)),
				region=c.region,
				city=c.city,
				area=c.area,
			)
		)
	return rows


# ============================================================
# DISCOUNT (Customer Referral)
# ============================================================


def set_discounts(rows, company):
	"""row.discount: per-carton Discount Amount of the active referral (or a range). Returns notes."""
	by_customer = {row.customer: row for row in rows}
	on = getdate(today())
	referral = frappe.qb.DocType("Customer Referral")
	item = frappe.qb.DocType("Customer Referral Item")
	lines = (
		frappe.qb.from_(referral)
		.inner_join(item)
		.on((item.parent == referral.name) & (item.parenttype == "Customer Referral"))
		.select(
			referral.customer,
			item.item_code,
			item.uom,
			item.rate_or_discount,
			item.discount_amount,
		)
		.where(
			(referral.docstatus == 1)
			& (referral.company == company)
			& (referral.customer.isin(list(by_customer)))
			& (referral.valid_from.isnull() | (referral.valid_from <= on))
			& (referral.valid_upto.isnull() | (referral.valid_upto >= on))
		)
	).run(as_dict=True)

	carton = get_carton_factors({line.item_code for line in lines})
	uom_factor = get_uom_factors({(line.item_code, line.uom) for line in lines})

	amounts, no_carton = {}, set()
	for line in lines:
		name = by_customer[line.customer].customer_name
		# Discounts are per carton: Discount Percentage / Rate rows are ignored, without a note.
		if (line.rate_or_discount or "Discount Amount") != "Discount Amount":
			continue
		factor = uom_factor.get((line.item_code, line.uom))
		if not carton.get(line.item_code) or not factor:
			no_carton.add(f"{name} ({line.item_code})")
			continue
		# discount per uom -> per stock unit -> per carton
		per_carton = flt(line.discount_amount) / factor * carton[line.item_code]
		amounts.setdefault(line.customer, []).append(per_carton)

	for row in rows:
		values = amounts.get(row.customer)
		if not values:
			row.discount = ""
			continue
		low, high = min(values), max(values)
		row.discount = fmt_amount(low) if high - low <= AMOUNT_TOLERANCE else f"{fmt_amount(low)}{EN_DASH}{fmt_amount(high)}"

	notes = []
	if no_carton:
		notes.append(_("Referral items without a Carton UOM, not in Discount: {0}").format(", ".join(sorted(no_carton))))
	return notes


def get_uom_factors(pairs):
	"""{(item_code, uom): stock units per uom}; the stock UOM itself is 1."""
	if not pairs:
		return {}
	items = list({item_code for item_code, _uom in pairs})
	factors = {
		(d.parent, d.uom): flt(d.conversion_factor)
		for d in frappe.get_all(
			"UOM Conversion Detail",
			filters={"parenttype": "Item", "parent": ["in", items]},
			fields=["parent", "uom", "conversion_factor"],
		)
		if flt(d.conversion_factor) > 0
	}
	for name, stock_uom in frappe.get_all("Item", filters={"name": ["in", items]}, fields=["name", "stock_uom"], as_list=True):
		factors[(name, stock_uom)] = 1
	return factors


# ============================================================
# BALANCE
# ============================================================


def set_balances(rows, company):
	gle = frappe.qb.DocType("GL Entry")
	balances = dict(
		frappe.qb.from_(gle)
		.select(gle.party, Sum(gle.debit - gle.credit))
		.where(
			(gle.company == company)
			& (gle.party_type == "Customer")
			& (gle.party.isin([row.customer for row in rows]))
			& (gle.posting_date <= getdate(today()))
			& (gle.is_cancelled == 0)
		)
		.groupby(gle.party)
		.run()
	)

	for row in rows:
		balance = flt(balances.get(row.customer))
		row.balance_value = balance
		row.balance = fmt_amount(abs(balance)) + (" CR" if balance < -AMOUNT_TOLERANCE else "")


def fmt_amount(value):
	"""56000 -> '56,000'; decimals only when there are any (56,000.50)."""
	value = flt(value, 2)
	return fmt_money(value, precision=0 if value == int(value) else 2)


# ============================================================
# COLUMNS
# ============================================================


def get_columns():
	def text(label, fieldname, width, **extra):
		return {"label": label, "fieldname": fieldname, "fieldtype": "Data", "width": width, **extra}

	return [
		text(_("AC/Code"), "ac_code", 100),
		text(_("A/C Title"), "customer_name", 220),
		text(_("Sale Person"), "sales_person", 140),
		text(_("Region"), "region", 130),
		text(_("City"), "city", 110),
		text(_("Area"), "area", 120),
		text(_("Discount"), "discount", 90, align="right", description=_("Per carton, from the active Customer Referral")),
		text(_("Balance"), "balance", 120, align="right", description=_("Receivable balance up to today; CR = credit balance")),
	]
