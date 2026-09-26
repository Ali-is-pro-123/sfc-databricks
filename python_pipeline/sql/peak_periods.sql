-- Use complete accepted order headers so multi-line baskets count once.
CREATE OR REPLACE TEMP TABLE eligible_orders AS
SELECT order_code, restaurant_code, accepted_line_count,
       accepted_basket_revenue,
       timezone(timezone, timezone('UTC', ordered_at)) AS ordered_local_at
FROM order_coverage
WHERE status = 'completed' AND accepted_line_count > 0
  AND known_rejected_lines = 0
  AND CAST(timezone(timezone, timezone('UTC', ordered_at)) AS DATE) < ?;

CREATE OR REPLACE TEMP TABLE order_facts AS
SELECT e.order_code, e.restaurant_code, CAST(e.ordered_local_at AS DATE) AS local_date,
       EXTRACT('hour' FROM e.ordered_local_at)::INTEGER AS local_hour,
       EXTRACT('isodow' FROM e.ordered_local_at)::INTEGER AS weekday_number,
       CASE WHEN EXTRACT('isodow' FROM e.ordered_local_at) IN (6,7)
            THEN 'weekend' ELSE 'weekday' END AS day_type,
       strftime(e.ordered_local_at, '%Y-%m') AS year_month,
       CASE WHEN EXTRACT('month' FROM e.ordered_local_at) IN (12,1,2) THEN 'Winter'
            WHEN EXTRACT('month' FROM e.ordered_local_at) IN (3,4,5) THEN 'Spring'
            WHEN EXTRACT('month' FROM e.ordered_local_at) IN (6,7,8) THEN 'Summer'
            ELSE 'Autumn' END AS season,
       ANY_VALUE(l.channel_code) AS channel_code,
       ANY_VALUE(l.channel_name) AS channel_name,
       CASE WHEN ANY_VALUE(l.channel_name) = 'Dine-in' THEN 'Dine-in'
            WHEN ANY_VALUE(l.channel_name) = 'Third-party Delivery' THEN 'Delivery'
            WHEN ANY_VALUE(l.channel_name) = 'Takeaway' THEN 'Takeaway'
            WHEN ANY_VALUE(l.channel_name) = 'Website/App' THEN 'Website/App'
            ELSE 'Other/Unknown' END AS channel_group,
       COUNT(*) AS joined_lines,
       COUNT(DISTINCT l.channel_code) AS distinct_channels,
       SUM(l.revenue) AS joined_revenue,
       MAX(e.accepted_line_count) AS expected_lines,
       MAX(e.accepted_basket_revenue) AS revenue
FROM eligible_orders e JOIN order_lines l ON e.order_code = l.order_code
GROUP BY e.order_code, e.restaurant_code, e.ordered_local_at;

-- Calendar days, including days with zero observed orders, are exposure.
CREATE OR REPLACE TEMP TABLE calendar_days AS
SELECT CAST(day_value AS DATE) AS local_date,
       EXTRACT('isodow' FROM day_value)::INTEGER AS weekday_number,
       CASE WHEN EXTRACT('isodow' FROM day_value) IN (6,7)
            THEN 'weekend' ELSE 'weekday' END AS day_type,
       strftime(day_value, '%Y-%m') AS year_month,
       CASE WHEN EXTRACT('month' FROM day_value) IN (12,1,2) THEN 'Winter'
            WHEN EXTRACT('month' FROM day_value) IN (3,4,5) THEN 'Spring'
            WHEN EXTRACT('month' FROM day_value) IN (6,7,8) THEN 'Summer'
            ELSE 'Autumn' END AS season
FROM generate_series((SELECT MIN(local_date) FROM order_facts),
                     ?::DATE - INTERVAL 1 DAY, INTERVAL 1 DAY) days(day_value);
