// Copyright (c) 2026, TRPL Solutions and contributors
// For license information, please see license.txt

const PC_CWS_MONTHS = [
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

frappe.query_reports["City Wise Sales Report"] = {
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
			fieldname: "group_by",
			label: __("Group By"),
			fieldtype: "Select",
			options: ["City", "Customer"],
			default: "City",
			reqd: 1,
		},
		{
			fieldname: "from_year",
			label: __("From Year"),
			fieldtype: "Select",
			options: pc_cws_years(),
			default: String(pc_cws_default_start().year()),
			reqd: 1,
		},
		{
			fieldname: "from_month",
			label: __("From Month"),
			fieldtype: "Select",
			options: PC_CWS_MONTHS,
			default: PC_CWS_MONTHS[pc_cws_default_start().month()],
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
			options: PC_CWS_MONTHS,
			default: PC_CWS_MONTHS[moment().month()],
			reqd: 1,
		},
		pc_cws_multi("city", __("City"), "City"),
		pc_cws_multi("territory", __("Region"), "Territory"),
		pc_cws_multi("area", __("Area"), "Area"),
		pc_cws_multi("sales_person", __("Sales Officer"), "Sales Person"),
		pc_cws_multi("brand", __("Brand"), "Brand"),
		pc_cws_multi("sku", __("SKU"), "SKU"),
		{
			fieldname: "customer",
			label: __("Customer"),
			fieldtype: "Autocomplete",
			get_query: () => ({
				query: "pc_production.pc_production.report.city_wise_sales_report.city_wise_sales_report.get_filter_options",
				params: { doctype: "Customer" },
			}),
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && data.bold) {
			return `<b>${value}</b>`;
		}
		return value;
	},
};

// Not Link fields: the report is open to every desk user, and most have no permission on
// these doctypes (see city_wise_sales_report.get_filter_options).
function pc_cws_multi(fieldname, label, doctype) {
	return {
		fieldname,
		label,
		fieldtype: "MultiSelectList",
		get_data: (txt) =>
			frappe
				.call({
					method: "pc_production.pc_production.report.city_wise_sales_report.city_wise_sales_report.get_filter_options",
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

function pc_cws_default_start() {
	// First month of the current fiscal year, else January of this year.
	const fiscal_year = frappe.boot.current_fiscal_year;
	return fiscal_year && fiscal_year[1] ? moment(fiscal_year[1]) : moment().startOf("year");
}

function pc_cws_years() {
	const current = moment().year();
	const years = [];
	for (let year = current - 5; year <= current + 1; year++) {
		years.push(String(year));
	}
	return years;
}
