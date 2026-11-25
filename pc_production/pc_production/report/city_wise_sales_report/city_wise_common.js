// Copyright (c) 2026, TRPL Solutions and contributors
// For license information, please see license.txt

// Shared settings of City Wise Sales Report and the reports built on it (e.g. Interior Sindh City
// Wise Sales), pulled in with an include directive. Function declarations only: the file is evaluated
// once per report that includes it, in the page's global scope.

// options: exclude (filter fieldnames to drop), defaults ({fieldname: value}), print_title.
function pc_city_wise_settings(options) {
	options = options || {};
	const exclude = options.exclude || [];
	const defaults = options.defaults || {};
	const months = [
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

	const settings = {
		filters: [
			// Period first, like the client's Excel.
			{
				fieldname: "from_year",
				label: __("From Year"),
				fieldtype: "Select",
				options: pc_cws_years(),
				default: String(moment().year()),
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
				fieldname: "from_month",
				label: __("From Month"),
				fieldtype: "Select",
				options: months,
				default: months[pc_cws_default_start_month()],
				reqd: 1,
			},
			{
				fieldname: "to_month",
				label: __("To Month"),
				fieldtype: "Select",
				options: months,
				default: months[moment().month()],
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
				fieldname: "group_by",
				label: __("Group By"),
				fieldtype: "Select",
				options: ["City", "Customer"],
				default: "City",
				reqd: 1,
			},
			{
				fieldname: "chart",
				label: __("Chart"),
				fieldtype: "Select",
				options: ["Month Wise Total", "Top 10"],
				default: "Month Wise Total",
			},
			{
				fieldname: "print_filters",
				label: __("Print Filters"),
				fieldtype: "Check",
				default: 0,
				// Only changes the print layout; no need to re-run the report.
				on_change: () => {},
			},
			pc_cws_multi("city", __("City"), "City"),
			pc_cws_multi("territory", __("Region"), "Territory"),
			pc_cws_multi("area", __("Area"), "Area"),
			pc_cws_multi("sales_person", __("Sales Officer"), "Sales Person"),
			pc_cws_multi("brand", __("Brand"), "Brand"),
			pc_cws_multi("sku", __("SKU"), "SKU"),
			pc_cws_multi("customer", __("Customer"), "Customer"),
		],

		onload(report) {
			// Print preview / PDF of the rows and filters on screen (public/js/pc_report_print.bundle.js,
			// table: city_wise_sales_report.html).
			pc_report_print.setup(report, {
				title: (ctx) =>
					options.print_title ||
					(ctx.filters.group_by === "Customer"
						? __("Customer Wise Sales Report")
						: __("City Wise Sales Report")),
				orientation: "Landscape",
				font_size: 8,
				subtitle: __("Cartons"),
				period: pc_report_print.month_period,
				print_filters: "print_filters",
				filters: [
					["city", "City"],
					["territory", "Region"],
					["area", "Area"],
					["sales_person", "Sales Officer"],
					["brand", "Brand"],
					["sku", "SKU"],
					["customer", "Customer"],
				],
			});
		},

		formatter(value, row, column, data, default_formatter) {
			value = default_formatter(value, row, column, data);
			if (!data) return value;

			if (data.row_type === "month_total" || data.row_type === "monthly_average") {
				return `<span class="pc-cws-${data.row_type}">${value}</span>`;
			}
			if (column.fieldname === "rank") {
				return `<span class="text-muted">${value}</span>`;
			}
			return value;
		},

		after_datatable_render(datatable) {
			pc_cws_add_styles();
			// Column descriptions (e.g. the Per Month Avg formula) as header tooltips.
			for (const column of datatable.getColumns()) {
				if (column.description) {
					$(datatable.wrapper)
						.find(`.dt-cell--header-${column.colIndex}`)
						.attr("title", column.description);
				}
			}
		},
	};

	settings.filters = settings.filters
		.filter((df) => !exclude.includes(df.fieldname))
		.map((df) => (df.fieldname in defaults ? { ...df, default: defaults[df.fieldname] } : df));
	return settings;
}

// Not Link fields: the report is open to every desk user, and most have no permission on
// these doctypes (see report_utils.get_filter_options).
function pc_cws_multi(fieldname, label, doctype) {
	return {
		fieldname,
		label,
		fieldtype: "MultiSelectList",
		get_data: (txt) =>
			frappe
				.call({
					method: "pc_production.pc_production.report_utils.get_filter_options",
					args: { doctype, txt },
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

function pc_cws_add_styles() {
	if (document.getElementById("pc-cws-styles")) return;
	// Bold, shaded footer rows across the whole row.
	$("<style id='pc-cws-styles'>")
		.text(
			`.dt-row:has(.pc-cws-month_total) .dt-cell,
			.dt-row:has(.pc-cws-monthly_average) .dt-cell { background-color: var(--subtle-fg); font-weight: 600; }
			.dt-row:has(.pc-cws-month_total) .dt-cell { border-top: 2px solid var(--border-color); }`
		)
		.appendTo(document.head);
}

function pc_cws_default_start_month() {
	// First month of the current fiscal year, else January.
	const fiscal_year = frappe.boot.current_fiscal_year;
	return fiscal_year && fiscal_year[1] ? moment(fiscal_year[1]).month() : 0;
}

function pc_cws_years() {
	const current = moment().year();
	const years = [];
	for (let year = current - 5; year <= current + 1; year++) {
		years.push(String(year));
	}
	return years;
}
