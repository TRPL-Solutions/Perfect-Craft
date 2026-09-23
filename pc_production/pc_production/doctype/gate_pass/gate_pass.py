# Copyright (c) 2026, TRPL Solutions and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


TRANSPORT_CHARGES_ITEM = "Transport Charges"
TRANSPORT_ITEM_GROUP = "Services"


class GatePass(Document):

	# ================================================================
	# STANDARD DOCUMENT EVENTS
	# ================================================================

	def before_insert(self):
		"""
		Automatically set Created By from document owner/current user.
		"""
		self.set_created_by()


	def validate(self):
		"""
		Final server-side validation.

		Client-side JS gives immediate UI updates, while Python remains
		the source of truth so API/import/background saves are also safe.
		"""
		self.set_created_by()
		self.set_total_qty()
		self.validate_transport_details()


	def on_update(self):
		"""
		While Gate Pass is Draft:

		- Create a Draft Purchase Invoice when transporter + charges exist.
		- Keep existing Draft PI synchronized.
		- Remove stale Draft PI if transport charges are removed.
		"""
		if self.docstatus == 0:
			self.sync_transport_purchase_invoice()


	def on_submit(self):
		"""
		When Gate Pass is submitted, submit its linked Purchase Invoice.
		"""
		self.validate_transport_details()
		self.submit_transport_purchase_invoice()


	def on_cancel(self):
		"""
		Cancel linked Purchase Invoice whenever Gate Pass is cancelled.
		"""
		self.cancel_linked_purchase_invoice()


	def on_trash(self):
		"""
		Delete linked Purchase Invoice when Gate Pass is deleted.
		"""
		self.delete_linked_purchase_invoice()


	# ================================================================
	# CREATED BY
	# ================================================================

	def set_created_by(self):
		"""
		Created By must automatically represent the document owner.

		On a new document owner is normally the logged-in user.
		"""
		if not self.created_by:
			self.created_by = self.owner or frappe.session.user


	# ================================================================
	# TOTAL QTY
	# ================================================================

	def set_total_qty(self):
		"""
		Automatically calculate Total Qty from all Gate Pass item rows.
		"""
		total_qty = 0

		for row in self.items or []:
			qty = flt(row.qty)

			if qty < 0:
				frappe.throw(
					_("Quantity cannot be negative in row {0}.").format(
						row.idx
					)
				)

			total_qty += qty

		self.custom_total_amount = total_qty


	# ================================================================
	# TRANSPORT VALIDATION
	# ================================================================

	def validate_transport_details(self):
		"""
		Transporter is mandatory whenever Delivery Charges are entered.
		Negative delivery charges are not allowed.
		"""
		delivery_charges = flt(self.delivery_charges)

		if delivery_charges < 0:
			frappe.throw(
				_("Delivery Charges cannot be negative.")
			)

		if delivery_charges > 0 and not self.transporter:
			frappe.throw(
				_(
					"Transporter is required when Delivery Charges "
					"are greater than zero."
				)
			)


	# ================================================================
	# PURCHASE INVOICE SYNC
	# ================================================================

	def sync_transport_purchase_invoice(self):
		"""
		Keep Draft Purchase Invoice synchronized with Gate Pass.

		Rules:
		- No charges -> no PI required.
		- Charges > 0 -> Transporter required.
		- Existing Draft PI -> update it.
		- Existing active PI found through custom_gate_pass -> reuse it.
		- Otherwise create a new Draft PI.
		"""
		delivery_charges = flt(self.delivery_charges)

		# ------------------------------------------------------------
		# No charges / no transporter:
		# remove any stale Draft PI created earlier.
		# ------------------------------------------------------------
		if not self.transporter or delivery_charges <= 0:
			self.remove_draft_transport_purchase_invoice()
			return

		self.ensure_gate_pass_field_exists()

		# ------------------------------------------------------------
		# Purchase Invoice is already linked on Gate Pass
		# ------------------------------------------------------------
		if self.purchase_invoice:

			if frappe.db.exists(
				"Purchase Invoice",
				self.purchase_invoice
			):
				pi = frappe.get_doc(
					"Purchase Invoice",
					self.purchase_invoice
				)

				if pi.docstatus == 0:
					self.update_existing_purchase_invoice(pi)
					return

				if pi.docstatus == 1:
					# Submitted PI does not need draft synchronization.
					return

				# Cancelled PI should not remain linked to Draft GP.
				if pi.docstatus == 2:
					self.db_set(
						"purchase_invoice",
						None,
						update_modified=False
					)
					self.purchase_invoice = None

			else:
				self.db_set(
					"purchase_invoice",
					None,
					update_modified=False
				)
				self.purchase_invoice = None

		# ------------------------------------------------------------
		# Duplicate protection:
		# maybe a PI already exists but link was not loaded/set.
		# ------------------------------------------------------------
		existing_pi = frappe.db.get_value(
			"Purchase Invoice",
			{
				"custom_gate_pass": self.name,
				"docstatus": ["!=", 2],
			},
			"name",
		)

		if existing_pi:

			self.purchase_invoice = existing_pi

			self.db_set(
				"purchase_invoice",
				existing_pi,
				update_modified=False
			)

			pi = frappe.get_doc(
				"Purchase Invoice",
				existing_pi
			)

			if pi.docstatus == 0:
				self.update_existing_purchase_invoice(pi)

			return

		# ------------------------------------------------------------
		# No existing PI -> create one
		# ------------------------------------------------------------
		self.create_transport_purchase_invoice()


	# ================================================================
	# CREATE PURCHASE INVOICE
	# ================================================================

	def create_transport_purchase_invoice(self):

		if not self.transporter:
			return

		if flt(self.delivery_charges) <= 0:
			return

		self.ensure_gate_pass_field_exists()

		# ------------------------------------------------------------
		# Duplicate safety check
		# ------------------------------------------------------------
		existing_pi = frappe.db.get_value(
			"Purchase Invoice",
			{
				"custom_gate_pass": self.name,
				"docstatus": ["!=", 2],
			},
			"name",
		)

		if existing_pi:

			self.purchase_invoice = existing_pi

			self.db_set(
				"purchase_invoice",
				existing_pi,
				update_modified=False
			)

			return

		# ------------------------------------------------------------
		# Ensure Transport Charges service item exists
		# ------------------------------------------------------------
		item_code = self.get_or_create_transport_charges_item()

		# ------------------------------------------------------------
		# Create PI
		# ------------------------------------------------------------
		pi = frappe.new_doc("Purchase Invoice")

		pi.company = self.company
		pi.supplier = self.transporter
		pi.custom_gate_pass = self.name

		if self.date:
			pi.posting_date = self.date

		pi.remarks = _(
			"Auto-created against Gate Pass {0}"
		).format(self.name)

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

		# ERPNext will populate accounts/UOM/etc. according to defaults.
		pi.set_missing_values()

		pi.flags.ignore_permissions = True

		# Draft PI
		pi.insert(ignore_permissions=True)

		# ------------------------------------------------------------
		# Store backlink on Gate Pass
		# ------------------------------------------------------------
		self.purchase_invoice = pi.name

		self.db_set(
			"purchase_invoice",
			pi.name,
			update_modified=False
		)


	# ================================================================
	# UPDATE EXISTING DRAFT PURCHASE INVOICE
	# ================================================================

	def update_existing_purchase_invoice(self, pi=None):

		if not pi:

			if not self.purchase_invoice:
				return

			if not frappe.db.exists(
				"Purchase Invoice",
				self.purchase_invoice
			):
				self.db_set(
					"purchase_invoice",
					None,
					update_modified=False
				)

				self.purchase_invoice = None
				self.create_transport_purchase_invoice()
				return

			pi = frappe.get_doc(
				"Purchase Invoice",
				self.purchase_invoice
			)

		# Submitted/cancelled PI should never be modified.
		if pi.docstatus != 0:
			return

		item_code = self.get_or_create_transport_charges_item()

		changed = False

		# ------------------------------------------------------------
		# Supplier / Transporter
		# ------------------------------------------------------------
		if pi.supplier != self.transporter:
			pi.supplier = self.transporter
			changed = True

		# ------------------------------------------------------------
		# Company
		# ------------------------------------------------------------
		if pi.company != self.company:
			pi.company = self.company
			changed = True

		# ------------------------------------------------------------
		# Gate Pass backlink
		# ------------------------------------------------------------
		if pi.custom_gate_pass != self.name:
			pi.custom_gate_pass = self.name
			changed = True

		# ------------------------------------------------------------
		# Posting Date
		# ------------------------------------------------------------
		if self.date and str(pi.posting_date) != str(self.date):
			pi.posting_date = self.date
			changed = True

		# ------------------------------------------------------------
		# PI must contain exactly one Transport Charges row
		# ------------------------------------------------------------
		rebuild_items = False

		if len(pi.items or []) != 1:
			rebuild_items = True

		elif pi.items[0].item_code != item_code:
			rebuild_items = True

		if rebuild_items:

			pi.set("items", [])

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

			changed = True

		else:

			row = pi.items[0]

			if flt(row.qty) != 1:
				row.qty = 1
				changed = True

			if flt(row.rate) != flt(self.delivery_charges):
				row.rate = flt(self.delivery_charges)
				changed = True

		# ------------------------------------------------------------
		# Save only when something actually changed
		# ------------------------------------------------------------
		if changed:

			pi.set_missing_values()

			pi.flags.ignore_permissions = True

			pi.save(ignore_permissions=True)


	# ================================================================
	# REMOVE STALE DRAFT PI
	# ================================================================

	def remove_draft_transport_purchase_invoice(self):
		"""
		If user previously entered charges and a Draft PI was created,
		then later clears transporter/charges, delete that stale Draft PI.
		"""

		pi_names = []

		if self.purchase_invoice:
			pi_names.append(self.purchase_invoice)

		if self.name:
			for pi_name in frappe.get_all(
				"Purchase Invoice",
				filters={
					"custom_gate_pass": self.name,
					"docstatus": 0,
				},
				pluck="name",
			):
				if pi_name not in pi_names:
					pi_names.append(pi_name)

		for pi_name in pi_names:

			if not frappe.db.exists(
				"Purchase Invoice",
				pi_name
			):
				continue

			pi = frappe.get_doc(
				"Purchase Invoice",
				pi_name
			)

			# Only Draft PI may be automatically removed here.
			if pi.docstatus == 0:

				frappe.delete_doc(
					"Purchase Invoice",
					pi.name,
					ignore_permissions=True,
					force=True,
					ignore_doctypes=["Gate Pass"],
				)

		if self.purchase_invoice:

			self.purchase_invoice = None

			self.db_set(
				"purchase_invoice",
				None,
				update_modified=False
			)


	# ================================================================
	# SUBMIT PURCHASE INVOICE
	# ================================================================

	def submit_transport_purchase_invoice(self):

		if not self.transporter:
			return

		if flt(self.delivery_charges) <= 0:
			return

		self.ensure_gate_pass_field_exists()

		# Safety net
		if not self.purchase_invoice:
			self.create_transport_purchase_invoice()

		if not self.purchase_invoice:
			frappe.throw(
				_(
					"Purchase Invoice could not be created "
					"for Transport Charges."
				)
			)

		if not frappe.db.exists(
			"Purchase Invoice",
			self.purchase_invoice
		):
			frappe.throw(
				_(
					"Linked Purchase Invoice {0} does not exist."
				).format(self.purchase_invoice)
			)

		pi = frappe.get_doc(
			"Purchase Invoice",
			self.purchase_invoice
		)

		if pi.docstatus == 0:

			# Final sync immediately before submission.
			self.update_existing_purchase_invoice(pi)

			pi.reload()

			pi.flags.ignore_permissions = True

			pi.submit()

		elif pi.docstatus == 2:
			frappe.throw(
				_(
					"Linked Purchase Invoice {0} is cancelled."
				).format(pi.name)
			)


	# ================================================================
	# TRANSPORT CHARGES ITEM
	# ================================================================

	@staticmethod
	def get_or_create_transport_charges_item():

		if frappe.db.exists(
			"Item",
			TRANSPORT_CHARGES_ITEM
		):
			return TRANSPORT_CHARGES_ITEM

		# ------------------------------------------------------------
		# Find Services Item Group
		# ------------------------------------------------------------
		item_group = None

		if frappe.db.exists(
			"Item Group",
			TRANSPORT_ITEM_GROUP
		):
			item_group = TRANSPORT_ITEM_GROUP

		if not item_group:

			item_group = frappe.db.get_value(
				"Item Group",
				{"is_group": 0},
				"name"
			)

		if not item_group:
			frappe.throw(
				_(
					"Please create an Item Group before creating "
					"the Transport Charges service item."
				)
			)

		# ------------------------------------------------------------
		# Create non-stock service item
		# ------------------------------------------------------------
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


	# ================================================================
	# CUSTOM FIELD SAFETY
	# ================================================================

	@staticmethod
	def ensure_gate_pass_field_exists():
		"""
		Clear message if migration/fixture was not applied.
		"""
		if not frappe.get_meta(
			"Purchase Invoice"
		).has_field("custom_gate_pass"):

			frappe.throw(
				_(
					"Purchase Invoice field 'Gate Pass' "
					"(custom_gate_pass) is missing. "
					"Please run bench migrate."
				)
			)


	# ================================================================
	# CANCEL LINKED PURCHASE INVOICE
	# ================================================================

	def cancel_linked_purchase_invoice(self):

		pi_name = self.get_linked_purchase_invoice_name()

		if not pi_name:
			return

		if not frappe.db.exists(
			"Purchase Invoice",
			pi_name
		):
			return

		pi = frappe.get_doc(
			"Purchase Invoice",
			pi_name
		)

		if pi.docstatus == 1:

			pi.flags.ignore_permissions = True
			pi.flags.ignore_links = True

			pi.cancel()


	# ================================================================
	# DELETE LINKED PURCHASE INVOICE
	# ================================================================

	def delete_linked_purchase_invoice(self):

		pi_name = self.get_linked_purchase_invoice_name()

		if not pi_name:
			return

		if not frappe.db.exists(
			"Purchase Invoice",
			pi_name
		):
			return

		pi = frappe.get_doc(
			"Purchase Invoice",
			pi_name
		)

		# ------------------------------------------------------------
		# Cancel first if somehow still submitted
		# ------------------------------------------------------------
		if pi.docstatus == 1:

			pi.flags.ignore_permissions = True
			pi.flags.ignore_links = True

			pi.cancel()
			pi.reload()

		# ------------------------------------------------------------
		# Delete Draft / Cancelled PI
		# ------------------------------------------------------------
		if pi.docstatus in (0, 2):

			frappe.delete_doc(
				"Purchase Invoice",
				pi.name,
				ignore_permissions=True,
				force=True,
				ignore_doctypes=["Gate Pass"],
			)


	def get_linked_purchase_invoice_name(self):

		if self.purchase_invoice:
			return self.purchase_invoice

		if not self.name:
			return None

		if not frappe.get_meta(
			"Purchase Invoice"
		).has_field("custom_gate_pass"):
			return None

		return frappe.db.get_value(
			"Purchase Invoice",
			{
				"custom_gate_pass": self.name,
				"docstatus": ["!=", 2],
			},
			"name",
		)


# ======================================================================
# CUSTOM CANCEL ENDPOINT
# ======================================================================

@frappe.whitelist()
def cancel_gate_pass(gate_pass):
	"""
	Client-side Gate Pass cancel button calls this method directly.

	This avoids Frappe's browser-side linked-document pre-check from
	blocking cancellation because the logged-in user may not have direct
	Purchase Invoice Cancel permission.
	"""

	doc = frappe.get_doc(
		"Gate Pass",
		gate_pass
	)

	if doc.docstatus != 1:
		frappe.throw(
			_("Only a submitted Gate Pass can be cancelled.")
		)

	# User must still have permission to cancel Gate Pass.
	frappe.has_permission(
		"Gate Pass",
		"cancel",
		doc=doc,
		throw=True
	)

	# Cancel PI first.
	doc.cancel_linked_purchase_invoice()

	doc.reload()

	# Ignore backlink because linked PI has already been handled.
	doc.flags.ignore_links = True

	doc.cancel()

	return doc.name