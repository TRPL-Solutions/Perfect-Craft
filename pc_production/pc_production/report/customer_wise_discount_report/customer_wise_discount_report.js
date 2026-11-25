// Copyright (c) 2026, TRPL Solutions and contributors
// For license information, please see license.txt

// pc_cws_multi (multi-select filters on report_utils.get_filter_options) comes from here.
{% include "pc_production/pc_production/report/city_wise_sales_report/city_wise_common.js" %}

frappe.query_reports["Customer Wise Discount Report"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_start(),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.month_end(),
			reqd: 1,
		},
		{
			// Single customer or all; not a Link (most report users cannot read Customer).
			fieldname: "customer",
			label: __("Customer"),
			fieldtype: "Autocomplete",
			get_query: () => ({
				query: "pc_production.pc_production.report_utils.get_filter_options",
				params: { doctype: "Customer" },
			}),
		},
		pc_cws_multi("sales_person", __("Sales Officer"), "Sales Person"),
		pc_cws_multi("territory", __("Region"), "Territory"),
		pc_cws_multi("city", __("City"), "City"),
		pc_cws_multi("area", __("Area"), "Area"),
		{
			fieldname: "include_customers_without_sales",
			label: __("Include customers without sales"),
			fieldtype: "Check",
			default: 0,
		},
	],

	onload(report) {
		// Print preview / PDF of the rows and filters on screen (public/js/pc_report_print.bundle.js,
		// table: customer_wise_discount_report.html).
		pc_report_print.setup(report, {
			title: "CUSTOMER WISE DISCOUNT REPORT",
			orientation: "Landscape",
			font_size: 8,
			filters: [
				["customer", "Customer"],
				["sales_person", "Sales Officer"],
				["territory", "Region"],
				["city", "City"],
				["area", "Area"],
			],
		});
	},

	formatter(value, row, column, data, default_formatter) {
		// The Grand Total row has no credit or per-CTN figures (not summable).
		const not_totalled = ["credit_days", "credit_limit", "discount_per_ctn"];
		if (data && data.row_type === "total" && not_totalled.includes(column.fieldname)) {
			return "";
		}
		value = default_formatter(value, row, column, data);
		if (data && data.bold) {
			return `<b>${value}</b>`;
		}
		return value;
	},
};
