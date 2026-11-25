// Copyright (c) 2026, TRPL Solutions and contributors
// For license information, please see license.txt

frappe.query_reports["Recovery Report"] = {
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
			fieldname: "sales_person",
			label: __("Sales Man"),
			fieldtype: "Autocomplete",
			get_query: () => pc_recovery_options("Sales Person"),
		},
		{
			fieldname: "territory",
			label: __("Region"),
			fieldtype: "Autocomplete",
			get_query: () => pc_recovery_options("Territory"),
		},
		{
			fieldname: "customer",
			label: __("Customer"),
			fieldtype: "Autocomplete",
			get_query: () => pc_recovery_options("Customer"),
		},
		{
			fieldname: "debtors_account",
			label: __("Debtors A/c."),
			fieldtype: "Autocomplete",
			get_query: () =>
				pc_recovery_options("Account", {
					company: frappe.query_report.get_filter_value("company"),
				}),
		},
	],

	onload(report) {
		// Print preview / PDF of the rows and filters on screen (public/js/pc_report_print.bundle.js,
		// table: recovery_print_layout.html).
		pc_report_print.setup(report, {
			title: __("Recovery Report"),
			orientation: "Portrait",
			font_size: 8.5,
			filters: [
				["sales_person", "Sales Man"],
				["territory", "Region"],
				["customer", "Customer"],
				["debtors_account", "Debtors A/c."],
			],
		});
	},

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;

		if (data.row_type === "sales_person" && column.fieldname === "customer_name") {
			return `<b style="color: var(--blue-600); text-decoration: underline;">${value}</b>`;
		}
		if (data.bold) {
			return `<b>${value}</b>`;
		}
		return value;
	},
};

// Not Link fields: the report is open to every desk user, and most have no permission on
// these doctypes (see recovery_report.get_filter_options).
function pc_recovery_options(doctype, params = {}) {
	return {
		query: "pc_production.pc_production.report.recovery_report.recovery_report.get_filter_options",
		params: { doctype, ...params },
	};
}
