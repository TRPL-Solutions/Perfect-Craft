// Copyright (c) 2026, TRPL Solutions and contributors
// For license information, please see license.txt

// Customers of a Sales Officer with a checkbox each (all ticked); Download / Share / WhatsApp /
// Email send the ledgers of the ticked customers only (see ledger_sharing_report.py).

const PC_LSR_METHOD = "pc_production.pc_production.report.ledger_sharing_report.ledger_sharing_report";

// Rows ticked in the table (the checkbox column), as report data rows.
function pc_lsr_ticked() {
	const report = frappe.query_report;
	const datatable = report.datatable;
	if (!datatable) return [];
	return datatable.rowmanager
		.getCheckedRows()
		.map((index) => report.data[cint(index)])
		.filter((row) => row && row.customer);
}

function pc_lsr_args(rows) {
	const report = frappe.query_report;
	return {
		company: report.get_filter_value("company"),
		customers: JSON.stringify(rows.map((r) => r.customer)),
		from_date: report.get_filter_value("from_date"),
		to_date: report.get_filter_value("as_on_date"),
	};
}

function pc_lsr_need_rows() {
	const rows = pc_lsr_ticked();
	if (!rows.length) {
		frappe.msgprint(__("Tick at least one customer."));
		return null;
	}
	return rows;
}

// Save a URL as a file without a popup (popup blockers allow only one window.open per click).
function pc_lsr_save(url) {
	const a = document.createElement("a");
	a.href = url;
	a.download = "";
	document.body.appendChild(a);
	a.click();
	a.remove();
}

function pc_lsr_download_zip() {
	const rows = pc_lsr_need_rows();
	if (!rows) return;
	open_url_post(`/api/method/${PC_LSR_METHOD}.download_ledgers_zip`, pc_lsr_args(rows));
}

// Share: the browser's share sheet (WhatsApp, Gmail, ...) with one PDF per ticked customer.
async function pc_lsr_share() {
	const rows = pc_lsr_need_rows();
	if (!rows) return;
	const probe = new File([""], "probe.pdf", { type: "application/pdf" });
	if (!navigator.canShare || !navigator.canShare({ files: [probe] })) {
		frappe.msgprint({
			title: __("Share not available"),
			message: __(
				"This browser cannot share files (sharing works on phones and on Chrome / Edge for Windows and Mac, over HTTPS). Use Download to get the PDFs instead."
			),
			primary_action: { label: __("Download ZIP"), action: () => pc_lsr_download_zip() },
		});
		return;
	}
	frappe.show_alert({ message: __("Preparing {0} ledger(s)...", [rows.length]), indicator: "blue" });
	const files = [];
	for (const row of rows) {
		const response = await fetch(row.ledger_url, { credentials: "same-origin" });
		if (!response.ok) {
			frappe.msgprint(__("Could not prepare the ledger of {0}.", [row.customer_name]));
			return;
		}
		const blob = await response.blob();
		files.push(new File([blob], `Ledger ${row.ac_code} ${row.customer_name}.pdf`, { type: "application/pdf" }));
	}
	// Sharing needs a fresh click: the PDFs took time to prepare.
	const dialog = new frappe.ui.Dialog({
		title: __("Share Ledgers"),
		fields: [{ fieldtype: "HTML", options: `<p>${__("{0} ledger PDF(s) ready.", [files.length])}</p>` }],
		primary_action_label: __("Share now"),
		primary_action: async () => {
			try {
				await navigator.share({ files, title: __("Account Ledgers") });
				dialog.hide();
			} catch (e) {
				if (e.name !== "AbortError") frappe.msgprint(__("Sharing failed: {0}", [e.message]));
			}
		},
	});
	dialog.show();
}

