-- Aggregate each source before joining. Waste is never repeated per sales line.
WITH sales AS (
    SELECT restaurant_code, item_code, date,
           COUNT(*) AS sales_line_count, COUNT(DISTINCT order_code) AS order_count,
           SUM(quantity) AS sold_quantity, SUM(gross_amount) AS gross_amount,
           SUM(discount_amount) AS discount_amount, SUM(revenue) AS revenue,
           SUM(cost) AS cost, SUM(contribution) AS contribution
    FROM integrated_lines WHERE status = 'completed'
    GROUP BY restaurant_code, item_code, date
), waste AS (
    SELECT w.restaurant_code, w.item_code,
           to_date(from_utc_timestamp(w.recorded_at, r.timezone)) AS date,
           COUNT(*) AS waste_record_count, SUM(w.prepared_quantity) AS prepared_quantity,
           SUM(w.wasted_quantity) AS wasted_quantity,
           SUM(w.wasted_quantity * w.unit_cost) AS waste_cost
    FROM wastage w JOIN restaurants r ON w.restaurant_code = r.code
    GROUP BY w.restaurant_code, w.item_code,
             to_date(from_utc_timestamp(w.recorded_at, r.timezone))
), observed_ratings AS (
    SELECT restaurant_code, item_code,
           to_date(from_utc_timestamp(rated_at, restaurant_timezone)) AS date,
           COUNT(*) AS rating_count, SUM(rating_score) AS rating_sum
    FROM integrated_lines WHERE rating_code IS NOT NULL
    GROUP BY restaurant_code, item_code,
             to_date(from_utc_timestamp(rated_at, restaurant_timezone))
), observed_keys AS (
    SELECT restaurant_code, item_code, date FROM inventory
    UNION SELECT restaurant_code, item_code, date FROM sales
    UNION SELECT restaurant_code, item_code, date FROM waste
    UNION SELECT restaurant_code, item_code, date FROM observed_ratings
), daily AS (
    SELECT k.*, r.name AS restaurant_name, m.name AS item_name,
           m.category_code, c.name AS category_name,
           COALESCE(s.sales_line_count, 0) AS sales_line_count,
           COALESCE(s.order_count, 0) AS order_count,
           COALESCE(s.sold_quantity, 0) AS sold_quantity,
           COALESCE(s.gross_amount, 0) AS gross_amount,
           COALESCE(s.discount_amount, 0) AS discount_amount,
           COALESCE(s.revenue, 0) AS revenue, COALESCE(s.cost, 0) AS cost,
           COALESCE(s.contribution, 0) AS contribution,
           COALESCE(w.waste_record_count, 0) AS waste_record_count,
           COALESCE(w.prepared_quantity, 0) AS prepared_quantity,
           COALESCE(w.wasted_quantity, 0) AS wasted_quantity,
           COALESCE(w.waste_cost, 0) AS waste_cost,
           COALESCE(rt.rating_count, 0) AS rating_count,
           COALESCE(rt.rating_sum, 0) AS rating_sum,
           CASE WHEN rt.rating_count > 0 THEN rt.rating_sum / rt.rating_count END AS average_rating,
           i.code IS NOT NULL AS has_inventory,
           i.opening_quantity, i.replenished_quantity, i.consumed_quantity,
           i.opening_quantity + i.replenished_quantity - i.consumed_quantity AS closing_quantity
    FROM observed_keys k
    LEFT JOIN sales s USING (restaurant_code, item_code, date)
    LEFT JOIN waste w USING (restaurant_code, item_code, date)
    LEFT JOIN observed_ratings rt USING (restaurant_code, item_code, date)
    LEFT JOIN inventory i USING (restaurant_code, item_code, date)
    JOIN restaurants r ON k.restaurant_code = r.code
    JOIN menu_items m ON k.item_code = m.code
    JOIN menu_categories c ON m.category_code = c.code
)
SELECT *, consumed_quantity - sold_quantity - wasted_quantity AS consumption_gap,
       date_format(date, 'yyyy-MM') AS _month
FROM daily
