WITH month_bounds AS (
    SELECT to_date(date_trunc('month', min(date))) AS first_month,
           to_date(date_trunc('month', max(date))) AS last_month
    FROM eda_orders
), month_dates AS (
    SELECT explode(sequence(first_month, last_month, interval 1 month)) AS month_date
    FROM month_bounds
), month_list AS (
    SELECT date_format(month_date, 'yyyy-MM') AS local_month FROM month_dates
), observed AS (
    SELECT date_format(date, 'yyyy-MM') AS local_month,
           COUNT(DISTINCT order_code) AS order_count,
           SUM(quantity) AS quantity_sold, SUM(revenue) AS revenue,
           SUM(cost) AS cost, SUM(contribution) AS contribution
    FROM eda_lines GROUP BY date_format(date, 'yyyy-MM')
)
SELECT m.local_month,
       COALESCE(o.order_count, 0) AS order_count,
       COALESCE(o.quantity_sold, 0) AS quantity_sold,
       COALESCE(o.revenue, 0) AS revenue,
       COALESCE(o.cost, 0) AS cost,
       COALESCE(o.contribution, 0) AS contribution
FROM month_list m LEFT JOIN observed o ON m.local_month = o.local_month
