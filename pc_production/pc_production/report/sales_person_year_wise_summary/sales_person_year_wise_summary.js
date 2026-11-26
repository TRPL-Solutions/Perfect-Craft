// Copyright (c) 2026, TRPL Solutions and contributors
// For license information, please see license.txt

// pc_cws_multi (multi-select filters on report_utils.get_filter_options) comes from here.
{% include "pc_production/pc_production/report/city_wise_sales_report/city_wise_common.js" %}

const PC_SPYW_REPORT = "Sales Person Year Wise Summary";

// Every query report shares one page, so the heading added above the table would stay when the
// user switches to another report. Show it only while this report's route is open (coming back
// to the report does not re-render it, so it is hidden / shown rather than removed).
function pc_spyw_toggle_heading() {
	const route = frappe.get_route() || [];
	const here = route[0] === "query-report" && route[1] === PC_SPYW_REPORT;
	$(".pc-spyw-heading").toggle(here);
}

frappe.query_reports[PC_SPYW_REPORT] = {
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
			default: frappe.datetime.year_start(),
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
			// Single customer or all, searchable by A/C Code; not a Link (most report users cannot
			// read Customer).
			fieldname: "customer",
			label: __("Customer (A/C Code)"),
			fieldtype: "Autocomplete",
			get_query: () => ({
				query: "pc_production.pc_production.report.sales_person_year_wise_summary.sales_person_year_wise_summary.get_customer_options",
			}),
		},
		pc_cws_multi("sales_person", __("Sales Person"), "Sales Person"),
		pc_cws_multi("territory", __("Region"), "Territory"),
		pc_cws_multi("city", __("City"), "City"),
		pc_cws_multi("area", __("Area"), "Area"),
		pc_cws_multi("brand", __("Sub Category (Brand)"), "Brand"),
		pc_cws_multi("sku", __("SKU"), "SKU"),
		// Show / Hide columns (an unticked Check is not sent; none ticked shows all three).
		{ fieldname: "show_qty", label: __("Show Qty"), fieldtype: "Check", default: 1 },
		{ fieldname: "show_amount", label: __("Show Amount"), fieldtype: "Check", default: 1 },
		{ fieldname: "show_receipt", label: __("Show Receipt"), fieldtype: "Check", default: 1 },
	],

	onload(report) {
		// Once per page load: hide the heading on other routes (see pc_spyw_toggle_heading).
		if (!window.pc_spyw_route_hook) {
			frappe.router.on("change", pc_spyw_toggle_heading);
			window.pc_spyw_route_hook = true;
		}
		// Print preview / PDF of the rows and filters on screen (public/js/pc_report_print.bundle.js,
		// table: sales_person_year_wise_summary.html). Title from the TOTAL row.
		const info = (ctx) => (ctx.data || []).find((r) => r && r.row_type === "total") || {};
		pc_report_print.setup(report, {
			title: (ctx) => info(ctx).report_title || __("SALE PERSON: ALL"),
			orientation: "Portrait",
			font_size: 9,
			subtitle: __("Sale Summary Year Wise"),
			filters: [
				["customer", "Customer"],
				["territory", "Region"],
				["city", "City"],
				["area", "Area"],
				["brand", "Sub Category"],
				["sku", "SKU"],
			],
		});
	},

	after_datatable_render() {
		// "SALE PERSON: FAISAL" (or ALL) above the table, the same text as the print title.
		const report = frappe.query_report;
		const total = (report.data || []).find((r) => r && r.row_type === "total") || {};
		const people = report.get_filter_value("sales_person") || [];
		const title =
			total.report_title ||
			__("SALE PERSON: {0}", [people.length ? people.join(", ").toUpperCase() : __("ALL")]);
		let $heading = report.page.main.find(".pc-spyw-heading");
		if (!$heading.length) {
			$heading = $(`<div class="pc-spyw-heading"
				style="font-weight: 700; font-size: var(--text-lg); padding: var(--padding-sm) var(--padding-md);"></div>`)
				.insertBefore(report.$report);
		}
		$heading.text(title);
		pc_spyw_toggle_heading();
	},

	formatter(value, row, column, data, default_formatter) {
		if (column.fieldtype === "Float" && value != null && value !== "") {
			// Whole cartons (a Float column never formats with 0 decimals).
			value = `<div style="text-align: right">${format_number(value, null, 0)}</div>`;
		} else {
			value = default_formatter(value, row, column, data);
		}
		if (data && data.bold) {
			return `<b>${value}</b>`;
		}
		return value;
	},
};
