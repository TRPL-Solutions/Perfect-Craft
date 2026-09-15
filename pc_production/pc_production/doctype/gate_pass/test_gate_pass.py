# Copyright (c) 2026, TRPL Solutions and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestGatePass(FrappeTestCase):
	def setUp(self):
		self.company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
			"Company", {}, "name"
		)
		self.transporter = self.make_transporter("_Test Transporter")

	def tearDown(self):
		frappe.db.rollback()

	def make_transporter(self, name):
		if frappe.db.exists("Supplier", name):
			return name
		supplier = frappe.get_doc(
			{
				"doctype": "Supplier",
				"supplier_name": name,
				"supplier_group": frappe.db.get_value("Supplier Group", {}, "name"),
				"is_transporter": 1,
			}
		)
		supplier.insert(ignore_permissions=True)
		return supplier.name

	def make_gate_pass(self, delivery_charges=1500):
		gp = frappe.get_doc(
			{
				"doctype": "Gate Pass",
				"date": frappe.utils.today(),
				"type": "General Items",
				"return_type": "Non-Returnable",
				"gate_pass_type": "External",
				"gate_pass_for": "Out",
				"company": self.company,
				"created_by": frappe.session.user,
				"verified_by": "Test Verifier",
				"transporter": self.transporter,
				"delivery_charges": delivery_charges,
				"items": [
					{
						"type_of_product": "Non-Inventory",
						"type": "Product",
						"qty": 1,
						"item_name": "Test Item",
					}
				],
			}
		)
		gp.insert(ignore_permissions=True)
		return gp

	def test_purchase_invoice_created_on_submit(self):
		gp = self.make_gate_pass()
		gp.submit()
		gp.reload()

		self.assertTrue(gp.purchase_invoice)
		pi = frappe.get_doc("Purchase Invoice", gp.purchase_invoice)
		self.assertEqual(pi.supplier, self.transporter)
		self.assertEqual(pi.docstatus, 1)
		self.assertEqual(len(pi.items), 1)
		self.assertEqual(pi.items[0].qty, 1)
		self.assertEqual(pi.items[0].rate, 1500)

	def test_no_duplicate_purchase_invoice(self):
		gp = self.make_gate_pass()
		gp.submit()
		gp.reload()
		first_pi = gp.purchase_invoice

		# Re-invoking the creation routine should not create a second PI.
		gp.create_transport_purchase_invoice()
		gp.reload()
		self.assertEqual(gp.purchase_invoice, first_pi)

	def test_purchase_invoice_cancelled_on_gate_pass_cancel(self):
		gp = self.make_gate_pass()
		gp.submit()
		gp.reload()
		pi_name = gp.purchase_invoice

		gp.cancel()
		pi = frappe.get_doc("Purchase Invoice", pi_name)
		self.assertEqual(pi.docstatus, 2)

	def test_purchase_invoice_deleted_after_gate_pass_deleted(self):
		gp = self.make_gate_pass()
		gp.submit()
		gp.reload()
		pi_name = gp.purchase_invoice

		gp.cancel()
		frappe.delete_doc("Gate Pass", gp.name, force=True)

		self.assertFalse(frappe.db.exists("Purchase Invoice", pi_name))

	def test_no_purchase_invoice_without_transporter(self):
		gp = self.make_gate_pass()
		gp.transporter = None
		gp.delivery_charges = 0
		gp.save()
		gp.submit()
		gp.reload()

		self.assertFalse(gp.purchase_invoice)
