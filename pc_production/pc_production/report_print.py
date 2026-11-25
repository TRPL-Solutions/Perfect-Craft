# Copyright (c) 2026, TRPL Solutions and contributors
# For license information, please see license.txt

"""Server side of the shared report print engine (public/js/pc_report_print.bundle.js).

get_print_header  Company name, fiscal year(s) and location for the page header.
get_report_pdf    Renders the HTML built by the preview to an A4 PDF with wkhtmltopdf: margins and
                  orientation from the preview, the page header (#header-html) on every page and a
                  footer (#footer-html) with "Page X of Y".

The preview and the PDF both use the bundled Liberation Sans (Arial metrics): the browser loads it
by URL, wkhtmltopdf from disk, so the column widths and font size fitted in the preview hold in the
PDF too (the server itself has no Arial).
"""

import os
import re

import frappe
from frappe import _
from frappe.core.doctype.access_log.access_log import make_access_log
from frappe.utils import flt, getdate
from frappe.utils.pdf import get_pdf

from pc_production.pc_production.report.recovery_report.recovery_report import get_report_header

ORIENTATIONS = ("Portrait", "Landscape")
SIDE_MARGIN_MM = 9
MARGIN_TOP_RANGE_MM = (10, 90)
MARGIN_BOTTOM_RANGE_MM = (5, 30)
FONT_FAMILY = "PC Print Sans"
FONT_FILES = {
	"normal": ("LiberationSans-Regular.ttf", "Liberation Sans"),
	"bold": ("LiberationSans-Bold.ttf", "Liberation Sans Bold"),
}


@frappe.whitelist()
def get_print_header(company, from_date=None, to_date=None):
	if not company or not frappe.db.exists("Company", company):
		frappe.throw(_("Select a valid Company"))

	today = getdate()
	filters = frappe._dict(
		company=company,
		from_date=getdate(from_date) if from_date else today,
		to_date=getdate(to_date) if to_date else today,
	)
	return get_report_header(filters)


@frappe.whitelist(methods=["POST"])
def get_report_pdf(
	report_name, html, orientation="Portrait", margin_top=None, margin_bottom=None, filename=None
):
	if (
		not frappe.db.exists("Report", report_name)
		or not frappe.get_doc("Report", report_name).is_permitted()
	):
		frappe.throw(_("Not permitted to print {0}").format(report_name), frappe.PermissionError)

	if orientation not in ORIENTATIONS:
		orientation = "Portrait"

	make_access_log(report_name=report_name, file_type="PDF", method="PDF")

	html, fonts_dir = add_font_faces(html)
	options = {
		"page-size": "A4",
		"orientation": orientation,
		"margin-top": f"{clamp(margin_top, MARGIN_TOP_RANGE_MM, 40)}mm",
		"margin-bottom": f"{clamp(margin_bottom, MARGIN_BOTTOM_RANGE_MM, 12)}mm",
		"margin-left": f"{SIDE_MARGIN_MM}mm",
		"margin-right": f"{SIDE_MARGIN_MM}mm",
		"header-spacing": "0",
		"footer-spacing": "0",
		# The HTML comes from the browser: no network access at all (dead proxy, nothing bypassed),
		# local files only from the bundled fonts folder.
		"proxy": "http://0.0.0.0:0",
		"allow": fonts_dir,
		"load-error-handling": "ignore",
		"load-media-error-handling": "ignore",
	}

	frappe.local.response.filename = get_filename(filename, report_name)
	frappe.local.response.filecontent = get_pdf(html, options)
	frappe.local.response.type = "pdf"


def add_font_faces(html):
	"""Prepend @font-face rules pointing at the bundled font files (file:// URLs).

	The local() source comes first on purpose: get_pdf's scrub_urls rewrites every ": url(...)"
	that is not http(s) into a URL on the site, which would break the file:// path.
	"""
	fonts_dir = frappe.get_app_path("pc_production", "public", "fonts")
	rules = "".join(
		f"@font-face {{ font-family: '{FONT_FAMILY}'; font-weight: {weight}; font-style: normal; "
		f"src: local('{local_name}'), url('file://{os.path.join(fonts_dir, name)}') format('truetype'); }}"
		for weight, (name, local_name) in FONT_FILES.items()
	)
	style = f"<style>{rules}</style>"
	if "<head>" in html:
		return html.replace("<head>", f"<head>{style}", 1), fonts_dir
	return style + html, fonts_dir


def clamp(value, value_range, default):
	value = flt(value) or default
	low, high = value_range
	return round(min(max(value, low), high), 1)


def get_filename(filename, report_name):
	name = re.sub(r'[\\/:*?"<>|\r\n]+', " ", filename or report_name).strip() or "Report"
	name = re.sub(r"\s+", " ", name)[:150]
	return name if name.lower().endswith(".pdf") else f"{name}.pdf"
