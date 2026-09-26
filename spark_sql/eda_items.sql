-- Sales, observed ratings, and waste have different grains; aggregate first.
WITH sales AS (
    SELECT item_code, COUNT(*) AS line_count,
           COUNT(DISTINCT order_code) AS order_count, SUM(quantity) AS quantity_sold,
           SUM(gross_amount) AS gross_amount, SUM(discount_amount) AS discount_amount,
           SUM(revenue) AS revenue, SUM(cost) AS cost, SUM(contribution) AS contribution,
           SUM(CASE WHEN line_promotion_code IS NOT NULL THEN quantity ELSE 0 END) AS promoted_quantity
    FROM eda_lines GROUP BY item_code
), rating_summary AS (
    SELECT item_code, COUNT(*) AS rating_count, AVG(rating_score) AS average_rating
    FROM eda_ratings GROUP BY item_code
), waste_summary AS (
    SELECT item_code, SUM(wasted_quantity) AS wasted_quantity,
           SUM(waste_cost) AS waste_cost, SUM(prepared_quantity) AS recorded_prepared_quantity,
           SUM(waste_record_count) AS waste_record_count
    FROM eda_daily GROUP BY item_code
)
SELECT m.code AS item_code, m.name AS item_name, m.category_code,
       c.name AS category_name, m.introduced_on,
       datediff(x.cutoff, m.introduced_on) AS exposure_days,
       COALESCE(s.line_count, 0) AS line_count,
       COALESCE(s.order_count, 0) AS order_count,
       COALESCE(s.quantity_sold, 0) AS quantity_sold,
       COALESCE(s.gross_amount, 0) AS gross_amount,
       COALESCE(s.discount_amount, 0) AS discount_amount,
       COALESCE(s.revenue, 0) AS revenue,
       COALESCE(s.cost, 0) AS cost,
       COALESCE(s.contribution, 0) AS contribution,
       CASE WHEN s.revenue > 0 THEN 100.0 * s.contribution / s.revenue END AS margin_percentage,
       COALESCE(s.promoted_quantity, 0) AS promoted_quantity,
       CASE WHEN s.quantity_sold > 0 THEN 1.0 * s.promoted_quantity / s.quantity_sold END AS promotion_share,
       COALESCE(rt.rating_count, 0) AS rating_count, rt.average_rating,
       COALESCE(w.wasted_quantity, 0) AS wasted_quantity,
       COALESCE(w.waste_cost, 0) AS waste_cost,
       COALESCE(w.recorded_prepared_quantity, 0) AS recorded_prepared_quantity,
       COALESCE(w.waste_record_count, 0) AS waste_record_count,
       CASE WHEN COALESCE(s.quantity_sold, 0) + COALESCE(w.wasted_quantity, 0) > 0
            THEN 100.0 * COALESCE(w.wasted_quantity, 0) /
                 (COALESCE(s.quantity_sold, 0) + COALESCE(w.wasted_quantity, 0))
       END AS waste_share_of_accounted_portions
FROM eda_catalog m
JOIN menu_categories c ON m.category_code = c.code
CROSS JOIN eda_context x
LEFT JOIN sales s ON m.code = s.item_code
LEFT JOIN rating_summary rt ON m.code = rt.item_code
LEFT JOIN waste_summary w ON m.code = w.item_code
