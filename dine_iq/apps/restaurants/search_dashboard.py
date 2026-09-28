"""Cross-dimensional, access-scoped search over verified accepted sales."""

from datetime import date
from pathlib import Path

import duckdb
from django.conf import settings

from .dashboard_data import DashboardUnavailable, _read_report
from .customer_dashboard import SEGMENTS


AS_OF = "2026-07-01"
START = date(2025, 1, 1)
END = date(2026, 6, 30)
CLASSES = ("Profit Driver", "Volume Driver", "Hidden Opportunity", "Low Performer")
PAGE_SIZE = 25


def _view(con, name, path, expected):
    marker_ok = (path / "_SUCCESS").is_file() if path.is_dir() else path.is_file()
    if not marker_ok:
        raise DashboardUnavailable(f"Search source is missing: {name}")
    pattern = f"{path.as_posix()}/**/*.parquet" if path.is_dir() else path.as_posix()
    con.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{pattern.replace(chr(39), chr(39) * 2)}')")
    if con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] != expected:
        raise DashboardUnavailable(f"Search source count differs: {name}")


def _date(value, default):
    try:
        parsed = date.fromisoformat(str(value))
        return parsed if START <= parsed <= END else default
    except (TypeError, ValueError):
        return default


def _number(value, lower, upper):
    if value in (None, ""):
        return None
    try:
        number = float(value)
        return number if lower <= number <= upper else None
    except (TypeError, ValueError):
        return None


def _scoped_segments(con):
    """Use the Step 15 precedence on this location cohort, not global labels."""
    con.execute("""CREATE TEMP TABLE visits AS SELECT order_code,customer_code,
        MIN(local_date) AS local_date,SUM(revenue) AS revenue,
        MAX(CASE WHEN order_promotion_code IS NOT NULL OR line_promotion_code IS NOT NULL
            OR discount_amount>0 THEN 1 ELSE 0 END) AS promoted
        FROM eligible_lines GROUP BY order_code,customer_code""")
    con.execute("""CREATE TEMP TABLE customer_labels AS
      WITH summary AS (
        SELECT customer_code,MIN(local_date) AS first_visit,COUNT(*) AS lifetime_visits,
          SUM(CASE WHEN local_date>=DATE '2026-01-02' THEN 1 ELSE 0 END) AS visits_180,
          SUM(CASE WHEN local_date>=DATE '2026-01-02' THEN revenue ELSE 0 END) AS monetary_180,
          SUM(CASE WHEN local_date>=DATE '2026-04-02' THEN 1 ELSE 0 END) AS visits_90,
          SUM(CASE WHEN local_date>=DATE '2026-01-02' THEN promoted ELSE 0 END) AS promoted_180,
          SUM(promoted) AS promoted_lifetime
        FROM visits GROUP BY customer_code
      ), threshold AS (
        SELECT quantile_cont(monetary_180,0.75) AS p75 FROM summary WHERE monetary_180>0
      ) SELECT s.customer_code,CASE
          WHEN first_visit>=DATE '2026-05-02' THEN 'New Customers'
          WHEN lifetime_visits>=2 AND visits_90=0 THEN 'At-Risk Customers'
          WHEN visits_180>=3 AND (CASE WHEN visits_180>0 THEN promoted_180::DOUBLE/visits_180
            ELSE promoted_lifetime::DOUBLE/lifetime_visits END)>=0.5
            THEN 'Promotion-Driven Customers'
          WHEN visits_180>=6 AND monetary_180>=t.p75 THEN 'High-Value Loyal Customers'
          WHEN visits_180>=6 THEN 'Frequent Customers'
          ELSE 'Occasional Customers' END AS segment
        FROM summary s CROSS JOIN threshold t""")


