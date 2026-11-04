# Copyright (c) 2026, TRPL Solutions and contributors
# See license.txt

import frappe
from frappe.desk.search import search_link
from frappe.tests.utils import FrappeTestCase

YEAR = 2099  # far-future year so real settings never trigger the duplicate check
OTHER_COMPANY = "SR-TEST Other Company"


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

		expense = {"company": cls.company, "account_type": "Expense Account", "disabled": 0}
		cls.ledgers = frappe.get_all("Account", filters={**expense, "is_group": 0}, pluck="name", limit=2)
		cls.expense_group = frappe.db.get_value("Account", {**expense, "is_group": 1})
		cls.bank = frappe.db.get_value(
			"Account", {"company": cls.company, "account_type": "Bank", "is_group": 0}
		) or make_account(
			"SR-TEST Bank",
			frappe.db.get_value("Account", {"company": cls.company, "account_type": "Bank", "is_group": 1})
			or frappe.db.get_value("Account", {"company": cls.company, "root_type": "Asset", "is_group": 1}),
			cls.company,
			"Bank",
		)
		cls.income = frappe.db.get_value("Account", {"company": cls.company, "root_type": "Income", "is_group": 0})
		cls.untyped_expense = frappe.db.get_value(
			"Account", {"company": cls.company, "root_type": "Expense", "is_group": 0, "account_type": ""}
		)

		# Rolled back with the rest of the test transaction.
		cls.disabled = make_account("SR-TEST Disabled Expense", cls.expense_group, cls.company, "Expense Account")
		frappe.db.set_value("Account", cls.disabled, "disabled", 1)

	def make_setting(self, rows, month="January", expected_qty=100, **kwargs):
		return frappe.get_doc(
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

	def assert_rejected(self, account, pattern, **kwargs):
		doc = self.make_setting([(self.ledgers[0], 500), (account, 1000)], month="February", **kwargs)
		with self.assertRaisesRegex(frappe.ValidationError, rf"Row 2: Account .*{pattern}"):
			doc.insert()

	def test_expense_ledger_save_submit_and_calculate(self):
		self.assertEqual(len(self.ledgers), 2, "site needs two enabled Expense Account ledgers")
		doc = self.make_setting([(self.ledgers[0], 3000), (self.ledgers[1], 2000)], expected_qty=250)
		doc.insert()
		self.assertEqual(doc.total_expense_amount, 5000)
		self.assertEqual(doc.per_qty_amount, 20)
		self.assertEqual(str(doc.from_date), f"{YEAR}-01-01")
		self.assertEqual(str(doc.to_date), f"{YEAR}-01-31")
		doc.submit()
		self.assertEqual(doc.docstatus, 1)

	def test_expense_group_rejected(self):
		self.assert_rejected(self.expense_group, "is a Group Account")

	def test_bank_account_rejected(self):
		self.assert_rejected(self.bank, "must have Account Type 'Expense Account'")

	def test_income_account_rejected(self):
		self.assert_rejected(self.income, "must have Account Type 'Expense Account'")

	def test_untyped_expense_ledger_rejected(self):
		self.assert_rejected(self.untyped_expense, r"current: Not Set")

	def test_disabled_account_rejected(self):
		self.assert_rejected(self.disabled, "is disabled")

	def test_other_company_account_rejected(self):
		doc = self.make_setting([(self.ledgers[0], 1000)], month="April")
		doc.company = OTHER_COMPANY
		doc.flags.ignore_links = True
		with self.assertRaisesRegex(frappe.ValidationError, "Row 1: Account .* does not belong to Company"):
			doc.insert()

	def test_missing_account_rejected(self):
		doc = self.make_setting([("SR-TEST Missing Account", 1000)], month="May")
		doc.flags.ignore_links = True
		with self.assertRaisesRegex(frappe.ValidationError, "Row 1: Account .* does not exist"):
			doc.insert()

	def test_invalid_accounts_rejected_via_api(self):
		from frappe.client import insert

		for account in (self.expense_group, self.bank, self.income, self.disabled):
			doc = self.make_setting([(account, 1000)], month="March")
			with self.assertRaises(frappe.ValidationError, msg=account):
				insert(doc.as_dict())

	def test_link_search_with_form_filters(self):
		"""The filters set by monthly_production_setting.js return only valid accounts."""

		def search(txt="", company=None):
			filters = {
				"company": company or self.company,
				"account_type": "Expense Account",
				"is_group": 0,
				"disabled": 0,
			}
			return [r["value"] for r in search_link("Account", txt, filters=filters, page_length=500)]

		results = search()
		self.assertTrue(set(self.ledgers) <= set(results))
		for account in results:
			self.assertEqual(
				frappe.db.get_value("Account", account, ["account_type", "is_group", "disabled", "company"]),
				("Expense Account", 0, 0, self.company),
			)
		for excluded in (self.expense_group, self.bank, self.income, self.untyped_expense, self.disabled):
			self.assertNotIn(excluded, results)
			name = frappe.db.get_value("Account", excluded, "account_name")
			self.assertNotIn(excluded, search(name))

		name = frappe.db.get_value("Account", self.ledgers[0], "account_name")
		self.assertIn(self.ledgers[0], search(name))
		# A different company yields a different (here empty) option list.
		self.assertEqual(search(company=OTHER_COMPANY), [])


def make_account(account_name, parent_account, company, account_type):
	return (
		frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": account_name,
				"parent_account": parent_account,
				"company": company,
				"account_type": account_type,
			}
		)
		.insert()
		.name
	)
