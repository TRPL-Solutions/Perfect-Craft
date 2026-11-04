# Copyright (c) 2026, TRPL Solutions and contributors
# See license.txt

import frappe
from frappe.desk.search import search_link
from frappe.tests.utils import FrappeTestCase

YEAR = 2099  # far-future year so real settings never trigger the duplicate check


def _block_commit():
	raise AssertionError("Monthly Production Setting tests must never commit")


class TestMonthlyProductionSetting(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.db.before_commit.add(_block_commit)
		cls.addClassCleanup(lambda: frappe.db.before_commit._functions.clear())
		frappe.set_user("Administrator")

		cls.company = frappe.defaults.get_global_default("company") or frappe.get_all("Company", pluck="name")[0]
		cls.cost_center = frappe.db.get_value("Cost Center", {"company": cls.company, "is_group": 0})
		cls.ledgers = frappe.get_all(
			"Account",
			filters={"company": cls.company, "is_group": 0, "root_type": "Expense"},
			pluck="name",
			limit=2,
		)
		cls.group = frappe.db.get_value("Account", {"company": cls.company, "is_group": 1, "root_type": "Expense"})

	def make_setting(self, rows, month="January", expected_qty=100, **kwargs):
		doc = frappe.get_doc(
			{
				"doctype": "Monthly Production Setting",
				"company": self.company,
				"cost_center": self.cost_center,
				"month": month,
				"year": YEAR,
				"expected_qty": expected_qty,
				"expenses": [{"type_of_expense": acc, "expense_amount": amt} for acc, amt in rows],
				**kwargs,
			}
		)
		return doc

	def test_ledger_accounts_save_submit_and_calculate(self):
		doc = self.make_setting([(self.ledgers[0], 3000), (self.ledgers[1], 2000)], expected_qty=250)
		doc.insert()
		self.assertEqual(doc.total_expense_amount, 5000)
		self.assertEqual(doc.per_qty_amount, 20)
		self.assertEqual(str(doc.from_date), f"{YEAR}-01-01")
		self.assertEqual(str(doc.to_date), f"{YEAR}-01-31")
		doc.submit()
		self.assertEqual(doc.docstatus, 1)

	def test_group_account_rejected(self):
		doc = self.make_setting([(self.group, 1000)], month="February")
		with self.assertRaisesRegex(frappe.ValidationError, "not a Group Account"):
			doc.insert()

	def test_group_account_rejected_via_api(self):
		from frappe.client import insert

		doc = self.make_setting([(self.group, 1000)], month="March")
		with self.assertRaisesRegex(frappe.ValidationError, "not a Group Account"):
			insert(doc.as_dict())

	def test_other_company_account_rejected(self):
		doc = self.make_setting([(self.ledgers[0], 1000)], month="April")
		doc.company = "SR-TEST Other Company"
		doc.flags.ignore_links = True
		with self.assertRaisesRegex(frappe.ValidationError, "does not belong to Company"):
			doc.insert()

	def test_missing_account_rejected(self):
		doc = self.make_setting([("SR-TEST Missing Account", 1000)], month="May")
		doc.flags.ignore_links = True
		with self.assertRaisesRegex(frappe.ValidationError, "does not exist"):
			doc.insert()

	def test_link_search_with_form_filters(self):
		"""The filters set by monthly_production_setting.js exclude group accounts."""
		filters = {"is_group": 0, "company": self.company}
		results = [r["value"] for r in search_link("Account", "", filters=filters, page_length=500)]
		self.assertTrue(results)
		groups = set(frappe.get_all("Account", filters={"is_group": 1}, pluck="name"))
		self.assertFalse(groups & set(results))
		self.assertIn(self.ledgers[0], results)

		group_name = frappe.db.get_value("Account", self.group, "account_name")
		found = [r["value"] for r in search_link("Account", group_name, filters=filters, page_length=500)]
		self.assertNotIn(self.group, found)

		ledger_name = frappe.db.get_value("Account", self.ledgers[0], "account_name")
		found = [r["value"] for r in search_link("Account", ledger_name, filters=filters, page_length=500)]
		self.assertIn(self.ledgers[0], found)

		other = search_link("Account", "", filters={"is_group": 0, "company": "SR-TEST Other Company"})
		self.assertEqual(other, [])
