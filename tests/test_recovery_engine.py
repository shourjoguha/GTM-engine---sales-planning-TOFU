import unittest

import pandas as pd

from gtm_engine.recovery import RecoveryEngine


class TestRecoveryEngineRegression(unittest.TestCase):
    def test_calculate_quarterly_gaps_avoids_9x_target_inflation(self) -> None:
        config = {
            "ae_model": {
                "stretch_threshold": 1.20,
                "mentoring": {"overhead_pct_per_new_hire": 0.10},
            },
            "system": {"tolerance": 0.001},
        }
        engine = RecoveryEngine(config=config)

        targets = pd.DataFrame(
            {
                "period": ["quarter_1", "quarter_2", "quarter_3", "quarter_4"],
                "target_bookings": [100.0, 120.0, 140.0, 160.0],
            }
        )

        allocation_rows = []
        per_row_projected = {
            "quarter_1": 10.0,
            "quarter_2": 12.0,
            "quarter_3": 14.0,
            "quarter_4": 16.0,
        }
        for period, row_value in per_row_projected.items():
            for _ in range(9):
                allocation_rows.append(
                    {
                        "period": period,
                        "projected_bookings": row_value,
                    }
                )
        allocation_results = pd.DataFrame(allocation_rows)

        analysis = engine.analyze(allocation_results=allocation_results, targets=targets)
        quarterly_summary = analysis["quarterly_summary"].sort_values("quarter").reset_index(drop=True)

        expected_target = pd.Series([100.0, 120.0, 140.0, 160.0], name="target")
        expected_projected = pd.Series([90.0, 108.0, 126.0, 144.0], name="projected")
        expected_gap = pd.Series([10.0, 12.0, 14.0, 16.0], name="gap")

        pd.testing.assert_series_equal(quarterly_summary["target"], expected_target, check_names=True)
        pd.testing.assert_series_equal(quarterly_summary["projected"], expected_projected, check_names=True)
        pd.testing.assert_series_equal(quarterly_summary["gap"], expected_gap, check_names=True)
        self.assertEqual(float(quarterly_summary["target"].sum()), 520.0)

    def test_calculate_quarterly_gaps_handles_duplicate_target_periods(self) -> None:
        config = {
            "ae_model": {
                "stretch_threshold": 1.20,
                "mentoring": {"overhead_pct_per_new_hire": 0.10},
            },
            "system": {"tolerance": 0.001},
        }
        engine = RecoveryEngine(config=config)

        targets = pd.DataFrame(
            {
                "period": [
                    "quarter_1", "quarter_1",
                    "quarter_2", "quarter_2",
                    "quarter_3", "quarter_3",
                    "quarter_4", "quarter_4",
                ],
                "target_bookings": [50.0, 50.0, 60.0, 60.0, 70.0, 70.0, 80.0, 80.0],
            }
        )
        allocation_results = pd.DataFrame(
            {
                "period": ["quarter_1", "quarter_2", "quarter_3", "quarter_4"],
                "projected_bookings": [90.0, 108.0, 126.0, 144.0],
            }
        )

        analysis = engine.analyze(allocation_results=allocation_results, targets=targets)
        quarterly_summary = analysis["quarterly_summary"].sort_values("quarter").reset_index(drop=True)

        expected_target = pd.Series([100.0, 120.0, 140.0, 160.0], name="target")
        expected_projected = pd.Series([90.0, 108.0, 126.0, 144.0], name="projected")
        expected_gap = pd.Series([10.0, 12.0, 14.0, 16.0], name="gap")

        pd.testing.assert_series_equal(quarterly_summary["target"], expected_target, check_names=True)
        pd.testing.assert_series_equal(quarterly_summary["projected"], expected_projected, check_names=True)
        pd.testing.assert_series_equal(quarterly_summary["gap"], expected_gap, check_names=True)


if __name__ == "__main__":
    unittest.main()
