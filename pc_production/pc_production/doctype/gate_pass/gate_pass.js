// Copyright (c) 2026, TRPL Solutions and contributors
// For license information, please see license.txt


// ================================================================
// Helper: Immediately sync Purchase Invoice field from database
// ================================================================
function sync_purchase_invoice_on_form(frm) {
	if (frm.is_new()) {
		return;
	}

	frappe.db
		.get_value("Gate Pass", frm.doc.name, "purchase_invoice")
		.then((r) => {
			const purchase_invoice =
				r &&
				r.message &&
				r.message.purchase_invoice
					? r.message.purchase_invoice
					: null;

			// Update browser-side document WITHOUT making form dirty
			if (frm.doc.purchase_invoice !== purchase_invoice) {
				frm.doc.purchase_invoice = purchase_invoice;
				frm.refresh_field("purchase_invoice");
			}

			add_purchase_invoice_button(frm);
		});
}


// ================================================================
// Helper: Show Purchase Invoice button
// ================================================================
function add_purchase_invoice_button(frm) {
	// Remove old button first to avoid duplicates
	frm.remove_custom_button(
		__("Purchase Invoice"),
		__("View")
	);

	if (!frm.doc.purchase_invoice) {
		return;
	}

	frm.add_custom_button(
		__("Purchase Invoice"),
		function () {
			frappe.set_route(
				"Form",
				"Purchase Invoice",
				frm.doc.purchase_invoice
			);
		},
		__("View")
	);
}


// ================================================================
// Gate Pass
// ================================================================
frappe.ui.form.on("Gate Pass", {

	setup(frm) {
		/*
		 * Purchase Invoice cancellation is handled automatically
		 * by Gate Pass Python code.
		 */
		frm.ignore_doctypes_on_cancel_all =
			frm.ignore_doctypes_on_cancel_all || [];

		if (
			!frm.ignore_doctypes_on_cancel_all.includes(
				"Purchase Invoice"
			)
		) {
			frm.ignore_doctypes_on_cancel_all.push(
				"Purchase Invoice"
			);
		}
	},


	refresh(frm) {

		// ============================================================
		// PURCHASE INVOICE FIELD / BUTTON
		// ============================================================

		if (frm.doc.purchase_invoice) {
			add_purchase_invoice_button(frm);
		} else {
			/*
			 * Purchase Invoice may have been created by Python
			 * during save but browser-side document may not yet
			 * contain the new link.
			 *
			 * Fetch it immediately from DB.
			 */
			sync_purchase_invoice_on_form(frm);
		}


		// ============================================================
		// CUSTOM CANCEL FLOW
		// ============================================================

		if (frm.doc.docstatus === 1) {

			frm.savecancel = function (
				btn,
				callback,
				on_error
			) {

				let message = __(
					"Permanently Cancel {0}?",
					[frm.doc.name]
				);

				if (frm.doc.purchase_invoice) {
					message += "<br><br>" + __(
						"Linked Purchase Invoice {0} will also be cancelled automatically.",
						[frm.doc.purchase_invoice]
					);
				}

				frappe.confirm(
					message,

					// YES
					() => {

						frappe.call({
							method:
								"pc_production.pc_production.doctype.gate_pass.gate_pass.cancel_gate_pass",

							args: {
								gate_pass: frm.doc.name,
							},

							freeze: true,

							freeze_message: __(
								"Cancelling Gate Pass and linked Purchase Invoice..."
							),

							callback: function (r) {

								if (!r.exc) {

									frappe.show_alert({
										message: __(
											"Gate Pass and Purchase Invoice cancelled."
										),
										indicator: "green",
									});

									/*
									 * Auto reload cancelled Gate Pass.
									 * User does NOT need manual browser refresh.
									 */
									frm.reload_doc().then(() => {
										if (callback) {
											callback();
										}
									});
								}
							},

							error: function () {
								if (on_error) {
									on_error();
								}
							},
						});
					},

					// NO
					() => {
						if (on_error) {
							on_error();
						}
					}
				);
			};
		}


		// ============================================================
		// CUSTOM DELETE FLOW
		// ============================================================

		/*
		 * Default Frappe behaviour after deletion is:
		 *
		 *     window.history.back()
		 *
		 * We don't want that because previous screen may be PI,
		 * another Gate Pass, etc.
		 *
		 * After successful delete always open:
		 *
		 *     Gate Pass List
		 */

		if (!frm.is_new() && frm.doc.docstatus !== 1) {

			frm.savetrash = function () {

				// Keep Frappe's standard Delete permission check
				frm.validate_form_action("Delete");

				/*
				 * frappe.model.delete_doc already shows:
				 *
				 * "Permanently delete GPxxxxx?"
				 *
				 * So no extra confirmation dialog is needed.
				 */
				frappe.model.delete_doc(
					"Gate Pass",
					frm.doc.name,

					function () {

						frappe.show_alert({
							message: __(
								"Gate Pass and linked Purchase Invoice deleted."
							),
							indicator: "green",
						});

						/*
						 * IMPORTANT:
						 * Always go directly to Gate Pass List.
						 */
						frappe.set_route(
							"List",
							"Gate Pass"
						);
					}
				);
			};
		}
	},


	// ================================================================
	// AFTER SAVE
	// ================================================================

	after_save(frm) {

		/*
		 * Python on_update() may create/update Purchase Invoice.
		 *
		 * Fetch PI from DB immediately so user does NOT need
		 * Ctrl+R / manual reload.
		 */
		sync_purchase_invoice_on_form(frm);
	},


	// ================================================================
	// TRANSPORTER
	// ================================================================

	transporter(frm) {

		if (!frm.doc.transporter) {
			frm.set_value("address", "");
			return;
		}

		frappe.call({
			method:
				"frappe.contacts.doctype.address.address.get_default_address",

			args: {
				doctype: "Supplier",
				name: frm.doc.transporter,
			},

			callback: function (r) {

				if (!r.message) {
					return;
				}

				frappe.db
					.get_value(
						"Address",
						r.message,
						"address_line1"
					)
					.then((res) => {

						if (
							res &&
							res.message &&
							res.message.address_line1
						) {
							frm.set_value(
								"address",
								res.message.address_line1
							);
						}
					});
			},
		});
	},
});