-- Rebuild location-level evidence using the same complete-basket population.
CREATE OR REPLACE TEMP TABLE eligible_orders AS
SELECT order_code, restaurant_code
FROM order_coverage
WHERE status = 'completed' AND accepted_line_count > 0
  AND known_rejected_lines = 0
  AND CAST(timezone(timezone, timezone('UTC', ordered_at)) AS DATE) < ?;

CREATE OR REPLACE TEMP TABLE local_basket_items AS
SELECT DISTINCT e.restaurant_code, e.order_code, l.item_code
FROM eligible_orders e JOIN order_lines l ON e.order_code = l.order_code;

CREATE OR REPLACE TEMP TABLE local_basket_counts AS
SELECT restaurant_code, COUNT(*) AS local_baskets
FROM eligible_orders GROUP BY restaurant_code;

CREATE OR REPLACE TEMP TABLE local_item_counts AS
SELECT restaurant_code, item_code, COUNT(*) AS local_item_baskets
FROM local_basket_items GROUP BY restaurant_code, item_code;

CREATE OR REPLACE TEMP TABLE local_pair_counts AS
SELECT a.restaurant_code, a.item_code AS item_a, b.item_code AS item_b,
       COUNT(*) AS local_pair_baskets
FROM local_basket_items a JOIN local_basket_items b
  ON a.restaurant_code = b.restaurant_code AND a.order_code = b.order_code
 AND a.item_code < b.item_code
GROUP BY a.restaurant_code, a.item_code, b.item_code;

-- Global rules are candidates. Local evidence and commercial guards decide.
CREATE OR REPLACE TEMP TABLE pair_screen AS
SELECT lp.restaurant_code, gp.item_a, gp.item_b,
       gp.pair_baskets AS global_pair_baskets,
       gp.support AS global_support, gp.confidence_a_to_b AS global_confidence_a_to_b,
       gp.confidence_b_to_a AS global_confidence_b_to_a, gp.lift AS global_lift,
       lp.local_pair_baskets, bc.local_baskets,
       ia.local_item_baskets AS item_a_baskets,
       ib.local_item_baskets AS item_b_baskets,
       lp.local_pair_baskets::DOUBLE / bc.local_baskets AS local_support,
       lp.local_pair_baskets::DOUBLE / ia.local_item_baskets AS local_confidence_a_to_b,
       lp.local_pair_baskets::DOUBLE / ib.local_item_baskets AS local_confidence_b_to_a,
       (lp.local_pair_baskets::DOUBLE * bc.local_baskets) /
           (ia.local_item_baskets::DOUBLE * ib.local_item_baskets) AS local_lift,
       pa.item_name AS item_a_name, pb.item_name AS item_b_name,
       pa.category_code AS item_a_category, pb.category_code AS item_b_category,
       pa.quantity_sold AS item_a_quantity_90, pb.quantity_sold AS item_b_quantity_90,
       pa.contribution::DOUBLE AS item_a_contribution_90,
       pb.contribution::DOUBLE AS item_b_contribution_90,
       pa.latest_unit_price::DOUBLE AS item_a_price,
       pb.latest_unit_price::DOUBLE AS item_b_price,
       ma.is_available AS item_a_catalog_available,
       mb.is_available AS item_b_catalog_available,
       CASE WHEN lp.local_pair_baskets < 10 THEN 'low_local_pair_count'
            WHEN (lp.local_pair_baskets::DOUBLE * bc.local_baskets) /
                 (ia.local_item_baskets::DOUBLE * ib.local_item_baskets) < 1.05
                 THEN 'weak_local_lift'
            WHEN pa.item_code IS NULL OR pb.item_code IS NULL
                 OR ma.code IS NULL OR mb.code IS NULL THEN 'missing_item_evidence'
            WHEN ma.is_available IS DISTINCT FROM TRUE OR mb.is_available IS DISTINCT FROM TRUE
                 THEN 'catalog_unavailable'
            WHEN pa.contribution IS NULL OR pb.contribution IS NULL
                 OR pa.contribution <= 0 OR pb.contribution <= 0
                 THEN 'nonpositive_direct_contribution'
            WHEN pa.quantity_sold < 5 OR pb.quantity_sold < 5 THEN 'low_local_sales'
            WHEN pa.latest_unit_price IS NULL OR pb.latest_unit_price IS NULL
                 OR pa.latest_unit_price <= 0 OR pb.latest_unit_price <= 0
                 THEN 'missing_positive_price'
            ELSE 'eligible' END AS screen_status
FROM global_pairs gp
JOIN local_pair_counts lp ON gp.item_a = lp.item_a AND gp.item_b = lp.item_b
JOIN local_item_counts ia ON lp.restaurant_code = ia.restaurant_code AND lp.item_a = ia.item_code
JOIN local_item_counts ib ON lp.restaurant_code = ib.restaurant_code AND lp.item_b = ib.item_code
JOIN local_basket_counts bc ON lp.restaurant_code = bc.restaurant_code
LEFT JOIN local_performance pa ON lp.restaurant_code = pa.restaurant_code AND lp.item_a = pa.item_code
LEFT JOIN local_performance pb ON lp.restaurant_code = pb.restaurant_code AND lp.item_b = pb.item_code
LEFT JOIN menu_items ma ON lp.item_a = ma.code
LEFT JOIN menu_items mb ON lp.item_b = mb.code;

