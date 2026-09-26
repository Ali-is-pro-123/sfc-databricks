WITH observed AS (
    SELECT restaurant_code, hour(ordered_local_at) AS local_hour,
           COUNT(DISTINCT order_code) AS order_count,
           SUM(quantity) AS quantity_sold, SUM(revenue) AS revenue,
           SUM(cost) AS cost, SUM(contribution) AS contribution
    FROM eda_lines GROUP BY restaurant_code, hour(ordered_local_at)
)
SELECT r.code AS restaurant_code, r.name AS restaurant_name, h.local_hour,
       COALESCE(o.order_count, 0) AS order_count,
       COALESCE(o.quantity_sold, 0) AS quantity_sold,
       COALESCE(o.revenue, 0) AS revenue,
       COALESCE(o.cost, 0) AS cost,
       COALESCE(o.contribution, 0) AS contribution
FROM restaurants r CROSS JOIN (SELECT explode(sequence(0, 23)) AS local_hour) h
LEFT JOIN observed o ON r.code = o.restaurant_code AND h.local_hour = o.local_hour
