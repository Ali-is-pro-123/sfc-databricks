-- One row per item/location/month; all behavioral predictors end before month_start.
CREATE OR REPLACE TEMP TABLE monthly_risk AS
WITH observed AS (
    SELECT restaurant_code,item_code,category_code,
           date_trunc('month',business_date)::DATE AS month_start,
           SUM(sold_quantity) AS sold_quantity,
           SUM(wasted_quantity) AS wasted_quantity,
           SUM(promoted_sold_quantity) AS promoted_sold_quantity,
           SUM(prepared_quantity) AS recorded_prepared_quantity
    FROM wastage_daily GROUP BY 1,2,3,4
), future AS (
    SELECT DISTINCT restaurant_code,item_code,category_code,
           DATE '2026-07-01' AS month_start,
           NULL::DOUBLE AS sold_quantity,NULL::DOUBLE AS wasted_quantity,
           NULL::DOUBLE AS promoted_sold_quantity,
           NULL::DOUBLE AS recorded_prepared_quantity
    FROM observed
), all_months AS (
    SELECT * FROM observed UNION ALL SELECT * FROM future
), features AS (
    SELECT *,
       COUNT(sold_quantity) OVER prior AS history_months,
       SUM(sold_quantity) OVER prior AS prior_3m_sold,
       SUM(wasted_quantity) OVER prior AS prior_3m_wasted,
       SUM(promoted_sold_quantity) OVER prior AS prior_3m_promoted_sold,
       SUM(recorded_prepared_quantity) OVER prior AS prior_3m_recorded_prepared,
       SUM(CASE WHEN wasted_quantity>0 THEN 1 ELSE 0 END) OVER prior AS prior_3m_waste_months,
       SUM(CASE WHEN wasted_quantity>=5 THEN 1 ELSE 0 END) OVER prior AS prior_3m_high_waste_months,
       LAG(sold_quantity) OVER seq AS prior_month_sold,
       LAG(wasted_quantity) OVER seq AS prior_month_wasted
    FROM all_months
    WINDOW seq AS (PARTITION BY restaurant_code,item_code ORDER BY month_start),
           prior AS (PARTITION BY restaurant_code,item_code ORDER BY month_start
                     ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING)
)
SELECT restaurant_code,item_code,category_code,month_start,
       history_months,prior_3m_sold,prior_3m_wasted,
       prior_3m_promoted_sold,prior_3m_recorded_prepared,
       prior_3m_waste_months,prior_3m_high_waste_months,prior_month_sold,prior_month_wasted,
       sin(2*pi()*month(month_start)/12) AS month_sin,
       cos(2*pi()*month(month_start)/12) AS month_cos,
       CASE WHEN wasted_quantity>=5 THEN 1 WHEN wasted_quantity<5 THEN 0 END AS waste_event
FROM features WHERE history_months=3;
