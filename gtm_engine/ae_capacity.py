"""
AE Capacity Model Module — Model effective Sales Accepted Opportunity (SAO) capacity.

Purpose:
    This module calculates how many SAOs the AE team can handle each month, accounting for:
    - Hiring plan (tranches of new AEs starting throughout the year)
    - Ramp curve (new AEs take time to reach full productivity, typically ~90 days)
    - Mentoring overhead (ramping AEs consume tenured AE time)
    - Shrinkage (PTO, admin, enablement take time away from selling)
    - Attrition (AEs leave and need backfill)

Inputs:
    - config: Dictionary-like object with ae_model settings:
        * ae_model.starting_hc: Initial tenured AE headcount
        * ae_model.productivity_per_ae: SAOs per fully-ramped AE per month
        * ae_model.hiring_plan: List of {count, start_month} tranches
        * ae_model.ramp.duration_days: Days to reach 100% productivity (e.g., 90)
        * ae_model.ramp.velocity: "linear" (current support) or "step" (future)
        * ae_model.mentoring.overhead_pct_per_new_hire: % of tenured AE time per mentee
        * ae_model.mentoring.max_mentees_per_ae: Max simultaneous mentees per mentor
        * ae_model.mentoring.warning_threshold: Flag if mentoring tax exceeds this %
        * ae_model.shrinkage.pto_pct, .admin_pct, .enablement_base_pct, .enablement_max_pct
        * ae_model.attrition.annual_rate: % AEs who leave per year
        * ae_model.attrition.backfill_delay_months: Months to hire replacement

Outputs:
    DataFrame with columns:
    - month: 1-12
    - hc_tenured: Fully-ramped AE count
    - hc_ramping: AEs currently in ramp period
    - hc_total: Total AE headcount
    - mentoring_tax: Fraction of tenured AE time consumed by mentoring
    - shrinkage_rate: Fraction of time lost to PTO/admin/enablement
    - effective_capacity_saos: Total SAOs the team can deliver this month
    - capacity_flag: Boolean, true if mentoring_tax > warning_threshold

Key Calculations per month:
    1. Initialize tenured pool from starting_hc
    2. For each hiring tranche that started before/in this month:
       a. Calculate days_in = days since tranche started
       b. If days_in >= ramp_duration: add full tranche to tenured pool
       c. Else: keep in ramping pool, compute ramp_factor = days_in / ramp_duration
       d. Compute mentoring overhead = A × (1 - days_in / ramp_duration) per hire
    3. Apply attrition: lose attrition_annual / 12 from tenured pool
    4. Compute shrinkage: pto + admin + enablement(new_hire_ratio)
    5. Calculate effective capacity:
       C_tenured = HC_tenured × (1 - shrinkage - mentoring_tax) × productivity_per_ae
       C_ramping = Σ(tranche_size × ramp_factor × (1 - shrinkage) × productivity_per_ae)
       C_total = C_tenured + C_ramping

Example:
    >>> config = {...}
    >>> ae_model = AECapacityModel(config)
    >>> capacity_df = ae_model.calculate()
    >>> print(capacity_df[["month", "hc_total", "effective_capacity_saos"]])
       month  hc_total  effective_capacity_saos
       1      100       3284
       2      102       3321
       ...
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, List


class AECapacityModel:
    """
    Model effective AE capacity (SAOs) by month, accounting for hiring, ramp,
    mentoring, shrinkage, and attrition.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize with config manager.

        Args:
            config: Dictionary-like object with ae_model parameters
        """
        self.config = config
        self._validate_config()

    def _validate_config(self) -> None:
        """Validate required AE model configuration."""
        starting_hc = self.config.get("ae_model.starting_hc", None)
        if starting_hc is None or starting_hc <= 0:
            raise ValueError("ae_model.starting_hc must be > 0")

        productivity = self.config.get("ae_model.productivity_per_ae", None)
        if productivity is None or productivity <= 0:
            raise ValueError("ae_model.productivity_per_ae must be > 0")

        ramp_days = self.config.get("ae_model.ramp.duration_days", None)
        if ramp_days is None or ramp_days <= 0:
            raise ValueError("ae_model.ramp.duration_days must be > 0")

    def calculate(self) -> pd.DataFrame:
        """
        Calculate effective AE capacity by month for 12 months.

        Returns DataFrame with columns:
        [month, hc_tenured, hc_ramping, hc_total, mentoring_tax,
         shrinkage_rate, effective_capacity_saos, capacity_flag]

        Logic per month:
        1. Start with tenured AE pool (starting_hc at month 1)
        2. Process hiring tranches: add to tenured if ramped, else to ramping pool
        3. Apply attrition to tenured pool
        4. Calculate shrinkage (pto + admin + enablement)
        5. Calculate mentoring tax on tenured pool
        6. Compute effective capacity for both tenured and ramping AEs
        7. Flag months where mentoring_tax > warning_threshold

        Returns:
            DataFrame with monthly capacity breakdown
        """
        rows = []
        starting_hc = self.config.get("ae_model.starting_hc", 100)
        productivity_per_ae = self.config.get("ae_model.productivity_per_ae", 35)
        ramp_duration_days = self.config.get("ae_model.ramp.duration_days", 90)
        ramp_duration_months = ramp_duration_days / 30  # Approximate: 30 days/month

        # Extract hiring plan
        hiring_plan = self.config.get("ae_model.hiring_plan", [])

        # Extract attrition parameters
        annual_attrition_rate = self.config.get("ae_model.attrition.annual_rate", 0.15)
        monthly_attrition_rate = annual_attrition_rate / 12

        # Extract warning threshold
        warning_threshold = self.config.get("ae_model.mentoring.warning_threshold", 0.25)

        # Track tenured HC across months
        tenured_hc = starting_hc

        # Process each month (1-12)
        for month in range(1, 13):
            # Step 1: Process hiring tranches for this month
            tranches_state = self._process_tranches(month, ramp_duration_months, hiring_plan)

            # Step 2: Calculate ramping AE state
            hc_ramping = 0
            total_ramping_capacity = 0

            for tranche in tranches_state:
                tranche_size = tranche["size"]
                ramp_factor = tranche["ramp_factor"]
                hc_ramping += tranche_size * ramp_factor  # Weighted count of ramping AEs

                # Ramping capacity: size × ramp_factor × (1 - shrinkage) × productivity
                shrinkage = self._calculate_shrinkage(month, len(tranches_state), hiring_plan)
                ramping_contribution = (
                    tranche_size * ramp_factor * (1 - shrinkage) * productivity_per_ae
                )
                total_ramping_capacity += ramping_contribution

            # Step 3: Apply attrition to tenured pool
            tenured_hc = self._apply_attrition(tenured_hc, month, monthly_attrition_rate)

            # Step 4: Calculate mentoring tax (pass current tenured_hc for correct fraction)
            mentoring_tax = self._calculate_mentoring_tax(month, tranches_state, tenured_hc)

            # Step 5: Calculate shrinkage
            shrinkage_rate = self._calculate_shrinkage(month, len(tranches_state), hiring_plan)

            # Step 6: Calculate tenured capacity
            tenured_capacity = (
                tenured_hc * (1 - shrinkage_rate - mentoring_tax) * productivity_per_ae
            )

            # Ensure capacity doesn't go negative
            tenured_capacity = max(0, tenured_capacity)

            # Step 7: Total capacity
            total_capacity = tenured_capacity + total_ramping_capacity

            # Step 8: Flag month if mentoring tax exceeds warning threshold
            capacity_flag = mentoring_tax > warning_threshold

            # Total HC (including fractional ramping AEs)
            hc_total = tenured_hc + hc_ramping

            rows.append({
                "month": month,
                "hc_tenured": tenured_hc,
                "hc_ramping": hc_ramping,
                "hc_total": hc_total,
                "mentoring_tax": mentoring_tax,
                "shrinkage_rate": shrinkage_rate,
                "effective_capacity_saos": total_capacity,
                "capacity_flag": capacity_flag
            })

        return pd.DataFrame(rows)

    def _process_tranches(self, month: int, ramp_duration_months: float,
                          hiring_plan: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        For a given month, calculate the state of each hiring tranche.

        Returns a list of dicts describing each tranche: size, start_month, days_in,
        ramp_factor (0.0 to 1.0), mentoring_overhead.

        Logic:
        1. For each tranche in hiring_plan:
           a. If tranche.start_month > month: skip (hasn't started)
           b. Else: calculate days_in = (month - start_month) × 30
           c. If days_in >= ramp_duration: ramp_factor = 1.0 (fully ramped)
           d. Else: ramp_factor = days_in / ramp_duration_days
           e. Store tranche state

        Args:
            month: Current month (1-12)
            ramp_duration_months: Ramp duration in months (~3 for 90 days)
            hiring_plan: List of {count, start_month} dicts

        Returns:
            List of dicts with keys: size, start_month, days_in, ramp_factor
        """
        tranches = []

        for tranche in hiring_plan:
            tranche_size = tranche.get("count", 0)
            start_month = tranche.get("start_month", 1)

            # Skip tranches that haven't started yet
            if start_month > month:
                continue

            # Calculate days since start (approximate: month difference × 30 days)
            months_in_ramp = month - start_month
            days_in = months_in_ramp * 30

            # Calculate ramp factor (linear ramp)
            ramp_duration_days = ramp_duration_months * 30
            if days_in >= ramp_duration_days:
                # Fully ramped, move to tenured
                ramp_factor = 1.0
            else:
                # Partially ramped
                ramp_factor = days_in / ramp_duration_days

            tranches.append({
                "size": tranche_size,
                "start_month": start_month,
                "days_in": days_in,
                "ramp_factor": ramp_factor
            })

        return tranches

    def _calculate_mentoring_tax(self, month: int, tranches_state: List[Dict[str, Any]],
                                 tenured_hc: float = None) -> float:
        """
        Calculate total mentoring overhead on tenured pool.

        Each ramping AE consumes A% × (1 - ramp_factor) of ONE tenured AE's time.
        The total overhead (in AE-equivalents) is divided by the current tenured
        headcount to yield the fraction of tenured capacity consumed.
        Respects max_mentees_per_ae constraint.

        Args:
            month: Current month (for reference)
            tranches_state: List of tranche state dicts from _process_tranches
            tenured_hc: Current tenured AE headcount (after attrition).
                        If None, falls back to starting_hc from config.

        Returns:
            float: Fraction of tenured AE capacity consumed by mentoring (0.0 to 1.0)
        """
        overhead_per_hire = self.config.get("ae_model.mentoring.overhead_pct_per_new_hire", 0.10)
        max_mentees_per_ae = self.config.get("ae_model.mentoring.max_mentees_per_ae", 2)

        if tenured_hc is None:
            tenured_hc = self.config.get("ae_model.starting_hc", 100)

        if tenured_hc <= 0:
            return 0.0

        # Sum overhead from all tranches still ramping (ramp_factor < 1.0)
        total_mentoring_overhead = 0  # in AE-equivalents (not a fraction yet)
        ramping_aes = 0

        for tranche in tranches_state:
            ramp_factor = tranche["ramp_factor"]
            tranche_size = tranche["size"]

            # Only count AEs still ramping (ramp_factor < 1.0)
            if ramp_factor < 1.0:
                # Overhead per hire: A × (1 - ramp_factor)
                overhead_per_hire_this_tranche = overhead_per_hire * (1 - ramp_factor)
                mentoring_hours = tranche_size * overhead_per_hire_this_tranche
                total_mentoring_overhead += mentoring_hours
                ramping_aes += tranche_size

        # Respect max_mentees_per_ae constraint
        max_total_mentees = max_mentees_per_ae * tenured_hc

        # Cap total ramping AEs by mentoring capacity
        if ramping_aes > max_total_mentees:
            scale = max_total_mentees / ramping_aes
            total_mentoring_overhead *= scale

        # Convert from AE-equivalents to fraction of tenured pool
        mentoring_fraction = total_mentoring_overhead / tenured_hc

        # Clamp to [0, 1]
        return max(0.0, min(1.0, mentoring_fraction))

    def _calculate_shrinkage(self, month: int, num_tranches: int,
                             hiring_plan: List[Dict[str, Any]]) -> float:
        """
        Calculate total shrinkage: PTO + admin + enablement(new_hire_ratio).

        Logic:
        1. PTO shrinkage: static, from config
        2. Admin shrinkage: static, from config
        3. Enablement shrinkage:
           - Base: from config
           - Scaling: depends on new_hire_ratio = (new hires in ramp) / total_hc
           - Formula: enablement = base + scaling × new_hire_ratio, capped at max

        Args:
            month: Current month (for context)
            num_tranches: Number of active hiring tranches this month
            hiring_plan: Hiring plan (to compute new_hire_ratio)

        Returns:
            float: Total shrinkage as fraction of time (0.0 to 1.0)
        """
        pto_pct = self.config.get("ae_model.shrinkage.pto_pct", 0.08)
        admin_pct = self.config.get("ae_model.shrinkage.admin_pct", 0.05)
        enable_base_pct = self.config.get("ae_model.shrinkage.enablement_base_pct", 0.03)
        enable_max_pct = self.config.get("ae_model.shrinkage.enablement_max_pct", 0.10)
        enable_scaling = self.config.get("ae_model.shrinkage.enablement_scaling", "proportional")

        # Static shrinkage
        static_shrinkage = pto_pct + admin_pct

        # Enablement shrinkage (scales with new hire ratio)
        if enable_scaling == "proportional" and num_tranches > 0:
            # Compute new_hire_ratio = currently ramping AEs / total AEs
            # For simplicity, use num_tranches as proxy (each tranche contributes ramping AEs)
            # Rough approximation: new_hire_ratio ≈ num_tranches / total_tranches_ever
            total_tranches_ever = len(hiring_plan) if hiring_plan else 1
            new_hire_ratio = min(num_tranches / max(1, total_tranches_ever), 1.0)

            # Enablement scales with new hire ratio
            enablement_pct = min(enable_max_pct, enable_base_pct + new_hire_ratio * (enable_max_pct - enable_base_pct))
        else:
            # Fixed enablement
            enablement_pct = enable_base_pct

        total_shrinkage = static_shrinkage + enablement_pct

        # Clamp to [0, 1]
        return max(0.0, min(1.0, total_shrinkage))

    def _apply_attrition(self, tenured_hc: float, month: int, monthly_rate: float) -> float:
        """
        Reduce tenured HC by monthly attrition rate.

        Logic:
        1. Apply monthly attrition: loss = tenured_hc × monthly_rate
        2. Return adjusted HC = tenured_hc - loss

        Args:
            tenured_hc: Current tenured AE headcount
            month: Current month (for context, not strictly needed)
            monthly_rate: Monthly attrition rate (annual_rate / 12)

        Returns:
            float: Adjusted tenured HC after attrition
        """
        loss = tenured_hc * monthly_rate
        return max(0, tenured_hc - loss)

    def get_capacity_summary(self) -> Dict[str, Any]:
        """
        Get summary statistics of AE capacity across the year.

        Returns:
            dict with keys:
            - total_annual_capacity: Total SAOs over all 12 months
            - min_monthly_capacity: Lowest monthly capacity
            - max_monthly_capacity: Highest monthly capacity
            - avg_monthly_capacity: Average monthly capacity
            - min_month: Month with lowest capacity
            - max_month: Month with highest capacity
        """
        df = self.calculate()

        total_capacity = df["effective_capacity_saos"].sum()
        min_capacity = df["effective_capacity_saos"].min()
        max_capacity = df["effective_capacity_saos"].max()
        avg_capacity = df["effective_capacity_saos"].mean()

        min_month = df.loc[df["effective_capacity_saos"].idxmin(), "month"]
        max_month = df.loc[df["effective_capacity_saos"].idxmax(), "month"]

        return {
            "total_annual_capacity": total_capacity,
            "min_monthly_capacity": min_capacity,
            "max_monthly_capacity": max_capacity,
            "avg_monthly_capacity": avg_capacity,
            "min_month": min_month,
            "max_month": max_month,
            "capacity_utilization_ratio": max_capacity / avg_capacity if avg_capacity > 0 else 1.0
        }

    def analyze_mentoring_relief(self, target_gap: float, month: int) -> Dict[str, Any]:
        """
        Model capacity relief if mentoring overhead A% is reduced.

        Used to answer: "If we reduce mentoring overhead by X%, how much capacity
        is freed up and does it close a capacity gap?"

        Logic:
        1. Calculate current capacity at month M with baseline A%
        2. Compute freed_capacity per 1% reduction in A%
        3. Find break_even_A_pct where freed_capacity ≥ target_gap
        4. Return break-even A% and recommendation

        Args:
            target_gap: Gap in capacity to fill (SAOs)
            month: Target month to analyze

        Returns:
            dict with keys:
            - baseline_overhead_pct: Current A% value
            - baseline_capacity: Current capacity at target month
            - freed_capacity_per_pct_reduction: Capacity freed per 1% A reduction
            - break_even_overhead_pct: A% value that closes gap (if achievable)
            - feasible: Boolean, true if gap can be closed with mentoring relief
            - recommendation: String describing the break-even scenario
        """
        df = self.calculate()

        # Get baseline values for target month
        month_data = df[df["month"] == month]
        if month_data.empty:
            raise ValueError(f"Month {month} not in capacity model output")

        baseline_overhead_pct = self.config.get("ae_model.mentoring.overhead_pct_per_new_hire", 0.10)
        baseline_capacity = month_data["effective_capacity_saos"].iloc[0]
        baseline_mentoring_tax = month_data["mentoring_tax"].iloc[0]

        # Estimate capacity freed per 1% reduction in A%
        # Rough estimate: if mentoring_tax = baseline_overhead_pct × ratio,
        # then reducing overhead by 1% frees ~1% of tenured AE time
        tenured_hc = month_data["hc_tenured"].iloc[0]
        productivity = self.config.get("ae_model.productivity_per_ae", 35)

        # Capacity freed per 1% reduction in A = tenured_hc × 1% × productivity
        freed_capacity_per_pct = tenured_hc * 0.01 * productivity

        if freed_capacity_per_pct <= 0:
            feasible = False
            break_even_overhead_pct = baseline_overhead_pct
        else:
            # Calculate break-even: baseline_capacity + freed_capacity_per_pct × pct_reduction >= target
            # pct_reduction = target_gap / freed_capacity_per_pct
            pct_reduction_needed = target_gap / freed_capacity_per_pct
            break_even_overhead_pct = baseline_overhead_pct * (1 - pct_reduction_needed / 100)

            # Feasible if break-even >= 0
            feasible = break_even_overhead_pct >= 0

        # Generate recommendation
        if feasible:
            pct_reduction_pct = 100 * (baseline_overhead_pct - break_even_overhead_pct) / baseline_overhead_pct
            recommendation = (
                f"Reduce mentoring overhead from {baseline_overhead_pct*100:.1f}% to "
                f"{break_even_overhead_pct*100:.1f}% ({pct_reduction_pct:.0f}% reduction) "
                f"to free {target_gap:.0f} SAO capacity in month {month}"
            )
        else:
            recommendation = (
                f"Gap of {target_gap:.0f} SAOs cannot be closed through mentoring relief alone. "
                f"Max achievable freed capacity: {freed_capacity_per_pct * 100:.0f} SAOs"
            )

        return {
            "baseline_overhead_pct": baseline_overhead_pct,
            "baseline_capacity": baseline_capacity,
            "freed_capacity_per_pct_reduction": freed_capacity_per_pct,
            "break_even_overhead_pct": break_even_overhead_pct,
            "feasible": feasible,
            "recommendation": recommendation
        }
