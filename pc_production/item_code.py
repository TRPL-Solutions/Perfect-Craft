import re
from contextlib import contextmanager

import frappe
from frappe import _
from frappe.model.naming import getseries

# Auto Item Code: <Parent Group Abbr>-<Item Group Abbr>-<Brand Short Name>-<running number>
# e.g. FG-WE-PK-1, FG-WE-XX-2, FG-WE-PW-3 ...
#
# - No Brand: the Brand segment is the placeholder "XX".
# - The running number is unique per <Parent>-<Group> across all brands, so the
#   Brand segment can be swapped without touching the number.
# - On an auto-generated code the Brand segment follows the Brand: setting or
#   changing the Brand renames the Item (Frappe rename_doc, so links follow),
#   e.g. FG-WE-XX-2 -> FG-WE-PW-2; clearing it goes back to XX. If the new code
#   is already taken the save is refused, so code and Brand never disagree.
# - custom_auto_item_code marks codes built here. Typed codes, and codes renamed
#   by hand afterwards, are never renamed automatically.

BRAND_PLACEHOLDER = "XX"


def set_auto_item_code(doc, method=None):
	"""Item before_insert: build item_code for new items left blank.
	Typed codes, variants and existing items are not touched."""
	if (doc.item_code or "").strip() or doc.variant_of:
		return

	group_prefix, brand_abbr = get_item_code_prefix(doc).rsplit("-", 1)
	number = next_item_number(group_prefix)

	doc.item_code = f"{group_prefix}-{brand_abbr}-{number}"
	doc.custom_auto_item_code = 1
	if not doc.item_name:
		doc.item_name = doc.item_code


def next_item_number(group_prefix):
	"""Next running number for <Parent>-<Group>, not used under any brand.

	The Series row lock (held until commit) serialises allocations in the
	group, so parallel saves get different numbers. It is the only lock taken
	here. The counter is part of the save's transaction: a failed save rolls it
	back, so no number is lost."""
	key = group_prefix + "-"
	with latest_committed_reads():
		if frappe.db.db_type == "mariadb":
			# Take the row's exclusive lock first, creating the row for the first
			# Item of a new group. (INSERT IGNORE would take a shared lock that
			# parallel first saves then all try to upgrade: deadlock.)
			frappe.db.sql(
				"insert into `tabSeries` (name, current) values (%s, 0) on duplicate key update current = current",
				key,
			)

		while True:
			number = getseries(key, 1)  # select ... for update + update
			if not is_number_used(group_prefix, number):
				return number


@contextmanager
def latest_committed_reads():
	"""Let locking reads see the latest committed row instead of failing.

	MariaDB 11.6+ defaults to innodb_snapshot_isolation=ON: a locking read
	(SELECT ... FOR UPDATE) of a row another transaction changed after this one
	took its snapshot aborts the whole transaction with error 1020 ("Record has
	changed since last read"). Frappe's getseries locks the Series row that
	way, so parallel Item saves in one group failed. Turning the check off for
	this session, only around these statements, gives the pre-11.6 InnoDB
	behaviour getseries is written for: wait for the lock, then read the
	committed value. The global setting is not touched."""
	restore = False
	if frappe.db.db_type == "mariadb":
		try:
			restore = bool(int(frappe.db.sql("select @@session.innodb_snapshot_isolation")[0][0]))
		except Exception:
			restore = False  # MariaDB < 11.6 / MySQL: no such variable, nothing to do
		if restore:
			frappe.db.sql("set session innodb_snapshot_isolation = OFF")
	try:
		yield
	finally:
		if restore:
			frappe.db.sql("set session innodb_snapshot_isolation = ON")


def is_number_used(group_prefix, number):
	"""True if <group>-<anything>-<number> exists (older per-brand codes, typed
	codes), so that swapping the Brand segment later stays free.

	Plain read, deliberately no row locks: a locking read here made inserts wait
	on Item rows that a parallel Brand save had locked while that save waited
	for this insert's Series lock (deadlock). The Series lock already keeps
	auto-generated numbers apart; a typed code committed in the same instant is
	still caught by the primary key."""
	# Segments are A-Z0-9 only (clean_abbr), so no LIKE wildcards to escape.
	return frappe.db.sql("select name from `tabItem` where name like %s limit 1", f"{group_prefix}-%-{number}")


