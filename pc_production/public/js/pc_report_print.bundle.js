// Copyright (c) 2026, TRPL Solutions and contributors
// For license information, please see license.txt

// Shared print engine of the PC Production script reports (loaded on every desk page through
// app_include_js). A report calls pc_report_print.setup(report, config) in its onload; "Print
// Report" (and Menu > Print / PDF) then open a full-screen preview of real A4 pages built from the
// rows and filters currently on screen, with Print (browser) and Download PDF (wkhtmltopdf, see
// report_print.py).
//
// Each report only supplies its config and its .html template. The template renders the table
// (colgroup, thead, tbody rows, optional notes after it) with the shared classes below; the engine
// adds the page header, page footer and theme, fits the font to the page width and splits the
// rows into pages. Template context: data, columns, filters, report, cfg (the config), pp (helpers).
//
// config:
//   title         string or fn(ctx) -> report title on the page
//   orientation   "Portrait" (default) | "Landscape"
//   font_size     table font size in pt (default 8); shrunk until every cell fits the width
//   subtitle      string or fn(ctx), shown after the period (e.g. "Cartons")
//   period        fn(filters, data) -> {from_date, to_date, label}; default: from_date / to_date
//   filters       [[fieldname, label], ...] listed in the header when set
//   print_filters fieldname of a Check filter: list the filters only when it is ticked
//
// Row classes for templates: pp-line (dotted line), pp-group (group heading), pp-subtotal
// (bold, ruled figures), pp-total (bold, ruled row), pp-grand (double underlined figures),
// pp-foot (bold, no rules), pp-empty. pp-keep-next keeps a row with the next one on the page
// (group headings), pp-keep-prev with the previous one (totals). Cell classes: pp-num, pp-c,
// pp-good, pp-bad, pp-label.

frappe.provide("pc_report_print");

