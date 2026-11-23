// Copyright (c) 2026, TRPL Solutions and contributors
// For license information, please see license.txt

// Remove a row's applied Pricing Rule before ERPNext re-prices the row for a new UOM.
//
// ERPNext's TransactionController.uom() (erpnext/public/js/controllers/transaction.js) clears
// row.pricing_rules *before* asking the server for the new price. The server then cannot tell
// that a rule was applied and never removes its discount, so switching a row from a UOM that
// has a UOM-specific rule (e.g. Customer Referral discount on Carton) to one that has none
// (e.g. Nos) keeps the old discount: 1,200 - 10% -> Nos 100 - 120 = rate -20.
//
// Frappe runs frappe.ui.form.on() handlers before the controller's own uom() and waits for
// a returned promise, so this handler removes the rule first, using ERPNext's own server and
// client logic, and then ERPNext's uom() re-applies whatever rule matches the new UOM.
// Rows without a pricing rule (manual discounts) are not touched.

(() => {
	if (window.__pc_uom_pricing_rule_fix) return;
	window.__pc_uom_pricing_rule_fix = true;

	const ITEM_DOCTYPES = [
		"Quotation Item",
		"Sales Order Item",
		"Delivery Note Item",
		"Sales Invoice Item",
	];

	const remove_rule_before_uom_change = (frm, cdt, cdn) => {
		const row = locals[cdt] && locals[cdt][cdn];
		if (!row || !row.pricing_rules || row.is_free_item || frm.doc.ignore_pricing_rule) {
			return;
		}

		const removed_pricing_rules = row.pricing_rules;
		return frappe
			.call({
				method: "erpnext.accounts.doctype.pricing_rule.pricing_rule.remove_pricing_rule_for_item",
				args: {
					pricing_rules: removed_pricing_rules,
					item_details: {
						doctype: row.doctype,
						name: row.name,
						item_code: row.item_code,
						pricing_rules: removed_pricing_rules,
						parenttype: row.parenttype,
						parent: row.parent,
						price_list_rate: row.price_list_rate,
					},
					item_code: row.item_code,
					rate: row.price_list_rate,
				},
			})
			.then((r) => {
				if (!r || !r.message) return;
				if (frm.cscript && typeof frm.cscript.remove_pricing_rule === "function") {
					// ERPNext's own client handling: resets the rule's discount/margin fields on
					// this row and removes free items added by product-discount rules.
					frm.cscript.remove_pricing_rule(r.message, removed_pricing_rules, row.name);
				} else {
					Object.assign(row, r.message);
				}
			});
	};

	ITEM_DOCTYPES.forEach((doctype) => {
		frappe.ui.form.on(doctype, { uom: remove_rule_before_uom_change });
	});
})();
