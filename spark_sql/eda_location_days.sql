WITH operations AS (
    SELECT restaurant_code, date,
           SUM(sales_line_count) AS accepted_sales_lines,
           SUM(sold_quantity) AS quantity_sold,
           SUM(revenue) AS revenue, SUM(cost) AS cost,
           SUM(contribution) AS contribution,
           SUM(wasted_quantity) AS wasted_quantity,
           SUM(waste_cost) AS waste_cost,
           SUM(waste_record_count) AS waste_record_count,
           SUM(CASE WHEN consumption_gap <> 0 THEN 1 ELSE 0 END) AS gap_item_days,
           SUM(CASE WHEN NOT has_inventory THEN 1 ELSE 0 END) AS missing_inventory_item_days,
           SUM(consumption_gap) AS consumption_gap
    FROM eda_daily GROUP BY restaurant_code, date
), headers AS (
    SELECT restaurant_code, date, COUNT(*) AS completed_header_count,
           SUM(CASE WHEN coverage_status = 'partial' THEN 1 ELSE 0 END) AS partial_header_count
    FROM eda_orders GROUP BY restaurant_code, date
)
SELECT o.restaurant_code, r.name AS restaurant_name, o.date,
       COALESCE(h.completed_header_count, 0) AS completed_header_count,
       COALESCE(h.partial_header_count, 0) AS partial_header_count,
       o.accepted_sales_lines, o.quantity_sold, o.revenue, o.cost, o.contribution,
       o.wasted_quantity, o.waste_cost, o.waste_record_count,
       o.gap_item_days, o.missing_inventory_item_days, o.consumption_gap
FROM operations o JOIN restaurants r ON o.restaurant_code = r.code
LEFT JOIN headers h ON o.restaurant_code = h.restaurant_code AND o.date = h.date
