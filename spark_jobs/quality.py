"""Spark expressions for auditable validation of the raw restaurant contract."""

from pyspark.sql import Window, functions as F


def flag(frame, condition, reason):
    return frame.withColumn("_errors", F.concat(F.col("_errors"),
        F.when(condition, F.array(F.lit(reason))).otherwise(F.array().cast("array<string>"))))


def cast_and_check(frame, table, fields, types, optional):
    frame = frame.withColumn("_raw_json", F.to_json(F.struct(*[F.col(c) for c in fields])))
    frame = frame.withColumn("_errors", F.array().cast("array<string>"))
    frame = flag(frame, F.col("_corrupt_record").isNotNull(), "malformed_csv")
    # Exact duplicate detection uses the original payload, before lossy casts.
    frame = frame.withColumn("_copy", F.row_number().over(Window.partitionBy("_raw_json").orderBy("_source_file")))
    frame = flag(frame, F.col("_copy") > 1, "duplicate_exact")
    for field in fields:
        kind = types[field]
        value = F.trim(F.col(field))
        required = (field == "code" or field.endswith("_code")) and field != "coupon_code" and (table, field) not in optional
        if required:
            frame = flag(frame, value.isNull() | (value == ""), f"missing:{field}")
        if kind != "string":
            target = "timestamp" if kind == "timestamp_utc" else kind
            converted = value.cast(target)
            frame = flag(frame, converted.isNull(), f"invalid_type:{field}")
            if kind.startswith("decimal") or kind == "integer":
                numeric = value.cast("decimal(30,8)")
                frame = flag(frame, numeric.isNull() | (numeric != converted.cast("decimal(30,8)")), f"invalid_precision:{field}")
                frame = flag(frame, converted < 0, f"negative:{field}")
            frame = frame.withColumn(field, converted)
        else:
            frame = frame.withColumn(field, F.when(value == "", F.lit(None)).otherwise(value))
    if "unit" in fields:
        frame = flag(frame, F.col("unit").isNull() | (F.col("unit") != "portion"), "invalid_unit")
    if table == "orders":
        frame = flag(frame, F.col("status").isNull() | ~F.col("status").isin("completed", "cancelled"), "invalid_order_status")
    if table == "order_items":
        frame = flag(frame, (F.col("quantity") <= 0) | (F.col("line_number") <= 0), "nonpositive_line_quantity")
        frame = flag(frame, F.col("discount_amount") > F.col("quantity") * F.col("unit_price"), "excess_discount")
    if table == "promotions":
        frame = flag(frame, F.col("ends_at") <= F.col("starts_at"), "invalid_campaign_dates")
        frame = flag(frame, F.col("discount_percent") > 100, "invalid_discount_percent")
    if table == "ratings":
        frame = flag(frame, ~F.col("score").between(1, 5), "invalid_rating")
    if table == "inventory":
        frame = flag(frame, F.col("consumed_quantity") > F.col("opening_quantity") + F.col("replenished_quantity"), "impossible_inventory")
    if table == "wastage":
        frame = flag(frame, F.col("wasted_quantity") > F.col("prepared_quantity"), "impossible_wastage")
    return frame


def conflicts(frame, table):
    canonical = frame.filter(F.col("_copy") == 1)
    duplicate_codes = canonical.groupBy("code").count().filter("count > 1").select("code").withColumn("_conflict", F.lit(True))
    frame = frame.join(duplicate_codes, "code", "left")
    frame = flag(frame, F.col("_conflict").isNotNull(), "conflicting_code").drop("_conflict")
    keys = {
        "order_items": ["order_code", "line_number"],
        "pricing_history": ["restaurant_code", "item_code", "effective_at"],
        "inventory": ["restaurant_code", "item_code", "date"],
        "ratings": ["order_item_code"],
        "promotion_items": ["promotion_code", "item_code"],
    }.get(table)
    if keys:
        duplicates = canonical.groupBy(*keys).count().filter("count > 1").select(*keys).withColumn("_conflict", F.lit(True))
        frame = frame.join(duplicates, keys, "left")
        frame = flag(frame, F.col("_conflict").isNotNull(), "conflicting_business_key").drop("_conflict")
    return frame


def references(frame, table, clean, refs):
    for field, parent in refs.get(table, {}).items():
        lookup = clean[parent].select(F.col("code").alias("_reference"))
        frame = frame.join(lookup, F.col(field) == F.col("_reference"), "left")
        frame = flag(frame, F.col(field).isNotNull() & F.col("_reference").isNull(), f"unknown_reference:{field}").drop("_reference")
    if table == "orders":
        parent = clean["promotions"].select(F.col("code").alias("_p"), "starts_at", "ends_at")
        frame = frame.join(parent, F.col("promotion_code") == F.col("_p"), "left")
        frame = flag(frame, (F.col("ordered_at") < F.col("starts_at")) | (F.col("ordered_at") >= F.col("ends_at")), "inactive_campaign")
        frame = frame.drop("_p", "starts_at", "ends_at")
    if table == "order_items":
        parent = clean["orders"].select(F.col("code").alias("_order"), F.col("promotion_code").alias("_campaign"), "ordered_at")
        frame = frame.join(parent, F.col("order_code") == F.col("_order"), "left")
        frame = flag(frame, F.col("promotion_code").isNotNull() & (F.col("_campaign").isNull() | (F.col("promotion_code") != F.col("_campaign"))), "campaign_mismatch")
        eligible = clean["promotion_items"].select(F.col("promotion_code").alias("_p"), F.col("item_code").alias("_i"))
        frame = frame.join(eligible, (F.col("promotion_code") == F.col("_p")) & (F.col("item_code") == F.col("_i")), "left")
        frame = flag(frame, F.col("promotion_code").isNotNull() & F.col("_p").isNull(), "ineligible_campaign_item")
        frame = frame.withColumn("_month", F.date_format("ordered_at", "yyyy-MM")).drop("_order", "_campaign", "_p", "_i", "ordered_at")
    if table == "ratings":
        parent = clean["order_items"].select(F.col("code").alias("_line"), "order_code")
        orders = clean["orders"].select(F.col("code").alias("_order"), "ordered_at", "status")
        frame = frame.join(parent, F.col("order_item_code") == F.col("_line"), "left").join(orders, F.col("order_code") == F.col("_order"), "left")
        frame = flag(frame, (F.col("status") != "completed") | (F.col("rated_at") < F.col("ordered_at")), "invalid_purchase_rating")
        frame = frame.drop("_line", "order_code", "_order", "ordered_at", "status")
    return frame
