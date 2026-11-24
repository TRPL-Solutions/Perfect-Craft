# Copyright (c) 2026, TRPL Solutions and contributors
# For license information, please see license.txt

"""Sales Person Target Achievement regression tests.

All fixtures are created inside one transaction and rolled back by
FrappeTestCase; a before_commit guard makes any accidental commit fail.

Scenario (November 2099, targets in cartons):
	Owais   Electrodes 1200/yr, Nov = 10%      -> 120     Wires 120/yr even -> 10
	Faisal  all item groups 600/yr even         -> 50
	Bilal   Electrodes 240/yr even              -> 20

	inv1  Owais 100%          10 Ctn electrodes @1200            paid
	inv2  Owais 60 / Faisal 40  400 Nos electrodes (=20 Ctn) @60 + 5 Ctn wires @1000   unpaid
	inv3  Faisal (North)       30 Nos item without Carton UOM @50   500 of 1500 paid
	inv4  Bilal               5 Ctn electrodes @1200 + 1 Ctn wires @1000   paid
	cn1   credit note against inv1, -2 Ctn
	draft, cancelled and December invoices must not count.
"""

import datetime

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from pc_production.pc_production.report.sales_person_target_achievement.sales_person_target_achievement import (
	execute,
	get_period_share,
)
from pc_production.pc_production.report.sales_report.test_sales_report import make_customer, make_tree

PREFIX = "SPTA-TEST"
FROM_DATE, TO_DATE = "2099-11-01", "2099-11-30"
BY_ITEM_GROUP = "Sales Person and Item Group"
MONTHS = (
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
)


def _block_commit():
	raise AssertionError("Sales Person Target Achievement tests must never commit")


