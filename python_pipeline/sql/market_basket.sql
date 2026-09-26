-- Complete completed orders form the denominator, including one-item baskets.
CREATE OR REPLACE TEMP TABLE eligible_orders AS
SELECT order_code, accepted_line_count, accepted_basket_revenue
FROM order_coverage
WHERE status = 'completed' AND accepted_line_count > 0
  AND known_rejected_lines = 0
  AND CAST(timezone(timezone, timezone('UTC', ordered_at)) AS DATE) < ?;

CREATE OR REPLACE TEMP TABLE line_reconciliation AS
SELECT e.order_code, COUNT(*) AS actual_lines, SUM(l.revenue) AS actual_revenue,
       MAX(e.accepted_line_count) AS expected_lines,
       MAX(e.accepted_basket_revenue) AS expected_revenue
FROM eligible_orders e JOIN order_lines l ON l.order_code = e.order_code
GROUP BY e.order_code;

-- Presence, not line quantity, drives support and confidence.
CREATE OR REPLACE TEMP TABLE basket_items AS
SELECT DISTINCT e.order_code, l.item_code
FROM eligible_orders e JOIN order_lines l ON l.order_code = e.order_code;

CREATE OR REPLACE TEMP TABLE item_counts AS
SELECT item_code, COUNT(*) AS item_baskets
FROM basket_items GROUP BY item_code;

CREATE OR REPLACE TEMP TABLE pair_counts AS
SELECT a.item_code AS item_a, b.item_code AS item_b,
       COUNT(*) AS pair_baskets
FROM basket_items a JOIN basket_items b
  ON a.order_code = b.order_code AND a.item_code < b.item_code
GROUP BY a.item_code, b.item_code;

CREATE OR REPLACE TEMP TABLE frequent_pairs AS
SELECT p.item_a, p.item_b, p.pair_baskets,
       a.item_baskets AS item_a_baskets, b.item_baskets AS item_b_baskets,
       n.baskets AS total_baskets,
       p.pair_baskets::DOUBLE / n.baskets AS support,
       p.pair_baskets::DOUBLE / a.item_baskets AS confidence_a_to_b,
       p.pair_baskets::DOUBLE / b.item_baskets AS confidence_b_to_a,
       (p.pair_baskets::DOUBLE * n.baskets) /
           (a.item_baskets::DOUBLE * b.item_baskets) AS lift
FROM pair_counts p JOIN item_counts a ON p.item_a = a.item_code
JOIN item_counts b ON p.item_b = b.item_code
CROSS JOIN (SELECT COUNT(*) AS baskets FROM eligible_orders) n
WHERE p.pair_baskets >= ?;

CREATE OR REPLACE TEMP TABLE association_rules AS
SELECT item_a AS antecedent_item_code, item_b AS consequent_item_code,
       pair_baskets, item_a_baskets AS antecedent_baskets,
       item_b_baskets AS consequent_baskets, total_baskets,
       support, confidence_a_to_b AS confidence, lift
FROM frequent_pairs
UNION ALL
SELECT item_b, item_a, pair_baskets, item_b_baskets,
       item_a_baskets, total_baskets, support, confidence_b_to_a, lift
FROM frequent_pairs;
