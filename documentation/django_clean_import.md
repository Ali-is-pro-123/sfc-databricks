# Django clean dataset import

The analytical pipeline writes its accepted Step 5 records to
`parquet_data/step05-full/clean/`. Django dashboards also need the same
business records in PostgreSQL. Run this command after migrations and a
successful Step 5 quality report:

```powershell
uv run python dine_iq/manage.py import_clean_dataset --dry-run
uv run python dine_iq/manage.py import_clean_dataset
```

The command requires PostgreSQL, the passed
`processed_data/step05-full/quality_report.json`, and `_SUCCESS` markers for
all 13 clean source tables. It checks source counts and unique codes against
the report, resolves every foreign key, then copies records in dependency
order. Every table is imported in its own transaction and checked against the
expected count. Stable numeric IDs are assigned by sorting source codes, so
a rerun can safely skip complete tables after checking their source keys and
promotion-item links. An incomplete or differently keyed table stops the
import for manual investigation instead of overwriting it.

This is a one-way import of the accepted synthetic snapshot, not a live sync.
It never writes to Django user, role, permission, or session tables. Existing
domain records are not silently deleted or replaced. The rerun guard checks
counts and keys, not every mutable non-key field; it is not a full audit of
later manual changes.

For the current full synthetic snapshot, the source report and PostgreSQL
counts agree: 24 restaurants, 180 menu items, 60,000 customers, 348,295
orders, 1,035,861 order items, 2,346,336 inventory rows, and 74,244 wastage
rows, along with the remaining six related tables. The executive dashboard
shows the accepted data after a browser refresh.
