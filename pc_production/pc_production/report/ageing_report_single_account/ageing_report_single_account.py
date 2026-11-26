# Copyright (c) 2026, TRPL Solutions and contributors
# For license information, please see license.txt

"""Ageing Report Single Account: the client's sheet "9 EDITING AGING REPORT" (ERPNext's Accounts
Receivable is left untouched).

Header    A/C Code (Customer custom_ac_code, else the ID), A/C Title, A/C Balance = the customer's
          GL balance (debit - credit) up to As On Date; a credit balance shows with "CR".
Rows      From Payment Ledger Entry (the allocation ERPNext's ageing uses), entries posted up to
          As On Date, grouped by the document they are allocated to:
          - a submitted Sales Invoice with a balance left: one row (Due Date, Cartons, Ageing
            Days = As On Date - Due Date, negative = not yet due, Invoice Amount = what the
            invoice posted to the receivable, Balance Amount = what is left on As On Date).
            Payments and credit notes after As On Date do not count.
          - anything not allocated to an invoice (advance / unallocated payment, unallocated
            Journal Entry, credit note without an invoice): one row with its balance (negative
            for a credit), so TOTAL Balance Amount = A/C Balance.
          Sorted by Due Date (unallocated rows last, by posting date).
Cartons   stock_qty / the item's Carton UOM factor, the invoice's own lines (items without a
          Carton UOM: listed in the notes).
"""

from collections import defaultdict

import frappe
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import date_diff, flt, fmt_money, formatdate, getdate, today

from pc_production.pc_production.report.sales_person_target_achievement.sales_person_target_achievement import (
	get_carton_factors,
)

AMOUNT_TOLERANCE = 0.005
UNALLOCATED_LABEL = {
	"Payment Entry": _("Unallocated payment"),
	"Journal Entry": _("Unallocated journal entry"),
	"Sales Invoice": _("Credit note"),
}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	validate_filters(filters)

	header = get_header(filters)
	rows = get_rows(filters)
	notes = set_cartons([r for r in rows if r.row_type == "invoice"])
	return get_columns(), get_data(rows, header, notes)


def validate_filters(filters):
	for fieldname, label in (("company", "Company"), ("customer", "Customer")):
		if not filters.get(fieldname):
			frappe.throw(_("{0} is mandatory").format(_(label)))
	filters.as_on_date = getdate(filters.get("as_on_date") or today())


# ============================================================
# HEADER
# ============================================================


def get_header(filters):
	customer = frappe.db.get_value("Customer", filters.customer, ["customer_name", "custom_ac_code"], as_dict=True)
	if not customer:
		frappe.throw(_("Customer {0} not found").format(filters.customer))

	gle = frappe.qb.DocType("GL Entry")
	balance = flt(
		(
			frappe.qb.from_(gle)
			.select(Sum(gle.debit - gle.credit))
			.where(
				(gle.company == filters.company)
				& (gle.party_type == "Customer")
				& (gle.party == filters.customer)
				& (gle.posting_date <= filters.as_on_date)
				& (gle.is_cancelled == 0)
			)
			.run()
		)[0][0]
	)
	return frappe._dict(
		ac_code=(customer.custom_ac_code or "").strip() or filters.customer,
		ac_title=customer.customer_name or filters.customer,
		balance=balance,
		balance_label=fmt_amount(abs(balance)) + (" CR" if balance < -AMOUNT_TOLERANCE else ""),
		as_on=formatdate(filters.as_on_date, "dd-MMM-yyyy"),
	)


def fmt_amount(value):
	"""3235139 -> '3,235,139'; decimals only when there are any."""
	value = flt(value, 2)
	return fmt_money(value, precision=0 if value == int(value) else 2)


# ============================================================
# ROWS (Payment Ledger Entry)
# ============================================================


