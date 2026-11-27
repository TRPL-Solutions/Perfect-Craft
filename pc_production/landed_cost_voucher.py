import calendar

import frappe
from frappe import _
from frappe.utils import cint

MONTHS = [
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
]


@frappe.whitelist()
def get_production_stock_entries(company: str, month: str, year: str, cost_center: str):
	"""Submitted Manufacture Stock Entries of a Cost Center in the given month,
	shaped as Landed Cost Voucher "Vouchers" rows."""
	frappe.has_permission("Stock Entry", "select", throw=True)

	if month not in MONTHS:
		frappe.throw(_("Invalid Month: {0}").format(month))

	year = cint(year)
	if not 1900 <= year <= 9999:
		frappe.throw(_("Year must be a 4 digit year"))

	month_no = MONTHS.index(month) + 1
	from_date = f"{year}-{month_no:02d}-01"
	to_date = f"{year}-{month_no:02d}-{calendar.monthrange(year, month_no)[1]:02d}"

	return frappe.get_all(
		"Stock Entry",
		filters={
			"docstatus": 1,
			"purpose": "Manufacture",
			"company": company,
			"cost_center": cost_center,
			"posting_date": ["between", [from_date, to_date]],
		},
		fields=["name", "posting_date", "total_incoming_value as grand_total"],
		order_by="posting_date asc, posting_time asc, name asc",
	)
