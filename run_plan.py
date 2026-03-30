#!/usr/bin/env python3
"""
GTM Planning Engine — Master Script

Runs the full planning pipeline end-to-end and saves all intermediate
results into a versioned output directory (versions/v{NNN}/).

Usage:
    python run_plan.py
    python run_plan.py --config config.yaml --description "FY26 base plan"
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from gtm_engine.config_manager import ConfigManager
from gtm_engine.data_loader import DataLoader
from gtm_engine.target_generator import TargetGenerator
from gtm_engine.ae_capacity import AECapacityModel
from gtm_engine.economics_engine import EconomicsEngine
from gtm_engine.optimizer import AllocationOptimizer
from gtm_engine.validation import ValidationEngine
from gtm_engine.recovery import RecoveryEngine
from gtm_engine.version_store import VersionStore


def json_safe(obj: object) -> object:
    """Convert numpy/pandas types for JSON serialization."""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, pd.DataFrame):
        return obj.to_dict(orient="records")
    if isinstance(obj, np.bool_):
        return bool(obj)
    raise TypeError(f"Not JSON serializable: {type(obj)}")


def sanitize_summary(summary: dict) -> dict:
    """Convert numpy types in a summary dict to native Python types."""
    cleaned = {}
    for key, value in summary.items():
        if isinstance(value, (np.integer, np.floating)):
            cleaned[key] = float(value)
        elif isinstance(value, np.bool_):
            cleaned[key] = bool(value)
        elif isinstance(value, dict):
            cleaned[key] = sanitize_summary(value)
        else:
            cleaned[key] = value
    return cleaned


def build_monthly_waterfall(
    targets: pd.DataFrame,
    capacity: pd.DataFrame,
    results: pd.DataFrame,
) -> pd.DataFrame:
    """Build consolidated month-by-month waterfall showing how metrics flow."""
    monthly_alloc = results.groupby("month").agg(
        total_required_saos=("required_saos", "sum"),
        total_pipeline=("projected_pipeline", "sum"),
        total_bookings=("projected_bookings", "sum"),
    ).reset_index()

    waterfall = targets[["month", "target_revenue"]].merge(
        capacity[[
            "month", "hc_tenured", "hc_ramping", "hc_total",
            "mentoring_tax", "shrinkage_rate", "effective_capacity_saos",
        ]],
        on="month",
    ).merge(monthly_alloc, on="month")

    waterfall["capacity_gap"] = (
        waterfall["effective_capacity_saos"] - waterfall["total_required_saos"]
    )
    waterfall["bookings_vs_target"] = (
        waterfall["total_bookings"] - waterfall["target_revenue"]
    )
    waterfall["cumulative_target"] = waterfall["target_revenue"].cumsum()
    waterfall["cumulative_bookings"] = waterfall["total_bookings"].cumsum()
    waterfall["cumulative_gap"] = (
        waterfall["cumulative_bookings"] - waterfall["cumulative_target"]
    )
    return waterfall


def build_economics_decay(
    baselines: dict,
    economics: EconomicsEngine,
) -> pd.DataFrame:
    """Generate decay curves at various volume levels for each segment."""
    volume_levels = [0, 50, 100, 200, 300, 400, 500, 600, 800, 1000]
    rows = []
    for segment in baselines:
        for vol in volume_levels:
            rows.append({
                "segment": segment,
                "volume_saos": vol,
                "effective_asp": economics.get_effective_asp(segment, vol),
                "effective_win_rate": economics.get_effective_win_rate(segment, vol),
                "effective_roi": economics.get_effective_roi(segment, vol),
            })
    return pd.DataFrame(rows)


def prepare_recovery_inputs(
    targets: pd.DataFrame,
    capacity: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Add column aliases required by RecoveryEngine."""
    targets_r = targets.copy()
    if "target_revenue" in targets_r.columns and "target_bookings" not in targets_r.columns:
        targets_r["target_bookings"] = targets_r["target_revenue"]
    if "quarter" not in targets_r.columns and "month" in targets_r.columns:
        targets_r["quarter"] = (targets_r["month"] - 1) // 3 + 1

    capacity_r = capacity.copy()
    if "quarter" not in capacity_r.columns and "month" in capacity_r.columns:
        capacity_r["quarter"] = (capacity_r["month"] - 1) // 3 + 1
    if "effective_capacity" not in capacity_r.columns and "effective_capacity_saos" in capacity_r.columns:
        capacity_r["effective_capacity"] = capacity_r["effective_capacity_saos"]

    return targets_r, capacity_r


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the GTM Planning Engine pipeline")
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML (default: config.yaml)")
    parser.add_argument("--description", default="", help="Version description label")
    args = parser.parse_args()

    project_root = Path(__file__).parent
    config_path = str(project_root / args.config)

    total_stages = 8
    print("=" * 70)
    print("GTM PLANNING ENGINE — FULL PIPELINE RUN")
    print("=" * 70)

    # ── Stage 1: Configuration ──────────────────────────────────────────
    print(f"\n[1/{total_stages}] Loading configuration...")
    config = ConfigManager(config_path)
    print(f"  Annual target: ${config.get('targets.annual_target'):,.0f}")
    print(f"  Planning mode: {config.get('targets.planning_mode')}")
    print(f"  Optimizer: {config.get('allocation.optimizer_mode', 'greedy')}")

    # ── Stage 2: Data loading ───────────────────────────────────────────
    print(f"\n[2/{total_stages}] Loading and preparing data...")
    loader = DataLoader(config)
    data_path = str(project_root / "data" / "raw" / "2025_actuals.csv")
    df_raw = loader.load(data_path)
    df_clean = loader.prepare(df_raw)
    baselines = loader.compute_segment_baselines(df_clean)
    print(f"  {len(df_clean)} rows, {len(baselines)} segments")

    # ── Stage 3: Target generation ──────────────────────────────────────
    print(f"\n[3/{total_stages}] Generating monthly targets...")
    target_gen = TargetGenerator(config)
    targets = target_gen.generate()
    print(f"  {len(targets)} periods, total: ${targets['target_revenue'].sum():,.0f}")

    # ── Stage 4: AE capacity ────────────────────────────────────────────
    print(f"\n[4/{total_stages}] Calculating AE capacity...")
    ae_model = AECapacityModel(config)
    capacity = ae_model.calculate()
    capacity_summary = ae_model.get_capacity_summary()
    print(f"  Annual capacity: {capacity_summary.get('total_annual_capacity', 0):,.0f} SAOs")

    # ── Stage 5: Economics engine ───────────────────────────────────────
    print(f"\n[5/{total_stages}] Initializing economics engine...")
    economics = EconomicsEngine(config)
    economics.load_baselines(baselines)
    print(f"  Baselines loaded for {len(baselines)} segments")

    # ── Stage 6: Optimization ───────────────────────────────────────────
    print(f"\n[6/{total_stages}] Running allocation optimizer...")
    optimizer = AllocationOptimizer(config)
    results = optimizer.optimize(
        targets=targets,
        base_data=df_clean,
        economics_engine=economics,
        capacity=capacity,
    )
    opt_summary = optimizer.get_optimization_summary(results)
    total_bookings = opt_summary.get('total_annual_bookings', opt_summary.get('total_bookings', 0))
    total_saos = opt_summary.get('total_annual_saos', opt_summary.get('total_saos', 0))
    print(f"  {len(results)} allocation rows")
    print(f"  Projected bookings: ${total_bookings:,.0f}")

    # ── Stage 7: Validation ─────────────────────────────────────────────
    print(f"\n[7/{total_stages}] Validating results...")
    validator = ValidationEngine(config)
    validation = validator.validate(results, targets=targets, capacity=capacity)
    overall_pass = validation.get("overall_pass", False) if isinstance(validation, dict) else False
    print(f"  Validation: {'PASS' if overall_pass else 'FAIL'}")

    # ── Stage 8: Recovery analysis ──────────────────────────────────────
    print(f"\n[8/{total_stages}] Running recovery analysis...")
    recovery_engine = RecoveryEngine(config)
    targets_r, capacity_r = prepare_recovery_inputs(targets, capacity)
    recovery_analysis = recovery_engine.analyze(results, targets_r, capacity_r)
    if isinstance(recovery_analysis, dict):
        print(f"  Risk: {recovery_analysis.get('risk_assessment', 'N/A')}")

    # ── Save version ────────────────────────────────────────────────────
    print("\n" + "-" * 70)
    print("Saving version...")

    summary_dict = sanitize_summary(opt_summary) if isinstance(opt_summary, dict) else {}
    store = VersionStore(config)
    version_id = store.save(
        config_snapshot=config.to_dict(),
        results=results,
        summary=summary_dict,
        description=args.description or "Pipeline run",
        planning_mode=config.get("targets.planning_mode", "full_year"),
    )

    version_dir = Path(config.get("system.output_dir", "versions")) / f"v{version_id:03d}"

    # ── Write intermediate files ────────────────────────────────────────
    targets.to_csv(version_dir / "targets.csv", index=False)

    capacity.to_csv(version_dir / "ae_capacity.csv", index=False)

    baselines_df = pd.DataFrame([
        {"segment": seg, "asp": vals["asp"], "win_rate": vals["win_rate"]}
        for seg, vals in baselines.items()
    ])
    baselines_df.to_csv(version_dir / "economics_baselines.csv", index=False)

    decay_df = build_economics_decay(baselines, economics)
    decay_df.to_csv(version_dir / "economics_decay.csv", index=False)

    with open(version_dir / "validation_report.json", "w") as f:
        json.dump(validation, f, indent=2, default=json_safe)

    with open(version_dir / "recovery_analysis.json", "w") as f:
        json.dump(recovery_analysis, f, indent=2, default=json_safe)

    waterfall = build_monthly_waterfall(targets, capacity, results)
    waterfall.to_csv(version_dir / "monthly_waterfall.csv", index=False)

    # ── Final summary ───────────────────────────────────────────────────
    print(f"\nVersion {version_id} saved to {version_dir}/")
    print(f"\n  Files:")
    print(f"    config.yaml              Config snapshot")
    print(f"    results.csv              Final allocation (segment x month)")
    print(f"    summary.json             Aggregate metrics")
    print(f"    targets.csv              Monthly target distribution")
    print(f"    ae_capacity.csv          Monthly AE capacity breakdown")
    print(f"    economics_baselines.csv  Segment ASP & win rate baselines")
    print(f"    economics_decay.csv      Decay curves by volume level")
    print(f"    validation_report.json   Validation check results")
    print(f"    recovery_analysis.json   Recovery & stretch analysis")
    print(f"    monthly_waterfall.csv    Consolidated month-by-month view")

    print(f"\n  Key Metrics:")
    print(f"    Annual target:       ${targets['target_revenue'].sum():,.0f}")
    print(f"    Projected bookings:  ${total_bookings:,.0f}")
    print(f"    Total SAOs:          {total_saos:,.0f}")
    print(f"    Validation:          {'PASS' if overall_pass else 'FAIL'}")

    print("\n" + "=" * 70)
    print("PIPELINE COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
