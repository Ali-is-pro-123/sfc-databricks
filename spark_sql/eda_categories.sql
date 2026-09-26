WITH sales AS (
    SELECT category_code, COUNT(DISTINCT order_code) AS order_count,
           SUM(quantity) AS quantity_sold, SUM(revenue) AS revenue,
           SUM(cost) AS cost, SUM(contribution) AS contribution
    FROM eda_lines GROUP BY category_code
), catalog AS (
    SELECT category_code, COUNT(*) AS item_count FROM eda_catalog GROUP BY category_code
)
SELECT c.code AS category_code, c.name AS category_name,
       COALESCE(m.item_count, 0) AS item_count,
       COALESCE(s.order_count, 0) AS order_count,
       COALESCE(s.quantity_sold, 0) AS quantity_sold,
       COALESCE(s.revenue, 0) AS revenue,
       COALESCE(s.cost, 0) AS cost,
       COALESCE(s.contribution, 0) AS contribution
FROM menu_categories c
LEFT JOIN catalog m ON c.code = m.category_code
LEFT JOIN sales s ON c.code = s.category_code