// WhatsApp: wa.me click-to-chat per customer; the PDF is downloaded to attach by hand.
function pc_lsr_whatsapp() {
	const rows = pc_lsr_need_rows();
	if (!rows) return;
	const report = frappe.query_report;
	const company = report.get_filter_value("company");
	const as_on = frappe.datetime.str_to_user(report.get_filter_value("as_on_date"));
	const esc = frappe.utils.escape_html;
	const lines = rows
		.map(
			(r, i) => `<tr>
				<td>${esc(r.customer_name)}</td><td class="text-right">${esc(r.balance)}</td><td>${esc(r.mobile || "")}</td>
				<td>${
					r.whatsapp_number
						? `<button class="btn btn-xs btn-success" data-lsr-row="${i}">${__("Open WhatsApp")}</button>`
						: `<span class="text-danger">${__("No valid mobile")}</span>`
				}</td></tr>`
		)
		.join("");
	const dialog = new frappe.ui.Dialog({
		title: __("Send Ledgers by WhatsApp"),
		size: "large",
		fields: [
			{
				fieldtype: "HTML",
				options: `<p class="text-muted small">${__(
					"Each button opens the customer's WhatsApp chat with a message and downloads the ledger PDF. Attach the PDF in the chat (WhatsApp links cannot carry files)."
				)}</p>
				<table class="table table-bordered table-sm"><thead><tr><th>${__("Customer")}</th><th class="text-right">${__(
					"Balance"
				)}</th><th>${__("Mobile")}</th><th></th></tr></thead><tbody>${lines}</tbody></table>`,
			},
		],
	});
	dialog.$wrapper.on("click", "[data-lsr-row]", (e) => {
		const r = rows[cint($(e.currentTarget).attr("data-lsr-row"))];
		const text = __("Dear {0}, your account balance with {1} as on {2} is {3}. Your ledger is attached.", [
			r.customer_name,
			company,
			as_on,
			r.balance,
		]);
		pc_lsr_save(r.ledger_url);
		window.open(`https://wa.me/${r.whatsapp_number}?text=${encodeURIComponent(text)}`, "_blank");
		$(e.currentTarget).removeClass("btn-success").addClass("btn-default").text(__("Opened"));
	});
	dialog.show();
}

function pc_lsr_email() {
	const rows = pc_lsr_need_rows();
	if (!rows) return;
	frappe.confirm(__("Email the ledger to {0} customer(s)?", [rows.length]), () =>
		frappe.call({
			method: `${PC_LSR_METHOD}.send_ledger_emails`,
			args: pc_lsr_args(rows),
			freeze: true,
			freeze_message: __("Preparing emails..."),
			callback: (r) => {
				const res = r.message || {};
				const esc = frappe.utils.escape_html;
				let message = __("Queued: {0}", [(res.sent || []).length]);
				if ((res.no_email || []).length) {
					message += `<br>${__("No email address")}: ${res.no_email.map(esc).join(", ")}`;
				}
				frappe.msgprint({ title: __("Ledger Emails"), message });
			},
		})
	);
}

frappe.query_reports["Ledger Sharing Report"] = {
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
			fieldname: "sales_person",
			label: __("Sales Officer"),
			fieldtype: "Autocomplete",
			reqd: 1,
			get_query: () => ({
				query: "pc_production.pc_production.report_utils.get_filter_options",
				params: { doctype: "Sales Person" },
			}),
		},
		{
			fieldname: "from_date",
			label: __("Ledger From Date"),
			fieldtype: "Date",
			default: erpnext.utils.get_fiscal_year(frappe.datetime.get_today(), true)[1],
			reqd: 1,
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
		// Inner toolbar buttons are cleared by the desk when another report opens.
		report.page.add_inner_button(__("Download PDFs"), pc_lsr_download_zip, __("Share / Send"));
		report.page.add_inner_button(__("Share"), pc_lsr_share, __("Share / Send"));
		report.page.add_inner_button(__("WhatsApp"), pc_lsr_whatsapp, __("Share / Send"));
		report.page.add_inner_button(__("Email"), pc_lsr_email, __("Share / Send"));

		// Print preview / PDF of the customer list (public/js/pc_report_print.bundle.js, table:
		// ledger_sharing_report.html).
		pc_report_print.setup(report, {
			title: "LEDGER SHARING REPORT",
			orientation: "Portrait",
			font_size: 9,
			subtitle: (ctx) => __("Sales Officer: {0}", [ctx.filters.sales_person || ""]),
			period: (filters) => ({
				from_date: filters.as_on_date,
				to_date: filters.as_on_date,
				label: __("As on {0}", [frappe.datetime.str_to_user(filters.as_on_date)]),
			}),
		});
	},

	get_datatable_options(options) {
		return Object.assign(options, { checkboxColumn: true });
	},

	after_datatable_render(datatable) {
		// All customers ticked by default; untick the ones not to send.
		datatable.rowmanager.checkAll(true);
	},

	formatter(value, row, column, data, default_formatter) {
		if (column.fieldname === "ledger_url" && data && data.ledger_url) {
			return `<a href="${encodeURI(data.ledger_url)}" target="_blank">${__("PDF")}</a>`;
		}
		if (column.fieldname === "balance") {
			return `<div style="text-align: right">${default_formatter(value, row, column, data)}</div>`;
		}
		return default_formatter(value, row, column, data);
	},
};
