import re

import frappe
from frappe import _
from frappe.model.naming import getseries

# Auto Item Code: <Parent Group Abbr>-<Item Group Abbr>-<Brand Short Name>-<running number>
# e.g. FG-WE-PK-1, FG-WE-PK-2 ... with a separate running number per prefix.


def set_auto_item_code(doc, method=None):
	"""Item before_insert: build item_code for new items left blank.
	Typed codes, variants and existing items are not touched."""
	if (doc.item_code or "").strip() or doc.variant_of:
		return

	prefix = get_item_code_prefix(doc)

	# Series counter is row-locked, so parallel saves get different numbers.
	# Skip numbers already taken (e.g. by a manually entered code).
	while True:
		code = f"{prefix}-{getseries(prefix + '-', 1)}"
		if not frappe.db.exists("Item", code):
			break

	doc.item_code = code
	if not doc.item_name:
		doc.item_name = code


def get_item_code_prefix(doc):
	if not doc.item_group:
		frappe.throw(_("Select Item Group to auto-generate the Item Code"))

	group_abbr, parent_group = frappe.db.get_value(
		"Item Group", doc.item_group, ["custom_abbreviation", "parent_item_group"]
	)
	parent_abbr = parent_group and frappe.db.get_value("Item Group", parent_group, "custom_abbreviation")
	brand_abbr = doc.brand and frappe.db.get_value("Brand", doc.brand, "custom_short_name")

	missing = []
	if not parent_abbr:
		missing.append(_("Abbreviation of parent Item Group {0}").format(frappe.bold(parent_group or "-")))
	if not group_abbr:
		missing.append(_("Abbreviation of Item Group {0}").format(frappe.bold(doc.item_group)))
	if not doc.brand:
		missing.append(_("Brand"))
	elif not brand_abbr:
		missing.append(_("Short Name of Brand {0}").format(frappe.bold(doc.brand)))

	if missing:
		frappe.throw(
			_("Cannot auto-generate the Item Code. Missing:")
			+ "<br>"
			+ "<br>".join(f"&bull; {m}" for m in missing)
			+ "<br><br>"
			+ _("Fill them in, or enter the Item Code manually."),
			title=_("Item Code"),
		)

	return "-".join(clean_abbr(a) for a in (parent_abbr, group_abbr, brand_abbr))


def clean_abbr(value):
	return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def validate_item_group_abbreviation(doc, method=None):
	"""Item Group validate: keep the abbreviation upper-case letters/digits."""
	if not doc.get("custom_abbreviation"):
		return
	abbr = doc.custom_abbreviation.strip().upper()
	if not re.fullmatch(r"[A-Z0-9]+", abbr):
		frappe.throw(_("Abbreviation may contain only letters and digits, e.g. FG"))
	doc.custom_abbreviation = abbr
