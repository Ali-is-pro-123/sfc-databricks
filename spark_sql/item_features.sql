WITH sales AS (
    SELECT restaurant_code, item_code, COUNT(*) AS line_count,
           COUNT(DISTINCT order_code) AS order_frequency, SUM(quantity) AS quantity_sold,
           SUM(revenue) AS revenue, SUM(cost) AS cost, SUM(contribution) AS contribution,
           SUM(gross_amount) AS gross_amount, SUM(discount_amount) AS discount_amount,
           SUM(CASE WHEN line_promotion_code IS NOT NULL THEN quantity ELSE 0 END) AS promoted_quantity,
           COUNT(DISTINCT CASE WHEN dayofweek(date) IN (1,7) THEN order_code END) AS weekend_orders
    FROM feature_lines GROUP BY restaurant_code, item_code
), visits AS (
    SELECT l.restaurant_code, l.item_code, l.customer_code, COUNT(DISTINCT l.order_code) AS visits
    FROM feature_lines l JOIN eligible_orders o ON l.order_code = o.order_code
    WHERE l.customer_code IS NOT NULL GROUP BY l.restaurant_code, l.item_code, l.customer_code
), repeat_customers AS (
    SELECT restaurant_code, item_code, COUNT(*) AS eligible_customers,
           SUM(CASE WHEN visits > 1 THEN 1 ELSE 0 END) AS repeat_customers
    FROM visits GROUP BY restaurant_code, item_code
), hours AS (
    SELECT restaurant_code, item_code, hour(ordered_local_at) AS local_hour,
           COUNT(DISTINCT order_code) AS hour_orders
    FROM feature_lines GROUP BY restaurant_code, item_code, hour(ordered_local_at)
), ranked_hours AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY restaurant_code, item_code
                                ORDER BY hour_orders DESC, local_hour) AS rank
    FROM hours
), ratings AS (
    SELECT restaurant_code, item_code, COUNT(*) AS rating_count, AVG(rating_score) AS average_rating,
           AVG(CASE WHEN rating_date < split_date THEN rating_score END) AS early_rating,
           AVG(CASE WHEN rating_date >= split_date THEN rating_score END) AS late_rating
    FROM feature_ratings GROUP BY restaurant_code, item_code
), operations AS (
    SELECT restaurant_code, item_code, SUM(wasted_quantity) AS wasted_quantity,
           SUM(waste_cost) AS waste_cost, SUM(prepared_quantity) AS recorded_prepared_quantity,
           SUM(CASE WHEN has_inventory THEN 1 ELSE 0 END) AS inventory_days,
           SUM(CASE WHEN NOT has_inventory THEN 1 ELSE 0 END) AS missing_inventory_days,
           SUM(CASE WHEN consumption_gap <> 0 THEN 1 ELSE 0 END) AS gap_days,
           SUM(consumption_gap) AS consumption_gap
    FROM feature_daily GROUP BY restaurant_code, item_code
), metrics AS (
    SELECT k.restaurant_code, k.item_code, m.name AS item_name, m.category_code,
           c.name AS category_name, r.name AS restaurant_name,
           COALESCE(s.line_count, 0) AS line_count,
           COALESCE(s.order_frequency, 0) AS order_frequency,
           COALESCE(s.quantity_sold, 0) AS quantity_sold,
           COALESCE(s.revenue, 0) AS revenue, COALESCE(s.cost, 0) AS cost,
           COALESCE(s.contribution, 0) AS contribution,
           100.0 * s.contribution / NULLIF(s.revenue, 0) AS profit_percentage,
           100.0 * s.discount_amount / NULLIF(s.gross_amount, 0) AS discount_percentage,
           1.0 * s.promoted_quantity / NULLIF(s.quantity_sold, 0) AS promotion_dependency,
           1.0 * s.weekend_orders / NULLIF(s.order_frequency, 0) AS weekend_order_ratio,
           COALESCE(rc.eligible_customers, 0) AS eligible_customers,
           1.0 * rc.repeat_customers / NULLIF(rc.eligible_customers, 0) AS repeat_purchase_rate,
           COALESCE(rt.rating_count, 0) AS rating_count, rt.average_rating,
           rt.late_rating - rt.early_rating AS rating_trend,
           h.local_hour AS peak_hour,
           1.0 * h.hour_orders / NULLIF(s.order_frequency, 0) AS peak_hour_frequency,
           COALESCE(op.wasted_quantity, 0) AS wasted_quantity,
           COALESCE(op.waste_cost, 0) AS waste_cost,
           op.recorded_prepared_quantity, op.inventory_days, op.missing_inventory_days,
           op.gap_days, op.consumption_gap,
           p.latest_unit_price, p.previous_unit_price,
           100.0 * (p.latest_unit_price - p.previous_unit_price) /
                    NULLIF(p.previous_unit_price, 0) AS price_change_percentage,
           m.introduced_on
    FROM feature_keys k
    JOIN menu_items m ON k.item_code = m.code
    JOIN menu_categories c ON m.category_code = c.code
    JOIN restaurants r ON k.restaurant_code = r.code
    LEFT JOIN sales s USING (restaurant_code, item_code)
    LEFT JOIN repeat_customers rc USING (restaurant_code, item_code)
    LEFT JOIN ratings rt USING (restaurant_code, item_code)
    LEFT JOIN ranked_hours h ON k.restaurant_code = h.restaurant_code AND k.item_code = h.item_code AND h.rank = 1
    LEFT JOIN operations op ON k.restaurant_code = op.restaurant_code AND k.item_code = op.item_code
    LEFT JOIN feature_prices p ON k.restaurant_code = p.restaurant_code AND k.item_code = p.item_code
)
SELECT *, 1.0 * quantity_sold / NULLIF(SUM(quantity_sold) OVER (PARTITION BY restaurant_code), 0) AS item_popularity,
       100.0 * wasted_quantity / NULLIF(quantity_sold + wasted_quantity, 0) AS accounted_wastage_percentage
FROM metrics
