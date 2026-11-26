# Copyright (c) 2026, TRPL Solutions and contributors
# For license information, please see license.txt

"""Ledger Sharing Report: the client's sheet "LEDGER SHARING REPORT".

Rows        Enabled customers whose Sales Team includes the selected Sales Officer (or a person
            under that Sales Officer group); the report screen ticks them all by default.
A/C Code    Customer custom_ac_code, else the ID.
Aging Days  Days of the oldest invoice still unpaid on As On Date: Ageing Report Single Account's
            rows (Payment Ledger Entry), As On Date - Due Date; blank when nothing is unpaid.
Balance     The customer's GL balance up to As On Date; a credit balance with "CR" (as Print
            Customer List shows it).
Mobile /    Customer mobile_no / email_id, else its primary Contact's. whatsapp_number: the mobile
Email       in international digits (e.g. 923001234567) for a wa.me link, using the Company's
            country for local numbers (0300-1234567).
Ledger      The customer's statement as a PDF (download_ledger): opening balance on Ledger From
            Date, every GL entry up to As On Date (one line per voucher), running and closing
            balance.

Sharing (buttons on the report, ticked customers only):
  Download   download_ledgers_zip: one PDF per customer in a ZIP.
  Share      the browser's share sheet (Web Share API) with the PDFs from download_ledger.
  WhatsApp   wa.me click-to-chat per customer with a ready message; the PDF is downloaded to
             attach by hand (WhatsApp links cannot carry files).
  Email      send_ledger_emails: queues one email per customer with its PDF, through the outgoing
             Email Account; refused with a clear message when there is none.
"""

import io
import zipfile
from urllib.parse import urlencode

import frappe
import phonenumbers
from frappe import _
from frappe.query_builder.functions import Sum
from frappe.utils import cint, flt, formatdate, get_first_day, getdate, now_datetime, today
from frappe.utils.pdf import get_pdf

from erpnext.accounts.utils import get_fiscal_year
from pc_production.pc_production.report.ageing_report_single_account.ageing_report_single_account import (
	get_rows as get_ageing_rows,
)
from pc_production.pc_production.report.print_customer_list.print_customer_list import fmt_amount
from pc_production.pc_production.report.recovery_report.recovery_report import get_teams
from pc_production.pc_production.report.sales_report.sales_report import get_descendants
from pc_production.pc_production.report_print import add_font_faces

REPORT_NAME = "Ledger Sharing Report"
AMOUNT_TOLERANCE = 0.005
LEDGER_TEMPLATE = "pc_production/pc_production/report/ledger_sharing_report/ledger_statement.html"
DOWNLOAD_METHOD = "/api/method/pc_production.pc_production.report.ledger_sharing_report.ledger_sharing_report.download_ledger"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	validate_filters(filters)

	rows = get_customers(filters)
	if not rows:
		return get_columns(), []

	set_balances(rows, filters)
	set_aging_days(rows, filters)
	set_contacts(rows, filters.company)
	for row in rows:
		row.ledger_url = ledger_url(row.customer, filters)
	return get_columns(), sorted(rows, key=lambda r: (r.customer_name or "").lower())


def validate_filters(filters):
	for fieldname, label in (("company", "Company"), ("sales_person", "Sales Officer")):
		if not filters.get(fieldname):
			frappe.throw(_("{0} is mandatory").format(_(label)))
	filters.as_on_date = getdate(filters.get("as_on_date") or today())
	filters.from_date = getdate(filters.get("from_date") or default_from_date(filters.as_on_date, filters.company))
	if filters.from_date > filters.as_on_date:
		frappe.throw(_("Ledger From Date cannot be after As On Date"))


def default_from_date(as_on_date, company):
	try:
		return get_fiscal_year(as_on_date, company=company)[1]
	except Exception:
		return get_first_day(as_on_date)


def check_permission():
	if not frappe.get_doc("Report", REPORT_NAME).is_permitted():
		frappe.throw(_("Not permitted to use {0}").format(REPORT_NAME), frappe.PermissionError)