def get_item_code_prefix(doc):
	if not doc.item_group:
		frappe.throw(_("Select Item Group to auto-generate the Item Code"))

	group_abbr, parent_group = frappe.db.get_value(
		"Item Group", doc.item_group, ["custom_abbreviation", "parent_item_group"]
	)
	parent_abbr = parent_group and frappe.db.get_value("Item Group", parent_group, "custom_abbreviation")
	brand_abbr = get_brand_abbr(doc.brand) if doc.brand else BRAND_PLACEHOLDER

	missing = []
	if not parent_abbr:
		missing.append(_("Abbreviation of parent Item Group {0}").format(frappe.bold(parent_group or "-")))
	if not group_abbr:
		missing.append(_("Abbreviation of Item Group {0}").format(frappe.bold(doc.item_group)))
	if not brand_abbr:
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


def get_brand_abbr(brand):
	return clean_abbr(frappe.db.get_value("Brand", brand, "custom_short_name"))


def validate_brand_in_item_code(doc, method=None):
	"""Item validate: if the Brand of an auto-coded Item changed (or is set
	while the code still has XX), work out the new code and refuse the save
	when it cannot be used. The rename itself runs in on_change."""
	if doc.is_new() or not doc.get("custom_auto_item_code") or doc.name != doc.item_code:
		return

	parts = doc.name.rsplit("-", 2)
	if len(parts) != 3 or not parts[2].isdigit():
		return
	group_prefix, current_abbr, number = parts

	if not (doc.has_value_changed("brand") or (doc.brand and current_abbr == BRAND_PLACEHOLDER)):
		return

	new_abbr = get_brand_abbr(doc.brand) if doc.brand else BRAND_PLACEHOLDER
	if not new_abbr:
		frappe.throw(
			_("Set the Short Name of Brand {0}: it replaces {1} in Item Code {2}.").format(
				frappe.bold(doc.brand), frappe.bold(current_abbr), frappe.bold(doc.name)
			),
			title=_("Item Code"),
		)
	if new_abbr == current_abbr:
		return

	new_name = f"{group_prefix}-{new_abbr}-{number}"
	# No Series lock here: auto-generated codes never reuse this number, so only
	# a typed code can compete for new_name, and the rename's primary key check
	# catches one committed after this read (see update_brand_in_item_code).
	taken = frappe.db.exists("Item", new_name)
	if taken:
		throw_item_code_taken(doc, new_name)

	doc.flags.pc_new_item_code = new_name


def throw_item_code_taken(doc, new_name):
	frappe.throw(
		_(
			"Item Code {0} cannot become {1} for Brand {2}: Item {1} already exists."
			"<br><br>Rename or correct Item {1} first, or rename this Item manually, then save again."
		).format(frappe.bold(doc.name), frappe.bold(new_name), frappe.bold(doc.brand or "-")),
		title=_("Item Code already exists"),
		exc=frappe.DuplicateEntryError,
	)


def update_brand_in_item_code(doc, method=None):
	"""Item on_change: apply the rename prepared in validate. Runs after the
	save is complete (version, global search) so the rename sees the final
	record."""
	new_name = doc.flags.pop("pc_new_item_code", None)
	if not new_name or new_name == doc.name:
		return

	from frappe.model.rename_doc import rename_doc
	from frappe.utils.global_search import delete_for_document, update_global_search

	old_name = doc.name
	delete_for_document(doc)
	frappe.flags.pc_auto_item_rename = True
	try:
		# Permissions skipped: the user saving the Brand may lack the Rename
		# right, and this rename is system-driven. merge stays False: an existing
		# Item is never merged into. Search index is updated for this Item only.
		rename_doc("Item", old_name, new_name, ignore_permissions=True, rebuild_search=False)
	except Exception as e:
		# new_name was committed by someone else after validate looked. The
		# error rolls back the whole save, so Item and Brand stay as they were.
		if not frappe.db.is_duplicate_entry(e):
			raise
		throw_item_code_taken(doc, new_name)
	finally:
		frappe.flags.pc_auto_item_rename = False

	# Hand the renamed record back to the caller. `localname` makes the desk
	# form switch to the new name after save, like it does for a new document.
	doc.name = new_name
	doc.load_from_db()
	doc.localname = old_name
	update_global_search(doc)


def clear_auto_flag_on_manual_rename(doc, method=None, old_name=None, new_name=None, merge=False):
	"""Item after_rename: a code renamed by hand is a manual code from now on."""
	if frappe.flags.get("pc_auto_item_rename") or merge:
		return
	if frappe.db.get_value("Item", new_name, "custom_auto_item_code"):
		frappe.db.set_value("Item", new_name, "custom_auto_item_code", 0, update_modified=False)


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