(() => {
	const MM = 96 / 25.4; // CSS px per mm
	const SHEET = { Portrait: [210, 297], Landscape: [297, 210] }; // mm
	const MARGIN = { top: 8, side: 9, gap: 3, bottom: 6, footer: 5 }; // mm, kept in sync with report_print.py
	const MIN_FONT = 5; // pt
	const FIT_SLACK = 1.04; // text measured 4% wider than in Chrome (wkhtmltopdf rounds glyph advances)
	const FONT_FAMILY = "PC Print Sans";
	const FONT_URL = "/assets/pc_production/fonts/";
	const HEADER_METHOD = "pc_production.pc_production.report_print.get_print_header";
	const PDF_METHOD = "/api/method/pc_production.pc_production.report_print.get_report_pdf";

	const THEME = `
		.pp-doc { font-family: "${FONT_FAMILY}", Arial, Helvetica, sans-serif; color: #000; font-size: 8pt;
			line-height: 1.25; text-align: left; -webkit-print-color-adjust: exact; print-color-adjust: exact;
			/* The desk sets letter-spacing etc. on body: reset, or the preview is wider than the PDF. */
			letter-spacing: normal; word-spacing: normal; text-transform: none; font-feature-settings: normal;
			font-variant: normal; font-kerning: auto; -webkit-font-smoothing: auto;
			/* Unhinted (fractional) glyph widths in Chrome, as in wkhtmltopdf: same line breaks. */
			text-rendering: geometricPrecision; }
		.pp-doc table { border-collapse: collapse; border-spacing: 0; }
		.pp-doc * { box-sizing: border-box; }
		.pp-header { width: 100%; table-layout: fixed; }
		.pp-header td { vertical-align: top; padding: 0; border: none; }
		.pp-header .pp-h-side { width: 21%; font-size: 7.5pt; line-height: 1.4; }
		.pp-header .pp-h-right { text-align: right; }
		.pp-header .pp-h-muted { color: #555; }
		.pp-company { font-size: 14pt; font-weight: bold; text-decoration: underline; text-align: center; line-height: 1.2; }
		.pp-location { font-size: 9pt; font-weight: bold; text-align: center; margin-top: 1px; }
		.pp-title { font-size: 12pt; font-weight: bold; text-decoration: underline; text-align: center; margin-top: 3px; }
		.pp-period { font-size: 8.5pt; text-align: center; margin-top: 2px; }
		.pp-filters { font-size: 7pt; text-align: center; color: #333; margin-top: 2px; }
		/* Separate borders (inside the cells): a collapsed border sticks out half above the table and
		   wkhtmltopdf clips it at the top of every page. */
		.pp-doc table.pp-table { width: 100%; table-layout: fixed; border-collapse: separate; border-spacing: 0; }
		.pp-table thead { display: table-header-group; }
		.pp-table tr { page-break-inside: avoid; }
		.pp-table th, .pp-table td { padding: 2px 4px; vertical-align: top; text-align: left; word-wrap: break-word; }
		.pp-table thead th { background: #e3e3e3; font-weight: bold; vertical-align: bottom;
			border-top: 1.5px solid #000; border-bottom: 1.5px solid #000; border-right: 1px solid #8c8c8c; }
		.pp-table thead th:first-child { border-left: 1.5px solid #000; }
		.pp-table thead th:last-child { border-right: 1.5px solid #000; }
		.pp-table thead tr.pp-head-top th { text-align: center; }
		.pp-table thead tr.pp-head-top th[colspan] { border-bottom: 1px solid #8c8c8c; }
		.pp-table thead tr + tr th { border-top: none; }
		.pp-table thead tr + tr th:first-child { border-left: none; }
		.pp-table thead tr + tr th.pp-last-group { border-right: 1px solid #8c8c8c; }
		.pp-table thead th.pp-num, .pp-table thead tr.pp-head-top th.pp-num { text-align: right; }
		.pp-table thead th.pp-c, .pp-table thead tr.pp-head-top th.pp-c { text-align: center; }
		.pp-table td.pp-num { text-align: right; white-space: nowrap; }
		.pp-table td.pp-c { text-align: center; }
		.pp-table td.pp-label { text-align: right; }
		.pp-table tr.pp-line td { border-bottom: 1px dotted #8c8c8c; }
		.pp-table tr.pp-group td { font-weight: bold; text-decoration: underline; color: #1a3fb3; padding-top: 7px; font-size: 1.1em; }
		.pp-table tr.pp-subtotal td { font-weight: bold; padding-top: 3px; padding-bottom: 5px; }
		.pp-table tr.pp-subtotal td.pp-num { border-top: 1px solid #000; }
		.pp-table tr.pp-total td { font-weight: bold; border-top: 1px solid #000; }
		.pp-table tr.pp-grand td { font-weight: bold; padding-top: 5px; }
		.pp-table tr.pp-grand td.pp-num { border-top: 1.5px solid #000; border-bottom: 4px double #000; }
		.pp-table tr.pp-foot td { font-weight: bold; }
		.pp-table tr.pp-empty td { text-align: center; font-style: italic; padding: 18px; border: 1px dotted #8c8c8c; }
		.pp-table td.pp-good { color: #1e7b34; font-weight: bold; }
		.pp-table td.pp-bad { color: #b03a2e; font-style: italic; }
		.pp-notes { margin-top: 5px; padding-right: 5%; /* wkhtmltopdf draws long lines ~3% wider than it measures */ font-size: 6.8pt; color: #333; line-height: 1.45; }
		.pp-footer { width: 100%; table-layout: fixed; font-size: 6.5pt; color: #555; border-top: 0.5px solid #999; }
		.pp-footer td { padding: 2px 0 0 0; border: none; vertical-align: top; }
		.pp-footer .pp-f-center { text-align: center; }
		.pp-footer .pp-f-right { text-align: right; }
	`;

	const PREVIEW_CSS = `
		.pp-overlay { position: fixed; inset: 0; z-index: 1060; display: flex; flex-direction: column; background: #525659; }
		.pp-toolbar { flex: none; display: flex; align-items: center; gap: 8px; padding: 8px 16px; background: #323639;
			color: #f1f1f1; box-shadow: 0 1px 4px rgba(0, 0, 0, .4); }
		.pp-toolbar .pp-tb-title { font-weight: 600; margin-right: auto; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
		.pp-toolbar .pp-tb-info { color: #bbb; font-size: 12px; margin-right: 8px; white-space: nowrap; }
		.pp-toolbar .btn-group .btn.active { background: var(--gray-700); color: #fff; }
		.pp-pages { flex: 1; overflow: auto; padding: 24px 16px; }
		.pp-pages .pp-sheet { margin: 0 auto 24px auto; box-shadow: 0 2px 10px rgba(0, 0, 0, .5); }
		.pp-sheet { position: relative; background: #fff; overflow: hidden; }
		.pp-sheet .pp-sheet-footer { position: absolute; left: ${MARGIN.side}mm; right: ${MARGIN.side}mm; }
		.pp-measure { position: absolute; left: -100000px; top: 0; visibility: hidden; }
		body.pp-preview-open { overflow: hidden; }
	`;

	pc_report_print.setup = function (report, config) {
		const open = () => pc_report_print.open(report, config);
		report.page.set_primary_action(__("Print Report"), open, "printer");
		// Menu > Print / PDF would render the template without the engine.
		report.print_report = open;
		report.pdf_report = open;
	};

	pc_report_print.open = async function (report, config) {
		const template = report.report_settings && report.report_settings.html_format;
		if (!template) {
			frappe.throw(__("This report has no print template."));
		}
		const filters = report.get_filter_values(true);
		if (!filters) return;

		const data = report.get_data_for_print();
		const columns = report.datatable ? report.get_visible_columns() : report.columns || [];
		const period = (config.period || pc_report_print.date_period)(filters, data);
		frappe.dom.freeze(__("Preparing print preview..."));
		try {
			const [info] = await Promise.all([
				frappe.xcall(HEADER_METHOD, {
					company: filters.company,
					from_date: period.from_date,
					to_date: period.to_date,
				}),
				load_fonts(),
			]);
			const ctx = {
				report,
				config,
				filters,
				data,
				columns,
				template,
				period,
				info: info || {},
				printed_at: moment(),
				printed_by: frappe.session.user_fullname || frappe.session.user,
			};
			ctx.title = value_of(config.title, ctx) || report.report_name;
			new Preview(ctx).show();
		} finally {
			frappe.dom.unfreeze();
		}
	};

	// Default period: the From Date / To Date filters.
	pc_report_print.date_period = function (filters) {
		const fmt = (d) => (d ? moment(d).format("DD-MMM-YYYY") : "");
		return {
			from_date: filters.from_date,
			to_date: filters.to_date,
			label: `From : ${fmt(filters.from_date)}    To : ${fmt(filters.to_date)}`,
		};
	};

	// Month reports (From Year / To Year / From Month / To Month, see report_utils.get_period):
	// a From Month after the To Month runs into the next year.
	pc_report_print.month_period = function (filters, data) {
		const month = (name) => Math.max(moment(name || "January", "MMMM").month(), 0);
		const start = month(filters.from_month);
		const end = month(filters.to_month);
		const from_year = cint(filters.from_year) || moment().year();
		const to_year = (cint(filters.to_year) || from_year) + (start > end ? 1 : 0);
		const from = moment({ year: from_year, month: start, day: 1 });
		const to = moment({ year: to_year, month: end, day: 1 }).endOf("month");
		const row = (data || []).find((r) => r && r.period_label);
		return {
			from_date: from.format("YYYY-MM-DD"),
			to_date: to.format("YYYY-MM-DD"),
			label:
				(row && row.period_label) ||
				`${from.format("MMM YYYY")} – ${to.format("MMM YYYY")}`,
		};
	};

	// Helpers available to the templates as `pp`.
	const pp = {
		esc: (v) => frappe.utils.escape_html(v == null ? "" : String(v)),
		blank: (v) => v == null || v === "",
		num: (v, decimals) =>
			v == null || v === "" ? "" : format_number(flt(v), null, decimals || 0),
		pct: (v, decimals) =>
			v == null || v === ""
				? ""
				: `${format_number(flt(v), null, decimals == null ? 2 : decimals)}%`,
		is_num: (c) => ["Currency", "Float", "Int", "Percent"].includes(c && c.fieldtype),
		list: (v) => (Array.isArray(v) ? v.join(", ") : v || ""),
		// <colgroup>: fixed % per fieldname (widths), the other columns share what is left; scaled to 100%.
		colgroup(cols, widths, other) {
			widths = widths || {};
			const fixed = cols.reduce((sum, c) => sum + (widths[c.fieldname] || 0), 0);
			const free = cols.filter((c) => !widths[c.fieldname]).length;
			const share = other || (free ? Math.max(100 - fixed, free * 3) / free : 0);
			const raw = cols.map((c) => widths[c.fieldname] || share);
			const total = raw.reduce((a, b) => a + b, 0) || 1;
			return `<colgroup>${raw
				.map((w) => `<col style="width: ${((w * 100) / total).toFixed(3)}%;">`)
				.join("")}</colgroup>`;
		},
	};
	pc_report_print.helpers = pp;

	class Preview {
		constructor(ctx) {
			this.ctx = ctx;
			this.orientation = ctx.config.orientation === "Landscape" ? "Landscape" : "Portrait";
		}

		show() {
			add_style("pp-theme", THEME);
			add_style("pp-preview", PREVIEW_CSS);
			const ctx = this.ctx;
			this.$overlay = $(`
				<div class="pp-overlay" role="dialog" aria-modal="true">
					<div class="pp-toolbar">
						<span class="pp-tb-title">${pp.esc(ctx.title)}</span>
						<span class="pp-tb-info"></span>
						<div class="btn-group btn-group-sm" role="group">
							<button class="btn btn-default btn-sm" data-orientation="Portrait">${__("Portrait")}</button>
							<button class="btn btn-default btn-sm" data-orientation="Landscape">${__("Landscape")}</button>
						</div>
						<button class="btn btn-default btn-sm" data-action="print">
							${frappe.utils.icon("printer", "xs")} ${__("Print")}</button>
						<button class="btn btn-primary btn-sm" data-action="pdf">${__("Download PDF")}</button>
						<button class="btn btn-default btn-sm" data-action="close" title="${__("Close")} (Esc)">
							${frappe.utils.icon("close", "sm")}</button>
					</div>
					<div class="pp-pages"></div>
				</div>`).appendTo(document.body);
			$(document.body).addClass("pp-preview-open");

			this.$overlay.on("click", "[data-orientation]", (e) => {
				this.orientation = $(e.currentTarget).attr("data-orientation");
				this.render();
			});
			this.$overlay.on("click", "[data-action=print]", () => this.print());
			this.$overlay.on("click", "[data-action=pdf]", () => this.download_pdf());
			this.$overlay.on("click", "[data-action=close]", () => this.close());
			this.on_key = (e) => e.key === "Escape" && this.close();
			document.addEventListener("keydown", this.on_key);
			this.on_resize = frappe.utils.debounce(() => this.zoom(), 150);
			window.addEventListener("resize", this.on_resize);
			this.render();
		}

		close() {
			document.removeEventListener("keydown", this.on_key);
			window.removeEventListener("resize", this.on_resize);
			$(document.body).removeClass("pp-preview-open");
			this.$overlay.remove();
		}

		render() {
			this.$overlay.find("[data-orientation]").each((i, el) => {
				$(el).toggleClass("active", $(el).attr("data-orientation") === this.orientation);
			});
			const [w, h] = SHEET[this.orientation];
			this.content_w = w - 2 * MARGIN.side;

			const measure = $(`<div class="pp-doc pp-measure"></div>`)
				.css("width", `${this.content_w}mm`)
				.appendTo(document.body)[0];
			try {
				measure.innerHTML = this.header_html();
				this.header_h =
					Math.ceil((measure.firstElementChild.offsetHeight / MM) * 10) / 10 + 0.5;

				measure.innerHTML = this.body_html();
				this.font_size = fit_font(measure, this.ctx.config.font_size || 8);
				this.body = measure.innerHTML;

				const body_h =
					(h - MARGIN.top - this.header_h - MARGIN.gap - this.footer_space()) * MM;
				this.pages = paginate(measure, body_h);
			} finally {
				measure.remove();
			}

			const $pages = this.$overlay.find(".pp-pages").empty();
			this.pages.forEach((page, i) =>
				$pages.append(this.sheet_html(page, i + 1, this.pages.length))
			);
			this.$overlay
				.find(".pp-tb-info")
				.text(
					`${__("A4 {0}", [__(this.orientation)])} · ${__("{0} page(s)", [
						this.pages.length,
					])} · ${__("font {0}pt", [this.font_size])}`
				);
			this.zoom();
		}

		zoom() {
			const $pages = this.$overlay.find(".pp-pages");
			const sheet_px = SHEET[this.orientation][0] * MM;
			const zoom = Math.min(1, ($pages.innerWidth() - 32) / sheet_px);
			$pages.find(".pp-sheet").css("zoom", zoom > 0 ? zoom : 1);
		}

		footer_space() {
			return MARGIN.footer + MARGIN.bottom;
		}

		body_html() {
			const ctx = this.ctx;
			return frappe.render_template(ctx.template, {
				data: ctx.data,
				columns: ctx.columns,
				filters: ctx.filters,
				report: ctx.report,
				cfg: ctx.config,
				pp,
			});
		}

		header_html() {
			const ctx = this.ctx;
			const info = ctx.info;
			const company = [
				info.company_name || ctx.filters.company || "",
				info.fiscal_year || "",
			]
				.join(" ")
				.trim();
			const location = info.company_location || info.company_city || "";
			const subtitle = value_of(ctx.config.subtitle, ctx);
			const period = [ctx.period.label, subtitle].filter(Boolean).join("  ·  ");
			const applied = this.applied_filters();
			return `
				<table class="pp-header"><tr>
					<td class="pp-h-side">${ctx.printed_at.format("DD-MMM-YYYY")}<br>${ctx.printed_at.format(
				"h:mm:ss A"
			)}</td>
					<td>
						<div class="pp-company">${pp.esc(company)}</div>
						${location ? `<div class="pp-location">${pp.esc(location)}</div>` : ""}
						<div class="pp-title">${pp.esc(ctx.title)}</div>
						<div class="pp-period">${pp.esc(period).replace(/ {2,}/g, (s) => "&nbsp;".repeat(s.length))}</div>
						${applied.length ? `<div class="pp-filters">${pp.esc(applied.join("   |   "))}</div>` : ""}
					</td>
					<td class="pp-h-side pp-h-right"><span class="pp-h-muted">${__("Printed by")}</span><br>${pp.esc(
				ctx.printed_by
			)}</td>
				</tr></table>`;
		}

		applied_filters() {
			const { config, filters } = this.ctx;
			const toggle = config.print_filters;
			if (toggle && (!filters[toggle] || filters[toggle] === "0")) return [];
			return (config.filters || [])
				.filter(([fieldname]) => pp.list(filters[fieldname]))
				.map(([fieldname, label]) => `${__(label)}: ${pp.list(filters[fieldname])}`);
		}

		footer_html(page, pages) {
			const ctx = this.ctx;
			const number =
				page == null
					? `${__("Page")} <span class="page"></span> ${__(
							"of"
					  )} <span class="topage"></span>`
					: __("Page {0} of {1}", [page, pages]);
			return `
				<table class="pp-footer"><tr>
					<td>${__("Generated by Thru ERP")}</td>
					<td class="pp-f-center">${pp.esc(ctx.title)}</td>
					<td class="pp-f-right">${number}</td>
				</tr></table>`;
		}

		sheet_html(page_html, page, pages) {
			const [w, h] = SHEET[this.orientation];
			return `
				<div class="pp-doc pp-sheet" style="width: ${w}mm; height: ${h}mm; padding: ${MARGIN.top}mm ${
				MARGIN.side
			}mm 0 ${MARGIN.side}mm;">
					<div style="height: ${this.header_h}mm; overflow: hidden;">${this.header_html()}</div>
					<div style="height: ${MARGIN.gap}mm;"></div>
					<div>${page_html}</div>
					<div class="pp-sheet-footer" style="bottom: ${MARGIN.bottom}mm; height: ${MARGIN.footer}mm;">
						${this.footer_html(page, pages)}</div>
				</div>`;
		}

		// Browser print: the preview's sheets, one per A4 page.
		print() {
			const [w, h] = SHEET[this.orientation];
			const sheets = this.pages
				.map((page, i) => this.sheet_html(page, i + 1, this.pages.length))
				.join("");
			const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${pp.esc(
				this.filename("")
			)}</title>
				<style>${font_faces(location.origin + FONT_URL)}${THEME}
					@page { size: A4 ${this.orientation.toLowerCase()}; margin: 0; }
					html, body { margin: 0; padding: 0; background: #fff; }
					.pp-sheet { position: relative; overflow: hidden; page-break-after: always; break-after: page; }
					.pp-sheet:last-child { page-break-after: auto; break-after: auto; }
					.pp-sheet .pp-sheet-footer { position: absolute; left: ${MARGIN.side}mm; right: ${MARGIN.side}mm; }
					.pp-sheet { width: ${w}mm; height: ${h}mm; }
				</style></head><body>${sheets}</body></html>`;

			$("#pp-print-frame").remove();
			const frame =
				$(`<iframe id="pp-print-frame" title="print" style="position: fixed; right: 0; bottom: 0;
				width: 0; height: 0; border: 0;"></iframe>`).appendTo(document.body)[0];
			const doc = frame.contentWindow.document;
			doc.open();
			doc.write(html);
			doc.close();
			const go = () => {
				frame.contentWindow.focus();
				frame.contentWindow.print();
			};
			(doc.fonts ? doc.fonts.ready : Promise.resolve()).then(() => setTimeout(go, 50));
		}

		// Download PDF: the same body as one flowing document; wkhtmltopdf breaks the pages, repeats
		// the table header and puts the page header / footer (with page numbers) on every page.
		pdf_html() {
			return `<!DOCTYPE html><html><head><meta charset="utf-8">
				<style>${THEME}
					html, body { margin: 0 !important; padding: 0 !important; background: #fff; }
					.print-format { padding: 0 !important; margin: 0 !important; max-width: none !important;
						min-height: 0 !important; width: auto !important; }
					/* wkhtmltopdf bottom-aligns the header in the top margin: the gap goes below it. */
					.pp-pdf-header { padding-bottom: ${MARGIN.gap}mm; }
					.pp-pdf-footer { padding-top: 1mm; }
				</style></head><body>
				<div id="header-html"><div class="pp-doc pp-pdf-header">${this.header_html()}</div></div>
				<div class="pp-doc">${this.body}</div>
				<div id="footer-html"><div class="pp-doc pp-pdf-footer">${this.footer_html()}</div></div>
				</body></html>`;
		}

		filename(extension = ".pdf") {
			const { period, title } = this.ctx;
			const fmt = (d) => (d ? moment(d).format("DD.MM.YYYY") : "");
			const range = [fmt(period.from_date), fmt(period.to_date)].filter(Boolean).join("-");
			return `${title}${range ? ` ${range}` : ""}${extension}`;
		}

		async download_pdf() {
			const $button = this.$overlay.find("[data-action=pdf]").prop("disabled", true);
			try {
				const response = await fetch(PDF_METHOD, {
					method: "POST",
					headers: {
						"X-Frappe-CSRF-Token": frappe.csrf_token,
						"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
					},
					body: new URLSearchParams({
						report_name: this.ctx.report.report_name,
						html: this.pdf_html(),
						orientation: this.orientation,
						margin_top: (MARGIN.top + this.header_h + MARGIN.gap).toFixed(1),
						margin_bottom: this.footer_space().toFixed(1),
						filename: this.filename(),
					}),
				});
				const type = response.headers.get("Content-Type") || "";
				if (!response.ok || !type.includes("pdf")) {
					throw new Error(await error_message(response));
				}
				const url = URL.createObjectURL(await response.blob());
				const link = Object.assign(document.createElement("a"), {
					href: url,
					download: this.filename(),
				});
				document.body.appendChild(link);
				link.click();
				link.remove();
				setTimeout(() => URL.revokeObjectURL(url), 10000);
			} catch (e) {
				frappe.msgprint({
					title: __("PDF failed"),
					message: pp.esc(e.message || e),
					indicator: "red",
				});
			} finally {
				$button.prop("disabled", false);
			}
		}
	}

	// Largest font (0.25pt steps) at which no number, and no column header word, is wider than its
	// column. Leaves the measure element rendered at that size.
	function fit_font(root, start) {
		const table = root.querySelector("table.pp-table");
		if (!table) return start;
		let size = start;
		for (;;) {
			table.style.fontSize = `${size}pt`;
			if (size <= MIN_FONT || fits(table)) return size;
			size = Math.max(MIN_FONT, size - 0.25);
		}
	}

	function fits(table) {
		if (table.scrollWidth > table.parentElement.clientWidth + 1) return false;
		const range = document.createRange();
		for (const cell of table.querySelectorAll("td.pp-num, th")) {
			const style = getComputedStyle(cell);
			const room =
				cell.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
			let need;
			if (cell.tagName === "TH") {
				need = longest_word(cell, range);
			} else {
				range.selectNodeContents(cell);
				need = range.getBoundingClientRect().width;
			}
			if (need * FIT_SLACK > room + 0.5) return false;
		}
		return true;
	}

	// Width of the longest word of a header cell (headers wrap between words, not inside them).
	function longest_word(cell, range) {
		let widest = 0;
		const walker = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
		while (walker.nextNode()) {
			const node = walker.currentNode;
			const text = node.nodeValue;
			const re = /\S+/g;
			let m;
			while ((m = re.exec(text))) {
				range.setStart(node, m.index);
				range.setEnd(node, m.index + m[0].length);
				widest = Math.max(widest, range.getBoundingClientRect().width);
			}
		}
		return widest;
	}

	// Splits the rendered table (and anything after it) into pages of at most `avail` px each;
	// every page repeats the colgroup and thead. Rows are never split.
	function paginate(root, avail) {
		const table = root.querySelector("table.pp-table");
		if (!table) return [root.innerHTML];
		const thead = table.tHead;
		const head_h = thead ? thead.getBoundingClientRect().height : 0;
		const shell = table.cloneNode(false).outerHTML.replace(/<\/table>$/, "");
		const colgroup = table.querySelector("colgroup");
		const top = `${shell}${colgroup ? colgroup.outerHTML : ""}${
			thead ? thead.outerHTML : ""
		}<tbody>`;
		const rows = table.tBodies.length ? Array.from(table.tBodies[0].rows) : [];
		const heights = new Map(rows.map((r) => [r, r.getBoundingClientRect().height]));
		const sum = (list) => list.reduce((a, r) => a + heights.get(r), 0);

		const groups = [];
		let current = [];
		let used = head_h;
		for (const row of rows) {
			const h = heights.get(row);
			if (current.length && used + h > avail) {
				const carry = [];
				// A heading stays with its first row; a total with the row above it.
				while (
					current.length > 1 &&
					current[current.length - 1].classList.contains("pp-keep-next")
				) {
					carry.unshift(current.pop());
				}
				let pull = row.classList.contains("pp-keep-prev");
				while (pull && current.length > 1 && !carry.length) {
					const moved = current.pop();
					carry.unshift(moved);
					pull = moved.classList.contains("pp-keep-prev");
				}
				groups.push(current);
				current = carry;
				used = head_h + sum(carry);
			}
			current.push(row);
			used += h;
		}
		if (current.length || !groups.length) groups.push(current);

		const pages = groups.map(
			(g) => `${top}${g.map((r) => r.outerHTML).join("")}</tbody></table>`
		);

		// Notes etc. after the table: on the last page when they fit, else on a page of their own.
		const after = Array.from(root.children).filter(
			(el) => el !== table && el.compareDocumentPosition(table) & 2
		);
		if (after.length) {
			const extra = after.reduce((a, el) => a + outer_height(el), 0);
			const html = after.map((el) => el.outerHTML).join("");
			if (used + extra <= avail) pages[pages.length - 1] += html;
			else pages.push(html);
		}
		return pages;
	}

	function outer_height(el) {
		const style = getComputedStyle(el);
		return (
			el.getBoundingClientRect().height +
			parseFloat(style.marginTop) +
			parseFloat(style.marginBottom)
		);
	}

	function value_of(value, ctx) {
		return typeof value === "function" ? value(ctx) : value;
	}

	function font_faces(base) {
		return [
			["normal", "LiberationSans-Regular.ttf"],
			["bold", "LiberationSans-Bold.ttf"],
		]
			.map(
				([weight, file]) =>
					`@font-face { font-family: "${FONT_FAMILY}"; font-weight: ${weight}; font-style: normal;
					src: url("${base}${file}") format("truetype"); }`
			)
			.join("\n");
	}

	function load_fonts() {
		add_style("pp-fonts", font_faces(FONT_URL));
		if (!document.fonts) return Promise.resolve();
		return Promise.all([
			document.fonts.load(`8pt "${FONT_FAMILY}"`),
			document.fonts.load(`bold 8pt "${FONT_FAMILY}"`),
		]).catch(() => null);
	}

	function add_style(id, css) {
		if (!document.getElementById(id)) {
			$("<style>").attr("id", id).text(css).appendTo(document.head);
		}
	}

	async function error_message(response) {
		try {
			const r = await response.json();
			const messages = r._server_messages ? JSON.parse(r._server_messages) : [];
			const text = messages.map((m) => {
				try {
					return JSON.parse(m).message;
				} catch {
					return m;
				}
			});
			return $("<div>")
				.html(text.join("\n") || r.exception || r.exc_type || response.statusText)
				.text();
		} catch {
			return `${response.status} ${response.statusText}`;
		}
	}
})();
