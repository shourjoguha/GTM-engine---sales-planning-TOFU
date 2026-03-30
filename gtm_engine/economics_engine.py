"""
Economics Engine Module — Model marginal economics (ASP, win rate) across volume levels.

Purpose:
    This module computes the effective Average Selling Price (ASP) and Close-Win (CW) rate
    for a given segment at a given volume level, accounting for decay effects.

    Decay models how economics degrade (or improve) as volume increases:
    - Linear: ASP degrades linearly beyond a threshold
    - Exponential: ASP degrades exponentially (steeper)
    - Step: ASP stays constant until threshold, then jumps
    - None: ASP stays constant regardless of volume

Inputs:
    - config: Dictionary-like object with economics parameters:
        * economics.default_decay: Global decay settings for asp and win_rate
        * economics.use_calibration: Boolean toggle for using calibrated vs. default params
        * economics.segment_overrides: (optional) Per-segment decay overrides
    - (Optional) Calibration data: deal-level DataFrame with columns [segment, volume, asp, win_rate]

Outputs:
    - Methods to get effective ASP, CW rate, and ROI at any volume level
    - Storage for calibrated parameters that override defaults

Key Calculations:
    1. get_effective_asp(segment, volume): Apply decay function to base ASP
    2. get_effective_win_rate(segment, volume): Apply decay function to base CW rate
    3. get_effective_roi(segment, volume): ASP(volume) × CW_rate(volume)
    4. _apply_decay(base_value, volume, decay_config): Core decay logic

    Decay formulas:
    - Linear: value = base - rate × max(0, volume - threshold), floored at base × floor_multiplier
    - Exponential: value = base × exp(-rate × max(0, volume - threshold)), floored
    - Step: value = base if volume <= threshold else base × (1 - rate), floored
    - None: value = base (unchanged)

Example:
    >>> config = {...}
    >>> engine = EconomicsEngine(config)
    >>> asp = engine.get_effective_asp("EOR.Marketing", volume=600)  # 600 SAOs
    >>> roi = engine.get_effective_roi("EOR.Marketing", volume=600)  # ROI per SAO
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, Any
from scipy.optimize import curve_fit


class EconomicsEngine:
    """
    Model effective ASP and CW rate at different volume levels, with decay support.

    Supports three decay functions (linear, exponential, step, none) and can be
    calibrated with historical deal data.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize with config and optionally calibrate from data.

        Args:
            config: Dictionary-like object with .get(key, default) interface
        """
        self.config = config
        self._calibrated_params = {}  # Dict to store fitted parameters
        self._base_asp_values = {}    # Cache for base ASP by segment
        self._base_win_rate_values = {}  # Cache for base win rate by segment
        self._baselines_loaded = False  # Track whether baselines have been set from data
        self._validate_config()

    def _validate_config(self) -> None:
        """Validate that required economics config is present."""
        # Check for default decay config
        default_decay = self.config.get("economics.default_decay", {})
        if not default_decay:
            raise ValueError("economics.default_decay must be configured")

    def get_effective_asp(self, segment: str, volume: float) -> float:
        """
        Get the effective Average Selling Price for a segment at a given volume.

        Applies decay function if volume exceeds threshold. Falls back to defaults
        if no base value is cached.

        Args:
            segment: Segment identifier (e.g., "EOR.Marketing", "CM.Outbound")
            volume: Number of SAOs being allocated to this segment

        Returns:
            float: Effective ASP in dollars, adjusted for volume decay
        """
        # Base ASP: from set_base_value() (populated by data_loader.compute_segment_baselines)
        # Falls back to __global__ baseline if segment not found, then to config manual_baselines
        base_asp = self._resolve_base_value(segment, "asp")

        # Get decay config for ASP
        decay_config = self.get_segment_config(segment, "asp")

        # Apply decay
        effective_asp = self._apply_decay(base_asp, volume, decay_config)

        return effective_asp

    def get_effective_win_rate(self, segment: str, volume: float) -> float:
        """
        Get the effective Close-Win rate for a segment at a given volume.

        Applies decay function if volume exceeds threshold. Falls back to defaults
        if no base value is cached.

        Args:
            segment: Segment identifier (e.g., "EOR.Marketing", "CM.Outbound")
            volume: Number of SAOs being allocated to this segment

        Returns:
            float: Effective CW rate as a decimal (0.0 to 1.0), adjusted for volume decay
        """
        # Base win rate: from set_base_value() (populated by data_loader.compute_segment_baselines)
        # Falls back to __global__ baseline if segment not found, then to config manual_baselines
        base_win_rate = self._resolve_base_value(segment, "win_rate")

        # Get decay config for win_rate
        decay_config = self.get_segment_config(segment, "win_rate")

        # Apply decay
        effective_win_rate = self._apply_decay(base_win_rate, volume, decay_config)

        # Ensure win rate stays in [0, 1]
        return max(0.0, min(1.0, effective_win_rate))

    def get_effective_roi(self, segment: str, volume: float) -> float:
        """
        Get the effective ROI (revenue per SAO) for a segment at a given volume.

        ROI = ASP(volume) × CW_rate(volume)

        Args:
            segment: Segment identifier
            volume: Number of SAOs allocated

        Returns:
            float: ROI in dollars per SAO
        """
        asp = self.get_effective_asp(segment, volume)
        win_rate = self.get_effective_win_rate(segment, volume)
        return asp * win_rate

    def _apply_decay(self, base_value: float, volume: float,
                     decay_config: Dict[str, Any]) -> float:
        """
        Apply decay function to a base value based on volume.

        Supports four function types:
        - "none": Return base_value unchanged
        - "linear": base - rate × max(0, volume - threshold), floored at base × floor_multiplier
        - "exponential": base × exp(-rate × max(0, volume - threshold)), floored
        - "step": base if volume <= threshold else base × (1 - rate), floored

        Args:
            base_value: Starting value (e.g., base ASP)
            volume: Current volume level (number of SAOs)
            decay_config: Dict with keys:
                - function: "linear", "exponential", "step", or "none"
                - rate: Decay rate parameter
                - threshold: Volume at which decay begins
                - floor_multiplier: Minimum value = base × floor_multiplier

        Returns:
            float: Decayed value, floored at base × floor_multiplier
        """
        # Extract decay parameters with defaults
        function_type = decay_config.get("function", "none")
        rate = decay_config.get("rate", 0.0)
        threshold = decay_config.get("threshold", 0)
        floor_multiplier = decay_config.get("floor_multiplier", 0.5)

        # Compute floor
        floor_value = base_value * floor_multiplier

        # Apply decay based on function type
        if function_type == "none":
            # No decay: return base value
            decayed_value = base_value

        elif function_type == "linear":
            # Linear decay: base - rate × max(0, volume - threshold)
            excess_volume = max(0, volume - threshold)
            decayed_value = base_value - (rate * excess_volume)

        elif function_type == "exponential":
            # Exponential decay: base × exp(-rate × max(0, volume - threshold))
            excess_volume = max(0, volume - threshold)
            decayed_value = base_value * np.exp(-rate * excess_volume)

        elif function_type == "step":
            # Step decay: base if volume <= threshold, else base × (1 - rate)
            if volume <= threshold:
                decayed_value = base_value
            else:
                decayed_value = base_value * (1 - rate)

        else:
            raise ValueError(f"Unknown decay function: {function_type}")

        # Apply floor constraint
        return max(floor_value, decayed_value)

    def get_segment_config(self, segment: str, param: str) -> Dict[str, Any]:
        """
        Get decay config for a segment+param, falling back to defaults if needed.

        Checks for segment-specific overrides, then falls back to global defaults.

        Args:
            segment: Segment identifier (e.g., "EOR.Marketing")
            param: Parameter name ("asp" or "win_rate")

        Returns:
            dict: Decay configuration {function, rate, threshold, floor_multiplier}
        """
        # Try to find segment-specific override
        overrides = self.config.get("economics.segment_overrides", {})
        if segment in overrides and param in overrides[segment]:
            return overrides[segment][param]

        # Fall back to global default
        default_decay = self.config.get("economics.default_decay", {})
        if param in default_decay:
            return default_decay[param]

        # If no config found, return a sensible default (no decay)
        return {"function": "none", "rate": 0, "threshold": 0, "floor_multiplier": 0.5}

    def set_calibrated_params(self, segment: str, param: str, fitted_params: Dict[str, Any]) -> None:
        """
        Override default parameters with calibrated values for a segment.

        Used after calibration to store fitted decay parameters.

        Args:
            segment: Segment identifier
            param: Parameter name ("asp" or "win_rate")
            fitted_params: Dict with fitted values {rate, threshold, floor_multiplier}
        """
        key = (segment, param)
        self._calibrated_params[key] = fitted_params

    def get_calibrated_params(self, segment: str, param: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve calibrated parameters for a segment+param if available.

        Args:
            segment: Segment identifier
            param: Parameter name

        Returns:
            dict or None: Fitted parameters if calibrated, else None
        """
        key = (segment, param)
        return self._calibrated_params.get(key, None)

    def _resolve_base_value(self, segment: str, metric: str) -> float:
        """
        Resolve the base value for a segment metric using the fallback chain:

        1. Segment-specific value from set_base_value() (data-derived)
        2. __global__ baseline (if segment not found but global was computed)
        3. Manual baselines from config (economics.baseline.manual_baselines)
        4. Raise ValueError — no hardcoded defaults

        Args:
            segment: Segment identifier (e.g., "EOR.Marketing")
            metric: "asp" or "win_rate"

        Returns:
            float: Resolved base value

        Raises:
            ValueError: If no base value can be resolved from any source
        """
        # 1. Check segment-specific cache (set by load_baselines or set_base_value)
        if metric == "asp" and segment in self._base_asp_values:
            return self._base_asp_values[segment]
        elif metric == "win_rate" and segment in self._base_win_rate_values:
            return self._base_win_rate_values[segment]

        # 2. Fall back to __global__ baseline
        if metric == "asp" and "__global__" in self._base_asp_values:
            return self._base_asp_values["__global__"]
        elif metric == "win_rate" and "__global__" in self._base_win_rate_values:
            return self._base_win_rate_values["__global__"]

        # 3. Fall back to manual baselines in config
        manual = self.config.get("economics.baseline.manual_baselines", {})
        if segment in manual and metric in manual[segment]:
            return manual[segment][metric]
        # Check manual global entry
        if "__global__" in manual and metric in manual["__global__"]:
            return manual["__global__"][metric]

        # 4. No value found — raise rather than silently using a hardcoded default
        raise ValueError(
            f"No base {metric} value found for segment '{segment}'. "
            f"Ensure baselines are loaded via load_baselines() before running the optimizer, "
            f"or provide manual_baselines in config.economics.baseline."
        )

    def load_baselines(self, baselines: Dict[str, Dict[str, float]]) -> None:
        """
        Bulk-load baseline values from data_loader.compute_segment_baselines().

        This is the primary entry point for populating base ASP and win rate values.
        Should be called after data loading and before optimization.

        Args:
            baselines: Dict from compute_segment_baselines(), mapping
                       segment_key → {'asp': float, 'win_rate': float}

        Example:
            >>> baselines = loader.compute_segment_baselines(df_clean)
            >>> economics.load_baselines(baselines)
        """
        for seg_key, values in baselines.items():
            if 'asp' in values:
                self._base_asp_values[seg_key] = values['asp']
            if 'win_rate' in values:
                self._base_win_rate_values[seg_key] = values['win_rate']
        self._baselines_loaded = True

    def set_base_value(self, segment: str, metric: str, value: float) -> None:
        """
        Set the base (non-decayed) value for a segment metric.

        Used when loading historical data to establish baseline ASP/win_rate per segment.

        Args:
            segment: Segment identifier
            metric: "asp" or "win_rate"
            value: Base value (dollars for ASP, decimal for win_rate)
        """
        if metric == "asp":
            self._base_asp_values[segment] = value
        elif metric == "win_rate":
            self._base_win_rate_values[segment] = value
        else:
            raise ValueError(f"Unknown metric: {metric}")


