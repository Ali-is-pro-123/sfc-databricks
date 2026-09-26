WITH observed AS (
    SELECT pmod(dayofweek(date) + 5, 7) + 1 AS iso_weekday,
           COUNT(DISTINCT order_code) AS order_count,
           SUM(quantity) AS quantity_sold, SUM(revenue) AS revenue,
           SUM(cost) AS cost, SUM(contribution) AS contribution
    FROM eda_lines GROUP BY pmod(dayofweek(date) + 5, 7) + 1
)
SELECT d.iso_weekday,
       element_at(array('Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'),
                  d.iso_weekday) AS weekday_name,
       COALESCE(o.order_count, 0) AS order_count,
       COALESCE(o.quantity_sold, 0) AS quantity_sold,
       COALESCE(o.revenue, 0) AS revenue,
       COALESCE(o.cost, 0) AS cost,
       COALESCE(o.contribution, 0) AS contribution
FROM (SELECT explode(sequence(1, 7)) AS iso_weekday) d
LEFT JOIN observed o ON d.iso_weekday = o.iso_weekday
