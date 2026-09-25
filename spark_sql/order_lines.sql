-- Half-open price intervals give each purchase at most one historical price.
WITH price_intervals AS (
    SELECT *, LEAD(effective_at) OVER (
        PARTITION BY restaurant_code, item_code ORDER BY effective_at
    ) AS next_effective_at
    FROM pricing_history
), joined AS (
    SELECT l.code AS line_code, o.code AS order_code, l.line_number,
           o.restaurant_code, r.name AS restaurant_name, r.city,
           r.timezone AS restaurant_timezone,
           o.customer_code, c.joined_on AS customer_joined_on,
           o.customer_code IS NULL AS anonymous_customer,
           o.channel_code, ch.name AS channel_name,
           l.item_code, m.name AS item_name, m.introduced_on,
           m.category_code, cat.name AS category_name,
           o.ordered_at, from_utc_timestamp(o.ordered_at, r.timezone) AS ordered_local_at,
           o.status, o.promotion_code AS order_promotion_code,
           op.name AS order_promotion_name,
           l.promotion_code AS line_promotion_code, lp.name AS line_promotion_name,
           lp.discount_percent AS campaign_discount_percent,
           l.quantity, l.unit_price, l.unit_cost, l.discount_amount, l.unit,
           CAST(l.quantity * l.unit_price AS DECIMAL(24,2)) AS gross_amount,
           CAST(l.quantity * l.unit_price - l.discount_amount AS DECIMAL(24,2)) AS revenue,
           CAST(l.quantity * l.unit_cost AS DECIMAL(24,2)) AS cost,
           p.code AS pricing_code, p.effective_at AS price_effective_at,
           p.unit_price AS history_unit_price, p.unit_cost AS history_unit_cost,
           p.code IS NULL AS missing_price_history,
           CASE WHEN p.code IS NULL THEN NULL
                ELSE l.unit_price <> p.unit_price OR l.unit_cost <> p.unit_cost
           END AS price_snapshot_mismatch,
           rt.code AS rating_code, rt.score AS rating_score, rt.rated_at,
           r.code IS NULL OR m.code IS NULL OR cat.code IS NULL OR ch.code IS NULL
             OR (o.customer_code IS NOT NULL AND c.code IS NULL)
             OR (o.promotion_code IS NOT NULL AND op.code IS NULL)
             OR (l.promotion_code IS NOT NULL AND lp.code IS NULL) AS broken_dimension
    FROM order_items l
    JOIN orders o ON l.order_code = o.code
    LEFT JOIN restaurants r ON o.restaurant_code = r.code
    LEFT JOIN customers c ON o.customer_code = c.code
    LEFT JOIN ordering_channels ch ON o.channel_code = ch.code
    LEFT JOIN menu_items m ON l.item_code = m.code
    LEFT JOIN menu_categories cat ON m.category_code = cat.code
    LEFT JOIN promotions op ON o.promotion_code = op.code
    LEFT JOIN promotions lp ON l.promotion_code = lp.code
    LEFT JOIN price_intervals p ON o.restaurant_code = p.restaurant_code
         AND l.item_code = p.item_code AND o.ordered_at >= p.effective_at
         AND (o.ordered_at < p.next_effective_at OR p.next_effective_at IS NULL)
    LEFT JOIN ratings rt ON rt.order_item_code = l.code
)
SELECT *, CAST(revenue - cost AS DECIMAL(24,2)) AS contribution,
       to_date(ordered_local_at) AS date,
       date_format(ordered_local_at, 'yyyy-MM') AS _month
FROM joined
