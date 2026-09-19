"""Orders saved without GST rows since the change get their GST-inclusive total."""


def execute():
	from instabiz.overrides.so_gst import after_migrate, backfill

	after_migrate()  # fields exist before the patch writes them
	print(f"so gst totals: {backfill()} orders")
