-- Build daily facts from accepted clean records, independently of Spark joins.
CREATE OR REPLACE TEMP TABLE sale_days AS
SELECT o.restaurant_code, i.item_code, m.category_code,
       CAST(timezone(r.timezone, timezone('UTC', o.ordered_at)) AS DATE) AS local_date,
       COUNT(DISTINCT o.code) AS order_count,
       SUM(i.quantity) AS sold_quantity,
       SUM(CAST(i.quantity * i.unit_price - i.discount_amount AS DECIMAL(24,2))) AS revenue,
       SUM(CAST(i.quantity * i.unit_cost AS DECIMAL(24,2))) AS cost
FROM clean_order_items i
JOIN clean_orders o ON i.order_code = o.code
JOIN clean_restaurants r ON o.restaurant_code = r.code
JOIN clean_menu_items m ON i.item_code = m.code
WHERE o.status = 'completed'
GROUP BY o.restaurant_code, i.item_code, m.category_code,
         CAST(timezone(r.timezone, timezone('UTC', o.ordered_at)) AS DATE);

CREATE OR REPLACE TEMP TABLE rating_days AS
SELECT o.restaurant_code, i.item_code,
       CAST(timezone(r.timezone, timezone('UTC', rt.rated_at)) AS DATE) AS local_date,
       COUNT(*) AS rating_count, SUM(rt.score) AS rating_sum
FROM clean_ratings rt
JOIN clean_order_items i ON rt.order_item_code = i.code
JOIN clean_orders o ON i.order_code = o.code
JOIN clean_restaurants r ON o.restaurant_code = r.code
GROUP BY o.restaurant_code, i.item_code,
         CAST(timezone(r.timezone, timezone('UTC', rt.rated_at)) AS DATE);

CREATE OR REPLACE TEMP TABLE waste_days AS
SELECT w.restaurant_code, w.item_code,
       CAST(timezone(r.timezone, timezone('UTC', w.recorded_at)) AS DATE) AS local_date,
       SUM(w.wasted_quantity) AS wasted_quantity
FROM clean_wastage w
JOIN clean_restaurants r ON w.restaurant_code = r.code
GROUP BY w.restaurant_code, w.item_code,
         CAST(timezone(r.timezone, timezone('UTC', w.recorded_at)) AS DATE);

-- Unioning pre-aggregated grains prevents ratings or waste from multiplying sales.
CREATE OR REPLACE TEMP TABLE daily AS
SELECT restaurant_code, item_code, local_date,
       SUM(sold_quantity) AS sold_quantity,
       SUM(order_count) AS order_count,
       SUM(revenue) AS revenue,
       SUM(cost) AS cost,
       SUM(wasted_quantity) AS wasted_quantity,
       SUM(rating_count) AS rating_count,
       SUM(rating_sum) AS rating_sum
FROM (
    SELECT restaurant_code, item_code, local_date, sold_quantity, order_count,
           revenue, cost, 0::DECIMAL(22,3) AS wasted_quantity,
           0::BIGINT AS rating_count, 0::BIGINT AS rating_sum
    FROM sale_days
    UNION ALL
    SELECT restaurant_code, item_code, local_date, 0::BIGINT, 0::BIGINT,
           0::DECIMAL(34,2), 0::DECIMAL(34,2), wasted_quantity,
           0::BIGINT, 0::BIGINT
    FROM waste_days
    UNION ALL
    SELECT restaurant_code, item_code, local_date, 0::BIGINT, 0::BIGINT,
           0::DECIMAL(34,2), 0::DECIMAL(34,2), 0::DECIMAL(22,3),
           rating_count, rating_sum
    FROM rating_days
) observations
GROUP BY restaurant_code, item_code, local_date;

CREATE OR REPLACE TEMP TABLE first_sales AS
SELECT restaurant_code, item_code, ANY_VALUE(category_code) AS category_code,
       MIN(local_date) AS first_sale_date
FROM sale_days
WHERE sold_quantity > 0
GROUP BY restaurant_code, item_code;
