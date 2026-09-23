// Copyright (c) 2026, TRPL Solutions and contributors
// For license information, please see license.txt


// =====================================================================
// CREATED BY
// =====================================================================

function set_created_by(frm) {
	if (
		frm.is_new() &&
		!frm.doc.created_by
	) {
		frm.set_value(
			"created_by",
			frappe.session.user
		);
	}
}


// =====================================================================
// TOTAL QTY
// =====================================================================

function calculate_total_qty(frm) {
	let total_qty = 0;

	(frm.doc.items || []).forEach((row) => {
		total_qty += flt(row.qty);
	});

	/*
	 * Only update if value actually changed.
	 */
	if (
		flt(frm.doc.custom_total_amount) !==
		flt(total_qty)
	) {
		frm.set_value(
			"custom_total_amount",
			total_qty
		);
	}
}


// =====================================================================
// SYNC PURCHASE INVOICE FIELD FROM DATABASE
// =====================================================================

function sync_purchase_invoice_on_form(frm) {

	if (frm.is_new()) {
		return;
	}

	frappe.db
		.get_value(
			"Gate Pass",
			frm.doc.name,
			"purchase_invoice"
		)
		.then((r) => {

			const purchase_invoice =
				r &&
				r.message &&
				r.message.purchase_invoice
					? r.message.purchase_invoice
					: null;

			/*
			 * Update browser document without requiring Ctrl + R.
			 */
			if (
				frm.doc.purchase_invoice !==
				purchase_invoice
			) {
				frm.doc.purchase_invoice =
					purchase_invoice;

				frm.refresh_field(
					"purchase_invoice"
				);
			}

			add_purchase_invoice_button(frm);
		});
}


// =====================================================================
// PURCHASE INVOICE BUTTON
// =====================================================================

function add_purchase_invoice_button(frm) {

	frm.remove_custom_button(
		__("Purchase Invoice"),
		__("View")
	);

	if (!frm.doc.purchase_invoice) {
		return;
	}

	frm.add_custom_button(
		__("Purchase Invoice"),

		() => {
			frappe.set_route(
				"Form",
				"Purchase Invoice",
				frm.doc.purchase_invoice
			);
		},

		__("View")
	);
}


// =====================================================================
// TRANSPORTER ADDRESS
// =====================================================================

function fetch_transporter_address(frm) {

	if (!frm.doc.transporter) {

		frm.set_value(
			"address",
			""
		);

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

				frm.set_value(
					"address",
					""
				);

				return;
			}

			frappe.db
				.get_value(
					"Address",
					r.message,
					[
						"address_line1",
						"address_line2",
						"city",
						"state",
						"pincode",
						"country",
					]
				)
				.then((res) => {

					if (
						!res ||
						!res.message
					) {
						return;
					}

					const a = res.message;

					const address_lines = [
						a.address_line1,
						a.address_line2,
						a.city,
						a.state,
						a.pincode,
						a.country,
					].filter(Boolean);

					frm.set_value(
						"address",
						address_lines.join(", ")
					);
				});
		},
	});
}


// =====================================================================
// GATE PASS
// =====================================================================

frappe.ui.form.on("Gate Pass", {

	setup(frm) {

		/*
		 * Linked Purchase Invoice cancellation is handled by
		 * gate_pass.py.
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


	onload(frm) {

		// Auto-set document owner/current user.
		set_created_by(frm);

		// Calculate immediately if rows already exist.
		if (frm.doc.docstatus === 0) {
			calculate_total_qty(frm);
		}
	},


	refresh(frm) {

		// -------------------------------------------------------------
		// CREATED BY
		// -------------------------------------------------------------
		set_created_by(frm);


		// -------------------------------------------------------------
		// TOTAL QTY
		// -------------------------------------------------------------
		if (frm.doc.docstatus === 0) {
			calculate_total_qty(frm);
		}


		// -------------------------------------------------------------
		// PURCHASE INVOICE FIELD / BUTTON
		// -------------------------------------------------------------
		if (frm.doc.purchase_invoice) {

			add_purchase_invoice_button(frm);

		} else {

			sync_purchase_invoice_on_form(frm);
		}


		// -------------------------------------------------------------
		// CUSTOM CANCEL FLOW
		// -------------------------------------------------------------
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

					message +=
						"<br><br>" +
						__(
							"Linked Purchase Invoice {0} will also be cancelled automatically.",
							[
								frm.doc.purchase_invoice,
							]
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
								gate_pass:
									frm.doc.name,
							},

							freeze: true,

							freeze_message: __(
								"Cancelling Gate Pass and linked Purchase Invoice..."
							),

							callback: function (r) {

								if (!r.exc) {

									frappe.show_alert({
										message: __(
											"Gate Pass and linked Purchase Invoice cancelled."
										),
										indicator:
											"green",
									});

									frm.reload_doc()
										.then(() => {

											if (
												callback
											) {
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


		// -------------------------------------------------------------
		// CUSTOM DELETE FLOW
		// -------------------------------------------------------------
		if (
			!frm.is_new() &&
			frm.doc.docstatus !== 1
		) {

			frm.savetrash = function () {

				frm.validate_form_action(
					"Delete"
				);

				frappe.model.delete_doc(

					"Gate Pass",
					frm.doc.name,

					function () {

						frappe.show_alert({
							message: __(
								"Gate Pass and linked Purchase Invoice deleted."
							),
							indicator:
								"green",
						});

						frappe.set_route(
							"List",
							"Gate Pass"
						);
					}
				);
			};
		}
	},


	// =================================================================
	// VALIDATE
	// =================================================================

	validate(frm) {

		set_created_by(frm);

		calculate_total_qty(frm);

		if (
			flt(frm.doc.delivery_charges) < 0
		) {
			frappe.throw(
				__(
					"Delivery Charges cannot be negative."
				)
			);
		}

		if (
			flt(frm.doc.delivery_charges) > 0 &&
			!frm.doc.transporter
		) {
			frappe.throw(
				__(
					"Transporter is required when Delivery Charges are greater than zero."
				)
			);
		}
	},


	// =================================================================
	// AFTER SAVE
	// =================================================================

	after_save(frm) {

		/*
		 * Python may have just created/updated/deleted the Draft PI.
		 * Refresh the linked PI field immediately.
		 */
		sync_purchase_invoice_on_form(frm);
	},


	// =================================================================
	// TRANSPORTER
	// =================================================================

	transporter(frm) {

		fetch_transporter_address(frm);
	},


	// =================================================================
	// DELIVERY CHARGES
	// =================================================================

	delivery_charges(frm) {

		if (
			flt(frm.doc.delivery_charges) > 0 &&
			!frm.doc.transporter
		) {
			frappe.show_alert({
				message: __(
					"Please select a Transporter for Delivery Charges."
				),
				indicator: "orange",
			});
		}
	},
});


// =====================================================================
// GATE PASS CHILD TABLE
// =====================================================================

frappe.ui.form.on("Gate Pass CT", {

	qty(frm, cdt, cdn) {

		/*
		 * Real-time Total Qty calculation.
		 *
		 * Example:
		 * 8 + 5 + 10 = Total Qty 23
		 */
		calculate_total_qty(frm);
	},


	items_add(frm, cdt, cdn) {

		calculate_total_qty(frm);
	},


	items_remove(frm, cdt, cdn) {

		calculate_total_qty(frm);
	},


	items_move(frm, cdt, cdn) {

		calculate_total_qty(frm);
	},
});