"""
What-If Engine — Scenario Analysis Module

Purpose:
    Models 2-5 named risk scenarios against the base plan. Each scenario applies
    a bundle of perturbations to the config, re-runs the planning pipeline, and
    compares results to the base.

    This module lets GTM leaders answer "What if market conditions change?" and
    quantifies the impact on bookings, capacity, hiring, and risk.

Key Concepts:
    - Scenario: A named bundle of perturbations (e.g., "Q2 attrition spike")
    - Perturbation: A change to one config value (e.g., ae_headcount_change)
    - Comparison: Side-by-side metrics showing delta from base vs scenario

Usage:
    engine = WhatIfEngine(config)
    comparison_df = engine.run_scenarios(base_results, base_summary, pipeline_fn)
    engine.print_comparison(comparison_df)

Classes:
    WhatIfEngine — Main orchestrator for scenario modeling
"""

import copy
import pandas as pd
import numpy as np
from typing import Callable, Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, asdict
from .utils import format_currency


@dataclass
class ScenarioComparison:
    """Container for scenario comparison metrics."""
    scenario_name: str
    scenario_description: str
    total_bookings: float
    total_saos: int
    total_ae_hc: int
    bookings_delta: float
    saos_delta: int
    hc_delta: int
    bookings_delta_pct: float
    saos_delta_pct: float
    hc_delta_pct: float
    capacity_utilisation: float
    monthly_volatility: float
    monthly_volatility_delta: float
    risk_flags: List[str]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for DataFrame conversion."""
        return asdict(self)


class WhatIfEngine:
    """
    What-If Scenario Engine for GTM Planning.

    Runs named scenarios (e.g., "Q2 attrition spike", "EOR pricing pressure")
    against a base plan and generates a comprehensive comparison report.

    Attributes:
        config (dict): Base configuration dict with what_if_scenarios defined
        scenarios (list): List of scenario dicts from config (each with name, description, perturbations)
    """

    def __init__(self, config: dict):
        """
        Initialize the What-If Engine.

        Args:
            config: Configuration dict with 'what_if_scenarios' key containing
                   list of scenario defs, each with 'name', 'description', 'perturbations'

        Raises:
            ValueError: If no scenarios defined in config, or invalid scenario structure
        """
        if not isinstance(config, dict):
            raise ValueError("config must be a dict")

        if 'what_if_scenarios' not in config:
            raise ValueError("config must contain 'what_if_scenarios' key")

        scenarios = config.get('what_if_scenarios', [])
        if not isinstance(scenarios, list):
            raise ValueError("what_if_scenarios must be a list")

        if len(scenarios) == 0:
            raise ValueError("At least one scenario must be defined in what_if_scenarios")

        if len(scenarios) > 5:
            raise ValueError("Maximum 5 scenarios allowed (got {})".format(len(scenarios)))

        # Validate scenario structure
        for scenario in scenarios:
            if 'name' not in scenario or 'perturbations' not in scenario:
                raise ValueError(
                    f"Each scenario must have 'name' and 'perturbations'. "
                    f"Got: {scenario.keys()}"
                )

        self.config = config
        # Filter to only enabled scenarios (default True if 'enabled' key not present)
        self.scenarios = [s for s in scenarios if s.get('enabled', True)]
        if len(self.scenarios) == 0:
            raise ValueError("No enabled scenarios found. Set enabled: true on at least one scenario.")
        self._scenario_results: Dict[str, dict] = {}

    def run_scenarios(
        self,
        base_results: pd.DataFrame,
        base_summary: dict,
        run_pipeline_fn: Callable[[dict], Tuple[pd.DataFrame, dict]]
    ) -> pd.DataFrame:
        """
        Run each what-if scenario and compare to base.

        Args:
            base_results: The base plan allocation results DataFrame with columns
                         like [segment, month, share, required_SAOs, projected_pipeline,
                         projected_bookings, projected_deals, etc.]
            base_summary: Summary dict from base plan with keys like
                         {'total_bookings', 'total_saos', 'total_ae_hc',
                          'productivity_per_ae', 'monthly_volatility', ...}
            run_pipeline_fn: Callable(config: dict) -> (results_df, summary_dict).
                            This is the full planning pipeline function that
                            takes a modified config and returns results.

        Returns:
            pd.DataFrame with comparison results, one row per scenario:
                Columns: [scenario, description, total_bookings, total_saos, total_ae_hc,
                         bookings_delta, saos_delta, hc_delta,
                         bookings_delta_pct, saos_delta_pct, hc_delta_pct,
                         capacity_utilisation, monthly_volatility, monthly_volatility_delta,
                         risk_flags]

        Raises:
            ValueError: If run_pipeline_fn fails or returns invalid output
            TypeError: If base_results or base_summary wrong type
        """
        if not isinstance(base_results, pd.DataFrame):
            raise TypeError("base_results must be a pandas DataFrame")

        if not isinstance(base_summary, dict):
            raise TypeError("base_summary must be a dict")

        if not callable(run_pipeline_fn):
            raise TypeError("run_pipeline_fn must be callable")

        comparisons = []

        for scenario in self.scenarios:
            scenario_name = scenario.get('name')
            scenario_description = scenario.get('description', '')

            # Deep-copy config and apply perturbations
            scenario_config = self._apply_perturbations(
                self.config,
                scenario.get('perturbations', {})
            )

            # Run pipeline with scenario config
            try:
                scenario_results, scenario_summary = run_pipeline_fn(scenario_config)
            except Exception as e:
                raise ValueError(
                    f"Pipeline failed for scenario '{scenario_name}': {str(e)}"
                )

            # Store results for later reference
            self._scenario_results[scenario_name] = {
                'config': scenario_config,
                'results': scenario_results,
                'summary': scenario_summary
            }

            # Compare against base
            comparison = self._compare_results(
                base_summary,
                scenario_summary,
                scenario_name,
                scenario_description
            )

            comparisons.append(comparison.to_dict())

        # Convert to DataFrame
        comparison_df = pd.DataFrame(comparisons)

        return comparison_df

    def _apply_perturbations(
        self,
        base_config: dict,
        perturbations: dict
    ) -> dict:
        """
        Deep-copy base config and apply perturbations.

        Supported perturbation types:

        1. ae_headcount_change: {month_N: delta} — adds/removes AEs in specific months
           Example: {month_4: -3, month_5: -2} means -3 AEs in Apr, -2 in May

        2. backfill_delay_months: int — overrides backfill delay setting
           Example: 3 means extend backfill delay from default 2 to 3 months

        3. asp_multiplier: {product: multiplier} — scales ASP for a product
           Example: {EOR: 0.85} means EOR ASP drops to 85% of base

        4. win_rate_multiplier: {dimension: multiplier} — scales win rate
           Example: {EOR: 0.90} means win rate becomes 90% of base for EOR

        5. channel_share_ceiling: {channel: new_ceiling} — overrides share ceiling
           Example: {Marketing: 0.25} means Marketing can't exceed 25% of allocation

        6. lead_volume_multiplier: {channel: multiplier} — scales lead volume
           Example: {Marketing: 0.70} means Marketing leads drop to 70% of base

        7. cancel_tranches: [indices] — removes hiring tranches by index
           Example: [3, 4] cancels the 3rd and 4th tranches (0-indexed)

        8. add_region: str — enables a new region dimension
           Example: "APAC" adds APAC as an active region

        9. region_performance_multiplier: {region: multiplier} — scales regional performance
           Example: {APAC: 0.60} means APAC at 60% of global performance initially

        Args:
            base_config: The base configuration dict to copy and modify
            perturbations: Dict of perturbations keyed by type

        Returns:
            Modified config dict (original is not mutated)

        Raises:
            KeyError: If perturbation references non-existent config path
        """
        # Deep copy to avoid mutating the original
        config = copy.deepcopy(base_config)

        # 1. AE headcount changes (month_N keys)
        if 'ae_headcount_change' in perturbations:
            changes = perturbations['ae_headcount_change']
            if not isinstance(changes, dict):
                raise ValueError("ae_headcount_change must be a dict {month_N: delta}")

            # Store as a custom config field for the pipeline to consume
            config['_ae_headcount_changes'] = changes

        # 2. Backfill delay
        if 'backfill_delay_months' in perturbations:
            delay = perturbations['backfill_delay_months']
            if not isinstance(delay, int) or delay < 0:
                raise ValueError("backfill_delay_months must be a non-negative int")
            config['ae_model']['attrition']['backfill_delay_months'] = delay

        # 3. ASP multiplier
        if 'asp_multiplier' in perturbations:
            multipliers = perturbations['asp_multiplier']
            if not isinstance(multipliers, dict):
                raise ValueError("asp_multiplier must be a dict {product: multiplier}")

            # Store as custom field
            if '_asp_multiplier' not in config:
                config['_asp_multiplier'] = {}
            config['_asp_multiplier'].update(multipliers)

        # 4. Win rate multiplier
        if 'win_rate_multiplier' in perturbations:
            multipliers = perturbations['win_rate_multiplier']
            if not isinstance(multipliers, dict):
                raise ValueError("win_rate_multiplier must be a dict {dimension: multiplier}")

            if '_win_rate_multiplier' not in config:
                config['_win_rate_multiplier'] = {}
            config['_win_rate_multiplier'].update(multipliers)

        # 5. Channel share ceiling
        if 'channel_share_ceiling' in perturbations:
            ceilings = perturbations['channel_share_ceiling']
            if not isinstance(ceilings, dict):
                raise ValueError("channel_share_ceiling must be a dict {channel: new_ceiling}")

            if 'allocation' not in config:
                config['allocation'] = {}
            if 'constraints' not in config['allocation']:
                config['allocation']['constraints'] = {}
            if 'segment_overrides' not in config['allocation']['constraints']:
                config['allocation']['constraints']['segment_overrides'] = {}

            for channel, ceiling in ceilings.items():
                key = f"*.{channel}"  # Wildcard for any product with this channel
                if key not in config['allocation']['constraints']['segment_overrides']:
                    config['allocation']['constraints']['segment_overrides'][key] = {}
                config['allocation']['constraints']['segment_overrides'][key]['ceiling'] = ceiling

        # 6. Lead volume multiplier
        if 'lead_volume_multiplier' in perturbations:
            multipliers = perturbations['lead_volume_multiplier']
            if not isinstance(multipliers, dict):
                raise ValueError("lead_volume_multiplier must be a dict {channel: multiplier}")

            if '_lead_volume_multiplier' not in config:
                config['_lead_volume_multiplier'] = {}
            config['_lead_volume_multiplier'].update(multipliers)

        # 7. Cancel tranches
        if 'cancel_tranches' in perturbations:
            indices = perturbations['cancel_tranches']
            if not isinstance(indices, list):
                raise ValueError("cancel_tranches must be a list of indices")

            hiring_plan = config['ae_model']['hiring_plan']
            # Deduplicate and validate indices
            unique_indices = list(set(indices))
            invalid = [i for i in unique_indices if not (0 <= i < len(hiring_plan))]
            if invalid:
                raise ValueError(
                    f"cancel_tranches indices out of range: {invalid}. "
                    f"Hiring plan has {len(hiring_plan)} tranches (0-indexed)."
                )
            # Remove in reverse order to preserve indices
            for idx in sorted(unique_indices, reverse=True):
                del hiring_plan[idx]

        # 8. Add region
        if 'add_region' in perturbations:
            region = perturbations['add_region']
            if not isinstance(region, str):
                raise ValueError("add_region must be a string (region name)")

            config['dimensions']['region']['enabled'] = True
            if region not in config['dimensions']['region']['values']:
                config['dimensions']['region']['values'].append(region)

        # 9. Region performance multiplier
        if 'region_performance_multiplier' in perturbations:
            multipliers = perturbations['region_performance_multiplier']
            if not isinstance(multipliers, dict):
                raise ValueError("region_performance_multiplier must be a dict {region: multiplier}")

            if '_region_performance_multiplier' not in config:
                config['_region_performance_multiplier'] = {}
            config['_region_performance_multiplier'].update(multipliers)

        return config

    def _compare_results(
        self,
        base_summary: dict,
        scenario_summary: dict,
        scenario_name: str,
        scenario_description: str = ''
    ) -> ScenarioComparison:
        """
        Calculate deltas between base and scenario across all key metrics.

        Extracts standard metrics from summary dicts, computes absolute and
        percentage deltas, identifies risk flags (e.g., negative bookings delta,
        high volatility, capacity constraints).

        Args:
            base_summary: Summary dict from base plan
            scenario_summary: Summary dict from scenario plan
            scenario_name: Name of the scenario
            scenario_description: Optional description

        Returns:
            ScenarioComparison object with all delta metrics

        Note:
            If a metric is missing from summary dict, defaults to 0 or flag as unknown.
        """
        # Extract key metrics, with defaults
        def get_metric(summary: dict, key: str, default: float = 0.0) -> float:
            """Safely extract metric from summary dict."""
            return summary.get(key, default)

        # Base metrics
        base_bookings = get_metric(base_summary, 'total_bookings', 0.0)
        base_saos = get_metric(base_summary, 'total_saos', 0)
        base_hc = get_metric(base_summary, 'total_ae_hc', 0)
        base_volatility = get_metric(base_summary, 'monthly_volatility', 0.0)

        # Scenario metrics
        scenario_bookings = get_metric(scenario_summary, 'total_bookings', 0.0)
        scenario_saos = get_metric(scenario_summary, 'total_saos', 0)
        scenario_hc = get_metric(scenario_summary, 'total_ae_hc', 0)
        scenario_volatility = get_metric(scenario_summary, 'monthly_volatility', 0.0)
        scenario_capacity_util = get_metric(scenario_summary, 'capacity_utilisation', 0.0)

        # Compute absolute deltas
        bookings_delta = scenario_bookings - base_bookings
        saos_delta = scenario_saos - base_saos
        hc_delta = scenario_hc - base_hc
        volatility_delta = scenario_volatility - base_volatility

        # Compute percentage deltas (avoid division by zero)
        bookings_delta_pct = (
            (bookings_delta / base_bookings * 100)
            if base_bookings != 0 else 0.0
        )
        saos_delta_pct = (
            (saos_delta / base_saos * 100)
            if base_saos != 0 else 0.0
        )
        hc_delta_pct = (
            (hc_delta / base_hc * 100)
            if base_hc != 0 else 0.0
        )

        # Identify risk flags
        risk_flags: List[str] = []

        # Bookings miss
        if bookings_delta < 0:
            miss_pct = abs(bookings_delta_pct)
            risk_flags.append(f"Bookings down {miss_pct:.1f}%")

        # Capacity constraint
        if scenario_capacity_util > 0.95:
            risk_flags.append(f"Capacity utilisation {scenario_capacity_util:.1%} (tight)")

        # Volatility increase
        if volatility_delta > 0:
            risk_flags.append(f"Monthly volatility up {volatility_delta:.2f}")

        # HC impact
        if hc_delta < 0:
            risk_flags.append(f"AE HC reduced by {abs(hc_delta)}")

        # SAO demand
        if saos_delta > base_saos * 0.25:
            risk_flags.append(f"SAO demand up {saos_delta_pct:.1f}% (may strain capacity)")

        return ScenarioComparison(
            scenario_name=scenario_name,
            scenario_description=scenario_description,
            total_bookings=self._format_currency(scenario_bookings),
            total_saos=int(scenario_saos),
            total_ae_hc=int(scenario_hc),
            bookings_delta=self._format_currency(bookings_delta),
            saos_delta=int(saos_delta),
            hc_delta=int(hc_delta),
            bookings_delta_pct=round(bookings_delta_pct, 2),
            saos_delta_pct=round(saos_delta_pct, 2),
            hc_delta_pct=round(hc_delta_pct, 2),
            capacity_utilisation=round(scenario_capacity_util, 3),
            monthly_volatility=round(scenario_volatility, 2),
            monthly_volatility_delta=round(volatility_delta, 2),
            risk_flags=risk_flags
        )

    @staticmethod
    def _format_currency(value: float) -> float:
        """
        Express a raw dollar value in millions (1 d.p.).

        Delegates to utils.format_currency so scale and precision are
        identical to what VersionComparator produces. A leader looking at
        both a what-if table and a comparator table sees the same units.
        """
        return format_currency(value)

    def print_comparison(self, comparison_df: pd.DataFrame) -> None:
        """
        Pretty-print the scenario comparison table to stdout.

        Formats numbers as currency, highlights risk flags, and presents
        comparison in a readable table format.

        Args:
            comparison_df: DataFrame from run_scenarios()
        """
        if comparison_df.empty:
            print("No scenarios to compare.")
            return

        print("\n" + "=" * 140)
        print("WHAT-IF SCENARIO COMPARISON".center(140))
        print("=" * 140 + "\n")

        for idx, row in comparison_df.iterrows():
            scenario_name = row['scenario_name']
            description = row['scenario_description']

            print(f"Scenario {idx + 1}: {scenario_name}")
            print(f"  Description: {description}")
            print(f"  {'-' * 136}")

            # Key metrics
            print(f"  Bookings:           ${row['total_bookings']:.0f}M  "
                  f"(delta: ${row['bookings_delta']:.0f}M / {row['bookings_delta_pct']:+.1f}%)")
            print(f"  SAOs:               {row['total_saos']:,}  "
                  f"(delta: {row['saos_delta']:+,} / {row['saos_delta_pct']:+.1f}%)")
            print(f"  AE Headcount:       {row['total_ae_hc']}  "
                  f"(delta: {row['hc_delta']:+d} / {row['hc_delta_pct']:+.1f}%)")
            print(f"  Capacity Util:      {row['capacity_utilisation']:.1%}")
            print(f"  Monthly Volatility: {row['monthly_volatility']:.2f}  "
                  f"(delta: {row['monthly_volatility_delta']:+.2f})")

            # Risk flags
            if row['risk_flags']:
                print(f"  Risk Flags:")
                for flag in row['risk_flags']:
                    print(f"    • {flag}")
            else:
                print(f"  Risk Flags: None")

            print()

        print("=" * 140)

    def to_dataframe(self, comparison_df: pd.DataFrame) -> pd.DataFrame:
        """
        Export comparison results as a clean, analysis-ready DataFrame.

        Useful for integration with Jupyter notebooks or further analysis.
        Rounds numeric columns to 2 decimal places and formats strings.

        Args:
            comparison_df: DataFrame from run_scenarios()

        Returns:
            Cleaned DataFrame ready for export/analysis
        """
        df = comparison_df.copy()

        # Round numeric columns
        numeric_cols = [
            'total_bookings', 'total_saos', 'total_ae_hc',
            'bookings_delta', 'saos_delta', 'hc_delta',
            'bookings_delta_pct', 'saos_delta_pct', 'hc_delta_pct',
            'capacity_utilisation', 'monthly_volatility', 'monthly_volatility_delta'
        ]

        for col in numeric_cols:
            if col in df.columns:
                df[col] = df[col].round(2)

        # Convert risk_flags list to string
        if 'risk_flags' in df.columns:
            df['risk_flags'] = df['risk_flags'].apply(
                lambda x: ' | '.join(x) if isinstance(x, list) else str(x)
            )

        return df

    def get_scenario_details(self, scenario_name: str) -> dict:
        """
        Retrieve detailed results for a specific scenario.

        Useful for deep-diving into a particular scenario's full allocation
        results and summary metrics.

        Args:
            scenario_name: Name of the scenario to retrieve

        Returns:
            Dict with 'config', 'results' (DataFrame), 'summary' (dict)

        Raises:
            KeyError: If scenario not found or hasn't been run yet
        """
        if scenario_name not in self._scenario_results:
            raise KeyError(
                f"Scenario '{scenario_name}' not found. "
                f"Available: {list(self._scenario_results.keys())}"
            )

        return self._scenario_results[scenario_name]
