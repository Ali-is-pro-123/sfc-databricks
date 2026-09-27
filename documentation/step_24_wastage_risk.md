# Step 24: Wastage risk prediction

## Plan and implementation

The SRS calls for predicting high-wastage items or periods. This pipeline
predicts whether an item/location will record **at least five accepted
wasted portions in the next calendar month**. It uses only the prior three
months of sold demand, wastage, promotion-attributed sales, recorded
preparation, and calendar/location/category context. The target month's
sales, waste, preparation, inventory and promotion outcomes never enter
its features. This fixed five-portion threshold is an exploratory business
definition, not an SRS-mandated cutoff.

Chronological training targets end December 2025; January–February 2026
select Extra Trees or the comparable prior-three-month high-waste frequency
baseline by validation average precision. March–June 2026 are held out.
The selected model is refitted on all observed targets only for July 2026
inference. Held-out scores are from the earlier fit, not the refitted one.
The report includes average precision, ROC-AUC, Brier loss, prevalence,
top-decile precision and recall, with month-level held-out metrics.

## Run

```powershell
uv run python -m unittest python_pipeline.test_wastage_risk -v
uv run python -m python_pipeline.wastage_risk `
  --daily parquet_data/step23-accepted-full/wastage_daily.parquet `
  --wastage-report processed_data/step23-accepted-full/wastage_report.json `
  --output parquet_data/step24-verified-full `
  --reports processed_data/step24-verified-full `
  --models models/step24-verified-full
```

Use new output folders for reruns. The authoritative report is
`processed_data/step24-verified-full/wastage_risk_report.json` and July scores
are in `parquet_data/step24-verified-full/next_month_wastage_risk.parquet`.
Earlier `step24-full`, `step24-highwaste-full`, and `step24-final-full` were diagnostic runs and
must not be used downstream.

## Full-data finding and limitation

Held-out prevalence is 22.07% among 17,184 item/location/month rows.
The selected model's average precision is 0.265, ROC-AUC 0.547 and top-decile
precision 29.55%. This is only modest discrimination; the model must **not**
drive automated preparation or inventory decisions. July scores cover
4,296 pairs; 24 recently introduced or otherwise short-history pairs are
unscored. The data is synthetic, and Step 23's accepted inventory gap remains.
