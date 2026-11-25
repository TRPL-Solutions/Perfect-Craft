// Copyright (c) 2026, TRPL Solutions and contributors
// For license information, please see license.txt

const PC_SKU_MONTHS = [
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
const PC_SKU_OPTIONS = "pc_production.pc_production.report_utils.get_filter_options";
const PC_SKU_FOOTER = ["total", "average", "max", "min", "share"];

frappe.query_reports["SKU Wise Sales Analysis"] = {
	filters: [
		// Period first, like the client's Excel.
		pc_sku_select("from_year", __("From Year"), pc_sku_years(), String(moment().year())),
		pc_sku_select("to_year", __("To Year"), pc_sku_years(), String(moment().year())),
		pc_sku_select(
			"from_month",
			__("From Month"),
			PC_SKU_MONTHS,
			PC_SKU_MONTHS[pc_sku_default_start_month()]
		),
		pc_sku_select("to_month", __("To Month"), PC_SKU_MONTHS, PC_SKU_MONTHS[moment().month()]),
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		// Sub Category = Brand, SKU = size.
		pc_sku_multi("brand", __("Sub Category (Brand)"), "Brand"),
		pc_sku_multi("item_group", __("Item Group"), "Item Group"),
		pc_sku_multi("sku", __("SKU"), "SKU", () => ({
			item_group: frappe.query_report.get_filter_value("item_group") || [],
		})),
		{
			fieldname: "chart",
			label: __("Chart"),
			fieldtype: "Select",
			options: ["By Brand (stacked)", "By SKU"],
			default: "By Brand (stacked)",
		},
		{
			fieldname: "print_filters",
			label: __("Print Filters"),
			fieldtype: "Check",
			default: 0,
			// Only changes the print layout; no need to re-run the report.
			on_change: () => {},
		},
		pc_sku_multi("customer", __("Customer"), "Customer"),
		pc_sku_multi("city", __("City"), "City"),
		pc_sku_multi("territory", __("Region"), "Territory"),
		pc_sku_multi("area", __("Area"), "Area"),
		pc_sku_multi("sales_person", __("Sales Officer"), "Sales Person"),
	],

	onload(report) {
		// Print preview / PDF of the rows and filters on screen (public/js/pc_report_print.bundle.js,
		// table: sku_wise_sales_analysis.html).
		pc_report_print.setup(report, {
			title: __("SKU Wise Sales Analysis"),
			orientation: "Landscape",
			font_size: 8,
			subtitle: __("Brand × SKU, cartons"),
			period: pc_report_print.month_period,
			print_filters: "print_filters",
			filters: [
				["brand", "Sub Category"],
				["sku", "SKU"],
				["item_group", "Item Group"],
				["customer", "Customer"],
				["city", "City"],
				["territory", "Region"],
				["area", "Area"],
				["sales_person", "Sales Officer"],
			],
		});
	},

	formatter(value, row, column, data, default_formatter) {
		if (
			data &&
			data.row_type === "share" &&
			pc_sku_is_value_column(column) &&
			value != null &&
			value !== ""
		) {
			value = `${format_number(value, null, 1)}%`;
		} else {
			value = default_formatter(value, row, column, data);
		}
		if (!data) return value;

		if (PC_SKU_FOOTER.includes(data.row_type)) {
			return `<span class="pc-sku-footer pc-sku-footer-${data.row_type}">${value}</span>`;
		}
		if (column.fieldname === "sr") {
			return `<span class="text-muted">${value}</span>`;
		}
		// Best and worst month per column (only where months differ).
		const extremes = pc_sku_extremes(column.fieldname);
		if (data.row_type === "month" && extremes && extremes.max !== extremes.min) {
			const raw = data[column.fieldname];
			if (Math.abs(raw - extremes.max) < 0.0005)
				return `<span class="pc-sku-best">${value}</span>`;
			if (Math.abs(raw - extremes.min) < 0.0005)
				return `<span class="pc-sku-worst">${value}</span>`;
		}
		return value;
	},

	after_datatable_render(datatable) {
		const wrapper = $(datatable.wrapper).addClass("pc-sku-report");
		const rules = [
			`.pc-sku-report .dt-row:has(.pc-sku-footer) .dt-cell { background-color: var(--subtle-fg); font-weight: 600; }`,
			`.pc-sku-report .dt-row:has(.pc-sku-footer-total) .dt-cell { border-top: 2px solid var(--gray-500); }`,
			`.pc-sku-best { color: var(--green-600); font-weight: 600; }`,
			`.pc-sku-worst { color: var(--red-600); font-weight: 600; }`,
		];
		for (const column of datatable.getColumns()) {
			// Two-level header is not possible on screen: tint each brand's block instead,
			// and show the full Brand + SKU as the header tooltip.
			if (column.brand_index != null && column.brand_index % 2 === 0) {
				rules.push(
					`.pc-sku-report .dt-cell--col-${column.colIndex}:not(.dt-cell--header) { background-color: var(--blue-50); }`
				);
			}
			if (column.description) {
				wrapper
					.find(`.dt-cell--header-${column.colIndex}`)
					.attr("title", column.description);
			}
		}
		$("#pc-sku-styles").remove();
		$("<style id='pc-sku-styles'>").text(rules.join("\n")).appendTo(document.head);
	},
};

function pc_sku_is_value_column(column) {
	return column && column.fieldtype === "Float";
}

function pc_sku_extremes(fieldname) {
	const rows = (frappe.query_report && frappe.query_report.data) || [];
	const max = rows.find((r) => r.row_type === "max");
	const min = rows.find((r) => r.row_type === "min");
	if (!max || !min || max[fieldname] == null) return null;
	return { max: max[fieldname], min: min[fieldname] };
}

function pc_sku_select(fieldname, label, options, value) {
	return { fieldname, label, fieldtype: "Select", options, default: value, reqd: 1 };
}

// Not Link fields: the report is open to every desk user, and most have no permission on
// these doctypes (see report_utils.get_filter_options).
function pc_sku_multi(fieldname, label, doctype, extra_args) {
	return {
		fieldname,
		label,
		fieldtype: "MultiSelectList",
		get_data: (txt) =>
			frappe
				.call({
					method: PC_SKU_OPTIONS,
					args: { doctype, txt, ...(extra_args ? extra_args() : {}) },
				})
				.then((r) =>
					(r.message || []).map((option) =>
						typeof option === "string"
							? { value: option, description: "" }
							: { value: option.value, description: option.label || "" }
					)
				),
	};
}

function pc_sku_default_start_month() {
	// First month of the current fiscal year, else January.
	const fiscal_year = frappe.boot.current_fiscal_year;
	return fiscal_year && fiscal_year[1] ? moment(fiscal_year[1]).month() : 0;
}

function pc_sku_years() {
	const current = moment().year();
	const years = [];
	for (let year = current - 5; year <= current + 1; year++) {
		years.push(String(year));
	}
	return years;
}
