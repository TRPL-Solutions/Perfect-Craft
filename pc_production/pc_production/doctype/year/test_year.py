# Copyright (c) 2026, TRPL Solutions and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate, nowdate

from pc_production.pc_production.doctype.year.year import FIRST_YEAR, ensure_years


class TestYear(FrappeTestCase):
	def test_ensure_years_adds_up_to_next_year(self):
		ensure_years()
		next_year = getdate(nowdate()).year + 1
		for y in range(FIRST_YEAR, next_year + 1):
			self.assertTrue(frappe.db.exists("Year", str(y)))

	def test_year_must_be_4_digits(self):
		self.assertRaises(frappe.ValidationError, frappe.get_doc({"doctype": "Year", "year": "26"}).insert)
