# Copyright (c) 2026, TRPL Solutions and Contributors
# See license.txt

import frappe

from frappe.tests.utils import FrappeTestCase


class TestGatePass(FrappeTestCase):

	def setUp(self):

		self.company = (
			frappe.db.get_single_value(
				"Global Defaults",
				"default_company"
			)
			or frappe.db.get_value(
				"Company",
				{},
				"name"
			)
		)

		self.transporter = self.make_transporter(
			"_Test Transporter"
		)

		self.uom = (
			"Nos"
			if frappe.db.exists("UOM", "Nos")
			else frappe.db.get_value(
				"UOM",
				{},
				"name"
			)
		)


	def tearDown(self):

		frappe.db.rollback()


	def make_transporter(self, name):

		if frappe.db.exists(
			"Supplier",
			name
		):
			return name

		supplier_group = frappe.db.get_value(
			"Supplier Group",
			{},
			"name"
		)

		supplier = frappe.get_doc(
			{
				"doctype": "Supplier",
				"supplier_name": name,
				"supplier_group":
					supplier_group,
				"is_transporter": 1,
			}
		)

		supplier.insert(
			ignore_permissions=True
		)

		return supplier.name


	def make_gate_pass(
		self,
		delivery_charges=1500,
		transporter=None,
		qty1=5,
		qty2=3,
	):

		if transporter is None:
			transporter = self.transporter

		gp = frappe.get_doc(
			{
				"doctype": "Gate Pass",
				"date":
					frappe.utils.today(),
				"type":
					"General Items",
				"return_type":
					"Non-Returnable",
				"gate_pass_type":
					"External",
				"gate_pass_for":
					"Out",
				"company":
					self.company,

				# Created By intentionally NOT provided.
				# It must populate automatically.

				"verified_by":
					"Test Verifier",

				"transporter":
					transporter,

				"delivery_charges":
					delivery_charges,

				"items": [
					{
						"type_of_product":
							"Non-Inventory",
						"type":
							"Product",
						"qty":
							qty1,
						"uom":
							self.uom,
						"item_name":
							"Test Item 1",
					},
					{
						"type_of_product":
							"Non-Inventory",
						"type":
							"Product",
						"qty":
							qty2,
						"uom":
							self.uom,
						"item_name":
							"Test Item 2",
					},
				],
			}
		)

		gp.insert(
			ignore_permissions=True
		)

		return gp


	def test_created_by_automatically_set(self):

		gp = self.make_gate_pass()

		self.assertEqual(
			gp.created_by,
			gp.owner
		)


	def test_total_qty_calculation(self):

		gp = self.make_gate_pass(
			qty1=8,
			qty2=7
		)

		self.assertEqual(
			gp.custom_total_amount,
			15
		)


	def test_draft_purchase_invoice_created(self):

		gp = self.make_gate_pass()

		gp.reload()

		self.assertTrue(
			gp.purchase_invoice
		)

		pi = frappe.get_doc(
			"Purchase Invoice",
			gp.purchase_invoice
		)

		self.assertEqual(
			pi.docstatus,
			0
		)

		self.assertEqual(
			pi.supplier,
			self.transporter
		)

		self.assertEqual(
			pi.custom_gate_pass,
			gp.name
		)


	def test_purchase_invoice_created_and_submitted(self):

		gp = self.make_gate_pass()

		gp.submit()

		gp.reload()

		self.assertTrue(
			gp.purchase_invoice
		)

		pi = frappe.get_doc(
			"Purchase Invoice",
			gp.purchase_invoice
		)

		self.assertEqual(
			pi.supplier,
			self.transporter
		)

		self.assertEqual(
			pi.docstatus,
			1
		)

		self.assertEqual(
			len(pi.items),
			1
		)

		self.assertEqual(
			pi.items[0].qty,
			1
		)

		self.assertEqual(
			pi.items[0].rate,
			1500
		)

		self.assertEqual(
			pi.custom_gate_pass,
			gp.name
		)


	def test_delivery_charge_change_updates_draft_pi(self):

		gp = self.make_gate_pass(
			delivery_charges=1500
		)

		gp.reload()

		pi_name = gp.purchase_invoice

		gp.delivery_charges = 2500

		gp.save()

		pi = frappe.get_doc(
			"Purchase Invoice",
			pi_name
		)

		self.assertEqual(
			pi.docstatus,
			0
		)

		self.assertEqual(
			pi.items[0].rate,
			2500
		)


	def test_no_duplicate_purchase_invoice(self):

		gp = self.make_gate_pass()

		gp.reload()

		first_pi = gp.purchase_invoice

		gp.create_transport_purchase_invoice()

		gp.reload()

		self.assertEqual(
			gp.purchase_invoice,
			first_pi
		)

		count = frappe.db.count(
			"Purchase Invoice",
			{
				"custom_gate_pass":
					gp.name,
				"docstatus":
					["!=", 2],
			},
		)

		self.assertEqual(
			count,
			1
		)


	def test_transporter_required_when_charges_exist(self):

		with self.assertRaises(
			frappe.ValidationError
		):

			self.make_gate_pass(
				delivery_charges=1500,
				transporter=""
			)


	def test_no_pi_when_delivery_charges_zero(self):

		gp = self.make_gate_pass(
			delivery_charges=0
		)

		gp.reload()

		self.assertFalse(
			gp.purchase_invoice
		)


	def test_clearing_draft_charges_removes_draft_pi(self):

		gp = self.make_gate_pass(
			delivery_charges=1500
		)

		gp.reload()

		pi_name = gp.purchase_invoice

		self.assertTrue(
			frappe.db.exists(
				"Purchase Invoice",
				pi_name
			)
		)

		gp.delivery_charges = 0

		gp.save()

		gp.reload()

		self.assertFalse(
			gp.purchase_invoice
		)

		self.assertFalse(
			frappe.db.exists(
				"Purchase Invoice",
				pi_name
			)
		)


	def test_purchase_invoice_cancelled_on_gate_pass_cancel(self):

		gp = self.make_gate_pass()

		gp.submit()

		gp.reload()

		pi_name = gp.purchase_invoice

		gp.cancel()

		pi = frappe.get_doc(
			"Purchase Invoice",
			pi_name
		)

		self.assertEqual(
			pi.docstatus,
			2
		)


	def test_purchase_invoice_deleted_after_gate_pass_deleted(self):

		gp = self.make_gate_pass()

		gp.submit()

		gp.reload()

		pi_name = gp.purchase_invoice

		gp.cancel()

		frappe.delete_doc(
			"Gate Pass",
			gp.name,
			force=True
		)

		self.assertFalse(
			frappe.db.exists(
				"Purchase Invoice",
				pi_name
			)
		)