def get_rows(filters):
	ple = frappe.qb.DocType("Payment Ledger Entry")
	entries = (
		frappe.qb.from_(ple)
		.select(ple.voucher_type, ple.voucher_no, ple.against_voucher_type, ple.against_voucher_no, ple.amount, ple.posting_date)
		.where(
			(ple.company == filters.company)
			& (ple.party_type == "Customer")
			& (ple.party == filters.customer)
			& (ple.account_type == "Receivable")
			& (ple.delinked == 0)
			& (ple.posting_date <= filters.as_on_date)
		)
	).run(as_dict=True)

	groups = defaultdict(lambda: frappe._dict(balance=0.0, invoice_amount=0.0, posting_date=None))
	for e in entries:
		key = (e.against_voucher_type or e.voucher_type, e.against_voucher_no or e.voucher_no)
		group = groups[key]
		group.balance += flt(e.amount)
		if (e.voucher_type, e.voucher_no) == key:
			# The document's own posting: the invoice amount / the unallocated amount.
			group.invoice_amount += flt(e.amount)
			group.posting_date = e.posting_date

	open_groups = {key: g for key, g in groups.items() if abs(g.balance) > AMOUNT_TOLERANCE}
	invoices = get_invoices([no for (vtype, no) in open_groups if vtype == "Sales Invoice"])

	rows = []
	for (vtype, vno), g in open_groups.items():
		invoice = invoices.get(vno) if vtype == "Sales Invoice" else None
		if invoice and not invoice.is_return:
			rows.append(
				frappe._dict(
					row_type="invoice",
					due_date=invoice.due_date,
					invoice=vno,
					ageing_days=date_diff(filters.as_on_date, invoice.due_date) if invoice.due_date else None,
					invoice_amount=g.invoice_amount,
					balance=g.balance,
					sort=(0, getdate(invoice.due_date or invoice.posting_date), vno),
				)
			)
		else:
			rows.append(
				frappe._dict(
					row_type="unallocated",
					invoice=f"{vno} ({UNALLOCATED_LABEL.get(vtype, vtype)})",
					voucher_type=vtype,
					voucher_no=vno,
					invoice_amount=g.invoice_amount,
					balance=g.balance,
					sort=(1, getdate(g.posting_date or filters.as_on_date), vno),
				)
			)
	return sorted(rows, key=lambda r: r.sort)


def get_invoices(names):
	if not names:
		return {}
	return {
		d.name: d
		for d in frappe.get_all(
			"Sales Invoice",
			filters={"name": ["in", names], "docstatus": 1},
			fields=["name", "due_date", "posting_date", "is_return"],
		)
	}


def set_cartons(rows):
	"""row.cartons from the invoice's lines; returns notes for items without a Carton UOM."""
	if not rows:
		return []
	items = frappe.get_all(
		"Sales Invoice Item",
		filters={"parenttype": "Sales Invoice", "parent": ["in", [r.invoice for r in rows]]},
		fields=["parent", "item_code", "stock_qty"],
	)
	factors = get_carton_factors({d.item_code for d in items})
	cartons, missing = defaultdict(float), set()
	for d in items:
		if factors.get(d.item_code):
			cartons[d.parent] += flt(d.stock_qty) / factors[d.item_code]
		else:
			missing.add(d.item_code)
	for row in rows:
		row.cartons = cartons.get(row.invoice, 0.0)
	if missing:
		return [_("Items without a Carton UOM (not in Cartons): {0}").format(", ".join(sorted(missing)))]
	return []


# ============================================================
# OUTPUT
# ============================================================


def get_data(rows, header, notes):
	data = []
	for row in rows:
		data.append(
			{
				"row_type": row.row_type,
				"due_date": row.get("due_date"),
				"invoice": row.invoice,
				"voucher_type": row.get("voucher_type") or "Sales Invoice",
				"voucher_no": row.get("voucher_no") or row.invoice,
				"cartons": row.get("cartons"),
				"ageing_days": row.get("ageing_days"),
				# Unallocated rows: only their balance (not an invoice).
				"invoice_amount": row.invoice_amount if row.row_type == "invoice" else None,
				"balance": row.balance,
			}
		)

	total_balance = sum(r.balance for r in rows)
	if abs(total_balance - header.balance) > AMOUNT_TOLERANCE:
		# e.g. a receivable posting without a Payment Ledger Entry: never hidden.
		notes = notes + [
			_("Total Balance Amount {0} differs from A/C Balance {1}.").format(
				fmt_amount(total_balance), header.balance_label
			)
		]

	data.append(
		{
			"row_type": "total",
			"invoice": _("TOTAL"),
			"bold": 1,
			"cartons": sum(flt(r.get("cartons")) for r in rows),
			"invoice_amount": sum(r.invoice_amount for r in rows if r.row_type == "invoice"),
			"balance": total_balance,
			# Read by the screen heading and the print: header and notes.
			"ac_code": header.ac_code,
			"ac_title": header.ac_title,
			"ac_balance": header.balance_label,
			"as_on": header.as_on,
			"notes": notes,
		}
	)
	return data


def get_columns():
	currency = {"fieldtype": "Currency", "options": "Company:company:default_currency"}
	return [
		{"label": _("Due Date"), "fieldname": "due_date", "fieldtype": "Date", "width": 110},
		{"label": _("Sale Invoice No."), "fieldname": "invoice", "fieldtype": "Data", "width": 260},
		{"label": _("Cartons"), "fieldname": "cartons", "fieldtype": "Float", "precision": 0, "width": 90},
		{
			"label": _("Ageing Days"),
			"fieldname": "ageing_days",
			"fieldtype": "Int",
			"width": 100,
			"description": _("As On Date - Due Date (negative = not yet due)"),
		},
		{"label": _("Invoice Amount"), "fieldname": "invoice_amount", "width": 140, **currency},
		{"label": _("Balance Amount"), "fieldname": "balance", "width": 140, **currency},
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