# ============================================================
# CUSTOMERS
# ============================================================


def get_customers(filters):
	people = set(get_descendants("Sales Person", filters.sales_person))
	teams = get_teams("Customer", set(frappe.get_all("Customer", filters={"disabled": 0}, pluck="name")))
	names = [customer for customer, team in teams.items() if any(sp in people for sp, _pct in team)]
	if not names:
		return []
	return [
		frappe._dict(
			customer=c.name,
			customer_name=c.customer_name or c.name,
			ac_code=(c.custom_ac_code or "").strip() or c.name,
		)
		for c in frappe.get_all(
			"Customer", filters={"name": ["in", names]}, fields=["name", "customer_name", "custom_ac_code"]
		)
	]


def set_balances(rows, filters):
	gle = frappe.qb.DocType("GL Entry")
	balances = dict(
		frappe.qb.from_(gle)
		.select(gle.party, Sum(gle.debit - gle.credit))
		.where(
			(gle.company == filters.company)
			& (gle.party_type == "Customer")
			& (gle.party.isin([r.customer for r in rows]))
			& (gle.posting_date <= filters.as_on_date)
			& (gle.is_cancelled == 0)
		)
		.groupby(gle.party)
		.run()
	)
	for row in rows:
		row.balance_value = flt(balances.get(row.customer))
		row.balance = balance_label(row.balance_value)


def balance_label(value):
	return fmt_amount(abs(value)) + (" CR" if value < -AMOUNT_TOLERANCE else "")


def set_aging_days(rows, filters):
	"""Oldest unpaid invoice on As On Date, from Ageing Report Single Account's rows."""
	for row in rows:
		invoices = get_ageing_rows(
			frappe._dict(company=filters.company, customer=row.customer, as_on_date=filters.as_on_date)
		)
		days = [r.ageing_days for r in invoices if r.row_type == "invoice" and r.balance > 0 and r.ageing_days is not None]
		row.aging_days = max(days) if days else None


def set_contacts(rows, company):
	customers = {
		c.name: c
		for c in frappe.get_all(
			"Customer",
			filters={"name": ["in", [r.customer for r in rows]]},
			fields=["name", "mobile_no", "email_id", "customer_primary_contact"],
		)
	}
	contact_names = [c.customer_primary_contact for c in customers.values() if c.customer_primary_contact]
	contacts = {
		c.name: c
		for c in frappe.get_all(
			"Contact", filters={"name": ["in", contact_names or [""]]}, fields=["name", "mobile_no", "phone", "email_id"]
		)
	}
	region = get_company_region(company)
	for row in rows:
		c = customers[row.customer]
		contact = contacts.get(c.customer_primary_contact) or frappe._dict()
		row.mobile = (c.mobile_no or contact.mobile_no or contact.phone or "").strip()
		row.email = (c.email_id or contact.email_id or "").strip()
		row.whatsapp_number = whatsapp_number(row.mobile, region)


def get_company_region(company):
	country = frappe.get_cached_value("Company", company, "country")
	code = frappe.get_cached_value("Country", country, "code") if country else None
	return (code or "PK").upper()


def whatsapp_number(mobile, region):
	"""'0300-1234567' -> '923001234567' (digits for wa.me); '' when not a valid number."""
	if not mobile:
		return ""
	try:
		number = phonenumbers.parse(mobile, region)
	except phonenumbers.NumberParseException:
		return ""
	if not phonenumbers.is_valid_number(number):
		return ""
	return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164).lstrip("+")


def ledger_url(customer, filters):
	return f"{DOWNLOAD_METHOD}?" + urlencode(
		{
			"company": filters.company,
			"customer": customer,
			"from_date": str(filters.from_date),
			"to_date": str(filters.as_on_date),
		}
	)


