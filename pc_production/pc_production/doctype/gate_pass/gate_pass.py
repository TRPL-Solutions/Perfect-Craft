# Copyright (c) 2026, TRPL Solutions and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

TRANSPORT_CHARGES_ITEM = "Transport Charges"
TRANSPORT_ITEM_GROUP = "Services"


class GatePass(Document):
	# ------------------------------------------------------------------
	# Standard document events
	# ------------------------------------------------------------------
	def validate(self):
		self.set_total_qty()

	def on_update(self):
		"""On every SAVE (while still a Draft), auto-create / keep in sync
		a DRAFT Purchase Invoice for the Transport Charges."""
		if self.docstatus == 0:
			self.sync_transport_purchase_invoice()

	def on_submit(self):
		"""On SUBMIT of the Gate Pass, submit the already-created draft
		Purchase Invoice (creating it first as a safety net if needed)."""
		self.submit_transport_purchase_invoice()

	def on_cancel(self):
		"""Runs whenever the Gate Pass is cancelled through ANY route
		(custom button, API, bulk cancel, etc). Frappe runs on_cancel()
		BEFORE its internal back-link check, so cancelling the Purchase
		Invoice here lets the Gate Pass cancellation go through cleanly."""
		self.cancel_linked_purchase_invoice()

	def on_trash(self):
		"""A Gate Pass can only be deleted once it is Draft or Cancelled.
		When deleted, automatically delete the linked Purchase Invoice too
		(cancelling it first if it was somehow still submitted)."""
		self.delete_linked_purchase_invoice()

	# ------------------------------------------------------------------
	# Helpers
	# ------------------------------------------------------------------
	def set_total_qty(self):
		self.custom_total_amount = sum(flt(row.qty) for row in self.items)

	# ------------------------------------------------------------------
	# Purchase Invoice automation
	# ------------------------------------------------------------------
	def sync_transport_purchase_invoice(self):
		if not self.transporter or not flt(self.delivery_charges):
			return
		if self.purchase_invoice:
			self.update_existing_purchase_invoice()
		else:
			self.create_transport_purchase_invoice()

	def create_transport_purchase_invoice(self):
		if self.purchase_invoice:
			return

		existing_pi = frappe.db.get_value(
			"Purchase Invoice",
			{"custom_gate_pass": self.name, "docstatus": ["!=", 2]},
			"name",
		)
		if existing_pi:

			self.purchase_invoice = existing_pi
			self.db_set("purchase_invoice", existing_pi, update_modified=False)
			return

		item_code = self.get_or_create_transport_charges_item()

		pi = frappe.new_doc("Purchase Invoice")
		pi.company = self.company
		pi.supplier = self.transporter
		pi.custom_gate_pass = self.name
		pi.remarks = _("Auto-created against Gate Pass {0}").format(self.name)

		pi.append(
			"items",
			{
				"item_code": item_code,
				"item_name": TRANSPORT_CHARGES_ITEM,
				"description": TRANSPORT_CHARGES_ITEM,
				"qty": 1,
				"rate": flt(self.delivery_charges),
			},
		)

		pi.set_missing_values()
		pi.flags.ignore_permissions = True
		pi.insert(ignore_permissions=True)  # saved as DRAFT only, not submitted

		self.purchase_invoice = pi.name
		self.db_set("purchase_invoice", pi.name, update_modified=False)

	def update_existing_purchase_invoice(self):
		if not frappe.db.exists("Purchase Invoice", self.purchase_invoice):
			self.db_set("purchase_invoice", None, update_modified=False)
			self.create_transport_purchase_invoice()
			return

		pi = frappe.get_doc("Purchase Invoice", self.purchase_invoice)
		if pi.docstatus != 0:
			return

		changed = False
		if pi.supplier != self.transporter:
			pi.supplier = self.transporter
			changed = True
		if pi.company != self.company:
			pi.company = self.company
			changed = True
		if pi.items and flt(pi.items[0].rate) != flt(self.delivery_charges):
			pi.items[0].qty = 1
			pi.items[0].rate = flt(self.delivery_charges)
			changed = True

		if changed:
			pi.flags.ignore_permissions = True
			pi.save(ignore_permissions=True)

	def submit_transport_purchase_invoice(self):
		if not self.transporter or not flt(self.delivery_charges):
			return

		if not self.purchase_invoice:
			self.create_transport_purchase_invoice()

		if not self.purchase_invoice:
			return

		pi = frappe.get_doc("Purchase Invoice", self.purchase_invoice)
		if pi.docstatus == 0:
			pi.flags.ignore_permissions = True
			pi.submit()

	@staticmethod
	def get_or_create_transport_charges_item():
		if frappe.db.exists("Item", TRANSPORT_CHARGES_ITEM):
			return TRANSPORT_CHARGES_ITEM

		item_group = TRANSPORT_ITEM_GROUP
		if not frappe.db.exists("Item Group", item_group):
			item_group = frappe.db.get_value("Item Group", {"is_group": 0}, "name") or "All Item Groups"

		item = frappe.new_doc("Item")
		item.item_code = TRANSPORT_CHARGES_ITEM
		item.item_name = TRANSPORT_CHARGES_ITEM
		item.item_group = item_group
		item.stock_uom = "Nos"
		item.is_stock_item = 0
		item.include_item_in_manufacturing = 0
		item.is_sales_item = 0
		item.is_purchase_item = 1
		item.flags.ignore_permissions = True
		item.insert(ignore_permissions=True)
		return item.item_code

	def cancel_linked_purchase_invoice(self):
		if not self.purchase_invoice:
			return
		if not frappe.db.exists("Purchase Invoice", self.purchase_invoice):
			return

		pi = frappe.get_doc("Purchase Invoice", self.purchase_invoice)
		if pi.docstatus == 1:
			pi.flags.ignore_permissions = True
			pi.flags.ignore_links = True
			pi.cancel()

	def delete_linked_purchase_invoice(self):
		if not self.purchase_invoice:
			return
		if not frappe.db.exists("Purchase Invoice", self.purchase_invoice):
			return

		pi = frappe.get_doc("Purchase Invoice", self.purchase_invoice)

		if pi.docstatus == 1:
			pi.flags.ignore_permissions = True
			pi.flags.ignore_links = True
			pi.cancel()
			pi.reload()

		if pi.docstatus in (0, 2):
			frappe.delete_doc(
				"Purchase Invoice",
				pi.name,
				ignore_permissions=True,
				force=True,
				ignore_doctypes=["Gate Pass"],
			)


# ----------------------------------------------------------------------
# Whitelisted helper - called directly from gate_pass.js so the browser
# NEVER runs Frappe's default "Cancel All Documents" pre-check, which
# would otherwise intercept the click before on_cancel() gets a chance
# to run (and which requires the current user to have Cancel permission
# on Purchase Invoice, causing the permission error you were seeing).
# ----------------------------------------------------------------------
@frappe.whitelist()
def cancel_gate_pass(gate_pass):
	doc = frappe.get_doc("Gate Pass", gate_pass)
	if doc.docstatus != 1:
		frappe.throw(_("Only a submitted Gate Pass can be cancelled."))

	frappe.has_permission("Gate Pass", "cancel", doc=doc, throw=True)

	# Cancel the Purchase Invoice FIRST (with ignore_permissions=True so
	# the current user's own Purchase Invoice permissions don't matter -
	# the Gate Pass permission check above is what gates this action).
	doc.cancel_linked_purchase_invoice()
	doc.reload()
	doc.flags.ignore_links = True
	doc.cancel()
	return doc.name