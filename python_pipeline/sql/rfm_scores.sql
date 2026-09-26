-- Scores are assigned from the verified point-in-time Step 15 measures.
CREATE OR REPLACE TEMP TABLE rfm_scores AS
WITH scored AS (
    SELECT s.customer_code, t.as_of_exclusive, s.joined_on,
           s.first_visit, s.last_visit, s.recency_days,
           s.visits_180::BIGINT AS frequency_180,
           s.monetary_180::DOUBLE AS monetary_180,
           s.lifetime_visits::BIGINT AS lifetime_visits,
           s.lifetime_monetary::DOUBLE AS lifetime_monetary,
           s.segment AS behavioral_segment,
           CASE WHEN s.lifetime_visits = 0 THEN 0
                WHEN s.recency_days <= 30 THEN 5
                WHEN s.recency_days <= 60 THEN 4
                WHEN s.recency_days <= 90 THEN 3
                WHEN s.recency_days <= 180 THEN 2
                ELSE 1 END AS r_score,
           CASE WHEN s.lifetime_visits = 0 THEN 0
                WHEN s.visits_180 >= 6 THEN 5
                WHEN s.visits_180 >= 4 THEN 4
                WHEN s.visits_180 >= 2 THEN 3
                WHEN s.visits_180 >= 1 THEN 2
                ELSE 1 END AS f_score,
           CASE WHEN s.lifetime_visits = 0 THEN 0
                WHEN s.monetary_180 >= t.p90 THEN 5
                WHEN s.monetary_180 >= t.p75 THEN 4
                WHEN s.monetary_180 >= t.p50 THEN 3
                WHEN s.monetary_180 >= t.p25 THEN 2
                ELSE 1 END AS m_score
    FROM customer_source s CROSS JOIN rfm_thresholds t
), combined AS (
    SELECT *, r_score + f_score + m_score AS rfm_total,
           CAST(r_score AS VARCHAR) || CAST(f_score AS VARCHAR) ||
           CAST(m_score AS VARCHAR) AS rfm_code
    FROM scored
)
SELECT *, CASE WHEN lifetime_visits = 0 THEN 'No Purchase History'
               WHEN r_score >= 4 AND f_score >= 4 AND m_score >= 4 THEN 'Top RFM'
               WHEN rfm_total >= 12 THEN 'High RFM'
               WHEN rfm_total >= 8 THEN 'Medium RFM'
               ELSE 'Low RFM' END AS rfm_tier
FROM combined;
