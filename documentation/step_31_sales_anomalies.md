# Step 31: Sales anomaly detection

## Plan and implementation

The SRS requires sudden sales spikes/drops, abnormally high order values,
unusual discounts, unexpected demand and duplicate transactions. This
runner uses only accepted Step 5 completed orders and lines. It groups
accepted baskets once, checks line/order quantity and money conservation,
then creates four auditable outputs:

1. Dense restaurant-local location/day order series, including zero-order
   days. Each day compares with its preceding eight **same weekdays**.
   A spike needs >=1.75x the prior mean and >=2.5 standard deviations
   above it; a drop needs <=0.5x the mean and <=2 standard deviations below.
   Both require eight prior weekdays and mean >=5 orders.
2. Dense location/category/complete-week sold portions, including zero-sale
   weeks. Unexpected demand uses the preceding eight weeks, >=80 prior
   portions, and the same 1.75x/2.5-SD high or 0.5x/2-SD low rules. A last
   partial week is excluded.
3. January–June 2026 monitored orders compared with same-location orders
   before January 2026. A high value exceeds historical p99 and is at least
   twice the historical median (>=100 reference orders). An unusual
   discount exceeds the p99 rate among historical discounted orders and is
   at least 30% (>=30 discounted reference orders).
4. Exact duplicate *candidates*: distinct accepted order codes with the
   same identified customer, location, timestamp and complete accepted
   item/quantity/price/discount basket. Anonymous or merely similar orders
   are not declared duplicates.

Rules 1–2 span the observed historical calendar, while order value and
discount flags use the explicitly chosen monitoring period. Thresholds
are review rules, not SRS-prescribed significance tests. A flag is not
proof of fraud, erroneous payment, or forecast failure. Quarantined lines
can leave accepted baskets incomplete, and synthetic seasonality or
promotion changes can explain unusual values.

## Run

```powershell
uv run python -m unittest python_pipeline.test_sales_anomalies -v
uv run python -m python_pipeline.sales_anomalies `
  --clean parquet_data/step05-full/clean `
  --quality-report processed_data/step05-full/quality_report.json `
  --as-of 2026-07-01 `
  --monitor-start 2026-01-01 `
  --output parquet_data/step31-full `
  --reports processed_data/step31-full
```

## Verified full result

The accepted completed cohort has 339,667 orders and 1,010,907 lines.
The full run flags 186 location/day spikes, 171 drops, 252 unexpected-high
and 229 unexpected-low location/category weeks, 2,428 unusually high
monitored order values, and 326 unusual discounts. No exact duplicate
candidate group was found in the accepted data. The report is
`processed_data/step31-full/sales_anomalies_report.json` and the four
Parquet outputs are in `parquet_data/step31-full/`.
