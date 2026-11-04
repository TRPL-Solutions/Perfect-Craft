# Copyright (c) 2026, TRPL Solutions and contributors
# For license information, please see license.txt

"""Sales Report regression tests.

All fixtures are created inside one transaction and rolled back by
FrappeTestCase; a before_commit guard makes any accidental commit fail.
"""

import io
import json
import time

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from pc_production.pc_production.report.sales_report.sales_report import execute

PREFIX = "SR-TEST"
FROM_DATE, TO_DATE = "2099-10-01", "2099-10-10"


def _block_commit():
	raise AssertionError("Sales Report tests must never commit")


class TestSalesReport(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.db.before_commit.add(_block_commit)
		cls.addClassCleanup(lambda: frappe.db.before_commit._functions.clear())
		frappe.set_user("Administrator")

		cls.company = frappe.defaults.get_global_default("company") or frappe.get_all("Company", pluck="name")[0]
		company = frappe.get_cached_doc("Company", cls.company)
		cls.abbr = company.abbr
		cls.income_account = company.default_income_account
		cls.cost_center = company.cost_center
		cls.receivable = company.default_receivable_account
		cls.receivable_parent = frappe.db.get_value("Account", cls.receivable, "parent_account")

		existing = frappe.db.count(
			"Sales Invoice",
			{"company": cls.company, "docstatus": 1, "posting_date": ["between", [FROM_DATE, "2099-10-31"]]},
		)
		if existing:
			raise AssertionError(f"Test window already contains {existing} real invoices")

		# Fixtures live in a far-future year so real client data never overlaps.
		if not frappe.db.get_value(
			"Fiscal Year", {"year_start_date": ["<=", FROM_DATE], "year_end_date": [">=", "2099-10-31"]}
		):
			frappe.get_doc(
				{
					"doctype": "Fiscal Year",
					"year": f"{PREFIX} 2099",
					"year_start_date": "2099-01-01",
					"year_end_date": "2099-12-31",
					"companies": [{"company": cls.company}],
				}
			).insert()

		cls.make_masters()
		cls.make_invoices()

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
		cls.item_a = make_item(f"{PREFIX}-ITEM-A", "PB Welding Electrode 10#", item_group, cls.company, cls.cost_center)
		cls.item_b = make_item(f"{PREFIX}-ITEM-B", "PB Welding Electrode 12#", item_group, cls.company, cls.cost_center)

		customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
		cls.cust_a = make_customer(f"{PREFIX} Abid Engineering", cls.south, customer_group)
		cls.cust_b = make_customer(f"{PREFIX} Zahid Traders", cls.north, customer_group)
		cls.cust_c = make_customer(f"{PREFIX} Mustafa Welding", None, customer_group)

		# Customer A: primary address set on the customer.
		address_a = make_address(cls.cust_a, "Karachi", "Gizri", is_primary=1)
		frappe.db.set_value("Customer", cls.cust_a, "customer_primary_address", address_a)
		# Customer B: only a linked address (exercises the fallback lookup).
		make_address(cls.cust_b, "Lahore", "Gulberg", is_primary=1)
		frappe.db.set_value("Customer", cls.cust_b, "customer_primary_address", None)
		# Customer C: no territory, no address -> N/A geography.

	@classmethod
	def make_invoices(cls):
		inv = cls.make_invoice
		# Multi-item invoice, single salesperson.
		cls.inv1 = inv(cls.cust_a, [(cls.item_a, 10, 100), (cls.item_b, 5, 200)], "2099-10-02", [(cls.owais, 100)])
		# Discount + tax + split salesperson.
		cls.inv2 = inv(
			cls.cust_b,
			[(cls.item_a, 20, 150)],
			"2099-10-03",
			[(cls.owais, 60), (cls.faisal, 40)],
			discount=300,
			taxes=True,
		)
		# No salesperson, separate receivable account.
		cls.inv3 = inv(cls.cust_c, [(cls.item_b, 1, 500)], "2099-10-04", debit_to=cls.test_receivable)
		# Return against inv1: 2 x item A.
		cls.ret1 = cls.make_return(cls.inv1, "2099-10-05", {cls.item_a: -2})
		# Excluded: draft, cancelled, outside range.
		cls.draft = inv(cls.cust_a, [(cls.item_a, 100, 100)], "2099-10-06", [(cls.owais, 100)], submit=False)
		cls.cancelled = inv(cls.cust_a, [(cls.item_a, 7, 100)], "2099-10-06", [(cls.owais, 100)])
		frappe.get_doc("Sales Invoice", cls.cancelled).cancel()
		cls.outside = inv(cls.cust_a, [(cls.item_a, 9, 100)], "2099-10-11", [(cls.owais, 100)])

	@classmethod
	def make_invoice(
		cls, customer, items, posting_date, team=None, debit_to=None, discount=0, taxes=False, submit=True
	):
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
		for item_code, qty, rate in items:
			si.append(
				"items",
				{
					"item_code": item_code,
					"qty": qty,
					"rate": rate,
					"income_account": cls.income_account,
					"cost_center": cls.cost_center,
				},
			)
		for sales_person, pct in team or []:
			si.append("sales_team", {"sales_person": sales_person, "allocated_percentage": pct})
		if discount:
			si.apply_discount_on = "Net Total"
			si.discount_amount = discount
		if taxes:
			si.append(
				"taxes",
				{
					"charge_type": "On Net Total",
					"account_head": frappe.db.get_value(
						"Account", {"company": cls.company, "account_type": "Tax", "is_group": 0}
					),
					"description": "GST",
					"rate": 10,
					"cost_center": cls.cost_center,
				},
			)
		si.insert()
		if submit:
			si.submit()
		return si.name

	@classmethod
	def make_return(cls, against, posting_date, qty_map):
		from erpnext.controllers.sales_and_purchase_return import make_return_doc

		ret = make_return_doc("Sales Invoice", against)
		ret.set_posting_time = 1
		ret.posting_date = ret.due_date = posting_date
		ret.items = [row for row in ret.items if row.item_code in qty_map]
		for row in ret.items:
			row.qty = qty_map[row.item_code]
		ret.insert()
		ret.submit()
		return ret.name

	# ------------------------------------------------------------
	# helpers
	# ------------------------------------------------------------

	def run_report(self, **kwargs):
		filters = {"company": self.company, "from_date": FROM_DATE, "to_date": TO_DATE}
		filters.update(kwargs)
		return execute(filters)[1]

	def grand(self, data):
		rows = [r for r in data if r.get("row_type") == "grand_total"]
		self.assertEqual(len(rows), 1)
		return round(flt(rows[0]["qty"]), 4), round(flt(rows[0]["amount"]), 4)

	def summary_groups(self, data):
		return [r["sales_person"] for r in data if r["row_type"] == "sales_person"]

	def subtotal(self, data, sales_person):
		row = next(r for r in data if r["row_type"] == "sales_person_total" and r["sales_person"] == sales_person)
		return round(row["qty"], 4), round(row["amount"], 4), row["percentage"]

	def invoice_totals(self, data):
		return {r["invoice_ref"]: round(r["amount"], 4) for r in data if r["row_type"] == "invoice_total"}

	def assert_reconciles(self, **kwargs):
		summary = self.run_report(report_type="Summary", **kwargs)
		detail = self.run_report(report_type="Detail", **kwargs)
		if not summary:
			self.assertEqual(detail, [])
			return None

		grand = self.grand(summary)
		self.assertEqual(grand, self.grand(detail), kwargs)

		subtotals = [r for r in summary if r["row_type"] == "sales_person_total"]
		customers = [r for r in summary if r["row_type"] == "customer"]
		self.assertAlmostEqual(sum(r["amount"] for r in subtotals), grand[1], 4)
		self.assertAlmostEqual(sum(r["amount"] for r in customers), grand[1], 4)
		self.assertAlmostEqual(sum(r["qty"] for r in customers), grand[0], 4)
		if grand[1]:
			self.assertAlmostEqual(sum(r["percentage"] for r in subtotals), 100, delta=0.05)

		items = [r for r in detail if r["row_type"] == "item"]
		self.assertAlmostEqual(sum(r["amount"] for r in items), grand[1], 4)
		self.assertAlmostEqual(sum(self.invoice_totals(detail).values()), grand[1], 4)
		return grand

	# ------------------------------------------------------------
	# basic inclusion rules
	# ------------------------------------------------------------

	def test_net_totals_include_returns(self):
		self.assertEqual(self.assert_reconciles(), (34, 5000))

	def test_gross_totals(self):
		self.assertEqual(self.assert_reconciles(sales_basis="Gross Sales"), (34, 5300))

	def test_exclude_returns(self):
		self.assertEqual(self.assert_reconciles(include_returns=0), (36, 5200))
		# Values the desk actually sends (falsy filter values are dropped client-side).
		self.assertEqual(self.assert_reconciles(include_returns="No"), (36, 5200))
		self.assertEqual(self.assert_reconciles(include_returns="Yes"), (34, 5000))
		detail = self.run_report(report_type="Detail", include_returns=0)
		self.assertNotIn(self.ret1, self.invoice_totals(detail))

	def test_return_is_negative(self):
		totals = self.invoice_totals(self.run_report(report_type="Detail"))
		self.assertEqual(totals[self.ret1], -200)

	def test_draft_cancelled_and_out_of_range_excluded(self):
		totals = self.invoice_totals(self.run_report(report_type="Detail"))
		for name in (self.draft, self.cancelled, self.outside):
			self.assertNotIn(name, totals)
		self.assertEqual(set(totals), {self.inv1, self.inv2, self.inv3, self.ret1})

	def test_date_boundary_inclusive(self):
		self.assertEqual(self.assert_reconciles(from_date="2099-10-11", to_date="2099-10-11"), (9, 900))

	def test_taxes_excluded_and_discount_applied(self):
		totals = self.invoice_totals(self.run_report(report_type="Detail"))
		self.assertEqual(totals[self.inv2], 2700)
		gross = self.invoice_totals(self.run_report(report_type="Detail", sales_basis="Gross Sales"))
		self.assertEqual(gross[self.inv2], 3000)

	def test_rate_follows_basis(self):
		net = self.run_report(report_type="Detail")
		row = next(r for r in net if r["row_type"] == "item" and r["invoice_ref"] == self.inv2)
		self.assertEqual(round(row["rate"], 2), 135)
		gross = self.run_report(report_type="Detail", sales_basis="Gross Sales")
		row = next(r for r in gross if r["row_type"] == "item" and r["invoice_ref"] == self.inv2)
		self.assertEqual(round(row["rate"], 2), 150)

	# ------------------------------------------------------------
	# detail structure
	# ------------------------------------------------------------

	def test_detail_multi_item_grouping(self):
		data = self.run_report(report_type="Detail", sort_by="Date")
		rows = [r for r in data if r.get("invoice_ref") == self.inv1]
		self.assertEqual([r["row_type"] for r in rows], ["item", "item", "invoice_total"])
		self.assertEqual(rows[0]["invoice"], self.inv1)
		self.assertNotIn("invoice", rows[1])
		self.assertEqual((rows[2]["qty"], rows[2]["amount"]), (15, 2000))
		self.assertEqual(rows[0]["customer_name"], self.cust_a)
		self.assertEqual((rows[0]["region"], rows[0]["city"], rows[0]["area"]), (self.south, "Karachi", "Gizri"))

	def test_detail_no_duplicate_invoice_values(self):
		data = self.run_report(report_type="Detail")
		item_rows = [r for r in data if r["row_type"] == "item"]
		self.assertEqual(len(item_rows), 5)
		self.assertEqual(sum(1 for r in data if r["row_type"] == "invoice_total"), 4)
		self.assertEqual(data[-1]["row_type"], "grand_total")

	def test_detail_split_salesperson_label(self):
		data = self.run_report(report_type="Detail")
		row = next(r for r in data if r.get("invoice") == self.inv2)
		self.assertEqual(row["sales_person"], f"{self.owais} (60%), {self.faisal} (40%)")
		row = next(r for r in data if r.get("invoice") == self.inv3)
		self.assertEqual(row["sales_person"], "Unassigned")

	def test_detail_salesperson_filter_allocates(self):
		data = self.run_report(report_type="Detail", sales_person=self.faisal)
		self.assertEqual(self.invoice_totals(data), {self.inv2: 1080})
		row = next(r for r in data if r["row_type"] == "item")
		self.assertEqual(round(row["qty"], 4), 8)

	# ------------------------------------------------------------
	# summary structure
	# ------------------------------------------------------------

	def test_summary_grouping_and_subtotals(self):
		data = self.run_report(report_type="Summary")
		self.assertEqual(self.summary_groups(data), [self.faisal, self.owais, "Unassigned"])
		self.assertEqual(self.subtotal(data, self.owais), (25, 3420, 68.4))
		self.assertEqual(self.subtotal(data, self.faisal), (8, 1080, 21.6))
		self.assertEqual(self.subtotal(data, "Unassigned"), (1, 500, 10))
		self.assertEqual(data[-1]["percentage"], 100)

	def test_summary_customer_rows(self):
		data = self.run_report(report_type="Summary")
		owais_rows = [r for r in data if r["row_type"] == "customer" and r["sales_person"] == self.owais]
		by_customer = {r["customer"]: (round(r["qty"], 4), round(r["amount"], 4)) for r in owais_rows}
		self.assertEqual(by_customer, {self.cust_a: (13, 1800), self.cust_b: (12, 1620)})
		self.assertEqual([r["sno"] for r in data if r["row_type"] == "customer"], ["1", "2", "3", "4"])

	def test_summary_customer_without_geography(self):
		data = self.run_report(report_type="Summary")
		row = next(r for r in data if r.get("customer") == self.cust_c)
		self.assertEqual((row["region"], row["city"], row["area"]), ("N/A", "N/A", "N/A"))
		self.assertEqual(row["sales_person"], "Unassigned")

	def test_summary_address_fallback(self):
		data = self.run_report(report_type="Summary")
		row = next(r for r in data if r.get("customer") == self.cust_b)
		self.assertEqual((row["city"], row["area"]), ("Lahore", "Gulberg"))

	def test_percentage_uses_basis_denominator(self):
		data = self.run_report(report_type="Summary", sales_basis="Gross Sales")
		self.assertEqual(self.grand(data), (34, 5300))
		# Owais gross: 2000 - 200 + 0.6 * 3000 = 3600 -> 67.92%
		self.assertEqual(self.subtotal(data, self.owais), (25, 3600, 67.92))

	def test_zero_sales_and_empty_results(self):
		self.assertEqual(self.run_report(report_type="Summary", customer=self.cust_c, sales_person=self.owais), [])
		self.assertEqual(self.run_report(report_type="Detail", from_date="2099-10-22", to_date="2099-10-23"), [])
		# Return-only range nets to zero amount without dividing by zero.
		data = self.run_report(report_type="Summary", from_date="2099-10-05", to_date="2099-10-05")
		self.assertEqual(self.grand(data), (-2, -200))

	def test_zero_denominator(self):
		inv = self.make_invoice(self.cust_c, [(self.item_a, 1, 100)], "2099-10-21")
		self.make_return(inv, "2099-10-21", {self.item_a: -1})
		data = self.run_report(report_type="Summary", from_date="2099-10-21", to_date="2099-10-21")
		self.assertEqual(self.grand(data), (0, 0))
		self.assertTrue(all(r.get("percentage", 0) == 0 for r in data))

	# ------------------------------------------------------------
	# filters
	# ------------------------------------------------------------

	def test_filter_control_account(self):
		self.assertEqual(self.assert_reconciles(control_account=self.test_receivable), (1, 500))
		self.assertEqual(self.assert_reconciles(control_account=self.receivable), (33, 4500))
		self.assertEqual(self.assert_reconciles(control_account=self.receivable_parent), (34, 5000))

	def test_filter_territory(self):
		self.assertEqual(self.assert_reconciles(territory=self.south), (13, 1800))
		self.assertEqual(self.assert_reconciles(territory=self.north), (20, 2700))
		self.assertEqual(self.assert_reconciles(territory=self.region), (33, 4500))

	def test_filter_city(self):
		self.assertEqual(self.assert_reconciles(city="Karachi"), (13, 1800))
		self.assertEqual(self.assert_reconciles(city=" karachi "), (13, 1800))
		self.assertEqual(self.assert_reconciles(city="Lahore"), (20, 2700))
		self.assertIsNone(self.assert_reconciles(city="Quetta"))

	def test_filter_area(self):
		self.assertEqual(self.assert_reconciles(area="Gizri"), (13, 1800))
		self.assertEqual(self.assert_reconciles(area="gulberg"), (20, 2700))

	def test_filter_sales_person(self):
		self.assertEqual(self.assert_reconciles(sales_person=self.owais), (25, 3420))
		self.assertEqual(self.assert_reconciles(sales_person=self.faisal), (8, 1080))
		self.assertEqual(self.assert_reconciles(sales_person=self.sp_group), (33, 4500))
		data = self.run_report(report_type="Summary", sales_person=self.sp_group)
		self.assertNotIn("Unassigned", self.summary_groups(data))

	def test_filter_customer(self):
		self.assertEqual(self.assert_reconciles(customer=self.cust_a), (13, 1800))
		self.assertEqual(self.assert_reconciles(customer=self.cust_c), (1, 500))

	def test_combined_filters(self):
		self.assertEqual(self.assert_reconciles(territory=self.region, sales_person=self.faisal), (8, 1080))
		self.assertEqual(
			self.assert_reconciles(city="Karachi", sales_person=self.owais, include_returns=0), (15, 2000)
		)
		self.assertEqual(
			self.assert_reconciles(
				control_account=self.receivable, territory=self.north, sales_basis="Gross Sales"
			),
			(20, 3000),
		)
		self.assertIsNone(self.assert_reconciles(customer=self.cust_a, sales_person=self.faisal))

	def test_reconciliation_matrix(self):
		for report_filters in (
			{},
			{"sales_basis": "Gross Sales"},
			{"include_returns": 0},
			{"sort_by": "Amount", "sort_order": "Descending"},
			{"sort_by": "Date"},
			{"sales_person": self.owais, "sales_basis": "Gross Sales"},
		):
			self.assert_reconciles(**report_filters)

	def test_share_allocation_edge_cases(self):
		from pc_production.pc_production.report.sales_report.sales_report import get_shares

		self.assertEqual(get_shares([]), [("Unassigned", 1)])
		self.assertEqual(get_shares([("A", 60), ("B", 40)]), [("A", 0.6), ("B", 0.4)])
		# Partial allocation (legacy/imported data): remainder stays visible as Unassigned.
		self.assertEqual(get_shares([("A", 75)]), [("A", 0.75), ("Unassigned", 0.25)])
		# Over-allocation is scaled so an invoice is never counted more than once.
		shares = get_shares([("A", 100), ("B", 100)])
		self.assertEqual([(sp, round(f, 4)) for sp, f in shares], [("A", 0.5), ("B", 0.5)])
		self.assertEqual(get_shares([("A", 0), ("B", 100)]), [("B", 1.0)])

	def test_invalid_filters(self):
		with self.assertRaises(frappe.ValidationError):
			execute({"company": self.company, "from_date": "2099-10-10", "to_date": "2099-10-01"})
		with self.assertRaises(frappe.ValidationError):
			execute({"company": self.company, "from_date": FROM_DATE})

	# ------------------------------------------------------------
	# sorting
	# ------------------------------------------------------------

	def test_summary_sort_by_amount(self):
		data = self.run_report(report_type="Summary", sort_by="Amount", sort_order="Descending")
		self.assertEqual(self.summary_groups(data), [self.owais, self.faisal, "Unassigned"])
		owais = [r["customer"] for r in data if r["row_type"] == "customer" and r["sales_person"] == self.owais]
		self.assertEqual(owais, [self.cust_a, self.cust_b])
		data = self.run_report(report_type="Summary", sort_by="Amount", sort_order="Ascending")
		self.assertEqual(self.summary_groups(data), [self.faisal, self.owais, "Unassigned"])

	def test_summary_sort_by_name_descending(self):
		data = self.run_report(report_type="Summary", sort_by="Name", sort_order="Descending")
		self.assertEqual(self.summary_groups(data), [self.owais, self.faisal, "Unassigned"])
		owais = [r["customer"] for r in data if r["row_type"] == "customer" and r["sales_person"] == self.owais]
		self.assertEqual(owais, [self.cust_b, self.cust_a])

	def test_detail_sorting(self):
		order = lambda **kw: list(self.invoice_totals(self.run_report(report_type="Detail", **kw)))
		self.assertEqual(order(sort_by="Date"), [self.inv1, self.inv2, self.inv3, self.ret1])
		self.assertEqual(order(sort_by="Date", sort_order="Descending"), [self.ret1, self.inv3, self.inv2, self.inv1])
		self.assertEqual(order(sort_by="Amount", sort_order="Descending"), [self.inv2, self.inv1, self.inv3, self.ret1])
		self.assertEqual(order(sort_by="Name")[:2], [self.inv1, self.ret1])
		self.assertEqual(order(sort_by="Name")[-1], self.inv2)

	# ------------------------------------------------------------
	# framework integration
	# ------------------------------------------------------------

	def test_report_record(self):
		report = frappe.get_doc("Report", "Sales Report")
		self.assertEqual(
			(report.report_type, report.ref_doctype, report.module, report.is_standard),
			("Script Report", "Sales Invoice", "PC Production", "Yes"),
		)

	def test_run_through_query_report_api(self):
		from frappe.desk.query_report import get_script, run

		result = run("Sales Report", filters={"company": self.company, "from_date": FROM_DATE, "to_date": TO_DATE, "report_type": "Summary"})
		self.assertEqual(result["result"][-1]["amount"], 5000)
		self.assertIn("sr-table", get_script("Sales Report")["html_format"])

	def test_permissions(self):
		user = frappe.get_doc(
			{"doctype": "User", "email": "sr-test-noaccess@example.com", "first_name": PREFIX, "send_welcome_email": 0}
		).insert()
		user.add_roles("Stock User")
		from frappe.desk.query_report import run

		frappe.set_user(user.name)
		try:
			with self.assertRaises(frappe.PermissionError):
				run("Sales Report", filters={"company": self.company, "from_date": FROM_DATE, "to_date": TO_DATE})
		finally:
			frappe.set_user("Administrator")

		user.add_roles("Accounts User")
		frappe.set_user(user.name)
		try:
			result = run("Sales Report", filters={"company": self.company, "from_date": FROM_DATE, "to_date": TO_DATE, "report_type": "Summary"})
			self.assertEqual(result["result"][-1]["amount"], 5000)
		finally:
			frappe.set_user("Administrator")

	def test_excel_and_csv_export(self):
		from frappe.desk.query_report import export_query
		from openpyxl import load_workbook

		for report_type in ("Summary", "Detail"):
			for file_format in ("Excel", "CSV"):
				frappe.local.form_dict = frappe._dict(
					report_name="Sales Report",
					file_format_type=file_format,
					filters=json.dumps({"company": self.company, "from_date": FROM_DATE, "to_date": TO_DATE, "report_type": report_type}),
					visible_idx="[]",
					include_indentation=0,
				)
				frappe.response.pop("filecontent", None)
				export_query()
				content = frappe.response["filecontent"]
				if file_format == "Excel":
					sheet = load_workbook(io.BytesIO(content)).active
					values = [[c.value for c in row] for row in sheet.iter_rows()]
				else:
					text = content.decode() if isinstance(content, bytes) else content
					values = [line for line in text.splitlines() if line]
				flat = json.dumps(values, default=str)
				self.assertIn("Grand Total", flat, (report_type, file_format))
				self.assertIn("5000", flat, (report_type, file_format))

	def test_large_dataset(self):
		count, items_per_invoice = 120, 3
		team = [(self.owais, 70), (self.faisal, 30)]
		for i in range(count):
			self.make_invoice(
				[self.cust_a, self.cust_b, self.cust_c][i % 3],
				[(self.item_a, 1, 100), (self.item_b, 2, 50), (self.item_a, 3, 10)][:items_per_invoice],
				"2099-10-15",
				team if i % 2 else None,
			)

		start = time.monotonic()
		grand = self.assert_reconciles(from_date="2099-10-15", to_date="2099-10-15")
		elapsed = time.monotonic() - start
		self.assertEqual(grand, (count * 6, count * 230))
		detail = self.run_report(report_type="Detail", from_date="2099-10-15", to_date="2099-10-15")
		self.assertEqual(len(detail), count * (items_per_invoice + 1) + 1)
		self.assertLess(elapsed, 10)
		print(f"\nLarge dataset: {count} invoices / {count * items_per_invoice} items, summary+detail in {elapsed:.2f}s")


def make_tree(doctype, name, parent, is_group=0):
	name_field = {"Territory": "territory_name", "Sales Person": "sales_person_name"}[doctype]
	parent_field = {"Territory": "parent_territory", "Sales Person": "parent_sales_person"}[doctype]
	return frappe.get_doc({"doctype": doctype, name_field: name, parent_field: parent, "is_group": is_group}).insert().name


def make_item(code, item_name, item_group, company, cost_center):
	return (
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": code,
				"item_name": item_name,
				"item_group": item_group,
				"stock_uom": frappe.db.get_value("UOM", "Nos") or frappe.db.get_value("UOM", {}),
				"is_stock_item": 0,
				# Item Default cost centers are mandatory on this site.
				"item_defaults": [
					{"company": company, "buying_cost_center": cost_center, "selling_cost_center": cost_center}
				],
			}
		)
		.insert()
		.name
	)


def make_customer(name, territory, customer_group):
	return (
		frappe.get_doc(
			{"doctype": "Customer", "customer_name": name, "customer_group": customer_group, "territory": territory}
		)
		.insert()
		.name
	)


def make_address(customer, city, area, is_primary=0):
	address = frappe.get_doc(
		{
			"doctype": "Address",
			"address_title": customer,
			"address_type": "Billing",
			"address_line1": "Test Street",
			"city": city,
			"country": frappe.db.get_value("Country", "Pakistan") or frappe.db.get_value("Country", {}),
			"is_primary_address": is_primary,
			"links": [{"link_doctype": "Customer", "link_name": customer}],
		}
	)
	if address.meta.has_field("custom_area"):
		address.custom_area = area
	return address.insert().name
