-- Compare the same campaign-eligible items in equal-length prior and active windows.
CREATE OR REPLACE TEMP TABLE eligible_window_lines AS
SELECT c.code AS promotion_code,l.restaurant_code,i.item_code,m.category_code,
       l.customer_code,l.order_code,l.ordered_at,
       CASE WHEN l.ordered_at<c.starts_at THEN 'prior' ELSE 'active' END AS period,
       i.quantity::DOUBLE AS quantity,
       (i.quantity*i.unit_price-i.discount_amount)::DOUBLE AS net_revenue,
       (i.quantity*(i.unit_price-i.unit_cost)-i.discount_amount)::DOUBLE AS contribution,
       i.discount_amount::DOUBLE AS discount_amount
FROM clean_promotions c JOIN clean_promotion_items pi ON pi.promotion_code=c.code
JOIN clean_order_items i ON i.item_code=pi.item_code
JOIN accepted_orders l ON l.order_code=i.order_code
JOIN clean_menu_items m ON m.code=i.item_code
WHERE l.ordered_at>=c.starts_at-(c.ends_at-c.starts_at)
  AND l.ordered_at<c.ends_at;

CREATE OR REPLACE TEMP TABLE eligible_window_metrics AS
SELECT promotion_code,
       COUNT(DISTINCT order_code) FILTER (WHERE period='prior') AS prior_orders,
       COUNT(DISTINCT order_code) FILTER (WHERE period='active') AS active_orders,
       COUNT(DISTINCT customer_code) FILTER (WHERE period='prior') AS prior_customers,
       COUNT(DISTINCT customer_code) FILTER (WHERE period='active') AS active_customers,
       SUM(quantity) FILTER (WHERE period='prior') AS prior_quantity,
       SUM(quantity) FILTER (WHERE period='active') AS active_quantity,
       SUM(net_revenue) FILTER (WHERE period='prior') AS prior_revenue,
       SUM(net_revenue) FILTER (WHERE period='active') AS active_revenue,
       SUM(contribution) FILTER (WHERE period='prior') AS prior_contribution,
       SUM(contribution) FILTER (WHERE period='active') AS active_contribution,
       SUM(discount_amount) FILTER (WHERE period='prior') AS prior_discount,
       SUM(discount_amount) FILTER (WHERE period='active') AS active_discount
FROM eligible_window_lines GROUP BY promotion_code;

-- Noneligible peers share the campaign's category and location.
CREATE OR REPLACE TEMP TABLE category_window_lines AS
SELECT c.code AS promotion_code,a.restaurant_code,i.item_code,m.category_code,
       CASE WHEN a.ordered_at<c.starts_at THEN 'prior' ELSE 'active' END AS period,
       i.quantity::DOUBLE AS quantity,
       (i.quantity*(i.unit_price-i.unit_cost)-i.discount_amount)::DOUBLE AS contribution,
       CASE WHEN pi.item_code IS NOT NULL THEN TRUE ELSE FALSE END AS eligible_item
FROM clean_promotions c
JOIN (SELECT DISTINCT promotion_code, m.category_code
      FROM clean_promotion_items pi JOIN clean_menu_items m ON m.code=pi.item_code) categories
  ON categories.promotion_code=c.code
JOIN clean_menu_items m ON m.category_code=categories.category_code
JOIN clean_order_items i ON i.item_code=m.code
JOIN accepted_orders a ON a.order_code=i.order_code
LEFT JOIN clean_promotion_items pi ON pi.promotion_code=c.code AND pi.item_code=i.item_code
WHERE a.ordered_at>=c.starts_at-(c.ends_at-c.starts_at)
  AND a.ordered_at<c.ends_at;

CREATE OR REPLACE TEMP TABLE category_item_windows AS
SELECT promotion_code,restaurant_code,category_code,item_code,
       bool_or(eligible_item) AS eligible_item,
       COALESCE(SUM(quantity) FILTER (WHERE period='prior'),0) AS prior_quantity,
       COALESCE(SUM(quantity) FILTER (WHERE period='active'),0) AS active_quantity,
       COALESCE(SUM(contribution) FILTER (WHERE period='prior'),0) AS prior_contribution,
       COALESCE(SUM(contribution) FILTER (WHERE period='active'),0) AS active_contribution
FROM category_window_lines GROUP BY 1,2,3,4;

