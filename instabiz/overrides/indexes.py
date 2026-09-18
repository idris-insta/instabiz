"""Performance indexes on columns the app's lists, dashboards and permission
queries filter on. Idempotent — runs after every `bench migrate`
(hooks.after_migrate); can also be run by hand via bench execute."""
import frappe

INDEXES = [
	("tabSales Invoice", "idx_si_sp_user", ["custom_sales_person_user"]),
	("tabSales Invoice", "idx_si_ds_return_date", ["docstatus", "is_return", "posting_date"]),
	("tabSales Invoice", "idx_si_sp_date", ["custom_sales_person_user", "posting_date"]),
	("tabCustomer", "idx_cust_sp_user", ["custom_sales_person_user"]),
	("tabCustomer", "idx_cust_territory", ["territory"]),
	("tabLead", "idx_lead_custom_status", ["custom_status"]),
	("tabLead", "idx_lead_last_activity", ["custom_last_activity_at"]),
	("tabIB Customer Score", "idx_score_customer", ["customer"]),
	# row-level permission filters (permissions.py) + list filters
	("tabQuotation", "idx_q_sp_user", ["custom_sales_person_user"]),
	("tabQuotation", "idx_q_status", ["docstatus", "status"]),
	("tabSales Order", "idx_so_sp_user", ["custom_sales_person_user"]),
	("tabSales Order", "idx_so_location", ["custom_location"]),
	("tabDelivery Note", "idx_dn_sp_user", ["custom_sales_person_user"]),
	# production screens (production.py groups WOs by these on every load)
	("tabIB Work Order", "idx_wo_order_sheet", ["order_sheet", "status"]),
	("tabIB Work Order", "idx_wo_os_item", ["order_sheet_item"]),
	("tabIB Order Sheet", "idx_os_sales_order", ["sales_order"]),
	# advance tracking + auto-reconcile
	("tabPayment Entry", "idx_pe_adv_so", ["custom_advance_for_so"]),
	("tabPayment Entry", "idx_pe_party", ["party_type", "party"]),
]


def _idx_exists(table, index_name):
	return frappe.db.sql(
		"SELECT 1 FROM information_schema.STATISTICS"
		" WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND INDEX_NAME=%s LIMIT 1",
		(table, index_name),
	)


def _columns_exist(table, cols):
	existing = set(frappe.db.get_table_columns(table[3:])) if frappe.db.table_exists(table[3:]) else set()
	return all(c in existing for c in cols)


def add_performance_indexes(verbose=True):
	created = 0
	for table, name, cols in INDEXES:
		if _idx_exists(table, name):
			continue
		# custom fields/doctypes may not exist yet on a fresh site — skip, next migrate retries
		if not _columns_exist(table, cols):
			continue
		col_list = ", ".join(f"`{c}`" for c in cols)
		try:
			frappe.db.sql_ddl(f"ALTER TABLE `{table}` ADD INDEX `{name}` ({col_list})")
			created += 1
			if verbose:
				print(f"  Created: {name} on {table}({col_list})")
		except Exception:
			frappe.log_error(title=f"IB index {name} failed", message=frappe.get_traceback())
	if verbose:
		print(f"IB indexes: {created} created.")
	return created


def after_migrate():
	add_performance_indexes(verbose=False)