class TestSalesPersonTargetAchievement(FrappeTestCase):
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
		cls.currency = company.default_currency
		cls.income_account = company.default_income_account
		cls.cost_center = company.cost_center
		cls.receivable = company.default_receivable_account

		existing = frappe.db.count(
			"Sales Invoice",
			{"company": cls.company, "docstatus": 1, "posting_date": ["between", [FROM_DATE, "2099-12-31"]]},
		)
		if existing:
			raise AssertionError(f"Test window already contains {existing} real invoices")

		# Fixtures live in a far-future year so real client data never overlaps.
		cls.fiscal_year = frappe.db.get_value(
			"Fiscal Year", {"year_start_date": ["<=", "2099-01-01"], "year_end_date": [">=", "2099-12-31"]}
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
		cls.make_targets()
		cls.make_invoices()

	# ------------------------------------------------------------
	# fixtures
	# ------------------------------------------------------------

	@classmethod
	def make_masters(cls):
		for uom in ("Nos", "Carton"):
			if not frappe.db.exists("UOM", uom):
				frappe.get_doc({"doctype": "UOM", "uom_name": uom}).insert()

		root_group = frappe.db.get_value("Item Group", {"parent_item_group": ["in", ["", None]]}, "name")
		cls.root_group = root_group
		cls.products = make_item_group(f"{PREFIX} Products", root_group, is_group=1)
		cls.electrodes = make_item_group(f"{PREFIX} Electrodes", cls.products)
		cls.wires = make_item_group(f"{PREFIX} Wires", cls.products)

		cls.region = make_tree("Territory", f"{PREFIX} Region", "All Territories", is_group=1)
		cls.south = make_tree("Territory", f"{PREFIX} South", cls.region)
		cls.north = make_tree("Territory", f"{PREFIX} North", cls.region)

		root_sp = frappe.db.get_value("Sales Person", {"parent_sales_person": ["in", ["", None]]}, "name")
		cls.sp_group = make_tree("Sales Person", f"{PREFIX} Sales Group", root_sp, is_group=1)
		cls.owais = make_tree("Sales Person", f"{PREFIX} Owais", cls.sp_group)
		cls.faisal = make_tree("Sales Person", f"{PREFIX} Faisal", cls.sp_group)
		cls.bilal = make_tree("Sales Person", f"{PREFIX} Bilal", cls.sp_group)

		cls.elec = make_item(f"{PREFIX}-ELEC", cls.electrodes, 20, cls.company, cls.cost_center)
		cls.wire = make_item(f"{PREFIX}-WIRE", cls.wires, 10, cls.company, cls.cost_center)
		cls.loose = make_item(f"{PREFIX}-LOOSE", cls.electrodes, None, cls.company, cls.cost_center)

		customer_group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
		cls.cust_a = make_customer(f"{PREFIX} Abid Engineering", cls.south, customer_group)
		cls.cust_b = make_customer(f"{PREFIX} Zahid Traders", cls.north, customer_group)

	@classmethod
	def make_targets(cls):
		cls.season = make_distribution(f"{PREFIX} Season", november=10)
		cls.even = make_distribution(f"{PREFIX} Even", november=100 / 12)

		set_targets(
			cls.owais, [(cls.electrodes, 1200, cls.season), (cls.wires, 120, cls.even)], cls.fiscal_year
		)
		set_targets(cls.faisal, [(None, 600, cls.even)], cls.fiscal_year)
		set_targets(cls.bilal, [(cls.electrodes, 240, cls.even)], cls.fiscal_year)

	@classmethod
	def make_invoices(cls):
		inv = cls.make_invoice
		cls.inv1 = inv(cls.cust_a, [(cls.elec, 10, "Carton", 1200)], "2099-11-03", [(cls.owais, 100)])
		cls.pay(cls.inv1)
		cls.inv2 = inv(
			cls.cust_a,
			[(cls.elec, 400, "Nos", 60), (cls.wire, 5, "Carton", 1000)],
			"2099-11-10",
			[(cls.owais, 60), (cls.faisal, 40)],
		)
		cls.inv3 = inv(cls.cust_b, [(cls.loose, 30, "Nos", 50)], "2099-11-15", [(cls.faisal, 100)])
		cls.pay(cls.inv3, 500)
		cls.inv4 = inv(
			cls.cust_a,
			[(cls.elec, 5, "Carton", 1200), (cls.wire, 1, "Carton", 1000)],
			"2099-11-20",
			[(cls.bilal, 100)],
		)
		cls.pay(cls.inv4)
		cls.cn1 = cls.make_return(cls.inv1, "2099-11-25", -2)

		# Excluded: draft, cancelled, outside range.
		cls.draft = inv(
			cls.cust_a, [(cls.elec, 50, "Carton", 1200)], "2099-11-05", [(cls.owais, 100)], submit=False
		)
		cls.cancelled = inv(cls.cust_a, [(cls.elec, 7, "Carton", 1200)], "2099-11-06", [(cls.owais, 100)])
		frappe.get_doc("Sales Invoice", cls.cancelled).cancel()
		cls.outside = inv(cls.cust_a, [(cls.elec, 9, "Carton", 1200)], "2099-12-01", [(cls.owais, 100)])

	@classmethod
	def make_invoice(cls, customer, items, posting_date, team, submit=True):
		si = frappe.new_doc("Sales Invoice")
		si.update(
			{
				"company": cls.company,
				"customer": customer,
				"set_posting_time": 1,
				"posting_date": posting_date,
				"due_date": posting_date,
				"debit_to": cls.receivable,
				"ignore_pricing_rule": 1,
			}
		)
		for item_code, qty, uom, rate in items:
			si.append(
				"items",
				{
					"item_code": item_code,
					"qty": qty,
					"uom": uom,
					"rate": rate,
					"income_account": cls.income_account,
					"cost_center": cls.cost_center,
				},
			)
		for sales_person, pct in team:
			si.append("sales_team", {"sales_person": sales_person, "allocated_percentage": pct})
		si.insert()
		if submit:
			si.submit()
		return si.name

	@classmethod
	def make_return(cls, against, posting_date, qty):
		from erpnext.controllers.sales_and_purchase_return import make_return_doc

		ret = make_return_doc("Sales Invoice", against)
		ret.set_posting_time = 1
		ret.posting_date = ret.due_date = posting_date
		ret.items[0].qty = qty
		ret.insert()
		ret.submit()
		return ret.name

	@classmethod
	def pay(cls, invoice, amount=None):
		from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

		pe = get_payment_entry("Sales Invoice", invoice, party_amount=amount)
		pe.posting_date = frappe.db.get_value("Sales Invoice", invoice, "posting_date")
		pe.reference_no = f"{PREFIX}-{invoice}"
		pe.reference_date = pe.posting_date
		pe.insert()
		pe.submit()
		return pe.name

	# ------------------------------------------------------------
	# helpers
	# ------------------------------------------------------------

	def run_report(self, **kwargs):
		filters = {"company": self.company, "from_date": FROM_DATE, "to_date": TO_DATE}
		filters.update(kwargs)
		return execute(filters)

	def rows(self, **kwargs):
		"""{sales_person or (sales_person, item_group): row} for detail rows, plus 'total'."""
		data = self.run_report(**kwargs)[1]
		result = {}
		for row in data:
			if row["row_type"] == "sales_person":
				result[row["sales_person"]] = row
			elif row["row_type"] == "item_group":
				result[(row["sales_person"], row["item_group"])] = row
			elif row["row_type"] == "grand_total":
				result["total"] = row
		return result

	def assert_row(self, row, target=None, achieved=None, invoiced=None, outstanding=None, remarks=None):
		if target is not None:
			self.assertAlmostEqual(flt(row["target_qty"]), target, places=2)
		if achieved is not None:
			self.assertAlmostEqual(flt(row["achieved_qty"]), achieved, places=4)
		if invoiced is not None:
			self.assertAlmostEqual(flt(row["invoiced_amount"]), invoiced, places=2)
		if outstanding is not None:
			self.assertAlmostEqual(flt(row["outstanding_amount"]), outstanding, places=2)
			self.assertAlmostEqual(
				flt(row["received_amount"]), flt(row["invoiced_amount"]) - outstanding, places=2
			)
		if remarks is not None:
			self.assertEqual(row["remarks"], remarks)

	# ------------------------------------------------------------
	# targets
	# ------------------------------------------------------------

	def test_targets_prorated_by_monthly_distribution(self):
		rows = self.rows(group_by=BY_ITEM_GROUP)
		self.assert_row(rows[(self.owais, self.electrodes)], target=120)  # 1200 x 10%
		self.assert_row(rows[(self.owais, self.wires)], target=10)  # 120 / 12

	def test_part_month_prorated_by_days(self):
		rows = self.rows(to_date="2099-11-15")
		self.assert_row(rows[self.owais], target=65)  # (120 + 10) x 15/30
		self.assert_row(rows[self.bilal], target=10)

	def test_equal_split_without_distribution(self):
		# Target Distribution is mandatory in the form; legacy/imported rows may lack it.
		detail = frappe.db.get_value("Target Detail", {"parent": self.faisal}, "name")
		frappe.db.set_value("Target Detail", detail, "distribution_id", None)
		try:
			self.assert_row(self.rows()[self.faisal], target=50)
		finally:
			frappe.db.set_value("Target Detail", detail, "distribution_id", self.even)

	def test_period_share(self):
		d = datetime.date
		self.assertAlmostEqual(get_period_share(d(2099, 1, 1), d(2099, 12, 31)), 1)
		self.assertAlmostEqual(get_period_share(d(2099, 2, 1), d(2099, 2, 14)), 14 / 28 / 12)
		self.assertAlmostEqual(get_period_share(d(2099, 1, 31), d(2099, 2, 1)), (1 / 31 + 1 / 28) / 12)
		self.assertAlmostEqual(get_period_share(d(2099, 3, 1), d(2099, 3, 31), {"March": 25}), 0.25)
		self.assertEqual(get_period_share(d(2099, 3, 1), d(2099, 3, 31), {"April": 100}), 0)

	def test_sales_person_with_target_but_no_sales(self):
		rows = self.rows(from_date="2099-11-01", to_date="2099-11-02")
		# (120 + 10) x 2/30
		self.assert_row(rows[self.owais], target=8.6667, achieved=0, invoiced=0, remarks="")
		self.assertEqual(rows[self.owais]["achievement"], 0)

	# ------------------------------------------------------------
	# achieved
	# ------------------------------------------------------------

	def test_carton_and_nos_converted_to_cartons(self):
		rows = self.rows(group_by=BY_ITEM_GROUP)
		# 10 Ctn + 60% of 400 Nos / 20 - 2 Ctn credit note
		self.assert_row(rows[(self.owais, self.electrodes)], achieved=20)
		self.assert_row(rows[(self.owais, self.wires)], achieved=3)

	def test_shared_invoice_split_by_allocation(self):
		rows = self.rows()
		self.assert_row(rows[self.faisal], achieved=10)  # 40% of (20 + 5)
		self.assert_row(rows[self.owais], achieved=23)

	def test_credit_note_is_negative(self):
		before = self.rows(to_date="2099-11-24")[self.owais]
		after = self.rows()[self.owais]
		self.assertAlmostEqual(after["achieved_qty"] - before["achieved_qty"], -2)
		self.assertAlmostEqual(after["invoiced_amount"] - before["invoiced_amount"], -2400)

	def test_draft_cancelled_and_out_of_range_excluded(self):
		self.assert_row(self.rows()["total"], achieved=39, invoiced=47100)
		self.assert_row(self.rows(to_date="2099-12-01")["total"], achieved=48)

	def test_item_without_carton_uom(self):
		columns, data = self.run_report()
		self.assertIn("unconverted_qty", [c["fieldname"] for c in columns])
		faisal = next(r for r in data if r.get("sales_person") == self.faisal)
		self.assertAlmostEqual(faisal["unconverted_qty"], 30)
		self.assertAlmostEqual(faisal["achieved_qty"], 10)  # Nos never mixed into cartons

		columns, _data = self.run_report(sales_person=self.owais)
		self.assertNotIn("unconverted_qty", [c["fieldname"] for c in columns])

	# ------------------------------------------------------------
	# item groups
	# ------------------------------------------------------------

	def test_item_group_rows_and_subtotals(self):
		data = self.run_report(group_by=BY_ITEM_GROUP)[1]
		subtotal = next(
			r
			for r in data
			if r["row_type"] == "sales_person_total" and r["sales_person"].startswith(self.owais)
		)
		self.assert_row(subtotal, target=130, achieved=23, invoiced=27000, outstanding=15000)
		self.assertEqual(subtotal["bold"], 1)

	def test_untargeted_item_group_has_zero_target(self):
		rows = self.rows(group_by=BY_ITEM_GROUP)
		wires = rows[(self.bilal, self.wires)]
		self.assert_row(wires, target=0, achieved=1)
		self.assertIsNone(wires["achievement"])

	def test_target_without_item_group_covers_all_groups(self):
		rows = self.rows(group_by=BY_ITEM_GROUP)
		self.assert_row(rows[(self.faisal, self.root_group)], target=50, achieved=10)
		self.assertFalse(
			[k for k in rows if isinstance(k, tuple) and k[0] == self.faisal and k[1] != self.root_group]
		)

	def test_parent_group_target_includes_child_groups(self):
		detail = frappe.db.get_value("Target Detail", {"parent": self.bilal}, "name")
		frappe.db.set_value("Target Detail", detail, "item_group", self.products)
		try:
			rows = self.rows(group_by=BY_ITEM_GROUP)
			self.assert_row(rows[(self.bilal, self.products)], target=20, achieved=6)
			self.assertNotIn((self.bilal, self.wires), rows)
		finally:
			frappe.db.set_value("Target Detail", detail, "item_group", self.electrodes)

	def test_filter_item_group(self):
		rows = self.rows(item_group=self.wires)
		self.assert_row(rows[self.owais], target=10, achieved=3)
		# Faisal's all-groups target can't be split to Wires, so only his sales show.
		self.assert_row(rows[self.faisal], target=0, achieved=2)
		self.assert_row(rows["total"], target=10, achieved=6)

	# ------------------------------------------------------------
	# amounts and remarks
	# ------------------------------------------------------------

	def test_amounts_and_remarks(self):
		rows = self.rows()
		self.assert_row(rows[self.bilal], invoiced=7000, outstanding=0, remarks="Received")
		self.assert_row(rows[self.faisal], invoiced=13100, outstanding=12600, remarks="Partially Received")
		self.assert_row(rows[self.owais], invoiced=27000, outstanding=15000, remarks="Partially Received")

	def test_not_received(self):
		rows = self.rows(group_by=BY_ITEM_GROUP)
		self.assert_row(
			rows[(self.owais, self.wires)], invoiced=3000, outstanding=3000, remarks="Not Received"
		)

	def test_payment_split_across_item_groups(self):
		rows = self.rows(group_by=BY_ITEM_GROUP)
		# inv2 electrodes are 24000 of 29000; Owais holds 60%.
		self.assert_row(rows[(self.owais, self.electrodes)], invoiced=24000, outstanding=12000)

	# ------------------------------------------------------------
	# total row
	# ------------------------------------------------------------

	def test_total_row(self):
		data = self.run_report()[1]
		total = data[-1]
		self.assertEqual(
			(total["row_type"], total["sales_person"], total["bold"]), ("grand_total", "Total", 1)
		)
		self.assert_row(total, target=200, achieved=39, invoiced=47100, outstanding=27600)
		self.assertAlmostEqual(total["achievement"], 19.5)
		detail = [r for r in data if r["row_type"] == "sales_person"]
		for field in ("target_qty", "achieved_qty", "invoiced_amount", "outstanding_amount"):
			self.assertAlmostEqual(sum(r[field] for r in detail), total[field], places=4)

	def test_grouped_total_matches_ungrouped(self):
		plain = self.rows()["total"]
		grouped = self.rows(group_by=BY_ITEM_GROUP)["total"]
		for field in ("target_qty", "achieved_qty", "invoiced_amount", "outstanding_amount"):
			self.assertAlmostEqual(plain[field], grouped[field], places=4)

	def test_targets_without_sales(self):
		# Targets are not per territory: they stay while achieved follows the filter.
		rows = self.rows(territory=self.north, item_group=self.wires)
		self.assertEqual(set(rows), {self.owais, "total"})
		self.assert_row(rows[self.owais], target=10, achieved=0, remarks="")

	def test_empty_result(self):
		# No fiscal year (so no targets) and no invoices.
		self.assertEqual(self.run_report(from_date="2199-01-01", to_date="2199-01-31")[1], [])

	# ------------------------------------------------------------
	# filters
	# ------------------------------------------------------------

	def test_filter_sales_person(self):
		rows = self.rows(sales_person=self.owais)
		self.assertEqual(set(rows), {self.owais, "total"})
		self.assert_row(rows["total"], target=130, achieved=23)

	def test_filter_sales_person_group_includes_members(self):
		self.assert_row(self.rows(sales_person=self.sp_group)["total"], target=200, achieved=39)

	def test_filter_territory(self):
		rows = self.rows(territory=self.south)
		self.assert_row(rows[self.faisal], achieved=10, invoiced=11600)  # inv3 is North
		self.assertEqual(rows[self.faisal]["unconverted_qty"], 0)
		self.assert_row(self.rows(territory=self.region)["total"], achieved=39)

	def test_filter_fiscal_year(self):
		self.assert_row(self.rows(fiscal_year=self.fiscal_year)["total"], target=200)
		with self.assertRaises(frappe.ValidationError):
			self.run_report(fiscal_year=self.fiscal_year, from_date="2098-12-31")

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
		report = frappe.get_doc("Report", "Sales Person Target Achievement")
		self.assertEqual(
			(report.report_type, report.ref_doctype, report.module, report.is_standard),
			("Script Report", "Item Group", "PC Production", "Yes"),
		)
		# Open to every desk user.
		self.assertEqual(report.roles, [])

	def test_run_through_query_report_api(self):
		from frappe.desk.query_report import run

		result = run(
			"Sales Person Target Achievement",
			filters={"company": self.company, "from_date": FROM_DATE, "to_date": TO_DATE},
		)
		self.assertAlmostEqual(result["result"][-1]["achieved_qty"], 39)

	def test_desk_user_without_sales_permissions(self):
		from frappe.desk.query_report import get_script, run

		from pc_production.pc_production.report.sales_person_target_achievement.sales_person_target_achievement import (
			get_filter_options,
			get_fiscal_year_dates,
		)

		# A desk user with an unrelated role: no permission on Sales Invoice or Sales Person.
		# (A user with no roles at all becomes a Website User and has no desk access.)
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": "spta-test-noaccess@example.com",
				"first_name": PREFIX,
				"send_welcome_email": 0,
			}
		).insert()
		user.add_roles("Stock User")
		filters = {
			"company": self.company,
			"from_date": FROM_DATE,
			"to_date": TO_DATE,
			"sales_person": self.sp_group,
			"territory": self.region,
			"fiscal_year": self.fiscal_year,
		}

		frappe.set_user(user.name)
		try:
			self.assertFalse(frappe.has_permission("Sales Invoice", "read"))
			self.assertFalse(frappe.has_permission("Sales Person", "read"))
			self.assertTrue(get_script("Sales Person Target Achievement"))
			result = run("Sales Person Target Achievement", filters=filters)
			self.assertAlmostEqual(result["result"][-1]["achieved_qty"], 39)

			self.assertIn(self.owais, get_filter_options("Sales Person", txt="Owais"))
			self.assertIn(self.south, get_filter_options("Territory", txt=PREFIX))
			self.assertIn(self.fiscal_year, get_filter_options("Fiscal Year"))
			self.assertEqual(str(get_fiscal_year_dates(self.fiscal_year)["year_start_date"]), "2099-01-01")
			with self.assertRaises(frappe.PermissionError):
				get_filter_options("Sales Invoice")
		finally:
			frappe.set_user("Administrator")