def get_columns():
	return [
		{"label": _("A/C Code"), "fieldname": "ac_code", "fieldtype": "Data", "width": 110},
		{"label": _("Customer Name"), "fieldname": "customer_name", "fieldtype": "Data", "width": 240},
		{
			"label": _("Aging Days"),
			"fieldname": "aging_days",
			"fieldtype": "Int",
			"width": 100,
			"description": _("Days of the oldest unpaid invoice (As On Date - Due Date)"),
		},
		{
			"label": _("Balance Amount"),
			"fieldname": "balance",
			"fieldtype": "Data",
			"width": 140,
			"align": "right",
			"description": _("Customer balance on As On Date; CR = credit balance"),
		},
		{"label": _("Mobile"), "fieldname": "mobile", "fieldtype": "Data", "width": 130},
		{"label": _("Ledger"), "fieldname": "ledger_url", "fieldtype": "Data", "width": 90},
	]


# ============================================================
# LEDGER PDF
# ============================================================


def get_ledger_context(company, customer, from_date, to_date):
	from_date, to_date = getdate(from_date), getdate(to_date)
	gle = frappe.qb.DocType("GL Entry")
	base = (
		(gle.company == company)
		& (gle.party_type == "Customer")
		& (gle.party == customer)
		& (gle.is_cancelled == 0)
	)
	opening = flt(
		frappe.qb.from_(gle).select(Sum(gle.debit - gle.credit)).where(base & (gle.posting_date < from_date)).run()[0][0]
	)
	entries = (
		frappe.qb.from_(gle)
		.select(
			gle.posting_date,
			gle.voucher_type,
			gle.voucher_no,
			Sum(gle.debit).as_("debit"),
			Sum(gle.credit).as_("credit"),
		)
		.where(base & (gle.posting_date >= from_date) & (gle.posting_date <= to_date))
		.groupby(gle.posting_date, gle.voucher_type, gle.voucher_no)
		.orderby(gle.posting_date)
		.orderby(gle.voucher_no)
	).run(as_dict=True)

	remarks = get_voucher_remarks(entries)
	balance, lines = opening, []
	for e in entries:
		balance += flt(e.debit) - flt(e.credit)
		lines.append(
			frappe._dict(
				date=formatdate(e.posting_date, "dd-MM-yyyy"),
				voucher=e.voucher_no,
				description=remarks.get((e.voucher_type, e.voucher_no)) or _(e.voucher_type),
				debit=flt(e.debit),
				credit=flt(e.credit),
				balance=balance,
				balance_label=balance_label(balance),
			)
		)

	customer_doc = frappe.db.get_value("Customer", customer, ["customer_name", "custom_ac_code"], as_dict=True)
	return frappe._dict(
		company=company,
		customer_name=customer_doc.customer_name or customer,
		ac_code=(customer_doc.custom_ac_code or "").strip() or customer,
		from_date=formatdate(from_date, "dd-MM-yyyy"),
		to_date=formatdate(to_date, "dd-MM-yyyy"),
		opening=opening,
		opening_label=balance_label(opening),
		lines=lines,
		total_debit=sum(line.debit for line in lines),
		total_credit=sum(line.credit for line in lines),
		closing=balance,
		closing_label=balance_label(balance),
		printed_on=formatdate(now_datetime(), "dd-MM-yyyy"),
		fmt=lambda v: fmt_amount(v) if abs(flt(v)) > AMOUNT_TOLERANCE else "",
	)


def get_voucher_remarks(entries):
	"""Short description per voucher: invoice cartons/items, payment mode, journal remark."""
	remarks = {}
	invoices = [e.voucher_no for e in entries if e.voucher_type == "Sales Invoice"]
	for d in frappe.get_all("Sales Invoice", filters={"name": ["in", invoices or [""]]}, fields=["name", "is_return"]):
		remarks[("Sales Invoice", d.name)] = _("Credit Note") if d.is_return else _("Sales Invoice")
	payments = [e.voucher_no for e in entries if e.voucher_type == "Payment Entry"]
	for d in frappe.get_all(
		"Payment Entry", filters={"name": ["in", payments or [""]]}, fields=["name", "mode_of_payment", "reference_no"]
	):
		text = _("Payment received")
		if d.mode_of_payment:
			text += f" ({d.mode_of_payment})"
		if d.reference_no:
			text += f" {_('Ref')} {d.reference_no}"
		remarks[("Payment Entry", d.name)] = text
	journals = [e.voucher_no for e in entries if e.voucher_type == "Journal Entry"]
	for d in frappe.get_all("Journal Entry", filters={"name": ["in", journals or [""]]}, fields=["name", "user_remark", "voucher_type"]):
		remarks[("Journal Entry", d.name)] = (d.user_remark or d.voucher_type or "")[:80]
	return remarks


