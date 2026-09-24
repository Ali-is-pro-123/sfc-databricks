# Domain Data Dictionary (Step 3)

These are clean application schemas, not the final raw generator schemas. Every
business entity has a numeric Django primary key, a unique `code` (up to 40
characters) for import joins, and a creation timestamp. LocationAccess uses only
a numeric primary key and the two foreign keys. Timestamps use timezone-aware
UTC storage; each restaurant retains its IANA display time zone.

| Entity | Main fields | Relationships / rules |
| --- | --- | --- |
| Restaurant | code, name, city, address, timezone, is_active | One location per record; valid IANA zone |
| MenuCategory | code, name, description | Unique name; referenced by menu items |
| MenuItem | code, name, description, category, is_available | Shared menu catalog; category protected from deletion |
| PricingHistory | restaurant, item, effective_at, unit_price, unit_cost | Unique location/item/timestamp; nonnegative price and cost |
| Customer | code, joined_on, cohort | Pseudonymous customer, separate from application login |
| OrderingChannel | code, name | Dine-in, takeaway, website/app and delivery can be created here |
| Promotion | name, coupon_code, starts_at, ends_at, discount_percent, items | Start before end; discount 0–100%; explicit applicable items |
| Order | restaurant, customer, channel, promotion, ordered_at, status | Customer/promotion optional; completed or cancelled; promotion active at order time |
| OrderItem | order, line_number, item, quantity, unit_price, unit_cost, discount_amount | Unique order/line number; positive quantity; discount cannot exceed gross value |
| Rating | order_item, score, rated_at | One rating per purchased line; score 1–5; completed purchase; date not before purchase |
| Inventory | restaurant, item, date, opening_quantity, replenished_quantity, consumed_quantity | One daily snapshot per location/item; consumption cannot exceed stock |
| Wastage | restaurant, item, recorded_at, prepared_quantity, wasted_quantity, unit_cost, reason | Waste cannot exceed prepared quantity; nonnegative cost and quantities |
| LocationAccess | user, restaurant | Unique user/location grant; assignments govern manager read access |

## Units and derived values

- Currency: PKR for this deployment. Unit monetary fields have two decimal places.
- Order quantities: integer portions. Inventory/wastage: fractional portions with
  three decimal places. No ingredient-to-portion conversion is inferred.
- Revenue = quantity × historical unit price − line discount amount.
- Contribution margin = revenue − quantity × historical unit cost. Negative
  margins are valid and needed for loss-making dish scenarios.
- Closing quantity = opening + replenished − consumed. Consumption includes waste.
- Wastage cost = wasted quantity × historical unit cost.
- Current menu price = the latest event for the location/item at or before now.
  Unpriced items are omitted from that location's priced menu.

## Validation boundary

Database constraints enforce numeric bounds, identifiers, duplicate prevention,
and same-row date rules even on bulk writes. Model validation additionally checks
time zones, campaign timing and rating purchase relationships. Bulk imports must
run these cross-record checks explicitly. Revalidating all dependent transactions
after an administrator changes a campaign or purchase is not automatic; pipeline
data-quality checks must catch such inconsistencies before analytics.

Step 4 adds `OrderItem.promotion`, a nullable reference identifying the campaign
responsible for that line's discount. It must match the order campaign and the
item must be in the campaign's applicable item set.

The model permits a mixed basket with a promotion attached to its order. Future
promotion analysis must check `Promotion.items`; it must not attribute every line
in a mixed basket to the campaign. Pricing/rating/wastage joins must be aggregated
at the correct grain before integration to avoid multiplying order-line revenue.
