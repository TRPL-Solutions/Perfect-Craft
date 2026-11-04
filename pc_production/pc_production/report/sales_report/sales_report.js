// Copyright (c) 2026, TRPL Solutions and contributors
// For license information, please see license.txt

frappe.query_reports["Sales Report"] = {
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
			label: __("Date From"),
			fieldtype: "Date",
			default: frappe.datetime.month_start(),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("Date To"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "report_type",
			label: __("Report Type"),
			fieldtype: "Select",
			options: ["Summary", "Detail"],
			default: "Detail",
			reqd: 1,
		},
		{
			fieldname: "control_account",
			label: __("Control A/c."),
			fieldtype: "Link",
			options: "Account",
			get_query: () => ({
				filters: [
					["company", "=", frappe.query_report.get_filter_value("company")],
					["root_type", "=", "Asset"],
					["account_type", "in", ["Receivable", ""]],
				],
			}),
			on_change: () => pc_sales_report_set_title("control_account", "control_account_title", "Account", "account_name"),
		},
		{
			fieldname: "control_account_title",
			label: __("Control A/c. Title"),
			fieldtype: "Data",
			read_only: 1,
			on_change: () => {},
		},
		{
			fieldname: "territory",
			label: __("Region"),
			fieldtype: "Link",
			options: "Territory",
		},
		{
			fieldname: "city",
			label: __("City"),
			fieldtype: "Data",
		},
		{
			fieldname: "area",
			label: __("Area"),
			fieldtype: "Data",
		},
		{
			fieldname: "sales_person",
			label: __("Sales Man"),
			fieldtype: "Link",
			options: "Sales Person",
		},
		{
			fieldname: "customer",
			label: __("A/c. Code"),
			fieldtype: "Link",
			options: "Customer",
			on_change: () => pc_sales_report_set_title("customer", "customer_title", "Customer", "customer_name"),
		},
		{
			fieldname: "customer_title",
			label: __("Account Title"),
			fieldtype: "Data",
			read_only: 1,
			on_change: () => {},
		},
		{
			fieldname: "sort_by",
			label: __("Sort By"),
			fieldtype: "Select",
			options: ["Name", "Amount", "Date"],
			default: "Name",
		},
		{
			fieldname: "sort_order",
			label: __("Sorting Order"),
			fieldtype: "Select",
			options: ["Ascending", "Descending"],
			default: "Ascending",
		},
		{
			fieldname: "sales_basis",
			label: __("Sales Basis"),
			fieldtype: "Select",
			options: ["Net Sales", "Gross Sales"],
			default: "Net Sales",
		},
		{
			fieldname: "include_returns",
			label: __("Include Returns"),
			// Select, not Check: unchecked (0) filter values are never sent to the server.
			fieldtype: "Select",
			options: ["Yes", "No"],
			default: "Yes",
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;

		if (data.row_type === "sales_person" && column.fieldname === "customer_name") {
			return `<b style="color: var(--blue-600); text-decoration: underline;">${value}</b>`;
		}
		if (data.row_type === "invoice_total" && column.fieldname === "item_name") {
			return `<div style="text-align: right;"><b>${value}</b></div>`;
		}
		if (data.bold) {
			return `<b>${value}</b>`;
		}
		return value;
	},

	onload(report) {
		// Restore titles when filters come pre-filled (route options / saved filters).
		pc_sales_report_set_title("control_account", "control_account_title", "Account", "account_name", false);
		pc_sales_report_set_title("customer", "customer_title", "Customer", "customer_name", false);
	},
};

function pc_sales_report_set_title(source, target, doctype, title_field, refresh = true) {
	const report = frappe.query_report;
	const name = report.get_filter_value(source);
	const apply = (title) => {
		report.get_filter(target).set_value(title || "");
		if (refresh) report.refresh();
	};

	if (!name) return apply("");

	frappe.db.get_value(doctype, name, title_field).then((r) => apply(r.message?.[title_field]));
}
