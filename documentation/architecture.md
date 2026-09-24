# DineIQ Architecture

## Runtime boundary

The development environment deliberately separates lightweight web work from
the Linux-oriented data infrastructure:

```text
Windows host
  Django 5.2 + uv
  Django templates + Tailwind CDN
  Browser dashboards
        |
        +-- PostgreSQL container
        +-- Redis container
        +-- Spark master container
                |
                +-- Spark worker container
```

Django remains easy to debug on Windows. PostgreSQL, Redis, Java, Apache Spark,
PySpark, Spark SQL, and Spark MLlib run in reproducible Linux containers.
The Spark master and worker use `config/spark.Dockerfile`, extending the pinned
Spark image with Python NumPy and SciPy packages required by MLlib.

## Analytical data flow

```text
Synthetic restaurant data
  -> raw CSV and JSON datasets
  -> Spark ingestion and schema validation
  -> data quality, cleaning, and quarantine
  -> integrated and partitioned Parquet datasets
  -> feature engineering
  -> Spark MLlib pipeline + independent Python pipeline
  -> prediction comparison and disagreement analysis
  -> restaurant intelligence and evidence-based recommendations
  -> Django dashboards, filters, reports, and exports
```

## Repository layout

| Path | Responsibility |
| --- | --- |
| `dine_iq/` | Django project and modular business applications |
| `templates/` | Shared Django templates using Tailwind CDN |
| `static/` | Project JavaScript, images, and small static assets |
| `data_generator/` | Reproducible synthetic restaurant dataset generation |
| `raw_data/` | Generated source data; ignored by Git |
| `processed_data/` | Cleaned and integrated data; ignored by Git |
| `parquet_data/` | Partitioned Big Data outputs; ignored by Git |
| `spark_jobs/` | Spark ingestion, cleaning, feature, and ML jobs |
| `spark_sql/` | Versioned Spark SQL queries |
| `python_pipeline/` | Independent Pandas and scikit-learn pipeline |
| `notebooks/` | Exploration only; production logic stays in modules |
| `models/` | Versioned generated model artifacts; ignored by Git |
| `database/` | Database notes, seed helpers, and exported schema evidence |
| `tests/` | Unit, integration, Spark, ML, security, and boundary tests |
| `sample_data/` | Small Git-safe samples for development and evaluation |
| `reports/` | Report templates and generated analytical reports |
| `documentation/` | Architecture, data dictionary, diagrams, and project report |
| `screenshots/` | Final verified application screenshots |
| `config/` | Non-secret analytical and model configuration |

## Design rules

1. Spark and Python models must process equivalent source records independently.
2. Time-dependent models must use chronological validation splits.
3. Every recommendation must retain its evidence and model version.
4. Long Spark and training jobs will run asynchronously; dashboards consume
   persisted results instead of blocking HTTP requests.
5. Secrets belong in `.env`; `.env.example` contains development-safe examples.
6. Generated large data and binary model artifacts are never committed directly.
