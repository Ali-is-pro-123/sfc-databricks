WITH sales AS (
    SELECT line_promotion_code AS promotion_code,
           COUNT(DISTINCT order_code) AS order_count,
           SUM(quantity) AS quantity_sold,
           SUM(gross_amount) AS gross_amount,
           SUM(discount_amount) AS discount_amount,
           SUM(revenue) AS revenue,
           SUM(cost) AS cost,
           SUM(contribution) AS contribution
    FROM eda_lines GROUP BY line_promotion_code
)
SELECT s.promotion_code, s.promotion_code IS NOT NULL AS has_line_promotion,
       CASE WHEN s.promotion_code IS NULL THEN 'Unpromoted line'
            ELSE p.name END AS promotion_name,
       s.order_count, s.quantity_sold, s.gross_amount, s.discount_amount,
       s.revenue, s.cost, s.contribution
FROM sales s LEFT JOIN promotions p ON s.promotion_code = p.code
