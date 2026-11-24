// Copyright (c) 2026, TRPL Solutions and contributors
// For license information, please see license.txt

{% include "pc_production/pc_production/report/city_wise_sales_report/city_wise_common.js" %}

frappe.query_reports["City Wise Sales Report"] = pc_city_wise_settings();