def get_ledger_pdf(company, customer, from_date, to_date):
	html = frappe.render_template(LEDGER_TEMPLATE, get_ledger_context(company, customer, from_date, to_date))
	html, fonts_dir = add_font_faces(html)
	return get_pdf(
		html,
		{
			"page-size": "A4",
			"margin-top": "10mm",
			"margin-bottom": "10mm",
			"margin-left": "9mm",
			"margin-right": "9mm",
			# Our own template: no network access, local files only from the bundled fonts folder.
			"proxy": "http://0.0.0.0:0",
			"allow": fonts_dir,
			"load-error-handling": "ignore",
			"load-media-error-handling": "ignore",
		},
	)


def ledger_filename(customer):
	code = frappe.db.get_value("Customer", customer, "custom_ac_code") or ""
	name = frappe.db.get_value("Customer", customer, "customer_name") or customer
	safe = "".join(ch if ch.isalnum() or ch in " -_." else "_" for ch in f"{code} {name}".strip())
	return f"Ledger {safe}.pdf"


@frappe.whitelist()
def download_ledger(company, customer, from_date, to_date):
	check_permission()
	frappe.local.response.filename = ledger_filename(customer)
	frappe.local.response.filecontent = get_ledger_pdf(company, customer, from_date, to_date)
	frappe.local.response.type = "pdf"


@frappe.whitelist(methods=["POST"])
def download_ledgers_zip(company, customers, from_date, to_date):
	check_permission()
	customers = frappe.parse_json(customers) if isinstance(customers, str) else customers
	if not customers:
		frappe.throw(_("Tick at least one customer."))
	buffer = io.BytesIO()
	with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
		for customer in customers:
			zf.writestr(ledger_filename(customer), get_ledger_pdf(company, customer, from_date, to_date))
	frappe.local.response.filename = f"Ledgers {formatdate(to_date, 'dd-MM-yyyy')}.zip"
	frappe.local.response.filecontent = buffer.getvalue()
	frappe.local.response.type = "download"


@frappe.whitelist(methods=["POST"])
def send_ledger_emails(company, customers, from_date, to_date):
	"""Queue one email per ticked customer with its ledger PDF. Returns {sent, no_email}."""
	check_permission()
	if not frappe.db.exists("Email Account", {"enable_outgoing": 1}):
		frappe.throw(
			_("No outgoing Email Account is set up. Set one up in Email Account, then try again."),
			title=_("Email not set up"),
		)
	customers = frappe.parse_json(customers) if isinstance(customers, str) else customers
	rows = [frappe._dict(customer=c) for c in customers or []]
	set_contacts(rows, company)

	sent, no_email = [], []
	for row in rows:
		name = frappe.db.get_value("Customer", row.customer, "customer_name") or row.customer
		if not row.email:
			no_email.append(name)
			continue
		frappe.sendmail(
			recipients=[row.email],
			subject=_("Account Ledger - {0} ({1} to {2})").format(
				name, formatdate(from_date, "dd-MM-yyyy"), formatdate(to_date, "dd-MM-yyyy")
			),
			message=_("Dear {0},<br><br>Please find attached your account ledger.<br><br>{1}").format(
				frappe.utils.escape_html(name), frappe.utils.escape_html(company)
			),
			attachments=[{"fname": ledger_filename(row.customer), "fcontent": get_ledger_pdf(company, row.customer, from_date, to_date)}],
			reference_doctype="Customer",
			reference_name=row.customer,
		)
		sent.append(name)
	return {"sent": sent, "no_email": no_email}
