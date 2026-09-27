CREATE TEMP VIEW eligible_customer_visits AS
SELECT restaurant_code, customer_code, COUNT(*) AS visits
FROM order_features
WHERE customer_metric_eligible AND customer_code IS NOT NULL
GROUP BY 1, 2;

CREATE TEMP VIEW customer_location AS
SELECT restaurant_code, COUNT(*) AS eligible_customers,
       SUM(visits) AS eligible_customer_orders,
       COUNT(*) FILTER (WHERE visits >= 2) AS repeat_customers
FROM eligible_customer_visits GROUP BY 1;

CREATE TEMP VIEW order_location AS
SELECT restaurant_code, COUNT(*) AS completed_orders,
       COUNT(*) FILTER (WHERE accepted_line_count > 0) AS nonempty_orders,
       SUM(accepted_line_count) AS accepted_lines,
       SUM(accepted_basket_revenue) AS order_revenue
FROM order_features GROUP BY 1;

CREATE TEMP VIEW menu_location AS
SELECT p.restaurant_code, COUNT(*) AS menu_pairs,
       COUNT(*) FILTER (WHERE p.quantity_sold > 0) AS selling_items,
       SUM(p.revenue) AS menu_revenue,
       SUM(p.cost) AS menu_cost,
       SUM(p.quantity_sold) AS menu_quantity,
       COUNT(*) FILTER (WHERE s.movement_class = 'slow_moving') AS slow_moving_items,
       COUNT(*) FILTER (WHERE s.movement_class = 'watchlist') AS watchlist_items
FROM performance p JOIN slow_pairs s USING (restaurant_code, item_code)
GROUP BY 1;

CREATE TEMP VIEW waste_location AS
SELECT restaurant_code, SUM(wasted_quantity) AS wasted_quantity,
       SUM(waste_cost) AS waste_cost, SUM(consumed_quantity) AS inventory_consumption
FROM wastage_daily
WHERE business_date >= (SELECT window_start FROM analysis_parameters)
  AND business_date < (SELECT as_of FROM analysis_parameters)
GROUP BY 1;

CREATE TEMP VIEW rating_location AS
SELECT restaurant_code, COUNT(*) AS ratings_submitted,
       AVG(rating_score) AS average_rating,
       COUNT(*) FILTER (WHERE rating_score <= 2) AS low_ratings
FROM rating_events
WHERE rating_local_date >= (SELECT window_start FROM analysis_parameters)
  AND rating_local_date < (SELECT as_of FROM analysis_parameters)
GROUP BY 1;

CREATE TEMP VIEW promo_location AS
SELECT c.restaurant_code, COUNT(*) AS tagged_promo_orders,
       SUM(c.net_revenue) AS promo_revenue,
       SUM(c.direct_contribution) AS promo_direct_contribution,
       SUM(c.attributed_contribution) AS promo_attributed_contribution,
       SUM(c.discount_amount) AS promo_discount
FROM campaign_orders c JOIN order_features o USING (order_code, restaurant_code)
GROUP BY 1;

CREATE TEMP TABLE location_intelligence AS
SELECT l.restaurant_code, l.restaurant_name, l.city,
       (SELECT window_start FROM analysis_parameters) AS window_start,
       (SELECT as_of FROM analysis_parameters) AS as_of_exclusive,
       l.order_frequency AS completed_orders, o.nonempty_orders, o.accepted_lines,
       l.revenue, l.cost, l.contribution, l.profit_percentage AS direct_margin_percentage,
       l.accepted_average_order_value AS average_order_value,
       l.quantity_sold, l.partial_orders, l.empty_orders,
       c.eligible_customers, c.eligible_customer_orders, c.repeat_customers,
       c.repeat_customers::DOUBLE / NULLIF(c.eligible_customers, 0) AS repeat_customer_rate,
       COALESCE(w.wasted_quantity, 0) AS wasted_quantity,
       COALESCE(w.waste_cost, 0) AS waste_cost,
       w.inventory_consumption,
       COALESCE(w.wasted_quantity, 0)::DOUBLE /
           NULLIF(l.quantity_sold + COALESCE(w.wasted_quantity, 0), 0) AS accounted_waste_share,
       r.ratings_submitted, r.average_rating, r.low_ratings,
       p.tagged_promo_orders, p.promo_revenue, p.promo_direct_contribution,
       p.promo_attributed_contribution, p.promo_discount,
       p.tagged_promo_orders::DOUBLE / NULLIF(o.nonempty_orders, 0) AS promo_order_share,
       m.menu_pairs, m.selling_items, m.slow_moving_items, m.watchlist_items,
       RANK() OVER (ORDER BY l.revenue DESC) AS revenue_rank,
       RANK() OVER (ORDER BY l.contribution DESC) AS contribution_rank
FROM location_features l
JOIN order_location o USING (restaurant_code)
JOIN menu_location m USING (restaurant_code)
LEFT JOIN customer_location c USING (restaurant_code)
LEFT JOIN waste_location w USING (restaurant_code)
LEFT JOIN rating_location r USING (restaurant_code)
LEFT JOIN promo_location p USING (restaurant_code);
