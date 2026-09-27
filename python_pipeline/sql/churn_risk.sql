-- Use the same known-complete, identified completed baskets as Step 15.
CREATE TEMP VIEW eligible_orders AS
SELECT order_code, customer_code, accepted_line_count, accepted_basket_revenue,
       CAST(timezone(timezone, timezone('UTC', ordered_at)) AS DATE) AS local_date
FROM order_coverage
WHERE status = 'completed' AND customer_code IS NOT NULL
  AND accepted_line_count > 0 AND known_rejected_lines = 0
  AND CAST(timezone(timezone, timezone('UTC', ordered_at)) AS DATE) >=
      (SELECT prior_start FROM analysis_parameters)
  AND CAST(timezone(timezone, timezone('UTC', ordered_at)) AS DATE) <
      (SELECT as_of FROM analysis_parameters);

CREATE TEMP VIEW period_visits AS
SELECT customer_code,
       COUNT(*) FILTER (WHERE local_date < (SELECT recent_start FROM analysis_parameters)) AS prior_90_visits,
       COUNT(*) FILTER (WHERE local_date >= (SELECT recent_start FROM analysis_parameters)) AS recent_90_visits,
       COALESCE(SUM(accepted_basket_revenue) FILTER
           (WHERE local_date < (SELECT recent_start FROM analysis_parameters)), 0) AS prior_90_spend,
       COALESCE(SUM(accepted_basket_revenue) FILTER
           (WHERE local_date >= (SELECT recent_start FROM analysis_parameters)), 0) AS recent_90_spend
FROM eligible_orders GROUP BY 1;

CREATE TEMP VIEW period_categories AS
SELECT e.customer_code,
       COUNT(DISTINCT l.category_code) FILTER
           (WHERE e.local_date < (SELECT recent_start FROM analysis_parameters)) AS prior_90_categories,
       COUNT(DISTINCT l.category_code) FILTER
           (WHERE e.local_date >= (SELECT recent_start FROM analysis_parameters)) AS recent_90_categories
FROM eligible_orders e JOIN order_lines l USING (order_code)
GROUP BY 1;

CREATE TEMP TABLE churn_risk AS
WITH measures AS (
    SELECT s.customer_code, s.joined_on, s.first_visit, s.last_visit,
           s.recency_days, s.lifetime_visits, s.lifetime_monetary,
           s.segment AS behavioral_segment, r.rfm_tier, r.rfm_code,
           COALESCE(v.prior_90_visits, 0) AS prior_90_visits,
           COALESCE(v.recent_90_visits, 0) AS recent_90_visits,
           COALESCE(v.prior_90_spend, 0) AS prior_90_spend,
           COALESCE(v.recent_90_spend, 0) AS recent_90_spend,
           COALESCE(c.prior_90_categories, 0) AS prior_90_categories,
           COALESCE(c.recent_90_categories, 0) AS recent_90_categories,
           s.lifetime_visits >= 2 AND s.first_visit <
               (SELECT prior_start FROM analysis_parameters) AS sufficient_history
    FROM customer_segments s JOIN rfm_scores r USING (customer_code)
    LEFT JOIN period_visits v USING (customer_code)
    LEFT JOIN period_categories c USING (customer_code)
), signals AS (
    SELECT *,
           sufficient_history AND recency_days > 90 AS stale_recency,
           sufficient_history AND prior_90_visits >= 2 AND
               recent_90_visits * 2 <= prior_90_visits AS declining_frequency,
           sufficient_history AND prior_90_spend > 0 AND
               recent_90_spend * 2 <= prior_90_spend AS declining_monetary,
           sufficient_history AND prior_90_categories >= 2 AND
               recent_90_categories < prior_90_categories AS declining_category_diversity
    FROM measures
), scored AS (
    SELECT *,
           stale_recency::INTEGER + declining_frequency::INTEGER +
           declining_monetary::INTEGER + declining_category_diversity::INTEGER AS decline_signal_count,
           recent_90_visits::DOUBLE / NULLIF(prior_90_visits, 0) AS visit_frequency_ratio,
           recent_90_spend::DOUBLE / NULLIF(prior_90_spend, 0) AS monetary_ratio
    FROM signals
)
SELECT *,
       CASE WHEN lifetime_visits = 0 THEN 'No Purchase History'
            WHEN NOT sufficient_history THEN 'Insufficient History'
            WHEN stale_recency OR (recency_days > 45 AND declining_frequency AND declining_monetary)
                 THEN 'High Review Priority'
            WHEN decline_signal_count >= 2 THEN 'Watch'
            ELSE 'No Current Decline Signal' END AS churn_review_band,
       (SELECT prior_start FROM analysis_parameters) AS prior_start,
       (SELECT recent_start FROM analysis_parameters) AS recent_start,
       (SELECT as_of FROM analysis_parameters) AS as_of_exclusive
FROM scored;
