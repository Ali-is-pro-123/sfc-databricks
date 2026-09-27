-- Price periods use restaurant-local dates. Generated changes start at local midnight.
CREATE OR REPLACE TEMP TABLE price_periods AS
WITH dated AS (
    SELECT p.code AS price_code,p.restaurant_code,p.item_code,m.category_code,
           m.introduced_on,p.unit_price::DOUBLE AS unit_price,
           p.unit_cost::DOUBLE AS unit_cost,
           CAST(timezone(r.timezone, timezone('UTC', p.effective_at)) AS DATE) AS effective_date
    FROM clean_pricing_history p JOIN clean_restaurants r ON r.code=p.restaurant_code
    JOIN clean_menu_items m ON m.code=p.item_code
), periods AS (
    SELECT *,LEAD(effective_date) OVER (
        PARTITION BY restaurant_code,item_code ORDER BY effective_date,price_code) AS next_effective_date
    FROM dated
)
SELECT price_code,restaurant_code,item_code,category_code,unit_price,unit_cost,
       greatest(effective_date,introduced_on) AS start_date,
       least(COALESCE(next_effective_date,CAST(? AS DATE)),CAST(? AS DATE)) AS end_date
FROM periods WHERE greatest(effective_date,introduced_on) <
                   least(COALESCE(next_effective_date,CAST(? AS DATE)),CAST(? AS DATE));

CREATE OR REPLACE TEMP TABLE completed_lines AS
WITH lines AS (
    SELECT i.code AS line_code,o.code AS order_code,o.restaurant_code,i.item_code,
           o.customer_code,CAST(timezone(r.timezone, timezone('UTC', o.ordered_at)) AS DATE) AS local_date,
           o.ordered_at,i.quantity::DOUBLE AS quantity,i.unit_price::DOUBLE AS unit_price,
           i.unit_cost::DOUBLE AS unit_cost,i.discount_amount::DOUBLE AS discount_amount,
           NULLIF(i.promotion_code,'') AS promotion_code,
           rt.score::DOUBLE AS rating_score
    FROM clean_order_items i JOIN clean_orders o ON o.code=i.order_code
    JOIN clean_restaurants r ON r.code=o.restaurant_code
    LEFT JOIN clean_ratings rt ON rt.order_item_code=i.code
    WHERE o.status='completed' AND
          CAST(timezone(r.timezone, timezone('UTC', o.ordered_at)) AS DATE) < CAST(? AS DATE)
), sequenced AS (
    SELECT *,CASE WHEN customer_code IS NOT NULL AND
        ROW_NUMBER() OVER (PARTITION BY restaurant_code,item_code,customer_code
                           ORDER BY ordered_at,order_code,line_code)>1 THEN 1 ELSE 0 END AS repeat_line
    FROM lines
)
SELECT p.price_code,s.* FROM sequenced s JOIN price_periods p
  ON p.restaurant_code=s.restaurant_code AND p.item_code=s.item_code
 AND s.local_date>=p.start_date AND s.local_date<p.end_date;

CREATE OR REPLACE TEMP TABLE price_epochs AS
SELECT p.price_code,p.restaurant_code,p.item_code,p.category_code,
       p.start_date,p.end_date,date_diff('day',p.start_date,p.end_date) AS exposure_days,
       p.unit_price,p.unit_cost,
       COUNT(l.line_code) AS sold_lines,
       COALESCE(SUM(l.quantity),0) AS sold_quantity,
       COALESCE(SUM(l.quantity*l.unit_price-l.discount_amount),0) AS net_revenue,
       COALESCE(SUM(l.quantity*l.unit_cost),0) AS direct_cost,
       COALESCE(SUM(l.discount_amount),0) AS discount_amount,
       COALESCE(SUM(CASE WHEN l.promotion_code IS NOT NULL THEN l.quantity ELSE 0 END),0) AS promoted_quantity,
       COUNT(l.rating_score) AS rated_lines,AVG(l.rating_score) AS mean_rating,
       COUNT(l.customer_code) AS identified_lines,
       COALESCE(SUM(l.repeat_line),0) AS repeat_lines,
       COALESCE(SUM(l.quantity),0)/date_diff('day',p.start_date,p.end_date) AS sold_per_exposure_day,
       CASE WHEN COUNT(l.customer_code)>0 THEN SUM(l.repeat_line)::DOUBLE/COUNT(l.customer_code) END AS repeat_line_rate
FROM price_periods p LEFT JOIN completed_lines l ON l.price_code=p.price_code
GROUP BY p.price_code,p.restaurant_code,p.item_code,p.category_code,
         p.start_date,p.end_date,p.unit_price,p.unit_cost;

CREATE OR REPLACE TEMP TABLE price_transitions AS
WITH sequenced AS (
    SELECT e.*,
           LAG(unit_price) OVER pair AS prior_unit_price,
           LAG(exposure_days) OVER pair AS prior_exposure_days,
           LAG(sold_quantity) OVER pair AS prior_sold_quantity,
           LAG(sold_per_exposure_day) OVER pair AS prior_sold_per_day,
           LAG(net_revenue) OVER pair AS prior_net_revenue,
           LAG(mean_rating) OVER pair AS prior_mean_rating,
           LAG(repeat_line_rate) OVER pair AS prior_repeat_line_rate
    FROM price_epochs e
    WINDOW pair AS (PARTITION BY restaurant_code,item_code ORDER BY start_date,price_code)
)
SELECT *,CASE WHEN prior_unit_price>0 THEN unit_price/prior_unit_price-1 END AS price_change_rate,
       CASE WHEN prior_sold_per_day>0 THEN sold_per_exposure_day/prior_sold_per_day-1 END AS demand_rate_change,
       (net_revenue-direct_cost) AS direct_contribution,
       CASE WHEN prior_unit_price IS NOT NULL AND prior_unit_price<>unit_price
                  AND prior_exposure_days>=30 AND exposure_days>=30
                  AND prior_sold_quantity>=20 AND sold_quantity>=20
                  AND prior_sold_per_day>0
                  AND ABS(sold_per_exposure_day/prior_sold_per_day-1)>=0.20
            THEN TRUE ELSE FALSE END AS notable_demand_change
FROM sequenced WHERE prior_unit_price IS NOT NULL;
