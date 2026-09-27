-- Calendar weeks without ratings remain zero-count observations.
CREATE OR REPLACE TEMP TABLE weekly_ratings AS
WITH bounds AS (
    SELECT date_trunc('week',MIN(rating_local_date))::DATE AS first_week,
           date_trunc('week',MAX(rating_local_date))::DATE AS last_week
    FROM rating_events
), weeks AS (
    SELECT week_start::DATE AS week_start FROM bounds,
         generate_series(first_week,last_week,INTERVAL 7 DAY) AS t(week_start)
), populations AS (
    SELECT 'item' AS grain,item_code AS entity_code FROM rating_events GROUP BY item_code
    UNION ALL
    SELECT 'location',restaurant_code FROM rating_events GROUP BY restaurant_code
), observed AS (
    SELECT 'item' AS grain,item_code AS entity_code,
           date_trunc('week',rating_local_date)::DATE AS week_start,
           COUNT(*) AS rating_count,SUM(rating_score)::DOUBLE AS score_sum,
           SUM(rating_score*rating_score)::DOUBLE AS score_square_sum,
           MAX(score_count) AS identical_score_count
    FROM (SELECT *,COUNT(*) OVER (PARTITION BY item_code,
          date_trunc('week',rating_local_date),rating_score) AS score_count
          FROM rating_events) x GROUP BY 1,2,3
    UNION ALL
    SELECT 'location',restaurant_code,date_trunc('week',rating_local_date)::DATE,
           COUNT(*),SUM(rating_score)::DOUBLE,
           SUM(rating_score*rating_score)::DOUBLE,MAX(score_count)
    FROM (SELECT *,COUNT(*) OVER (PARTITION BY restaurant_code,
          date_trunc('week',rating_local_date),rating_score) AS score_count
          FROM rating_events) x GROUP BY 1,2,3
)
SELECT p.grain,p.entity_code,w.week_start,
       COALESCE(o.rating_count,0) AS rating_count,
       COALESCE(o.score_sum,0) AS score_sum,
       COALESCE(o.score_square_sum,0) AS score_square_sum,
       COALESCE(o.identical_score_count,0) AS identical_score_count
FROM populations p CROSS JOIN weeks w
LEFT JOIN observed o ON o.grain=p.grain AND o.entity_code=p.entity_code
                    AND o.week_start=w.week_start;

CREATE OR REPLACE TEMP TABLE weekly_rating_anomalies AS
WITH history AS (
    SELECT *,
       COUNT(*) OVER prior AS prior_weeks,
       SUM(rating_count) OVER prior AS prior_8w_rating_count,
       SUM(score_sum) OVER prior AS prior_8w_score_sum,
       AVG(rating_count) OVER prior AS prior_weekly_count_mean,
       STDDEV_POP(rating_count) OVER prior AS prior_weekly_count_stddev
    FROM weekly_ratings
    WINDOW prior AS (PARTITION BY grain,entity_code ORDER BY week_start
                     ROWS BETWEEN 8 PRECEDING AND 1 PRECEDING)
)
SELECT grain,entity_code,week_start,rating_count,
       CASE WHEN rating_count>0 THEN score_sum/rating_count END AS mean_rating,
       identical_score_count,
       CASE WHEN rating_count>0 THEN identical_score_count::DOUBLE/rating_count END
           AS identical_score_share,
       prior_weeks,prior_8w_rating_count,
       CASE WHEN prior_8w_rating_count>0 THEN prior_8w_score_sum/prior_8w_rating_count END
           AS prior_8w_mean_rating,
       prior_weekly_count_mean,prior_weekly_count_stddev,
       CASE WHEN prior_weeks=8 AND prior_8w_rating_count>=30 AND rating_count>=8
                 AND score_sum/rating_count-
                     prior_8w_score_sum/prior_8w_rating_count>=1.0
            THEN TRUE ELSE FALSE END AS sudden_rating_spike,
       CASE WHEN prior_weeks=8 AND prior_8w_rating_count>=30 AND rating_count>=8
                 AND prior_8w_score_sum/prior_8w_rating_count-
                     score_sum/rating_count>=1.0
            THEN TRUE ELSE FALSE END AS sudden_rating_drop,
       CASE WHEN rating_count>=15 AND identical_score_count::DOUBLE/rating_count>=0.90
            THEN TRUE ELSE FALSE END AS excessive_identical_ratings,
       CASE WHEN prior_weeks=8 AND prior_8w_rating_count>=30 AND rating_count>=20
                 AND rating_count>=prior_weekly_count_mean*2
                 AND rating_count>=prior_weekly_count_mean+
                                   2*prior_weekly_count_stddev
            THEN TRUE ELSE FALSE END AS high_short_period_volume
FROM history;

-- Purchase-month cohorts provide a like-for-like rating/sales denominator.
CREATE OR REPLACE TEMP TABLE monthly_item_rating_sales AS
WITH monthly AS (
    SELECT item_code,period AS purchase_month,
           SUM(sold_lines) AS sold_lines,SUM(rating_count) AS rating_count,
           SUM(sold_quantity) AS sold_quantity
    FROM rating_metrics WHERE grain='item_location_month_promotion'
    GROUP BY 1,2
), history AS (
    SELECT *,
           COUNT(*) OVER prior AS prior_months,
           SUM(sold_lines) OVER prior AS prior_3m_sold_lines,
           SUM(rating_count) OVER prior AS prior_3m_rating_count
    FROM monthly
    WINDOW prior AS (PARTITION BY item_code ORDER BY purchase_month
                     ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING)
)
SELECT *,rating_count::DOUBLE/sold_lines AS rating_coverage,
       CASE WHEN prior_3m_sold_lines>0 THEN
           prior_3m_rating_count::DOUBLE/prior_3m_sold_lines END AS prior_3m_rating_coverage,
       CASE WHEN prior_months=3 AND prior_3m_rating_count>=15
                 AND rating_count>=10 AND sold_lines>=20
                 AND rating_count::DOUBLE/sold_lines>=0.35
                 AND rating_count::DOUBLE/sold_lines>=
                     2.0*prior_3m_rating_count/prior_3m_sold_lines
            THEN TRUE ELSE FALSE END AS rating_coverage_vs_sales_spike,
       CASE WHEN prior_months=3 AND prior_3m_rating_count>=15
                 AND rating_count>=prior_3m_rating_count/3.0*1.5
                 AND sold_lines<=prior_3m_sold_lines/3.0*0.75
            THEN TRUE ELSE FALSE END AS ratings_up_sales_down
FROM history;
