-- Completed accepted baskets are grouped before campaign-level aggregation.
CREATE OR REPLACE TEMP TABLE accepted_orders AS
SELECT o.code AS order_code,o.restaurant_code,o.customer_code,o.ordered_at,
       NULLIF(o.promotion_code,'') AS promotion_code,
       COUNT(*) AS accepted_lines,SUM(i.quantity)::DOUBLE AS sold_quantity,
       SUM(i.quantity*i.unit_price-i.discount_amount)::DOUBLE AS net_revenue,
       SUM(i.quantity*i.unit_cost)::DOUBLE AS direct_cost,
       SUM(i.discount_amount)::DOUBLE AS discount_amount,
       SUM(CASE WHEN NULLIF(i.promotion_code,'')=NULLIF(o.promotion_code,'')
                     AND NULLIF(i.promotion_code,'') IS NOT NULL
                THEN i.quantity ELSE 0 END)::DOUBLE AS attributed_quantity,
       SUM(CASE WHEN NULLIF(i.promotion_code,'')=NULLIF(o.promotion_code,'')
                     AND NULLIF(i.promotion_code,'') IS NOT NULL
                THEN i.quantity*i.unit_price-i.discount_amount ELSE 0 END)::DOUBLE
           AS attributed_revenue,
       SUM(CASE WHEN NULLIF(i.promotion_code,'')=NULLIF(o.promotion_code,'')
                     AND NULLIF(i.promotion_code,'') IS NOT NULL
                THEN i.quantity*(i.unit_price-i.unit_cost)-i.discount_amount ELSE 0 END)::DOUBLE
           AS attributed_contribution
FROM clean_orders o JOIN clean_order_items i ON i.order_code=o.code
CROSS JOIN analysis_parameters p
WHERE o.status='completed' AND o.ordered_at<p.as_of
GROUP BY o.code,o.restaurant_code,o.customer_code,o.ordered_at,o.promotion_code;

CREATE OR REPLACE TEMP TABLE customer_first_seen AS
SELECT customer_code,MIN(ordered_at) AS first_order_at
FROM accepted_orders WHERE customer_code IS NOT NULL GROUP BY 1;

CREATE OR REPLACE TEMP TABLE campaign_order_facts AS
SELECT a.*,a.net_revenue-a.direct_cost AS direct_contribution,
       CASE WHEN a.customer_code IS NOT NULL AND a.ordered_at=f.first_order_at
            THEN TRUE ELSE FALSE END AS first_observed_customer_order,
       CASE WHEN a.customer_code IS NOT NULL AND a.ordered_at>f.first_order_at
            THEN TRUE ELSE FALSE END AS returning_customer_order
FROM accepted_orders a JOIN clean_promotions c ON c.code=a.promotion_code
LEFT JOIN customer_first_seen f ON f.customer_code=a.customer_code
WHERE a.ordered_at>=c.starts_at AND a.ordered_at<c.ends_at;

CREATE OR REPLACE TEMP TABLE campaign_sales AS
SELECT promotion_code,COUNT(*) AS order_volume,
       SUM(sold_quantity) AS sold_quantity,SUM(net_revenue) AS net_revenue,
       SUM(direct_cost) AS direct_cost,SUM(direct_contribution) AS direct_contribution,
       SUM(discount_amount) AS discount_amount,
       SUM(attributed_quantity) AS attributed_quantity,
       SUM(attributed_revenue) AS attributed_revenue,
       SUM(attributed_contribution) AS attributed_contribution,
       SUM(net_revenue)/COUNT(*) AS average_order_value,
       COUNT(DISTINCT customer_code) AS identified_customers,
       COUNT(DISTINCT customer_code) FILTER (WHERE first_observed_customer_order)
           AS first_observed_customers,
       COUNT(DISTINCT customer_code) FILTER (WHERE returning_customer_order)
           AS returning_customers
FROM campaign_order_facts GROUP BY 1;

-- Follow-up is customer-level, not a count of every later basket.
CREATE OR REPLACE TEMP TABLE campaign_followup AS
WITH customers AS (
    SELECT DISTINCT promotion_code,customer_code FROM campaign_order_facts
    WHERE customer_code IS NOT NULL
)
SELECT x.promotion_code,
       COUNT(DISTINCT x.customer_code) FILTER (WHERE a.order_code IS NOT NULL)
           AS post_30_day_repeat_customers,
       COUNT(DISTINCT a.order_code) AS post_30_day_orders,
       SUM(a.net_revenue) AS post_30_day_revenue
