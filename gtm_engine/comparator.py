"""
Version Comparator — Multi-dimensional Plan Analysis Module

Purpose:
    Compares two or more plan versions across multiple analytical dimensions:
    numeric diffs, volatility, concentration risk, capacity utilisation, and more.

    This module lets GTM leaders answer "How do these two plans differ?" and
    identify which version is more stable, concentrated, or risky.

Key Concepts:
    - Version: A complete plan snapshot (config, results DataFrame, summary dict)
    - Metric: A single KPI like total_bookings or monthly_volatility
    - Risk Index: A composite score indicating plan stability/concentration

Usage:
    comparator = VersionComparator()
    versions = [
        {'version_id': 'v001', 'results': df1, 'summary': summary1},
        {'version_id': 'v002', 'results': df2, 'summary': summary2}
    ]
    comparison = comparator.compare(versions)
    comparator.print_comparison_report(comparison)

Classes:
    VersionComparator — Multi-dimensional version comparison engine
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from .utils import format_currency


@dataclass
class VersionMetrics:
    """Container for a single version's comparative metrics."""
    version_id: str
    total_bookings: float
    total_pipeline: float
    total_saos: int
    total_ae_hc: int
    avg_productivity_per_ae: float
    monthly_volatility: float
    coefficient_of_variation: float
    max_min_ratio: float
    herfindahl_index: float
    capacity_utilisation_variance: float
    stretch_exposure_pct: float
    confidence_weighted_bookings: float
    confidence_risk_flag: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for DataFrame conversion."""
        return asdict(self)


class VersionComparator:
    """
    Multi-Dimensional Version Comparator for GTM Plans.

    Compares 2+ versions across volatility, concentration, capacity, and risk metrics.
    Works independently—doesn't require other gtm_engine modules.

    Attributes:
        config (dict, optional): Configuration dict (used for stretch threshold, etc.)
    """

    def __init__(self, config: Optional[dict] = None):
        """
        Initialize the Version Comparator.

        Args:
            config: Optional ConfigManager or plain dict. When provided, thresholds
                   are read from config so this module stays aligned with the rest of
                   the engine. When omitted, safe defaults are used.

                   Reads:
                   - ae_model.stretch_threshold         (default 1.2)
                   - system.confidence_risk_low_max_pct    (default 5)
                   - system.confidence_risk_medium_max_pct (default 20)

                   Using dot-notation .get() works for both ConfigManager objects
                   (which resolve nested keys) and plain dicts (which return the
                   default when the literal dot-key is not found).
        """
        self.config = config or {}
        # Stretch threshold: same config path as RecoveryEngine so both modules
        # agree on what constitutes a "stretch" quarter.
        self.stretch_threshold = self.config.get('ae_model.stretch_threshold', 1.2)
        # Confidence risk bucket boundaries: same values as ValidationEngine's
        # pass/fail gate, ensuring comparator risk labels are interpretable
        # relative to the validation outcome.
        self.conf_low_max = self.config.get('system.confidence_risk_low_max_pct', 5)
        self.conf_medium_max = self.config.get('system.confidence_risk_medium_max_pct', 20)

    def compare(self, versions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Compare multiple plan versions across analytical dimensions.

        Args:
            versions: List of version dicts, each containing:
                - version_id (str): Unique identifier
                - results (pd.DataFrame): Allocation results with columns
                  [segment, month, share, required_SAOs, projected_pipeline,
                   projected_bookings, projected_deals, confidence_level, etc.]
                - summary (dict): Summary metrics with keys like
                  ['total_bookings', 'total_saos', 'total_ae_hc',
                   'productivity_per_ae', 'monthly_volatility', ...]

        Returns:
            Dict with keys:
            - metric_diffs: DataFrame comparing key metrics
            - allocation_shift: DataFrame showing segment share changes
            - volatility_analysis: Dict with volatility metrics per version
            - concentration_risk: Dict with HHI per version
            - capacity_utilisation_variance: Dict with variance metrics
            - stretch_exposure: Dict with stretch risk per version
            - confidence_risk: Dict with low-confidence exposure per version
            - metrics_table: Master DataFrame with all metrics

        Raises:
            ValueError: If versions invalid format or empty
            TypeError: If results or summary wrong type
        """
        if not isinstance(versions, list) or len(versions) < 2:
            raise ValueError("Must provide at least 2 versions to compare")

        # Validate version structure
        for version in versions:
            if 'version_id' not in version:
                raise ValueError("Each version must have 'version_id'")
            if 'results' not in version or not isinstance(version['results'], pd.DataFrame):
                raise TypeError(f"Version {version.get('version_id')} results must be DataFrame")
            if 'summary' not in version or not isinstance(version['summary'], dict):
                raise TypeError(f"Version {version.get('version_id')} summary must be dict")

        # Calculate metrics for each version
        metrics_list = []
        volatility_analysis = {}
        hhi_analysis = {}
        capacity_var_analysis = {}
        stretch_analysis = {}
        confidence_analysis = {}

        for version in versions:
            version_id = version['version_id']
            results_df = version['results']
            summary = version['summary']

            # Calculate all metrics
            volatility_metrics = self._calculate_volatility(results_df)
            hhi = self._calculate_hhi(results_df)
            capacity_var = self._calculate_capacity_utilisation_variance(results_df)
            stretch_exposure = self._calculate_stretch_exposure(results_df)
            confidence_risk = self._calculate_confidence_risk(results_df)

            # Extract key metrics from summary
            total_bookings = summary.get('total_bookings', 0.0)
            total_pipeline = summary.get('total_pipeline', 0.0)
            total_saos = summary.get('total_saos', 0)
            total_ae_hc = summary.get('total_ae_hc', 0)
            productivity = (
                total_saos / total_ae_hc
                if total_ae_hc > 0 else 0.0
            )

            # Create metrics object
            metrics = VersionMetrics(
                version_id=version_id,
                total_bookings=total_bookings,
                total_pipeline=total_pipeline,
                total_saos=total_saos,
                total_ae_hc=total_ae_hc,
                avg_productivity_per_ae=productivity,
                monthly_volatility=volatility_metrics['std_dev'],
                coefficient_of_variation=volatility_metrics['cv'],
                max_min_ratio=volatility_metrics['max_min_ratio'],
                herfindahl_index=hhi,
                capacity_utilisation_variance=capacity_var['variance'],
                stretch_exposure_pct=stretch_exposure['pct_quarters_stretched'],
                confidence_weighted_bookings=confidence_risk['low_confidence_bookings'],
                confidence_risk_flag=confidence_risk['risk_level']
            )

            metrics_list.append(metrics)
            volatility_analysis[version_id] = volatility_metrics
            hhi_analysis[version_id] = hhi
            capacity_var_analysis[version_id] = capacity_var
            stretch_analysis[version_id] = stretch_exposure
            confidence_analysis[version_id] = confidence_risk

        # Calculate metric diffs
        metric_diffs = self._calculate_metric_diffs(versions)

        # Calculate allocation shift (only if 2+ versions)
        allocation_shift = self._calculate_allocation_shift(versions)

        # Create master metrics table
        metrics_table = pd.DataFrame([m.to_dict() for m in metrics_list])

        return {
            'metric_diffs': metric_diffs,
            'allocation_shift': allocation_shift,
            'volatility_analysis': volatility_analysis,
            'concentration_risk': hhi_analysis,
            'capacity_utilisation_variance': capacity_var_analysis,
            'stretch_exposure': stretch_analysis,
            'confidence_risk': confidence_analysis,
            'metrics_table': metrics_table
        }

    def _calculate_metric_diffs(self, versions: List[Dict[str, Any]]) -> pd.DataFrame:
        """
        Compare total bookings, pipeline, SAOs, AE HC, productivity per AE
        across versions.

        Returns DataFrame with columns:
        [version_id, total_bookings, pipeline, total_saos, total_ae_hc,
         productivity_per_ae, bookings_vs_v1, saos_vs_v1, hc_vs_v1, ...]

        Args:
            versions: List of version dicts

        Returns:
            pd.DataFrame with metric comparisons
        """
        rows = []
        base_bookings = None
        base_saos = None
        base_hc = None

        for i, version in enumerate(versions):
            version_id = version['version_id']
            summary = version['summary']

            total_bookings = summary.get('total_bookings', 0.0)
            total_pipeline = summary.get('total_pipeline', 0.0)
            total_saos = summary.get('total_saos', 0)
            total_ae_hc = summary.get('total_ae_hc', 0)

            productivity = (
                total_saos / total_ae_hc
                if total_ae_hc > 0 else 0.0
            )

            row = {
                'version_id': version_id,
                'total_bookings': self._format_currency(total_bookings),
                'total_pipeline': self._format_currency(total_pipeline),
                'total_saos': int(total_saos),
                'total_ae_hc': int(total_ae_hc),
                'productivity_per_ae': round(productivity, 2)
            }

            # Set baseline for comparisons (first version)
            if i == 0:
                base_bookings = total_bookings
                base_saos = total_saos
                base_hc = total_ae_hc

            # Calculate deltas vs first version
            if base_bookings and base_bookings != 0:
                booking_delta_pct = (total_bookings - base_bookings) / base_bookings * 100
                row['bookings_vs_v1_pct'] = round(booking_delta_pct, 2)

            if base_saos and base_saos != 0:
                saos_delta_pct = (total_saos - base_saos) / base_saos * 100
                row['saos_vs_v1_pct'] = round(saos_delta_pct, 2)

            if base_hc and base_hc != 0:
                hc_delta_pct = (total_ae_hc - base_hc) / base_hc * 100
                row['hc_vs_v1_pct'] = round(hc_delta_pct, 2)

            rows.append(row)

        return pd.DataFrame(rows)

    def _calculate_allocation_shift(
        self,
        versions: List[Dict[str, Any]]
    ) -> pd.DataFrame:
        """
        How did segment shares change between versions?

        Calculates average share per segment per version and shows
        the shift from version 1 to each subsequent version.

        Args:
            versions: List of version dicts

        Returns:
            pd.DataFrame with columns [segment, v1_share, v2_share, ..., shift_pct]
        """
        if len(versions) < 2:
            return pd.DataFrame()

        # Group by segment and calculate average share per version
        segment_shares = {}

        for version in versions:
            version_id = version['version_id']
            results_df = version['results']

            # If 'segment_key' column exists, group by it. Otherwise try 'segment', product/channel combo
            if 'segment_key' in results_df.columns:
                shares = results_df.groupby('segment_key')['share'].mean()
            elif 'segment' in results_df.columns:
                shares = results_df.groupby('segment')['share'].mean()
            elif 'product' in results_df.columns and 'channel' in results_df.columns:
                shares = results_df.groupby(['product', 'channel'])['share'].mean()
                shares.index = [f"{p}.{c}" for p, c in shares.index]
            else:
                # Fallback: aggregate all rows
                shares = pd.Series({'total': results_df['share'].sum()})

            segment_shares[version_id] = shares

        # Create DataFrame of shares
        all_segments = set()
        for shares in segment_shares.values():
            all_segments.update(shares.index)

        shift_rows = []
        for segment in sorted(all_segments):
            row = {'segment': segment}

            for version_id in [v['version_id'] for v in versions]:
                shares = segment_shares.get(version_id, pd.Series())
                share = shares.get(segment, 0.0)
                row[version_id] = round(share, 3)

            # Calculate shift from first to last version
            v1_share = row[versions[0]['version_id']]
            vn_share = row[versions[-1]['version_id']]
            shift = vn_share - v1_share if v1_share != 0 else 0.0
            row['shift_pct'] = round(shift * 100, 2)

            shift_rows.append(row)

        return pd.DataFrame(shift_rows)

    def _calculate_volatility(self, results: pd.DataFrame) -> dict:
        """
        Monthly target volatility metrics: std dev, coefficient of variation,
        max/min ratio.

        Lower volatility = smoother, more predictable targets for sales teams.

        Args:
            results: Allocation results DataFrame

        Returns:
            Dict with keys:
            - std_dev: Standard deviation of monthly targets
            - cv: Coefficient of variation (std/mean, lower = smoother)
            - max_min_ratio: Highest month / lowest month
            - monthly_values: List of monthly totals for inspection
        """
        if 'month' not in results.columns or 'projected_bookings' not in results.columns:
            return {
                'std_dev': 0.0,
                'cv': 0.0,
                'max_min_ratio': 0.0,
                'monthly_values': []
            }

        # Sum bookings by month
        monthly_bookings = (
            results.groupby('month')['projected_bookings'].sum().values
        )

        if len(monthly_bookings) == 0 or monthly_bookings.sum() == 0:
            return {
                'std_dev': 0.0,
                'cv': 0.0,
                'max_min_ratio': 0.0,
                'monthly_values': monthly_bookings.tolist()
            }

        std_dev = np.std(monthly_bookings)
        mean = np.mean(monthly_bookings)
        cv = std_dev / mean if mean != 0 else 0.0

        min_month = np.min(monthly_bookings)
        max_month = np.max(monthly_bookings)
        max_min_ratio = max_month / min_month if min_month > 0 else 0.0

        return {
            'std_dev': round(std_dev, 2),
            'cv': round(cv, 3),
            'max_min_ratio': round(max_min_ratio, 2),
            'monthly_values': monthly_bookings.tolist()
        }

    def _calculate_hhi(self, results: pd.DataFrame) -> float:
        """
        Herfindahl-Hirschman Index across segments.

        HHI = Σ(share_i²) where shares are annual averages.
        Range: [1/n, 1.0]. Higher = more concentrated = riskier.

        Example:
        - 3 equal segments: HHI = 3 × (1/3)² = 0.333
        - 1 dominant segment: HHI = 1.0² = 1.0
        - 2 equal segments: HHI = 0.5

        Args:
            results: Allocation results DataFrame

        Returns:
            HHI score (float between 0 and 1)
        """
        if 'segment_key' not in results.columns and 'segment' not in results.columns and 'product' not in results.columns:
            return 0.0

        # Determine grouping column
        if 'segment_key' in results.columns:
            group_col = 'segment_key'
        elif 'segment' in results.columns:
            group_col = 'segment'
        elif 'product' in results.columns:
            group_col = 'product'
        else:
            return 0.0

        # Calculate average share per segment (across months)
        if 'share' in results.columns:
            segment_shares = results.groupby(group_col)['share'].mean().values
        else:
            return 0.0

        # Normalize to sum to 1.0
        total_share = segment_shares.sum()
        if total_share == 0:
            return 0.0

        normalized_shares = segment_shares / total_share

        # HHI = Σ(share_i²)
        hhi = np.sum(normalized_shares ** 2)

        return round(hhi, 3)

    def _calculate_capacity_utilisation_variance(
        self,
        results: pd.DataFrame,
        capacity: Optional[pd.DataFrame] = None
    ) -> dict:
        """
        How evenly is AE capacity used across months?

        Uneven utilization = some months overworked, some underutilized.
        This metric captures that distribution.

        If capacity DataFrame provided, uses actual capacity numbers.
        Otherwise, estimates from required_SAOs.

        Args:
            results: Allocation results DataFrame
            capacity: Optional capacity DataFrame with monthly capacity values

        Returns:
            Dict with keys:
            - variance: Variance in monthly utilisation rates
            - mean_utilisation: Average utilisation across months
            - min_utilisation: Lowest month utilisation
            - max_utilisation: Highest month utilisation
        """
        if 'month' not in results.columns:
            return {
                'variance': 0.0,
                'mean_utilisation': 0.0,
                'min_utilisation': 0.0,
                'max_utilisation': 0.0
            }

        # Calculate required SAOs per month
        if 'required_saos' in results.columns:
            monthly_saos = results.groupby('month')['required_saos'].sum().values
        else:
            # Fallback: use SAO count or return zero
            return {
                'variance': 0.0,
                'mean_utilisation': 0.0,
                'min_utilisation': 0.0,
                'max_utilisation': 0.0
            }

        if len(monthly_saos) == 0:
            return {
                'variance': 0.0,
                'mean_utilisation': 0.0,
                'min_utilisation': 0.0,
                'max_utilisation': 0.0
            }

        # If capacity provided, calculate utilisation %. Otherwise assume capacity = monthly_saos
        if capacity is not None and isinstance(capacity, pd.DataFrame):
            if 'month' in capacity.columns and 'effective_capacity_saos' in capacity.columns:
                capacity_values = capacity.set_index('month').loc[
                    results['month'].unique(), 'effective_capacity_saos'
                ].values
                utilisation = monthly_saos / capacity_values if capacity_values.sum() > 0 else monthly_saos
            else:
                utilisation = monthly_saos
        else:
            utilisation = monthly_saos

        variance = np.var(utilisation)
        mean_util = np.mean(utilisation)
        min_util = np.min(utilisation)
        max_util = np.max(utilisation)

        return {
            'variance': round(variance, 2),
            'mean_utilisation': round(mean_util, 2),
            'min_utilisation': round(min_util, 2),
            'max_utilisation': round(max_util, 2)
        }

    def _calculate_stretch_exposure(self, results: pd.DataFrame) -> dict:
        """
        Which quarters are near or above the stretch threshold?

        Stretch exposure = % of quarters requiring > 120% of original plan.
        Higher = riskier.

        Args:
            results: Allocation results DataFrame

        Returns:
            Dict with keys:
            - pct_quarters_stretched: Percentage of quarters above threshold
            - stretched_quarters: List of quarter indices above threshold
            - max_stretch_ratio: Highest quarterly ratio
        """
        if 'quarter' not in results.columns:
            # Try to derive quarters from months
            if 'month' not in results.columns:
                return {
                    'pct_quarters_stretched': 0.0,
                    'stretched_quarters': [],
                    'max_stretch_ratio': 0.0
                }

            results = results.copy()
            results['quarter'] = results['month'].apply(lambda m: (m - 1) // 3 + 1)

        # Calculate quarterly bookings
        if 'projected_bookings' not in results.columns:
            return {
                'pct_quarters_stretched': 0.0,
                'stretched_quarters': [],
                'max_stretch_ratio': 0.0
            }

        quarterly_bookings = results.groupby('quarter')['projected_bookings'].sum()

        if quarterly_bookings.empty:
            return {
                'pct_quarters_stretched': 0.0,
                'stretched_quarters': [],
                'max_stretch_ratio': 0.0
            }

        # Assume original plan = average quarterly bookings
        avg_quarterly = quarterly_bookings.mean()

        if avg_quarterly == 0:
            return {
                'pct_quarters_stretched': 0.0,
                'stretched_quarters': [],
                'max_stretch_ratio': 0.0
            }

        # Calculate ratio for each quarter
        stretch_ratios = quarterly_bookings / avg_quarterly
        stretched_quarters = [
            q for q, ratio in stretch_ratios.items()
            if ratio > self.stretch_threshold
        ]

        pct_stretched = (len(stretched_quarters) / len(stretch_ratios)) * 100

        return {
            'pct_quarters_stretched': round(pct_stretched, 2),
            'stretched_quarters': stretched_quarters,
            'max_stretch_ratio': round(stretch_ratios.max(), 2)
        }

    def _calculate_confidence_risk(self, results: pd.DataFrame) -> dict:
        """
        What % of bookings come from low-confidence segments?

        Low confidence = sparse historical data, using fallback values.
        Higher % = riskier plan.

        Args:
            results: Allocation results DataFrame

        Returns:
            Dict with keys:
            - low_confidence_bookings: Total bookings from low-confidence segments
            - low_confidence_pct: Percentage of total bookings
            - risk_level: 'Low' / 'Medium' / 'High'
        """
        if 'confidence_level' not in results.columns or 'projected_bookings' not in results.columns:
            return {
                'low_confidence_bookings': 0.0,
                'low_confidence_pct': 0.0,
                'risk_level': 'Unknown'
            }

        total_bookings = results['projected_bookings'].sum()

        if total_bookings == 0:
            return {
                'low_confidence_bookings': 0.0,
                'low_confidence_pct': 0.0,
                'risk_level': 'Unknown'
            }

        # Filter to low confidence rows
        low_conf_mask = results['confidence_level'].str.lower() == 'low'
        low_conf_bookings = results[low_conf_mask]['projected_bookings'].sum()

        low_conf_pct = (low_conf_bookings / total_bookings) * 100

        # Determine risk level using config-driven thresholds.
        # These thresholds are set in config.yaml (system.confidence_risk_*_max_pct)
        # and stored in __init__, keeping them aligned with ValidationEngine's
        # pass/fail gate (system.low_confidence_threshold).
        if low_conf_pct < self.conf_low_max:
            risk_level = 'Low'
        elif low_conf_pct < self.conf_medium_max:
            risk_level = 'Medium'
        else:
            risk_level = 'High'

        return {
            'low_confidence_bookings': round(low_conf_bookings, 1),
            'low_confidence_pct': round(low_conf_pct, 2),
            'risk_level': risk_level
        }

    def print_comparison_report(self, comparison: Dict[str, Any]) -> None:
        """
        Pretty-print the full comparison report to stdout.

        Displays metric diffs, volatility, concentration, capacity, stretch, and
        confidence risk in a readable, organized format.

        Args:
            comparison: Dict returned from compare()
        """
        print("\n" + "=" * 160)
        print("VERSION COMPARISON REPORT".center(160))
        print("=" * 160 + "\n")

        # 1. Metric Diffs
        print("METRIC COMPARISON")
        print("-" * 160)
        metric_diffs = comparison.get('metric_diffs', pd.DataFrame())
        if not metric_diffs.empty:
            print(metric_diffs.to_string(index=False))
        else:
            print("No metric data available.")
        print()

        # 2. Allocation Shift
        print("ALLOCATION SHIFT (Segment Share Changes)")
        print("-" * 160)
        allocation_shift = comparison.get('allocation_shift', pd.DataFrame())
        if not allocation_shift.empty:
            print(allocation_shift.to_string(index=False))
        else:
            print("No allocation data available.")
        print()

        # 3. Volatility Analysis
        print("VOLATILITY ANALYSIS (Lower = Smoother)")
        print("-" * 160)
        volatility = comparison.get('volatility_analysis', {})
        for version_id, metrics in volatility.items():
            print(f"\n{version_id}:")
            print(f"  Std Dev:         {metrics.get('std_dev', 0):.2f}")
            print(f"  Coefficient of Variation: {metrics.get('cv', 0):.3f}  (lower = more predictable)")
            print(f"  Max/Min Ratio:   {metrics.get('max_min_ratio', 0):.2f}")
        print()

        # 4. Concentration Risk (HHI)
        print("CONCENTRATION RISK (HHI — Higher = More Concentrated = Riskier)")
        print("-" * 160)
        hhi = comparison.get('concentration_risk', {})
        for version_id, score in hhi.items():
            risk = 'High' if score > 0.35 else 'Medium' if score > 0.25 else 'Low'
            print(f"  {version_id}: {score:.3f}  ({risk} concentration)")
        print()

        # 5. Capacity Utilisation Variance
        print("CAPACITY UTILISATION VARIANCE (Lower = More Even)")
        print("-" * 160)
        capacity_var = comparison.get('capacity_utilisation_variance', {})
        for version_id, metrics in capacity_var.items():
            print(f"\n{version_id}:")
            print(f"  Variance:        {metrics.get('variance', 0):.2f}")
            print(f"  Mean Util:       {metrics.get('mean_utilisation', 0):.2f}")
            print(f"  Min Util:        {metrics.get('min_utilisation', 0):.2f}")
            print(f"  Max Util:        {metrics.get('max_utilisation', 0):.2f}")
        print()

        # 6. Stretch Exposure
        print("STRETCH EXPOSURE (Quarters > 120% of Plan)")
        print("-" * 160)
        stretch = comparison.get('stretch_exposure', {})
        for version_id, metrics in stretch.items():
            print(f"  {version_id}: {metrics.get('pct_quarters_stretched', 0):.1f}%  "
                  f"(max ratio: {metrics.get('max_stretch_ratio', 0):.2f})")
        print()

        # 7. Confidence Risk
        print("CONFIDENCE RISK (Bookings from Low-Confidence Segments)")
        print("-" * 160)
        confidence = comparison.get('confidence_risk', {})
        for version_id, metrics in confidence.items():
            print(f"  {version_id}: {metrics.get('low_confidence_pct', 0):.1f}%  "
                  f"({metrics.get('risk_level', 'Unknown')} risk)")
        print()

        print("=" * 160)

    @staticmethod
    def _format_currency(value: float) -> float:
        """
        Express a raw dollar value in millions (1 d.p.).

        Delegates to utils.format_currency so the scale and precision are
        identical to what WhatIfEngine produces, making tables from both
        modules directly comparable.
        """
        return format_currency(value)

    def to_dataframe(
        self,
        comparison: Dict[str, Any]
    ) -> pd.DataFrame:
        """
        Export comparison results as a clean, analysis-ready DataFrame.

        Combines all metrics into a single wide-format table suitable for
        Jupyter notebooks or further analysis.

        Args:
            comparison: Dict returned from compare()

        Returns:
            pd.DataFrame with all metrics (one row per version)
        """
        metrics_table = comparison.get('metrics_table', pd.DataFrame())

        if metrics_table.empty:
            return pd.DataFrame()

        # Round numeric columns
        numeric_cols = [
            'total_bookings', 'total_pipeline', 'avg_productivity_per_ae',
            'monthly_volatility', 'coefficient_of_variation', 'max_min_ratio',
            'herfindahl_index', 'capacity_utilisation_variance',
            'stretch_exposure_pct', 'confidence_weighted_bookings'
        ]

        df = metrics_table.copy()

        for col in numeric_cols:
            if col in df.columns:
                df[col] = df[col].round(2)

        return df
