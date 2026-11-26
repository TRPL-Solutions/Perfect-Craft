// Copyright (c) 2026, TRPL Solutions and contributors
// For license information, please see license.txt

// pc_cws_multi, pc_cws_years and pc_cws_default_start_month come from here.
{% include "pc_production/pc_production/report/city_wise_sales_report/city_wise_common.js" %}

const PC_YWS_MONTHS = [
	"January",
	"February",
	"March",
	"April",
	"May",
	"June",
	"July",
	"August",
	"September",
	"October",
	"November",
	"December",
];

frappe.query_reports["Year Wise Sale Summary"] = {
	filters: [
		// One continuous range: From Year + Month to To Year + Month (e.g. Jul 2025 - Jul 2026).
		{
			fieldname: "from_year",
			label: __("From Year"),
			fieldtype: "Select",
			options: pc_cws_years(),
			default: String(moment().subtract(1, "year").year()),
			reqd: 1,
		},
		{
			fieldname: "from_month",
			label: __("From Month"),
			fieldtype: "Select",
			options: PC_YWS_MONTHS,
			default: PC_YWS_MONTHS[moment().month()],
			reqd: 1,
		},
		{
			fieldname: "to_year",
			label: __("To Year"),
			fieldtype: "Select",
			options: pc_cws_years(),
			default: String(moment().year()),
			reqd: 1,
		},
		{
			fieldname: "to_month",
			label: __("To Month"),
			fieldtype: "Select",
			options: PC_YWS_MONTHS,
			default: PC_YWS_MONTHS[moment().month()],
			reqd: 1,
		},
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			// Single customer or all, searchable by A/C Code; not a Link (most report users cannot
			// read Customer).
			fieldname: "customer",
			label: __("Customer (A/C Code)"),
			fieldtype: "Autocomplete",
			get_query: () => ({
				query: "pc_production.pc_production.report.year_wise_sale_summary.year_wise_sale_summary.get_customer_options",
			}),
		},
		pc_cws_multi("city", __("City"), "City"),
		pc_cws_multi("territory", __("Region"), "Territory"),
		pc_cws_multi("area", __("Area"), "Area"),
		pc_cws_multi("sales_person", __("Sales Person"), "Sales Person"),
		pc_cws_multi("brand", __("Brand"), "Brand"),
		pc_cws_multi("sku", __("SKU"), "SKU"),
	],

	onload(report) {
		// Print preview / PDF of the rows and filters on screen (public/js/pc_report_print.bundle.js,
		// table: year_wise_sale_summary.html). Title, sales person and period come from the
		// TOTAL CTN row.
		const info = (ctx) => (ctx.data || []).find((r) => r && r.row_type === "total") || {};
		pc_report_print.setup(report, {
			title: (ctx) => info(ctx).report_title || __("BRAND WISE SALES"),
			orientation: "Portrait",
			font_size: 8,
			subtitle: (ctx) => {
				const sp = info(ctx).sales_person;
				return [__("Cartons"), sp ? __("S/O: {0}", [sp]) : ""].filter(Boolean).join("  ·  ");
			},
			period: (filters, data) => {
				const row = (data || []).find((r) => r && r.row_type === "total") || {};
				const month = (name) => Math.max(PC_YWS_MONTHS.indexOf(name), 0);
				const from = moment({ year: cint(filters.from_year), month: month(filters.from_month), day: 1 });
				const to = moment({ year: cint(filters.to_year), month: month(filters.to_month), day: 1 }).endOf(
					"month"
				);
				return {
					from_date: from.format("YYYY-MM-DD"),
					to_date: to.format("YYYY-MM-DD"),
					label: row.period_label || `${from.format("MMM YYYY")} – ${to.format("MMM YYYY")}`,
				};
			},
			filters: [
				["customer", "Customer"],
				["city", "City"],
				["territory", "Region"],
				["area", "Area"],
				["sales_person", "Sales Person"],
				["brand", "Brand"],
				["sku", "SKU"],
			],
		});
	},

	formatter(value, row, column, data, default_formatter) {
		if (column.fieldtype === "Float" && value != null && value !== "") {
			// Whole cartons, averages included (a Float column never formats with 0 decimals).
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
