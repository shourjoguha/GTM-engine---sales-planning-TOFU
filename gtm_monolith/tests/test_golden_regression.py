"""
Golden output regression tests for the monolith engine.

Runs the monolith pipeline with the v006 reference config and compares
key metrics against the golden reference values. Tolerances are tight
enough to catch regressions but allow for floating-point differences.
"""

import json
import pytest
import pandas as pd
from pathlib import Path

from gtm_monolith.engine import (
    GTMConfig,
    DataLayer,
    TargetLayer,
    CapacityLayer,
    EconomicsLayer,
    OptimizerLayer,
    ValidationLayer,
    RecoveryLayer,
    LeverAnalysisLayer,
)
from gtm_monolith.run_plan_monolith import (
    build_enriched_summary,
    sanitize_summary,
    build_monthly_waterfall,
    build_economics_decay,
    build_cashcycle_waterfall,
    prepare_recovery_inputs,
)


GOLDEN_DIR = Path(__file__).parent / "golden" / "v006_reference"
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_PATH = str(PROJECT_ROOT / "data" / "raw" / "2025_actuals.csv")


@pytest.fixture(scope="module")
def golden_summary():
    with open(GOLDEN_DIR / "summary.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def golden_results():
    return pd.read_csv(GOLDEN_DIR / "results.csv")


@pytest.fixture(scope="module")
def golden_targets():
    return pd.read_csv(GOLDEN_DIR / "targets.csv")


@pytest.fixture(scope="module")
def golden_capacity():
    return pd.read_csv(GOLDEN_DIR / "ae_capacity.csv")


@pytest.fixture(scope="module")
def golden_config():
    return GTMConfig(str(GOLDEN_DIR / "config.yaml"))


@pytest.fixture(scope="module")
def monolith_pipeline(golden_config):
    """Run the monolith pipeline once and return all artifacts."""
    config = golden_config

    loader = DataLayer(config)
    df_raw = loader.load(DATA_PATH)
    df_clean = loader.prepare(df_raw)
    baselines = loader.compute_segment_baselines(df_clean)

    target_gen = TargetLayer(config)
    targets = target_gen.generate()

    ae_model = CapacityLayer(config)
    capacity = ae_model.calculate()

    economics = EconomicsLayer(config)
    economics.load_baselines(baselines)

    optimizer = OptimizerLayer(config)
    results = optimizer.optimize(
        targets=targets,
        base_data=df_clean,
        economics_engine=economics,
        capacity=capacity,
    )
    opt_summary = optimizer.get_optimization_summary(results)
    enriched = build_enriched_summary(opt_summary, capacity, results)
    summary = sanitize_summary(enriched)

    validator = ValidationLayer(config)
    validation = validator.validate(results, targets=targets, capacity=capacity)

    recovery_engine = RecoveryLayer(config)
    targets_r, capacity_r = prepare_recovery_inputs(targets, capacity)
    recovery = recovery_engine.analyze(results, targets_r, capacity_r)

    return {
        "results": results,
        "summary": summary,
        "targets": targets,
        "capacity": capacity,
        "baselines": baselines,
        "economics": economics,
        "validation": validation,
        "recovery": recovery,
    }


# ── Core metric regression tests ───────────────────────────────────


class TestGoldenMetrics:
    """Compare monolith output against golden reference values."""

    TOLERANCE = 1e-4  # 0.01% relative tolerance

    def _assert_close(self, actual, expected, label, rel_tol=None):
        tol = rel_tol or self.TOLERANCE
        if expected == 0:
            assert abs(actual) < 1e-6, f"{label}: expected ~0, got {actual}"
        else:
            rel_diff = abs(actual - expected) / abs(expected)
            assert rel_diff < tol, (
                f"{label}: expected {expected}, got {actual} "
                f"(rel diff: {rel_diff:.6f}, tolerance: {tol})"
            )

    def test_total_annual_bookings(self, monolith_pipeline, golden_summary):
        actual = monolith_pipeline["summary"].get(
            "total_annual_bookings",
            monolith_pipeline["summary"].get("total_bookings", 0),
        )
        expected = golden_summary["total_annual_bookings"]
        self._assert_close(actual, expected, "total_annual_bookings")

    def test_total_annual_saos(self, monolith_pipeline, golden_summary):
        actual = monolith_pipeline["summary"].get(
            "total_annual_saos",
            monolith_pipeline["summary"].get("total_saos", 0),
        )
        expected = golden_summary["total_annual_saos"]
        self._assert_close(actual, expected, "total_annual_saos")

    def test_total_ae_hc(self, monolith_pipeline, golden_summary):
        actual = monolith_pipeline["summary"]["total_ae_hc"]
        expected = golden_summary["total_ae_hc"]
        assert actual == expected, f"total_ae_hc: expected {expected}, got {actual}"

    def test_months_capacity_constrained(self, monolith_pipeline, golden_summary):
        actual = monolith_pipeline["summary"].get("months_capacity_constrained", 0)
        expected = golden_summary["months_capacity_constrained"]
        assert actual == expected, (
            f"months_capacity_constrained: expected {expected}, got {actual}"
        )

    def test_in_window_pct(self, monolith_pipeline, golden_summary):
        actual = monolith_pipeline["summary"].get("in_window_pct", 0)
        expected = golden_summary["in_window_pct"]
        self._assert_close(actual, expected, "in_window_pct", rel_tol=0.001)

    def test_total_pipeline(self, monolith_pipeline, golden_summary):
        actual = monolith_pipeline["summary"].get(
            "total_annual_pipeline",
            monolith_pipeline["summary"].get("total_pipeline", 0),
        )
        expected = golden_summary["total_annual_pipeline"]
        self._assert_close(actual, expected, "total_annual_pipeline")

    def test_total_deals(self, monolith_pipeline, golden_summary):
        actual = monolith_pipeline["summary"].get(
            "total_annual_deals",
            monolith_pipeline["summary"].get("total_deals", 0),
        )
        expected = golden_summary["total_annual_deals"]
        self._assert_close(actual, expected, "total_deals")


# ── Shape and schema tests ─────────────────────────────────────────


class TestOutputSchema:
    """Verify the monolith produces the same output structure."""

    def test_results_columns_match(self, monolith_pipeline, golden_results):
        actual_cols = set(monolith_pipeline["results"].columns)
        expected_cols = set(golden_results.columns)
        missing = expected_cols - actual_cols
        assert not missing, f"Missing columns in monolith results: {missing}"

    def test_results_row_count(self, monolith_pipeline, golden_results):
        actual = len(monolith_pipeline["results"])
        expected = len(golden_results)
        assert actual == expected, (
            f"Row count mismatch: monolith={actual}, golden={expected}"
        )

    def test_targets_shape(self, monolith_pipeline, golden_targets):
        actual = monolith_pipeline["targets"].shape
        expected = golden_targets.shape
        assert actual == expected, (
            f"Targets shape mismatch: monolith={actual}, golden={expected}"
        )

    def test_capacity_shape(self, monolith_pipeline, golden_capacity):
        actual = monolith_pipeline["capacity"].shape
        expected = golden_capacity.shape
        assert actual == expected, (
            f"Capacity shape mismatch: monolith={actual}, golden={expected}"
        )

    def test_validation_has_passed_key(self, monolith_pipeline):
        validation = monolith_pipeline["validation"]
        assert isinstance(validation, dict), "Validation result should be a dict"
        assert "passed" in validation, "Validation should have 'passed' key"

    def test_recovery_has_risk_assessment(self, monolith_pipeline):
        recovery = monolith_pipeline["recovery"]
        assert isinstance(recovery, dict), "Recovery result should be a dict"
        assert "risk_assessment" in recovery, "Recovery should have 'risk_assessment' key"


# ── Segment-level regression tests ─────────────────────────────────


class TestSegmentRegression:
    """Verify per-segment bookings match golden reference."""

    TOLERANCE = 0.01  # 1% tolerance for segment-level values

    def test_segment_bookings_match(self, monolith_pipeline, golden_results):
        actual = monolith_pipeline["results"]
        expected = golden_results

        if "segment_key" in actual.columns and "segment_key" in expected.columns:
            actual_seg = actual.groupby("segment_key")["projected_bookings"].sum()
            expected_seg = expected.groupby("segment_key")["projected_bookings"].sum()

            for seg in expected_seg.index:
                if seg in actual_seg.index:
                    exp_val = expected_seg[seg]
                    act_val = actual_seg[seg]
                    if exp_val > 0:
                        rel_diff = abs(act_val - exp_val) / exp_val
                        assert rel_diff < self.TOLERANCE, (
                            f"Segment {seg}: expected {exp_val:.2f}, "
                            f"got {act_val:.2f} (rel diff: {rel_diff:.4f})"
                        )

    def test_monthly_bookings_match(self, monolith_pipeline, golden_results):
        actual = monolith_pipeline["results"]
        expected = golden_results

        if "month" in actual.columns and "month" in expected.columns:
            actual_monthly = actual.groupby("month")["projected_bookings"].sum()
            expected_monthly = expected.groupby("month")["projected_bookings"].sum()

            for month in expected_monthly.index:
                if month in actual_monthly.index:
                    exp_val = expected_monthly[month]
                    act_val = actual_monthly[month]
                    if exp_val > 0:
                        rel_diff = abs(act_val - exp_val) / exp_val
                        assert rel_diff < 0.01, (
                            f"Month {month}: expected {exp_val:.2f}, "
                            f"got {act_val:.2f} (rel diff: {rel_diff:.4f})"
                        )


# ── Waterfall / economics decay tests ──────────────────────────────


class TestIntermediateArtifacts:
    """Test waterfall and decay curve generation."""

    def test_monthly_waterfall_shape(self, monolith_pipeline):
        targets = monolith_pipeline["targets"]
        capacity = monolith_pipeline["capacity"]
        results = monolith_pipeline["results"]
        waterfall = build_monthly_waterfall(targets, capacity, results)
        assert len(waterfall) == 12, f"Waterfall should have 12 rows, got {len(waterfall)}"
        expected_cols = {"month", "target_revenue", "total_bookings", "capacity_gap"}
        assert expected_cols.issubset(set(waterfall.columns))

    def test_economics_decay_generation(self, monolith_pipeline):
        baselines = monolith_pipeline["baselines"]
        economics = monolith_pipeline["economics"]
        decay_df = build_economics_decay(baselines, economics)
        assert len(decay_df) > 0, "Decay DataFrame should not be empty"
        expected_cols = {"segment", "volume_saos", "effective_asp", "effective_win_rate"}
        assert expected_cols.issubset(set(decay_df.columns))


# ── Config round-trip test ─────────────────────────────────────────


class TestConfigRoundTrip:
    """Verify GTMConfig from_dict/to_dict round-trip."""

    def test_from_dict_to_dict(self, golden_config):
        config_dict = golden_config.to_dict()
        config2 = GTMConfig.from_dict(config_dict)
        assert config2.to_dict() == config_dict

    def test_hash_stability(self, golden_config):
        h1 = golden_config.hash()
        h2 = golden_config.hash()
        assert h1 == h2, "Config hash should be stable"
