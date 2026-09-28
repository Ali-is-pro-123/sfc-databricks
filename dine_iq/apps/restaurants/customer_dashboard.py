"""Read-only customer intelligence with location-safe cohort calculations."""

from pathlib import Path

import duckdb
from django.conf import settings

from .dashboard_data import DashboardUnavailable, _read_report


SEGMENTS = ("New Customers", "At-Risk Customers", "Promotion-Driven Customers",
            "High-Value Loyal Customers", "Frequent Customers", "Occasional Customers",
            "No Purchase Yet")
TIERS = ("Top RFM", "High RFM", "Medium RFM", "Low RFM", "No Purchase History")
AS_OF = "2026-07-01"


def _view(con, name, path):
    available = (path / "_SUCCESS").is_file() if path.is_dir() else path.is_file()
    if not available:
        raise DashboardUnavailable(f"Customer source is missing: {name}")
    pattern = f"{path.as_posix()}/**/*.parquet" if path.is_dir() else path.as_posix()
    con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{pattern.replace(chr(39), chr(39) * 2)}')")


def build_customer_dashboard(allowed_codes, root=None):
    """Never apply network-wide customer labels to a subset of locations."""
    codes = sorted(set(allowed_codes))
    if not codes:
        return {"empty": True}
    root = Path(root or settings.PROJECT_ROOT)
    reports = {
        "coverage": _read_report(root / "processed_data/step06-full/integration_report.json",
                                 "status", "passed"),
        "segments": _read_report(root / "processed_data/step15-full/segmentation_report.json",
                                 "as_of_exclusive", AS_OF),
        "rfm": _read_report(root / "processed_data/step16-full/rfm_report.json",
                            "as_of_exclusive", AS_OF),
        "risk": _read_report(root / "processed_data/step36-full/churn_risk_report.json",
                             "as_of_exclusive", AS_OF),
    }
    con = duckdb.connect()
    con.execute("SET threads=4")
    try:
        _view(con, "coverage", root / "parquet_data/step06-full/order_coverage")
        if con.execute("SELECT COUNT(*) FROM coverage").fetchone()[0] != reports["coverage"]["outputs"]["order_coverage"]["rows"]:
            raise DashboardUnavailable("Order coverage count differs")
        source_codes = {row[0] for row in con.execute("SELECT DISTINCT restaurant_code FROM coverage").fetchall()}
        scoped_codes = sorted(source_codes.intersection(codes))
        if not scoped_codes:
            return {"empty": True}
        full_network = set(codes) == source_codes
        con.execute("CREATE TEMP TABLE allowed_locations (restaurant_code VARCHAR PRIMARY KEY)")
        con.executemany("INSERT INTO allowed_locations VALUES (?)", [(code,) for code in scoped_codes])
        con.execute("""CREATE TEMP TABLE visits AS
            SELECT c.order_code,c.customer_code,c.restaurant_code,c.accepted_basket_revenue AS revenue,
              CAST(timezone(c.timezone,timezone('UTC',c.ordered_at)) AS DATE) AS local_date
            FROM coverage c JOIN allowed_locations a USING (restaurant_code)
            WHERE c.status='completed' AND c.customer_code IS NOT NULL
              AND c.accepted_line_count>0 AND c.known_rejected_lines=0
              AND CAST(timezone(c.timezone,timezone('UTC',c.ordered_at)) AS DATE)<DATE '2026-07-01'""")
        visits, revenue = con.execute("SELECT COUNT(*),SUM(revenue) FROM visits").fetchone()
        if full_network and (visits != reports["segments"]["eligible_visits"] or
                             abs(float(revenue) - float(reports["segments"]["eligible_revenue"])) > .01):
            raise DashboardUnavailable("Full-network eligible visits do not reconcile")
        trends = [dict(month=row[0].strftime("%b %Y"), customers=row[1], visits=row[2], revenue=row[3])
                  for row in con.execute("""SELECT date_trunc('month',local_date)::DATE,
                      COUNT(DISTINCT customer_code),COUNT(*),SUM(revenue)
                      FROM visits WHERE local_date>=DATE '2026-01-01'
                      GROUP BY 1 ORDER BY 1""").fetchall()]
        if full_network:
            for name, path in (
                ("segments", root / "parquet_data/step15-full/customer_segments.parquet"),
                ("rfm", root / "parquet_data/step16-full/rfm_scores.parquet"),
                ("risk", root / "parquet_data/step36-full/churn_risk.parquet")):
                _view(con, name, path)
            if (con.execute("SELECT COUNT(*) FROM segments").fetchone()[0] != reports["segments"]["included_customers"] or
                con.execute("SELECT COUNT(*) FROM rfm").fetchone()[0] != reports["rfm"]["population"] or
                con.execute("SELECT COUNT(*) FROM risk").fetchone()[0] != reports["risk"]["checks"]["customers"]):
                raise DashboardUnavailable("Customer snapshot population differs")
            segment_counts = dict(con.execute("SELECT segment,COUNT(*) FROM segments GROUP BY 1").fetchall())
            tier_counts = dict(con.execute("SELECT rfm_tier,COUNT(*) FROM rfm GROUP BY 1").fetchall())
            risk_counts = dict(con.execute("SELECT churn_review_band,COUNT(*) FROM risk GROUP BY 1").fetchall())
            if (segment_counts != reports["segments"]["segment_counts"] or
                tier_counts != reports["rfm"]["tier_counts"] or
                risk_counts != reports["risk"]["checks"]["review_band_counts"]):
                raise DashboardUnavailable("Customer classifications do not reconcile")
            population = reports["segments"]["included_customers"]
        else:
            _view(con, "lines", root / "parquet_data/step06-full/order_lines")
            if con.execute("SELECT COUNT(*) FROM lines").fetchone()[0] != reports["coverage"]["outputs"]["order_lines"]["rows"]:
                raise DashboardUnavailable("Order lines count differs")
            con.execute("""CREATE TEMP TABLE scoped_customers AS
              WITH promoted AS (
                SELECT v.order_code,MAX(CASE WHEN l.order_promotion_code IS NOT NULL
                  OR l.line_promotion_code IS NOT NULL OR l.discount_amount>0 THEN 1 ELSE 0 END) AS used_promotion
                FROM visits v JOIN lines l USING(order_code) GROUP BY 1
              ), summary AS (
                SELECT v.customer_code,MIN(local_date) AS first_visit,MAX(local_date) AS last_visit,
                  COUNT(*) AS lifetime_visits,
                  SUM(CASE WHEN local_date>=DATE '2026-01-02' THEN 1 ELSE 0 END) AS visits_180,
                  SUM(CASE WHEN local_date>=DATE '2026-01-02' THEN revenue ELSE 0 END) AS monetary_180,
                  SUM(CASE WHEN local_date>=DATE '2026-04-02' THEN 1 ELSE 0 END) AS visits_90,
                  SUM(CASE WHEN local_date>=DATE '2026-01-02' THEN p.used_promotion ELSE 0 END) AS promoted_180,
                  SUM(p.used_promotion) AS promoted_lifetime
                FROM visits v JOIN promoted p USING(order_code) GROUP BY 1
              ), threshold AS (
                SELECT quantile_cont(monetary_180,0.25) AS p25,
                  quantile_cont(monetary_180,0.50) AS p50,
                  quantile_cont(monetary_180,0.75) AS p75,
                  quantile_cont(monetary_180,0.90) AS p90
                FROM summary WHERE monetary_180>0
              ), scored AS (
                SELECT s.*,
                  CASE WHEN first_visit>=DATE '2026-05-02' THEN 'New Customers'
                    WHEN lifetime_visits>=2 AND visits_90=0 THEN 'At-Risk Customers'
                    WHEN visits_180>=3 AND
                      (CASE WHEN visits_180>0 THEN promoted_180::DOUBLE/visits_180
                        ELSE promoted_lifetime::DOUBLE/lifetime_visits END)>=0.5
                      THEN 'Promotion-Driven Customers'
                    WHEN visits_180>=6 AND monetary_180>=t.p75 THEN 'High-Value Loyal Customers'
                    WHEN visits_180>=6 THEN 'Frequent Customers'
                    ELSE 'Occasional Customers' END AS segment,
                  CASE WHEN date_diff('day',last_visit,DATE '2026-07-01')<=30 THEN 5
                    WHEN date_diff('day',last_visit,DATE '2026-07-01')<=60 THEN 4
                    WHEN date_diff('day',last_visit,DATE '2026-07-01')<=90 THEN 3
                    WHEN date_diff('day',last_visit,DATE '2026-07-01')<=180 THEN 2 ELSE 1 END AS r_score,
                  CASE WHEN visits_180>=6 THEN 5 WHEN visits_180>=4 THEN 4
                    WHEN visits_180>=2 THEN 3 WHEN visits_180>=1 THEN 2 ELSE 1 END AS f_score,
                  CASE WHEN monetary_180>=t.p90 THEN 5 WHEN monetary_180>=t.p75 THEN 4
                    WHEN monetary_180>=t.p50 THEN 3 WHEN monetary_180>=t.p25 THEN 2 ELSE 1 END AS m_score
                FROM summary s CROSS JOIN threshold t
              ) SELECT *, CASE WHEN r_score>=4 AND f_score>=4 AND m_score>=4 THEN 'Top RFM'
                WHEN r_score+f_score+m_score>=12 THEN 'High RFM'
                WHEN r_score+f_score+m_score>=8 THEN 'Medium RFM'
                ELSE 'Low RFM' END AS rfm_tier FROM scored""")
            segment_counts = dict(con.execute("SELECT segment,COUNT(*) FROM scoped_customers GROUP BY 1").fetchall())
            tier_counts = dict(con.execute("SELECT rfm_tier,COUNT(*) FROM scoped_customers GROUP BY 1").fetchall())
            population = con.execute("SELECT COUNT(*) FROM scoped_customers").fetchone()[0]
            risk_counts = None
        return {"empty": False, "full_network": full_network, "location_count": len(scoped_codes),
                "population": population, "eligible_visits": visits,
                "segment_rows": [(name, segment_counts.get(name, 0)) for name in SEGMENTS if full_network or name != "No Purchase Yet"],
                "tier_rows": [(name, tier_counts.get(name, 0)) for name in TIERS if full_network or name != "No Purchase History"],
                "high_value": segment_counts.get("High-Value Loyal Customers", 0),
                "at_risk": segment_counts.get("At-Risk Customers", 0),
                "promotion_driven": segment_counts.get("Promotion-Driven Customers", 0),
                "high_review": risk_counts.get("High Review Priority", 0) if risk_counts else None,
                "trends": trends}
    finally:
        con.close()