def build_search_dashboard(allowed_codes, filters=None, root=None, result_limit=25):
    """Filter sale lines; class and waste are fixed 90-day item/location context."""
    codes = sorted(set(allowed_codes))
    if not codes:
        return {"empty": True}
    root = Path(root or settings.PROJECT_ROOT)
    filters = filters or {}
    integration = _read_report(root / "processed_data/step06-full/integration_report.json", "status", "passed")
    segments = _read_report(root / "processed_data/step15-full/segmentation_report.json",
                            "as_of_exclusive", AS_OF)
    menu = _read_report(root / "processed_data/step34-full/location_menu_performance_report.json",
                        "as_of_exclusive", AS_OF)
    con = duckdb.connect()
    con.execute("SET threads=4")
    try:
        _view(con, "coverage", root / "parquet_data/step06-full/order_coverage",
              integration["outputs"]["order_coverage"]["rows"])
        _view(con, "lines", root / "parquet_data/step06-full/order_lines",
              integration["outputs"]["order_lines"]["rows"])
        _view(con, "menu", root / "parquet_data/step34-full/location_menu_items.parquet",
              menu["outputs"]["location_menu_items"]["rows"])
        source_codes = {row[0] for row in con.execute("SELECT DISTINCT restaurant_code FROM menu").fetchall()}
        scoped_codes = sorted(source_codes.intersection(codes))
        if not scoped_codes:
            return {"empty": True}
        full_network = set(scoped_codes) == source_codes
        con.execute("CREATE TEMP TABLE allowed_locations (restaurant_code VARCHAR PRIMARY KEY)")
        con.executemany("INSERT INTO allowed_locations VALUES (?)", [(code,) for code in scoped_codes])
        con.execute("""CREATE TEMP TABLE eligible_lines AS SELECT l.line_code,l.order_code,
            l.restaurant_code,l.customer_code,l.item_code,l.item_name,l.category_code,
            l.category_name,l.channel_code,l.channel_name,l.order_promotion_code,
            l.line_promotion_code,l.unit_price,l.rating_score,l.quantity,l.revenue,
            l.discount_amount,l.date AS local_date
            FROM lines l JOIN coverage c USING (order_code)
            JOIN allowed_locations a ON l.restaurant_code=a.restaurant_code
            WHERE c.status='completed' AND c.customer_code IS NOT NULL
              AND c.accepted_line_count>0 AND c.known_rejected_lines=0
              AND l.date<DATE '2026-07-01'""")
        if full_network and con.execute("SELECT COUNT(*) FROM eligible_lines").fetchone()[0] != segments["eligible_lines"]:
            raise DashboardUnavailable("Accepted line population differs from Step 15")
        if full_network:
            _view(con, "segment_snapshot", root / "parquet_data/step15-full/customer_segments.parquet",
                  segments["included_customers"])
            con.execute("CREATE TEMP TABLE customer_labels AS SELECT customer_code,segment FROM segment_snapshot")
        else:
            _scoped_segments(con)
        category_options = con.execute("SELECT DISTINCT category_code,category_name FROM eligible_lines ORDER BY 2,1").fetchall()
        channel_options = con.execute("SELECT DISTINCT channel_code,channel_name FROM eligible_lines ORDER BY 2,1").fetchall()
        promotion_options = [row[0] for row in con.execute("""SELECT DISTINCT code FROM (
            SELECT order_promotion_code AS code FROM eligible_lines UNION ALL
            SELECT line_promotion_code AS code FROM eligible_lines) WHERE code IS NOT NULL ORDER BY code""").fetchall()]
        location = filters.get("location", "") if filters.get("location", "") in scoped_codes else ""
        category_codes = {row[0] for row in category_options}
        category = filters.get("category", "") if filters.get("category", "") in category_codes else ""
        channel_codes = {row[0] for row in channel_options}
        channel = filters.get("channel", "") if filters.get("channel", "") in channel_codes else ""
        promotion_value = filters.get("promotion", "")
        promotion = promotion_value if promotion_value in ["none", "any", *promotion_options] else ""
        segment = filters.get("segment", "") if filters.get("segment", "") in SEGMENTS else ""
        performance_class = filters.get("class", "") if filters.get("class", "") in CLASSES else ""
        item = str(filters.get("item", ""))[:60].strip()
        start = _date(filters.get("start"), date(2026, 4, 2))
        end = _date(filters.get("end"), END)
        if start > end:
            start, end = date(2026, 4, 2), END
        min_price = _number(filters.get("min_price"), 0, 1_000_000)
        max_price = _number(filters.get("max_price"), 0, 1_000_000)
        min_rating = _number(filters.get("min_rating"), 1, 5)
        min_waste = _number(filters.get("min_waste"), 0, 1_000_000)
        max_waste = _number(filters.get("max_waste"), 0, 1_000_000)
        clauses = ["e.local_date BETWEEN ? AND ?"]
        params = [start, end]
        for value, sql in ((location, "e.restaurant_code=?"), (category, "e.category_code=?"),
                           (channel, "e.channel_code=?"), (segment, "e.segment=?"),
                           (performance_class, "e.location_menu_class=?")):
            if value:
                clauses.append(sql)
                params.append(value)
        if item:
            clauses.append("(e.item_code ILIKE ? OR e.item_name ILIKE ?)")
            params.extend([f"%{item}%", f"%{item}%"])
        if promotion == "none":
            clauses.append("e.order_promotion_code IS NULL AND e.line_promotion_code IS NULL AND e.discount_amount=0")
        elif promotion == "any":
            clauses.append("(e.order_promotion_code IS NOT NULL OR e.line_promotion_code IS NOT NULL OR e.discount_amount>0)")
        elif promotion:
            clauses.append("(e.order_promotion_code=? OR e.line_promotion_code=?)")
            params.extend([promotion, promotion])
        for value, sql in ((min_price, "e.unit_price>=?"), (max_price, "e.unit_price<=?"),
                           (min_rating, "e.rating_score>=?"), (min_waste, "e.pair_wasted_quantity>=?"),
                           (max_waste, "e.pair_wasted_quantity<=?")):
            if value is not None:
                clauses.append(sql)
                params.append(value)
        con.execute("""CREATE TEMP VIEW scoped_lines AS SELECT e.*,s.segment,
            m.location_menu_class,m.wasted_quantity AS pair_wasted_quantity
            FROM eligible_lines e JOIN customer_labels s USING (customer_code)
            JOIN menu m ON e.restaurant_code=m.restaurant_code AND e.item_code=m.item_code""")
        where = " AND ".join(clauses)
        con.execute(f"CREATE TEMP TABLE filtered AS SELECT e.* FROM scoped_lines e WHERE {where}", params)
        line_count, order_count, customer_count, quantity, revenue = con.execute("""SELECT
            COUNT(*),COUNT(DISTINCT order_code),COUNT(DISTINCT customer_code),
            COALESCE(SUM(quantity),0),COALESCE(SUM(revenue),0) FROM filtered""").fetchone()
        query_sql = """SELECT restaurant_code,item_code,ANY_VALUE(item_name) AS item_name,
            ANY_VALUE(category_name) AS category_name,ANY_VALUE(location_menu_class) AS performance_class,
            ANY_VALUE(pair_wasted_quantity) AS pair_waste_90,COUNT(*) AS lines,
            SUM(quantity) AS quantity,SUM(revenue) AS revenue,AVG(rating_score) AS observed_rating,
            COUNT(rating_score) AS rating_count FROM filtered GROUP BY 1,2
            ORDER BY revenue DESC,restaurant_code,item_code"""
        if result_limit is not None:
            query_sql += " LIMIT ?"
        cursor = con.execute(query_sql, [result_limit] if result_limit is not None else [])
        names = [column[0] for column in cursor.description]
        results = [dict(zip(names, row)) for row in cursor.fetchall()]
        return {"empty": False, "full_network": full_network, "location_count": len(scoped_codes),
                "line_count": line_count, "order_count": order_count,
                "customer_count": customer_count, "quantity": quantity, "revenue": revenue,
                "results": results, "location_options": scoped_codes,
                "category_options": category_options, "channel_options": channel_options,
                "promotion_options": promotion_options, "segment_options": SEGMENTS if full_network else SEGMENTS[:-1],
                "class_options": CLASSES, "location": location, "category": category,
                "channel": channel, "promotion": promotion, "segment": segment,
                "performance_class": performance_class, "item": item,
                "start": start.isoformat(), "end": end.isoformat(),
                "min_price": min_price, "max_price": max_price,
                "min_rating": min_rating, "min_waste": min_waste, "max_waste": max_waste}
    finally:
        con.close()
