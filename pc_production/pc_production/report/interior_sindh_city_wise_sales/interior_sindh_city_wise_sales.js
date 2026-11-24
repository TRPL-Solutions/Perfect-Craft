// Copyright (c) 2026, TRPL Solutions and contributors
// For license information, please see license.txt

// City Wise Sales Report's filters and screen settings, without Group By (always Customer here)
// and with Region defaulting to Interior Sindh.
{% include "pc_production/pc_production/report/city_wise_sales_report/city_wise_common.js" %}

frappe.query_reports["Interior Sindh City Wise Sales"] = pc_city_wise_settings({
	exclude: ["group_by"],
	defaults: { territory: ["Interior Sindh"] },
	print_title: "Interior Sindh – City Wise Sales",
});
