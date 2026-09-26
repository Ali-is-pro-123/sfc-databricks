-- Accepted completed sale lines are the denominator; ratings join only once.
CREATE OR REPLACE TEMP TABLE sold_lines AS
SELECT i.code AS line_code,o.code AS order_code,o.restaurant_code,i.item_code,
       m.category_code,o.customer_code,o.ordered_at,
       CAST(timezone(r.timezone,timezone('UTC',o.ordered_at)) AS DATE) AS purchase_date,
       strftime(CAST(timezone(r.timezone,timezone('UTC',o.ordered_at)) AS DATE),'%Y-%m') AS purchase_month,
       CASE WHEN NULLIF(i.promotion_code,'') IS NOT NULL THEN 'promoted'
            ELSE 'not_promoted' END AS promotion_status,
       i.quantity::DOUBLE AS sold_quantity,
       (i.quantity*i.unit_price-i.discount_amount)::DOUBLE AS net_revenue,
       (i.quantity*(i.unit_price-i.unit_cost)-i.discount_amount)::DOUBLE AS direct_contribution,
       LEAD(o.ordered_at) OVER (
           PARTITION BY o.customer_code,o.restaurant_code,i.item_code
           ORDER BY o.ordered_at,o.code,i.code) AS next_same_item_purchase_at
FROM clean_order_items i JOIN clean_orders o ON o.code=i.order_code
JOIN clean_restaurants r ON r.code=o.restaurant_code
JOIN clean_menu_items m ON m.code=i.item_code
CROSS JOIN analysis_parameters p
WHERE o.status='completed' AND o.ordered_at<p.as_of;

CREATE OR REPLACE TEMP TABLE rated_lines AS
SELECT s.*,rt.code AS rating_code,rt.score AS rating_score,rt.rated_at,
       CASE WHEN rt.code IS NOT NULL THEN
           CAST(timezone(r.timezone,timezone('UTC',rt.rated_at)) AS DATE) END AS rating_local_date,
       CASE WHEN rt.code IS NOT NULL AND s.customer_code IS NOT NULL
                 AND rt.rated_at+INTERVAL 90 DAY<=p.as_of
            THEN TRUE ELSE FALSE END AS followup_eligible,
       CASE WHEN rt.code IS NOT NULL AND s.customer_code IS NOT NULL
                 AND rt.rated_at+INTERVAL 90 DAY<=p.as_of
            THEN s.next_same_item_purchase_at>rt.rated_at
                 AND s.next_same_item_purchase_at<rt.rated_at+INTERVAL 90 DAY END
           AS repeat_same_item_within_90d
FROM sold_lines s JOIN clean_restaurants r ON r.code=s.restaurant_code
CROSS JOIN analysis_parameters p
LEFT JOIN clean_ratings rt ON rt.order_item_code=s.line_code
                          AND rt.rated_at<p.as_of;

CREATE OR REPLACE TEMP TABLE rating_events AS
SELECT rating_code,line_code,order_code,restaurant_code,item_code,category_code,
       customer_code,purchase_date,purchase_month,promotion_status,
       sold_quantity,net_revenue,direct_contribution,
       rating_score,rated_at,rating_local_date,
       strftime(rating_local_date,'%Y-%m') AS rating_month,
       followup_eligible,repeat_same_item_within_90d
FROM rated_lines WHERE rating_code IS NOT NULL;

CREATE OR REPLACE TEMP TABLE rating_metrics AS
WITH expanded AS (
    SELECT 'item' AS grain,NULL::VARCHAR AS restaurant_code,item_code,
           NULL::VARCHAR AS period,NULL::VARCHAR AS promotion_status,
           sold_quantity,net_revenue,direct_contribution,rating_score,
           followup_eligible,repeat_same_item_within_90d FROM rated_lines
    UNION ALL
    SELECT 'location',restaurant_code,NULL,NULL,NULL,sold_quantity,net_revenue,
           direct_contribution,rating_score,followup_eligible,repeat_same_item_within_90d
    FROM rated_lines
    UNION ALL
    SELECT 'item_location',restaurant_code,item_code,NULL,NULL,sold_quantity,
           net_revenue,direct_contribution,rating_score,followup_eligible,
           repeat_same_item_within_90d FROM rated_lines
    UNION ALL
    SELECT 'purchase_month',NULL,NULL,purchase_month,NULL,sold_quantity,
           net_revenue,direct_contribution,rating_score,followup_eligible,
           repeat_same_item_within_90d FROM rated_lines
    UNION ALL
    SELECT 'promotion_status',NULL,NULL,NULL,promotion_status,sold_quantity,
           net_revenue,direct_contribution,rating_score,followup_eligible,
           repeat_same_item_within_90d FROM rated_lines
    UNION ALL
    SELECT 'item_location_month_promotion',restaurant_code,item_code,
           purchase_month,promotion_status,sold_quantity,net_revenue,
           direct_contribution,rating_score,followup_eligible,
           repeat_same_item_within_90d FROM rated_lines
)
SELECT grain,restaurant_code,item_code,period,promotion_status,
       COUNT(*) AS sold_lines,SUM(sold_quantity) AS sold_quantity,
       SUM(net_revenue) AS net_revenue,
       SUM(direct_contribution) AS direct_contribution,
       CASE WHEN SUM(net_revenue)>0 THEN SUM(direct_contribution)/SUM(net_revenue) END
           AS direct_margin_rate,
       COUNT(rating_score) AS rating_count,
       COUNT(*)-COUNT(rating_score) AS unrated_lines,
       AVG(rating_score) AS mean_rating,
       COUNT(*) FILTER (WHERE rating_score<=2) AS low_rating_count,
       COUNT(*) FILTER (WHERE rating_score>=4) AS high_rating_count,
       COUNT(*) FILTER (WHERE followup_eligible) AS repeat_followup_eligible_ratings,
       COUNT(*) FILTER (WHERE repeat_same_item_within_90d) AS repeat_same_item_90d_count,
       CASE WHEN COUNT(*) FILTER (WHERE followup_eligible)>0 THEN
           COUNT(*) FILTER (WHERE repeat_same_item_within_90d)::DOUBLE/
           COUNT(*) FILTER (WHERE followup_eligible) END AS repeat_same_item_90d_rate,
       COUNT(rating_score)::DOUBLE/COUNT(*) AS rating_coverage
FROM expanded GROUP BY grain,restaurant_code,item_code,period,promotion_status;
