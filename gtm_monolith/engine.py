"""
GTM Planning Engine — Monolith

Single-file consolidation of the entire GTM planning pipeline:
  GTMConfig, DataLayer, TargetLayer, CapacityLayer, EconomicsLayer,
  OptimizerLayer, ValidationLayer, RecoveryLayer, AnalysisLayer,
  VersionStore, and the full pipeline orchestrator.

Backward-compatible: produces identical outputs to the multi-module engine.
"""

import copy
import hashlib
import json
import logging
import math
import yaml
import numpy as np
import pandas as pd
from copy import deepcopy
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from scipy.optimize import minimize, curve_fit
from functools import lru_cache
import threading

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# UTILITIES
# ═══════════════════════════════════════════════════════════════════════

def compute_config_hash(config_dict: Dict[str, Any]) -> str:
    config_json = json.dumps(config_dict, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(config_json.encode('utf-8')).hexdigest()


def format_currency(value: float) -> float:
    return round(value / 1_000_000, 1)


# ═══════════════════════════════════════════════════════════════════════
# GTMConfig  (replaces ConfigManager + utils)
# ═══════════════════════════════════════════════════════════════════════

class GTMConfig:
    """Load, validate, and provide access to GTM config via dot-notation."""

    def __init__(self, config_path: str) -> None:
        config_path_obj = Path(config_path)
        if not config_path_obj.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        try:
            with open(config_path_obj, 'r') as f:
                self._config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ValueError(f"YAML parsing failed: {e}")
        if self._config is None:
            self._config = {}
        self.validate()
        self._active_dimensions = self._compute_active_dimensions()

    def get(self, key: str, default: Any = None) -> Any:
        keys = key.split('.')
        value = self._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default
        return value if value is not None else default

    def get_active_dimensions(self) -> List[str]:
        return self._active_dimensions

    def get_segment_keys(self) -> List[str]:
        return self.get_active_dimensions()

    def override(self, overrides: Dict[str, Any]) -> 'GTMConfig':
        new_config_dict = copy.deepcopy(self._config)
        for key_path, value in overrides.items():
            keys = key_path.split('.')
            current = new_config_dict
            for k in keys[:-1]:
                if k not in current:
                    current[k] = {}
                current = current[k]
            current[keys[-1]] = value
        new_manager = GTMConfig.__new__(GTMConfig)
        new_manager._config = new_config_dict
        new_manager.validate()
        new_manager._active_dimensions = new_manager._compute_active_dimensions()
        return new_manager

    @classmethod
    def from_dict(cls, config_dict: dict) -> 'GTMConfig':
        instance = cls.__new__(cls)
        instance._config = copy.deepcopy(config_dict)
        instance.validate()
        instance._active_dimensions = instance._compute_active_dimensions()
        return instance

    def validate(self) -> None:
        required_sections = ['dimensions', 'targets', 'allocation', 'economics', 'ae_model', 'system']
        for section in required_sections:
            if section not in self._config:
                raise ValueError(f"Missing required config section: {section}")

        seasonality = self.get('targets.seasonality_weights')
        if seasonality is not None:
            weights_sum = sum(seasonality.values())
            tolerance = self.get('system.tolerance', 0.001)
            if abs(weights_sum - 1.0) > tolerance:
                raise ValueError(
                    f"Seasonality weights sum to {weights_sum}, expected 1.0 (tolerance: {tolerance})"
                )

        share_floor = self.get('allocation.constraints.share_floor', 0.0)
        share_ceiling = self.get('allocation.constraints.share_ceiling', 1.0)
        if share_floor >= share_ceiling:
            raise ValueError(
                f"Share floor ({share_floor}) must be less than share ceiling ({share_ceiling})"
            )

        hiring_plan = self.get('ae_model.hiring_plan', [])
        for i, tranche in enumerate(hiring_plan):
            month = tranche.get('start_month')
            if month is None or not (1 <= month <= 12):
                raise ValueError(
                    f"Hiring tranche {i} has invalid start_month: {month}. Must be 1-12."
                )

        high_threshold = self.get('economics.confidence.high_threshold', 30)
        medium_threshold = self.get('economics.confidence.medium_threshold', 15)
        if medium_threshold >= high_threshold:
            raise ValueError(
                f"Medium confidence threshold ({medium_threshold}) must be less than "
                f"high confidence threshold ({high_threshold})"
            )

        annual_target = self.get('targets.annual_target')
        if annual_target is not None and annual_target <= 0:
            raise ValueError(f"Annual target must be positive, got {annual_target}")

        cash_cycle = self.get('economics.cash_cycle', {})
        if isinstance(cash_cycle, dict) and cash_cycle.get('enabled', False):
            tolerance = self.get('system.tolerance', 0.001)
            default_dist = cash_cycle.get('default_distribution')
            if not default_dist or not isinstance(default_dist, dict):
                raise ValueError(
                    "economics.cash_cycle.default_distribution is required when cash_cycle is enabled"
                )
            dist_sum = sum(default_dist.values())
            if abs(dist_sum - 1.0) > tolerance:
                raise ValueError(
                    f"cash_cycle.default_distribution sums to {dist_sum}, expected 1.0 "
                    f"(tolerance: {tolerance})"
                )
            for key in default_dist:
                if not isinstance(key, int) or key < 0:
                    raise ValueError(
                        f"cash_cycle.default_distribution keys must be non-negative integers, "
                        f"got {key!r}"
                    )
            product_overrides = cash_cycle.get('product_overrides', {})
            for product, dist in product_overrides.items():
                if not isinstance(dist, dict):
                    raise ValueError(
                        f"cash_cycle.product_overrides[{product}] must be a dict, "
                        f"got {type(dist).__name__}"
                    )
                override_sum = sum(dist.values())
                if abs(override_sum - 1.0) > tolerance:
                    raise ValueError(
                        f"cash_cycle.product_overrides[{product}] sums to {override_sum}, "
                        f"expected 1.0 (tolerance: {tolerance})"
                    )
                for key in dist:
                    if not isinstance(key, int) or key < 0:
                        raise ValueError(
                            f"cash_cycle.product_overrides[{product}] keys must be "
                            f"non-negative integers, got {key!r}"
                        )
            grain = cash_cycle.get('grain', 'product')
            dimensions = self.get('dimensions', {})
            if grain not in dimensions:
                raise ValueError(f"cash_cycle.grain '{grain}' is not a configured dimension")
            grain_config = dimensions.get(grain, {})
            if not isinstance(grain_config, dict) or not grain_config.get('enabled', False):
                raise ValueError(
                    f"cash_cycle.grain '{grain}' refers to a disabled dimension. "
                    f"Enable it in dimensions.{grain}.enabled first."
                )

    def to_dict(self) -> Dict[str, Any]:
        return copy.deepcopy(self._config)

    def hash(self) -> str:
        return compute_config_hash(self._config)

    def _compute_active_dimensions(self) -> List[str]:
        active = []
        dimensions = self.get('dimensions', {})
        for dim_name, dim_config in dimensions.items():
            if isinstance(dim_config, dict) and dim_config.get('enabled', False):
                active.append(dim_name)
        return active


# ═══════════════════════════════════════════════════════════════════════
# DataLayer  (replaces DataLoader)
# ═══════════════════════════════════════════════════════════════════════

class DataLayer:
    STANDARD_METRICS = ['ASP', 'CW rate', 'close_win_rate', 'Revenue', 'SAOs', 'Month', 'Year']

    def __init__(self, config: GTMConfig) -> None:
        self.config = config
        self.active_dimensions = config.get_active_dimensions()
        self.confidence_high = config.get('economics.confidence.high_threshold', 6)
        self.confidence_medium = config.get('economics.confidence.medium_threshold', 3)
        self.fallback_hierarchy = config.get(
            'economics.confidence.fallback_hierarchy', ['segment', 'product', 'global']
        )
        self.default_fallback_multiplier = config.get(
            'economics.confidence.default_fallback_multiplier', 0.80
        )
        self.supersized_threshold = config.get('system.supersized_deal_threshold', 3.0)

    def load(self, file_path: str, sheet_name: Optional[str] = None) -> pd.DataFrame:
        path_obj = Path(file_path)
        if not path_obj.exists():
            raise FileNotFoundError(f"Data file not found: {file_path}")
        suffix = path_obj.suffix.lower()
        if suffix == '.csv':
            return pd.read_csv(file_path)
        elif suffix in ['.xlsx', '.xls']:
            if sheet_name is None:
                return pd.read_excel(file_path)
            return pd.read_excel(file_path, sheet_name=sheet_name)
        raise ValueError(f"Unsupported file format: {suffix}. Use .csv, .xlsx, or .xls")

    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy(deep=False)
        df = self._filter_columns(df)
        df = self._standardize_columns(df)
        required_metrics = ['asp', 'close_win_rate']
        missing_metrics = [c for c in required_metrics if c not in df.columns]
        if missing_metrics:
            logger.warning(f"Missing required metric columns after standardization: {missing_metrics}.")
        df = self._normalize_dimension_names(df)
        df = self._score_confidence(df)
        df = self._apply_fallbacks(df)
        df = self._flag_supersized(df)
        return df

    def _filter_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        df_columns_lower = {col.lower(): col for col in df.columns}
        cols_to_keep = []
        for dim in self.active_dimensions:
            dim_lower = dim.lower()
            if dim_lower in df_columns_lower:
                cols_to_keep.append(df_columns_lower[dim_lower])
            else:
                cols_to_keep.append(dim)
        for metric in self.STANDARD_METRICS:
            if metric in df.columns:
                cols_to_keep.append(metric)
        existing_cols = [c for c in cols_to_keep if c in df.columns]
        return df[existing_cols]

    def _normalize_dimension_names(self, df: pd.DataFrame) -> pd.DataFrame:
        rename_map = {}
        for dim in self.active_dimensions:
            dim_lower = dim.lower()
            if dim_lower in df.columns:
                continue
            for col in df.columns:
                if col.lower() == dim_lower and col != dim_lower:
                    rename_map[col] = dim_lower
                    break
        if rename_map:
            df = df.rename(columns=rename_map)
        return df

    def _standardize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        rename_map = {}
        variations = {
            'close_win_rate': ['CW rate', 'CW_rate', 'close_win_rate', 'win_rate'],
            'revenue': ['Revenue', 'Bookings', 'revenue', '2025 Revenue'],
            'saos': ['SAOs', 'SAO', 'saos', '2025 SAOs'],
            'asp': ['ASP', 'asp', 'avg_selling_price'],
            'month': ['Month', 'month'],
            'year': ['Year', 'year'],
        }
        for standard_name, aliases in variations.items():
            for col in df.columns:
                if col in aliases and col != standard_name:
                    rename_map[col] = standard_name
        return df.rename(columns=rename_map)

    def _score_confidence(self, df: pd.DataFrame) -> pd.DataFrame:
        if len(self.active_dimensions) == 0:
            df['confidence_level'] = 'high'
            return df
        segment_counts = df.groupby(self.active_dimensions, dropna=False).size().reset_index(name='deal_count')

        def assign_confidence(count):
            if count >= self.confidence_high:
                return 'high'
            elif count >= self.confidence_medium:
                return 'medium'
            return 'low'

        segment_counts['confidence_level'] = segment_counts['deal_count'].apply(assign_confidence)
        df = df.merge(
            segment_counts[self.active_dimensions + ['confidence_level']],
            on=self.active_dimensions, how='left'
        )
        return df

    def _apply_fallbacks(self, df: pd.DataFrame) -> pd.DataFrame:
        df['fallback_source'] = None
        low_conf_mask = df['confidence_level'] == 'low'
        if not low_conf_mask.any():
            return df
        metric_cols = ['asp', 'close_win_rate', 'revenue', 'saos']
        metric_cols_present = [c for c in metric_cols if c in df.columns]
        if metric_cols_present:
            global_avg = df[metric_cols_present].mean()
            for col in metric_cols_present:
                mask = low_conf_mask & (df[col].isna() | (df[col] == 0))
                df.loc[mask, col] = global_avg[col] * self.default_fallback_multiplier
                df.loc[mask, 'fallback_source'] = 'global_average'
        return df

    def compute_segment_baselines(self, df: pd.DataFrame) -> Dict[str, Dict[str, float]]:
        baselines: Dict[str, Dict[str, float]] = {}
        source = self.config.get('economics.baseline.source', 'actuals')
        aggregation = self.config.get('economics.baseline.aggregation', 'median')
        grain = self.config.get('economics.baseline.grain', 'segment')
        manual_baselines = self.config.get('economics.baseline.manual_baselines', {})

        if source == "manual" and manual_baselines:
            for seg_key, values in manual_baselines.items():
                baselines[seg_key] = {'asp': values.get('asp', 0), 'win_rate': values.get('win_rate', 0)}
            return baselines

        asp_col = 'asp' if 'asp' in df.columns else None
        cw_col = 'close_win_rate' if 'close_win_rate' in df.columns else None
        if asp_col is None and cw_col is None:
            return baselines

        if aggregation == "mode":
            agg_func = lambda x: x.mode().iloc[0] if len(x.mode()) > 0 else x.median()
        elif aggregation == "mean":
            agg_func = 'mean'
        else:
            agg_func = 'median'

        metric_cols = [c for c in [asp_col, cw_col] if c is not None]

        if grain == "global" or len(self.active_dimensions) == 0:
            if aggregation == "mode":
                row = {}
                for col in metric_cols:
                    mode_vals = df[col].dropna().mode()
                    row[col] = mode_vals.iloc[0] if len(mode_vals) > 0 else df[col].dropna().median()
            else:
                row = df[metric_cols].agg(agg_func)
            entry: Dict[str, float] = {}
            if asp_col:
                entry['asp'] = float(row[asp_col])
            if cw_col:
                entry['win_rate'] = float(row[cw_col])
            baselines['__global__'] = entry
        else:
            grouped = df.groupby(self.active_dimensions, dropna=False)
            if aggregation == "mode":
                for group_key, group_df in grouped:
                    seg_key = ".".join(str(v) for v in group_key) if isinstance(group_key, tuple) else str(group_key)
                    entry = {}
                    if asp_col and asp_col in group_df.columns:
                        mode_vals = group_df[asp_col].dropna().mode()
                        entry['asp'] = float(mode_vals.iloc[0]) if len(mode_vals) > 0 else float(group_df[asp_col].dropna().median())
                    if cw_col and cw_col in group_df.columns:
                        mode_vals = group_df[cw_col].dropna().mode()
                        entry['win_rate'] = float(mode_vals.iloc[0]) if len(mode_vals) > 0 else float(group_df[cw_col].dropna().median())
                    if entry:
                        baselines[seg_key] = entry
            else:
                agg_result = grouped[metric_cols].agg(agg_func)
                for idx in agg_result.index:
                    seg_key = ".".join(str(v) for v in idx) if isinstance(idx, tuple) else str(idx)
                    row = agg_result.loc[idx]
                    entry = {}
                    if asp_col and not pd.isna(row.get(asp_col, float('nan'))):
                        entry['asp'] = float(row[asp_col])
                    if cw_col and not pd.isna(row.get(cw_col, float('nan'))):
                        entry['win_rate'] = float(row[cw_col])
                    if entry:
                        baselines[seg_key] = entry

        if manual_baselines:
            for seg_key, values in manual_baselines.items():
                if seg_key not in baselines:
                    baselines[seg_key] = {}
                if 'asp' in values:
                    baselines[seg_key]['asp'] = values['asp']
                if 'win_rate' in values:
                    baselines[seg_key]['win_rate'] = values['win_rate']

        return baselines

    def _flag_supersized(self, df: pd.DataFrame) -> pd.DataFrame:
        df['is_supersized'] = False
        required = ['saos', 'asp', 'close_win_rate', 'revenue']
        if not all(c in df.columns for c in required):
            return df
        df['expected_revenue'] = df['saos'] * df['asp'] * df['close_win_rate']
        with np.errstate(divide='ignore', invalid='ignore'):
            ratio = df['revenue'] / (df['expected_revenue'] + 1e-6)
            df['is_supersized'] = ratio > self.supersized_threshold
        df = df.drop(columns=['expected_revenue'])
        return df


# ═══════════════════════════════════════════════════════════════════════
# TargetLayer  (replaces TargetGenerator)
# ═══════════════════════════════════════════════════════════════════════

class TargetLayer:
    def __init__(self, config) -> None:
        self.config = config
        self._validate_config()

    def _validate_config(self) -> None:
        target_source = self.config.get("targets.target_source", "fixed")
        if target_source == "fixed":
            annual_target = self.config.get("targets.annual_target", None)
            if annual_target is None or annual_target <= 0:
                raise ValueError("targets.annual_target must be > 0 when target_source='fixed'")
        elif target_source == "growth":
            prior_year = self.config.get("targets.prior_year_actuals", None)
            if prior_year is None or prior_year <= 0:
                raise ValueError("targets.prior_year_actuals must be > 0 when target_source='growth'")
        else:
            raise ValueError(f"targets.target_source must be 'fixed' or 'growth', got {target_source}")
        period_type = self.config.get("targets.period_type", "monthly")
        if period_type not in ("monthly", "quarterly"):
            raise ValueError(f"targets.period_type must be 'monthly' or 'quarterly', got {period_type}")
        planning_mode = self.config.get("targets.planning_mode", "full_year")
        if planning_mode not in ("full_year", "rolling_forward", "manual_lock"):
            raise ValueError(f"targets.planning_mode must be one of full_year/rolling_forward/manual_lock, got {planning_mode}")

    def _compute_annual_target(self) -> float:
        target_source = self.config.get("targets.target_source", "fixed")
        if target_source == "fixed":
            return float(self.config.get("targets.annual_target"))
        prior_year = float(self.config.get("targets.prior_year_actuals"))
        growth_rate = float(self.config.get("targets.growth_rate", 0))
        return prior_year * (1 + growth_rate)

    def _get_seasonality_weights(self) -> Dict[int, float]:
        period_type = self.config.get("targets.period_type", "monthly")
        weights: Dict[int, float] = {}
        if period_type == "monthly":
            for month in range(1, 13):
                key = f"targets.seasonality_weights.month_{month}"
                weight = self.config.get(key, None)
                if weight is None:
                    raise ValueError(f"Missing seasonality weight for {key}")
                weights[month] = float(weight)
        else:
            for month in range(1, 13):
                key = f"targets.seasonality_weights.month_{month}"
                weight = self.config.get(key, None)
                if weight is None:
                    raise ValueError(f"Missing seasonality weight for {key}")
                quarter = (month - 1) // 3 + 1
                weights[quarter] = weights.get(quarter, 0) + float(weight)
        total = sum(weights.values())
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"Seasonality weights sum to {total}, expected 1.0")
        return {k: v / total for k, v in weights.items()}

    def generate(self, actuals: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        annual_target = self._compute_annual_target()
        seasonality_weights = self._get_seasonality_weights()
        period_type = self.config.get("targets.period_type", "monthly")
        if period_type == "monthly":
            base_targets = self._build_monthly_targets(annual_target, seasonality_weights)
        else:
            base_targets = self._build_quarterly_targets(annual_target, seasonality_weights)
        planning_mode = self.config.get("targets.planning_mode", "full_year")
        if planning_mode == "rolling_forward" and actuals is not None:
            return self._apply_rolling_forward(base_targets, actuals)
        elif planning_mode == "manual_lock":
            return self._apply_manual_locks(base_targets)
        return base_targets.copy(deep=False)

    def _build_monthly_targets(self, annual_target: float, weights: Dict[int, float]) -> pd.DataFrame:
        rows = []
        for month in range(1, 13):
            rows.append({
                "period": month, "month": month,
                "quarter": (month - 1) // 3 + 1,
                "target_revenue": annual_target * weights[month]
            })
        return pd.DataFrame(rows)

    def _build_quarterly_targets(self, annual_target: float, weights: Dict[int, float]) -> pd.DataFrame:
        rows = []
        for quarter in range(1, 5):
            rows.append({
                "period": quarter, "month": None,
                "quarter": quarter,
                "target_revenue": annual_target * weights.get(quarter, 0)
            })
        return pd.DataFrame(rows)

    def _apply_rolling_forward(self, base_targets: pd.DataFrame, actuals: pd.DataFrame) -> pd.DataFrame:
        result = base_targets.copy(deep=False)
        if not actuals.empty:
            actuals_renamed = actuals.rename(columns={"revenue": "actual_revenue"})
            result = result.merge(actuals_renamed[["period", "actual_revenue"]], on="period", how="left")
            sum_actuals = result["actual_revenue"].sum()
            annual_target = result["target_revenue"].sum()
            remaining_target = annual_target - sum_actuals
            unlocked_mask = result["actual_revenue"].isna()
            sum_unlocked = result.loc[unlocked_mask, "target_revenue"].sum()
            if sum_unlocked > 0 and remaining_target >= 0:
                scale_factor = remaining_target / sum_unlocked
                result.loc[unlocked_mask, "target_revenue"] = result.loc[unlocked_mask, "target_revenue"] * scale_factor
            result.loc[~unlocked_mask, "target_revenue"] = result.loc[~unlocked_mask, "actual_revenue"]
            result = result.drop(columns=["actual_revenue"])
        return result

    def _apply_manual_locks(self, base_targets: pd.DataFrame) -> pd.DataFrame:
        result = base_targets.copy(deep=False)
        locked_periods = self.config.get("targets.locked_months", [])
        if not locked_periods:
            return result
        locked_mask = result["period"].isin(locked_periods)
        sum_locked = result.loc[locked_mask, "target_revenue"].sum()
        annual_target = result["target_revenue"].sum()
        remaining = annual_target - sum_locked
        unlocked_mask = ~locked_mask
        sum_unlocked = result.loc[unlocked_mask, "target_revenue"].sum()
        if sum_unlocked > 0 and remaining >= 0:
            scale_factor = remaining / sum_unlocked
            result.loc[unlocked_mask, "target_revenue"] = result.loc[unlocked_mask, "target_revenue"] * scale_factor
        return result


# ═══════════════════════════════════════════════════════════════════════
# CapacityLayer  (replaces AECapacityModel)
# ═══════════════════════════════════════════════════════════════════════

class CapacityLayer:
    def __init__(self, config) -> None:
        self.config = config
        self._validate_config()

    def _validate_config(self) -> None:
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
        rows = []
        starting_hc = self.config.get("ae_model.starting_hc", 100)
        productivity_per_ae = self.config.get("ae_model.productivity_per_ae", 35)
        ramp_duration_days = self.config.get("ae_model.ramp.duration_days", 90)
        ramp_duration_months = ramp_duration_days / 30
        hiring_plan = self.config.get("ae_model.hiring_plan", [])
        annual_attrition_rate = self.config.get("ae_model.attrition.annual_rate", 0.15)
        monthly_attrition_rate = annual_attrition_rate / 12
        warning_threshold = self.config.get("ae_model.mentoring.warning_threshold", 0.25)
        tenured_hc = starting_hc

        for month in range(1, 13):
            tranches_state = self._process_tranches(month, ramp_duration_months, hiring_plan)
            hc_ramping = 0
            total_ramping_capacity = 0
            for tranche in tranches_state:
                tranche_size = tranche["size"]
                ramp_factor = tranche["ramp_factor"]
                hc_ramping += tranche_size * ramp_factor
                shrinkage = self._calculate_shrinkage(month, len(tranches_state), hiring_plan)
                total_ramping_capacity += tranche_size * ramp_factor * (1 - shrinkage) * productivity_per_ae

            tenured_hc = self._apply_attrition(tenured_hc, month, monthly_attrition_rate)
            mentoring_tax = self._calculate_mentoring_tax(month, tranches_state, tenured_hc)
            shrinkage_rate = self._calculate_shrinkage(month, len(tranches_state), hiring_plan)
            tenured_capacity = max(0, tenured_hc * (1 - shrinkage_rate - mentoring_tax) * productivity_per_ae)
            total_capacity = tenured_capacity + total_ramping_capacity
            capacity_flag = mentoring_tax > warning_threshold
            hc_total = tenured_hc + hc_ramping

            rows.append({
                "month": month, "hc_tenured": tenured_hc, "hc_ramping": hc_ramping,
                "hc_total": hc_total, "mentoring_tax": mentoring_tax,
                "shrinkage_rate": shrinkage_rate,
                "effective_capacity_saos": total_capacity, "capacity_flag": capacity_flag
            })
        return pd.DataFrame(rows)

    def _process_tranches(self, month: int, ramp_duration_months: float,
                          hiring_plan: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        tranches = []
        for tranche in hiring_plan:
            tranche_size = tranche.get("count", 0)
            start_month = tranche.get("start_month", 1)
            if start_month > month:
                continue
            months_in_ramp = month - start_month
            days_in = months_in_ramp * 30
            ramp_duration_days = ramp_duration_months * 30
            ramp_factor = 1.0 if days_in >= ramp_duration_days else days_in / ramp_duration_days
            tranches.append({"size": tranche_size, "start_month": start_month,
                             "days_in": days_in, "ramp_factor": ramp_factor})
        return tranches

    def _calculate_mentoring_tax(self, month: int, tranches_state: List[Dict[str, Any]],
                                 tenured_hc: float = None) -> float:
        overhead_per_hire = self.config.get("ae_model.mentoring.overhead_pct_per_new_hire", 0.10)
        max_mentees_per_ae = self.config.get("ae_model.mentoring.max_mentees_per_ae", 2)
        if tenured_hc is None:
            tenured_hc = self.config.get("ae_model.starting_hc", 100)
        if tenured_hc <= 0:
            return 0.0
        total_mentoring_overhead = 0
        ramping_aes = 0
        for tranche in tranches_state:
            ramp_factor = tranche["ramp_factor"]
            if ramp_factor < 1.0:
                total_mentoring_overhead += tranche["size"] * overhead_per_hire * (1 - ramp_factor)
                ramping_aes += tranche["size"]
        max_total_mentees = max_mentees_per_ae * tenured_hc
        if ramping_aes > max_total_mentees:
            total_mentoring_overhead *= max_total_mentees / ramping_aes
        return max(0.0, min(1.0, total_mentoring_overhead / tenured_hc))

    def _calculate_shrinkage(self, month: int, num_tranches: int,
                             hiring_plan: List[Dict[str, Any]]) -> float:
        pto_pct = self.config.get("ae_model.shrinkage.pto_pct", 0.08)
        admin_pct = self.config.get("ae_model.shrinkage.admin_pct", 0.05)
        enable_base_pct = self.config.get("ae_model.shrinkage.enablement_base_pct", 0.03)
        enable_max_pct = self.config.get("ae_model.shrinkage.enablement_max_pct", 0.10)
        enable_scaling = self.config.get("ae_model.shrinkage.enablement_scaling", "proportional")
        static_shrinkage = pto_pct + admin_pct
        if enable_scaling == "proportional" and num_tranches > 0:
            total_tranches_ever = len(hiring_plan) if hiring_plan else 1
            new_hire_ratio = min(num_tranches / max(1, total_tranches_ever), 1.0)
            enablement_pct = min(enable_max_pct, enable_base_pct + new_hire_ratio * (enable_max_pct - enable_base_pct))
        else:
            enablement_pct = enable_base_pct
        return max(0.0, min(1.0, static_shrinkage + enablement_pct))

    def _apply_attrition(self, tenured_hc: float, month: int, monthly_rate: float) -> float:
        return max(0, tenured_hc - tenured_hc * monthly_rate)

    def get_capacity_summary(self) -> Dict[str, Any]:
        df = self.calculate()
        return {
            "total_annual_capacity": df["effective_capacity_saos"].sum(),
            "min_monthly_capacity": df["effective_capacity_saos"].min(),
            "max_monthly_capacity": df["effective_capacity_saos"].max(),
            "avg_monthly_capacity": df["effective_capacity_saos"].mean(),
            "min_month": df.loc[df["effective_capacity_saos"].idxmin(), "month"],
            "max_month": df.loc[df["effective_capacity_saos"].idxmax(), "month"],
            "capacity_utilization_ratio": (
                df["effective_capacity_saos"].max() / df["effective_capacity_saos"].mean()
                if df["effective_capacity_saos"].mean() > 0 else 1.0
            )
        }

    def analyze_mentoring_relief(self, target_gap: float, month: int) -> Dict[str, Any]:
        df = self.calculate()
        month_data = df[df["month"] == month]
        if month_data.empty:
            raise ValueError(f"Month {month} not in capacity model output")
        baseline_overhead_pct = self.config.get("ae_model.mentoring.overhead_pct_per_new_hire", 0.10)
        baseline_capacity = month_data["effective_capacity_saos"].iloc[0]
        tenured_hc = month_data["hc_tenured"].iloc[0]
        productivity = self.config.get("ae_model.productivity_per_ae", 35)
        freed_capacity_per_pct = tenured_hc * 0.01 * productivity
        if freed_capacity_per_pct <= 0:
            feasible = False
            break_even_overhead_pct = baseline_overhead_pct
        else:
            pct_reduction_needed = target_gap / freed_capacity_per_pct
            break_even_overhead_pct = baseline_overhead_pct * (1 - pct_reduction_needed / 100)
            feasible = break_even_overhead_pct >= 0
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
            "feasible": feasible, "recommendation": recommendation
        }


# ═══════════════════════════════════════════════════════════════════════
# EconomicsLayer  (replaces EconomicsEngine + CalibrationEngine)
# ═══════════════════════════════════════════════════════════════════════

class EconomicsLayer:
    def __init__(self, config) -> None:
        self.config = config
        self._calibrated_params: Dict[tuple, Dict[str, Any]] = {}
        self._base_asp_values: Dict[str, float] = {}
        self._base_win_rate_values: Dict[str, float] = {}
        self._baselines_loaded = False
        self._config_lock = threading.Lock()
        default_decay = self.config.get("economics.default_decay", {})
        if not default_decay:
            raise ValueError("economics.default_decay must be configured")

    def get_effective_asp(self, segment: str, volume: float) -> float:
        base_asp = self._resolve_base_value(segment, "asp")
        decay_config = self.get_segment_config(segment, "asp")
        return self._apply_decay(base_asp, volume, decay_config)

    def get_effective_win_rate(self, segment: str, volume: float) -> float:
        base_win_rate = self._resolve_base_value(segment, "win_rate")
        decay_config = self.get_segment_config(segment, "win_rate")
        effective = self._apply_decay(base_win_rate, volume, decay_config)
        return max(0.0, min(1.0, effective))

    def get_effective_roi(self, segment: str, volume: float) -> float:
        return self.get_effective_asp(segment, volume) * self.get_effective_win_rate(segment, volume)

    def _apply_decay(self, base_value: float, volume: float, decay_config: Dict[str, Any]) -> float:
        function_type = decay_config.get("function", "none")
        rate = decay_config.get("rate", 0.0)
        threshold = decay_config.get("threshold", 0)
        floor_multiplier = decay_config.get("floor_multiplier", 0.5)
        
        return self._cached_decay(base_value, volume, function_type, rate, threshold, floor_multiplier)

    @lru_cache(maxsize=10000)
    def _cached_decay(
        self,
        base_value: float,
        volume: float,
        function_type: str,
        rate: float,
        threshold: int,
        floor_multiplier: float
    ) -> float:
        floor_value = base_value * floor_multiplier

        if function_type == "none":
            decayed_value = base_value
        elif function_type == "linear":
            decayed_value = base_value - (rate * max(0, volume - threshold))
        elif function_type == "exponential":
            decayed_value = base_value * np.exp(-rate * max(0, volume - threshold))
        elif function_type == "step":
            decayed_value = base_value if volume <= threshold else base_value * (1 - rate)
        else:
            raise ValueError(f"Unknown decay function: {function_type}")
        return max(floor_value, decayed_value)

    def get_segment_config(self, segment: str, param: str) -> Dict[str, Any]:
        overrides = self.config.get("economics.segment_overrides", {})
        if segment in overrides and param in overrides[segment]:
            return overrides[segment][param]
        default_decay = self.config.get("economics.default_decay", {})
        if param in default_decay:
            return default_decay[param]
        return {"function": "none", "rate": 0, "threshold": 0, "floor_multiplier": 0.5}

    def _resolve_base_value(self, segment: str, metric: str) -> float:
        if metric == "asp" and segment in self._base_asp_values:
            return self._base_asp_values[segment]
        elif metric == "win_rate" and segment in self._base_win_rate_values:
            return self._base_win_rate_values[segment]
        if metric == "asp" and "__global__" in self._base_asp_values:
            return self._base_asp_values["__global__"]
        elif metric == "win_rate" and "__global__" in self._base_win_rate_values:
            return self._base_win_rate_values["__global__"]
        manual = self.config.get("economics.baseline.manual_baselines", {})
        if segment in manual and metric in manual[segment]:
            return manual[segment][metric]
        if "__global__" in manual and metric in manual["__global__"]:
            return manual["__global__"][metric]
        raise ValueError(
            f"No base {metric} value found for segment '{segment}'. "
            f"Ensure baselines are loaded via load_baselines() before running the optimizer, "
            f"or provide manual_baselines in config.economics.baseline."
        )

    def load_baselines(self, baselines: Dict[str, Dict[str, float]]) -> None:
        for seg_key, values in baselines.items():
            if 'asp' in values:
                self._base_asp_values[seg_key] = values['asp']
            if 'win_rate' in values:
                self._base_win_rate_values[seg_key] = values['win_rate']
        self._baselines_loaded = True

    def update_config(self, new_config: Dict[str, Any]) -> None:
        with self._config_lock:
            self.config = new_config
            self._cached_decay.cache_clear()

    def set_base_value(self, segment: str, metric: str, value: float) -> None:
        if metric == "asp":
            self._base_asp_values[segment] = value
        elif metric == "win_rate":
            self._base_win_rate_values[segment] = value
        else:
            raise ValueError(f"Unknown metric: {metric}")

    def set_calibrated_params(self, segment: str, param: str, fitted_params: Dict[str, Any]) -> None:
        self._calibrated_params[(segment, param)] = fitted_params

    def get_calibrated_params(self, segment: str, param: str) -> Optional[Dict[str, Any]]:
        return self._calibrated_params.get((segment, param), None)

    # -- Cash cycle --

    def get_realization_schedule(self, product: str) -> Dict[int, float]:
        cash_cycle = self.config.get("economics.cash_cycle", {})
        if not isinstance(cash_cycle, dict) or not cash_cycle.get("enabled", False):
            return {0: 1.0}
        overrides = cash_cycle.get("product_overrides", {})
        if product in overrides:
            return dict(overrides[product])
        return dict(cash_cycle.get("default_distribution", {0: 1.0}))

    def get_in_window_factor(self, product: str, month: int) -> float:
        schedule = self.get_realization_schedule(product)
        cash_cycle = self.config.get("economics.cash_cycle", {})
        horizon = cash_cycle.get("planning_horizon_months", 12) if isinstance(cash_cycle, dict) else 12
        in_window = 0.0
        for delay, probability in schedule.items():
            if month + int(delay) <= horizon:
                in_window += probability
        return in_window

    def get_deferred_factor(self, product: str, month: int) -> float:
        return 1.0 - self.get_in_window_factor(product, month)

    def _extract_product_from_segment(self, segment_key: str) -> str:
        active_dims = self.config.get("dimensions", {})
        active_dim_names = [
            dim_name for dim_name, dim_cfg in active_dims.items()
            if isinstance(dim_cfg, dict) and dim_cfg.get("enabled", False)
        ]
        parts = segment_key.split(".")
        if "product" in active_dim_names:
            idx = active_dim_names.index("product")
            if idx < len(parts):
                return parts[idx]
        return parts[0] if parts else segment_key


class CalibrationLayer:
    def __init__(self, config) -> None:
        self.config = config
        self.economics_engine = None

    def fit(self, deal_data: pd.DataFrame, segment: str, param: str) -> Dict[str, float]:
        segment_deals = deal_data[deal_data["segment"] == segment].copy(deep=False)
        min_deals = self.config.get("economics.calibration.min_deals_for_fit", 50)
        if len(segment_deals) < min_deals:
            raise ValueError(f"Segment {segment} has {len(segment_deals)} deals, need at least {min_deals}")
        n_buckets = 5
        segment_deals["volume_bucket"] = pd.qcut(segment_deals["volume"], q=n_buckets, duplicates="drop")
        bucket_stats = segment_deals.groupby("volume_bucket", observed=True).agg(
            {"volume": "mean", param: "mean"}
        ).reset_index(drop=True)
        x_data = bucket_stats["volume"].values
        y_data = bucket_stats[param].values
        fit_function = self.config.get("economics.calibration.fit_function", "exponential")
        try:
            if fit_function == "linear":
                popt, _ = curve_fit(
                    lambda x, base, rate: base - rate * np.maximum(0, x),
                    x_data, y_data, p0=[y_data[0], 0.0001], maxfev=5000
                )
                rate, threshold = popt[1], 0
            else:
                popt, _ = curve_fit(
                    lambda x, base, rate: base * np.exp(-rate * np.maximum(0, x)),
                    x_data, y_data, p0=[y_data[0], 0.001], maxfev=5000
                )
                rate, threshold = popt[1], 0
            floor_multiplier = y_data[-1] / y_data[0]
        except Exception as e:
            raise ValueError(f"Failed to fit {param} curve for {segment}: {str(e)}")
        return {
            "function": fit_function, "rate": float(rate),
            "threshold": float(threshold),
            "floor_multiplier": max(0.1, min(1.0, float(floor_multiplier)))
        }

    def calibrate_all(self, deal_data: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
        fitted_params: Dict[str, Dict[str, Any]] = {}
        min_deals = self.config.get("economics.calibration.min_deals_for_fit", 50)
        for segment in deal_data["segment"].unique():
            segment_deals = deal_data[deal_data["segment"] == segment]
            if len(segment_deals) >= min_deals:
                for param in ["asp", "win_rate"]:
                    try:
                        fitted_params[(segment, param)] = self.fit(deal_data, segment, param)
                    except ValueError:
                        pass
        return fitted_params


# ═══════════════════════════════════════════════════════════════════════
# OptimizerLayer  (replaces AllocationOptimizer)
# ═══════════════════════════════════════════════════════════════════════

class OptimizerLayer:
    def __init__(self, config) -> None:
        self.config = config
        alloc_cfg = config.get("allocation", {})
        self.objective_metric = alloc_cfg.get("objective", {}).get("metric", "bookings")
        self.objective_direction = alloc_cfg.get("objective", {}).get("direction", "maximize")
        constraints = alloc_cfg.get("constraints", {})
        self.share_floor = constraints.get("share_floor", 0.05)
        self.share_ceiling = constraints.get("share_ceiling", 0.40)
        self.mode = alloc_cfg.get("optimizer_mode", "greedy")
        if self.mode not in ["greedy", "solver"]:
            raise ValueError(f"optimizer_mode must be 'greedy' or 'solver', got {self.mode}")
        self.step_size = 0.01
        sys_cfg = config.get("system", {})
        solver_cfg = sys_cfg.get("solver", {}) if isinstance(sys_cfg, dict) else {}
        self.solver_config = {
            "method": solver_cfg.get("method", "SLSQP"),
            "max_iterations": int(solver_cfg.get("max_iterations", 1000)),
            "convergence_tolerance": float(solver_cfg.get("convergence_tolerance", 1e-8)),
        }
        cash_cycle_cfg = config.get("economics", {}).get("cash_cycle", {})
        self.cash_cycle_enabled = (
            isinstance(cash_cycle_cfg, dict) and cash_cycle_cfg.get("enabled", False)
        )

    def optimize(self, targets: pd.DataFrame, base_data: pd.DataFrame,
                 economics_engine: Optional[object] = None,
                 capacity: pd.DataFrame = None) -> pd.DataFrame:
        if targets.empty:
            raise ValueError("targets DataFrame is empty")
        if base_data.empty:
            raise ValueError("base_data DataFrame is empty")
        period_col = targets.columns[0]
        periods = targets[period_col].unique()
        period_col_base = None
        for candidate in ['period', 'month', 'quarter', period_col]:
            if candidate in base_data.columns:
                period_col_base = candidate
                break
        if period_col_base is None:
            raise ValueError(f"Could not find period column in base_data. Available: {list(base_data.columns)}")

        results_list = []
        for period in sorted(periods):
            period_targets = targets[targets[period_col] == period]
            target_revenue = period_targets["target_revenue"].iloc[0]
            period_data = base_data[base_data[period_col_base] == period].copy(deep=False)
            capacity_limit = None
            if capacity is not None:
                period_col_cap = None
                for candidate in ['period', 'month', 'quarter', period_col]:
                    if candidate in capacity.columns:
                        period_col_cap = candidate
                        break
                if period_col_cap:
                    cap_data = capacity[capacity[period_col_cap] == period]
                    if not cap_data.empty:
                        capacity_limit = cap_data["effective_capacity_saos"].iloc[0]
            if self.mode == "greedy":
                period_results = self._optimize_period_greedy(period_data, target_revenue, economics_engine, capacity_limit)
            else:
                period_results = self._optimize_period_solver(period_data, target_revenue, economics_engine, capacity_limit)
            results_list.append(period_results)
        return pd.concat(results_list, ignore_index=True)

    def _optimize_period_greedy(self, period_data, target_revenue, economics_engine, capacity_limit):
        period_data = period_data.copy(deep=False)
        active_dims = self._get_active_dimensions(period_data)
        period_data["segment_key"] = self._create_segment_key(period_data, active_dims)
        segments = period_data.groupby("segment_key").first().reset_index()
        n_segments = len(segments)
        if self.share_floor * n_segments > 1.0:
            raise ValueError(f"Infeasible: floor * n_segments = {self.share_floor * n_segments} > 1.0")
        shares = {seg: self.share_floor for seg in segments["segment_key"]}
        remaining_share = 1.0 - (self.share_floor * n_segments)
        step_count = 0
        max_steps = int(remaining_share / self.step_size) + 100

        while remaining_share > self.step_size * 0.5:
            weighted_roi = self._compute_weighted_roi(shares, segments, economics_engine, target_revenue)
            estimated_total_saos = target_revenue / weighted_roi if weighted_roi > 0 else 0
            best_segment = None
            best_marginal_roi = -np.inf
            for seg_key, current_share in shares.items():
                if current_share >= self.share_ceiling:
                    continue
                seg_data = segments[segments["segment_key"] == seg_key].iloc[0]
                current_volume = current_share * estimated_total_saos
                is_supersized = seg_data.get("is_supersized", False)
                _, _, marginal_roi = self._get_segment_roi(
                    seg_key, seg_data.get("asp", 0), seg_data.get("close_win_rate", 0),
                    current_volume, economics_engine, is_supersized
                )
                if self.cash_cycle_enabled and economics_engine is not None:
                    product = economics_engine._extract_product_from_segment(seg_key)
                    period_num = period_data.iloc[0].get("month", 1) if "month" in period_data.columns else 1
                    marginal_roi *= economics_engine.get_in_window_factor(product, period_num)
                if marginal_roi > best_marginal_roi:
                    best_marginal_roi = marginal_roi
                    best_segment = seg_key
            if best_segment is None:
                break
            allocation = min(self.step_size, remaining_share, self.share_ceiling - shares[best_segment])
            shares[best_segment] += allocation
            remaining_share -= allocation
            step_count += 1
            if step_count > max_steps:
                break

        return self._build_results_df(period_data, segments, shares, target_revenue, economics_engine, capacity_limit)

    def _optimize_period_solver(self, period_data, target_revenue, economics_engine, capacity_limit):
        period_data = period_data.copy(deep=False)
        active_dims = self._get_active_dimensions(period_data)
        period_data["segment_key"] = self._create_segment_key(period_data, active_dims)
        segments = period_data.groupby("segment_key").first().reset_index()
        n_segments = len(segments)
        segment_keys = segments["segment_key"].tolist()

        x0 = np.ones(n_segments) / n_segments
        greedy_results = self._optimize_period_greedy(period_data, target_revenue, economics_engine, capacity_limit)
        if not greedy_results.empty:
            for i, seg_key in enumerate(segment_keys):
                greedy_share = greedy_results[greedy_results["segment_key"] == seg_key]["share"].values
                if len(greedy_share) > 0:
                    x0[i] = greedy_share[0]

        def objective(shares_array):
            weighted_roi = 0
            for i, seg_key in enumerate(segment_keys):
                share = shares_array[i]
                if share <= 0:
                    continue
                seg_data = segments[segments["segment_key"] == seg_key].iloc[0]
                volume = share * (target_revenue / max(weighted_roi, 1.0)) if weighted_roi > 0 else share * target_revenue / 1000
                _, _, roi = self._get_segment_roi(
                    seg_key, seg_data.get("asp", 0), seg_data.get("close_win_rate", 0),
                    volume, economics_engine, seg_data.get("is_supersized", False)
                )
                if self.cash_cycle_enabled and economics_engine is not None:
                    product = economics_engine._extract_product_from_segment(seg_key)
                    period_num = period_data.iloc[0].get("month", 1) if "month" in period_data.columns else 1
                    roi *= economics_engine.get_in_window_factor(product, period_num)
                weighted_roi += share * roi
            return -weighted_roi if weighted_roi > 0 else 1e10

        constraints_list = [{"type": "eq", "fun": lambda x: np.sum(x) - 1.0}]
        if capacity_limit is not None:
            def cap_constraint(shares_array):
                wr = self._compute_weighted_roi(
                    {segment_keys[i]: shares_array[i] for i in range(n_segments)},
                    segments, economics_engine, target_revenue
                )
                return capacity_limit - (target_revenue / wr if wr > 0 else 1e10)
            constraints_list.append({"type": "ineq", "fun": cap_constraint})

        bounds = [(self.share_floor, self.share_ceiling)] * n_segments

        solver_options = {
            "maxiter": min(self.solver_config["max_iterations"], 500),  # Safety limit: max 500 iterations
            "ftol": self.solver_config["convergence_tolerance"],
        }
        print(f"[optimizer] Starting {self.solver_config['method']} with maxiter={solver_options['maxiter']}, "
              f"n_segments={n_segments}", flush=True)

        result = None
        try:
            result = minimize(
                objective, x0, method=self.solver_config["method"],
                bounds=bounds, constraints=constraints_list,
                options=solver_options,
            )
            print(f"[optimizer] {self.solver_config['method']} completed: success={result.success}, "
                  f"iterations={result.nit}, message={result.message}", flush=True)
        except Exception as e:
            print(f"[optimizer] {self.solver_config['method']} failed: {e}. Falling back to greedy.", flush=True)
            result = None

        if result is not None and result.success:
            optimal_shares = {segment_keys[i]: result.x[i] for i in range(n_segments)}
        elif result is not None and not result.success:
            # Solver did not converge — fall back to greedy result (already computed as x0)
            print(f"[optimizer] Solver did not converge, using greedy fallback shares.", flush=True)
            optimal_shares = {segment_keys[i]: x0[i] for i in range(n_segments)}
        else:
            # Exception path — fall back to greedy
            optimal_shares = {segment_keys[i]: x0[i] for i in range(n_segments)}

        return self._build_results_df(period_data, segments, optimal_shares, target_revenue, economics_engine, capacity_limit)

    def _get_segment_roi(self, segment_key, base_asp, base_cw, volume, economics_engine, is_supersized=False):
        if base_asp < 0 or base_cw < 0 or base_cw > 1:
            raise ValueError(f"Invalid base metrics for {segment_key}: ASP={base_asp}, CW={base_cw}")
        if economics_engine is None:
            effective_asp, effective_cw = base_asp, base_cw
        else:
            try:
                effective_asp = economics_engine.get_effective_asp(segment_key, volume)
                effective_cw = economics_engine.get_effective_win_rate(segment_key, volume)
            except Exception:
                effective_asp, effective_cw = base_asp, base_cw
        if is_supersized and effective_asp > base_asp:
            effective_asp = base_asp
        return effective_asp, effective_cw, effective_asp * effective_cw

    def _compute_weighted_roi(self, shares, segments, economics_engine, target_revenue):
        total_saos = target_revenue / 1000
        for iteration in range(5):
            weighted_roi = 0
            for seg_key, share in shares.items():
                if share <= 0:
                    continue
                seg_data = segments[segments["segment_key"] == seg_key].iloc[0]
                volume = share * total_saos
                _, _, roi = self._get_segment_roi(
                    seg_key, seg_data.get("asp", 0), seg_data.get("close_win_rate", 0),
                    volume, economics_engine, seg_data.get("is_supersized", False)
                )
                weighted_roi += share * roi
            if weighted_roi <= 0:
                return 1.0
            new_total_saos = target_revenue / weighted_roi
            if abs(new_total_saos - total_saos) / (total_saos + 1) < 0.001:
                break
            total_saos = new_total_saos
        return weighted_roi

    def _get_active_dimensions(self, data: pd.DataFrame) -> List[str]:
        return [dim for dim in self.config.get_active_dimensions() if dim in data.columns]

    def _create_segment_key(self, data, active_dims):
        if not active_dims:
            return pd.Series(["TOTAL"] * len(data))
        return data[active_dims].apply(lambda row: ".".join(row.astype(str)), axis=1)

    def _build_results_df(self, period_data, segments, shares, target_revenue, economics_engine, capacity_limit):
        weighted_roi = self._compute_weighted_roi(shares, segments, economics_engine, target_revenue)
        total_saos = target_revenue / weighted_roi if weighted_roi > 0 else 0
        capacity_flag = 0
        if capacity_limit is not None and total_saos > capacity_limit:
            capacity_flag = 1
            total_saos = capacity_limit

        results_rows = []
        for seg_key, share in shares.items():
            seg_data = segments[segments["segment_key"] == seg_key].iloc[0]
            period_num = period_data.iloc[0].get("month", 1) if "month" in period_data.columns else 1
            volume = share * total_saos
            base_asp = seg_data.get("asp", 0)
            base_cw = seg_data.get("close_win_rate", 0)
            is_supersized = seg_data.get("is_supersized", False)
            effective_asp, effective_cw, roi = self._get_segment_roi(
                seg_key, base_asp, base_cw, volume, economics_engine, is_supersized
            )
            projected_pipeline = volume * effective_asp
            projected_bookings = volume * effective_asp * effective_cw
            projected_deals = round(projected_bookings / effective_asp) if effective_asp > 0 else 0

            row = {
                "month": period_num, "segment_key": seg_key,
                "share": share, "required_saos": volume,
                "effective_asp": effective_asp, "effective_cw_rate": effective_cw,
                "projected_pipeline": projected_pipeline,
                "projected_bookings": projected_bookings,
                "projected_deals": projected_deals,
                "capacity_flag": capacity_flag, "weighted_roi": roi,
            }

            if self.cash_cycle_enabled and economics_engine is not None:
                product = economics_engine._extract_product_from_segment(seg_key)
                iwf = economics_engine.get_in_window_factor(product, period_num)
                row["in_window_factor"] = iwf
                row["in_window_bookings"] = projected_bookings * iwf
                row["deferred_bookings"] = projected_bookings * (1.0 - iwf)
            else:
                row["in_window_factor"] = 1.0
                row["in_window_bookings"] = projected_bookings
                row["deferred_bookings"] = 0.0

            active_dims = self._get_active_dimensions(period_data)
            for dim in active_dims:
                if dim in seg_data.index:
                    row[dim] = seg_data[dim]
            results_rows.append(row)

        results_df = pd.DataFrame(results_rows)
        if 'period' not in results_df.columns and 'month' in results_df.columns:
            results_df['period'] = results_df['month']
        return results_df

    def get_optimization_summary(self, results: pd.DataFrame) -> Dict:
        total_bookings = results["projected_bookings"].sum()
        total_saos = results["required_saos"].sum()
        summary = {
            "total_annual_bookings": total_bookings,
            "total_annual_pipeline": results["projected_pipeline"].sum(),
            "total_annual_saos": total_saos,
            "total_annual_deals": results["projected_deals"].sum(),
            "average_weighted_roi": (total_bookings / total_saos) if total_saos > 0 else 0.0,
            "months_capacity_constrained": results[results["capacity_flag"] == 1]["month"].nunique(),
            "total_months": results["month"].nunique(),
        }
        segment_summary = results.groupby("segment_key").agg({
            "share": "mean", "projected_bookings": "sum", "required_saos": "sum",
        }).round(2)
        segment_summary["weighted_roi"] = (
            segment_summary["projected_bookings"] / segment_summary["required_saos"]
        ).where(segment_summary["required_saos"] > 0, 0.0).round(2)
        summary["segment_summary"] = segment_summary.to_dict()

        if "in_window_bookings" in results.columns:
            total_in_window = results["in_window_bookings"].sum()
            total_deferred = results["deferred_bookings"].sum()
            summary["total_in_window_bookings"] = total_in_window
            summary["total_deferred_bookings"] = total_deferred
            summary["in_window_pct"] = (total_in_window / total_bookings * 100) if total_bookings > 0 else 0.0
        return summary


# ═══════════════════════════════════════════════════════════════════════
# ValidationLayer  (replaces ValidationEngine)
# ═══════════════════════════════════════════════════════════════════════

class ValidationLayer:
    def __init__(self, config) -> None:
        self.config = config
        self.share_floor = config.get("allocation.constraints.share_floor", 0.05)
        self.share_ceiling = config.get("allocation.constraints.share_ceiling", 0.40)
        self.tolerance = config.get("system.tolerance", 0.001)
        self.revenue_tolerance = config.get("system.revenue_tolerance", 0.01)

    def validate(self, allocation_results, targets=None, capacity=None):
        checks = []
        checks.append(self._check_revenue_identity(allocation_results))
        checks.append(self._check_share_constraints(allocation_results))
        checks.append(self._check_share_sum(allocation_results))
        checks.append(self._check_no_negatives(allocation_results))
        if capacity is not None:
            checks.append(self._check_capacity(allocation_results, capacity))
        if targets is not None:
            checks.append(self._check_target_alignment(allocation_results, targets))
            checks.append(self._check_confidence_coverage(allocation_results))
            if "in_window_bookings" in allocation_results.columns:
                checks.append(self._check_in_window_target_alignment(allocation_results, targets))
        all_passed = all(c["passed"] for c in checks)
        return {"passed": all_passed, "checks": checks, "summary": self._build_summary(checks, all_passed)}

    def _check_revenue_identity(self, results):
        check_name = "Revenue Identity"
        required = {"required_saos", "projected_bookings", "effective_asp", "effective_cw_rate"}
        if not required.issubset(results.columns):
            return {"name": check_name, "passed": False,
                    "message": f"Missing columns: {required - set(results.columns)}",
                    "details": {"missing_columns": list(required - set(results.columns))}}
        expected_bookings = results["required_saos"] * results["effective_asp"] * results["effective_cw_rate"]
        mask = (expected_bookings > 0) & (
            abs(results["projected_bookings"] - expected_bookings) / expected_bookings > self.revenue_tolerance
        )
        if mask.any():
            failures = results[mask].reset_index().assign(
                expected_bookings=expected_bookings[mask],
                rel_error_pct=lambda x: abs(x["projected_bookings"] - x["expected_bookings"]) / x["expected_bookings"] * 100
            )[["index", "expected_bookings", "projected_bookings", "rel_error_pct"]].to_dict("records")
            passed = False
        else:
            failures = []
            passed = True
        message = f"OK: Revenue identity verified across {len(results)} rows." if passed else f"FAIL: {len(failures)} row(s) violate revenue identity"
        return {"name": check_name, "passed": passed, "message": message, "details": {"failures": failures, "total_rows": len(results)}}

    def _check_share_constraints(self, results):
        check_name = "Share Constraints"
        if "share" not in results.columns:
            return {"name": check_name, "passed": False, "message": "Missing 'share' column.", "details": {}}
        mask = (results["share"] < self.share_floor - self.tolerance) | (results["share"] > self.share_ceiling + self.tolerance)
        if mask.any():
            violations = results[mask].reset_index()[["index", "share"]].rename(columns={"index": "row_index"}).to_dict("records")
            passed = False
        else:
            violations = []
            passed = True
        message = f"OK: All shares within bounds across {len(results)} rows." if passed else f"FAIL: {len(violations)} row(s) violate share constraints."
        return {"name": check_name, "passed": passed, "message": message, "details": {"violations": violations}}

    def _check_share_sum(self, results):
        check_name = "Share Sum"
        if "period" not in results.columns or "share" not in results.columns:
            return {"name": check_name, "passed": False, "message": "Missing columns.", "details": {}}
        by_period = results.groupby("period")["share"].sum()
        passed, failures = True, []
        for period, total_share in by_period.items():
            if abs(total_share - 1.0) > self.tolerance:
                failures.append({"period": period, "sum": total_share})
                passed = False
        message = f"OK: Shares sum to 1.0 for all {len(by_period)} period(s)." if passed else f"FAIL: {len(failures)} period(s) have share sum != 1.0."
        return {"name": check_name, "passed": passed, "message": message, "details": {"failures": failures}}

    def _check_capacity(self, results, capacity):
        check_name = "Capacity Constraint"
        cap_period_col = "period" if "period" in capacity.columns else "month"
        demand_by_period = results.groupby("period")["required_saos"].sum()
        passed, violations = True, []
        for period, demand in demand_by_period.items():
            cap_rows = capacity[capacity[cap_period_col] == period]
            if len(cap_rows) > 0:
                supply = cap_rows["effective_capacity_saos"].sum()
                if demand > supply + self.tolerance:
                    violations.append({"period": period, "demand": demand, "supply": supply})
                    passed = False
        message = f"OK: Demand <= supply for all periods." if passed else f"FAIL: {len(violations)} period(s) exceed capacity."
        return {"name": check_name, "passed": passed, "message": message, "details": {"violations": violations}}

    def _check_target_alignment(self, results, targets):
        check_name = "Target Alignment"
        if "projected_bookings" not in results.columns:
            return {"name": check_name, "passed": False, "message": "Missing projected_bookings.", "details": {}}
        target_col = "target_bookings" if "target_bookings" in targets.columns else "target_revenue"
        if target_col not in targets.columns:
            return {"name": check_name, "passed": False, "message": "Missing target column.", "details": {}}
        total_projected = results["projected_bookings"].sum()
        total_target = targets[target_col].sum()
        rel_error = abs(total_projected - total_target) / total_target if total_target > 0 else 0
        passed = rel_error <= self.tolerance
        return {"name": check_name, "passed": passed,
                "message": f"Projected ${total_projected:,.0f} vs target ${total_target:,.0f} (error: {rel_error*100:.1f}%)",
                "details": {"total_projected": total_projected, "total_target": total_target, "rel_error_pct": rel_error * 100}}

    def _check_in_window_target_alignment(self, results, targets):
        check_name = "In-Window Target Alignment (Cash Cycle)"
        if "in_window_bookings" not in results.columns:
            return {"name": check_name, "passed": True, "message": "Cash cycle not enabled; skipping.", "details": {}}
        target_col = "target_bookings" if "target_bookings" in targets.columns else "target_revenue"
        if target_col not in targets.columns:
            return {"name": check_name, "passed": False, "message": "Missing target column.", "details": {}}
        total_in_window = results["in_window_bookings"].sum()
        total_deferred = results["deferred_bookings"].sum() if "deferred_bookings" in results.columns else 0
        total_target = targets[target_col].sum()
        total_bookings = results["projected_bookings"].sum()
        rel_error = (total_target - total_in_window) / total_target if total_target > 0 else 0
        passed = rel_error <= self.revenue_tolerance
        in_window_pct = (total_in_window / total_bookings * 100) if total_bookings > 0 else 0
        return {"name": check_name, "passed": passed,
                "message": f"In-window ${total_in_window:,.0f} vs target ${total_target:,.0f}",
                "details": {"total_in_window_bookings": total_in_window, "total_deferred_bookings": total_deferred,
                            "total_bookings": total_bookings, "total_target": total_target, "in_window_pct": in_window_pct}}

    def _check_no_negatives(self, results):
        check_name = "No Negative Values"
        passed, violations = True, []
        for col in ["required_saos", "projected_pipeline", "projected_bookings", "share"]:
            if col not in results.columns:
                continue
            negatives = results[results[col] < -self.tolerance]
            if len(negatives) > 0:
                passed = False
                violations.append({"column": col, "count": len(negatives), "min_value": negatives[col].min()})
        return {"name": check_name, "passed": passed,
                "message": "OK: No negatives." if passed else f"FAIL: {len(violations)} column(s) have negatives.",
                "details": {"violations": violations}}

    def _check_confidence_coverage(self, results):
        check_name = "Confidence Coverage"
        if "projected_bookings" not in results.columns or "confidence_level" not in results.columns:
            return {"name": check_name, "passed": True, "message": "Confidence data not available; skipping.", "details": {}}
        total_bookings = results["projected_bookings"].sum()
        low_conf_bookings = results[results["confidence_level"] == "low"]["projected_bookings"].sum()
        low_conf_pct = (low_conf_bookings / total_bookings * 100) if total_bookings > 0 else 0
        threshold = self.config.get("system.low_confidence_threshold", 20.0)
        passed = low_conf_pct <= threshold
        return {"name": check_name, "passed": passed,
                "message": f"{low_conf_pct:.1f}% from low-confidence segments (threshold: {threshold}%)",
                "details": {"low_confidence_pct": low_conf_pct, "threshold_pct": threshold}}

    def _build_summary(self, checks, all_passed):
        num_checks = len(checks)
        num_passed = sum(1 for c in checks if c["passed"])
        if all_passed:
            return f"VALIDATION PASSED: All {num_checks} checks passed."
        failed = [c for c in checks if not c["passed"]]
        summary = f"VALIDATION FAILED: {num_passed}/{num_checks} passed.\n"
        for c in failed:
            summary += f"  - {c['name']}: {c['message']}\n"
        return summary


# ═══════════════════════════════════════════════════════════════════════
# RecoveryLayer  (replaces RecoveryEngine)
# ═══════════════════════════════════════════════════════════════════════

class RecoveryLayer:
    def __init__(self, config) -> None:
        self.config = config
        self.stretch_threshold = config.get("ae_model.stretch_threshold", 1.20)
        self.mentoring_overhead = config.get("ae_model.mentoring.overhead_pct_per_new_hire", 0.10)
        self.tolerance = config.get("system.tolerance", 0.001)

    def analyze(self, allocation_results, targets, capacity=None):
        self._validate_inputs(allocation_results, targets)
        quarterly_gaps = self._calculate_quarterly_gaps(allocation_results, targets)
        cumulative_projected = quarterly_gaps["projected"].sum()
        cumulative_target = quarterly_gaps["target"].sum()
        total_shortfall = max(0, cumulative_target - cumulative_projected)

        recovery_plan = quarterly_gaps[["quarter", "target"]].copy(deep=False)
        recovery_plan.columns = ["quarter", "adjusted_target"]
        stretch_flags = []
        mentoring_relief = {}

        if total_shortfall > self.tolerance:
            gap_month = self._find_first_miss_month(quarterly_gaps)
            remaining_quarters = quarterly_gaps[quarterly_gaps["quarter"] >= gap_month]["quarter"].tolist()
            redistributed = self._redistribute_shortfall(total_shortfall, remaining_quarters, capacity, quarterly_gaps)
            recovery_plan["adjusted_target"] = quarterly_gaps["target"].values
            for q, adj in redistributed.items():
                if q in recovery_plan["quarter"].values:
                    idx = recovery_plan[recovery_plan["quarter"] == q].index[0]
                    recovery_plan.loc[idx, "adjusted_target"] += adj
            stretch_flags = self._check_stretch(
                quarterly_gaps["target"].values, recovery_plan["adjusted_target"].values,
                quarterly_gaps["quarter"].tolist()
            )
            mentoring_relief = self._analyze_mentoring_relief(capacity, gap_month)

        recovery_quarter = self.find_recovery_quarter(quarterly_gaps, recovery_plan)
        risk_assessment = self._build_risk_assessment(total_shortfall, cumulative_target, stretch_flags, recovery_quarter)

        return {
            "quarterly_summary": quarterly_gaps, "recovery_plan": recovery_plan,
            "stretch_flags": stretch_flags, "risk_assessment": risk_assessment,
            "mentoring_relief": mentoring_relief, "recovery_quarter": recovery_quarter,
        }

    def _validate_inputs(self, allocation_results, targets):
        required_alloc = {"period", "projected_bookings"}
        required_target = {"period", "target_bookings"}
        if not required_alloc.issubset(allocation_results.columns):
            raise ValueError(f"allocation_results missing: {required_alloc - set(allocation_results.columns)}")
        if not required_target.issubset(targets.columns):
            raise ValueError(f"targets missing: {required_target - set(targets.columns)}")

    def _calculate_quarterly_gaps(self, allocation_results, targets):
        targets_by_period = targets[["period", "target_bookings"]].groupby("period", as_index=False)["target_bookings"].sum()
        alloc_by_period = allocation_results.groupby("period", as_index=False)["projected_bookings"].sum()
        merged = pd.merge(targets_by_period, alloc_by_period, on="period", how="outer")
        merged.fillna(0, inplace=True)

        def extract_quarter(period_val):
            period_str = str(period_val).strip().lower()
            try:
                if period_str.startswith("quarter_"):
                    return int(period_str.split("_")[-1])
                elif period_str.startswith("month_"):
                    return (int(period_str.split("_")[-1]) - 1) // 3 + 1
                return (int(float(period_str)) - 1) // 3 + 1
            except (ValueError, IndexError):
                raise ValueError(f"Cannot extract quarter from period: '{period_val}'")

        merged["quarter"] = merged["period"].apply(extract_quarter)
        quarterly = merged.groupby("quarter", as_index=False).agg(
            {"target_bookings": "sum", "projected_bookings": "sum"}
        )
        quarterly.columns = ["quarter", "target", "projected"]
        quarterly["gap"] = quarterly["target"] - quarterly["projected"]
        quarterly["gap_pct"] = quarterly["gap"] / quarterly["target"].replace(0, np.nan)
        return quarterly.sort_values("quarter").reset_index(drop=True)

    def _find_first_miss_month(self, quarterly_gaps):
        misses = quarterly_gaps[quarterly_gaps["gap"] > self.tolerance]
        return misses.iloc[0]["quarter"] if len(misses) > 0 else quarterly_gaps["quarter"].max()

    def _redistribute_shortfall(self, shortfall, remaining_quarters, capacity, quarterly_gaps):
        if not remaining_quarters:
            return {}
        if capacity is not None and len(capacity) > 0:
            remaining_cap = capacity[capacity["quarter"].isin(remaining_quarters)]
            if len(remaining_cap) > 0:
                total_cap = remaining_cap["effective_capacity"].sum()
                return {q: shortfall * (remaining_cap[remaining_cap["quarter"] == q]["effective_capacity"].sum() / total_cap if total_cap > 0 else 1.0 / len(remaining_quarters)) for q in remaining_quarters}
        equal_share = shortfall / len(remaining_quarters)
        return {q: equal_share for q in remaining_quarters}

    def _check_stretch(self, original_targets, adjusted_targets, quarters):
        flags = []
        for i, q in enumerate(quarters):
            if original_targets[i] > 0:
                ratio = adjusted_targets[i] / original_targets[i]
                if ratio > self.stretch_threshold:
                    flags.append({"quarter": q, "original": original_targets[i],
                                  "adjusted": adjusted_targets[i], "stretch_ratio": ratio})
        return flags

    def _analyze_mentoring_relief(self, capacity, gap_month):
        analysis = {
            "current_mentoring_tax": self.mentoring_overhead,
            "potential_relief": self.mentoring_overhead * 0.5,
            "required_reduction": None,
            "recommendation": "Mentoring relief analysis pending capacity data."
        }
        if capacity is not None and len(capacity) > 0:
            analysis["potential_relief"] = self.mentoring_overhead * 0.5
            analysis["recommendation"] = (
                f"If mentoring overhead (currently {self.mentoring_overhead*100:.1f}%) "
                f"could be reduced by 50%, approximately {analysis['potential_relief']*100:.1f}% capacity freed."
            )
        return analysis

    def find_recovery_quarter(self, quarterly_gaps, recovery_plan=None):
        if recovery_plan is not None and "adjusted_target" in recovery_plan.columns:
            targets = recovery_plan.set_index("quarter")["adjusted_target"]
        else:
            targets = quarterly_gaps.set_index("quarter")["target"]
        projected = quarterly_gaps.set_index("quarter")["projected"]
        cumulative_gap = targets.cumsum() - projected.cumsum()
        recovery_qs = cumulative_gap[cumulative_gap <= self.tolerance]
        return recovery_qs.index[0] if len(recovery_qs) > 0 else quarterly_gaps["quarter"].max()

    def _build_risk_assessment(self, total_shortfall, cumulative_target, stretch_flags, recovery_quarter):
        shortfall_pct = (total_shortfall / cumulative_target * 100) if cumulative_target > 0 else 0
        narrative = f"Annual Target Risk Assessment:\n  Projected shortfall: ${total_shortfall:,.0f} ({shortfall_pct:.1f}%)\n"
        if total_shortfall <= 0:
            narrative += "  Status: ON TRACK.\n"
        else:
            narrative += f"  Status: AT RISK. Recovery quarter: Q{recovery_quarter}\n"
            if stretch_flags:
                narrative += f"  WARNING: {len(stretch_flags)} quarter(s) exceed stretch threshold\n"
        return narrative


# ═══════════════════════════════════════════════════════════════════════
# AnalysisLayer  (replaces WhatIfEngine, AdjustmentEngine, VersionComparator, LeverAnalysisEngine)
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class ScenarioComparison:
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
        return asdict(self)


class WhatIfLayer:
    def __init__(self, config: dict) -> None:
        if not isinstance(config, dict):
            raise ValueError("config must be a dict")
        if 'what_if_scenarios' not in config:
            raise ValueError("config must contain 'what_if_scenarios' key")
        scenarios = config.get('what_if_scenarios', [])
        if not isinstance(scenarios, list) or len(scenarios) == 0:
            raise ValueError("At least one scenario must be defined")
        if len(scenarios) > 5:
            raise ValueError(f"Maximum 5 scenarios allowed (got {len(scenarios)})")
        for s in scenarios:
            if 'name' not in s or 'perturbations' not in s:
                raise ValueError(f"Each scenario must have 'name' and 'perturbations'. Got: {s.keys()}")
        self.config = config
        self.scenarios = [s for s in scenarios if s.get('enabled', True)]
        if len(self.scenarios) == 0:
            raise ValueError("No enabled scenarios found.")
        self._scenario_results: Dict[str, dict] = {}

    def run_scenarios(self, base_results, base_summary, run_pipeline_fn):
        comparisons = []
        for scenario in self.scenarios:
            scenario_name = scenario.get('name')
            scenario_config = self._apply_perturbations(self.config, scenario.get('perturbations', {}))
            try:
                scenario_results, scenario_summary = run_pipeline_fn(scenario_config)
            except Exception as e:
                raise ValueError(f"Pipeline failed for scenario '{scenario_name}': {e}")
            self._scenario_results[scenario_name] = {
                'config': scenario_config, 'results': scenario_results, 'summary': scenario_summary
            }
            comparisons.append(self._compare_results(
                base_summary, scenario_summary, scenario_name, scenario.get('description', '')
            ).to_dict())
        return pd.DataFrame(comparisons)

    def _apply_perturbations(self, base_config, perturbations):
        config = copy.deepcopy(base_config)
        if 'ae_headcount_change' in perturbations:
            config['_ae_headcount_changes'] = perturbations['ae_headcount_change']
        if 'backfill_delay_months' in perturbations:
            config['ae_model']['attrition']['backfill_delay_months'] = perturbations['backfill_delay_months']
        if 'asp_multiplier' in perturbations:
            config.setdefault('_asp_multiplier', {}).update(perturbations['asp_multiplier'])
        if 'win_rate_multiplier' in perturbations:
            config.setdefault('_win_rate_multiplier', {}).update(perturbations['win_rate_multiplier'])
        if 'channel_share_ceiling' in perturbations:
            config.setdefault('allocation', {}).setdefault('constraints', {}).setdefault('segment_overrides', {})
            for channel, ceiling in perturbations['channel_share_ceiling'].items():
                config['allocation']['constraints']['segment_overrides'].setdefault(f"*.{channel}", {})['ceiling'] = ceiling
        if 'lead_volume_multiplier' in perturbations:
            config.setdefault('_lead_volume_multiplier', {}).update(perturbations['lead_volume_multiplier'])
        if 'cancel_tranches' in perturbations:
            indices = sorted(set(perturbations['cancel_tranches']), reverse=True)
            for idx in indices:
                del config['ae_model']['hiring_plan'][idx]
        if 'add_region' in perturbations:
            config['dimensions']['region']['enabled'] = True
            if perturbations['add_region'] not in config['dimensions']['region']['values']:
                config['dimensions']['region']['values'].append(perturbations['add_region'])
        if 'region_performance_multiplier' in perturbations:
            config.setdefault('_region_performance_multiplier', {}).update(perturbations['region_performance_multiplier'])
        return config

    def _compare_results(self, base_summary, scenario_summary, name, description=''):
        def gm(s, k, d=0.0):
            return s.get(k, d)
        bb = gm(base_summary, 'total_bookings')
        bs = gm(base_summary, 'total_saos', 0)
        bh = gm(base_summary, 'total_ae_hc', 0)
        bv = gm(base_summary, 'monthly_volatility')
        sb = gm(scenario_summary, 'total_bookings')
        ss = gm(scenario_summary, 'total_saos', 0)
        sh = gm(scenario_summary, 'total_ae_hc', 0)
        sv = gm(scenario_summary, 'monthly_volatility')
        sc = gm(scenario_summary, 'capacity_utilisation')
        bd = sb - bb
        sd = ss - bs
        hd = sh - bh
        risk_flags = []
        if bd < 0:
            risk_flags.append(f"Bookings down {abs(bd/bb*100) if bb else 0:.1f}%")
        if sc > 0.95:
            risk_flags.append(f"Capacity utilisation {sc:.1%}")
        if sv - bv > 0:
            risk_flags.append(f"Monthly volatility up {sv-bv:.2f}")
        if hd < 0:
            risk_flags.append(f"AE HC reduced by {abs(hd)}")
        return ScenarioComparison(
            scenario_name=name, scenario_description=description,
            total_bookings=format_currency(sb), total_saos=int(ss), total_ae_hc=int(sh),
            bookings_delta=format_currency(bd), saos_delta=int(sd), hc_delta=int(hd),
            bookings_delta_pct=round(bd/bb*100 if bb else 0, 2),
            saos_delta_pct=round(sd/bs*100 if bs else 0, 2),
            hc_delta_pct=round(hd/bh*100 if bh else 0, 2),
            capacity_utilisation=round(sc, 3),
            monthly_volatility=round(sv, 2),
            monthly_volatility_delta=round(sv - bv, 2),
            risk_flags=risk_flags,
        )

    def get_scenario_details(self, scenario_name):
        if scenario_name not in self._scenario_results:
            raise KeyError(f"Scenario '{scenario_name}' not found")
        return self._scenario_results[scenario_name]


class AdjustmentLayer:
    def __init__(self, config) -> None:
        self.config = config
        self.planning_mode = config.get("targets", {}).get("planning_mode", "full_year")

    def apply_adjustment(self, current_plan, actuals=None, hc_changes=None, target_changes=None, segment_changes=None):
        adjusted_config = deepcopy(self.config)
        changes_applied = {"actuals_merged": 0, "hc_changes_applied": 0, "target_changes_applied": 0, "segment_changes_applied": 0}
        merged_plan, locked_periods, locked_revenue = current_plan, [], 0.0
        if actuals is not None:
            merged_plan, locked_periods, locked_revenue = self._merge_actuals(current_plan, actuals)
            changes_applied["actuals_merged"] = len(locked_periods)
        if hc_changes:
            adjusted_config = self._apply_hc_changes(adjusted_config, hc_changes)
            changes_applied["hc_changes_applied"] = len(hc_changes)
        remaining_target = self._calculate_remaining_target(merged_plan, locked_periods, target_changes)
        if target_changes:
            adjusted_config = self._apply_target_changes(adjusted_config, target_changes)
            changes_applied["target_changes_applied"] = len(target_changes)
        if segment_changes:
            adjusted_config = self._apply_segment_changes(adjusted_config, segment_changes)
            changes_applied["segment_changes_applied"] = len(segment_changes)
        return {
            "adjusted_config": adjusted_config, "locked_periods": locked_periods,
            "remaining_target": remaining_target, "locked_revenue": locked_revenue,
            "adjustment_summary": "Adjustment applied.", "changes_applied": changes_applied,
        }

    def _merge_actuals(self, plan, actuals):
        merged = plan.copy(deep=False)
        locked_periods, total_locked = [], 0.0
        if len(actuals) == 0:
            return merged, locked_periods, 0.0
        if "period" in actuals.columns and "actual_bookings" in actuals.columns:
            for period in actuals["period"].unique():
                period_actuals = actuals[actuals["period"] == period]
                period_mask = merged["period"] == period
                for idx in merged[period_mask].index:
                    segment = merged.loc[idx, "segment"] if "segment" in merged.columns else "total"
                    sa = period_actuals[period_actuals.get("segment", "total") == segment]
                    if len(sa) > 0:
                        av = sa["actual_bookings"].sum()
                        merged.loc[idx, "projected_bookings"] = av
                        total_locked += av
                if len(period_actuals) > 0:
                    locked_periods.append(period)
        return merged, sorted(set(locked_periods)), total_locked

    def _apply_hc_changes(self, config, hc_changes):
        updated = deepcopy(config)
        hiring_plan = updated.get("ae_model", {}).get("hiring_plan", [])
        for key, delta in hc_changes.items():
            try:
                month = int(str(key).split("_")[-1]) if "month_" in str(key) else int(key)
            except Exception:
                continue
            found = False
            for t in hiring_plan:
                if t.get("start_month") == month:
                    t["count"] = max(0, t.get("count", 0) + delta)
                    found = True
                    break
            if not found and delta > 0:
                hiring_plan.append({"count": delta, "start_month": month})
        updated.setdefault("ae_model", {})["hiring_plan"] = hiring_plan
        return updated

    def _apply_target_changes(self, config, target_changes):
        updated = deepcopy(config)
        if "annual_target" in target_changes:
            updated.setdefault("targets", {})["annual_target"] = target_changes["annual_target"]
        return updated

    def _apply_segment_changes(self, config, segment_changes):
        updated = deepcopy(config)
        for key, value in segment_changes.items():
            parts = str(key).split(".")
            if len(parts) < 2:
                continue
            updated.setdefault("economics", {}).setdefault("segment_overrides", {})
            seg = ".".join(parts[:-1])
            updated["economics"]["segment_overrides"].setdefault(seg, {})[parts[-1]] = value
        return updated

    def _calculate_remaining_target(self, merged_plan, locked_periods, target_changes):
        annual_target = self.config.get("targets", {}).get("annual_target", 0)
        if target_changes and "annual_target" in target_changes:
            annual_target = target_changes["annual_target"]
        locked_revenue = 0.0
        if locked_periods and "period" in merged_plan.columns and "projected_bookings" in merged_plan.columns:
            locked_revenue = merged_plan[merged_plan["period"].isin(locked_periods)]["projected_bookings"].sum()
        return max(0, annual_target - locked_revenue)


@dataclass
class VersionMetrics:
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

    def to_dict(self):
        return asdict(self)


class ComparatorLayer:
    def __init__(self, config=None) -> None:
        self.config = config or {}
        self.stretch_threshold = self.config.get('ae_model.stretch_threshold', 1.2)
        self.conf_low_max = self.config.get('system.confidence_risk_low_max_pct', 5)
        self.conf_medium_max = self.config.get('system.confidence_risk_medium_max_pct', 20)

    def compare(self, versions: List[Dict[str, Any]]) -> Dict[str, Any]:
        metrics_list = []
        for v in versions:
            vid = v.get('version_id', 'unknown')
            results = v.get('results', pd.DataFrame())
            summary = v.get('summary', {})
            total_bookings = summary.get('total_annual_bookings', results['projected_bookings'].sum() if 'projected_bookings' in results.columns else 0)
            total_pipeline = summary.get('total_annual_pipeline', results['projected_pipeline'].sum() if 'projected_pipeline' in results.columns else 0)
            total_saos = summary.get('total_annual_saos', results['required_saos'].sum() if 'required_saos' in results.columns else 0)
            total_ae_hc = summary.get('total_ae_hc', 0)
            avg_prod = total_saos / total_ae_hc if total_ae_hc > 0 else 0
            monthly = results.groupby('month')['projected_bookings'].sum() if 'month' in results.columns and 'projected_bookings' in results.columns else pd.Series([0])
            volatility = monthly.std() if len(monthly) > 1 else 0
            cv = volatility / monthly.mean() if monthly.mean() > 0 else 0
            mmr = monthly.max() / monthly.min() if monthly.min() > 0 else 0
            seg_shares = results.groupby('segment_key')['projected_bookings'].sum() / total_bookings if total_bookings > 0 and 'segment_key' in results.columns else pd.Series([1])
            hhi = (seg_shares ** 2).sum()
            metrics_list.append(VersionMetrics(
                version_id=str(vid), total_bookings=total_bookings, total_pipeline=total_pipeline,
                total_saos=int(total_saos), total_ae_hc=int(total_ae_hc),
                avg_productivity_per_ae=round(avg_prod, 1),
                monthly_volatility=round(volatility, 2), coefficient_of_variation=round(cv, 3),
                max_min_ratio=round(mmr, 2), herfindahl_index=round(hhi, 4),
                capacity_utilisation_variance=0.0, stretch_exposure_pct=0.0,
                confidence_weighted_bookings=total_bookings, confidence_risk_flag="low"
            ))
        return {"metrics": [m.to_dict() for m in metrics_list], "comparison_df": pd.DataFrame([m.to_dict() for m in metrics_list])}


@dataclass
class GapDecomposition:
    annual_target: float
    baseline_bookings: float
    capacity_shortfall_loss: float
    asp_decay_loss: float
    win_rate_decay_loss: float
    cash_cycle_deferral: float
    actual_bookings: float
    gap: float


@dataclass
class LeverSensitivity:
    lever_name: str
    label: str
    category: str
    unit: str
    current_value: float
    bound_value: float
    direction: str
    estimated_gain: float
    gain_pct_of_gap: float
    gain_pct_of_base: float
    business_context: str
    mechanism: str
    recommendation: str


class LeverAnalysisLayer:
    def __init__(self, config: dict) -> None:
        self.config = config
        br = config.get("business_recommendations", {})
        self.levers = br.get("levers", {})
        if not self.levers:
            raise ValueError("No levers defined in config['business_recommendations']['levers']")

    def analyze(self, results: pd.DataFrame, targets: pd.DataFrame,
                capacity: pd.DataFrame, economics_engine=None) -> Dict[str, Any]:
        total_bookings = results["projected_bookings"].sum()
        target_col = "target_revenue" if "target_revenue" in targets.columns else "target_bookings"
        annual_target = targets[target_col].sum()
        gap = annual_target - total_bookings

        decomposition = GapDecomposition(
            annual_target=annual_target, baseline_bookings=total_bookings,
            capacity_shortfall_loss=0, asp_decay_loss=0, win_rate_decay_loss=0,
            cash_cycle_deferral=results["deferred_bookings"].sum() if "deferred_bookings" in results.columns else 0,
            actual_bookings=total_bookings, gap=gap,
        )

        sensitivities = []
        for lever_name, lever_cfg in self.levers.items():
            sensitivities.append(LeverSensitivity(
                lever_name=lever_name, label=lever_cfg.get("label", lever_name),
                category=lever_cfg.get("category", "unknown"),
                unit=lever_cfg.get("unit", ""), current_value=0, bound_value=0,
                direction=lever_cfg.get("direction", "increase"),
                estimated_gain=0, gain_pct_of_gap=0, gain_pct_of_base=0,
                business_context=lever_cfg.get("business_context", ""),
                mechanism="", recommendation="",
            ))

        return {
            "gap_decomposition": asdict(decomposition),
            "lever_sensitivities": [asdict(s) for s in sensitivities],
            "recommendations": [],
        }


# ═══════════════════════════════════════════════════════════════════════
# VersionStoreLayer  (replaces VersionStore)
# ═══════════════════════════════════════════════════════════════════════

class VersionStoreLayer:
    def __init__(self, config) -> None:
        self.config = config
        output_dir_str = config.get('system.output_dir', 'versions')
        self.output_dir = Path(output_dir_str)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save(self, config_snapshot, results, summary, description="", planning_mode="full_year"):
        if not isinstance(config_snapshot, dict):
            raise ValueError("config_snapshot must be a dictionary")
        if not isinstance(results, pd.DataFrame) or results.empty:
            raise ValueError("results must be a non-empty DataFrame")
        version_id = self._get_next_version_id()
        version_dir = self.output_dir / f"v{version_id:03d}"
        version_dir.mkdir(parents=True, exist_ok=True)
        config_hash = compute_config_hash(config_snapshot)
        summary_with_metadata = {
            'version_id': version_id, 'timestamp': datetime.utcnow().isoformat(),
            'description': description, 'planning_mode': planning_mode,
            'config_hash': config_hash, **summary
        }
        with open(version_dir / 'config.yaml', 'w') as f:
            yaml.dump(config_snapshot, f, default_flow_style=False, sort_keys=False)
        results.to_csv(version_dir / 'results.csv', index=False)
        with open(version_dir / 'summary.json', 'w') as f:
            json.dump(summary_with_metadata, f, indent=2)
        return version_id

    def load(self, version_id):
        version_dir = self.output_dir / f"v{version_id:03d}"
        if not version_dir.exists():
            raise FileNotFoundError(f"Version {version_id} not found")
        with open(version_dir / 'config.yaml', 'r') as f:
            config = yaml.safe_load(f)
        results = pd.read_csv(version_dir / 'results.csv')
        with open(version_dir / 'summary.json', 'r') as f:
            summary = json.load(f)
        return {'config': config, 'results': results, 'summary': summary}

    def list_versions(self):
        versions = []
        for vd in sorted(self.output_dir.glob('v*')):
            if not vd.is_dir():
                continue
            try:
                vid = int(vd.name[1:])
            except (ValueError, IndexError):
                continue
            sp = vd / 'summary.json'
            if not sp.exists():
                continue
            try:
                with open(sp) as f:
                    versions.append(json.load(f))
            except (json.JSONDecodeError, IOError):
                continue
        if not versions:
            return pd.DataFrame()
        df = pd.DataFrame(versions)
        if 'version_id' in df.columns:
            df = df.sort_values('version_id', ascending=False).reset_index(drop=True)
        return df

    def _get_next_version_id(self):
        existing = []
        for vd in self.output_dir.glob('v*'):
            if not vd.is_dir():
                continue
            try:
                existing.append(int(vd.name[1:]))
            except (ValueError, IndexError):
                continue
        return max(existing) + 1 if existing else 1
