-- Aggregate each event stream before joining it to the restaurant/item/day grain.
CREATE OR REPLACE TEMP TABLE sold_daily AS
SELECT o.restaurant_code, i.item_code,
       CAST(timezone(r.timezone, timezone('UTC', o.ordered_at)) AS DATE) AS business_date,
       SUM(i.quantity)::DOUBLE AS sold_quantity,
       SUM(CASE WHEN NULLIF(i.promotion_code, '') IS NOT NULL THEN i.quantity ELSE 0 END)::DOUBLE AS promoted_sold_quantity
FROM clean_order_items i JOIN clean_orders o ON i.order_code=o.code
JOIN clean_restaurants r ON r.code=o.restaurant_code
WHERE o.status='completed'
GROUP BY 1,2,3;

CREATE OR REPLACE TEMP TABLE waste_daily AS
SELECT w.restaurant_code,w.item_code,
       CAST(timezone(r.timezone, timezone('UTC', w.recorded_at)) AS DATE) AS business_date,
       COUNT(*) AS waste_records,
       SUM(w.prepared_quantity)::DOUBLE AS prepared_quantity,
       SUM(w.wasted_quantity)::DOUBLE AS wasted_quantity,
       SUM(w.wasted_quantity*w.unit_cost)::DOUBLE AS waste_cost
FROM clean_wastage w JOIN clean_restaurants r ON r.code=w.restaurant_code
GROUP BY 1,2,3;

CREATE OR REPLACE TEMP TABLE inventory_daily AS
SELECT restaurant_code,item_code,date AS business_date,
       SUM(opening_quantity)::DOUBLE AS opening_quantity,
       SUM(replenished_quantity)::DOUBLE AS replenished_quantity,
       SUM(consumed_quantity)::DOUBLE AS consumed_quantity,
       COUNT(*) AS inventory_records
FROM clean_inventory GROUP BY 1,2,3;

CREATE OR REPLACE TEMP TABLE wastage_daily AS
WITH keys AS (
    SELECT restaurant_code,item_code,business_date FROM sold_daily
    UNION SELECT restaurant_code,item_code,business_date FROM waste_daily
    UNION SELECT restaurant_code,item_code,business_date FROM inventory_daily
)
SELECT k.restaurant_code,k.item_code,m.category_code,k.business_date,
       strftime(k.business_date,'%Y-%m') AS year_month,
       isodow(k.business_date) AS weekday_number,
       COALESCE(s.sold_quantity,0) AS sold_quantity,
       COALESCE(s.promoted_sold_quantity,0) AS promoted_sold_quantity,
       CASE WHEN COALESCE(s.promoted_sold_quantity,0)>0 THEN TRUE ELSE FALSE END AS promotion_day,
       COALESCE(w.waste_records,0) AS waste_records,
       COALESCE(w.prepared_quantity,0) AS prepared_quantity,
       COALESCE(w.wasted_quantity,0) AS wasted_quantity,
       COALESCE(w.waste_cost,0) AS waste_cost,
       i.opening_quantity,i.replenished_quantity,i.consumed_quantity,
       COALESCE(i.inventory_records,0) AS inventory_records,
       CASE WHEN w.prepared_quantity>0 THEN w.wasted_quantity/w.prepared_quantity END AS waste_to_prepared_rate
FROM keys k JOIN clean_menu_items m ON m.code=k.item_code
LEFT JOIN sold_daily s USING (restaurant_code,item_code,business_date)
LEFT JOIN waste_daily w USING (restaurant_code,item_code,business_date)
LEFT JOIN inventory_daily i USING (restaurant_code,item_code,business_date);
