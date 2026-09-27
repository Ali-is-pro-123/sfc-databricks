-- Rebuild accepted sale dates independently of the Step 9 feature snapshot.
CREATE OR REPLACE TEMP TABLE sale_lines_90 AS
SELECT o.restaurant_code,i.item_code,o.code AS order_code,
       CAST(timezone(r.timezone,timezone('UTC',o.ordered_at)) AS DATE) AS local_date,
       i.quantity::DOUBLE AS quantity,
       (i.quantity*i.unit_price-i.discount_amount)::DOUBLE AS revenue,
       (i.quantity*i.unit_cost)::DOUBLE AS cost
FROM clean_order_items i JOIN clean_orders o ON o.code=i.order_code
JOIN clean_restaurants r ON r.code=o.restaurant_code
CROSS JOIN analysis_parameters p
WHERE o.status='completed'
  AND CAST(timezone(r.timezone,timezone('UTC',o.ordered_at)) AS DATE)>=
      p.as_of-INTERVAL 90 DAY
  AND CAST(timezone(r.timezone,timezone('UTC',o.ordered_at)) AS DATE)<p.as_of;

CREATE OR REPLACE TEMP TABLE sale_90 AS
SELECT restaurant_code,item_code,COUNT(DISTINCT order_code) AS order_frequency,
       SUM(quantity) AS quantity_sold,SUM(revenue) AS revenue,SUM(cost) AS cost,
       MIN(local_date) AS first_sale_date,MAX(local_date) AS last_sale_date
FROM sale_lines_90 GROUP BY 1,2;

CREATE OR REPLACE TEMP TABLE purchase_gaps AS
WITH days AS (
    SELECT DISTINCT restaurant_code,item_code,local_date FROM sale_lines_90
), sequenced AS (
    SELECT d.*,date_diff('day',
            COALESCE(LAG(local_date) OVER
                (PARTITION BY restaurant_code,item_code ORDER BY local_date),
                p.as_of-INTERVAL 90 DAY),local_date) AS gap_from_previous
    FROM days d CROSS JOIN analysis_parameters p
), gaps AS (
    SELECT restaurant_code,item_code,MAX(gap_from_previous) AS max_internal_or_opening_gap
    FROM sequenced GROUP BY 1,2
)
SELECT s.restaurant_code,s.item_code,
       date_diff('day',s.last_sale_date,p.as_of) AS days_since_last_sale,
       greatest(g.max_internal_or_opening_gap,
                date_diff('day',s.last_sale_date,p.as_of)) AS longest_no_sale_gap_days
FROM sale_90 s JOIN gaps g USING (restaurant_code,item_code)
CROSS JOIN analysis_parameters p;

