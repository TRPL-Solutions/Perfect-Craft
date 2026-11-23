# Copyright (c) 2026, TRPL Solutions and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder import Criterion
from frappe.utils import flt, get_link_to_form, getdate

PRICING_RULE_LINK_FIELD = "custom_customer_referral"
DEFAULT_RATE_OR_DISCOUNT = "Discount Amount"

# rate_or_discount option -> the value field it uses (same fieldnames on Pricing Rule)
VALUE_FIELD_BY_TYPE = {
	"Rate": "rate",
	"Discount Percentage": "discount_percentage",
	"Discount Amount": "discount_amount",
}


class CustomerReferral(Document):
	def before_validate(self):
		if not self.company:
			self.company = frappe.defaults.get_user_default("Company")

		# rows saved before rate_or_discount existed were always "Discount Amount"
		for row in self.items:
			if not row.rate_or_discount:
				row.rate_or_discount = DEFAULT_RATE_OR_DISCOUNT

	def validate(self):
		self.validate_dates()
		self.validate_referred_customers()
		self.validate_items()
		self.validate_overlapping_referral()

	def on_submit(self):
		self.create_pricing_rules()

	def on_cancel(self):
		self.disable_pricing_rules()

	# ---------------------------------------------------------------
	# Validations
	# ---------------------------------------------------------------

	def validate_dates(self):
		if self.valid_upto and getdate(self.valid_upto) < getdate(self.valid_from):
			frappe.throw(_("Valid Upto date cannot be before Valid From date."))

	def validate_referred_customers(self):
		if not self.referred_customers:
			frappe.throw(_("Please add at least one Referred Customer."))

		seen = set()
		for row in self.referred_customers:
			if row.referred_customer == self.customer:
				frappe.throw(
					_("Row #{0}: Referrer {1} cannot refer themselves.").format(
						row.idx, frappe.bold(self.customer)
					)
				)

			if row.referred_customer in seen:
				frappe.throw(
					_("Row #{0}: Referred Customer {1} is entered more than once.").format(
						row.idx, frappe.bold(row.referred_customer)
					)
				)
			seen.add(row.referred_customer)

		self.validate_referred_by_other_referrer(seen)
		self.validate_circular_referral(seen)

	def validate_circular_referral(self, referred_customers):
		"""Block X -> Y when a submitted referral already has Y -> X."""
		parent = frappe.qb.DocType("Customer Referral")
		child = frappe.qb.DocType("Customer Referral Customer")

		circular = (
			frappe.qb.from_(child)
			.join(parent)
			.on(child.parent == parent.name)
			.select(parent.name, parent.customer)
			.where(
				(parent.docstatus == 1)
				& (parent.name != self.name)
				& (child.parenttype == "Customer Referral")
				& (parent.customer.isin(list(referred_customers)))
				& (child.referred_customer == self.customer)
			)
			.limit(1)
			.run(as_dict=True)
		)

		if circular:
			row = circular[0]
			frappe.throw(
				_("Circular referral: {0} already referred {1} in {2}.").format(
					frappe.bold(row.customer),
					frappe.bold(self.customer),
					get_link_to_form("Customer Referral", row.name),
				)
			)

	def validate_referred_by_other_referrer(self, referred_customers):
		parent = frappe.qb.DocType("Customer Referral")
		child = frappe.qb.DocType("Customer Referral Customer")

		existing = (
			frappe.qb.from_(child)
			.join(parent)
			.on(child.parent == parent.name)
			.select(child.referred_customer, parent.name, parent.customer)
			.where(
				(parent.docstatus == 1)
				& (parent.customer != self.customer)
				& (parent.name != self.name)
				& (child.parenttype == "Customer Referral")
				& (child.referred_customer.isin(list(referred_customers)))
			)
			.run(as_dict=True)
		)

		if existing:
			row = existing[0]
			frappe.throw(
				_("Customer {0} has already been referred by {1} in {2}.").format(
					frappe.bold(row.referred_customer),
					frappe.bold(row.customer),
					get_link_to_form("Customer Referral", row.name),
				)
			)

	def validate_items(self):
		if not self.items:
			frappe.throw(_("Please add at least one Item."))

		seen = set()
		for row in self.items:
			key = (row.item_code, row.uom)
			if key in seen:
				frappe.throw(
					_("Row #{0}: Item {1} with UOM {2} is entered more than once.").format(
						row.idx, frappe.bold(row.item_code), frappe.bold(row.uom)
					)
				)
			seen.add(key)

			self.validate_rate_or_discount(row)
			self.validate_item(row)

	def validate_rate_or_discount(self, row):
		value_field = VALUE_FIELD_BY_TYPE.get(row.rate_or_discount)
		if not value_field:
			frappe.throw(
				_("Row #{0}: Invalid Rate or Discount {1}.").format(
					row.idx, frappe.bold(row.rate_or_discount)
				)
			)

		label = _(row.meta.get_label(value_field))
		if flt(row.get(value_field)) <= 0:
			frappe.throw(_("Row #{0}: {1} must be greater than zero.").format(row.idx, frappe.bold(label)))

		if value_field == "discount_percentage" and flt(row.discount_percentage) > 100:
			frappe.throw(_("Row #{0}: {1} cannot be more than 100.").format(row.idx, frappe.bold(label)))

		# clear the unused value fields so stale values are not saved
		for other_field in VALUE_FIELD_BY_TYPE.values():
			if other_field != value_field:
				row.set(other_field, 0)

	def validate_item(self, row):
		item = frappe.db.get_value(
			"Item", row.item_code, ["disabled", "is_sales_item", "stock_uom"], as_dict=True
		)
		if not item:
			frappe.throw(_("Row #{0}: Item {1} does not exist.").format(row.idx, frappe.bold(row.item_code)))

		if item.disabled or not item.is_sales_item:
			frappe.throw(
				_("Row #{0}: Item {1} must be enabled and be a Sales Item.").format(
					row.idx, frappe.bold(row.item_code)
				)
			)

		if row.uom != item.stock_uom and not frappe.db.exists(
			"UOM Conversion Detail",
			{"parenttype": "Item", "parent": row.item_code, "uom": row.uom},
		):
			frappe.throw(
				_(
					"Row #{0}: UOM {1} is not the stock UOM of Item {2} and has no conversion factor in the Item's UOM table."
				).format(row.idx, frappe.bold(row.uom), frappe.bold(row.item_code))
			)

	def validate_overlapping_referral(self):
		ref = frappe.qb.DocType("Customer Referral")
		conditions = [
			ref.docstatus == 1,
			ref.customer == self.customer,
			ref.company == self.company,
			ref.name != self.name,
			# existing range ends on/after our start (empty valid_upto = open ended)
			ref.valid_upto.isnull() | (ref.valid_upto >= self.valid_from),
		]
		if self.valid_upto:
			# existing range starts on/before our end
			conditions.append(ref.valid_from <= self.valid_upto)

		overlap = frappe.qb.from_(ref).select(ref.name).where(Criterion.all(conditions)).limit(1).run()
		if overlap:
			frappe.throw(
				_(
					"Customer {0} already has a submitted Customer Referral {1} overlapping this period."
				).format(frappe.bold(self.customer), get_link_to_form("Customer Referral", overlap[0][0]))
			)

	# ---------------------------------------------------------------
	# Pricing Rules
	# ---------------------------------------------------------------

	def create_pricing_rules(self):
		currency = frappe.get_cached_value("Company", self.company, "default_currency")

		for row in self.items:
			rate_or_discount = row.rate_or_discount or DEFAULT_RATE_OR_DISCOUNT
			value_field = VALUE_FIELD_BY_TYPE[rate_or_discount]
			pricing_rule = frappe.get_doc(
				{
					"doctype": "Pricing Rule",
					"title": _("Referral {0} - {1} ({2})").format(self.name, row.item_code, row.uom),
					"apply_on": "Item Code",
					"price_or_product_discount": "Price",
					"selling": 1,
					"buying": 0,
					"applicable_for": "Customer",
					"customer": self.customer,
					"company": self.company,
					"currency": currency,
					"valid_from": self.valid_from,
					"valid_upto": self.valid_upto,
					"rate_or_discount": rate_or_discount,
					value_field: row.get(value_field),
					"priority": self.priority,
					PRICING_RULE_LINK_FIELD: self.name,
					"items": [{"item_code": row.item_code, "uom": row.uom}],
				}
			)
			pricing_rule.insert(ignore_permissions=True)
			row.db_set("pricing_rule", pricing_rule.name)

	def disable_pricing_rules(self):
		for name in frappe.get_all(
			"Pricing Rule", filters={PRICING_RULE_LINK_FIELD: self.name}, pluck="name"
		):
			pricing_rule = frappe.get_doc("Pricing Rule", name)
			if not pricing_rule.disable:
				pricing_rule.disable = 1
				pricing_rule.save(ignore_permissions=True)
