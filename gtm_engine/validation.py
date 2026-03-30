"""
Validation Engine (Module 8)

Purpose:
    Verify mathematical consistency and constraint satisfaction across all module outputs.
    Acts as a gatekeeper: does the plan make sense?

Key capabilities:
    - Revenue identity checks (bookings = SAOs × ASP × CW Rate)
    - Constraint validation (shares within floor/ceiling, sum to 1.0)
    - Capacity validation (total demand ≤ available supply)
    - Target alignment (projected ≈ annual target within tolerance)
    - Confidence coverage (flag if too much revenue from low-confidence segments)
    - Comprehensive pass/fail reporting

Data flow:
    Allocation Results → Validation Engine → Validation Report (pass/fail + diagnostics)

Author: GTM Planning Engine
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any


class ValidationEngine:
    """
    Engine for comprehensive validation of allocation results.

    This module runs a series of mathematical and logical checks to verify:
        1. Revenue calculations are correct (bookings = SAOs × ASP × CW)
        2. Constraints are satisfied (share floor/ceiling, sum = 1.0)
        3. Capacity constraints are met (demand <= supply)
        4. Annual target is hit within tolerance
        5. No negative values (revenue, SAOs, shares, etc.)
        6. Confidence levels are appropriate (not too much from low-confidence segments)

    Workflow:
        1. Ingest allocation results, targets, capacity
        2. Run all validation checks
        3. Aggregate results into pass/fail verdict
        4. Provide detailed diagnostics for any failures
        5. Generate human-readable report

    This module is tolerance-aware: uses config values to allow for rounding and
    floating-point precision issues.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize Validation Engine with config thresholds.

        Args:
            config: Dict-like config object with .get(key, default) method.
                   Must contain:
                   - allocation.constraints.share_floor: float (default 0.05)
                   - allocation.constraints.share_ceiling: float (default 0.40)
                   - system.tolerance: float (default 0.001, for relative comparisons)
                   - system.revenue_tolerance: float (default 0.01, for identity checks)
        """
        self.config = config
        self.share_floor = config.get("allocation.constraints.share_floor", 0.05)
        self.share_ceiling = config.get("allocation.constraints.share_ceiling", 0.40)
        self.tolerance = config.get("system.tolerance", 0.001)
        self.revenue_tolerance = config.get("system.revenue_tolerance", 0.01)

    def validate(
        self,
        allocation_results: pd.DataFrame,
        targets: Optional[pd.DataFrame] = None,
        capacity: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Any]:
        """
        Run all validation checks on the allocation results.

        Args:
            allocation_results: Core allocation results DataFrame.
                               Expected columns include:
                               - period, segment, share, required_saos
                               - projected_pipeline, projected_bookings
                               - effective_asp, effective_cw_rate (for revenue identity check)
            targets: Optional DataFrame with [period, target_bookings].
            capacity: Optional DataFrame with [period, effective_capacity_saos].

        Returns:
            Dict with keys:
                - passed: bool (True if all checks pass)
                - checks: List of check result dicts. Each has:
                    - name: str (check name)
                    - passed: bool
                    - message: str (summary)
                    - details: dict (additional context)
                - summary: str (human-readable overview)
        """
        checks = []

        # Run individual checks
        checks.append(self._check_revenue_identity(allocation_results))
        checks.append(self._check_share_constraints(allocation_results))
        checks.append(self._check_share_sum(allocation_results))
        checks.append(self._check_no_negatives(allocation_results))

        if capacity is not None:
            checks.append(self._check_capacity(allocation_results, capacity))

        if targets is not None:
            checks.append(self._check_target_alignment(allocation_results, targets))
            checks.append(self._check_confidence_coverage(allocation_results))

        # Aggregate result
        all_passed = all(c["passed"] for c in checks)

        # Build summary
        summary = self._build_summary(checks, all_passed)

        return {
            "passed": all_passed,
            "checks": checks,
            "summary": summary,
        }

    def _check_revenue_identity(self, results: pd.DataFrame) -> Dict[str, Any]:
        """
        Verify bookings = SAOs × ASP × CW_rate for every row.

        This is a core identity: if violated, something in the calculation layer is broken.

        Args:
            results: Allocation results DataFrame.

        Returns:
            Dict with check result.
        """
        check_name = "Revenue Identity"
        passed = True
        failures = []

        # Require these columns
        required = {"required_saos", "projected_bookings", "effective_asp", "effective_cw_rate"}
        if not required.issubset(results.columns):
            return {
                "name": check_name,
                "passed": False,
                "message": f"Missing required columns: {required - set(results.columns)}",
                "details": {"missing_columns": list(required - set(results.columns))},
            }

        # Compute expected bookings
        results_copy = results.copy()
        results_copy["expected_bookings"] = results_copy["required_saos"] * results_copy["effective_asp"] * results_copy["effective_cw_rate"]

        # Compare with actual
        for idx, row in results_copy.iterrows():
            expected = row["expected_bookings"]
            actual = row["projected_bookings"]
            if expected > 0:
                rel_error = abs(actual - expected) / expected
                if rel_error > self.revenue_tolerance:
                    failures.append({
                        "row_index": idx,
                        "expected": expected,
                        "actual": actual,
                        "rel_error_pct": rel_error * 100,
                    })
                    passed = False

        if passed:
            message = f"OK: Revenue identity verified across {len(results_copy)} rows."
        else:
            message = f"FAIL: {len(failures)} row(s) violate revenue identity (tolerance: {self.revenue_tolerance*100:.1f}%)"

        return {
            "name": check_name,
            "passed": passed,
            "message": message,
            "details": {"failures": failures, "total_rows": len(results_copy)},
        }

    def _check_share_constraints(self, results: pd.DataFrame) -> Dict[str, Any]:
        """
        Verify share_floor <= share <= share_ceiling for every row.

        Args:
            results: Allocation results DataFrame with 'share' column.

        Returns:
            Dict with check result.
        """
        check_name = "Share Constraints"
        passed = True
        violations = []

        if "share" not in results.columns:
            return {
                "name": check_name,
                "passed": False,
                "message": "Missing 'share' column.",
                "details": {},
            }

        for idx, row in results.iterrows():
            share = row.get("share", 0)
            if share < self.share_floor - self.tolerance or share > self.share_ceiling + self.tolerance:
                violations.append({
                    "row_index": idx,
                    "share": share,
                    "floor": self.share_floor,
                    "ceiling": self.share_ceiling,
                })
                passed = False

        if passed:
            message = (
                f"OK: All shares within [{self.share_floor*100:.1f}%, {self.share_ceiling*100:.1f}%] "
                f"across {len(results)} rows."
            )
        else:
            message = f"FAIL: {len(violations)} row(s) violate share constraints."

        return {
            "name": check_name,
            "passed": passed,
            "message": message,
            "details": {"violations": violations},
        }

    def _check_share_sum(self, results: pd.DataFrame) -> Dict[str, Any]:
        """
        Verify shares sum to 1.0 per period.

        Args:
            results: Allocation results with 'period' and 'share' columns.

        Returns:
            Dict with check result.
        """
        check_name = "Share Sum"
        passed = True
        failures = []

        if "period" not in results.columns or "share" not in results.columns:
            return {
                "name": check_name,
                "passed": False,
                "message": "Missing 'period' or 'share' column.",
                "details": {},
            }

        # Group by period and sum shares
        by_period = results.groupby("period")["share"].sum()

        for period, total_share in by_period.items():
            if abs(total_share - 1.0) > self.tolerance:
                failures.append({
                    "period": period,
                    "sum": total_share,
                    "diff_from_1": total_share - 1.0,
                })
                passed = False

        if passed:
            message = f"OK: Shares sum to 1.0 ±{self.tolerance} for all {len(by_period)} period(s)."
        else:
            message = f"FAIL: {len(failures)} period(s) have share sum != 1.0."

        return {
            "name": check_name,
            "passed": passed,
            "message": message,
            "details": {"failures": failures},
        }

    def _check_capacity(
        self,
        results: pd.DataFrame,
        capacity: pd.DataFrame,
    ) -> Dict[str, Any]:
        """
        Verify total SAOs <= effective capacity per period.

        Args:
            results: Allocation results with [period, required_SAOs].
            capacity: Capacity DataFrame with [period, effective_capacity].

        Returns:
            Dict with check result.
        """
        check_name = "Capacity Constraint"
        passed = True
        violations = []

        if "period" not in results.columns or "required_saos" not in results.columns:
            return {
                "name": check_name,
                "passed": False,
                "message": "Missing 'period' or 'required_saos' column in results.",
                "details": {},
            }

        # Capacity may use 'month' or 'period' as the time-index column
        cap_period_col = "period" if "period" in capacity.columns else "month"
        if cap_period_col not in capacity.columns or "effective_capacity_saos" not in capacity.columns:
            return {
                "name": check_name,
                "passed": False,
                "message": "Missing period/month or 'effective_capacity_saos' column in capacity.",
                "details": {},
            }

        # Aggregate demand by period
        demand_by_period = results.groupby("period")["required_saos"].sum()

        # Merge with capacity (join on whichever time column capacity uses)
        for period, demand in demand_by_period.items():
            cap_rows = capacity[capacity[cap_period_col] == period]
            if len(cap_rows) > 0:
                supply = cap_rows["effective_capacity_saos"].sum()
                if demand > supply + self.tolerance:
                    violations.append({
                        "period": period,
                        "demand": demand,
                        "supply": supply,
                        "overage": demand - supply,
                    })
                    passed = False

        if passed:
            message = f"OK: Demand <= supply for all {len(demand_by_period)} period(s)."
        else:
            message = f"FAIL: {len(violations)} period(s) exceed capacity."

        return {
            "name": check_name,
            "passed": passed,
            "message": message,
            "details": {"violations": violations},
        }

    def _check_target_alignment(
        self,
        results: pd.DataFrame,
        targets: pd.DataFrame,
    ) -> Dict[str, Any]:
        """
        Verify total projected bookings ≈ annual target within tolerance.

        Args:
            results: Allocation results with 'projected_bookings' column.
            targets: Targets DataFrame with 'target_bookings' column.

        Returns:
            Dict with check result.
        """
        check_name = "Target Alignment"

        if "projected_bookings" not in results.columns:
            return {
                "name": check_name,
                "passed": False,
                "message": "Missing 'projected_bookings' column in results.",
                "details": {},
            }

        # TargetGenerator may output 'target_revenue' or 'target_bookings'
        target_col = "target_bookings" if "target_bookings" in targets.columns else "target_revenue"
        if target_col not in targets.columns:
            return {
                "name": check_name,
                "passed": False,
                "message": "Missing 'target_bookings' or 'target_revenue' column in targets.",
                "details": {},
            }

        total_projected = results["projected_bookings"].sum()
        total_target = targets[target_col].sum()

        if total_target > 0:
            rel_error = abs(total_projected - total_target) / total_target
            passed = rel_error <= self.tolerance
        else:
            passed = abs(total_projected - total_target) <= self.tolerance
            rel_error = 0

        if passed:
            message = (
                f"OK: Total projected bookings ${total_projected:,.0f} "
                f"matches target ${total_target:,.0f} within {self.tolerance*100:.1f}% tolerance."
            )
        else:
            message = (
                f"FAIL: Total projected ${total_projected:,.0f} "
                f"vs target ${total_target:,.0f} (error: {rel_error*100:.1f}%)."
            )

        return {
            "name": check_name,
            "passed": passed,
            "message": message,
            "details": {
                "total_projected": total_projected,
                "total_target": total_target,
                "rel_error_pct": rel_error * 100,
            },
        }

    def _check_no_negatives(self, results: pd.DataFrame) -> Dict[str, Any]:
        """
        Verify no negative values in SAOs, revenue, share, HC.

        Args:
            results: Allocation results DataFrame.

        Returns:
            Dict with check result.
        """
        check_name = "No Negative Values"
        passed = True
        violations = []

        # Check key numeric columns
        numeric_cols = [
            "required_saos",
            "projected_pipeline",
            "projected_bookings",
            "share",
        ]

        for col in numeric_cols:
            if col not in results.columns:
                continue

            negatives = results[results[col] < -self.tolerance]
            if len(negatives) > 0:
                passed = False
                violations.append({
                    "column": col,
                    "count": len(negatives),
                    "min_value": negatives[col].min(),
                })

        if passed:
            message = f"OK: No negative values in {len([c for c in numeric_cols if c in results.columns])} key columns."
        else:
            message = f"FAIL: {len(violations)} column(s) contain negative values."

        return {
            "name": check_name,
            "passed": passed,
            "message": message,
            "details": {"violations": violations},
        }

    def _check_confidence_coverage(self, results: pd.DataFrame) -> Dict[str, Any]:
        """
        Flag if >20% of bookings come from low-confidence segments.

        Low-confidence segments = those with few historical deals or sparse data.

        Args:
            results: Allocation results with [projected_bookings, confidence_level].

        Returns:
            Dict with check result.
        """
        check_name = "Confidence Coverage"

        if "projected_bookings" not in results.columns or "confidence_level" not in results.columns:
            return {
                "name": check_name,
                "passed": True,
                "message": "Confidence level data not available; skipping check.",
                "details": {},
            }

        total_bookings = results["projected_bookings"].sum()
        low_conf_bookings = results[results["confidence_level"] == "low"]["projected_bookings"].sum()

        low_conf_pct = (low_conf_bookings / total_bookings * 100) if total_bookings > 0 else 0

        # Flag if > threshold% from low confidence
        threshold = self.config.get("system.low_confidence_threshold", 20.0)
        passed = low_conf_pct <= threshold

        if passed:
            message = f"OK: Only {low_conf_pct:.1f}% of bookings from low-confidence segments (threshold: {threshold}%)."
        else:
            message = (
                f"WARNING: {low_conf_pct:.1f}% of bookings from low-confidence segments "
                f"(exceeds {threshold}% threshold)."
            )

        return {
            "name": check_name,
            "passed": passed,
            "message": message,
            "details": {
                "low_confidence_pct": low_conf_pct,
                "threshold_pct": threshold,
                "low_conf_bookings": low_conf_bookings,
                "total_bookings": total_bookings,
            },
        }

    def _build_summary(self, checks: List[Dict[str, Any]], all_passed: bool) -> str:
        """
        Build a human-readable summary of validation results.

        Args:
            checks: List of check result dicts.
            all_passed: Overall pass/fail verdict.

        Returns:
            String narrative.
        """
        num_checks = len(checks)
        num_passed = sum(1 for c in checks if c["passed"])

        if all_passed:
            summary = f"VALIDATION PASSED: All {num_checks} checks passed.\n"
            summary += "The allocation plan is mathematically consistent and satisfies all constraints."
        else:
            failed_checks = [c for c in checks if not c["passed"]]
            summary = (
                f"VALIDATION FAILED: {num_passed}/{num_checks} checks passed. "
                f"{len(failed_checks)} issue(s) detected.\n\n"
                "Failed checks:\n"
            )
            for check in failed_checks:
                summary += f"  - {check['name']}: {check['message']}\n"

        return summary

    def print_report(self, validation_results: Dict[str, Any]) -> None:
        """
        Pretty-print the validation report to console.

        Args:
            validation_results: Output from validate() method.
        """
        print("\n" + "=" * 70)
        print("VALIDATION REPORT")
        print("=" * 70)

        # Print summary
        print(validation_results["summary"])

        # Print check details
        print("\nDetailed Checks:")
        print("-" * 70)
        for check in validation_results["checks"]:
            status = "PASS" if check["passed"] else "FAIL"
            print(f"\n[{status}] {check['name']}")
            print(f"  {check['message']}")
            if check["details"]:
                if "violations" in check["details"] and check["details"]["violations"]:
                    print(f"  Violations: {len(check['details']['violations'])}")
                if "failures" in check["details"] and check["details"]["failures"]:
                    print(f"  Failures: {len(check['details']['failures'])}")

        print("\n" + "=" * 70)
