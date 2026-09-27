CREATE TEMP VIEW class_spread AS
SELECT item_code, COUNT(DISTINCT menu_class) AS distinct_location_classes,
       COUNT(*) AS locations_observed
FROM local_classes GROUP BY 1;

CREATE TEMP TABLE location_menu_items AS
SELECT l.restaurant_code, l.restaurant_name, l.category_code, l.category_name,
       l.item_code, l.item_name, l.menu_class AS location_menu_class,
       g.menu_class AS item_wide_menu_class,
       l.menu_class <> g.menu_class AS differs_from_item_wide,
       s.distinct_location_classes > 1 AS varies_across_locations,
       s.distinct_location_classes, s.locations_observed,
       l.classification_reason, l.provisional_evidence,
       l.quantity_sold, l.order_frequency, l.revenue, l.cost, l.contribution,
       l.profit_percentage AS direct_margin_percentage,
       l.demand_score, l.profitability_score, l.rating_count, l.average_rating,
       l.eligible_customers, l.repeat_purchase_rate, l.wasted_quantity,
       l.accounted_wastage_percentage, l.promotion_dependency,
       l.high_recorded_waste, l.poor_rating, l.high_promotion_reliance,
       l.declining_sales, l.feature_as_of AS as_of_exclusive, l.window_days
FROM local_classes l
JOIN global_classes g USING (item_code)
JOIN class_spread s USING (item_code);

CREATE TEMP TABLE location_menu_summary AS
SELECT m.restaurant_code, ANY_VALUE(m.restaurant_name) AS restaurant_name,
       ANY_VALUE(i.city) AS city,
       COUNT(*) AS menu_items,
       COUNT(*) FILTER (WHERE m.location_menu_class = 'Profit Driver') AS profit_drivers,
       COUNT(*) FILTER (WHERE m.location_menu_class = 'Volume Driver') AS volume_drivers,
       COUNT(*) FILTER (WHERE m.location_menu_class = 'Hidden Opportunity') AS hidden_opportunities,
       COUNT(*) FILTER (WHERE m.location_menu_class = 'Low Performer') AS low_performers,
       COUNT(*) FILTER (WHERE m.provisional_evidence) AS provisional_items,
       COUNT(*) FILTER (WHERE m.differs_from_item_wide) AS differing_from_item_wide,
       COUNT(*) FILTER (WHERE m.varies_across_locations) AS variable_across_locations,
       SUM(m.quantity_sold) AS quantity_sold,
       SUM(m.revenue) AS revenue, SUM(m.cost) AS cost,
       SUM(m.contribution) AS direct_contribution,
       SUM(m.revenue) FILTER (WHERE m.location_menu_class = 'Profit Driver') AS profit_driver_revenue,
       SUM(m.revenue) FILTER (WHERE m.location_menu_class = 'Volume Driver') AS volume_driver_revenue,
       SUM(m.revenue) FILTER (WHERE m.location_menu_class = 'Hidden Opportunity') AS hidden_opportunity_revenue,
       SUM(m.revenue) FILTER (WHERE m.location_menu_class = 'Low Performer') AS low_performer_revenue,
       ANY_VALUE(i.as_of_exclusive) AS as_of_exclusive
FROM location_menu_items m JOIN location_intelligence i USING (restaurant_code)
GROUP BY 1;

CREATE TEMP TABLE cross_location_item_variation AS
SELECT item_code, ANY_VALUE(item_name) AS item_name,
       ANY_VALUE(category_code) AS category_code,
       ANY_VALUE(item_wide_menu_class) AS item_wide_menu_class,
       COUNT(*) AS locations_observed,
       COUNT(DISTINCT location_menu_class) AS distinct_location_classes,
       COUNT(*) FILTER (WHERE location_menu_class = 'Profit Driver') AS profit_driver_locations,
       COUNT(*) FILTER (WHERE location_menu_class = 'Volume Driver') AS volume_driver_locations,
       COUNT(*) FILTER (WHERE location_menu_class = 'Hidden Opportunity') AS hidden_opportunity_locations,
       COUNT(*) FILTER (WHERE location_menu_class = 'Low Performer') AS low_performer_locations,
       COUNT(*) FILTER (WHERE provisional_evidence) AS provisional_locations,
       SUM(revenue) AS revenue, SUM(contribution) AS direct_contribution
FROM location_menu_items GROUP BY 1;
