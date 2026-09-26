# Step 23: Wastage analysis

## Plan and implementation

The SRS asks for wastage by item, category, location, day, time period,
demand, inventory consumption, promotion and preparation quantity. Accepted
Step 5 clean sales, wastage and inventory are separately aggregated at
restaurant/item/business-date grain, then joined. Sales and wastage timestamps
are converted to each restaurant's local date, matching the inventory ledger
date. This avoids multiplication when a day has several orders or waste
events. The daily Parquet includes sold demand, promotion-attributed sold
quantity, preparation and waste from available waste logs, cost, and inventory
consumption. Separate additive summaries cover item, category, location, day,
month, item/location, category/location/month and promotion-day groups.

Promotion-day means at least one completed promoted sale on the same
item/location/day. It is an association, not an attribution of waste to a
campaign or an estimate of promotional lift. Preparation totals cover only
days with accepted wastage records, not all prepared portions; consequently
`waste_to_prepared_rate` is a recorded-event ratio, not a complete operational
wastage rate. `waste_share_of_outflow` uses accepted sold plus wasted portions.

The runner checks source counts, unique daily keys, nonnegative quantities,
source-to-daily sales and waste totals, inventory coverage, and conservation
of waste quantity/cost in every summary. Inventory-versus-accepted-sales/waste
gaps are disclosed, not silently allocated to a menu item or campaign.

## Run

```powershell
uv run python -m unittest python_pipeline.test_wastage_analysis -v
uv run python -m python_pipeline.wastage_analysis `
  --clean parquet_data/step05-full/clean `
  --quality-report processed_data/step05-full/quality_report.json `
  --output parquet_data/step23-accepted-full `
  --reports processed_data/step23-accepted-full
```

Use a new output folder for reruns. The verified full report is
`processed_data/step23-accepted-full/wastage_report.json`.

## Full-data finding and source caveat

Accepted data has 2,346,336 item/location/business-date rows, 74,244
wastage records, 200,208 wasted portions, and 1,182,659 accepted sold
portions. Accepted inventory consumption is 1,401,110 portions, which is
18,243 above accepted sold plus wasted quantity on 14,313 daily keys.
Step 5 quarantined order-item and wastage rows while retaining inventory
records, a plausible contributor to the gap. The output includes this as a
data-quality limitation; it does not present inventory as fully balanced.

Two initial diagnostic outputs (`step23-full` and `step23-business-full`)
were produced while investigating the date basis. The authoritative
accepted-data run is `step23-accepted-full`; the diagnostic outputs should
not be used for downstream work.
