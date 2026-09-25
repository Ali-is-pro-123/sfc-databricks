WITH baskets AS (
    SELECT restaurant_code, COUNT(*) AS order_frequency,
           SUM(accepted_basket_revenue) AS revenue, SUM(accepted_quantity) AS quantity_sold,
           AVG(accepted_basket_revenue) AS accepted_average_order_value,
           AVG(CASE WHEN dayofweek(date) IN (1,7) THEN 1.0 ELSE 0.0 END) AS weekend_order_ratio,
           SUM(CASE WHEN coverage_status = 'partial' THEN 1 ELSE 0 END) AS partial_orders,
           SUM(CASE WHEN coverage_status = 'no_accepted_lines' THEN 1 ELSE 0 END) AS empty_orders
    FROM feature_baskets GROUP BY restaurant_code
), lines AS (
    SELECT restaurant_code, SUM(cost) AS cost, SUM(contribution) AS contribution
    FROM feature_lines GROUP BY restaurant_code
)
SELECT r.code AS restaurant_code, r.name AS restaurant_name, r.city,
       COALESCE(b.order_frequency, 0) AS order_frequency, COALESCE(b.revenue, 0) AS revenue,
       COALESCE(b.quantity_sold, 0) AS quantity_sold, COALESCE(l.cost, 0) AS cost,
       COALESCE(l.contribution, 0) AS contribution,
       100.0 * l.contribution / NULLIF(b.revenue, 0) AS profit_percentage,
       b.accepted_average_order_value, b.weekend_order_ratio,
       COALESCE(b.partial_orders, 0) AS partial_orders, COALESCE(b.empty_orders, 0) AS empty_orders,
       1.0 * b.revenue / NULLIF(SUM(b.revenue) OVER (), 0) AS revenue_share
FROM feature_locations r LEFT JOIN baskets b ON r.code = b.restaurant_code
LEFT JOIN lines l ON r.code = l.restaurant_code
