CREATE TEMP VIEW segment_risk AS
SELECT behavioral_segment, COUNT(*) AS customers,
       COUNT(*) FILTER (WHERE churn_review_band = 'High Review Priority') AS high_review_customers,
       SUM(recent_90_spend) AS recent_90_spend
FROM churn_risk GROUP BY 1;

CREATE TEMP VIEW location_anomaly_counts AS
SELECT restaurant_code,
       COUNT(*) FILTER (WHERE sudden_sales_spike OR sudden_sales_drop) AS flagged_days,
       COUNT(*) FILTER (WHERE sudden_sales_drop) AS drop_days,
       COUNT(*) FILTER (WHERE sudden_sales_spike) AS spike_days
FROM location_day_anomalies
WHERE local_date >= (SELECT window_start FROM analysis_parameters)
  AND local_date < (SELECT as_of FROM analysis_parameters)
GROUP BY 1;

CREATE TEMP TABLE recommendation_candidates AS
SELECT 'promote_hidden_opportunity' AS recommendation_type,
       'item_location' AS scope, m.restaurant_code, m.item_code AS subject_code,
       NULL::VARCHAR AS related_code,
       'Review targeted promotion for this local Hidden Opportunity' AS recommended_action,
       json_object('location_class',m.location_menu_class,'direct_margin_percentage',m.direct_margin_percentage,
                   'average_rating',m.average_rating,'rating_count',m.rating_count,
                   'accounted_wastage_percentage',m.accounted_wastage_percentage,
                   'order_frequency',m.order_frequency,'provisional',m.provisional_evidence)::VARCHAR AS evidence_json,
       'Step 34' AS source_steps
FROM location_menu_items m
WHERE m.location_menu_class='Hidden Opportunity' AND NOT m.provisional_evidence
  AND m.contribution>0 AND m.direct_margin_percentage>=30
  AND m.rating_count>=10 AND m.average_rating>=4
  AND m.accounted_wastage_percentage<15

UNION ALL
SELECT 'review_preparation_quantity','item_location',s.restaurant_code,s.item_code,NULL,
       'Review preparation quantity and waste controls; do not change stock automatically',
       json_object('wasted_quantity',s.wasted_quantity,
                   'accounted_wastage_percentage',s.accounted_wastage_percentage,
                   'movement_class',s.movement_class,'quantity_sold',s.quantity_sold)::VARCHAR,
       'Step 32'
FROM slow_pairs s
WHERE s.high_wastage AND s.wasted_quantity>=10
  AND s.accounted_wastage_percentage>=25

UNION ALL
SELECT 'review_price_sensitivity','item_location',p.restaurant_code,p.item_code,NULL,
       'Review local pricing evidence before any price change',
       json_object('sensitivity_class',p.sensitivity_class,'eligible_changes',p.eligible_changes,
                   'min_response_index',p.min_response_index,
                   'max_response_index',p.max_response_index,
                   'compared_portions',p.compared_portions)::VARCHAR,
       'Step 26'
FROM price_sensitivity p
WHERE p.sensitivity_class='highly_price_sensitive' AND p.eligible_changes>=2

UNION ALL
SELECT 'review_bundle','item_pair_location',b.restaurant_code,b.antecedent_item_code,
       b.consequent_item_code,
       'Review a bundle or frequently paired offer after stock and margin checks',
       json_object('candidate_type',b.recommendation_type,'local_pair_baskets',b.local_pair_baskets,
                   'local_confidence',b.local_confidence,'local_lift',b.local_lift,
                   'antecedent_contribution_90',b.antecedent_contribution_90,
                   'consequent_contribution_90',b.consequent_contribution_90,
                   'live_stock_verified',b.live_stock_verified)::VARCHAR,
       'Step 18'
FROM (SELECT *, ROW_NUMBER() OVER (
          PARTITION BY restaurant_code,antecedent_item_code,consequent_item_code
          ORDER BY local_rank, recommendation_type) AS candidate_row
      FROM bundle_candidates
      WHERE recommendation_type IN ('combo_meal','frequently_paired')
        AND local_rank<=3) b
WHERE b.candidate_row=1
  AND b.antecedent_contribution_90>0 AND b.consequent_contribution_90>0

UNION ALL
SELECT 'review_low_performer','item_location',m.restaurant_code,m.item_code,NULL,
       'Review redesign or retirement of this persistent local Low Performer',
       json_object('location_class',m.location_menu_class,'movement_class',s.movement_class,
                   'item_age_days',s.item_age_days,'quantity_sold',m.quantity_sold,
                   'direct_contribution',m.contribution,'provisional',m.provisional_evidence)::VARCHAR,
       'Steps 32, 34'
FROM location_menu_items m JOIN slow_pairs s USING (restaurant_code,item_code)
WHERE m.location_menu_class='Low Performer' AND s.movement_class='slow_moving'
  AND s.item_age_days>=60 AND NOT m.provisional_evidence

UNION ALL
SELECT 'review_segment_outreach','customer_segment',NULL,g.behavioral_segment,NULL,
       'Review a consent-aware outreach test for this at-risk segment',
       json_object('customers',g.customers,'high_review_customers',g.high_review_customers,
                   'high_review_share',g.high_review_customers::DOUBLE/g.customers,
                   'recent_90_spend',g.recent_90_spend)::VARCHAR,
       'Steps 15, 36'
FROM segment_risk g
WHERE g.customers>=100 AND g.high_review_customers>=100
  AND g.high_review_customers::DOUBLE/g.customers>=0.30

UNION ALL
SELECT 'review_promotion','promotion',NULL,p.promotion_code,NULL,
       'Investigate potential promotion trap before changing the campaign',
       json_object('tagged_campaign_orders',p.tagged_campaign_orders,
                   'sales_up_contribution_down',p.sales_up_contribution_down,
                   'customers_up_margin_down',p.customers_up_margin_down,
                   'eligible_waste_up',p.eligible_waste_up,
                   'low_post_discount_repeat',p.low_post_discount_repeat,
                   'possible_high_margin_cannibalization',p.possible_high_margin_cannibalization)::VARCHAR,
       'Step 28'
FROM promotion_traps p
WHERE p.sales_up_contribution_down OR p.customers_up_margin_down
   OR p.eligible_waste_up OR p.low_post_discount_repeat
   OR p.possible_high_margin_cannibalization

UNION ALL
SELECT 'investigate_location_anomaly','location',a.restaurant_code,a.restaurant_code,NULL,
       'Investigate repeated unusual sales days at this location',
       json_object('flagged_days',a.flagged_days,'drop_days',a.drop_days,
                   'spike_days',a.spike_days)::VARCHAR,
       'Step 31'
FROM location_anomaly_counts a WHERE a.flagged_days>=3;
