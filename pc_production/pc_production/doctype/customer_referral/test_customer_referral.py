# Copyright (c) 2026, TRPL Solutions and contributors
# For license information, please see license.txt

import frappe
from erpnext.stock.doctype.item.test_item import make_item
from erpnext.stock.get_item_details import get_item_details
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, nowdate

# ERPNext's auto-generated test records for these link targets pull in a
# dependency chain (Customer -> Territory -> Target Detail -> Monthly
# Distribution) that fails on a fresh site. The tests create their own
# Customers, Items and UOMs, and use the site's default company instead.
test_ignore = ["Company", "Customer", "Item", "UOM", "Pricing Rule"]

PRICE_LIST = "_Test Referral Selling"
ITEM = "_Test Referral Item"
CARTON_FACTOR = 12
NOS_PRICE = 100
CARTON_PRICE = 1200

REFERRER = "_Test Referral Referrer"
REFERRED = "_Test Referral Referred"
REFERRED_2 = "_Test Referral Referred 2"
OTHER_REFERRER = "_Test Referral Other Referrer"


class TestCustomerReferral(FrappeTestCase):
	def setUp(self):
		for uom in ("Carton", "Nos"):
			if not frappe.db.exists("UOM", uom):
				frappe.get_doc({"doctype": "UOM", "uom_name": uom}).insert()

		for customer in (REFERRER, REFERRED, REFERRED_2, OTHER_REFERRER):
			make_customer(customer)

		self.company = get_test_company()
		self.currency = frappe.get_cached_value("Company", self.company, "default_currency")
		if not frappe.db.exists("Price List", PRICE_LIST):
			frappe.get_doc(
				{
					"doctype": "Price List",
					"price_list_name": PRICE_LIST,
					"selling": 1,
					"currency": self.currency,
					"enabled": 1,
				}
			).insert()

		make_item(
			ITEM,
			{
				"stock_uom": "Nos",
				"is_sales_item": 1,
				"is_stock_item": 0,
				"uoms": [{"uom": "Carton", "conversion_factor": CARTON_FACTOR}],
			},
		)
		make_item_price(ITEM, "Nos", NOS_PRICE)
		make_item_price(ITEM, "Carton", CARTON_PRICE)

	def tearDown(self):
		frappe.db.rollback()

	# ---------------------------------------------------------------
	# Pricing Rule behaviour
	# ---------------------------------------------------------------

	def test_submit_creates_pricing_rule(self):
		doc = make_referral(discount_amount=50)

		rule_name = doc.items[0].pricing_rule
		self.assertTrue(rule_name)

		rule = frappe.get_doc("Pricing Rule", rule_name)
		self.assertEqual(rule.customer, REFERRER)
		self.assertEqual(rule.applicable_for, "Customer")
		self.assertEqual(rule.rate_or_discount, "Discount Amount")
		self.assertEqual(rule.discount_amount, 50)
		self.assertEqual(rule.selling, 1)
		self.assertEqual(rule.buying, 0)
		self.assertEqual(rule.company, self.company)
		self.assertEqual(rule.currency, self.currency)
		self.assertEqual(rule.custom_customer_referral, doc.name)
		self.assertEqual(len(rule.items), 1)
		self.assertEqual(rule.items[0].item_code, ITEM)
		self.assertEqual(rule.items[0].uom, "Carton")

	def test_discount_applies_only_to_referrer_in_carton(self):
		make_referral(discount_amount=50)

		carton = self.get_details(REFERRER, "Carton")
		self.assertEqual(carton.price_list_rate, CARTON_PRICE)
		self.assertEqual(carton.discount_amount, 50)

		nos = self.get_details(REFERRER, "Nos")
		self.assertEqual(nos.price_list_rate, NOS_PRICE)
		self.assertEqual(nos.get("discount_amount") or 0, 0)

		referred = self.get_details(REFERRED, "Carton")
		self.assertEqual(referred.get("discount_amount") or 0, 0)

	def test_rate_type(self):
		# a stale discount_amount on the row must be cleared, not sent to the Pricing Rule
		doc = make_referral(item_row={"rate_or_discount": "Rate", "rate": 1100, "discount_amount": 50})
		row = doc.items[0]
		self.assertEqual(row.discount_amount, 0)
		self.assertEqual(row.discount_percentage, 0)

		rule = frappe.get_doc("Pricing Rule", row.pricing_rule)
		self.assertEqual(rule.rate_or_discount, "Rate")
		self.assertEqual(rule.rate, 1100)
		self.assertEqual(rule.discount_amount, 0)

		carton = self.get_details(REFERRER, "Carton")
		self.assertEqual(effective_rate(carton), 1100)
		self.assertEqual(effective_rate(self.get_details(REFERRER, "Nos")), NOS_PRICE)
		self.assertEqual(effective_rate(self.get_details(REFERRED, "Carton")), CARTON_PRICE)

	def test_discount_percentage_type(self):
		doc = make_referral(item_row={"rate_or_discount": "Discount Percentage", "discount_percentage": 5})
		row = doc.items[0]
		self.assertEqual(row.discount_amount, 0)

		rule = frappe.get_doc("Pricing Rule", row.pricing_rule)
		self.assertEqual(rule.rate_or_discount, "Discount Percentage")
		self.assertEqual(rule.discount_percentage, 5)

		carton = self.get_details(REFERRER, "Carton")
		self.assertEqual(carton.discount_percentage, 5)
		self.assertEqual(effective_rate(carton), 1140)
		self.assertEqual(effective_rate(self.get_details(REFERRER, "Nos")), NOS_PRICE)

	def test_discount_percentage_over_100(self):
		doc = make_referral(
			do_not_save=True, item_row={"rate_or_discount": "Discount Percentage", "discount_percentage": 101}
		)
		self.assertRaisesRegex(frappe.ValidationError, "cannot be more than 100", doc.insert)

	def test_missing_value_for_chosen_type(self):
		# discount_amount is filled, but the chosen type needs a different field
		for rate_or_discount in ("Rate", "Discount Percentage"):
			doc = make_referral(do_not_save=True, item_row={"rate_or_discount": rate_or_discount})
			self.assertRaisesRegex(frappe.ValidationError, "must be greater than zero", doc.insert)

	def test_empty_rate_or_discount_means_discount_amount(self):
		# rows created before the field existed have no rate_or_discount
		doc = make_referral(item_row={"rate_or_discount": None})
		self.assertEqual(doc.items[0].rate_or_discount, "Discount Amount")

		rule = frappe.get_doc("Pricing Rule", doc.items[0].pricing_rule)
		self.assertEqual(rule.rate_or_discount, "Discount Amount")
		self.assertEqual(rule.discount_amount, 50)
		self.assertEqual(effective_rate(self.get_details(REFERRER, "Carton")), 1150)

	def test_cancel_disables_rule_and_amend_applies_new_amount(self):
		doc = make_referral(discount_amount=50)
		old_rule = doc.items[0].pricing_rule

		doc.cancel()
		self.assertEqual(frappe.db.get_value("Pricing Rule", old_rule, "disable"), 1)
		self.assertTrue(frappe.db.exists("Pricing Rule", old_rule))
		self.assertEqual(self.get_details(REFERRER, "Carton").get("discount_amount") or 0, 0)

		amended = frappe.copy_doc(doc)
		amended.docstatus = 0
		amended.amended_from = doc.name
		amended.items[0].discount_amount = 80
		amended.insert()
		amended.submit()

		new_rule = amended.items[0].pricing_rule
		self.assertTrue(new_rule)
		self.assertNotEqual(new_rule, old_rule)
		self.assertEqual(self.get_details(REFERRER, "Carton").discount_amount, 80)

	# ---------------------------------------------------------------
	# Validations
	# ---------------------------------------------------------------

	def test_valid_upto_before_valid_from(self):
		doc = make_referral(do_not_save=True, valid_upto=add_days(nowdate(), -1))
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_no_referred_customers(self):
		doc = make_referral(do_not_save=True)
		doc.referred_customers = []
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_referrer_cannot_refer_self(self):
		doc = make_referral(do_not_save=True, referred=[REFERRER])
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_duplicate_referred_customer(self):
		doc = make_referral(do_not_save=True, referred=[REFERRED, REFERRED])
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_referred_by_different_referrer(self):
		make_referral(referred=[REFERRED])
		doc = make_referral(do_not_save=True, customer=OTHER_REFERRER, referred=[REFERRED])
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_circular_referral(self):
		first = make_referral(customer=REFERRER, referred=[REFERRED])

		# REFERRED cannot turn around and refer REFERRER
		doc = make_referral(do_not_save=True, customer=REFERRED, referred=[REFERRER])
		self.assertRaisesRegex(
			frappe.ValidationError,
			f"Circular referral: .*{REFERRER}.* already referred .*{REFERRED}.* in .*{first.name}",
			doc.insert,
		)

		# only submitted referrals count: once the first one is cancelled it is allowed
		first.cancel()
		doc = make_referral(customer=REFERRED, referred=[REFERRER])
		self.assertEqual(doc.docstatus, 1)

	def test_no_items(self):
		doc = make_referral(do_not_save=True)
		doc.items = []
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_duplicate_item_uom(self):
		doc = make_referral(do_not_save=True)
		doc.append("items", {"item_code": ITEM, "uom": "Carton", "discount_amount": 10})
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_discount_must_be_positive(self):
		for amount in (0, -5):
			doc = make_referral(do_not_save=True, discount_amount=amount)
			self.assertRaises(frappe.ValidationError, doc.insert)

	def test_item_must_be_enabled_sales_item(self):
		make_item("_Test Referral Non Sales Item", {"stock_uom": "Nos", "is_sales_item": 0})
		doc = make_referral(do_not_save=True, item_code="_Test Referral Non Sales Item", uom="Nos")
		self.assertRaises(frappe.ValidationError, doc.insert)

		make_item("_Test Referral Disabled Item", {"stock_uom": "Nos", "is_sales_item": 1})
		frappe.db.set_value("Item", "_Test Referral Disabled Item", "disabled", 1)
		doc = make_referral(do_not_save=True, item_code="_Test Referral Disabled Item", uom="Nos")
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_uom_must_belong_to_item(self):
		make_item("_Test Referral Nos Only Item", {"stock_uom": "Nos", "is_sales_item": 1})
		doc = make_referral(do_not_save=True, item_code="_Test Referral Nos Only Item", uom="Carton")
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_overlapping_referral(self):
		# open-ended referral overlaps anything after its start
		make_referral(referred=[REFERRED])
		doc = make_referral(
			do_not_save=True,
			referred=[REFERRED_2],
			valid_from=add_days(nowdate(), 30),
			valid_upto=add_days(nowdate(), 60),
		)
		self.assertRaises(frappe.ValidationError, doc.insert)

	def test_overlapping_bounded_referrals(self):
		make_referral(referred=[REFERRED], valid_upto=add_days(nowdate(), 10))

		# overlaps on the last day of the first referral
		doc = make_referral(do_not_save=True, referred=[REFERRED_2], valid_from=add_days(nowdate(), 10))
		self.assertRaises(frappe.ValidationError, doc.insert)

		# starts after the first one ends: allowed
		make_referral(referred=[REFERRED_2], valid_from=add_days(nowdate(), 11))

	# ---------------------------------------------------------------
	# Helpers
	# ---------------------------------------------------------------

	def get_details(self, customer, uom):
		return get_item_details(
			{
				"item_code": ITEM,
				"company": self.company,
				"customer": customer,
				"doctype": "Sales Invoice",
				"name": None,
				"currency": self.currency,
				"conversion_rate": 1,
				"price_list": PRICE_LIST,
				"selling_price_list": PRICE_LIST,
				"price_list_currency": self.currency,
				"plc_conversion_rate": 1,
				"transaction_date": nowdate(),
				"posting_date": nowdate(),
				"uom": uom,
				"stock_uom": "Nos",
				"conversion_factor": CARTON_FACTOR if uom == "Carton" else 1,
				"qty": 1,
			}
		)


