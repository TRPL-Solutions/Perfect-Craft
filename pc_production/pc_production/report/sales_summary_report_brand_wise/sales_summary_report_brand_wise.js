// Copyright (c) 2026, TRPL Solutions and contributors
// For license information, please see license.txt

// pc_cws_multi (multi-select filters on report_utils.get_filter_options) comes from here.
{% include "pc_production/pc_production/report/city_wise_sales_report/city_wise_common.js" %}

frappe.query_reports["Sales Summary Report Brand Wise"] = {
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
			default: pc_bw_default_from_date(),
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
		// Sub-Category = Brand, Category = Item Group, SKU = size.
		pc_cws_multi("brand", __("Brand (Sub-Category)"), "Brand"),
		// Default Electrodes: set in onload (a MultiSelectList ignores df.default when the report
		// opens; Reset Filters uses it).
		Object.assign(pc_cws_multi("item_group", __("Category"), "Item Group"), {
			default: ["Electrodes"],
		}),
		pc_cws_multi("sku", __("SKU"), "SKU", () => ({
			item_group: frappe.query_report.get_filter_value("item_group") || [],
		})),
		{
			fieldname: "packing",
			label: __("Packing"),
			fieldtype: "Select",
			options: ["All", "Old (Hash)", "New (Red)"],
			default: "All",
			description: __(
				"Item Packing Type (Perfect Bridge); Old / New show only items of that packing"
			),
		},
		pc_cws_multi("city", __("City"), "City"),
		pc_cws_multi("territory", __("Region"), "Territory"),
		pc_cws_multi("area", __("Area"), "Area"),
		pc_cws_multi("sales_person", __("Sales Person"), "Sales Person"),
	],

	onload(report) {
		const category = report.get_filter("item_group");
		if (category && !(category.get_value() || []).length) {
			category.set_value(["Electrodes"]);
		}
		// Print preview / PDF of the rows and filters on screen (public/js/pc_report_print.bundle.js,
		// table: sales_summary_report_brand_wise.html).
		pc_report_print.setup(report, {
			title: "SALES SUMMARY REPORT BRAND WISE",
			orientation: "Landscape",
			font_size: 8,
			subtitle: __("Cartons"),
			filters: [
				["customer", "Customer"],
				["brand", "Brand (Sub-Category)"],
				["item_group", "Category"],
				["sku", "SKU"],
				["packing", "Packing"],
				["city", "City"],
				["territory", "Region"],
				["area", "Area"],
				["sales_person", "Sales Person"],
			],
		});
	},

	formatter(value, row, column, data, default_formatter) {
		if (!data) return default_formatter(value, row, column, data);
		// Brand heading: only its name.
		if (data.row_type === "brand" && column.fieldname !== "customer_name") return "";
		if (column.fieldtype === "Float" && value != null && value !== "") {
			// Whole cartons; averages to 1 decimal (a Float column never formats with 0 decimals).
			const decimals = column.fieldname === "average" || data.row_type === "average" ? 1 : 0;
			value = `<div style="text-align: right">${format_number(value, null, decimals)}</div>`;
		} else {
			value = default_formatter(value, row, column, data);
		}
		if (data.row_type === "brand") {
			return `<span class="pc-bw-brand pc-bw-brand-${
				(data.brand_index || 0) % 4
			}">${value}</span>`;
		}
		if (data.row_type !== "line") {
			return `<span class="pc-bw-foot pc-bw-${data.row_type}"><b>${value}</b></span>`;
		}
		return value;
	},

	after_datatable_render(datatable) {
		$(datatable.wrapper).addClass("pc-bw-report");
		if (document.getElementById("pc-bw-styles")) return;
		const bands = ["--bg-yellow", "--bg-blue", "--bg-green", "--bg-pink"];
		const rules = bands.map(
			(v, i) =>
				`.pc-bw-report .dt-row:has(.pc-bw-brand-${i}) .dt-cell { background-color: var(${v}); font-weight: 600; }`
		);
		rules.push(
			`.pc-bw-report .dt-row:has(.pc-bw-foot) .dt-cell { background-color: var(--subtle-fg); }`,
			`.pc-bw-report .dt-row:has(.pc-bw-total) .dt-cell { border-top: 2px solid var(--gray-500); }`
		);
		$("<style id='pc-bw-styles'>").text(rules.join("\n")).appendTo(document.head);
	},
};

function pc_bw_default_from_date() {
	// First day of the current fiscal year, else of the current month.
	const fiscal_year = frappe.boot.current_fiscal_year;
	return fiscal_year && fiscal_year[1] ? fiscal_year[1] : frappe.datetime.month_start();
}
