# Copyright (c) 2026, TRPL Solutions and contributors
# For license information, please see license.txt

"""Recovery Report regression tests.

All fixtures are created inside one transaction and rolled back by
FrappeTestCase; a before_commit guard makes any accidental commit fail.

Scenario (October 2099):
	inv1  Abid (South)     10,000  Owais 100
	inv2  Zahid (North)    20,000  Owais 60 / Faisal 40   (customer team: Faisal)
	inv3  Mustafa (North)   5,000  no team, test debtors account   (customer team: none)
	inv4  Abid              8,000  Faisal 100

	p1  inv1 10,000                         -> Owais 10,000
	p2  inv2 10,000                         -> Owais 6,000 / Faisal 4,000
	p3  inv2 5,000 allocated, 500 deducted  -> cash 4,500 -> Owais 2,700 / Faisal 1,800
	p4  advance Abid 3,000                  -> customer team Owais
	p5  advance Mustafa 1,000               -> Unassigned
	p6  inv3 2,000                          -> no invoice/customer team -> Unassigned
	p7  refund to Abid 500                  -> Owais -500
	je1 cash receipt Zahid 2,500 on inv2    -> Owais 1,500 / Faisal 1,000
	Excluded: write-off JE, credit note, cancelled payment, November payment.

	Owais 22,700   Faisal 6,800   Unassigned 3,000   Grand total 32,500
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from pc_production.pc_production.report.recovery_report.recovery_report import (
	execute,
	get_cash_factor,
	get_filter_options,
)
from pc_production.pc_production.report.sales_report.test_sales_report import (
	make_address,
	make_customer,
	make_item,
	make_tree,
)

PREFIX = "RR-TEST"
FROM_DATE, TO_DATE = "2099-10-01", "2099-10-31"


def _block_commit():
	raise AssertionError("Recovery Report tests must never commit")


class TestRecoveryReport(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.db.before_commit.add(_block_commit)
		cls.addClassCleanup(lambda: frappe.db.before_commit._functions.clear())
		frappe.set_user("Administrator")

		cls.company = (
			frappe.defaults.get_global_default("company") or frappe.get_all("Company", pluck="name")[0]
		)
		company = frappe.get_cached_doc("Company", cls.company)
		cls.income_account = company.default_income_account
		cls.cost_center = company.cost_center
		cls.receivable = company.default_receivable_account
		cls.receivable_parent = frappe.db.get_value("Account", cls.receivable, "parent_account")
		cls.cash = company.default_cash_account
		cls.write_off = company.write_off_account

		existing = frappe.db.count(
			"GL Entry",
			{
				"company": cls.company,
				"is_cancelled": 0,
				"posting_date": ["between", [FROM_DATE, "2099-11-30"]],
			},
		)
		if existing:
			raise AssertionError(f"Test window already contains {existing} real GL entries")

		# Fixtures live in a far-future year so real client data never overlaps.
		cls.fiscal_year = frappe.db.get_value(
			"Fiscal Year", {"year_start_date": ["<=", FROM_DATE], "year_end_date": [">=", "2099-11-30"]}
		)
		if not cls.fiscal_year:
			cls.fiscal_year = (
				frappe.get_doc(
					{
						"doctype": "Fiscal Year",
						"year": f"{PREFIX} 2099",
						"year_start_date": "2099-01-01",
						"year_end_date": "2099-12-31",
						"companies": [{"company": cls.company}],
					}
				)
				.insert()
				.name
			)

		cls.make_masters()
		cls.make_transactions()

	# ------------------------------------------------------------
	# fixtures
	# ------------------------------------------------------------

	@classmethod
	def make_masters(cls):
		cls.region = make_tree("Territory", f"{PREFIX} Region", "All Territories", is_group=1)
		cls.south = make_tree("Territory", f"{PREFIX} South", cls.region)
		cls.north = make_tree("Territory", f"{PREFIX} North", cls.region)

		root_sp = frappe.db.get_value("Sales Person", {"parent_sales_person": ["in", ["", None]]}, "name")
		cls.sp_group = make_tree("Sales Person", f"{PREFIX} Sales Group", root_sp, is_group=1)
		cls.owais = make_tree("Sales Person", f"{PREFIX} Owais", cls.sp_group)
		cls.faisal = make_tree("Sales Person", f"{PREFIX} Faisal", cls.sp_group)

		cls.test_receivable = (
			frappe.get_doc(
				{
					"doctype": "Account",
					"account_name": f"{PREFIX} Debtors",
					"parent_account": cls.receivable_parent,
					"company": cls.company,
					"account_type": "Receivable",
				}
			)
			.insert()
			.name
		)

		item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
		cls.item = make_item(
			f"{PREFIX}-ITEM", "PB Welding Electrode 10#", item_group, cls.company, cls.cost_center
		)

		customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
		cls.abid = make_customer(f"{PREFIX} Abid Engineering", cls.south, customer_group)
		cls.zahid = make_customer(f"{PREFIX} Zahid Traders", cls.north, customer_group)
		cls.mustafa = make_customer(f"{PREFIX} Mustafa Welding", cls.north, customer_group)

		address = make_address(cls.abid, "Karachi", "Korangi", is_primary=1)
		frappe.db.set_value("Customer", cls.abid, "customer_primary_address", address)
		make_address(cls.zahid, "Hyderabad", "Latifabad", is_primary=1)
		# Mustafa: no address -> City N/A.

		set_customer_team(cls.abid, [(cls.owais, 100)])
		set_customer_team(cls.zahid, [(cls.faisal, 100)])

	@classmethod
	def make_transactions(cls):
		inv = cls.make_invoice
		cls.inv1 = inv(cls.abid, 10000, "2099-10-02", [(cls.owais, 100)])
		cls.inv2 = inv(cls.zahid, 20000, "2099-10-03", [(cls.owais, 60), (cls.faisal, 40)])
		cls.inv3 = inv(cls.mustafa, 5000, "2099-10-04", [], debit_to=cls.test_receivable)
		cls.inv4 = inv(cls.abid, 8000, "2099-10-04", [(cls.faisal, 100)])

		cls.p1 = cls.receive(cls.inv1, 10000, "2099-10-05")
		cls.p2 = cls.receive(cls.inv2, 10000, "2099-10-06")
		cls.p3 = cls.receive(cls.inv2, 5000, "2099-10-07", deduction=500)
		cls.p4 = cls.unallocated("Receive", cls.abid, 3000, "2099-10-08")
		cls.p5 = cls.unallocated("Receive", cls.mustafa, 1000, "2099-10-09")
		cls.p6 = cls.receive(cls.inv3, 2000, "2099-10-10")
		cls.p7 = cls.unallocated("Pay", cls.abid, 500, "2099-10-11")
		cls.je1 = cls.journal(cls.zahid, 2500, "2099-10-12", debit_account=cls.cash, invoice=cls.inv2)

		# Excluded: no cash moves, cancelled, or outside the date range.
		cls.je_write_off = cls.journal(cls.zahid, 1000, "2099-10-13", debit_account=cls.write_off)
		cls.credit_note = cls.make_return(cls.inv4, "2099-10-14")
		cls.cancelled = cls.receive(cls.inv4, 4000, "2099-10-15")
		frappe.get_doc("Payment Entry", cls.cancelled).cancel()
		cls.outside = cls.receive(cls.inv4, 1000, "2099-11-01")

	@classmethod
	def make_invoice(cls, customer, amount, posting_date, team, debit_to=None):
		si = frappe.new_doc("Sales Invoice")
		si.update(
			{
				"company": cls.company,
				"customer": customer,
				"set_posting_time": 1,
				"posting_date": posting_date,
				"due_date": posting_date,
				"debit_to": debit_to or cls.receivable,
				"ignore_pricing_rule": 1,
			}
		)
		si.append(
			"items",
			{
				"item_code": cls.item,
				"qty": 1,
				"rate": amount,
				"income_account": cls.income_account,
				"cost_center": cls.cost_center,
			},
		)
		si.set("sales_team", [])
		for sales_person, pct in team:
			si.append("sales_team", {"sales_person": sales_person, "allocated_percentage": pct})
		si.insert()
		si.submit()
		return si.name

	@classmethod
	def make_return(cls, against, posting_date):
		from erpnext.controllers.sales_and_purchase_return import make_return_doc

		ret = make_return_doc("Sales Invoice", against)
		ret.set_posting_time = 1
		ret.posting_date = ret.due_date = posting_date
		ret.items[0].qty = -1
		ret.items[0].rate = 2000
		ret.insert()
		ret.submit()
		return ret.name

	@classmethod
	def receive(cls, invoice, allocated, posting_date, deduction=0):
		from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

		pe = get_payment_entry("Sales Invoice", invoice, party_amount=allocated - deduction)
		pe.posting_date = pe.reference_date = posting_date
		pe.reference_no = f"{PREFIX}-{posting_date}"
		if deduction:
			pe.append(
				"deductions", {"account": cls.write_off, "cost_center": cls.cost_center, "amount": deduction}
			)
			pe.references[0].allocated_amount = allocated
		pe.insert()
		pe.submit()
		return pe.name

	@classmethod
	def unallocated(cls, payment_type, customer, amount, posting_date):
		receive = payment_type == "Receive"
		pe = frappe.new_doc("Payment Entry")
		pe.update(
			{
				"payment_type": payment_type,
				"company": cls.company,
				"posting_date": posting_date,
				"party_type": "Customer",
				"party": customer,
				"paid_from": cls.receivable if receive else cls.cash,
				"paid_to": cls.cash if receive else cls.receivable,
				"paid_amount": amount,
				"received_amount": amount,
				"source_exchange_rate": 1,
				"target_exchange_rate": 1,
				"reference_no": f"{PREFIX}-{posting_date}",
				"reference_date": posting_date,
			}
		)
		pe.setup_party_account_field()
		pe.set_missing_values()
		pe.insert()
		pe.submit()
		return pe.name

	@classmethod
	def journal(cls, customer, amount, posting_date, debit_account, invoice=None):
		party_row = {
			"account": cls.receivable,
			"party_type": "Customer",
			"party": customer,
			"credit_in_account_currency": amount,
		}
		if invoice:
			party_row.update({"reference_type": "Sales Invoice", "reference_name": invoice})
		je = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"voucher_type": "Cash Entry" if debit_account == cls.cash else "Journal Entry",
				"company": cls.company,
				"posting_date": posting_date,
				"accounts": [
					{
						"account": debit_account,
						"debit_in_account_currency": amount,
						"cost_center": cls.cost_center,
					},
					party_row,
				],
			}
		)
		je.insert()
		je.submit()
		return je.name

	# ------------------------------------------------------------
	# helpers
	# ------------------------------------------------------------

	def run_report(self, **kwargs):
		filters = {"company": self.company, "from_date": FROM_DATE, "to_date": TO_DATE}
		filters.update(kwargs)
		return execute(filters)[1]

	def grand(self, data):
		rows = [r for r in data if r["row_type"] == "grand_total"]
		self.assertEqual(len(rows), 1)
		return round(flt(rows[0]["amount"]), 2)

	def subtotals(self, data):
		return {
			r["sales_person"]: round(r["amount"], 2) for r in data if r["row_type"] == "sales_person_total"
		}

	def customer_rows(self, data):
		return {(r["sales_person"], r["customer"]): r for r in data if r["row_type"] == "customer"}

	def assert_reconciles(self, data):
		grand = self.grand(data)
		customers = [r for r in data if r["row_type"] == "customer"]
		subtotals = [r for r in data if r["row_type"] == "sales_person_total"]
		self.assertAlmostEqual(sum(r["amount"] for r in customers), grand, 2)
		self.assertAlmostEqual(sum(r["amount"] for r in subtotals), grand, 2)
		if grand:
			self.assertAlmostEqual(sum(r["percentage"] for r in subtotals), 100, delta=0.05)
		return grand

	# ------------------------------------------------------------
	# amounts
	# ------------------------------------------------------------

	def test_totals_by_sales_person(self):
		data = self.run_report()
		self.assertEqual(self.assert_reconciles(data), 32500)
		self.assertEqual(self.subtotals(data), {self.owais: 22700, self.faisal: 6800, "Unassigned": 3000})

	def test_customer_rows(self):
		rows = self.customer_rows(self.run_report())
		self.assertEqual(
			{key: round(r["amount"], 2) for key, r in rows.items()},
			{
				(self.owais, self.abid): 12500,  # 10,000 + 3,000 advance - 500 refund
				(self.owais, self.zahid): 10200,  # 6,000 + 2,700 + 1,500
				(self.faisal, self.zahid): 6800,  # 4,000 + 1,800 + 1,000
				("Unassigned", self.mustafa): 3000,
			},
		)

	def test_deduction_counts_cash_only(self):
		rows = self.customer_rows(self.run_report(from_date="2099-10-07", to_date="2099-10-07"))
		self.assertAlmostEqual(rows[(self.owais, self.zahid)]["amount"], 2700)  # 60% of 4,500
		self.assertAlmostEqual(rows[(self.faisal, self.zahid)]["amount"], 1800)

	def test_refund_reduces_recovery(self):
		data = self.run_report(from_date="2099-10-11", to_date="2099-10-11")
		self.assertEqual(self.grand(data), -500)
		self.assertEqual(self.subtotals(data), {self.owais: -500})

	def test_journal_entry_cash_receipt_counts(self):
		data = self.run_report(from_date="2099-10-12", to_date="2099-10-12")
		self.assertEqual(self.subtotals(data), {self.owais: 1500, self.faisal: 1000})

	def test_credit_note_and_write_off_excluded(self):
		self.assertEqual(self.run_report(from_date="2099-10-13", to_date="2099-10-14"), [])

	def test_cancelled_and_out_of_range_excluded(self):
		self.assertEqual(self.run_report(from_date="2099-10-15", to_date="2099-10-15"), [])
		data = self.run_report(to_date="2099-11-01")
		self.assertEqual(self.grand(data), 33500)
		self.assertEqual(self.subtotals(data)[self.faisal], 7800)

	def test_cash_factor(self):
		self.assertEqual(get_cash_factor(9800, 10000), 0.98)
		self.assertEqual(get_cash_factor(-500, -500), 1)
		self.assertEqual(get_cash_factor(0, 1000), 0)
		self.assertEqual(get_cash_factor(15000, 10000), 1)
		self.assertEqual(get_cash_factor(500, 0), 0)

	# ------------------------------------------------------------
	# sales person attribution
	# ------------------------------------------------------------

	def test_invoice_team_wins_over_customer_team(self):
		# Zahid's customer team is Faisal 100, but p2 is allocated to an Owais 60 / Faisal 40 invoice.
		data = self.run_report(from_date="2099-10-06", to_date="2099-10-06")
		self.assertEqual(self.subtotals(data), {self.owais: 6000, self.faisal: 4000})

	def test_advance_uses_customer_team(self):
		data = self.run_report(from_date="2099-10-08", to_date="2099-10-08")
		self.assertEqual(self.subtotals(data), {self.owais: 3000})

	def test_unassigned(self):
		data = self.run_report(from_date="2099-10-09", to_date="2099-10-10")
		self.assertEqual(self.subtotals(data), {"Unassigned": 3000})
		groups = [r["sales_person"] for r in self.run_report() if r["row_type"] == "sales_person"]
		self.assertEqual(groups[-1], "Unassigned")

	def test_later_reconciliation_moves_advance_to_invoice_team(self):
		from erpnext.accounts.utils import reconcile_against_document

		pe = frappe.get_doc("Payment Entry", self.p4)
		reconcile_against_document(
			[
				frappe._dict(
					{
						"voucher_type": "Payment Entry",
						"voucher_no": pe.name,
						"voucher_detail_no": None,
						"against_voucher_type": "Sales Invoice",
						"against_voucher": self.inv4,
						"account": self.receivable,
						"party_type": "Customer",
						"party": self.abid,
						"dr_or_cr": "credit_in_account_currency",
						"unreconciled_amount": 3000,
						"unadjusted_amount": 3000,
						"allocated_amount": 3000,
						"grand_total": 8000,
						"outstanding_amount": 8000,
						"exchange_rate": 1,
						"is_advance": "Yes",
						"difference_amount": 0,
						"cost_center": self.cost_center,
					}
				)
			]
		)
		data = self.run_report(from_date="2099-10-08", to_date="2099-10-08")
		self.assertEqual(self.subtotals(data), {self.faisal: 3000})

	# ------------------------------------------------------------
	# layout
	# ------------------------------------------------------------

	def test_rows_and_percentages(self):
		data = self.run_report()
		rows = self.customer_rows(data)
		abid = rows[(self.owais, self.abid)]
		self.assertEqual((abid["region"], abid["city"]), (self.south, "Karachi"))
		self.assertAlmostEqual(abid["percentage"], round(12500 * 100 / 32500, 2))
		mustafa = rows[("Unassigned", self.mustafa)]
		self.assertEqual((mustafa["region"], mustafa["city"]), (self.north, "N/A"))
		self.assertEqual([r["sno"] for r in data if r["row_type"] == "customer"], ["1", "2", "3", "4"])

		total = data[-1]
		self.assertEqual((total["row_type"], total["percentage"], total["bold"]), ("grand_total", 100, 1))
		self.assertEqual(total["fiscal_year"], self.fiscal_year)

	def test_empty_result(self):
		self.assertEqual(self.run_report(from_date="2099-12-01", to_date="2099-12-31"), [])

	# ------------------------------------------------------------
	# filters
	# ------------------------------------------------------------

	def test_filter_sales_person(self):
		data = self.run_report(sales_person=self.owais)
		self.assertEqual(self.subtotals(data), {self.owais: 22700})
		self.assertEqual(data[-1]["percentage"], 100)
		self.assertEqual(self.grand(self.run_report(sales_person=self.sp_group)), 29500)

	def test_filter_territory(self):
		self.assertEqual(self.subtotals(self.run_report(territory=self.south)), {self.owais: 12500})
		self.assertEqual(self.grand(self.run_report(territory=self.region)), 32500)

	def test_filter_customer(self):
		data = self.run_report(customer=self.zahid)
		self.assertEqual(self.subtotals(data), {self.owais: 10200, self.faisal: 6800})

	def test_filter_debtors_account(self):
		self.assertEqual(
			self.subtotals(self.run_report(debtors_account=self.test_receivable)), {"Unassigned": 2000}
		)
		self.assertEqual(self.grand(self.run_report(debtors_account=self.receivable_parent)), 32500)

	def test_invalid_filters(self):
		for missing in ("company", "from_date", "to_date"):
			filters = {"company": self.company, "from_date": FROM_DATE, "to_date": TO_DATE}
			filters.pop(missing)
			with self.assertRaises(frappe.ValidationError):
				execute(filters)
		with self.assertRaises(frappe.ValidationError):
			self.run_report(from_date=TO_DATE, to_date=FROM_DATE)

	# ------------------------------------------------------------
	# report record, API, permissions
	# ------------------------------------------------------------

	def test_report_record(self):
		report = frappe.get_doc("Report", "Recovery Report")
		self.assertEqual(
			(report.report_type, report.ref_doctype, report.module, report.is_standard),
			("Script Report", "Item Group", "PC Production", "Yes"),
		)
		self.assertEqual(report.roles, [])

	def test_run_through_query_report_api(self):
		from frappe.desk.query_report import get_script, run

		result = run(
			"Recovery Report", filters={"company": self.company, "from_date": FROM_DATE, "to_date": TO_DATE}
		)
		self.assertEqual(result["result"][-1]["amount"], 32500)
		self.assertIn("Perfect Craft", get_script("Recovery Report")["html_format"])

	def test_desk_user_without_accounts_permissions(self):
		from frappe.desk.query_report import run

		# A desk user with an unrelated role: no permission on GL Entry or Sales Person.
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": "rr-test-noaccess@example.com",
				"first_name": PREFIX,
				"send_welcome_email": 0,
			}
		).insert()
		user.add_roles("Stock User")

		frappe.set_user(user.name)
		try:
			self.assertFalse(frappe.has_permission("GL Entry", "read"))
			self.assertFalse(frappe.has_permission("Sales Person", "read"))
			result = run(
				"Recovery Report",
				filters={
					"company": self.company,
					"from_date": FROM_DATE,
					"to_date": TO_DATE,
					"sales_person": self.sp_group,
					"territory": self.region,
				},
			)
			self.assertEqual(result["result"][-1]["amount"], 29500)

			self.assertIn(self.owais, get_filter_options("Sales Person", txt="Owais"))
			self.assertIn(self.south, get_filter_options("Territory", txt=PREFIX))
			self.assertIn(self.abid, [c["value"] for c in get_filter_options("Customer", txt="Abid")])
			accounts = get_filter_options("Account", company=self.company)
			self.assertIn(self.test_receivable, accounts)
			self.assertNotIn(self.cash, accounts)
			with self.assertRaises(frappe.PermissionError):
				get_filter_options("GL Entry")
		finally:
			frappe.set_user("Administrator")


def set_customer_team(customer, team):
	doc = frappe.get_doc("Customer", customer)
	doc.set("sales_team", [{"sales_person": sp, "allocated_percentage": pct} for sp, pct in team])
	doc.save()
