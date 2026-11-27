// Production mode: with Production ticked and Month / Year / Cost Center filled,
// fill Vouchers with the month's submitted Manufacture Stock Entries of that
// Cost Center, then their items into Receipt Items (the standard "Get Items").

frappe.ui.form.on("Landed Cost Voucher", {
	setup(frm) {
		frm.set_query("custom_production_cost_center", () => ({
			filters: { company: frm.doc.company, is_group: 0 },
		}));
	},

	custom_production(frm) {
		if (frm.doc.custom_production && !frm.doc.custom_production_year) {
			// Setting the year triggers its own handler, which fetches if ready
			frm.set_value("custom_production_year", String(new Date().getFullYear()));
			return;
		}
		pc_fetch_production_entries(frm);
	},
	custom_production_month: pc_fetch_production_entries,
	custom_production_year: pc_fetch_production_entries,
	custom_production_cost_center: pc_fetch_production_entries,
});

function pc_fetch_production_entries(frm) {
	const d = frm.doc;
	if (d.docstatus !== 0 || !d.custom_production) return;
	if (!d.custom_production_month || !d.custom_production_year || !d.custom_production_cost_center) {
		return;
	}
	if (!/^\d{4}$/.test(String(d.custom_production_year).trim())) {
		frappe.msgprint(__("Please enter Year as a 4 digit number, e.g. 2026."));
		return;
	}
	if (!d.company) {
		frappe.msgprint(__("Please select Company first."));
		return;
	}

	frappe.call({
		method: "pc_production.landed_cost_voucher.get_production_stock_entries",
		args: {
			company: d.company,
			month: d.custom_production_month,
			year: String(d.custom_production_year).trim(),
			cost_center: d.custom_production_cost_center,
		},
		freeze: true,
		freeze_message: __("Fetching Manufacture Stock Entries..."),
		callback(r) {
			const entries = r.message || [];

			frm.clear_table("purchase_receipts");
			frm.clear_table("items");

			if (!entries.length) {
				frm.refresh_field("purchase_receipts");
				frm.refresh_field("items");
				frappe.msgprint({
					title: __("No Stock Entries Found"),
					indicator: "orange",
					message: __(
						"No submitted Manufacture Stock Entries found for Cost Center {0} in {1} {2}.",
						[
							frappe.utils.escape_html(d.custom_production_cost_center).bold(),
							__(d.custom_production_month),
							d.custom_production_year,
						]
					),
				});
				return;
			}

			entries.forEach((se) => {
				frm.add_child("purchase_receipts", {
					receipt_document_type: "Stock Entry",
					receipt_document: se.name,
					posting_date: se.posting_date,
					grand_total: se.grand_total,
				});
			});
			frm.refresh_field("purchase_receipts");

			// Same as clicking the standard "Get Items" button
			frm.script_manager.trigger("get_items_from_purchase_receipts");

			frappe.show_alert({
				message: __("{0} Manufacture Stock Entries added", [entries.length]),
				indicator: "green",
			});
		},
	});
}
