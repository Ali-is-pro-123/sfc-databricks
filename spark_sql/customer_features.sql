WITH purchases AS (
    SELECT customer_code, COUNT(*) AS frequency, SUM(accepted_basket_revenue) AS monetary_value,
           AVG(accepted_basket_revenue) AS average_order_value,
           AVG(accepted_quantity) AS average_basket_quantity,
           AVG(CASE WHEN dayofweek(date) IN (1,7) THEN 1.0 ELSE 0.0 END) AS weekend_order_ratio,
           MAX(date) AS last_window_visit
    FROM eligible_orders WHERE customer_code IS NOT NULL GROUP BY customer_code
), channels AS (
    SELECT customer_code, channel_code, COUNT(*) AS channel_orders
    FROM eligible_orders WHERE customer_code IS NOT NULL GROUP BY customer_code, channel_code
), preferred_channels AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY customer_code ORDER BY channel_orders DESC, channel_code) AS rank
    FROM channels
), category_counts AS (
    SELECT l.customer_code, l.category_code, SUM(l.quantity) AS category_quantity
    FROM feature_lines l JOIN eligible_orders o ON l.order_code = o.order_code
    WHERE l.customer_code IS NOT NULL GROUP BY l.customer_code, l.category_code
), preferred_categories AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY customer_code ORDER BY category_quantity DESC, category_code) AS rank
    FROM category_counts
), promotions AS (
    SELECT l.customer_code, SUM(l.quantity) AS quantity,
           SUM(CASE WHEN l.line_promotion_code IS NOT NULL THEN l.quantity ELSE 0 END) AS promoted_quantity
    FROM feature_lines l JOIN eligible_orders o ON l.order_code = o.order_code
    WHERE l.customer_code IS NOT NULL GROUP BY l.customer_code
), history AS (
    SELECT customer_code, MAX(date) AS last_visit_date, COUNT(*) AS available_history_frequency
    FROM historical_visits WHERE customer_code IS NOT NULL GROUP BY customer_code
)
SELECT c.code AS customer_code, c.joined_on, h.last_visit_date,
       COALESCE(h.available_history_frequency, 0) AS available_history_frequency,
       COALESCE(p.frequency, 0) AS frequency, COALESCE(p.monetary_value, 0) AS monetary_value,
       p.average_order_value, p.average_basket_quantity, p.weekend_order_ratio,
       ch.channel_code AS preferred_channel_code, cat.category_code AS preferred_category_code,
       1.0 * pr.promoted_quantity / NULLIF(pr.quantity, 0) AS promotion_dependency
FROM feature_customers c
LEFT JOIN purchases p ON c.code = p.customer_code
LEFT JOIN history h ON c.code = h.customer_code
LEFT JOIN preferred_channels ch ON c.code = ch.customer_code AND ch.rank = 1
LEFT JOIN preferred_categories cat ON c.code = cat.customer_code AND cat.rank = 1
LEFT JOIN promotions pr ON c.code = pr.customer_code
