-- An eligible visit has a known, complete accepted basket before the cutoff.
CREATE OR REPLACE TEMP TABLE eligible_orders AS
SELECT order_code, customer_code, restaurant_code, accepted_line_count,
       accepted_basket_revenue,
       CAST(timezone(timezone, timezone('UTC', ordered_at)) AS DATE) AS local_date
FROM order_coverage
WHERE status = 'completed' AND customer_code IS NOT NULL
  AND accepted_line_count > 0 AND known_rejected_lines = 0
  AND CAST(timezone(timezone, timezone('UTC', ordered_at)) AS DATE) < ?;

-- Line facts are collapsed before customer aggregation, so visits count once.
CREATE OR REPLACE TEMP TABLE visit_facts AS
SELECT e.order_code, e.customer_code, e.local_date,
       COUNT(*) AS line_count, SUM(l.revenue) AS revenue,
       SUM(l.quantity) AS quantity, ANY_VALUE(l.channel_code) AS channel_code,
       EXTRACT('hour' FROM MIN(l.ordered_local_at)) AS local_hour,
       MAX(CASE WHEN l.order_promotion_code IS NOT NULL
                     OR l.line_promotion_code IS NOT NULL
                     OR l.discount_amount > 0 THEN 1 ELSE 0 END) AS promoted,
       MAX(e.accepted_line_count) AS expected_line_count,
       MAX(e.accepted_basket_revenue) AS expected_revenue
FROM eligible_orders e JOIN order_lines l ON l.order_code = e.order_code
GROUP BY e.order_code, e.customer_code, e.local_date;

CREATE OR REPLACE TEMP TABLE customer_summary AS
SELECT customer_code, COUNT(*) AS lifetime_visits, SUM(revenue) AS lifetime_monetary,
       MIN(local_date) AS first_visit, MAX(local_date) AS last_visit,
       SUM(CASE WHEN local_date >= ? - INTERVAL 180 DAY THEN 1 ELSE 0 END) AS visits_180,
       SUM(CASE WHEN local_date >= ? - INTERVAL 180 DAY THEN revenue ELSE 0 END) AS monetary_180,
       SUM(CASE WHEN local_date >= ? - INTERVAL 90 DAY THEN 1 ELSE 0 END) AS visits_90,
       SUM(promoted) AS promoted_visits_lifetime,
       SUM(CASE WHEN local_date >= ? - INTERVAL 180 DAY THEN promoted ELSE 0 END) AS promoted_visits_180
FROM visit_facts GROUP BY customer_code;

CREATE OR REPLACE TEMP TABLE favorite_categories AS
SELECT customer_code, category_code AS favorite_category_code, category_quantity
FROM (
    SELECT e.customer_code, l.category_code, SUM(l.quantity) AS category_quantity,
           ROW_NUMBER() OVER (PARTITION BY e.customer_code
               ORDER BY SUM(l.quantity) DESC, l.category_code) AS preference_rank
    FROM eligible_orders e JOIN order_lines l ON l.order_code = e.order_code
    WHERE l.category_code IS NOT NULL
    GROUP BY e.customer_code, l.category_code
) ranked WHERE preference_rank = 1;

CREATE OR REPLACE TEMP TABLE favorite_channels AS
SELECT customer_code, channel_code AS favorite_channel_code, channel_visits
FROM (
    SELECT customer_code, channel_code, COUNT(*) AS channel_visits,
           ROW_NUMBER() OVER (PARTITION BY customer_code
               ORDER BY COUNT(*) DESC, channel_code) AS preference_rank
    FROM visit_facts WHERE channel_code IS NOT NULL
    GROUP BY customer_code, channel_code
) ranked WHERE preference_rank = 1;

CREATE OR REPLACE TEMP TABLE favorite_dayparts AS
SELECT customer_code, daypart AS favorite_daypart, daypart_visits
FROM (
    SELECT customer_code, daypart, COUNT(*) AS daypart_visits,
           ROW_NUMBER() OVER (PARTITION BY customer_code
               ORDER BY COUNT(*) DESC, daypart) AS preference_rank
    FROM (
        SELECT customer_code,
               CASE WHEN local_hour < 11 THEN 'breakfast'
                    WHEN local_hour < 15 THEN 'lunch'
                    WHEN local_hour < 18 THEN 'afternoon'
                    WHEN local_hour < 22 THEN 'dinner'
                    ELSE 'late_night' END AS daypart
        FROM visit_facts
    ) timed
    GROUP BY customer_code, daypart
) ranked WHERE preference_rank = 1;

CREATE OR REPLACE TEMP TABLE customer_features AS
SELECT c.code AS customer_code, c.joined_on, s.first_visit, s.last_visit,
       CASE WHEN s.last_visit IS NOT NULL THEN date_diff('day', s.last_visit, ?) END AS recency_days,
       COALESCE(s.lifetime_visits, 0) AS lifetime_visits,
       COALESCE(s.lifetime_monetary, 0)::DOUBLE AS lifetime_monetary,
       COALESCE(s.visits_180, 0) AS visits_180,
       COALESCE(s.monetary_180, 0)::DOUBLE AS monetary_180,
       COALESCE(s.visits_90, 0) AS visits_90,
       CASE WHEN s.lifetime_visits > 0 THEN (s.lifetime_monetary / s.lifetime_visits)::DOUBLE END AS average_order_value,
       CASE WHEN s.lifetime_visits > 0 THEN
            (s.lifetime_visits * 30.0 / GREATEST(1, date_diff('day', s.first_visit, ?)))::DOUBLE END
            AS visits_per_30_days,
       CASE WHEN s.visits_180 > 0 THEN (s.promoted_visits_180::DOUBLE / s.visits_180)
            WHEN s.lifetime_visits > 0 THEN (s.promoted_visits_lifetime::DOUBLE / s.lifetime_visits)
            END AS promotion_order_share,
       COALESCE(s.promoted_visits_lifetime, 0) AS promoted_visits_lifetime,
       CASE WHEN s.lifetime_visits >= 2 THEN TRUE ELSE FALSE END AS repeat_customer,
       fc.favorite_category_code, fc.category_quantity AS favorite_category_quantity,
       ch.favorite_channel_code, ch.channel_visits AS favorite_channel_visits,
       dp.favorite_daypart, dp.daypart_visits AS favorite_daypart_visits
FROM customers c
LEFT JOIN customer_summary s ON c.code = s.customer_code
LEFT JOIN favorite_categories fc ON c.code = fc.customer_code
LEFT JOIN favorite_channels ch ON c.code = ch.customer_code
LEFT JOIN favorite_dayparts dp ON c.code = dp.customer_code
WHERE c.joined_on < ?;
