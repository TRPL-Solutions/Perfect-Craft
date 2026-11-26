# Copyright (c) 2026, TRPL Solutions and contributors
# For license information, please see license.txt

"""Sales Person Year Wise Summary: the client's sheet "5-SALEMAN YEAR WISE".

One row per calendar month the From/To Date range touches (months without sales or receipts show
0), then TOTAL and AVERAGE PER MONTH (total / months in the range).

CARTON QTY    Submitted Sales Invoices (credit notes negative): stock_qty / the item's Carton UOM
              factor, from report_utils.get_invoice_lines (items without a Carton UOM: in the note).
TOTAL AMOUNT  The same invoice lines with tax, as Sales Vs Recovery Report: each invoice's
              base_grand_total spread over its lines by net amount (equal shares when the net
              total is zero). Lines without a Carton UOM still count here.
RECEIPT       Exactly Recovery Report (get_receipts / set_sales_person_shares): cash and bank
              actually received through Payment / Journal Entries, split to sales persons through
              the invoices they paid, in the month of the payment. City / Area on the customer's
              primary address. Brand and SKU do not apply (a payment is not split by brand).
Sales Person  With the filter, every figure is the selected persons' share: Qty and Amount by the
              invoice's Sales Team, Receipt as Recovery Report. Shown in the print title
              ("SALE PERSON: FAISAL"; ALL without the filter).
Show / Hide   show_qty / show_amount / show_receipt (Check filters; the desk does not send an
              unticked one). None ticked shows all three.
"""

import calendar
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, getdate

from pc_production.pc_production.report.recovery_report.recovery_report import (
	get_receipts,
	set_sales_person_shares,
)
from pc_production.pc_production.report.sales_report.sales_report import set_customer_geography
from pc_production.pc_production.report_utils import (
	QTY_TOLERANCE,
	get_invoice_lines,
	get_list,
	get_quality_notes,
	matches_geography,
)

MULTI_FILTERS = ("sales_person", "territory", "city", "area", "brand", "sku")
FIELDS = ("qty", "amount", "receipt")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	validate_filters(filters)
	months = get_months(filters.from_date, filters.to_date)
	shown = get_shown(filters)

	by_month = {month: defaultdict(float) for month in months}
	notes = []
	if "qty" in shown or "amount" in shown:
		notes += add_sales(by_month, filters)
	if "receipt" in shown:
		add_receipts(by_month, filters)
		if filters.brand or filters.sku:
			notes.append(_("Brand / SKU filter Qty and Amount only; Receipt is all money received."))

	data = get_data(by_month, months, shown, filters, notes)
	return get_columns(shown), data


def validate_filters(filters):
	for fieldname, label in (("company", "Company"), ("from_date", "From Date"), ("to_date", "To Date")):
		if not filters.get(fieldname):
			frappe.throw(_("{0} is mandatory").format(_(label)))
	filters.from_date, filters.to_date = getdate(filters.from_date), getdate(filters.to_date)
	if filters.from_date > filters.to_date:
		frappe.throw(_("From Date cannot be after To Date"))
	for fieldname in MULTI_FILTERS:
		filters[fieldname] = get_list(filters.get(fieldname))
	filters.customer_name = filters.get("customer") or None


def get_shown(filters):
	shown = [field for field in FIELDS if filters.get(f"show_{field}") not in (None, "", 0, "0", False)]
	return shown or list(FIELDS)


def get_months(from_date, to_date):
	months, (year, month) = [], (from_date.year, from_date.month)
	while (year, month) <= (to_date.year, to_date.month):
		months.append((year, month))
		year, month = (year + 1, 1) if month == 12 else (year, month + 1)
	return months


# ============================================================
# SALES (Carton Qty, Total Amount with tax)
# ============================================================


def add_sales(by_month, filters):
	line_filters = frappe._dict(filters, customer=[filters.customer_name] if filters.customer_name else [])
	lines = get_invoice_lines(line_filters)
	if not lines:
		return []

	totals = get_invoice_totals({line.invoice for line in lines})
	for line in lines:
		posted = getdate(line.posting_date)
		row = by_month[(posted.year, posted.month)]
		factor = flt(line.factor)
		row["qty"] += line.cartons * factor
		row["amount"] += line_amount_with_tax(line, totals[line.invoice]) * factor

	quality = get_quality_notes(lines, _("no Carton UOM (amount counted, cartons not)"))
	return [quality] if quality else []