def get_test_company():
	company = frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")
	if not company:
		raise AssertionError("Customer Referral tests need at least one Company on the test site.")
	return company


def effective_rate(details):
	"""Line rate a Sales Order would get from these item details."""
	return flt(details.price_list_rate) - flt(details.get("discount_amount"))


def make_customer(name):
	if frappe.db.exists("Customer", name):
		return
	frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": name,
			"customer_type": "Company",
			"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
			"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
		}
	).insert()


def make_item_price(item_code, uom, rate):
	if frappe.db.exists("Item Price", {"item_code": item_code, "price_list": PRICE_LIST, "uom": uom}):
		return
	frappe.get_doc(
		{
			"doctype": "Item Price",
			"item_code": item_code,
			"price_list": PRICE_LIST,
			"uom": uom,
			"price_list_rate": rate,
		}
	).insert()


def make_referral(
	customer=REFERRER,
	referred=None,
	item_code=ITEM,
	uom="Carton",
	discount_amount=50,
	valid_from=None,
	valid_upto=None,
	do_not_save=False,
	item_row=None,
):
	doc = frappe.get_doc(
		{
			"doctype": "Customer Referral",
			"customer": customer,
			"company": get_test_company(),
			"valid_from": valid_from or nowdate(),
			"valid_upto": valid_upto,
			"priority": "1",
			"referred_customers": [{"referred_customer": c} for c in (referred or [REFERRED])],
			"items": [
				{"item_code": item_code, "uom": uom, "discount_amount": discount_amount, **(item_row or {})}
			],
		}
	)
	if not do_not_save:
		doc.insert()
		doc.submit()
	return doc
