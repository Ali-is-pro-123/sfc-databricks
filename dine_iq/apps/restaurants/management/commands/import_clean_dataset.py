"""Load verified Step 5 clean Parquet into PostgreSQL without touching accounts."""

import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from apps.restaurants import models


TABLES = (
    ("restaurants", models.Restaurant, ("code", "name", "city", "address", "timezone", "is_active")),
    ("menu_categories", models.MenuCategory, ("code", "name", "description")),
    ("menu_items", models.MenuItem, ("code", "category_id", "name", "description", "is_available")),
    ("ordering_channels", models.OrderingChannel, ("code", "name")),
    ("customers", models.Customer, ("code", "joined_on", "cohort")),
    ("promotions", models.Promotion, ("code", "name", "coupon_code", "starts_at", "ends_at", "discount_percent")),
    ("promotion_items", models.Promotion.items.through, ("promotion_id", "menuitem_id")),
    ("pricing_history", models.PricingHistory, ("code", "restaurant_id", "item_id", "effective_at", "unit_price", "unit_cost")),
    ("orders", models.Order, ("code", "restaurant_id", "customer_id", "channel_id", "promotion_id", "ordered_at", "status")),
    ("order_items", models.OrderItem, ("code", "order_id", "line_number", "item_id", "quantity", "unit_price", "unit_cost", "discount_amount", "promotion_id")),
    ("ratings", models.Rating, ("code", "order_item_id", "score", "rated_at")),
    ("inventory", models.Inventory, ("code", "restaurant_id", "item_id", "date", "opening_quantity", "replenished_quantity", "consumed_quantity")),
    ("wastage", models.Wastage, ("code", "restaurant_id", "item_id", "recorded_at", "prepared_quantity", "wasted_quantity", "unit_cost", "reason")),
)


SELECTS = {
    "restaurants": "SELECT k.id,s.code,s.name,s.city,s.address,s.timezone,s.is_active FROM src_restaurants s JOIN keys_restaurants k USING(code)",
    "menu_categories": "SELECT k.id,s.code,s.name,s.description FROM src_menu_categories s JOIN keys_menu_categories k USING(code)",
    "menu_items": "SELECT k.id,s.code,c.id,s.name,s.description,s.is_available FROM src_menu_items s JOIN keys_menu_items k USING(code) JOIN keys_menu_categories c ON c.code=s.category_code",
    "ordering_channels": "SELECT k.id,s.code,s.name FROM src_ordering_channels s JOIN keys_ordering_channels k USING(code)",
    "customers": "SELECT k.id,s.code,s.joined_on,s.cohort FROM src_customers s JOIN keys_customers k USING(code)",
    "promotions": "SELECT k.id,s.code,s.name,s.coupon_code,s.starts_at,s.ends_at,s.discount_percent FROM src_promotions s JOIN keys_promotions k USING(code)",
    "promotion_items": "SELECT k.id,p.id,i.id FROM src_promotion_items s JOIN keys_promotion_items k USING(code) JOIN keys_promotions p ON p.code=s.promotion_code JOIN keys_menu_items i ON i.code=s.item_code",
    "pricing_history": "SELECT k.id,s.code,r.id,i.id,s.effective_at,s.unit_price,s.unit_cost FROM src_pricing_history s JOIN keys_pricing_history k USING(code) JOIN keys_restaurants r ON r.code=s.restaurant_code JOIN keys_menu_items i ON i.code=s.item_code",
    "orders": "SELECT k.id,s.code,r.id,c.id,ch.id,p.id,s.ordered_at,s.status FROM src_orders s JOIN keys_orders k USING(code) JOIN keys_restaurants r ON r.code=s.restaurant_code LEFT JOIN keys_customers c ON c.code=s.customer_code JOIN keys_ordering_channels ch ON ch.code=s.channel_code LEFT JOIN keys_promotions p ON p.code=s.promotion_code",
    "order_items": "SELECT k.id,s.code,o.id,s.line_number,i.id,s.quantity,s.unit_price,s.unit_cost,s.discount_amount,p.id FROM src_order_items s JOIN keys_order_items k USING(code) JOIN keys_orders o ON o.code=s.order_code JOIN keys_menu_items i ON i.code=s.item_code LEFT JOIN keys_promotions p ON p.code=s.promotion_code",
    "ratings": "SELECT k.id,s.code,l.id,s.score,s.rated_at FROM src_ratings s JOIN keys_ratings k USING(code) JOIN keys_order_items l ON l.code=s.order_item_code",
    "inventory": "SELECT k.id,s.code,r.id,i.id,s.date,s.opening_quantity,s.replenished_quantity,s.consumed_quantity FROM src_inventory s JOIN keys_inventory k USING(code) JOIN keys_restaurants r ON r.code=s.restaurant_code JOIN keys_menu_items i ON i.code=s.item_code",
    "wastage": "SELECT k.id,s.code,r.id,i.id,s.recorded_at,s.prepared_quantity,s.wasted_quantity,s.unit_cost,s.reason FROM src_wastage s JOIN keys_wastage k USING(code) JOIN keys_restaurants r ON r.code=s.restaurant_code JOIN keys_menu_items i ON i.code=s.item_code",
}