CREATE OR REPLACE TEMP TABLE slow_moving_pairs AS
WITH peers AS (
    SELECT restaurant_code,category_code,
           COUNT(*) AS peer_items,
           quantile_cont(quantity_sold,0.25) AS category_location_quantity_q25,
           quantile_cont(order_frequency,0.25) AS category_location_orders_q25
    FROM performance GROUP BY 1,2
), base AS (
    SELECT f.restaurant_code,f.item_code,f.item_name,f.category_code,
           f.restaurant_name,f.item_age_days,f.quantity_sold,f.order_frequency,
           f.revenue::DOUBLE AS revenue,f.contribution::DOUBLE AS direct_contribution,
           f.profit_percentage::DOUBLE AS direct_margin_percentage,
           f.eligible_customers,f.repeat_purchase_rate::DOUBLE AS repeat_purchase_rate,
           f.wasted_quantity::DOUBLE AS wasted_quantity,
           f.accounted_wastage_percentage::DOUBLE AS accounted_wastage_percentage,
           f.prior_30d_quantity,f.recent_30d_quantity,
           f.prior_30d_exposure_days,f.recent_30d_exposure_days,
           f.quantity_trend_percentage,
           COALESCE(g.days_since_last_sale,90) AS days_since_last_sale,
           COALESCE(g.longest_no_sale_gap_days,90) AS longest_no_sale_gap_days,
           p.peer_items,p.category_location_quantity_q25,
           p.category_location_orders_q25
    FROM performance f JOIN peers p USING (restaurant_code,category_code)
    LEFT JOIN purchase_gaps g USING (restaurant_code,item_code)
), signals AS (
    SELECT *,
           quantity_sold<=category_location_quantity_q25 AS low_sales_volume,
           order_frequency<=category_location_orders_q25 AS low_purchase_frequency,
           longest_no_sale_gap_days>=21 AS long_purchase_gap,
           CASE WHEN eligible_customers>=20 AND repeat_purchase_rate IS NOT NULL
                THEN repeat_purchase_rate<=0.05 END AS low_repeat_purchase,
           CASE WHEN accounted_wastage_percentage IS NOT NULL
                THEN accounted_wastage_percentage>=25 AND wasted_quantity>=5 END
                AS high_wastage,
           CASE WHEN direct_margin_percentage IS NOT NULL
                THEN direct_margin_percentage<=20 END AS weak_profitability,
           CASE WHEN quantity_trend_percentage IS NOT NULL
                     AND prior_30d_exposure_days>=20
                     AND recent_30d_exposure_days>=20
                THEN quantity_trend_percentage<=-25 END AS poor_trend
    FROM base
), scored AS (
    SELECT *,
           low_sales_volume::INT+low_purchase_frequency::INT+
           long_purchase_gap::INT AS low_activity_signals,
           COALESCE(low_repeat_purchase,FALSE)::INT+
           COALESCE(high_wastage,FALSE)::INT+
           COALESCE(weak_profitability,FALSE)::INT+
           COALESCE(poor_trend,FALSE)::INT AS adverse_health_signals,
           COALESCE(high_wastage,FALSE)::INT+
           COALESCE(weak_profitability,FALSE)::INT+
           COALESCE(poor_trend,FALSE)::INT AS nonrepeat_health_signals,
           (low_repeat_purchase IS NOT NULL)::INT+
           (high_wastage IS NOT NULL)::INT+
           (weak_profitability IS NOT NULL)::INT+
           (poor_trend IS NOT NULL)::INT AS health_signals_observed
    FROM signals
)
SELECT *,CASE WHEN item_age_days<60 OR peer_items<8 THEN 'insufficient_evidence'
              WHEN quantity_sold=0 AND days_since_last_sale>=60 THEN 'slow_moving'
              WHEN health_signals_observed<2 THEN 'insufficient_evidence'
              WHEN low_activity_signals>=2 AND
                   (nonrepeat_health_signals>=1 OR low_activity_signals=3)
                   THEN 'slow_moving'
              WHEN low_activity_signals>=2 OR
                   (low_activity_signals>=1 AND adverse_health_signals>=2)
                   THEN 'watchlist'
              ELSE 'not_slow_moving' END AS movement_class
FROM scored;

CREATE OR REPLACE TEMP TABLE slow_moving_items AS
SELECT item_code,item_name,category_code,COUNT(*) AS locations,
       COUNT(*) FILTER (WHERE movement_class='slow_moving') AS slow_locations,
       COUNT(*) FILTER (WHERE movement_class='watchlist') AS watchlist_locations,
       COUNT(*) FILTER (WHERE movement_class='insufficient_evidence') AS insufficient_locations,
       SUM(quantity_sold) AS sold_quantity_90d,
       SUM(direct_contribution) AS direct_contribution_90d,
       CASE WHEN COUNT(*) FILTER (WHERE movement_class<>'insufficient_evidence')<12
            THEN 'insufficient_evidence'
            WHEN COUNT(*) FILTER (WHERE movement_class='slow_moving')>=
                 COUNT(*) FILTER (WHERE movement_class<>'insufficient_evidence')*0.5
            THEN 'widespread_slow_moving'
            WHEN COUNT(*) FILTER (WHERE movement_class='slow_moving')>0
            THEN 'location_specific_slow_moving'
            WHEN COUNT(*) FILTER (WHERE movement_class='watchlist')>0
            THEN 'watchlist'
            ELSE 'not_slow_moving' END AS item_movement_class
FROM slow_moving_pairs GROUP BY item_code,item_name,category_code;
