// Copyright (c) 2026, TRPL Solutions and contributors
// For license information, please see license.txt

frappe.query_reports["Sales Person Target Achievement"] = {
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
			fieldname: "fiscal_year",
			label: __("Fiscal Year"),
			fieldtype: "Autocomplete",
			get_query: () => pc_target_achievement_options("Fiscal Year"),
			on_change: () => pc_target_achievement_fit_dates_to_fiscal_year(),
		},
		{
			fieldname: "sales_person",
			label: __("Sales Person"),
			fieldtype: "Autocomplete",
			get_query: () => pc_target_achievement_options("Sales Person"),
		},
		{
			fieldname: "item_group",
			label: __("Item Group"),
			fieldtype: "Link",
			options: "Item Group",
		},
		{
			fieldname: "territory",
			label: __("Territory"),
			fieldtype: "Autocomplete",
			get_query: () => pc_target_achievement_options("Territory"),
		},
		{
			fieldname: "group_by",
			label: __("Group By"),
			fieldtype: "Select",
			options: ["Sales Person", "Sales Person and Item Group"],
			default: "Sales Person",
		},
	],

	onload(report) {
		// Print preview / PDF of the rows and filters on screen (public/js/pc_report_print.bundle.js,
		// table: sales_person_target_achievement.html).
		pc_report_print.setup(report, {
			title: __("Sales Person Target Achievement"),
			orientation: "Portrait",
			font_size: 8,
			filters: [
				["fiscal_year", "Fiscal Year"],
				["sales_person", "Sales Person"],
				["item_group", "Item Group"],
				["territory", "Territory"],
			],
		});
	},

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;

		if (column.fieldname === "remarks" && data.remarks) {
			const color = {
				Received: "var(--green-600)",
				"Partially Received": "var(--orange-600)",
				"Not Received": "var(--red-600)",
			}[data.remarks];
			if (color) value = `<span style="color: ${color};">${value}</span>`;
		}
		if (data.bold) {
			return `<b>${value}</b>`;
		}
		return value;
	},
};

// Not Link fields: most users have no permission on these doctypes (see get_filter_options).
function pc_target_achievement_options(doctype) {
	return {
		query: "pc_production.pc_production.report.sales_person_target_achievement.sales_person_target_achievement.get_filter_options",
		params: { doctype },
	};
}

function pc_target_achievement_fit_dates_to_fiscal_year() {
	// Dates must lie within the selected Fiscal Year; move them there when they don't.
	const report = frappe.query_report;
	const fiscal_year = report.get_filter_value("fiscal_year");
	if (!fiscal_year) return report.refresh();

	frappe
		.xcall(
			"pc_production.pc_production.report.sales_person_target_achievement.sales_person_target_achievement.get_fiscal_year_dates",
			{ fiscal_year }
		)
		.then((fy) => {
			fy = fy || {};
			const from_date = report.get_filter_value("from_date");
			const to_date = report.get_filter_value("to_date");
			if (
				fy.year_start_date &&
				(from_date < fy.year_start_date || to_date > fy.year_end_date)
			) {
				report.set_filter_value({
					from_date: fy.year_start_date,
					to_date: fy.year_end_date,
				});
			} else {
				report.refresh();
			}
		});
}
