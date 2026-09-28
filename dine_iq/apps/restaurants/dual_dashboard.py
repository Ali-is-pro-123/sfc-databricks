"""Read-only Spark/Python demand comparison within permitted locations."""

import hashlib
from pathlib import Path

import duckdb
from django.conf import settings

from .dashboard_data import DashboardUnavailable, _read_report


MONTHS = ("2026-03", "2026-04", "2026-05", "2026-06")
STATUSES = ("match", "mismatch")
SORTS = {
    "difference": "absolute_difference DESC,record_id",
    "spark_error": "spark_absolute_error DESC,record_id",
    "python_error": "python_absolute_error DESC,record_id",
    "record": "record_id",
}
PAGE_SIZE = 25


def build_dual_dashboard(allowed_codes, filters=None, root=None, export_all=False):
    """Recompute scoped agreement, accuracy and counts from paired records."""
    codes = sorted(set(allowed_codes))
    if not codes:
        return {"empty": True}
    root = Path(root or settings.PROJECT_ROOT)
    report = _read_report(root / "processed_data/step14-full-verified/comparison_report.json",
                          "status", "passed")
    for label, path, expected_hash in (
        ("Spark", root / "processed_data/step12-full/demand_model_report.json",
         report["lineage"]["spark_report_sha256"]),
        ("Python", root / "processed_data/step13-full/python_demand_report.json",
         report["lineage"]["python_report_sha256"]),
    ):
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
            raise DashboardUnavailable(f"{label} comparison lineage differs")
    csv_path = root / "processed_data/step14-full-verified/record_comparison.csv"
    if not csv_path.is_file():
        raise DashboardUnavailable("Paired comparison records are missing")
    filters = filters or {}
    con = duckdb.connect()
    con.execute("SET threads=4")
    try:
        safe_path = csv_path.as_posix().replace("'", "''")
        con.execute(f"CREATE VIEW comparisons AS SELECT * FROM read_csv_auto('{safe_path}',HEADER=TRUE)")
        rows, keys, locations = con.execute("""SELECT COUNT(*),COUNT(DISTINCT record_id),
            COUNT(DISTINCT restaurant_code) FROM comparisons""").fetchone()
        if rows != report["overall"]["rows"] or keys != rows:
            raise DashboardUnavailable("Paired comparison records do not reconcile")
        source_codes = {row[0] for row in con.execute("SELECT DISTINCT restaurant_code FROM comparisons").fetchall()}
        scoped_codes = sorted(source_codes.intersection(codes))
        if not scoped_codes:
            return {"empty": True}
        full_network = set(scoped_codes) == source_codes
        con.execute("CREATE TEMP TABLE allowed_locations (restaurant_code VARCHAR PRIMARY KEY)")
        con.executemany("INSERT INTO allowed_locations VALUES (?)", [(code,) for code in scoped_codes])
        con.execute("""CREATE TEMP VIEW scoped AS SELECT c.* FROM comparisons c
            JOIN allowed_locations a USING (restaurant_code)""")
        count, matched, spark_mae, python_mae, mean_difference = con.execute("""SELECT
            COUNT(*),SUM(CASE WHEN match_or_mismatch='match' THEN 1 ELSE 0 END),
            AVG(spark_absolute_error),AVG(python_absolute_error),AVG(absolute_difference)
            FROM scoped""").fetchone()
        agreement = 100 * matched / count
        if full_network and (matched != report["overall"]["matched"] or
                             abs(agreement - report["overall"]["agreement_percent"]) > 1e-7 or
                             abs(spark_mae - report["overall"]["spark_mae"]) > 1e-7 or
                             abs(python_mae - report["overall"]["python_mae"]) > 1e-7):
            raise DashboardUnavailable("Network-wide comparison summary differs")
        by_month = [{"month": month, "rows": total, "matched": agreed,
                     "agreement": 100 * agreed / total,
                     "spark_mae": spark_error, "python_mae": python_error}
                    for month, total, agreed, spark_error, python_error in con.execute("""SELECT
                        strftime(cutoff,'%Y-%m'),COUNT(*),SUM(CASE WHEN match_or_mismatch='match' THEN 1 ELSE 0 END),
                        AVG(spark_absolute_error),AVG(python_absolute_error)
                        FROM scoped GROUP BY 1 ORDER BY 1""").fetchall()]
        if full_network and any(row["rows"] != report["by_month"][row["month"]]["rows"] or
                                row["matched"] != report["by_month"][row["month"]]["matched"]
                                for row in by_month):
            raise DashboardUnavailable("Monthly comparison counts differ")
        selected_location = filters.get("location", "")
        if selected_location not in scoped_codes:
            selected_location = ""
        selected_month = filters.get("month", "")
        if selected_month not in MONTHS:
            selected_month = ""
        selected_status = filters.get("status", "")
        if selected_status not in STATUSES:
            selected_status = ""
        query = str(filters.get("q", ""))[:40].strip()
        sort = filters.get("sort", "difference")
        if sort not in SORTS:
            sort = "difference"
        try:
            requested_page = int(filters.get("page", 1))
        except (TypeError, ValueError):
            requested_page = 1
        where = []
        parameters = []
        if selected_location:
            where.append("restaurant_code = ?")
            parameters.append(selected_location)
        if selected_month:
            where.append("strftime(cutoff,'%Y-%m') = ?")
            parameters.append(selected_month)
        if selected_status:
            where.append("match_or_mismatch = ?")
            parameters.append(selected_status)
        if query:
            where.append("item_code ILIKE ?")
            parameters.append(f"%{query}%")
        condition = " WHERE " + " AND ".join(where) if where else ""
        filtered_count = con.execute(f"SELECT COUNT(*) FROM scoped{condition}", parameters).fetchone()[0]
        page_count = max(1, (filtered_count + PAGE_SIZE - 1) // PAGE_SIZE)
        page = min(max(1, requested_page), page_count)
        query_sql = f"""SELECT restaurant_code,item_code,cutoff,actual_value,
            spark_result,python_result,numerical_difference_python_minus_spark,
            absolute_difference,agreement_tolerance,match_or_mismatch,
            disagreement_code,spark_absolute_error,python_absolute_error
            FROM scoped{condition} ORDER BY {SORTS[sort]}"""
        if not export_all:
            query_sql += " LIMIT ? OFFSET ?"
            parameters.extend([PAGE_SIZE, (page - 1) * PAGE_SIZE])
        cursor = con.execute(query_sql, parameters)
        names = [column[0] for column in cursor.description]
        records = [dict(zip(names, values)) for values in cursor.fetchall()]
        return {"empty": False, "location_count": len(scoped_codes), "full_network": full_network,
                "rows": count, "matched": matched, "disagreements": count - matched,
                "agreement": agreement, "spark_mae": spark_mae, "python_mae": python_mae,
                "mean_difference": mean_difference, "by_month": by_month,
                "location_options": scoped_codes, "selected_location": selected_location,
                "selected_month": selected_month, "selected_status": selected_status,
                "query": query, "sort": sort, "filtered_count": filtered_count,
                "page": page, "page_count": page_count, "has_previous": page > 1,
                "has_next": page < page_count, "records": records,
                "spark_model": report["lineage"]["spark_selected_model"],
                "python_model": report["lineage"]["python_selected_model"]}
    finally:
        con.close()