class CalibrationEngine:
    """
    Fit decay curves from historical deal data to calibrate economics.

    Takes deal-level data, bins by volume, and fits decay functions using
    scipy.optimize.curve_fit.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize calibration engine with config.

        Args:
            config: Dictionary-like object with calibration settings
        """
        self.config = config
        self.economics_engine = None  # Will be set externally if needed

    def fit(self, deal_data: pd.DataFrame, segment: str, param: str) -> Dict[str, float]:
        """
        Fit a decay curve from historical deal data.

        Groups deals by volume bucket, computes mean ASP (or win rate) per bucket,
        fits the configured decay function using scipy.optimize.curve_fit.

        Logic:
        1. Filter deal_data to the specified segment
        2. Check that at least min_deals_for_fit deals exist
        3. Create volume buckets (e.g., 0-50, 50-100, 100-200)
        4. Compute mean ASP or win_rate per bucket
        5. Fit the configured decay function
        6. Return fitted parameters {rate, threshold, floor_multiplier}

        Args:
            deal_data: DataFrame with columns [segment, volume, asp, win_rate]
            segment: Segment identifier to fit
            param: "asp" or "win_rate"

        Returns:
            dict: Fitted parameters {rate, threshold, floor_multiplier}

        Raises:
            ValueError: If not enough data to fit
        """
        # Step 1: Filter to segment
        segment_deals = deal_data[deal_data["segment"] == segment].copy()

        # Step 2: Check minimum deal count
        min_deals = self.config.get("economics.calibration.min_deals_for_fit", 50)
        if len(segment_deals) < min_deals:
            raise ValueError(
                f"Segment {segment} has {len(segment_deals)} deals, "
                f"need at least {min_deals} to fit"
            )

        # Step 3: Create volume buckets and compute mean per bucket
        # Use quantile-based buckets for more even distribution
        n_buckets = 5
        segment_deals["volume_bucket"] = pd.qcut(
            segment_deals["volume"], q=n_buckets, duplicates="drop"
        )

        # Group by bucket and compute mean
        bucket_stats = segment_deals.groupby("volume_bucket", observed=True).agg({
            "volume": "mean",
            param: "mean"
        }).reset_index(drop=True)

        # Step 4: Extract x (volume) and y (asp or win_rate) for curve fitting
        x_data = bucket_stats["volume"].values
        y_data = bucket_stats[param].values

        # Step 5: Fit the configured decay function
        fit_function = self.config.get("economics.calibration.fit_function", "exponential")

        try:
            if fit_function == "linear":
                # y = base - rate * x
                # Fit: [base, rate]
                popt, _ = curve_fit(
                    lambda x, base, rate: base - rate * np.maximum(0, x),
                    x_data, y_data,
                    p0=[y_data[0], 0.0001],
                    maxfev=5000
                )
                rate, threshold = popt[1], 0
                floor_multiplier = y_data[-1] / y_data[0]  # Last value / first value

            elif fit_function == "exponential":
                # y = base * exp(-rate * x)
                # Fit: [base, rate]
                popt, _ = curve_fit(
                    lambda x, base, rate: base * np.exp(-rate * np.maximum(0, x)),
                    x_data, y_data,
                    p0=[y_data[0], 0.001],
                    maxfev=5000
                )
                rate = popt[1]
                threshold = 0
                floor_multiplier = y_data[-1] / y_data[0]

            else:
                # Default to exponential
                popt, _ = curve_fit(
                    lambda x, base, rate: base * np.exp(-rate * np.maximum(0, x)),
                    x_data, y_data,
                    p0=[y_data[0], 0.001],
                    maxfev=5000
                )
                rate = popt[1]
                threshold = 0
                floor_multiplier = y_data[-1] / y_data[0]

        except Exception as e:
            raise ValueError(f"Failed to fit {param} curve for {segment}: {str(e)}")

        # Step 6: Return fitted parameters
        return {
            "function": fit_function,
            "rate": float(rate),
            "threshold": float(threshold),
            "floor_multiplier": max(0.1, min(1.0, float(floor_multiplier)))  # Constrain to [0.1, 1.0]
        }

    def calibrate_all(self, deal_data: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
        """
        Fit decay curves for all segments that have sufficient data.

        Iterates over unique segments in deal_data, attempts to fit ASP and win_rate
        curves for each, and returns a dict of all successful fits.

        Args:
            deal_data: DataFrame with columns [segment, volume, asp, win_rate]

        Returns:
            dict: {(segment, param): fitted_params, ...}
            Example: {("EOR.Marketing", "asp"): {rate: 0.0005, ...}, ...}
        """
        fitted_params = {}
        min_deals = self.config.get("economics.calibration.min_deals_for_fit", 50)

        # Get unique segments
        segments = deal_data["segment"].unique()

        for segment in segments:
            segment_deals = deal_data[deal_data["segment"] == segment]

            # Try to fit ASP
            if len(segment_deals) >= min_deals:
                try:
                    asp_params = self.fit(deal_data, segment, "asp")
                    fitted_params[(segment, "asp")] = asp_params
                except ValueError:
                    # Not enough data for this segment
                    pass

                # Try to fit win_rate
                try:
                    wr_params = self.fit(deal_data, segment, "win_rate")
                    fitted_params[(segment, "win_rate")] = wr_params
                except ValueError:
                    # Not enough data for this segment
                    pass

        return fitted_params
