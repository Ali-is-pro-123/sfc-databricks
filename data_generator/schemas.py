"""CSV contract: references use stable codes, amounts use decimal strings."""

SCHEMAS = {
    "restaurants": "code name city address timezone is_active",
    "menu_categories": "code name description",
    "menu_items": "code category_code name description is_available introduced_on",
    "customers": "code joined_on cohort",
    "ordering_channels": "code name",
    "pricing_history": "code restaurant_code item_code effective_at unit_price unit_cost",
    "promotions": "code name coupon_code starts_at ends_at discount_percent",
    "promotion_items": "code promotion_code item_code",
    "orders": "code restaurant_code customer_code channel_code promotion_code ordered_at status",
    "order_items": "code order_code line_number item_code quantity unit_price unit_cost discount_amount promotion_code unit",
    "ratings": "code order_item_code score rated_at",
    "inventory": "code restaurant_code item_code date opening_quantity replenished_quantity consumed_quantity unit",
    "wastage": "code restaurant_code item_code recorded_at prepared_quantity wasted_quantity unit_cost reason unit",
}
SCHEMAS = {name: fields.split() for name, fields in SCHEMAS.items()}
REFERENCES = {
    "menu_items": {"category_code": "menu_categories"},
    "pricing_history": {"restaurant_code": "restaurants", "item_code": "menu_items"},
    "promotion_items": {"promotion_code": "promotions", "item_code": "menu_items"},
    "orders": {"restaurant_code": "restaurants", "customer_code": "customers", "channel_code": "ordering_channels", "promotion_code": "promotions"},
    "order_items": {"order_code": "orders", "item_code": "menu_items", "promotion_code": "promotions"},
    "ratings": {"order_item_code": "order_items"},
    "inventory": {"restaurant_code": "restaurants", "item_code": "menu_items"},
    "wastage": {"restaurant_code": "restaurants", "item_code": "menu_items"},
}
OPTIONAL = {("orders", "customer_code"), ("orders", "promotion_code"), ("order_items", "promotion_code")}
TRANSACTIONS = {"orders": "ordered_at", "order_items": None, "ratings": "rated_at", "inventory": "date", "wastage": "recorded_at"}

MONEY = {"unit_price", "unit_cost", "discount_amount"}
QUANTITIES = {"opening_quantity", "replenished_quantity", "consumed_quantity", "prepared_quantity", "wasted_quantity"}
INTEGERS = {"quantity", "line_number", "score"}


def field_type(field):
    if field in MONEY:
        return "decimal(14,2)"
    if field in QUANTITIES:
        return "decimal(12,3)"
    if field == "discount_percent":
        return "decimal(5,2)"
    if field in INTEGERS:
        return "integer"
    if field.endswith("_at"):
        return "timestamp_utc"
    if field in ("date", "joined_on", "introduced_on"):
        return "date"
    if field in ("is_active", "is_available"):
        return "boolean"
    return "string"
