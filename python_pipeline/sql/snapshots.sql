-- All predictors end before cutoff; label begins at cutoff.
CREATE OR REPLACE TEMP TABLE supervised_snapshots AS
WITH monthly AS (
    SELECT k.restaurant_code, k.item_code, k.category_code,
           k.first_sale_date, c.cutoff,
           SUM(CASE WHEN d.local_date >= c.cutoff - INTERVAL 30 DAY
                     AND d.local_date < c.cutoff THEN d.sold_quantity ELSE 0 END) AS quantity_last_30,
           SUM(CASE WHEN d.local_date >= c.cutoff - INTERVAL 60 DAY
                     AND d.local_date < c.cutoff - INTERVAL 30 DAY
                    THEN d.sold_quantity ELSE 0 END) AS quantity_previous_30,
           SUM(CASE WHEN d.local_date >= c.cutoff - INTERVAL 90 DAY
                     AND d.local_date < c.cutoff THEN d.sold_quantity ELSE 0 END) AS quantity_last_90,
           SUM(CASE WHEN d.local_date >= c.cutoff - INTERVAL 30 DAY
                     AND d.local_date < c.cutoff THEN d.order_count ELSE 0 END) AS orders_last_30,
           SUM(CASE WHEN d.local_date >= c.cutoff - INTERVAL 30 DAY
                     AND d.local_date < c.cutoff THEN d.revenue ELSE 0 END) AS revenue_last_30,
           SUM(CASE WHEN d.local_date >= c.cutoff - INTERVAL 90 DAY
                     AND d.local_date < c.cutoff THEN d.revenue - d.cost ELSE 0 END) AS contribution_last_90,
           SUM(CASE WHEN d.local_date >= c.cutoff - INTERVAL 90 DAY
                     AND d.local_date < c.cutoff THEN d.wasted_quantity ELSE 0 END) AS waste_last_90,
           SUM(CASE WHEN d.local_date >= c.cutoff - INTERVAL 90 DAY
                     AND d.local_date < c.cutoff THEN d.rating_count ELSE 0 END) AS rating_count_last_90,
           SUM(CASE WHEN d.local_date >= c.cutoff - INTERVAL 90 DAY
                     AND d.local_date < c.cutoff THEN d.rating_sum ELSE 0 END) AS rating_sum_last_90,
           COUNT(DISTINCT CASE WHEN d.local_date >= c.cutoff - INTERVAL 90 DAY
                                AND d.local_date < c.cutoff AND d.sold_quantity > 0
                               THEN d.local_date END) AS sales_days_last_90,
           SUM(CASE WHEN d.local_date >= c.cutoff
                     AND d.local_date < c.cutoff + INTERVAL 1 MONTH
                    THEN d.sold_quantity ELSE 0 END) AS label
    FROM first_sales k
    CROSS JOIN cutoffs c
    LEFT JOIN daily d ON d.restaurant_code = k.restaurant_code
                     AND d.item_code = k.item_code
                     AND d.local_date >= c.cutoff - INTERVAL 90 DAY
                     AND d.local_date < c.cutoff + INTERVAL 1 MONTH
    WHERE k.first_sale_date < c.cutoff
    GROUP BY k.restaurant_code, k.item_code, k.category_code,
             k.first_sale_date, c.cutoff
)
SELECT restaurant_code, item_code, category_code, first_sale_date, cutoff,
       quantity_last_30::DOUBLE AS quantity_last_30,
       quantity_previous_30::DOUBLE AS quantity_previous_30,
       quantity_last_90::DOUBLE AS quantity_last_90,
       orders_last_30::DOUBLE AS orders_last_30,
       revenue_last_30::DOUBLE AS revenue_last_30,
       contribution_last_90::DOUBLE AS contribution_last_90,
       waste_last_90::DOUBLE AS waste_last_90,
       CASE WHEN rating_count_last_90 > 0
            THEN rating_sum_last_90::DOUBLE / rating_count_last_90 ELSE 0.0 END
            AS rating_mean_last_90,
       CASE WHEN rating_count_last_90 > 0 THEN 1.0 ELSE 0.0 END
            AS rating_observed_last_90,
       sales_days_last_90::DOUBLE AS sales_days_last_90,
       date_diff('day', first_sale_date, cutoff)::DOUBLE AS days_since_first_sale,
       sin(2 * pi() * month(cutoff) / 12)::DOUBLE AS cutoff_month_sin,
       cos(2 * pi() * month(cutoff) / 12)::DOUBLE AS cutoff_month_cos,
       date_diff('day', cutoff, cutoff + INTERVAL 1 MONTH) AS target_month_days,
       (quantity_last_30 * date_diff('day', cutoff, cutoff + INTERVAL 1 MONTH) / 30.0)::DOUBLE AS baseline,
       label::DOUBLE AS label,
       CASE WHEN cutoff < ? THEN 'train'
            WHEN cutoff < ? THEN 'validation' ELSE 'test' END AS split
FROM monthly;
