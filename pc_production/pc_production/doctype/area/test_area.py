# Copyright (c) 2026, TRPL Solutions and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestArea(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_named_by_area_name(self):
		area = frappe.get_doc(
			{"doctype": "Area", "area_name": "_Test Area Gulberg", "city": "Lahore", "province": "Punjab"}
		).insert()
		self.assertEqual(area.name, "_Test Area Gulberg")

	def test_area_name_is_unique(self):
		frappe.get_doc({"doctype": "Area", "area_name": "_Test Area Saddar"}).insert()
		self.assertRaises(
			frappe.DuplicateEntryError,
			frappe.get_doc({"doctype": "Area", "area_name": "_Test Area Saddar"}).insert,
		)
