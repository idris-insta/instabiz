#!/usr/bin/env python3
"""Fail if a SQL string / get_all filter compares a remapped status against its
raw ERPNext value without also including the value IbStatusMixin persists.

IbStatusMixin (instabiz/overrides/utils.py) rewrites status through each
override class's STATUS_MAP before it reaches the DB, so e.g. a submitted
Quotation is stored as "Pending", never "Open". A query filtering on "Open"
alone silently matches nothing. Pure stdlib — runs in CI without a bench.
"""
import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent / "instabiz"
CLASS_FILES = {
	"Quotation": "overrides/quotation.py",
	"Sales Order": "overrides/sales_order.py",
	"Delivery Note": "overrides/delivery_note.py",
	"Sales Invoice": "overrides/sales_invoice.py",
}


def load_status_maps():
	maps = {}
	for doctype, rel in CLASS_FILES.items():
		tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
		for node in ast.walk(tree):
			if isinstance(node, ast.Assign) and any(
				isinstance(t, ast.Name) and t.id == "STATUS_MAP" for t in node.targets
			):
				maps[doctype] = ast.literal_eval(node.value)
	return maps


# Raw values that ARE stored despite being in STATUS_MAP, because code writes
# them directly with db.set_value (bypassing set_status):
#   Quotation "Expired" — quotation_expiry._auto_expire_quotations()
_WRITTEN_DIRECTLY = {("Quotation", "Expired")}


def dead_statuses(doctype, status_map):
	# Raw values that never survive to the DB (remapped, and not themselves a target)
	return {
		k: v for k, v in status_map.items()
		if k not in status_map.values() and (doctype, k) not in _WRITTEN_DIRECTLY
	}


def check_text(text, doctype, dead):
	"""text references doctype; return problems for dead statuses used without their target."""
	problems = []
	quoted = set(re.findall(r"['\"]([A-Za-z ]+)['\"]", text))
	for raw, stored in dead.items():
		if raw in quoted and stored not in quoted:
			problems.append(f"{doctype}: uses '{raw}' without '{stored}' (persisted as '{stored}')")
	return problems


def mentions(text, doctype):
	return f"`tab{doctype}`" in text or f"tab{doctype}`" in text


# Statuses shared with non-remapped doctypes (Work Order, PO, ...) — only flag
# them when the SQL clearly targets one remapped doctype and no other table.
_OTHER_TABLES = re.compile(r"`tab(?!Quotation|Sales Order|Delivery Note|Sales Invoice)[A-Z][^`]*`")


def scan_file(path, maps):
	src = path.read_text(encoding="utf-8")
	try:
		tree = ast.parse(src)
	except SyntaxError:
		return []
	out = []
	deads = {dt: dead_statuses(dt, m) for dt, m in maps.items()}

	for node in ast.walk(tree):
		# 1) SQL string constants (incl. f-string parts)
		if isinstance(node, (ast.Constant, ast.JoinedStr)):
			if isinstance(node, ast.Constant):
				if not isinstance(node.value, str):
					continue
				text = node.value
			else:
				text = "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
			if "status" not in text.lower():
				continue
			targets = [dt for dt in maps if mentions(text, dt)]
			if len(targets) != 1:
				continue
			# only the part of the SQL that is about status, and skip joins to other tables
			if _OTHER_TABLES.search(text):
				continue
			for p in check_text(text, targets[0], deads[targets[0]]):
				out.append((node.lineno, p))

		# 2) frappe.get_all / get_list / db.exists / db.count("Doctype", filters={..."status": ...})
		if isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
			doctype = node.args[0].value
			if doctype not in maps:
				continue
			filt = None
			if len(node.args) > 1:
				filt = node.args[1]
			for kw in node.keywords:
				if kw.arg == "filters":
					filt = kw.value
			if isinstance(filt, ast.Dict):
				for k, v in zip(filt.keys, filt.values):
					if isinstance(k, ast.Constant) and k.value == "status":
						seg = ast.get_source_segment(src, v) or ""
						for p in check_text(seg, doctype, deads[doctype]):
							out.append((node.lineno, p))
	return out


def main():
	maps = load_status_maps()
	missing = set(CLASS_FILES) - set(maps)
	if missing:
		print(f"could not read STATUS_MAP for: {sorted(missing)}")
		return 2
	failures = 0
	for path in sorted(ROOT.rglob("*.py")):
		if "node_modules" in path.parts:
			continue
		for lineno, problem in scan_file(path, maps):
			failures += 1
			print(f"{path.relative_to(ROOT.parent)}:{lineno}: {problem}")
	if failures:
		print(f"\n{failures} status literal problem(s). Use the persisted value (see STATUS_MAP) "
			  "or instabiz.overrides.ib_status.stored_statuses().")
		return 1
	print("status literals OK")
	return 0


if __name__ == "__main__":
	sys.exit(main())
