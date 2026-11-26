// Copyright (c) 2026, TRPL Solutions and contributors
// For license information, please see license.txt

const PC_AGEING_REPORT = "Ageing Report Single Account";

// Every query report shares one page, so the A/C header added above the table would stay when the
// user switches to another report. Show it only while this report's route is open (coming back
// to the report does not re-render it, so it is hidden / shown rather than removed).
function pc_ageing_toggle_header() {
	const route = frappe.get_route() || [];
	const here = route[0] === "query-report" && route[1] === PC_AGEING_REPORT;
	$(".pc-ageing-header").toggle(here);
}

frappe.query_reports[PC_AGEING_REPORT] = {
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
			// Single customer, searchable by A/C Code; not a Link (most report users cannot read
			// Customer).
			fieldname: "customer",
			label: __("Customer (A/C Code)"),
			fieldtype: "Autocomplete",
			reqd: 1,
			get_query: () => ({
				query: "pc_production.pc_production.report.ageing_report_single_account.ageing_report_single_account.get_customer_options",
			}),
		},
		{
			fieldname: "as_on_date",
			label: __("As On Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
	],

	onload(report) {
		// Once per page load: hide the header on other routes (see pc_ageing_toggle_header).
		if (!window.pc_ageing_route_hook) {
			frappe.router.on("change", pc_ageing_toggle_header);
			window.pc_ageing_route_hook = true;
		}
		// Print preview / PDF of the rows on screen (public/js/pc_report_print.bundle.js, table:
		// ageing_report_single_account.html). A/C header from the TOTAL row.
		const info = (data) => (data || []).find((r) => r && r.row_type === "total") || {};
		pc_report_print.setup(report, {
			title: "AGEING REPORT SINGLE ACCOUNT",
			orientation: "Portrait",
			font_size: 9,
			period: (filters, data) => ({
				from_date: filters.as_on_date,
				to_date: filters.as_on_date,
				label: __("As on {0}", [info(data).as_on || frappe.datetime.str_to_user(filters.as_on_date)]),
			}),
		});
	},

	after_datatable_render() {
		// A/C Code, A/C Title, A/C Balance above the table (also printed above the table).
		const report = frappe.query_report;
		const info = (report.data || []).find((r) => r && r.row_type === "total") || {};
		let $header = report.page.main.find(".pc-ageing-header");
		if (!$header.length) {
			$header = $(`<div class="pc-ageing-header"
				style="font-weight: 700; line-height: 1.6; padding: var(--padding-sm) var(--padding-md);"></div>`)
				.insertBefore(report.$report);
		}
		$header.html(
			[
				[__("A/C Code"), info.ac_code],
				[__("A/C Title"), info.ac_title],
				[__("A/C Balance"), info.ac_balance],
			]
				.map(([label, value]) => `${label} : ${frappe.utils.escape_html(value || "")}`)
				.join("<br>")
		);
		pc_ageing_toggle_header();
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
