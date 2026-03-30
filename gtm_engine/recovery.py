"""
Recovery & Rebalancing Engine (Module 7)

Purpose:
    Handle quarterly target misses and model recovery options. When actual or
    projected quarterly bookings fall short of targets, this module redistributes
    the shortfall across remaining quarters and alerts on feasibility.

Key capabilities:
    - Compare quarterly projections to quarterly targets
    - Redistribute shortfalls weighted by capacity
    - Flag "stretch" quarters that exceed safe limits (e.g., >120% of plan)
    - Model mentoring relief options to free up capacity
    - Identify the recovery quarter (when cumulative trajectory normalizes)

Data flow:
    Allocation Results → Recovery Engine → Recovery Plan + Stretch Flags + Mentoring Analysis

Author: GTM Planning Engine
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Any


class RecoveryEngine:
    """
    Engine for quarterly recovery planning and rebalancing.

    This module analyzes quarterly performance, identifies shortfalls, and proposes
    recovery strategies. It helps leadership understand the feasibility of hitting
    annual targets and where to focus capacity gains.

    Workflow:
        1. Ingest quarterly allocation results and targets
        2. Calculate quarterly gaps (actual vs projected)
        3. If shortfall exists, redistribute it across remaining quarters weighted by capacity
        4. Flag quarters where rebalanced targets exceed stretch_threshold
        5. Model mentoring relief as an alternative capacity-freeing lever
        6. Identify the recovery quarter (when cumulative bookings catch up to trajectory)
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Recovery Engine with config parameters.

        Args:
            config: Dict-like config object with .get(key, default) method.
                   Must contain:
                   - ae_model.stretch_threshold: float (default 1.20 = 120%)
                   - ae_model.mentoring.overhead_pct_per_new_hire: float
                   - system.tolerance: float (for numeric comparisons)
        """
        self.config = config
        self.stretch_threshold = config.get("ae_model.stretch_threshold", 1.20)
        self.mentoring_overhead = config.get("ae_model.mentoring.overhead_pct_per_new_hire", 0.10)
        self.tolerance = config.get("system.tolerance", 0.001)

    def analyze(
        self,
        allocation_results: pd.DataFrame,
        targets: pd.DataFrame,
        capacity: pd.DataFrame = None,
    ) -> Dict[str, Any]:
        """
        Analyze quarterly performance vs targets and produce recovery plan.

        High-level flow:
            1. Calculate quarterly gaps (target vs projected bookings)
            2. If cumulative shortfall exists, redistribute across remaining quarters
            3. Check for stretch violations (adjusted > stretch_threshold × original)
            4. Model mentoring relief to free capacity
            5. Find recovery quarter

        Args:
            allocation_results: DataFrame with columns [period, projected_bookings, ...]
                               One row per period (month or quarter).
            targets: DataFrame with columns [period, target_bookings].
            capacity: Optional. DataFrame with columns [quarter, effective_capacity].
                     If provided, used for weighting redistribution.

        Returns:
            Dict with keys:
                - quarterly_summary: DataFrame [quarter, target, projected, gap, gap_pct]
                - recovery_plan: DataFrame showing redistributed targets
                - stretch_flags: List of quarters where adjusted/original > stretch_threshold
                - risk_assessment: String summary of annual target risk
                - mentoring_relief: Dict with capacity analysis
                - recovery_quarter: Int (quarter number when cumulative catches up)

        Raises:
            ValueError: If required columns missing or data incompatible.
        """
        # Validate inputs
        self._validate_inputs(allocation_results, targets)

        # Calculate quarterly gaps
        quarterly_gaps = self._calculate_quarterly_gaps(allocation_results, targets)

        # Determine if there's a shortfall to redistribute
        cumulative_projected = quarterly_gaps["projected"].sum()
        cumulative_target = quarterly_gaps["target"].sum()
        total_shortfall = max(0, cumulative_target - cumulative_projected)

        # Initialize recovery plan (copy of original targets)
        recovery_plan = quarterly_gaps[["quarter", "target"]].copy()
        recovery_plan.columns = ["quarter", "adjusted_target"]
        stretch_flags = []
        mentoring_relief = {}

        if total_shortfall > self.tolerance:
            # Identify remaining quarters (those with shortfall)
            gap_month = self._find_first_miss_month(quarterly_gaps)
            remaining_quarters = quarterly_gaps[quarterly_gaps["quarter"] >= gap_month]["quarter"].tolist()

            # Redistribute shortfall
            redistributed = self._redistribute_shortfall(
                total_shortfall,
                remaining_quarters,
                capacity,
                quarterly_gaps
            )
            recovery_plan["adjusted_target"] = quarterly_gaps["target"].values
            for q, adjustment in redistributed.items():
                if q in recovery_plan["quarter"].values:
                    idx = recovery_plan[recovery_plan["quarter"] == q].index[0]
                    recovery_plan.loc[idx, "adjusted_target"] += adjustment

            # Check for stretch violations
            stretch_flags = self._check_stretch(
                quarterly_gaps["target"].values,
                recovery_plan["adjusted_target"].values,
                quarterly_gaps["quarter"].tolist()
            )

            # Analyze mentoring relief
            mentoring_relief = self._analyze_mentoring_relief(capacity, gap_month)

        # Find recovery quarter
        recovery_quarter = self.find_recovery_quarter(quarterly_gaps, recovery_plan)

        # Build risk assessment narrative
        risk_assessment = self._build_risk_assessment(
            total_shortfall,
            cumulative_target,
            stretch_flags,
            recovery_quarter
        )

        return {
            "quarterly_summary": quarterly_gaps,
            "recovery_plan": recovery_plan,
            "stretch_flags": stretch_flags,
            "risk_assessment": risk_assessment,
            "mentoring_relief": mentoring_relief,
            "recovery_quarter": recovery_quarter,
        }

    def _validate_inputs(
        self,
        allocation_results: pd.DataFrame,
        targets: pd.DataFrame,
    ) -> None:
        """
        Validate that required columns exist and data is compatible.

        Args:
            allocation_results: Must have 'period' and 'projected_bookings'.
            targets: Must have 'period' and 'target_bookings'.

        Raises:
            ValueError if validation fails.
        """
        required_cols_alloc = {"period", "projected_bookings"}
        required_cols_target = {"period", "target_bookings"}

        if not required_cols_alloc.issubset(allocation_results.columns):
            missing = required_cols_alloc - set(allocation_results.columns)
            raise ValueError(f"allocation_results missing columns: {missing}")

        if not required_cols_target.issubset(targets.columns):
            missing = required_cols_target - set(targets.columns)
            raise ValueError(f"targets missing columns: {missing}")

    def _calculate_quarterly_gaps(
        self,
        allocation_results: pd.DataFrame,
        targets: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Compare quarterly projected bookings to quarterly targets.

        If allocation_results is at monthly grain, aggregate to quarterly.
        Compute gap = target - projected, and gap_pct = gap / target.

        Args:
            allocation_results: DataFrame with period, projected_bookings columns.
            targets: DataFrame with period, target_bookings columns.

        Returns:
            DataFrame with columns:
            [quarter, target, projected, gap, gap_pct]
        """
        targets_by_period = (
            targets[["period", "target_bookings"]]
            .groupby("period", as_index=False)["target_bookings"]
            .sum()
        )

        allocation_by_period = (
            allocation_results
            .groupby("period", as_index=False)["projected_bookings"]
            .sum()
        )

        merged = pd.merge(
            targets_by_period,
            allocation_by_period,
            on="period",
            how="outer"
        )
        merged.fillna(0, inplace=True)

        # Infer quarter from period if not explicit
        # Assume period format is "month_N" or "quarter_N"
        def extract_quarter(period_val) -> int:
            """Convert period value (int month 1-12, or string 'month_N'/'quarter_N') to quarter number."""
            period_str = str(period_val).strip().lower()
            try:
                if period_str.startswith("quarter_"):
                    return int(period_str.split("_")[-1])
                elif period_str.startswith("month_"):
                    month = int(period_str.split("_")[-1])
                    return (month - 1) // 3 + 1
                else:
                    # Assume plain integer (e.g., 1-12 for months)
                    num = int(float(period_str))
                    return (num - 1) // 3 + 1
            except (ValueError, IndexError):
                raise ValueError(
                    f"Cannot extract quarter from period value: '{period_val}'. "
                    f"Expected an integer month (1-12), 'month_N', or 'quarter_N'."
                )

        merged["quarter"] = merged["period"].apply(extract_quarter)

        # Aggregate to quarterly
        quarterly = merged.groupby("quarter", as_index=False).agg({
            "target_bookings": "sum",
            "projected_bookings": "sum",
        })
        quarterly.columns = ["quarter", "target", "projected"]

        # Calculate gaps
        quarterly["gap"] = quarterly["target"] - quarterly["projected"]
        quarterly["gap_pct"] = quarterly["gap"] / quarterly["target"].replace(0, np.nan)

        return quarterly.sort_values("quarter").reset_index(drop=True)

    def _find_first_miss_month(self, quarterly_gaps: pd.DataFrame) -> int:
        """
        Find the first quarter with a shortfall (gap > tolerance).

        Args:
            quarterly_gaps: DataFrame with gap column.

        Returns:
            Int: quarter number of first miss, or max quarter if all on track.
        """
        misses = quarterly_gaps[quarterly_gaps["gap"] > self.tolerance]
        if len(misses) > 0:
            return misses.iloc[0]["quarter"]
        return quarterly_gaps["quarter"].max()

    def _redistribute_shortfall(
        self,
        shortfall: float,
        remaining_quarters: List[int],
        capacity: Optional[pd.DataFrame],
        quarterly_gaps: pd.DataFrame,
    ) -> Dict[int, float]:
        """
        Distribute shortfall across remaining quarters, weighted by capacity.

        Formula:
            Q_adjusted = Q_original + shortfall × (C_q / Σ C_remaining)

        If capacity not provided, uses equal weighting.

        Args:
            shortfall: Total revenue shortfall to redistribute ($).
            remaining_quarters: List of quarter numbers to redistribute into.
            capacity: Optional DataFrame with [quarter, effective_capacity].
            quarterly_gaps: The quarterly gaps DataFrame for context.

        Returns:
            Dict mapping {quarter: adjustment_amount}.
        """
        if not remaining_quarters:
            return {}

        adjustments = {}

        if capacity is not None and len(capacity) > 0:
            # Weight by capacity
            remaining_capacity = capacity[capacity["quarter"].isin(remaining_quarters)]
            if len(remaining_capacity) > 0:
                total_capacity = remaining_capacity["effective_capacity"].sum()
                for q in remaining_quarters:
                    cap_q = remaining_capacity[
                        remaining_capacity["quarter"] == q
                    ]["effective_capacity"].sum()
                    weight = cap_q / total_capacity if total_capacity > 0 else 1.0 / len(remaining_quarters)
                    adjustments[q] = shortfall * weight
            else:
                # Fallback to equal weighting
                equal_share = shortfall / len(remaining_quarters)
                for q in remaining_quarters:
                    adjustments[q] = equal_share
        else:
            # Equal weighting
            equal_share = shortfall / len(remaining_quarters)
            for q in remaining_quarters:
                adjustments[q] = equal_share

        return adjustments

    def _check_stretch(
        self,
        original_targets: np.ndarray,
        adjusted_targets: np.ndarray,
        quarters: List[int],
    ) -> List[Dict[str, Any]]:
        """
        Flag quarters where adjusted/original > stretch_threshold.

        Args:
            original_targets: Array of original quarterly targets.
            adjusted_targets: Array of adjusted (rebalanced) targets.
            quarters: List of quarter numbers.

        Returns:
            List of dicts: [{quarter: Q, original: $, adjusted: $, stretch_ratio: X}]
        """
        stretch_flags = []
        for i, q in enumerate(quarters):
            if original_targets[i] > 0:
                ratio = adjusted_targets[i] / original_targets[i]
                if ratio > self.stretch_threshold:
                    stretch_flags.append({
                        "quarter": q,
                        "original": original_targets[i],
                        "adjusted": adjusted_targets[i],
                        "stretch_ratio": ratio,
                    })
        return stretch_flags

    def _analyze_mentoring_relief(
        self,
        capacity: Optional[pd.DataFrame],
        gap_month: int,
    ) -> Dict[str, Any]:
        """
        Model: if mentoring overhead (A%) is reduced by X%, how much capacity is freed?
        Find break-even A% that closes the gap.

        This is a simplified model showing the "what if we reduced mentoring load" lever.

        Args:
            capacity: DataFrame with mentoring_overhead_pct column (if available).
            gap_month: The quarter/month where the miss occurs.

        Returns:
            Dict with keys:
            - current_mentoring_tax: Current overhead as % of capacity.
            - potential_relief: Estimated capacity that could be freed (%).
            - required_reduction: What % reduction in A would close the gap (%).
            - recommendation: String narrative.
        """
        analysis = {
            "current_mentoring_tax": self.mentoring_overhead,
            "potential_relief": self.mentoring_overhead * 0.5,  # Assume 50% of overhead is reducible
            "required_reduction": None,
            "recommendation": "Mentoring relief analysis pending capacity data.",
        }

        if capacity is not None and len(capacity) > 0:
            # Simplified: if we could cut mentoring overhead by 50%, we'd free ~5% capacity
            # This is illustrative; real calculation depends on active ramps
            analysis["potential_relief"] = self.mentoring_overhead * 0.5
            analysis["recommendation"] = (
                f"If mentoring overhead (currently {self.mentoring_overhead*100:.1f}%) "
                f"could be reduced by 50% (e.g., via external mentoring support), "
                f"approximately {analysis['potential_relief']*100:.1f}% capacity could be freed."
            )

        return analysis

    def find_recovery_quarter(
        self,
        quarterly_gaps: pd.DataFrame,
        recovery_plan: Optional[pd.DataFrame] = None,
    ) -> int:
        """
        Find the earliest quarter where cumulative bookings recover to annual trajectory.

        "Recovery" is defined as cumulative projected bookings >= cumulative target
        (i.e., cumulative gap flips from negative to non-negative).

        Args:
            quarterly_gaps: DataFrame with quarter, target, projected columns.
            recovery_plan: Optional recovery plan with adjusted targets.

        Returns:
            Int: Quarter number when cumulative catches up. If never, returns max quarter.
        """
        # Use recovery plan if provided, else original projections
        if recovery_plan is not None and "adjusted_target" in recovery_plan.columns:
            targets = recovery_plan.set_index("quarter")["adjusted_target"]
        else:
            targets = quarterly_gaps.set_index("quarter")["target"]

        projected = quarterly_gaps.set_index("quarter")["projected"]

        # Calculate cumulative gap
        cumulative_target = targets.cumsum()
        cumulative_projected = projected.cumsum()
        cumulative_gap = cumulative_target - cumulative_projected

        # Find first quarter where gap flips non-negative
        recovery_qs = cumulative_gap[cumulative_gap <= self.tolerance]
        if len(recovery_qs) > 0:
            return recovery_qs.index[0]

        # If never recovers, return last quarter
        return quarterly_gaps["quarter"].max()

    def _build_risk_assessment(
        self,
        total_shortfall: float,
        cumulative_target: float,
        stretch_flags: List[Dict],
        recovery_quarter: int,
    ) -> str:
        """
        Build a human-readable risk assessment narrative.

        Args:
            total_shortfall: Total annual revenue gap ($).
            cumulative_target: Annual target ($).
            stretch_flags: List of flagged quarters.
            recovery_quarter: Quarter when cumulative recovers.

        Returns:
            String narrative.
        """
        shortfall_pct = (total_shortfall / cumulative_target * 100) if cumulative_target > 0 else 0

        narrative = f"Annual Target Risk Assessment:\n"
        narrative += f"  Projected shortfall: ${total_shortfall:,.0f} ({shortfall_pct:.1f}% of target)\n"

        if total_shortfall <= 0:
            narrative += f"  Status: ON TRACK. No shortfall detected.\n"
        else:
            narrative += f"  Status: AT RISK. Requires rebalancing or recovery levers.\n"
            narrative += f"  Recovery quarter: Q{recovery_quarter}\n"

            if stretch_flags:
                narrative += f"  WARNING: {len(stretch_flags)} quarter(s) exceed stretch threshold (>{self.stretch_threshold*100:.0f}%):\n"
                for flag in stretch_flags:
                    stretch_pct = (flag["stretch_ratio"] - 1) * 100
                    narrative += (
                        f"    - Q{flag['quarter']}: adjusted to ${flag['adjusted']:,.0f} "
                        f"({stretch_pct:.1f}% above original)\n"
                    )

        return narrative
