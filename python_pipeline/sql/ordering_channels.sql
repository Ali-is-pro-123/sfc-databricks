-- Preserve completed headers with no accepted lines so AOV matches Step 7.
CREATE TEMP VIEW basket_lines AS
SELECT o.order_code, COUNT(i.code) AS line_count,
       COALESCE(SUM(i.quantity), 0) AS quantity,
       COALESCE(SUM(i.quantity * i.unit_price - i.discount_amount), 0) AS revenue,
       COALESCE(SUM(i.quantity * i.unit_cost), 0) AS cost,
       COALESCE(SUM(i.discount_amount), 0) AS discount
FROM order_features o LEFT JOIN clean_order_items i ON i.order_code = o.order_code
GROUP BY 1;

CREATE TEMP TABLE channel_orders AS
SELECT o.order_code, o.restaurant_code, o.channel_code,
       c.name AS channel_name, o.date AS local_date,
       EXTRACT('hour' FROM timezone(o.timezone, timezone('UTC', o.ordered_at)))::INTEGER AS local_hour,
       o.accepted_line_count, o.accepted_quantity, o.accepted_basket_revenue,
       b.cost AS direct_cost, b.discount,
       o.accepted_basket_revenue - b.cost AS direct_contribution,
       o.known_rejected_lines, o.customer_metric_eligible,
       p.order_code IS NOT NULL AS campaign_tagged
FROM order_features o
JOIN clean_ordering_channels c ON c.code = o.channel_code
JOIN basket_lines b USING (order_code)
LEFT JOIN campaign_orders p USING (order_code);

CREATE TEMP TABLE channel_summary AS
SELECT channel_code, ANY_VALUE(channel_name) AS channel_name,
       COUNT(*) AS completed_orders,
       COUNT(*) FILTER (WHERE accepted_line_count > 0) AS nonempty_orders,
       SUM(accepted_line_count) AS accepted_lines,
       SUM(accepted_quantity) AS sold_quantity,
       SUM(accepted_quantity)::DOUBLE / NULLIF(COUNT(*), 0) AS average_basket_quantity,
       SUM(accepted_line_count)::DOUBLE / NULLIF(COUNT(*), 0) AS average_basket_lines,
       SUM(accepted_basket_revenue) AS revenue,
       SUM(accepted_basket_revenue) / NULLIF(COUNT(*), 0) AS average_order_value,
       SUM(direct_cost) AS direct_cost,
       SUM(direct_contribution) AS direct_contribution,
       100.0 * SUM(direct_contribution) / NULLIF(SUM(accepted_basket_revenue), 0) AS direct_margin_percentage,
       SUM(discount) AS discount,
       COUNT(*) FILTER (WHERE discount > 0) AS discounted_orders,
       COUNT(*) FILTER (WHERE campaign_tagged) AS campaign_tagged_orders,
       COUNT(*) FILTER (WHERE campaign_tagged)::DOUBLE /
           NULLIF(COUNT(*) FILTER (WHERE accepted_line_count > 0), 0) AS campaign_share_of_nonempty_orders,
       COUNT(*) FILTER (WHERE known_rejected_lines > 0) AS partial_orders,
       COUNT(*) FILTER (WHERE accepted_line_count = 0) AS empty_orders
FROM channel_orders GROUP BY 1;

CREATE TEMP TABLE location_channel_summary AS
SELECT restaurant_code, channel_code, ANY_VALUE(channel_name) AS channel_name,
       COUNT(*) AS completed_orders, SUM(accepted_quantity) AS sold_quantity,
       SUM(accepted_basket_revenue) AS revenue,
       SUM(accepted_basket_revenue) / NULLIF(COUNT(*), 0) AS average_order_value,
       SUM(direct_contribution) AS direct_contribution,
       SUM(discount) AS discount,
       COUNT(*) FILTER (WHERE campaign_tagged) AS campaign_tagged_orders
FROM channel_orders GROUP BY 1, 2;

CREATE TEMP TABLE channel_menu_preferences AS
SELECT o.channel_code, ANY_VALUE(o.channel_name) AS channel_name,
       i.item_code, ANY_VALUE(m.name) AS item_name,
       COUNT(*) AS accepted_lines, SUM(i.quantity) AS sold_quantity,
       SUM(i.quantity * i.unit_price - i.discount_amount) AS revenue,
       SUM(i.quantity * (i.unit_price - i.unit_cost) - i.discount_amount) AS direct_contribution,
       DENSE_RANK() OVER (PARTITION BY o.channel_code ORDER BY SUM(i.quantity) DESC) AS quantity_rank
FROM channel_orders o JOIN clean_order_items i USING (order_code)
JOIN clean_menu_items m ON m.code = i.item_code
GROUP BY 1, 3;

CREATE TEMP TABLE channel_peak_hours AS
SELECT channel_code, ANY_VALUE(channel_name) AS channel_name,
       local_hour, COUNT(*) AS completed_orders,
       SUM(accepted_basket_revenue) AS revenue,
       RANK() OVER (PARTITION BY channel_code ORDER BY COUNT(*) DESC) AS order_volume_rank
FROM channel_orders GROUP BY 1, 3;
