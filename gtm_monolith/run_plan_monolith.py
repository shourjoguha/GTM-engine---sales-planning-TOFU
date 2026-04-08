#!/usr/bin/env python3
"""
GTM Planning Engine — Monolith CLI

Runs the full planning pipeline end-to-end and saves all intermediate
results into a versioned output directory (versions/v{NNN}/).

Supports five modes:
    full        — Run the complete 8-stage pipeline (default)
    adjustment  — Load a version, apply mid-cycle changes, re-run, compare
    what-if     — Run base pipeline + scenario analysis
    compare     — Compare 2+ existing plan versions
    recommend   — Analytical gap attribution + ranked lever recommendations

Usage:
    python run_plan_monolith.py
    python run_plan_monolith.py --config config.yaml --description "FY26 base plan"
    python run_plan_monolith.py --mode what-if --enable-scenarios all
    python run_plan_monolith.py --mode adjustment --base-version 1 --target-changes '{"annual_target": 195000000}'
    python run_plan_monolith.py --mode compare --compare-versions 1 2 5
    python run_plan_monolith.py --mode recommend --base-version 15
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, Dict, Tuple, Any

import numpy as np
import pandas as pd

from gtm_monolith.engine import (
    GTMConfig,
    DataLayer,
    TargetLayer,
    CapacityLayer,
    EconomicsLayer,
    OptimizerLayer,
    ValidationLayer,
    RecoveryLayer,
    VersionStoreLayer,
    AdjustmentLayer,
    WhatIfLayer,
    ComparatorLayer,
    LeverAnalysisLayer,
)


# ── Utility functions ──────────────────────────────────────────────────


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


def build_enriched_summary(
    opt_summary: dict,
    capacity: pd.DataFrame,
    results: pd.DataFrame,
) -> dict:
    """Normalize optimizer summary keys and add computed metrics."""
    enriched = dict(opt_summary)

    enriched["total_bookings"] = opt_summary.get(
        "total_bookings", opt_summary.get("total_annual_bookings", 0.0)
    )
    enriched["total_pipeline"] = opt_summary.get(
        "total_pipeline", opt_summary.get("total_annual_pipeline", 0.0)
    )
    enriched["total_saos"] = opt_summary.get(
        "total_saos", opt_summary.get("total_annual_saos", 0)
    )
    enriched["total_deals"] = opt_summary.get(
        "total_deals", opt_summary.get("total_annual_deals", 0)
    )

    total_ae_hc = 0
    if "hc_total" in capacity.columns:
        total_ae_hc = int(capacity["hc_total"].max())
    enriched["total_ae_hc"] = total_ae_hc

    total_saos = enriched["total_saos"]
    enriched["productivity_per_ae"] = (
        float(total_saos) / total_ae_hc if total_ae_hc > 0 else 0.0
    )

    if "month" in results.columns and "projected_bookings" in results.columns:
        monthly_bookings = results.groupby("month")["projected_bookings"].sum()
        enriched["monthly_volatility"] = float(monthly_bookings.std())
    else:
        enriched["monthly_volatility"] = 0.0

    if "effective_capacity_saos" in capacity.columns:
        total_capacity = float(capacity["effective_capacity_saos"].sum())
        enriched["capacity_utilisation"] = (
            float(total_saos) / total_capacity if total_capacity > 0 else 0.0
        )
    else:
        enriched["capacity_utilisation"] = 0.0

    return enriched


def normalize_saved_summary(summary: dict) -> dict:
    """Normalize a saved summary.json so it has the keys Comparator expects."""
    normalized = dict(summary)
    normalized.setdefault("total_bookings", summary.get("total_annual_bookings", 0.0))
    normalized.setdefault("total_pipeline", summary.get("total_annual_pipeline", 0.0))
    normalized.setdefault("total_saos", summary.get("total_annual_saos", 0))
    normalized.setdefault("total_deals", summary.get("total_annual_deals", 0))
    normalized.setdefault("total_ae_hc", 0)
    normalized.setdefault("monthly_volatility", 0.0)
    normalized.setdefault("capacity_utilisation", 0.0)
    return normalized


# ── Waterfall / decay builders ─────────────────────────────────────────


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
    economics: EconomicsLayer,
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


def build_cashcycle_waterfall(
    results: pd.DataFrame,
    economics: EconomicsLayer,
    config: GTMConfig,
) -> pd.DataFrame:
    """Build month-by-month booking realization waterfall from cash cycle delays."""
    horizon = config.get("economics.cash_cycle", {}).get("planning_horizon_months", 12)
    rows = []
    for _, row in results.iterrows():
        month = int(row["month"])
        seg_key = row["segment_key"]
        product = economics._extract_product_from_segment(seg_key)
        schedule = economics.get_realization_schedule(product)
        total_bookings = row["projected_bookings"]

        for delay, prob in schedule.items():
            booking_month = month + int(delay)
            rows.append({
                "sao_month": month,
                "booking_month": booking_month,
                "segment_key": seg_key,
                "product": product,
                "delay_months": int(delay),
                "probability": prob,
                "sao_bookings": total_bookings,
                "realized_bookings": total_bookings * prob,
                "in_window": booking_month <= horizon,
            })
    return pd.DataFrame(rows)


def prepare_recovery_inputs(
    targets: pd.DataFrame,
    capacity: pd.DataFrame,
) -> tuple:
    """Add column aliases required by RecoveryLayer."""
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


def alias_columns_for_adjustment(df: pd.DataFrame) -> pd.DataFrame:
    """Add column aliases that AdjustmentLayer expects (segment, period)."""
    out = df.copy()
    if "segment_key" in out.columns and "segment" not in out.columns:
        out["segment"] = out["segment_key"]
    if "month" in out.columns and "period" not in out.columns:
        out["period"] = out["month"]
    return out


# ── Pipeline function factory ──────────────────────────────────────────


def make_pipeline_fn(
    project_root: Path,
    data_path: str,
) -> Callable[[dict], Tuple[pd.DataFrame, dict]]:
    """Return a re-entrant pipeline callable for WhatIfLayer.

    The returned function accepts a plain config dict, runs stages 2-6
    of the planning pipeline, and returns ``(results_df, enriched_summary)``.
    Each call creates fresh engine instances — no shared mutable state.
    """

    def run_core_pipeline(config_dict: dict) -> Tuple[pd.DataFrame, dict]:
        config = GTMConfig.from_dict(config_dict)

        loader = DataLayer(config)
        df_raw = loader.load(data_path)
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
        return results, sanitize_summary(enriched)

    return run_core_pipeline


# ── Mode implementations ───────────────────────────────────────────────


def run_full_mode(args: argparse.Namespace, config: GTMConfig, project_root: Path) -> None:
    """Run the complete 8-stage pipeline (default mode)."""
    data_path = str(project_root / "data" / "raw" / "2025_actuals.csv")
    total_stages = 8

    # ── Stage 2: Data loading ───────────────────────────────────────
    print(f"\n[2/{total_stages}] Loading and preparing data...")
    loader = DataLayer(config)
    df_raw = loader.load(data_path)
    df_clean = loader.prepare(df_raw)
    baselines = loader.compute_segment_baselines(df_clean)
    print(f"  {len(df_clean)} rows, {len(baselines)} segments")

    # ── Stage 3: Target generation ──────────────────────────────────
    print(f"\n[3/{total_stages}] Generating monthly targets...")
    target_gen = TargetLayer(config)
    targets = target_gen.generate()
    print(f"  {len(targets)} periods, total: ${targets['target_revenue'].sum():,.0f}")

    # ── Stage 4: AE capacity ────────────────────────────────────────
    print(f"\n[4/{total_stages}] Calculating AE capacity...")
    ae_model = CapacityLayer(config)
    capacity = ae_model.calculate()
    capacity_summary = ae_model.get_capacity_summary()
    print(f"  Annual capacity: {capacity_summary.get('total_annual_capacity', 0):,.0f} SAOs")

    # ── Stage 5: Economics engine ───────────────────────────────────
    print(f"\n[5/{total_stages}] Initializing economics engine...")
    economics = EconomicsLayer(config)
    economics.load_baselines(baselines)
    print(f"  Baselines loaded for {len(baselines)} segments")

    # ── Stage 6: Optimization ───────────────────────────────────────
    print(f"\n[6/{total_stages}] Running allocation optimizer...")
    optimizer = OptimizerLayer(config)
    results = optimizer.optimize(
        targets=targets,
        base_data=df_clean,
        economics_engine=economics,
        capacity=capacity,
    )
    opt_summary = optimizer.get_optimization_summary(results)
    enriched = build_enriched_summary(opt_summary, capacity, results)
    total_bookings = enriched["total_bookings"]
    total_saos = enriched["total_saos"]
    print(f"  {len(results)} allocation rows")
    print(f"  Projected bookings: ${total_bookings:,.0f}")

    # ── Stage 7: Validation ─────────────────────────────────────────
    print(f"\n[7/{total_stages}] Validating results...")
    validator = ValidationLayer(config)
    validation = validator.validate(results, targets=targets, capacity=capacity)
    overall_pass = validation.get("passed", False) if isinstance(validation, dict) else False
    print(f"  Validation: {'PASS' if overall_pass else 'FAIL'}")

    # ── Stage 8: Recovery analysis ──────────────────────────────────
    print(f"\n[8/{total_stages}] Running recovery analysis...")
    recovery_engine = RecoveryLayer(config)
    targets_r, capacity_r = prepare_recovery_inputs(targets, capacity)
    recovery_analysis = recovery_engine.analyze(results, targets_r, capacity_r)
    if isinstance(recovery_analysis, dict):
        print(f"  Risk: {recovery_analysis.get('risk_assessment', 'N/A')}")

    # ── Save version ────────────────────────────────────────────────
    print("\n" + "-" * 70)
    print("Saving version...")

    summary_dict = sanitize_summary(enriched)
    store = VersionStoreLayer(config)
    version_id = store.save(
        config_snapshot=config.to_dict(),
        results=results,
        summary=summary_dict,
        description=args.description or "Pipeline run",
        planning_mode=config.get("targets.planning_mode", "full_year"),
    )

    version_dir = Path(config.get("system.output_dir", "versions")) / f"v{version_id:03d}"

    # ── Write intermediate files ────────────────────────────────────
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

    lever_engine = LeverAnalysisLayer(config.to_dict())
    lever_report = lever_engine.analyze(results, capacity, targets, baselines)
    _save_lever_analysis_outputs(version_dir, lever_engine, lever_report)

    cash_cycle_cfg = config.get("economics.cash_cycle", {})
    cash_cycle_enabled = (
        isinstance(cash_cycle_cfg, dict) and cash_cycle_cfg.get("enabled", False)
    )
    if cash_cycle_enabled:
        waterfall_cc = build_cashcycle_waterfall(results, economics, config)
        waterfall_cc.to_csv(version_dir / "cashcycle_waterfall.csv", index=False)

    # ── Final summary ───────────────────────────────────────────────
    _print_final_summary(
        version_id, version_dir, targets, total_bookings, total_saos,
        overall_pass, results, cash_cycle_enabled,
    )


def run_adjustment_mode(args: argparse.Namespace, config: GTMConfig, project_root: Path) -> None:
    """Load a version, apply mid-cycle adjustments, re-run, and compare."""
    if args.base_version is None:
        print("ERROR: --base-version is required for adjustment mode.")
        sys.exit(1)

    store = VersionStoreLayer(config)
    data_path = str(project_root / "data" / "raw" / "2025_actuals.csv")

    # ── Load base version ───────────────────────────────────────────
    print(f"\nLoading base version v{args.base_version:03d}...")
    base = store.load(args.base_version)
    base_results = alias_columns_for_adjustment(base["results"])
    base_summary = normalize_saved_summary(base["summary"])

    # ── Parse adjustment inputs ─────────────────────────────────────
    actuals = None
    if args.actuals_file:
        print(f"  Loading actuals from {args.actuals_file}...")
        actuals = pd.read_csv(args.actuals_file)

    hc_changes = json.loads(args.hc_changes) if args.hc_changes else None
    target_changes = json.loads(args.target_changes) if args.target_changes else None
    segment_changes = json.loads(args.segment_changes) if args.segment_changes else None

    # ── Apply adjustments ───────────────────────────────────────────
    print("\nApplying adjustments...")
    adj_engine = AdjustmentLayer(config.to_dict())
    adj_result = adj_engine.apply_adjustment(
        current_plan=base_results,
        actuals=actuals,
        hc_changes=hc_changes,
        target_changes=target_changes,
        segment_changes=segment_changes,
    )

    print(f"  Locked periods: {adj_result['locked_periods']}")
    print(f"  Locked revenue: ${adj_result['locked_revenue']:,.0f}")
    print(f"  Remaining target: ${adj_result['remaining_target']:,.0f}")

    # ── Re-run pipeline with adjusted config ────────────────────────
    print("\nRe-running pipeline with adjusted config...")
    adjusted_config = GTMConfig.from_dict(adj_result["adjusted_config"])

    loader = DataLayer(adjusted_config)
    df_raw = loader.load(data_path)
    df_clean = loader.prepare(df_raw)
    baselines = loader.compute_segment_baselines(df_clean)

    target_gen = TargetLayer(adjusted_config)
    targets = target_gen.generate()

    ae_model = CapacityLayer(adjusted_config)
    capacity = ae_model.calculate()

    economics = EconomicsLayer(adjusted_config)
    economics.load_baselines(baselines)

    optimizer = OptimizerLayer(adjusted_config)
    results = optimizer.optimize(
        targets=targets,
        base_data=df_clean,
        economics_engine=economics,
        capacity=capacity,
    )
    opt_summary = optimizer.get_optimization_summary(results)
    enriched = build_enriched_summary(opt_summary, capacity, results)

    # ── Validate and recover ────────────────────────────────────────
    validator = ValidationLayer(adjusted_config)
    validation = validator.validate(results, targets=targets, capacity=capacity)
    overall_pass = validation.get("passed", False) if isinstance(validation, dict) else False
    print(f"  Validation: {'PASS' if overall_pass else 'FAIL'}")

    recovery_engine = RecoveryLayer(adjusted_config)
    targets_r, capacity_r = prepare_recovery_inputs(targets, capacity)
    recovery_analysis = recovery_engine.analyze(results, targets_r, capacity_r)

    # ── Save new version ────────────────────────────────────────────
    summary_dict = sanitize_summary(enriched)
    version_id = store.save(
        config_snapshot=adjusted_config.to_dict(),
        results=results,
        summary=summary_dict,
        description=args.description or f"Mid-cycle adjustment from v{args.base_version:03d}",
        planning_mode=adjusted_config.get("targets.planning_mode", "full_year"),
    )
    version_dir = Path(config.get("system.output_dir", "versions")) / f"v{version_id:03d}"

    targets.to_csv(version_dir / "targets.csv", index=False)
    capacity.to_csv(version_dir / "ae_capacity.csv", index=False)

    with open(version_dir / "adjustment_summary.txt", "w") as f:
        f.write(adj_result["adjustment_summary"])

    with open(version_dir / "adjustment_metadata.json", "w") as f:
        json.dump({
            "base_version": args.base_version,
            "locked_periods": adj_result["locked_periods"],
            "remaining_target": adj_result["remaining_target"],
            "locked_revenue": adj_result["locked_revenue"],
            "changes_applied": adj_result["changes_applied"],
        }, f, indent=2, default=json_safe)

    with open(version_dir / "validation_report.json", "w") as f:
        json.dump(validation, f, indent=2, default=json_safe)

    with open(version_dir / "recovery_analysis.json", "w") as f:
        json.dump(recovery_analysis, f, indent=2, default=json_safe)

    waterfall = build_monthly_waterfall(targets, capacity, results)
    waterfall.to_csv(version_dir / "monthly_waterfall.csv", index=False)

    # ── Compare base vs adjusted ────────────────────────────────────
    print("\nComparing base vs adjusted plan...")
    comparator = ComparatorLayer(config.to_dict())
    versions_for_compare = [
        {"version_id": f"v{args.base_version:03d}", "results": base["results"], "summary": base_summary},
        {"version_id": f"v{version_id:03d}", "results": results, "summary": summary_dict},
    ]
    comparison = comparator.compare(versions_for_compare)

    with open(version_dir / "comparison_vs_base.json", "w") as f:
        serializable = {}
        for k, v in comparison.items():
            if isinstance(v, pd.DataFrame):
                serializable[k] = v.to_dict(orient="records")
            else:
                serializable[k] = v
        json.dump(serializable, f, indent=2, default=json_safe)

    print(f"\nVersion {version_id} saved to {version_dir}/")
    print(f"  Adjustment narrative: adjustment_summary.txt")
    print(f"  Comparison vs base:   comparison_vs_base.json")


def run_whatif_mode(args: argparse.Namespace, config: GTMConfig, project_root: Path) -> None:
    """Run base pipeline + what-if scenario analysis."""
    data_path = str(project_root / "data" / "raw" / "2025_actuals.csv")

    if args.base_version is not None:
        print(f"\nLoading base version v{args.base_version:03d}...")
        store = VersionStoreLayer(config)
        base = store.load(args.base_version)
        base_results = base["results"]
        base_summary = normalize_saved_summary(base["summary"])
    else:
        print("\nRunning base pipeline...")
        pipeline_fn = make_pipeline_fn(project_root, data_path)
        base_results, base_summary = pipeline_fn(config.to_dict())
        print(f"  Base bookings: ${base_summary['total_bookings']:,.0f}")

    config_dict = config.to_dict()
    scenarios = config_dict.get("what_if_scenarios", [])

    if args.enable_scenarios:
        names_to_enable = args.enable_scenarios
        for scenario in scenarios:
            if "all" in names_to_enable or scenario["name"] in names_to_enable:
                scenario["enabled"] = True
        config_dict["what_if_scenarios"] = scenarios

    enabled_names = [s["name"] for s in scenarios if s.get("enabled", True)]
    if not enabled_names:
        print("ERROR: No scenarios are enabled. Use --enable-scenarios to enable scenarios.")
        print("  Available scenarios:")
        for s in scenarios:
            print(f"    - \"{s['name']}\"")
        sys.exit(1)

    print(f"\nEnabled scenarios ({len(enabled_names)}):")
    for name in enabled_names:
        print(f"  - {name}")

    pipeline_fn = make_pipeline_fn(project_root, data_path)
    whatif_engine = WhatIfLayer(config_dict)
    print("\nRunning scenarios...")
    comparison_df = whatif_engine.run_scenarios(base_results, base_summary, pipeline_fn)

    # ── Save outputs ────────────────────────────────────────────────
    store = VersionStoreLayer(config)
    version_id = store.save(
        config_snapshot=config_dict,
        results=base_results,
        summary=sanitize_summary(base_summary),
        description=args.description or "What-if scenario analysis",
        planning_mode=config.get("targets.planning_mode", "full_year"),
    )
    version_dir = Path(config.get("system.output_dir", "versions")) / f"v{version_id:03d}"

    if isinstance(comparison_df, pd.DataFrame):
        comparison_df.to_csv(version_dir / "what_if_comparison.csv", index=False)
    elif isinstance(comparison_df, list):
        pd.DataFrame([c.to_dict() if hasattr(c, 'to_dict') else c for c in comparison_df]).to_csv(
            version_dir / "what_if_comparison.csv", index=False
        )

    for scenario_name in enabled_names:
        safe_name = scenario_name.replace(" ", "_").replace("/", "_").lower()
        try:
            details = whatif_engine.get_scenario_details(scenario_name)
            details["results"].to_csv(
                version_dir / f"what_if_scenario_{safe_name}.csv", index=False,
            )
            with open(version_dir / f"what_if_scenario_{safe_name}_summary.json", "w") as f:
                json.dump(details["summary"], f, indent=2, default=json_safe)
        except KeyError:
            pass

    print(f"\nWhat-if analysis saved to {version_dir}/")
    print(f"  what_if_comparison.csv         Scenario comparison table")
    for name in enabled_names:
        safe = name.replace(" ", "_").replace("/", "_").lower()
        print(f"  what_if_scenario_{safe}.csv     {name} results")


def run_compare_mode(args: argparse.Namespace, config: GTMConfig, project_root: Path) -> None:
    """Compare 2+ existing plan versions."""
    if not args.compare_versions or len(args.compare_versions) < 2:
        print("ERROR: --compare-versions requires at least 2 version IDs.")
        sys.exit(1)

    store = VersionStoreLayer(config)

    versions_for_compare = []
    for vid in args.compare_versions:
        print(f"  Loading v{vid:03d}...")
        loaded = store.load(vid)
        versions_for_compare.append({
            "version_id": f"v{vid:03d}",
            "results": loaded["results"],
            "summary": normalize_saved_summary(loaded["summary"]),
        })

    print(f"\nComparing {len(versions_for_compare)} versions...")
    comparator = ComparatorLayer(config.to_dict())
    comparison = comparator.compare(versions_for_compare)

    output_dir = Path(config.get("system.output_dir", "versions"))
    compare_dir = output_dir / "comparisons"
    compare_dir.mkdir(parents=True, exist_ok=True)

    version_label = "_vs_".join(f"v{v:03d}" for v in args.compare_versions)

    metric_diffs = comparison.get("metric_diffs", pd.DataFrame())
    if not isinstance(metric_diffs, pd.DataFrame):
        metric_diffs = pd.DataFrame()
    if not metric_diffs.empty:
        metric_diffs.to_csv(compare_dir / f"comparison_{version_label}_metrics.csv", index=False)

    alloc_shift = comparison.get("allocation_shift", pd.DataFrame())
    if not isinstance(alloc_shift, pd.DataFrame):
        alloc_shift = pd.DataFrame()
    if not alloc_shift.empty:
        alloc_shift.to_csv(compare_dir / f"comparison_{version_label}_allocation_shift.csv", index=False)

    serializable = {}
    for k, v in comparison.items():
        if isinstance(v, pd.DataFrame):
            serializable[k] = v.to_dict(orient="records")
        else:
            serializable[k] = v
    with open(compare_dir / f"comparison_{version_label}_report.json", "w") as f:
        json.dump(serializable, f, indent=2, default=json_safe)

    print(f"\nComparison saved to {compare_dir}/")
    print(f"  comparison_{version_label}_metrics.csv")
    print(f"  comparison_{version_label}_allocation_shift.csv")
    print(f"  comparison_{version_label}_report.json")


def run_recommend_mode(args: argparse.Namespace, config: GTMConfig, project_root: Path) -> None:
    """Run lever sensitivity analysis and produce plain-language recommendations."""
    data_path = str(project_root / "data" / "raw" / "2025_actuals.csv")

    print("\nBuilding capacity model and segment baselines...")
    loader = DataLayer(config)
    df_raw = loader.load(data_path)
    df_clean = loader.prepare(df_raw)
    baselines = loader.compute_segment_baselines(df_clean)

    target_gen = TargetLayer(config)
    targets = target_gen.generate()

    ae_model = CapacityLayer(config)
    capacity = ae_model.calculate()

    economics = EconomicsLayer(config)
    economics.load_baselines(baselines)

    if args.base_version is not None:
        print(f"\nLoading base results from v{args.base_version:03d}...")
        store = VersionStoreLayer(config)
        base = store.load(args.base_version)
        base_results = base["results"]
        base_summary = normalize_saved_summary(base["summary"])
        targets_path = Path(config.get("system.output_dir", "versions")) / f"v{args.base_version:03d}" / "targets.csv"
        if targets_path.exists():
            targets = pd.read_csv(targets_path)
        print(f"  Base bookings: ${base_results['projected_bookings'].sum():,.0f}")
    else:
        print("\nRunning optimizer to get base allocation...")
        optimizer = OptimizerLayer(config)
        base_results = optimizer.optimize(
            targets=targets,
            base_data=df_clean,
            economics_engine=economics,
            capacity=capacity,
        )
        opt_summary = optimizer.get_optimization_summary(base_results)
        base_summary = build_enriched_summary(opt_summary, capacity, base_results)
        print(f"  Base bookings: ${base_summary['total_bookings']:,.0f}")

    config_dict = config.to_dict()
    print("\nRunning analytical lever sensitivity analysis...")
    lever_engine = LeverAnalysisLayer(config_dict)
    report = lever_engine.analyze(base_results, capacity, targets, baselines)

    print()
    lever_engine.print_recommendations(report)

    store = VersionStoreLayer(config)
    version_id = store.save(
        config_snapshot=config_dict,
        results=base_results,
        summary=sanitize_summary(base_summary),
        description=args.description or "Lever analysis recommendations",
        planning_mode=config.get("targets.planning_mode", "full_year"),
    )
    version_dir = Path(config.get("system.output_dir", "versions")) / f"v{version_id:03d}"
    _save_lever_analysis_outputs(version_dir, lever_engine, report)

    print(f"\nLever analysis saved to {version_dir}/")
    print(f"  lever_analysis.csv            Ranked lever impact table")
    print(f"  lever_recommendations.txt     Plain-language narrative")
    print(f"  lever_analysis_report.json    Summary metrics")


# ── Helpers ─────────────────────────────────────────────────────────


def _print_final_summary(
    version_id: int,
    version_dir: Path,
    targets: pd.DataFrame,
    total_bookings: float,
    total_saos: float,
    overall_pass: bool,
    results: pd.DataFrame,
    cash_cycle_enabled: bool,
) -> None:
    """Print the final pipeline summary to stdout."""
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
    print(f"    lever_analysis.csv       Ranked lever impact table")
    print(f"    lever_recommendations.txt Plain-language narrative")
    print(f"    lever_analysis_report.json Summary metrics")
    if cash_cycle_enabled:
        print(f"    cashcycle_waterfall.csv   Cash cycle booking realization waterfall")

    print(f"\n  Key Metrics:")
    print(f"    Annual target:       ${targets['target_revenue'].sum():,.0f}")
    print(f"    Projected bookings:  ${total_bookings:,.0f}")
    print(f"    Total SAOs:          {total_saos:,.0f}")
    print(f"    Validation:          {'PASS' if overall_pass else 'FAIL'}")

    if "in_window_bookings" in results.columns and cash_cycle_enabled:
        in_window_total = results["in_window_bookings"].sum()
        deferred_total = results["deferred_bookings"].sum()
        in_window_pct = in_window_total / total_bookings * 100 if total_bookings > 0 else 0
        print(f"\n  Cash Cycle:")
        print(f"    In-window bookings:  ${in_window_total:,.0f} ({in_window_pct:.1f}%)")
        print(f"    Deferred bookings:   ${deferred_total:,.0f} ({100 - in_window_pct:.1f}%)")

    print("\n" + "=" * 70)
    print("PIPELINE COMPLETE")
    print("=" * 70)


def _build_lever_analysis_report_json(report: dict) -> dict:
    annual_target = report["annual_target"]
    gap = report["gap"]
    return {
        "gap": gap,
        "gap_pct": round(gap / annual_target * 100, 2) if annual_target else 0,
        "annual_target": annual_target,
        "actual_bookings": report["actual_bookings"],
        "sao_shadow_price": report["sao_shadow_price"],
    }


def _save_lever_analysis_outputs(
    version_dir: Path,
    lever_engine: LeverAnalysisLayer,
    report: dict,
) -> None:
    lever_df = lever_engine.to_dataframe(report)
    lever_df.to_csv(version_dir / "lever_analysis.csv", index=False)

    with open(version_dir / "lever_recommendations.txt", "w") as f:
        f.write(report["recommendations_text"])

    report_json = _build_lever_analysis_report_json(report)
    with open(version_dir / "lever_analysis_report.json", "w") as f:
        json.dump(report_json, f, indent=2, default=json_safe)


# ── Main entry point ───────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the GTM Planning Engine pipeline (monolith)")
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML (default: config.yaml)")
    parser.add_argument("--description", default="", help="Version description label")

    parser.add_argument(
        "--mode",
        choices=["full", "adjustment", "what-if", "compare", "recommend"],
        default="full",
        help="Execution mode (default: full)",
    )

    parser.add_argument("--base-version", type=int, default=None, help="Base version ID for adjustment or what-if mode")
    parser.add_argument("--actuals-file", default=None, help="Path to actuals CSV for adjustment mode")
    parser.add_argument("--hc-changes", default=None, help='JSON string of HC changes, e.g. \'{"month_5": -3}\'')
    parser.add_argument("--target-changes", default=None, help='JSON string of target changes, e.g. \'{"annual_target": 195000000}\'')
    parser.add_argument("--segment-changes", default=None, help='JSON string of segment changes, e.g. \'{"EOR.asp": 12000}\'')
    parser.add_argument("--enable-scenarios", nargs="+", default=None, help='Scenario names to enable, or "all"')
    parser.add_argument("--compare-versions", type=int, nargs="+", default=None, help="Version IDs to compare (2+ required)")

    args = parser.parse_args()

    project_root = Path(__file__).parent.parent
    config_path = str(project_root / args.config)

    print("=" * 70)
    print("GTM PLANNING ENGINE — FULL PIPELINE RUN (MONOLITH)")
    print("=" * 70)

    # ── Stage 1: Configuration ──────────────────────────────────────
    print(f"\n[1] Loading configuration...")
    config = GTMConfig(config_path)
    print(f"  Annual target: ${config.get('targets.annual_target'):,.0f}")
    print(f"  Planning mode: {config.get('targets.planning_mode')}")
    print(f"  Optimizer: {config.get('allocation.optimizer_mode', 'greedy')}")
    print(f"  Mode: {args.mode}")

    # ── Dispatch to mode ────────────────────────────────────────────
    if args.mode == "full":
        run_full_mode(args, config, project_root)
    elif args.mode == "adjustment":
        run_adjustment_mode(args, config, project_root)
    elif args.mode == "what-if":
        run_whatif_mode(args, config, project_root)
    elif args.mode == "compare":
        run_compare_mode(args, config, project_root)
    elif args.mode == "recommend":
        run_recommend_mode(args, config, project_root)


if __name__ == "__main__":
    main()
