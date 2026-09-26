WITH headers AS (
    SELECT channel_code, COUNT(*) AS completed_header_count,
           SUM(CASE WHEN coverage_status = 'partial' THEN 1 ELSE 0 END) AS partial_header_count,
           SUM(CASE WHEN coverage_status = 'no_accepted_lines' THEN 1 ELSE 0 END) AS empty_header_count
    FROM eda_orders GROUP BY channel_code
), sales AS (
    SELECT channel_code, COUNT(DISTINCT order_code) AS sales_bearing_order_count,
           SUM(quantity) AS quantity_sold, SUM(revenue) AS revenue,
           SUM(cost) AS cost, SUM(contribution) AS contribution
    FROM eda_lines GROUP BY channel_code
)
SELECT ch.code AS channel_code, ch.name AS channel_name,
       COALESCE(h.completed_header_count, 0) AS completed_header_count,
       COALESCE(h.partial_header_count, 0) AS partial_header_count,
       COALESCE(h.empty_header_count, 0) AS empty_header_count,
       COALESCE(s.sales_bearing_order_count, 0) AS sales_bearing_order_count,
       COALESCE(s.quantity_sold, 0) AS quantity_sold,
       COALESCE(s.revenue, 0) AS revenue,
       COALESCE(s.cost, 0) AS cost,
       COALESCE(s.contribution, 0) AS contribution
FROM ordering_channels ch
LEFT JOIN headers h ON ch.code = h.channel_code
LEFT JOIN sales s ON ch.code = s.channel_code