CREATE OR REPLACE TEMP TABLE cannibalization_candidates AS
SELECT e.promotion_code,e.restaurant_code,e.category_code,
       e.item_code AS promoted_item_code,p.item_code AS peer_item_code,
       e.prior_quantity AS promoted_prior_quantity,
       e.active_quantity AS promoted_active_quantity,
       p.prior_quantity AS peer_prior_quantity,
       p.active_quantity AS peer_active_quantity,
       e.active_contribution/e.active_quantity AS promoted_active_contribution_per_portion,
       p.prior_contribution/p.prior_quantity AS peer_prior_contribution_per_portion
FROM category_item_windows e JOIN category_item_windows p
  ON e.promotion_code=p.promotion_code
 AND e.restaurant_code=p.restaurant_code AND e.category_code=p.category_code
 AND e.item_code<>p.item_code
WHERE e.eligible_item AND NOT p.eligible_item
  AND e.prior_quantity>=20 AND e.active_quantity>=20
  AND e.active_quantity>=e.prior_quantity*1.20
  AND p.prior_quantity>=20 AND p.active_quantity<=p.prior_quantity*0.80
  AND p.prior_contribution/p.prior_quantity>
      e.active_contribution/e.active_quantity;

CREATE OR REPLACE TEMP TABLE promotion_traps AS
SELECT p.promotion_code,p.name,p.starts_at,p.ends_at,p.campaign_days,
       p.order_volume AS tagged_campaign_orders,
       p.net_revenue AS tagged_campaign_revenue,
       p.direct_contribution AS tagged_campaign_contribution,
       p.identified_customers,p.post_30_day_repeat_rate,p.followup_complete,
       COALESCE(w.prior_orders,0) AS prior_eligible_orders,
       COALESCE(w.active_orders,0) AS active_eligible_orders,
       COALESCE(w.prior_customers,0) AS prior_eligible_customers,
       COALESCE(w.active_customers,0) AS active_eligible_customers,
       COALESCE(w.prior_quantity,0) AS prior_eligible_quantity,
       COALESCE(w.active_quantity,0) AS active_eligible_quantity,
       COALESCE(w.prior_revenue,0) AS prior_eligible_revenue,
       COALESCE(w.active_revenue,0) AS active_eligible_revenue,
       COALESCE(w.prior_contribution,0) AS prior_eligible_contribution,
       COALESCE(w.active_contribution,0) AS active_eligible_contribution,
       CASE WHEN w.prior_revenue>0 THEN w.prior_contribution/w.prior_revenue END AS prior_margin_rate,
       CASE WHEN w.active_revenue>0 THEN w.active_contribution/w.active_revenue END AS active_margin_rate,
       p.prior_equal_window_eligible_item_waste AS prior_eligible_waste,
       p.active_eligible_item_waste AS active_eligible_waste,
       COALESCE(c.candidate_count,0) AS cannibalization_candidate_count,
       CASE WHEN w.prior_quantity>=50 AND w.active_quantity>=w.prior_quantity*1.20
                 AND w.prior_contribution>0 AND w.active_contribution<w.prior_contribution*0.90
            THEN TRUE ELSE FALSE END AS sales_up_contribution_down,
       CASE WHEN w.prior_customers>=20 AND w.active_customers>=w.prior_customers*1.10
                 AND w.prior_revenue>0 AND w.active_revenue>0
                 AND w.active_contribution/w.active_revenue<=
                     w.prior_contribution/w.prior_revenue-0.10
            THEN TRUE ELSE FALSE END AS customers_up_margin_down,
       CASE WHEN p.prior_equal_window_eligible_item_waste>=10
                 AND p.active_eligible_item_waste>=
                     p.prior_equal_window_eligible_item_waste*1.20
                 AND p.active_eligible_item_waste-
                     p.prior_equal_window_eligible_item_waste>=10
            THEN TRUE ELSE FALSE END AS eligible_waste_up,
       CASE WHEN p.followup_complete AND p.identified_customers>=30
                 AND p.attributed_quantity>=p.sold_quantity*0.20
                 AND p.post_30_day_repeat_rate<=0.05
            THEN TRUE ELSE FALSE END AS low_post_discount_repeat,
       COALESCE(c.candidate_count,0)>0 AS possible_high_margin_cannibalization
FROM promotion_effectiveness p
LEFT JOIN eligible_window_metrics w USING (promotion_code)
LEFT JOIN (SELECT promotion_code,COUNT(*) AS candidate_count
           FROM cannibalization_candidates GROUP BY 1) c USING (promotion_code);