FROM customers x JOIN clean_promotions c ON c.code=x.promotion_code
CROSS JOIN analysis_parameters p
LEFT JOIN accepted_orders a ON a.customer_code=x.customer_code
     AND a.ordered_at>=c.ends_at
     AND a.ordered_at<least(c.ends_at+INTERVAL 30 DAY,p.as_of)
GROUP BY x.promotion_code;

-- Wastage is for eligible items while a campaign is active, not attributed waste.
CREATE OR REPLACE TEMP TABLE campaign_waste AS
SELECT c.code AS promotion_code,
       SUM(CASE WHEN w.recorded_at>=c.starts_at AND w.recorded_at<c.ends_at
                THEN w.wasted_quantity ELSE 0 END)::DOUBLE AS active_wasted_quantity,
       SUM(CASE WHEN w.recorded_at>=c.starts_at AND w.recorded_at<c.ends_at
                THEN w.wasted_quantity*w.unit_cost ELSE 0 END)::DOUBLE AS active_waste_cost,
       SUM(CASE WHEN w.recorded_at>=c.starts_at-(c.ends_at-c.starts_at)
                     AND w.recorded_at<c.starts_at
                THEN w.wasted_quantity ELSE 0 END)::DOUBLE AS prior_equal_window_wasted_quantity
FROM clean_promotions c JOIN clean_promotion_items pi ON pi.promotion_code=c.code
LEFT JOIN clean_wastage w ON w.item_code=pi.item_code
    AND w.recorded_at>=c.starts_at-(c.ends_at-c.starts_at)
    AND w.recorded_at<c.ends_at
GROUP BY c.code;

CREATE OR REPLACE TEMP TABLE promotion_effectiveness AS
SELECT c.code AS promotion_code,c.name,c.starts_at,c.ends_at,
       date_diff('day',c.starts_at,c.ends_at) AS campaign_days,
       c.discount_percent::DOUBLE AS advertised_discount_percent,
       COUNT(DISTINCT pi.item_code) AS eligible_items,
       COALESCE(s.order_volume,0) AS order_volume,
       COALESCE(s.sold_quantity,0) AS sold_quantity,
       COALESCE(s.net_revenue,0) AS net_revenue,
       COALESCE(s.direct_cost,0) AS direct_cost,
       COALESCE(s.direct_contribution,0) AS direct_contribution,
       COALESCE(s.discount_amount,0) AS discount_amount,
       COALESCE(s.attributed_quantity,0) AS attributed_quantity,
       COALESCE(s.attributed_revenue,0) AS attributed_revenue,
       COALESCE(s.attributed_contribution,0) AS attributed_contribution,
       s.average_order_value,
       COALESCE(s.identified_customers,0) AS identified_customers,
       COALESCE(s.first_observed_customers,0) AS first_observed_customers,
       COALESCE(s.returning_customers,0) AS returning_customers,
       COALESCE(f.post_30_day_repeat_customers,0) AS post_30_day_repeat_customers,
       COALESCE(f.post_30_day_orders,0) AS post_30_day_orders,
       COALESCE(f.post_30_day_revenue,0) AS post_30_day_revenue,
       p.as_of>=c.ends_at+INTERVAL 30 DAY AS followup_complete,
       COALESCE(w.active_wasted_quantity,0) AS active_eligible_item_waste,
       COALESCE(w.active_waste_cost,0) AS active_eligible_item_waste_cost,
       COALESCE(w.prior_equal_window_wasted_quantity,0) AS prior_equal_window_eligible_item_waste,
       CASE WHEN s.net_revenue>0 THEN s.direct_contribution/s.net_revenue END AS contribution_margin_rate,
       CASE WHEN s.identified_customers>0 THEN
           f.post_30_day_repeat_customers::DOUBLE/s.identified_customers END AS post_30_day_repeat_rate
FROM clean_promotions c CROSS JOIN analysis_parameters p
LEFT JOIN clean_promotion_items pi ON pi.promotion_code=c.code
LEFT JOIN campaign_sales s ON s.promotion_code=c.code
LEFT JOIN campaign_followup f ON f.promotion_code=c.code
LEFT JOIN campaign_waste w ON w.promotion_code=c.code
GROUP BY c.code,c.name,c.starts_at,c.ends_at,c.discount_percent,p.as_of,
         s.order_volume,s.sold_quantity,s.net_revenue,s.direct_cost,
         s.direct_contribution,s.discount_amount,s.attributed_quantity,
         s.attributed_revenue,s.attributed_contribution,s.average_order_value,
         s.identified_customers,s.first_observed_customers,s.returning_customers,
         f.post_30_day_repeat_customers,f.post_30_day_orders,f.post_30_day_revenue,
         w.active_wasted_quantity,w.active_waste_cost,w.prior_equal_window_wasted_quantity;
