-- Accepted completed baskets are the unit for value, discount and duplication.
CREATE OR REPLACE TEMP TABLE order_facts AS
SELECT o.code AS order_code,o.restaurant_code,o.customer_code,o.ordered_at,
       CAST(timezone(r.timezone,timezone('UTC',o.ordered_at)) AS DATE) AS local_date,
       COUNT(*) AS accepted_lines,SUM(i.quantity)::DOUBLE AS sold_quantity,
       SUM(i.quantity*i.unit_price)::DOUBLE AS gross_revenue,
       SUM(i.discount_amount)::DOUBLE AS discount_amount,
       SUM(i.quantity*i.unit_price-i.discount_amount)::DOUBLE AS net_revenue,
       SUM(i.quantity*i.unit_cost)::DOUBLE AS direct_cost,
       string_agg(i.item_code || ':' || i.quantity::VARCHAR || ':' ||
                  i.unit_price::VARCHAR || ':' || i.discount_amount::VARCHAR,
                  '|' ORDER BY i.item_code,i.line_number) AS basket_signature
FROM clean_orders o JOIN clean_order_items i ON i.order_code=o.code
JOIN clean_restaurants r ON r.code=o.restaurant_code
CROSS JOIN analysis_parameters p
WHERE o.status='completed' AND o.ordered_at<p.as_of
GROUP BY o.code,o.restaurant_code,o.customer_code,o.ordered_at,r.timezone;

CREATE OR REPLACE TEMP TABLE location_day_anomalies AS
WITH bounds AS (
    SELECT MIN(local_date) AS first_day,MAX(local_date) AS last_day FROM order_facts
), calendar AS (
    SELECT d::DATE AS local_date FROM bounds,
         generate_series(first_day,last_day,INTERVAL 1 DAY) AS t(d)
), daily AS (
    SELECT r.code AS restaurant_code,c.local_date,
           COALESCE(o.orders,0) AS orders,COALESCE(o.net_revenue,0) AS net_revenue
    FROM clean_restaurants r CROSS JOIN calendar c
    LEFT JOIN (SELECT restaurant_code,local_date,COUNT(*) AS orders,
                     SUM(net_revenue) AS net_revenue
               FROM order_facts GROUP BY 1,2) o
      ON o.restaurant_code=r.code AND o.local_date=c.local_date
), history AS (
    SELECT a.restaurant_code,a.local_date,a.orders,a.net_revenue,
           COUNT(b.local_date) AS prior_same_weekdays,
           AVG(b.orders) AS prior_orders_mean,
           STDDEV_POP(b.orders) AS prior_orders_stddev
    FROM daily a LEFT JOIN daily b
      ON a.restaurant_code=b.restaurant_code
     AND b.local_date>=a.local_date-INTERVAL 56 DAY
     AND b.local_date<=a.local_date-INTERVAL 7 DAY
     AND isodow(b.local_date)=isodow(a.local_date)
    GROUP BY 1,2,3,4
)
SELECT *,CASE WHEN prior_same_weekdays=8 AND prior_orders_mean>=5
                  AND orders>=prior_orders_mean*1.75
                  AND orders>=prior_orders_mean+2.5*prior_orders_stddev
             THEN TRUE ELSE FALSE END AS sudden_sales_spike,
         CASE WHEN prior_same_weekdays=8 AND prior_orders_mean>=5
                  AND orders<=prior_orders_mean*0.50
                  AND orders<=prior_orders_mean-2*prior_orders_stddev
             THEN TRUE ELSE FALSE END AS sudden_sales_drop
FROM history;

