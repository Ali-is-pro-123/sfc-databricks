"""Calendar and direct-horizon target checks for configurable forecasts."""

import unittest
from datetime import date

import duckdb

from python_pipeline.demand import NUMERIC
from python_pipeline.forecast import add_months, month_days, months_between, training_query


class ForecastTests(unittest.TestCase):
    def test_calendar_month_boundaries(self):
        self.assertEqual(add_months(date(2026, 12, 1), 2), date(2027, 2, 1))
        self.assertEqual(add_months(date(2026, 1, 1), -1), date(2025, 12, 1))
        self.assertEqual(month_days(date(2026, 2, 1)), 28)
        self.assertEqual(months_between(date(2026, 7, 1), date(2026, 9, 1)), 2)
        with self.assertRaisesRegex(ValueError, "day one"):
            add_months(date(2026, 7, 2), 1)
        with self.assertRaisesRegex(ValueError, "horizons"):
            training_query(4)

    def test_direct_horizon_uses_future_target_not_future_features(self):
        con = duckdb.connect()
        numeric_columns = ", ".join(f"{name} DOUBLE" for name in NUMERIC)
        con.execute(f"""CREATE TABLE historic_snapshots(restaurant_code VARCHAR,
            item_code VARCHAR,category_code VARCHAR,cutoff DATE,label DOUBLE,
            {numeric_columns})""")
        columns = "restaurant_code,item_code,category_code,cutoff,label," + ",".join(NUMERIC)
        for month, label, recent in ((5,10,1),(6,20,2),(7,30,3)):
            numeric_values = [float(recent)] + [0.0]*(len(NUMERIC)-1)
            con.execute(f"INSERT INTO historic_snapshots({columns}) VALUES ({','.join(['?']*(5+len(NUMERIC)))})",
                        ["R1","I1","C1",date(2025,month,1),label,*numeric_values])
        rows = con.execute(training_query(2),[date(2025,8,1)]).fetchall()
        self.assertEqual(len(rows),2)
        feature_count = len(NUMERIC)+2
        self.assertEqual((rows[0][0],rows[0][feature_count],rows[0][feature_count+2]),
                         (1.0,20.0,date(2025,6,1)))
        self.assertEqual((rows[1][0],rows[1][feature_count],rows[1][feature_count+2]),
                         (2.0,30.0,date(2025,7,1)))
        con.execute("UPDATE historic_snapshots SET label=99 WHERE cutoff='2025-06-01'")
        changed = con.execute(training_query(2),[date(2025,8,1)]).fetchone()
        self.assertEqual(changed[0],1.0)
        self.assertEqual(changed[feature_count],99.0)


if __name__ == "__main__":
    unittest.main()