CREATE OR REPLACE TEMP TABLE pair_candidates AS
SELECT *, CASE WHEN local_confidence_a_to_b >= 0.15
                    AND local_confidence_b_to_a >= 0.15 AND local_lift >= 1.10
               THEN TRUE ELSE FALSE END AS combo_eligible
FROM pair_screen WHERE screen_status = 'eligible';

CREATE OR REPLACE TEMP TABLE candidate_recommendations AS
WITH pair_ranked AS (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY restaurant_code
                  ORDER BY local_pair_baskets DESC, local_lift DESC, item_a, item_b)
                  AS frequent_rank,
           ROW_NUMBER() OVER (PARTITION BY restaurant_code, combo_eligible
                  ORDER BY local_pair_baskets * local_lift DESC, item_a, item_b)
                  AS combo_rank
    FROM pair_candidates
), directed AS (
    SELECT restaurant_code, item_a AS antecedent_item_code,
           item_b AS consequent_item_code, item_a_name AS antecedent_name,
           item_b_name AS consequent_name, item_a_category AS antecedent_category,
           item_b_category AS consequent_category,
           item_a_price AS antecedent_price, item_b_price AS consequent_price,
           item_a_contribution_90 AS antecedent_contribution_90,
           item_b_contribution_90 AS consequent_contribution_90,
           global_pair_baskets, global_support,
           global_confidence_a_to_b AS global_confidence, global_lift,
           local_pair_baskets, local_baskets, item_a_baskets AS antecedent_baskets,
           item_b_baskets AS consequent_baskets, local_support,
           local_confidence_a_to_b AS local_confidence, local_lift
    FROM pair_candidates
    UNION ALL
    SELECT restaurant_code, item_b, item_a, item_b_name, item_a_name,
           item_b_category, item_a_category, item_b_price, item_a_price,
           item_b_contribution_90, item_a_contribution_90,
           global_pair_baskets, global_support, global_confidence_b_to_a,
           global_lift, local_pair_baskets, local_baskets, item_b_baskets,
           item_a_baskets, local_support, local_confidence_b_to_a, local_lift
    FROM pair_candidates
), directed_ranked AS (
    SELECT *, CASE WHEN consequent_price > antecedent_price * 1.10
                   THEN 'upsell_add_on' ELSE 'cross_sell' END AS recommendation_type,
           ROW_NUMBER() OVER (PARTITION BY restaurant_code, antecedent_item_code,
                   CASE WHEN consequent_price > antecedent_price * 1.10
                        THEN 'upsell_add_on' ELSE 'cross_sell' END
                   ORDER BY local_confidence * local_lift * sqrt(local_pair_baskets) DESC,
                            consequent_item_code) AS local_rank
    FROM directed WHERE local_confidence >= 0.08
)
SELECT restaurant_code, 'frequently_paired' AS recommendation_type,
       item_a AS antecedent_item_code, item_b AS consequent_item_code,
       item_a_name AS antecedent_name, item_b_name AS consequent_name,
       item_a_category AS antecedent_category, item_b_category AS consequent_category,
       item_a_price AS antecedent_price, item_b_price AS consequent_price,
       item_a_contribution_90 AS antecedent_contribution_90,
       item_b_contribution_90 AS consequent_contribution_90,
       global_pair_baskets, global_support, global_confidence_a_to_b AS global_confidence,
       global_lift, local_pair_baskets, local_baskets, item_a_baskets AS antecedent_baskets,
       item_b_baskets AS consequent_baskets, local_support,
       local_confidence_a_to_b AS local_confidence, local_lift,
       frequent_rank AS local_rank,
       'Frequently co-purchased locally; review live stock and offer economics.' AS explanation,
       FALSE AS live_stock_verified
FROM pair_ranked WHERE frequent_rank <= 10
UNION ALL
SELECT restaurant_code, 'combo_meal', item_a, item_b, item_a_name, item_b_name,
       item_a_category, item_b_category, item_a_price, item_b_price,
       item_a_contribution_90, item_b_contribution_90,
       global_pair_baskets, global_support, global_confidence_a_to_b, global_lift,
       local_pair_baskets, local_baskets, item_a_baskets, item_b_baskets,
       local_support, local_confidence_a_to_b, local_lift, combo_rank,
       'Both local rule directions are strong; bundle price and margin need review.', FALSE
FROM pair_ranked WHERE combo_eligible AND combo_rank <= 5
UNION ALL
SELECT restaurant_code, recommendation_type, antecedent_item_code,
       consequent_item_code, antecedent_name, consequent_name,
       antecedent_category, consequent_category, antecedent_price,
       consequent_price, antecedent_contribution_90, consequent_contribution_90,
       global_pair_baskets, global_support, global_confidence, global_lift,
       local_pair_baskets, local_baskets, antecedent_baskets, consequent_baskets,
       local_support, local_confidence, local_lift, local_rank,
       CASE WHEN recommendation_type = 'upsell_add_on'
            THEN 'Higher-priced co-purchased add-on; not evidence for substitution.'
            ELSE 'Co-purchased add-on with positive observed direct contribution.' END,
       FALSE
FROM directed_ranked WHERE local_rank <= 3;
