// Copyright (c) 2026, TRPL Solutions and contributors
// For license information, please see license.txt

// pc_cws_multi (multi-select filters on report_utils.get_filter_options) comes from here.
{% include "pc_production/pc_production/report/city_wise_sales_report/city_wise_common.js" %}

frappe.query_reports["Print Customer List"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		pc_cws_multi("city", __("City"), "City"),
		pc_cws_multi("sales_person", __("Sale Person"), "Sales Person"),
		pc_cws_multi("territory", __("Region"), "Territory"),
		pc_cws_multi("area", __("Area"), "Area"),
	],

	onload(report) {
		// Print preview / PDF of the rows and filters on screen (public/js/pc_report_print.bundle.js,
		// table: print_customer_list.html).
		pc_report_print.setup(report, {
			title: "SALESMAN CUSTOMER LIST",
			orientation: "Portrait",
			font_size: 8,
			filters: [
				["city", "City"],
				["sales_person", "Sale Person"],
				["territory", "Region"],
				["area", "Area"],
			],
		});
	},

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		// Discount and Balance are text (ranges, "CR"): keep them right-aligned like amounts.
		if (["discount", "balance"].includes(column.fieldname)) {
			return `<div style="text-align: right">${value}</div>`;
		}
		return value;
	},
};
