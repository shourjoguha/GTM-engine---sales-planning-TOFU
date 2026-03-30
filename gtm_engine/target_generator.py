"""
Target Generator Module — Distribute annual revenue target across planning periods.

Purpose:
    This module breaks down the annual revenue target into period-level targets (monthly or
    quarterly) using configurable seasonality weights. It supports three planning modes:
    1. Full year: Distribute target across all 12 months
    2. Rolling forward: Lock completed months with actuals, redistribute remaining target
    3. Manual lock: Freeze specific months, redistribute across unlocked periods

Inputs:
    - config: Dictionary-like object with .get(key, default) interface. Must contain:
        * targets.target_source: "fixed" or "growth"
        * targets.annual_target: Fixed annual revenue target ($)
                            OR
            * targets.growth_rate: YoY growth rate (used if deriving target from prior year)
            * targets.prior_year_actuals: Prior year revenue (used if target_source="growth")
        * targets.period_type: "monthly" or "quarterly"
        * targets.seasonality_weights: Dict of weights by period (must sum to 1.0)
        * targets.planning_mode: "full_year", "rolling_forward", or "manual_lock"
        * targets.locked_months: List of months to freeze (for manual_lock mode)
    - actuals: Optional DataFrame with columns [period, revenue] for rolling_forward mode

Outputs:
    DataFrame with columns:
    - period: Month (1-12) or Quarter (1-4)
    - month: Month number (1-12) if period_type="monthly", null if quarterly
    - quarter: Quarter number (1-4) if aggregated
    - target_revenue: Dollar amount for the period

Key Calculations:
    1. Determine T_annual from config (either fixed or derived from growth rate)
    2. Distribute T_annual using seasonality weights
    3. If rolling_forward: merge actuals, lock completed periods, redistribute remaining
    4. If manual_lock: preserve locked months, redistribute across unlocked periods

Example:
    >>> config = {"targets.annual_target": 188_000_000, "targets.period_type": "monthly"}
    >>> gen = TargetGenerator(config)
    >>> targets_df = gen.generate()
    >>> print(targets_df.head())
      period  month  quarter  target_revenue
      1       1      1        10340000.0
      2       2      1        12220000.0
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, Any


class TargetGenerator:
    """
    Generate period-level revenue targets from annual target and seasonality weights.

    Supports three planning modes:
    - full_year: Distribute across all periods
    - rolling_forward: Lock completed periods with actuals, redistribute remainder
    - manual_lock: Freeze specific periods, redistribute across unlocked periods
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize with config manager.

        Args:
            config: Dictionary-like object with .get(key, default) interface
        """
        self.config = config
        self._annual_target = None #  variable is  unused 
        self._seasonality_weights = None  #  variable is unused 
        self._validate_config()

    def _validate_config(self) -> None:
        """
        Validate that required config keys are present and sensible.

        Raises:
            ValueError: If annual_target is invalid, seasonality weights don't sum to 1.0, etc.
        """
        # Check that we can derive annual target
        target_source = self.config.get("targets.target_source", "fixed")
        if target_source == "fixed":
            annual_target = self.config.get("targets.annual_target", None)
            if annual_target is None or annual_target <= 0:
                raise ValueError("targets.annual_target must be > 0 when target_source='fixed'")
        elif target_source == "growth":
            prior_year = self.config.get("targets.prior_year_actuals", None)
            growth_rate = self.config.get("targets.growth_rate", 0)
            if prior_year is None or prior_year <= 0:
                raise ValueError("targets.prior_year_actuals must be > 0 when target_source='growth'")
        else:
            raise ValueError(f"targets.target_source must be 'fixed' or 'growth', got {target_source}")

        # Check period type
        period_type = self.config.get("targets.period_type", "monthly")
        if period_type not in ("monthly", "quarterly"):
            raise ValueError(f"targets.period_type must be 'monthly' or 'quarterly', got {period_type}")

        # Check planning mode
        planning_mode = self.config.get("targets.planning_mode", "full_year")
        if planning_mode not in ("full_year", "rolling_forward", "manual_lock"):
            raise ValueError(f"targets.planning_mode must be one of full_year/rolling_forward/manual_lock, got {planning_mode}")

    def _compute_annual_target(self) -> float:
        """
        Compute the annual target from config.

        Returns either the fixed target or derives it from prior year × (1 + growth_rate).

        Returns:
            float: Annual revenue target in dollars
        """
        target_source = self.config.get("targets.target_source", "fixed")

        if target_source == "fixed":
            return float(self.config.get("targets.annual_target"))
        else:
            # Derive from prior year actuals and growth rate
            prior_year = float(self.config.get("targets.prior_year_actuals"))
            growth_rate = float(self.config.get("targets.growth_rate", 0))
            return prior_year * (1 + growth_rate)

    def _get_seasonality_weights(self) -> Dict[int, float]:
        """
        Retrieve and validate seasonality weights from config.

        Returns a dict keyed by month (1-12) or quarter (1-4) with normalized weights
        that sum to 1.0.

        Returns:
            dict: {period_number: weight, ...} normalized to sum to 1.0

        Raises:
            ValueError: If weights are missing or invalid
        """
        period_type = self.config.get("targets.period_type", "monthly")
        weights = {}

        if period_type == "monthly":
            # Load monthly weights from config
            for month in range(1, 13):
                key = f"targets.seasonality_weights.month_{month}"
                weight = self.config.get(key, None)
                if weight is None:
                    raise ValueError(f"Missing seasonality weight for {key}")
                weights[month] = float(weight)
        else:
            # For quarterly mode: aggregate monthly weights into quarterly
            # We'll compute this on-the-fly when needed
            for month in range(1, 13):
                key = f"targets.seasonality_weights.month_{month}"
                weight = self.config.get(key, None)
                if weight is None:
                    raise ValueError(f"Missing seasonality weight for {key}")
                # Map month to quarter
                quarter = (month - 1) // 3 + 1
                weights[quarter] = weights.get(quarter, 0) + float(weight)

        # Validate that weights sum to 1.0 (with small tolerance for float rounding)
        total = sum(weights.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Seasonality weights sum to {total}, expected 1.0")

        # Normalize to exactly 1.0
        return {k: v / total for k, v in weights.items()}

    def generate(self, actuals: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        """
        Generate period-level targets for the planning year.

        Logic:
        1. Determine annual target (fixed or from growth rate)
        2. If period_type = "monthly":
           - Apply seasonality_weights to distribute annual target across months
        3. If period_type = "quarterly":
           - Aggregate seasonality weights into quarterly, distribute
        4. If planning_mode = "rolling_forward" and actuals provided:
           - Lock completed periods to actuals
           - Compute remaining target = annual - sum(actuals)
           - Redistribute remaining across unlocked periods (preserving relative weights)
        5. If planning_mode = "manual_lock":
           - Preserve locked periods at original target
           - Redistribute remaining target across unlocked periods

        Args:
            actuals: Optional DataFrame with columns [period, revenue] for rolling_forward mode

        Returns:
            DataFrame with columns [period, month, quarter, target_revenue]
            - period: 1-12 for monthly, 1-4 for quarterly
            - month: Month number 1-12 (null for quarterly)
            - quarter: Quarter 1-4 (null for monthly)
            - target_revenue: Dollar target for period
        """
        # Step 1: Compute annual target
        annual_target = self._compute_annual_target()

        # Step 2: Get seasonality weights for the period type
        seasonality_weights = self._get_seasonality_weights()
        period_type = self.config.get("targets.period_type", "monthly")

        # Step 3: Build base targets dataframe
        if period_type == "monthly":
            base_targets = self._build_monthly_targets(annual_target, seasonality_weights)
        else:
            base_targets = self._build_quarterly_targets(annual_target, seasonality_weights)

        # Step 4: Apply planning mode adjustments
        planning_mode = self.config.get("targets.planning_mode", "full_year")

        if planning_mode == "rolling_forward" and actuals is not None:
            targets = self._apply_rolling_forward(base_targets, actuals)
        elif planning_mode == "manual_lock":
            targets = self._apply_manual_locks(base_targets)
        else:
            # full_year mode: use base targets as-is
            targets = base_targets.copy()

        return targets

    def _build_monthly_targets(self, annual_target: float, weights: Dict[int, float]) -> pd.DataFrame:
        """
        Build base monthly targets using seasonality weights.

        Args:
            annual_target: Total annual revenue target ($)
            weights: Dict {month_number: weight} for 12 months

        Returns:
            DataFrame with columns [period, month, quarter, target_revenue]
        """
        rows = []
        for month in range(1, 13):
            weight = weights[month]
            target_revenue = annual_target * weight
            quarter = (month - 1) // 3 + 1

            rows.append({
                "period": month,
                "month": month,
                "quarter": quarter,
                "target_revenue": target_revenue
            })

        return pd.DataFrame(rows)

    def _build_quarterly_targets(self, annual_target: float, weights: Dict[int, float]) -> pd.DataFrame:
        """
        Build base quarterly targets using aggregated seasonality weights.

        Args:
            annual_target: Total annual revenue target ($)
            weights: Dict {quarter_number: weight} for 4 quarters

        Returns:
            DataFrame with columns [period, month, quarter, target_revenue]
        """
        rows = []
        for quarter in range(1, 5):
            weight = weights.get(quarter, 0)
            target_revenue = annual_target * weight

            rows.append({
                "period": quarter,
                "month": None,
                "quarter": quarter,
                "target_revenue": target_revenue
            })

        return pd.DataFrame(rows)

    def _apply_rolling_forward(self, base_targets: pd.DataFrame,
                                actuals: pd.DataFrame) -> pd.DataFrame:
        """
        Apply rolling_forward mode: lock completed months with actuals, redistribute remainder.

        Logic:
        1. Merge actuals into base targets on period
        2. Identify locked periods (those with actuals) and unlocked periods
        3. Compute remaining target = annual - sum(actuals for locked periods)
        4. Redistribute remaining target across unlocked periods using their relative weights

        Args:
            base_targets: DataFrame with [period, month, quarter, target_revenue]
            actuals: DataFrame with [period, revenue] for locked periods

        Returns:
            DataFrame with [period, month, quarter, target_revenue] where locked periods
            show actuals and unlocked periods show redistributed targets
        """
        result = base_targets.copy()

        # Merge actuals on 'period' column
        if not actuals.empty:
            actuals_renamed = actuals.rename(columns={"revenue": "actual_revenue"})
            result = result.merge(actuals_renamed[["period", "actual_revenue"]],
                                  on="period", how="left")

            # Sum of actuals for locked periods
            sum_actuals = result["actual_revenue"].sum()

            # Annual target (sum all base targets)
            annual_target = result["target_revenue"].sum()

            # Remaining target to redistribute
            remaining_target = annual_target - sum_actuals

            # Identify unlocked periods and their base weights
            unlocked_mask = result["actual_revenue"].isna()
            unlocked_targets = result.loc[unlocked_mask, "target_revenue"]
            sum_unlocked_targets = unlocked_targets.sum()

            # Redistribute remaining target proportionally across unlocked periods
            if sum_unlocked_targets > 0 and remaining_target >= 0:
                # Apply proportional scaling to unlocked periods
                scale_factor = remaining_target / sum_unlocked_targets
                result.loc[unlocked_mask, "target_revenue"] = (
                    result.loc[unlocked_mask, "target_revenue"] * scale_factor
                )

            # For locked periods, use actuals
            result.loc[~unlocked_mask, "target_revenue"] = result.loc[~unlocked_mask, "actual_revenue"]

            # Drop the temporary actual_revenue column
            result = result.drop(columns=["actual_revenue"])

        return result

    def _apply_manual_locks(self, base_targets: pd.DataFrame) -> pd.DataFrame:
        """
        Apply manual_lock mode: freeze specified periods, redistribute across unlocked.

        Logic:
        1. Read locked_months from config
        2. Mark periods in locked_months as locked, others as unlocked
        3. Compute remaining target = annual - sum(locked period targets)
        4. Redistribute remaining target across unlocked periods preserving their relative weights

        Args:
            base_targets: DataFrame with [period, month, quarter, target_revenue]

        Returns:
            DataFrame with [period, month, quarter, target_revenue] where locked periods
            retain original targets and unlocked periods are redistributed
        """
        result = base_targets.copy()

        locked_periods = self.config.get("targets.locked_months", [])
        if not locked_periods:
            # No locked periods, return unchanged
            return result

        # Create a mask for locked periods
        locked_mask = result["period"].isin(locked_periods)

        # Sum targets for locked periods
        sum_locked_targets = result.loc[locked_mask, "target_revenue"].sum()

        # Annual target
        annual_target = result["target_revenue"].sum()

        # Remaining target to redistribute
        remaining_target = annual_target - sum_locked_targets

        # Sum targets for unlocked periods
        unlocked_mask = ~locked_mask
        sum_unlocked_targets = result.loc[unlocked_mask, "target_revenue"].sum()

        # Redistribute remaining target proportionally across unlocked periods
        if sum_unlocked_targets > 0 and remaining_target >= 0:
            scale_factor = remaining_target / sum_unlocked_targets
            result.loc[unlocked_mask, "target_revenue"] = (
                result.loc[unlocked_mask, "target_revenue"] * scale_factor
            )

        return result