def make_item_group(name, parent, is_group=0):
	return (
		frappe.get_doc(
			{
				"doctype": "Item Group",
				"item_group_name": name,
				"parent_item_group": parent,
				"is_group": is_group,
			}
		)
		.insert()
		.name
	)


def make_item(code, item_group, carton_factor, company, cost_center):
	item = frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": code,
			"item_name": code,
			"item_group": item_group,
			"stock_uom": "Nos",
			"is_stock_item": 0,
			# Item Default cost centers are mandatory on this site.
			"item_defaults": [
				{"company": company, "buying_cost_center": cost_center, "selling_cost_center": cost_center}
			],
		}
	)
	if carton_factor:
		item.append("uoms", {"uom": "Carton", "conversion_factor": carton_factor})
	return item.insert().name


def make_distribution(name, november):
	"""Monthly Distribution with the given November percentage, the rest spread evenly."""
	dist = frappe.new_doc("Monthly Distribution")
	dist.distribution_id = name
	dist.set("percentages", [])
	others = round((100 - november) / 11, 6)
	for month in MONTHS:
		pct = november if month == "November" else others
		if month == "December":
			pct = round(100 - november - others * 10, 6)
		dist.append("percentages", {"month": month, "percentage_allocation": pct})
	return dist.insert().name


def set_targets(sales_person, targets, fiscal_year):
	doc = frappe.get_doc("Sales Person", sales_person)
	for item_group, qty, distribution in targets:
		doc.append(
			"targets",
			{
				"item_group": item_group,
				"fiscal_year": fiscal_year,
				"target_qty": qty,
				"distribution_id": distribution,
			},
		)
	doc.save()
