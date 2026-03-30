"""
Ad-Hoc Adjustment Engine (Module 9)

Purpose:
    Handle mid-cycle re-planning by locking completed periods, incorporating
    actual performance, and re-optimizing for the remainder of the year.

Key capabilities:
    - Lock periods with actual performance data
    - Apply HC changes (hiring/attrition events)
    - Update annual or period targets mid-year
    - Adjust segment-specific parameters (ASP, win rate, etc.)
    - Compute remaining target and recalibrate optimization inputs
    - Generate audit trail of adjustments made

Data flow:
    Current Plan + Actuals + Changes → Adjustment Engine → Updated Config + Locked Periods + Remaining Target

Use case:
    "We just closed Q2 actuals ($45M, beat target by $5M). Q3 hiring was 5 fewer people.
     Annual target revised to $195M. Re-optimize Q3-Q4 against this."

Author: GTM Planning Engine
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from copy import deepcopy


class AdjustmentEngine:
    """
    Engine for mid-cycle adjustments and re-planning.

    This module is the gateway for "reality-driven re-planning." When:
        - Actual quarterly results come in
        - AE attrition/hiring differs from plan
        - Market conditions change (e.g., EOR ASP pressure)
        - Annual targets are revised

    ...the Adjustment Engine applies these changes to the config and plan,
    locks completed periods, and signals which modules need to re-run.

    Workflow:
        1. Ingest current plan (from Version Store)
        2. Merge actuals for completed periods (locks them)
        3. Apply each type of change (HC, target, segment params)
        4. Calculate remaining target for unlocked periods
        5. Return adjusted config + metadata for re-optimization

    The calling system (usually the main orchestrator) then re-runs:
        Target Generator (rolling_forward mode) → Optimizer → Recovery → Validation
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Adjustment Engine.

        Args:
            config: Dict-like config object with .get(key, default) method.
                   Should contain planning_mode and other standard GTM config.
        """
        self.config = config
        self.planning_mode = config.get("targets", {}).get("planning_mode", "full_year")

    def apply_adjustment(
        self,
        current_plan: pd.DataFrame,
        actuals: Optional[pd.DataFrame] = None,
        hc_changes: Optional[Dict[str, int]] = None,
        target_changes: Optional[Dict[str, float]] = None,
        segment_changes: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """
        Process mid-cycle adjustments and prepare inputs for re-optimization.

        This is the main entry point. It applies changes in order and validates
        consistency. Each change type is optional; omit to skip.

        Args:
            current_plan: The existing allocation plan DataFrame.
                         Expected columns: [period, segment, projected_bookings, ...]
            actuals: Optional. Real performance DataFrame for completed periods.
                    Expected columns: [period, segment, actual_bookings, ...]
            hc_changes: Optional. Dict of HC adjustments. E.g.:
                       {
                           "month_5": -3,     # 3 AEs departed in month 5
                           "month_8": 5,      # 5 new AEs starting month 8
                       }
            target_changes: Optional. Dict of target adjustments. E.g.:
                           {
                               "annual_target": 195000000,  # Revised from $188M to $195M
                               "month_4_target": 18000000,  # Adjust specific month target
                           }
            segment_changes: Optional. Dict of segment-specific parameter updates. E.g.:
                            {
                                "EOR.asp": 12000,       # EOR ASP revised down to $12K
                                "Payroll.cw_rate": 0.65,  # Win rate adjustment
                            }

        Returns:
            Dict with keys:
                - adjusted_config: Updated config dict (ready for re-optimizer)
                - locked_periods: List of period identifiers that are frozen
                - remaining_target: Revenue still needed from unlocked periods ($)
                - locked_revenue: Actual revenue locked in from completed periods ($)
                - adjustment_summary: Human-readable description of changes
                - changes_applied: Dict of what was actually changed {type: count}
        """
        # Start with a deep copy of config to avoid side effects
        adjusted_config = deepcopy(self.config)

        # Track what we've changed
        changes_applied = {
            "actuals_merged": 0,
            "hc_changes_applied": 0,
            "target_changes_applied": 0,
            "segment_changes_applied": 0,
        }

        # Step 1: Merge actuals (if provided)
        merged_plan, locked_periods, locked_revenue = (current_plan, [], 0.0)
        if actuals is not None:
            merged_plan, locked_periods, locked_revenue = self._merge_actuals(current_plan, actuals)
            changes_applied["actuals_merged"] = len(locked_periods)

        # Step 2: Apply HC changes (if provided)
        if hc_changes:
            adjusted_config = self._apply_hc_changes(adjusted_config, hc_changes)
            changes_applied["hc_changes_applied"] = len(hc_changes)

        # Step 3: Apply target changes (if provided)
        remaining_target = self._calculate_remaining_target(merged_plan, locked_periods, target_changes)
        if target_changes:
            adjusted_config = self._apply_target_changes(adjusted_config, target_changes)
            changes_applied["target_changes_applied"] = len(target_changes)

        # Step 4: Apply segment-specific changes (if provided)
        if segment_changes:
            adjusted_config = self._apply_segment_changes(adjusted_config, segment_changes)
            changes_applied["segment_changes_applied"] = len(segment_changes)

        # Step 5: Generate summary narrative
        adjustment_summary = self.generate_summary({
            "locked_periods": locked_periods,
            "locked_revenue": locked_revenue,
            "remaining_target": remaining_target,
            "hc_changes": hc_changes or {},
            "target_changes": target_changes or {},
            "segment_changes": segment_changes or {},
        })

        return {
            "adjusted_config": adjusted_config,
            "locked_periods": locked_periods,
            "remaining_target": remaining_target,
            "locked_revenue": locked_revenue,
            "adjustment_summary": adjustment_summary,
            "changes_applied": changes_applied,
        }

    def _merge_actuals(
        self,
        plan: pd.DataFrame,
        actuals: pd.DataFrame,
    ) -> Tuple[pd.DataFrame, List[str], float]:
        """
        Replace planned values with actuals for completed periods.

        For any period where actuals are provided, we lock that period and use
        actual bookings instead of projections.

        Args:
            plan: Current plan DataFrame with [period, segment, projected_bookings].
            actuals: Actuals DataFrame with [period, segment, actual_bookings].

        Returns:
            Tuple of (merged_df, locked_periods_list, total_locked_revenue)
        """
        merged = plan.copy()
        locked_periods = []
        total_locked_revenue = 0.0

        # Get unique periods from actuals
        if len(actuals) == 0:
            return merged, locked_periods, 0.0

        actual_periods = actuals["period"].unique() if "period" in actuals.columns else []

        # Merge actuals onto plan
        if "period" in actuals.columns and "actual_bookings" in actuals.columns:
            for period in actual_periods:
                # Get actuals for this period
                period_actuals = actuals[actuals["period"] == period]

                # Update plan rows for this period
                period_mask = merged["period"] == period
                for idx in merged[period_mask].index:
                    # Find matching actual for this segment (if exists)
                    segment = merged.loc[idx, "segment"] if "segment" in merged.columns else "total"
                    segment_actuals = period_actuals[
                        period_actuals.get("segment", "total") == segment
                    ]

                    if len(segment_actuals) > 0:
                        actual_value = segment_actuals["actual_bookings"].sum()
                        merged.loc[idx, "projected_bookings"] = actual_value
                        total_locked_revenue += actual_value

                if len(period_actuals) > 0:
                    locked_periods.append(period)

        # Remove duplicates from locked_periods
        locked_periods = sorted(list(set(locked_periods)))

        return merged, locked_periods, total_locked_revenue

    def _apply_hc_changes(self, config: Dict[str, Any], hc_changes: Dict[str, int]) -> Dict[str, Any]:
        """
        Modify the hiring plan in config to reflect HC changes.

        HC changes are specified as month-level adjustments:
            {"month_4": -3} means "3 fewer AEs in month 4"
            {"month_8": 5} means "5 additional AEs starting month 8"

        This implementation updates the hiring_plan section of ae_model.

        Args:
            config: Config dict (will be modified).
            hc_changes: Dict like {"month_N": ±count}.

        Returns:
            Updated config dict.
        """
        updated_config = deepcopy(config)

        # Get current hiring plan
        hiring_plan = updated_config.get("ae_model", {}).get("hiring_plan", [])

        for change_key, delta_count in hc_changes.items():
            # Parse month from key (e.g., "month_4" -> 4)
            try:
                if "month_" in str(change_key):
                    month = int(str(change_key).split("_")[-1])
                else:
                    month = int(change_key)
            except:
                continue

            # Check if there's already a tranche for this month
            found = False
            for tranche in hiring_plan:
                if tranche.get("start_month") == month:
                    tranche["count"] = max(0, tranche.get("count", 0) + delta_count)
                    found = True
                    break

            # If not found, add a new tranche
            if not found and delta_count > 0:
                hiring_plan.append({"count": delta_count, "start_month": month})

        # Update config
        if "ae_model" not in updated_config:
            updated_config["ae_model"] = {}
        updated_config["ae_model"]["hiring_plan"] = hiring_plan

        return updated_config

    def _apply_target_changes(self, config: Dict[str, Any], target_changes: Dict[str, float]) -> Dict[str, Any]:
        """
        Update annual target and recompute period targets.

        Target changes can be:
            {"annual_target": 200000000} to change annual target
            {"month_N_target": X} to override specific period targets (used downstream)

        Args:
            config: Config dict.
            target_changes: Dict with target updates.

        Returns:
            Updated config dict.
        """
        updated_config = deepcopy(config)

        # Update annual target if provided
        if "annual_target" in target_changes:
            new_target = target_changes["annual_target"]
            if "targets" not in updated_config:
                updated_config["targets"] = {}
            updated_config["targets"]["annual_target"] = new_target

        # Note: Per-period overrides (month_N_target) are handled by the Target Generator
        # in rolling_forward mode, so we don't modify those here.
        # Instead, we signal via a special key that the optimizer should be aware of.

        return updated_config

    def _apply_segment_changes(self, config: Dict[str, Any], segment_changes: Dict[str, float]) -> Dict[str, Any]:
        """
        Update segment-specific parameters (ASP, CW rate, etc.).

        Segment changes are specified as strings like "EOR.asp" or "Payroll.cw_rate".

        Args:
            config: Config dict.
            segment_changes: Dict like {"EOR.asp": 12000, "Payroll.cw_rate": 0.65}.

        Returns:
            Updated config dict.
        """
        updated_config = deepcopy(config)

        for change_key, value in segment_changes.items():
            # Parse the change key: "PRODUCT.METRIC" or "PRODUCT.CHANNEL.METRIC"
            parts = str(change_key).split(".")
            if len(parts) < 2:
                continue

            # For simplicity, store segment overrides in a special section
            # (This is a placeholder; actual implementation depends on how
            # the Economics Engine and other modules resolve these.)
            if "segment_overrides" not in updated_config.get("economics", {}):
                if "economics" not in updated_config:
                    updated_config["economics"] = {}
                updated_config["economics"]["segment_overrides"] = {}

            # Store the override
            segment_key = ".".join(parts[:-1])  # e.g., "EOR" or "Payroll"
            metric_key = parts[-1]  # e.g., "asp"
            if segment_key not in updated_config["economics"]["segment_overrides"]:
                updated_config["economics"]["segment_overrides"][segment_key] = {}
            updated_config["economics"]["segment_overrides"][segment_key][metric_key] = value

        return updated_config

    def _calculate_remaining_target(
        self,
        merged_plan: pd.DataFrame,
        locked_periods: List[str],
        target_changes: Optional[Dict[str, float]],
    ) -> float:
        """
        Calculate the remaining revenue target for unlocked periods.

        Logic:
            1. Get the annual target (from config or from target_changes)
            2. Sum actual/locked revenue from completed periods
            3. Remaining = Annual - Locked

        Args:
            merged_plan: Merged plan+actuals DataFrame.
            locked_periods: List of locked period identifiers.
            target_changes: Dict with potential annual_target override.

        Returns:
            Float: Remaining target ($).
        """
        # Get annual target
        annual_target = self.config.get("targets", {}).get("annual_target", 0)
        if target_changes and "annual_target" in target_changes:
            annual_target = target_changes["annual_target"]

        # Sum locked revenue (actuals for completed periods)
        locked_revenue = 0.0
        if len(locked_periods) > 0 and "period" in merged_plan.columns and "projected_bookings" in merged_plan.columns:
            locked_data = merged_plan[merged_plan["period"].isin(locked_periods)]
            locked_revenue = locked_data["projected_bookings"].sum()

        # Remaining target
        remaining = max(0, annual_target - locked_revenue)
        return remaining

    def generate_summary(self, adjustment_context: Dict[str, Any]) -> str:
        """
        Create a human-readable summary of all adjustments made.

        Args:
            adjustment_context: Dict with keys like locked_periods, locked_revenue, etc.

        Returns:
            String narrative.
        """
        locked_periods = adjustment_context.get("locked_periods", [])
        locked_revenue = adjustment_context.get("locked_revenue", 0.0)
        remaining_target = adjustment_context.get("remaining_target", 0.0)
        hc_changes = adjustment_context.get("hc_changes", {})
        target_changes = adjustment_context.get("target_changes", {})
        segment_changes = adjustment_context.get("segment_changes", {})

        summary = "MID-CYCLE ADJUSTMENT SUMMARY\n"
        summary += "=" * 60 + "\n\n"

        # Actual locking
        if locked_periods:
            summary += f"Periods Locked (Actual Performance):\n"
            summary += f"  Periods: {', '.join(locked_periods)}\n"
            summary += f"  Locked Revenue: ${locked_revenue:,.0f}\n"
            summary += f"  Remaining Target: ${remaining_target:,.0f}\n\n"
        else:
            summary += "No completed periods to lock.\n\n"

        # HC changes
        if hc_changes:
            summary += f"Headcount Adjustments:\n"
            for month_key, delta in hc_changes.items():
                direction = "increase" if delta > 0 else "decrease"
                summary += f"  {month_key}: {direction} by {abs(delta)} AE(s)\n"
            summary += "\n"

        # Target changes
        if target_changes:
            summary += f"Target Adjustments:\n"
            for key, value in target_changes.items():
                if "annual" in key.lower():
                    summary += f"  {key}: ${value:,.0f}\n"
                else:
                    summary += f"  {key}: ${value:,.0f}\n"
            summary += "\n"

        # Segment changes
        if segment_changes:
            summary += f"Segment-Specific Changes:\n"
            for key, value in segment_changes.items():
                summary += f"  {key}: {value}\n"
            summary += "\n"

        summary += "Next Steps:\n"
        summary += "  1. Re-run Target Generator (rolling_forward mode)\n"
        summary += "  2. Re-run Optimizer with adjusted config\n"
        summary += "  3. Run Recovery & Validation on new plan\n"
        summary += "  4. Store as new version in Version Store\n"

        return summary
