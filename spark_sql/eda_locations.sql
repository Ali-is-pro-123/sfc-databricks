WITH headers AS (
    SELECT restaurant_code, COUNT(*) AS completed_header_count,
           SUM(CASE WHEN coverage_status = 'partial' THEN 1 ELSE 0 END) AS partial_header_count,
           SUM(CASE WHEN coverage_status = 'no_accepted_lines' THEN 1 ELSE 0 END) AS empty_header_count,
           SUM(CASE WHEN customer_code IS NULL THEN 1 ELSE 0 END) AS anonymous_header_count
    FROM eda_orders GROUP BY restaurant_code
), sales AS (
    SELECT restaurant_code, COUNT(DISTINCT order_code) AS sales_bearing_order_count,
           SUM(quantity) AS quantity_sold, SUM(revenue) AS revenue,
           SUM(cost) AS cost, SUM(contribution) AS contribution
    FROM eda_lines GROUP BY restaurant_code
), waste AS (
    SELECT restaurant_code, SUM(wasted_quantity) AS wasted_quantity,
           SUM(waste_cost) AS waste_cost FROM eda_daily GROUP BY restaurant_code
)
SELECT r.code AS restaurant_code, r.name AS restaurant_name, r.city,
       COALESCE(h.completed_header_count, 0) AS completed_header_count,
       COALESCE(h.partial_header_count, 0) AS partial_header_count,
       COALESCE(h.empty_header_count, 0) AS empty_header_count,
       COALESCE(h.anonymous_header_count, 0) AS anonymous_header_count,
       COALESCE(s.sales_bearing_order_count, 0) AS sales_bearing_order_count,
       COALESCE(s.quantity_sold, 0) AS quantity_sold,
       COALESCE(s.revenue, 0) AS revenue,
       COALESCE(s.cost, 0) AS cost,
       COALESCE(s.contribution, 0) AS contribution,
       CASE WHEN s.revenue > 0 THEN 100.0 * s.contribution / s.revenue END AS margin_percentage,
       COALESCE(w.wasted_quantity, 0) AS wasted_quantity,
       COALESCE(w.waste_cost, 0) AS waste_cost
FROM restaurants r
LEFT JOIN headers h ON r.code = h.restaurant_code
LEFT JOIN sales s ON r.code = s.restaurant_code
LEFT JOIN waste w ON r.code = w.restaurant_code