CREATE OR REPLACE TEMP TABLE category_week_demand AS
WITH bounds AS (
    SELECT date_trunc('week',MIN(local_date))::DATE AS first_week,
           date_trunc('week',MAX(local_date))::DATE AS last_week FROM order_facts
), weeks AS (
    SELECT w::DATE AS week_start FROM bounds,
         generate_series(first_week,last_week,INTERVAL 7 DAY) AS t(w)
), population AS (
    SELECT r.code AS restaurant_code,c.code AS category_code
    FROM clean_restaurants r CROSS JOIN clean_menu_categories c
), observed AS (
    SELECT o.restaurant_code,m.category_code,
           date_trunc('week',o.local_date)::DATE AS week_start,
           SUM(i.quantity)::DOUBLE AS sold_quantity
    FROM order_facts o JOIN clean_order_items i ON i.order_code=o.order_code
    JOIN clean_menu_items m ON m.code=i.item_code
    GROUP BY 1,2,3
), dense AS (
    SELECT p.restaurant_code,p.category_code,w.week_start,
           COALESCE(o.sold_quantity,0) AS sold_quantity
    FROM population p CROSS JOIN weeks w
    LEFT JOIN observed o USING (restaurant_code,category_code,week_start)
), history AS (
    SELECT *,COUNT(*) OVER prior AS prior_weeks,
           AVG(sold_quantity) OVER prior AS prior_weekly_mean,
           STDDEV_POP(sold_quantity) OVER prior AS prior_weekly_stddev,
           SUM(sold_quantity) OVER prior AS prior_8w_quantity
    FROM dense
    WINDOW prior AS (PARTITION BY restaurant_code,category_code
                     ORDER BY week_start ROWS BETWEEN 8 PRECEDING AND 1 PRECEDING)
)
SELECT h.*,CASE WHEN prior_weeks=8 AND prior_8w_quantity>=80
                    AND sold_quantity>=prior_weekly_mean*1.75
                    AND sold_quantity>=prior_weekly_mean+2.5*prior_weekly_stddev
               THEN TRUE ELSE FALSE END AS unexpected_high_demand,
           CASE WHEN prior_weeks=8 AND prior_8w_quantity>=80
                    AND sold_quantity<=prior_weekly_mean*0.50
                    AND sold_quantity<=prior_weekly_mean-2*prior_weekly_stddev
               THEN TRUE ELSE FALSE END AS unexpected_low_demand
FROM history h CROSS JOIN analysis_parameters p
WHERE h.week_start+INTERVAL 7 DAY<=p.as_of;

CREATE OR REPLACE TEMP TABLE order_value_reference AS
SELECT restaurant_code,COUNT(*) AS baseline_orders,
       median(net_revenue) AS median_net_order_value,
       quantile_cont(net_revenue,0.99) AS p99_net_order_value,
       COUNT(*) FILTER (WHERE discount_amount>0) AS baseline_discounted_orders,
       quantile_cont(discount_amount/gross_revenue,0.99)
           FILTER (WHERE discount_amount>0 AND gross_revenue>0)
           AS p99_discount_rate
FROM order_facts o CROSS JOIN analysis_parameters p
WHERE local_date<p.monitor_start
GROUP BY restaurant_code;

CREATE OR REPLACE TEMP TABLE order_value_anomalies AS
SELECT o.order_code,o.restaurant_code,o.customer_code,o.local_date,
       o.accepted_lines,o.sold_quantity,o.gross_revenue,o.discount_amount,
       o.net_revenue,o.net_revenue-o.direct_cost AS direct_contribution,
       CASE WHEN o.gross_revenue>0 THEN o.discount_amount/o.gross_revenue END
           AS discount_rate,
       r.baseline_orders,r.median_net_order_value,r.p99_net_order_value,
       r.baseline_discounted_orders,r.p99_discount_rate,
       CASE WHEN r.baseline_orders>=100 AND o.net_revenue>r.p99_net_order_value
                    AND o.net_revenue>=2*r.median_net_order_value
            THEN TRUE ELSE FALSE END AS abnormally_high_order_value,
       CASE WHEN r.baseline_discounted_orders>=30 AND o.gross_revenue>0
                    AND o.discount_amount/o.gross_revenue>r.p99_discount_rate
                    AND o.discount_amount/o.gross_revenue>=0.30
            THEN TRUE ELSE FALSE END AS unusual_discount
FROM order_facts o JOIN order_value_reference r USING (restaurant_code)
CROSS JOIN analysis_parameters p
WHERE o.local_date>=p.monitor_start;

CREATE OR REPLACE TEMP TABLE duplicate_transaction_candidates AS
WITH grouped AS (
    SELECT restaurant_code,customer_code,ordered_at,basket_signature,
           COUNT(*) AS matching_orders,
           string_agg(order_code,',' ORDER BY order_code) AS order_codes,
           MIN(net_revenue) AS min_net_revenue,MAX(net_revenue) AS max_net_revenue
    FROM order_facts WHERE customer_code IS NOT NULL
    GROUP BY 1,2,3,4 HAVING COUNT(*)>1
)
SELECT * FROM grouped;