class Command(BaseCommand):
    help = "Import passed Step 5 clean Parquet into an empty or matching PostgreSQL domain database."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Validate sources, joins, counts and existing keys without importing.")
        parser.add_argument("--batch-size", type=int, default=5000)

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            raise CommandError("The verified full import requires PostgreSQL.")
        if options["batch_size"] < 1 or options["batch_size"] > 50000:
            raise CommandError("Batch size must be between 1 and 50000.")
        root = Path(settings.PROJECT_ROOT)
        report_path = root / "processed_data/step05-full/quality_report.json"
        if not report_path.is_file():
            raise CommandError("Step 5 quality report is missing.")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report.get("status") != "passed":
            raise CommandError("Step 5 quality report did not pass.")
        con = duckdb.connect()
        con.execute("SET threads=4")
        try:
            for name, _, _ in TABLES:
                folder = root / "parquet_data/step05-full/clean" / name
                if not (folder / "_SUCCESS").is_file():
                    raise CommandError(f"Successful clean source is missing: {name}")
                con.execute(f"CREATE VIEW src_{name} AS SELECT * FROM read_parquet('{folder.as_posix()}/**/*.parquet')")
                expected = report["tables"][name]["accepted_rows"]
                observed = con.execute(f"SELECT COUNT(*),COUNT(DISTINCT code) FROM src_{name}").fetchone()
                if observed != (expected, expected):
                    raise CommandError(f"Source count or key uniqueness differs: {name}: {observed}")
                con.execute(f"CREATE TEMP TABLE keys_{name} AS SELECT row_number() OVER (ORDER BY code)::BIGINT AS id,code FROM src_{name}")
            for name, model, columns in TABLES:
                expected = report["tables"][name]["accepted_rows"]
                joined = con.execute(f"SELECT COUNT(*) FROM ({SELECTS[name]})").fetchone()[0]
                if joined != expected:
                    raise CommandError(f"Foreign-key resolution differs for {name}: {joined} of {expected}")
                present = model.objects.count()
                if present not in (0, expected):
                    raise CommandError(f"Existing {name} count {present} is neither empty nor complete ({expected}).")
                if present == expected:
                    # Equal counts alone do not prove a previous import used these IDs.
                    with connection.cursor() as db_cursor:
                        if name == "promotion_items":
                            db_cursor.execute(f"SELECT id,promotion_id,menuitem_id FROM {connection.ops.quote_name(model._meta.db_table)} ORDER BY id")
                            actual_links = db_cursor.fetchall()
                            source_links = con.execute(f"{SELECTS[name]} ORDER BY k.id").fetchall()
                            if actual_links != source_links:
                                raise CommandError("Existing promotion-item links differ from clean source")
                        else:
                            db_cursor.execute(f"SELECT id,code FROM {connection.ops.quote_name(model._meta.db_table)} ORDER BY code")
                            source_cursor = con.execute(f"SELECT id,code FROM keys_{name} ORDER BY code")
                            position = 0
                            while batch := db_cursor.fetchmany(options["batch_size"]):
                                source_batch = source_cursor.fetchmany(len(batch))
                                position += len(batch)
                                if batch != source_batch:
                                    raise CommandError(f"Existing {name} keys differ from clean source")
                            if position != expected:
                                raise CommandError(f"Existing {name} key count differs")
                    self.stdout.write(f"{name}: already populated ({present:,}); skipping")
                    continue
                if options["dry_run"]:
                    self.stdout.write(f"{name}: ready to import {expected:,}")
                    continue
                self.stdout.write(f"{name}: importing {expected:,} rows")
                cursor = con.execute(SELECTS[name])
                stamp = datetime.now(timezone.utc)
                db_columns = ["id", *columns]
                if name != "promotion_items":
                    db_columns.append("created_at")
                target = connection.ops.quote_name(model._meta.db_table)
                quoted = ", ".join(connection.ops.quote_name(column) for column in db_columns)
                with transaction.atomic():
                    with connection.cursor() as db_cursor:
                        with db_cursor.cursor.copy(f"COPY {target} ({quoted}) FROM STDIN") as copy:
                            imported = 0
                            while batch := cursor.fetchmany(options["batch_size"]):
                                for row in batch:
                                    copy.write_row((*row, stamp) if name != "promotion_items" else row)
                                imported += len(batch)
                        if imported != expected:
                            raise CommandError(f"Imported row count differs for {name}: {imported}")
                        sequence = connection.ops.quote_name(f"{model._meta.db_table}_id_seq")
                        db_cursor.execute(f"SELECT setval('{sequence}', %s, true)", [expected])
                if model.objects.count() != expected:
                    raise CommandError(f"Post-import count differs for {name}")
                self.stdout.write(self.style.SUCCESS(f"{name}: verified {expected:,}"))
        finally:
            con.close()