def get_invoice_totals(invoices):
	"""{invoice: base_grand_total, base_net_total and line count}."""
	return {
		d.name: d
		for d in frappe.db.sql(
			"""
			select si.name, si.base_grand_total, si.base_net_total,
				(select count(*) from `tabSales Invoice Item` x
					where x.parent = si.name and x.parenttype = 'Sales Invoice') as line_count
			from `tabSales Invoice` si
			where si.name in %(invoices)s
			""",
			{"invoices": list(invoices)},
			as_dict=True,
		)
	}


def line_amount_with_tax(line, invoice):
	"""Invoice grand total spread over its lines by net amount (Sales Report GRAND_TOTAL_BASIS)."""
	if flt(invoice.base_net_total):
		return flt(line.base_net_amount) * flt(invoice.base_grand_total) / flt(invoice.base_net_total)
	return flt(invoice.base_grand_total) / (invoice.line_count or 1)


# ============================================================
# RECEIPTS (Recovery Report)
# ============================================================


def add_receipts(by_month, filters):
	receipts = get_receipts(
		frappe._dict(
			company=filters.company,
			from_date=filters.from_date,
			to_date=filters.to_date,
			customer=filters.customer_name,
			territory=filters.territory,
			debtors_account=None,
		)
	)
	set_sales_person_shares(receipts, frappe._dict(sales_person=filters.sales_person))
	receipts = [r for r in receipts if r.shares]
	if not receipts:
		return

	set_customer_geography(receipts)
	receipts = [r for r in receipts if matches_geography(r, filters)]
	dates = get_voucher_dates(receipts)
	for row in receipts:
		posted = dates[(row.voucher_type, row.voucher_no)]
		by_month[(posted.year, posted.month)]["receipt"] += flt(row.amount) * sum(f for _sp, f in row.shares)


def get_voucher_dates(receipts):
	"""{(voucher_type, voucher_no): posting_date} (get_receipts groups by voucher)."""
	dates = {}
	for voucher_type in {r.voucher_type for r in receipts}:
		names = [r.voucher_no for r in receipts if r.voucher_type == voucher_type]
		for name, posting_date in frappe.get_all(
			voucher_type, filters={"name": ["in", names]}, fields=["name", "posting_date"], as_list=True
		):
			dates[(voucher_type, name)] = getdate(posting_date)
	return dates


# ============================================================
# OUTPUT
# ============================================================


def get_data(by_month, months, shown, filters, notes):
	data = []
	for year, month in months:
		values = by_month[(year, month)]
		data.append({"row_type": "month", "month": f"{calendar.month_abbr[month]} {year}",
			**{field: flt(values.get(field)) for field in shown}})

	total = {field: sum(r[field] for r in data) for field in shown}
	data.append(
		{
			"row_type": "total",
			"month": _("TOTAL"),
			"bold": 1,
			**total,
			# Read by the print: title and notes.
			"report_title": _("SALE PERSON: {0}").format(
				", ".join(filters.sales_person).upper() if filters.sales_person else _("ALL")
			),
			"notes": notes,
		}
	)
	data.append(
		{
			"row_type": "average",
			"month": _("AVERAGE PER MONTH"),
			"bold": 1,
			**{field: total[field] / len(months) for field in shown},
		}
	)
	for row in data:
		for field in shown:
			if abs(row[field]) < QTY_TOLERANCE:
				row[field] = 0.0
	return data


def get_columns(shown):
	columns = {
		"qty": {"label": _("Carton Qty"), "fieldname": "qty", "fieldtype": "Float", "precision": 0, "width": 120},
		"amount": {
			"label": _("Total Amount"),
			"fieldname": "amount",
			"fieldtype": "Currency",
			"options": "Company:company:default_currency",
			"width": 150,
			"description": _("Sales with tax (invoice grand total)"),
		},
		"receipt": {
			"label": _("Receipt"),
			"fieldname": "receipt",
			"fieldtype": "Currency",
			"options": "Company:company:default_currency",
			"width": 150,
			"description": _("Money received (as Recovery Report)"),
		},
	}
	return [{"label": _("Month"), "fieldname": "month", "fieldtype": "Data", "width": 160}] + [
		columns[field] for field in shown
	]


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
		{"value": c.name, "label": f"{(c.custom_ac_code or '').strip() or c.name}: {c.customer_name or c.name}"}
		for c in customers
	]
