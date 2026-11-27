# Copyright (c) 2026, TRPL Solutions and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, nowdate

FIRST_YEAR = 2020


class Year(Document):
	def validate(self):
		self.year = (self.year or "").strip()
		if not (len(self.year) == 4 and self.year.isdigit()):
			frappe.throw(_("Year must be a 4 digit number, e.g. 2026"))


def ensure_years():
	"""Make sure every Year from 2020 up to next year exists.
	Runs after migrate and daily, so the next year is added automatically."""
	next_year = getdate(nowdate()).year + 1
	existing = set(frappe.get_all("Year", pluck="name"))
	added = False
	for y in range(FIRST_YEAR, next_year + 1):
		if str(y) not in existing:
			frappe.get_doc({"doctype": "Year", "year": str(y)}).insert(ignore_permissions=True)
			added = True
	if added:
		frappe.db.commit()
