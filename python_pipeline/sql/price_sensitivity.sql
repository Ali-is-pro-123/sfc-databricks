-- Peers share location, category and transition date, but exclude the target item.
CREATE OR REPLACE TEMP TABLE transition_evidence AS
WITH comparable AS (
    SELECT t.*,
           CASE WHEN t.prior_sold_per_day>0 AND t.sold_per_exposure_day>0
                THEN ln(t.sold_per_exposure_day/t.prior_sold_per_day) END AS demand_log_change,
           CASE WHEN t.sold_quantity>0 THEN t.promoted_quantity/t.sold_quantity END AS promoted_share
    FROM price_transitions t
), peers AS (
    SELECT a.price_code,COUNT(b.item_code) AS peer_count,
           median(b.demand_log_change) AS peer_median_demand_log_change
    FROM comparable a LEFT JOIN comparable b
      ON a.restaurant_code=b.restaurant_code
     AND a.category_code=b.category_code
     AND a.start_date=b.start_date
     AND a.item_code<>b.item_code
     AND b.prior_exposure_days>=30 AND b.exposure_days>=30
     AND b.prior_sold_quantity>=20 AND b.sold_quantity>=20
     AND b.demand_log_change IS NOT NULL
    GROUP BY a.price_code
), joined AS (
    SELECT a.*,p.peer_count,p.peer_median_demand_log_change,
           CASE WHEN a.prior_sold_quantity>0 THEN
               (a.prior_sold_quantity*a.prior_unit_price-a.prior_net_revenue)/
               (a.prior_sold_quantity*a.prior_unit_price) END AS prior_discount_share,
           CASE WHEN a.sold_quantity>0 THEN
               a.discount_amount/(a.sold_quantity*a.unit_price) END AS current_discount_share
    FROM comparable a JOIN peers p USING (price_code)
)
SELECT price_code,restaurant_code,item_code,category_code,start_date,end_date,
       prior_unit_price,unit_price,price_change_rate,
       prior_exposure_days,exposure_days,prior_sold_quantity,sold_quantity,
       prior_sold_per_day,sold_per_exposure_day,demand_log_change,
       peer_count,peer_median_demand_log_change,
       prior_discount_share,current_discount_share,
       demand_log_change-peer_median_demand_log_change AS peer_adjusted_demand_log_change,
       CASE WHEN price_change_rate>0 AND peer_median_demand_log_change IS NOT NULL
                 AND demand_log_change IS NOT NULL
            THEN -(demand_log_change-peer_median_demand_log_change)/ln(1+price_change_rate)
       END AS response_index,
       CASE WHEN price_change_rate>=0.03 AND prior_exposure_days>=30
                 AND exposure_days>=30 AND prior_sold_quantity>=20
                 AND sold_quantity>=20 AND peer_count>=5
                 AND demand_log_change IS NOT NULL
                 AND ABS(COALESCE(current_discount_share,0)-
                         COALESCE(prior_discount_share,0))<=0.15
            THEN TRUE ELSE FALSE END AS eligible
FROM joined;

CREATE OR REPLACE TEMP TABLE pair_sensitivity AS
WITH evidence AS (
    SELECT restaurant_code,item_code,category_code,
           COUNT(*) AS price_changes,
           COUNT(*) FILTER (WHERE eligible) AS eligible_changes,
           MIN(response_index) FILTER (WHERE eligible) AS min_response_index,
           MAX(response_index) FILTER (WHERE eligible) AS max_response_index,
           AVG(response_index) FILTER (WHERE eligible) AS mean_response_index,
           MIN(peer_count) FILTER (WHERE eligible) AS min_peer_count,
           SUM(prior_sold_quantity+sold_quantity) FILTER (WHERE eligible) AS compared_portions
    FROM transition_evidence GROUP BY 1,2,3
)
SELECT k.restaurant_code,k.item_code,k.category_code,
       COALESCE(e.price_changes,0) AS price_changes,
       COALESCE(e.eligible_changes,0) AS eligible_changes,
       e.min_response_index,e.max_response_index,e.mean_response_index,
       e.min_peer_count,e.compared_portions,
       CASE WHEN COALESCE(e.eligible_changes,0)<2 THEN 'insufficient_evidence'
            WHEN e.min_response_index>=1.5 THEN 'highly_price_sensitive'
            WHEN e.max_response_index<0.5 THEN 'low_price_sensitivity'
            WHEN e.min_response_index>=0.5 AND e.max_response_index<2.5
                 THEN 'moderately_price_sensitive'
            ELSE 'mixed_evidence' END AS sensitivity_class
FROM (SELECT DISTINCT restaurant_code,item_code,category_code FROM price_epochs) k
LEFT JOIN evidence e USING (restaurant_code,item_code,category_code);

CREATE OR REPLACE TEMP TABLE item_sensitivity AS
WITH votes AS (
    SELECT item_code,category_code,COUNT(*) AS locations,
           COUNT(*) FILTER (WHERE sensitivity_class IN
               ('highly_price_sensitive','moderately_price_sensitive','low_price_sensitivity'))
               AS classified_locations,
           COUNT(*) FILTER (WHERE sensitivity_class='highly_price_sensitive') AS high_locations,
           COUNT(*) FILTER (WHERE sensitivity_class='moderately_price_sensitive') AS moderate_locations,
           COUNT(*) FILTER (WHERE sensitivity_class='low_price_sensitivity') AS low_locations,
           COUNT(*) FILTER (WHERE sensitivity_class='mixed_evidence') AS mixed_locations,
           COUNT(*) FILTER (WHERE sensitivity_class='insufficient_evidence') AS insufficient_locations
    FROM pair_sensitivity GROUP BY 1,2
)
SELECT *,CASE WHEN classified_locations<12 THEN 'insufficient_evidence'
              WHEN high_locations>=classified_locations*0.60 THEN 'highly_price_sensitive'
              WHEN moderate_locations>=classified_locations*0.60 THEN 'moderately_price_sensitive'
              WHEN low_locations>=classified_locations*0.60 THEN 'low_price_sensitivity'
              ELSE 'mixed_location_evidence' END AS sensitivity_class
FROM votes;
