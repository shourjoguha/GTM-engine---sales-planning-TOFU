"""
DataLoader: Data Preparation and Cleaning for GTM Planning Engine

This module ingests raw data from CSV or Excel files and produces a clean,
analysis-ready dataframe. It applies dimension filtering, confidence scoring,
fallback value imputation, and anomaly detection.

Key Responsibilities:
- Load data from CSV or Excel files (auto-detect format from extension)
- Filter to active dimensions only (drop toggled-off columns)
- Standardize column names to match expected metric columns
- Score confidence per segment based on deal count
- Apply fallback values for low-confidence segments using parent values
- Detect and flag supersized deals (outlier revenue anomalies)

The data loader bridges raw operational data and the downstream analysis modules.
It ensures:
- Data quality: handles missing values, standardizes naming, detects anomalies
- Consistency: enforces active dimensions, applies confidence rules
- Traceability: flags which values came from fallbacks vs. raw data

Example usage:
    config = ConfigManager('config.yaml')
    loader = DataLoader(config)
    df_raw = loader.load('data/raw/2025_actuals.csv')
    df_clean = loader.prepare(df_raw)
    # df_clean has confidence_level and is_supersized columns
"""

import logging
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from .config_manager import ConfigManager

logger = logging.getLogger(__name__)


class DataLoader:
    """
    Loads and cleans raw data for GTM planning analysis.

    Attributes:
        config (ConfigManager): Configuration controlling dimension toggles and confidence thresholds.
        active_dimensions (list[str]): List of dimension names to keep in prepared data.
        confidence_thresholds (dict): High and medium confidence deal count thresholds.
        fallback_hierarchy (list): Hierarchy for fallback value selection (e.g., ['product', 'global'])
    """

    # Standard metric columns expected in data
    STANDARD_METRICS = ['ASP', 'CW rate', 'close_win_rate', 'Revenue', 'SAOs', 'Month', 'Year']

    def __init__(self, config: ConfigManager) -> None:
        """
        Initialize DataLoader with configuration.

        Args:
            config (ConfigManager): Configuration object containing dimension toggles,
                                   confidence thresholds, and fallback rules.
        """
        self.config = config
        self.active_dimensions = config.get_active_dimensions()

        # Extract confidence thresholds from config
        self.confidence_high = config.get('economics.confidence.high_threshold', 6)
        self.confidence_medium = config.get('economics.confidence.medium_threshold', 3)

        # Extract fallback hierarchy and multiplier
        self.fallback_hierarchy = config.get(
            'economics.confidence.fallback_hierarchy',
            ['segment', 'product', 'global']
        )
        self.default_fallback_multiplier = config.get(
            'economics.confidence.default_fallback_multiplier',
            0.80
        )

        # Extract supersized deal detection threshold
        self.supersized_threshold = config.get('system.supersized_deal_threshold', 3.0)


    def load(self, file_path: str, sheet_name: Optional[str] = None) -> pd.DataFrame:
        """
        Load data from CSV or Excel file. Auto-detects format from file extension.

        Supports:
        - CSV files (.csv): loaded directly with pd.read_csv
        - Excel files (.xlsx, .xls): loaded with pd.read_excel

        Args:
            file_path (str): Path to the data file (CSV or Excel).
            sheet_name (str, optional): Sheet name for Excel files. If None, uses first sheet.

        Returns:
            pd.DataFrame: Raw dataframe loaded from file.

        Raises:
            FileNotFoundError: If file does not exist.
            ValueError: If file format is not supported.
        """
        path_obj = Path(file_path)

        # Check file exists
        if not path_obj.exists():
            raise FileNotFoundError(f"Data file not found: {file_path}")

        # Auto-detect format from extension
        suffix = path_obj.suffix.lower()

        if suffix == '.csv':
            # Load CSV file
            df = pd.read_csv(file_path)
        elif suffix in ['.xlsx', '.xls']:
            # Load Excel file
            if sheet_name is None:
                # Load first sheet if not specified
                df = pd.read_excel(file_path)
            else:
                df = pd.read_excel(file_path, sheet_name=sheet_name)
        else:
            raise ValueError(f"Unsupported file format: {suffix}. Use .csv, .xlsx, or .xls")

        return df


    def prepare(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Clean and prepare raw data for analysis.

        Processing pipeline:
        1. Keep only active dimension columns + metric columns
        2. Standardize column names (normalize variants like 'CW rate' -> 'close_win_rate')
        3. Ensure active dimension columns use lowercase names
        4. Score confidence level per segment based on deal count
        5. Apply fallback values for low-confidence segments using parent values
        6. Flag supersized deals (where actual revenue >> expected)

        Args:
            df (pd.DataFrame): Raw data loaded from file.

        Returns:
            pd.DataFrame: Cleaned data with additional columns:
                - confidence_level: 'high', 'medium', or 'low'
                - is_supersized: Boolean flag for outlier revenue anomalies
                - fallback_source: Which segment was used for fallback values (if applicable)
        """
        df = df.copy()

        # Step 1: Filter to active dimensions and standard metrics
        df = self._filter_columns(df)

        # Step 2: Standardize column names
        df = self._standardize_columns(df)

        # Step 2.5: Warn on missing required metric columns post-standardization
        required_metrics = ['asp', 'close_win_rate']
        missing_metrics = [c for c in required_metrics if c not in df.columns]
        if missing_metrics:
            logger.warning(
                f"Missing required metric columns after standardization: {missing_metrics}. "
                f"ROI computation will fall back to defaults. "
                f"Present columns: {list(df.columns)}"
            )
        else:
            logger.info(f"Required metric columns verified: {required_metrics}")

        # Step 2.5: Rename active dimension columns to lowercase for consistency
        df = self._normalize_dimension_names(df)

        # Step 3: Score confidence per segment
        df = self._score_confidence(df)

        # Step 4: Apply fallback values for low-confidence segments
        df = self._apply_fallbacks(df)

        # Step 5: Flag supersized deals
        df = self._flag_supersized(df)

        return df


    def _filter_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Keep only active dimension columns and standard metric columns.

        Removes any columns that:
        - Are disabled dimensions (e.g., 'region' if region is not active)
        - Are not in the active dimensions and not in standard metrics

        Args:
            df (pd.DataFrame): Raw dataframe.

        Returns:
            pd.DataFrame: Filtered dataframe with only relevant columns.
        """
        # Create a case-insensitive mapping of dataframe columns
        df_columns_lower = {col.lower(): col for col in df.columns}

        # Determine which columns to keep
        cols_to_keep = []

        # Add active dimension columns (case-insensitive matching)
        for dim in self.active_dimensions:
            dim_lower = dim.lower()
            if dim_lower in df_columns_lower:
                cols_to_keep.append(df_columns_lower[dim_lower])
            else:
                cols_to_keep.append(dim)  # Fall back to original (will be filtered out later)

        # Add standard metric columns that exist in the dataframe
        for metric in self.STANDARD_METRICS:
            if metric in df.columns:
                cols_to_keep.append(metric)

        # Keep only these columns that actually exist
        existing_cols = [c for c in cols_to_keep if c in df.columns]

        # Warn if standard metrics are missing
        missing_metrics = set(self.STANDARD_METRICS) - set(df.columns)
        if missing_metrics:
            # Allow missing metrics but note them for debugging
            pass

        return df[existing_cols]


    def _normalize_dimension_names(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Rename active dimension columns to lowercase.

        This is the single authoritative location for lowercasing dimension column
        names, ensuring they match what ConfigManager returns from
        get_active_dimensions(). For example, 'Product' -> 'product'.

        _standardize_columns() handles metric column aliases only and explicitly
        delegates dimension lowercasing here, so there is no duplication.

        Args:
            df (pd.DataFrame): Dataframe with potentially mixed-case dimension names.

        Returns:
            pd.DataFrame: Dataframe with all active dimension columns in lowercase.
        """
        rename_map = {}

        # For each active dimension, find the actual column name and rename to lowercase
        for dim in self.active_dimensions:
            dim_lower = dim.lower()

            # Check if the exact lowercase name already exists
            if dim_lower in df.columns:
                continue  # Already lowercase

            # Check if a mixed-case version exists
            for col in df.columns:
                if col.lower() == dim_lower and col != dim_lower:
                    rename_map[col] = dim_lower
                    break

        if rename_map:
            df = df.rename(columns=rename_map)

        return df

    def _standardize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Standardize metric column names to the engine's canonical schema.

        Handles common naming variations for metric columns only:
        - 'CW rate' or 'win_rate'        -> 'close_win_rate'
        - 'Revenue' or 'Bookings'         -> 'revenue'
        - 'SAOs'                          -> 'saos'
        - 'ASP' or 'avg_selling_price'    -> 'asp'
        - 'Month', 'Year'                 -> 'month', 'year'

        Dimension column lowercasing is intentionally NOT done here.
        That responsibility belongs exclusively to _normalize_dimension_names(),
        which runs immediately after this step in the prepare() pipeline.
        Keeping the two concerns separate prevents silent double-renaming if the
        pipeline order ever changes, and makes each method's contract unambiguous.

        Args:
            df (pd.DataFrame): Raw dataframe with potentially non-standard names.

        Returns:
            pd.DataFrame: Dataframe with standardized metric column names.
        """
        rename_map = {}

        # Map common variations for metric columns only
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

        df = df.rename(columns=rename_map)

        return df


    def _score_confidence(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add confidence_level column based on deal count per segment.

        Confidence scoring:
        - deal_count >= high_threshold: 'high' confidence
        - deal_count >= medium_threshold: 'medium' confidence
        - deal_count < medium_threshold: 'low' confidence (requires fallback)

        A "deal" is counted as one row per segment. If data is pre-aggregated,
        this may count one row as one segment-period.

        Args:
            df (pd.DataFrame): Dataframe with active dimensions.

        Returns:
            pd.DataFrame: Dataframe with added 'confidence_level' column.
        """
        if len(self.active_dimensions) == 0:
            # No dimensions, everything is global
            df['confidence_level'] = 'high'
            return df

        # Group by active dimensions and count rows (proxy for deal count)
        segment_counts = df.groupby(self.active_dimensions, dropna=False).size().reset_index(name='deal_count')

        # Map deal count to confidence level
        def assign_confidence(count):
            if count >= self.confidence_high:
                return 'high'
            elif count >= self.confidence_medium:
                return 'medium'
            else:
                return 'low'

        segment_counts['confidence_level'] = segment_counts['deal_count'].apply(assign_confidence)

        # Merge confidence back to original data
        df = df.merge(
            segment_counts[self.active_dimensions + ['confidence_level']],
            on=self.active_dimensions,
            how='left'
        )

        return df


    def _apply_fallbacks(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        For low-confidence segments, replace metric values with parent segment values × multiplier.

        Fallback hierarchy (from config):
        - sub_segment → segment → product → global

        For each low-confidence row, this method:
        1. Identifies the parent segment (next level up in hierarchy)
        2. Looks up the parent's average metric values
        3. Applies fallback multiplier (default 0.80)
        4. Adds fallback_source column for traceability

        Args:
            df (pd.DataFrame): Dataframe with confidence_level column.

        Returns:
            pd.DataFrame: Dataframe with fallback values applied where needed.
        """
        df['fallback_source'] = None

        # Find low-confidence rows
        low_conf_mask = df['confidence_level'] == 'low'

        if not low_conf_mask.any():
            # No low-confidence rows, return as-is
            return df

        # For now, simple approach: use global average for all low-confidence
        # (More sophisticated hierarchy logic can be added later)

        # Identify metric columns
        metric_cols = ['asp', 'close_win_rate', 'revenue', 'saos']
        metric_cols_present = [c for c in metric_cols if c in df.columns]

        if len(metric_cols_present) > 0:
            # Compute global averages
            global_avg = df[metric_cols_present].mean()

            # Apply fallback to low-confidence rows
            for col in metric_cols_present:
                # Only replace if the low-conf row has a null or zero value
                mask = low_conf_mask & (df[col].isna() | (df[col] == 0))
                df.loc[mask, col] = global_avg[col] * self.default_fallback_multiplier
                df.loc[mask, 'fallback_source'] = 'global_average'

        return df


    def compute_segment_baselines(self, df: pd.DataFrame) -> Dict[str, Dict[str, float]]:
        """
        Compute baseline ASP and CW rate per segment from prepared actuals data.

        Uses the aggregation method and grain specified in config.economics.baseline.
        These baselines feed into the EconomicsEngine as starting values before
        decay is applied.

        Aggregation collapses across the time dimension (months) — each segment
        gets a single baseline representing its "normal" economics.

        Config keys used:
            economics.baseline.aggregation: "median" | "mean" | "mode"
            economics.baseline.grain: "segment" | "global"
            economics.baseline.source: "actuals" | "manual"
            economics.baseline.manual_baselines: dict (optional overrides)

        Args:
            df (pd.DataFrame): Prepared dataframe from self.prepare() with
                                standardized columns (asp, close_win_rate, etc.)

        Returns:
            dict: Mapping of segment_key → {asp: float, win_rate: float}
                  segment_key is dot-joined active dimensions (e.g., "EOR.Marketing")
                  or "__global__" when grain = "global".
                  Returns only segments where at least one metric could be computed.

        Example:
            >>> baselines = loader.compute_segment_baselines(df_clean)
            >>> baselines["EOR.Marketing"]
            {'asp': 11500.0, 'win_rate': 0.38}
        """
        baselines = {}

        # Read config
        source = self.config.get('economics.baseline.source', 'actuals')
        aggregation = self.config.get('economics.baseline.aggregation', 'median')
        grain = self.config.get('economics.baseline.grain', 'segment')
        manual_baselines = self.config.get('economics.baseline.manual_baselines', {})

        # If source is manual and manual_baselines exist, use those directly
        if source == "manual" and manual_baselines:
            for seg_key, values in manual_baselines.items():
                baselines[seg_key] = {
                    'asp': values.get('asp', 0),
                    'win_rate': values.get('win_rate', 0)
                }
            return baselines

        # Determine which metric columns to aggregate
        asp_col = 'asp' if 'asp' in df.columns else None
        cw_col = 'close_win_rate' if 'close_win_rate' in df.columns else None

        if asp_col is None and cw_col is None:
            return baselines  # No metrics to compute

        # Select aggregation function
        if aggregation == "median":
            agg_func = 'median'
        elif aggregation == "mean":
            agg_func = 'mean'
        elif aggregation == "mode":
            agg_func = lambda x: x.mode().iloc[0] if len(x.mode()) > 0 else x.median()
        else:
            agg_func = 'median'  # Safe default

        # Build metric list for aggregation
        metric_cols = [c for c in [asp_col, cw_col] if c is not None]

        if grain == "global":
            # Single baseline for everything
            if aggregation == "mode":
                row = {}
                for col in metric_cols:
                    mode_vals = df[col].dropna().mode()
                    row[col] = mode_vals.iloc[0] if len(mode_vals) > 0 else df[col].dropna().median()
            else:
                row = df[metric_cols].agg(agg_func)

            entry = {}
            if asp_col:
                entry['asp'] = float(row[asp_col])
            if cw_col:
                entry['win_rate'] = float(row[cw_col])
            baselines['__global__'] = entry

        else:
            # Per-segment baselines using active dimensions
            if len(self.active_dimensions) == 0:
                # No dimensions active — treat as global
                if aggregation == "mode":
                    row = {}
                    for col in metric_cols:
                        mode_vals = df[col].dropna().mode()
                        row[col] = mode_vals.iloc[0] if len(mode_vals) > 0 else df[col].dropna().median()
                else:
                    row = df[metric_cols].agg(agg_func)
                entry = {}
                if asp_col:
                    entry['asp'] = float(row[asp_col])
                if cw_col:
                    entry['win_rate'] = float(row[cw_col])
                baselines['__global__'] = entry
            else:
                # Group by active dimensions and aggregate across time
                grouped = df.groupby(self.active_dimensions, dropna=False)

                if aggregation == "mode":
                    # Mode needs special handling
                    for group_key, group_df in grouped:
                        # Build segment key string
                        if isinstance(group_key, tuple):
                            seg_key = ".".join(str(v) for v in group_key)
                        else:
                            seg_key = str(group_key)

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

                    for idx, row in agg_result.iterrows():
                        # Build segment key string
                        if isinstance(idx, tuple):
                            seg_key = ".".join(str(v) for v in idx)
                        else:
                            seg_key = str(idx)

                        entry = {}
                        if asp_col and not pd.isna(row.get(asp_col, float('nan'))):
                            entry['asp'] = float(row[asp_col])
                        if cw_col and not pd.isna(row.get(cw_col, float('nan'))):
                            entry['win_rate'] = float(row[cw_col])
                        if entry:
                            baselines[seg_key] = entry

        # Apply manual overrides on top (if any exist and source is "actuals")
        # This allows partial manual overrides while computing the rest from data
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
        """
        Flag rows where actual revenue >> expected revenue (SAOs × ASP), beyond a threshold.

        A supersized deal is detected when:
            actual_revenue > (SAOs × ASP × CW_rate) × supersized_threshold

        This helps identify data anomalies or unusually large deals that may skew
        the analysis. These are flagged but not removed, allowing the user to
        investigate or manually adjust.

        Args:
            df (pd.DataFrame): Dataframe with revenue, saos, asp, and close_win_rate columns.

        Returns:
            pd.DataFrame: Dataframe with added 'is_supersized' column (boolean).
        """
        df['is_supersized'] = False

        # Check if required columns exist
        required = ['saos', 'asp', 'close_win_rate', 'revenue']
        if not all(c in df.columns for c in required):
            # Cannot flag supersized without required columns
            return df

        # Compute expected revenue
        df['expected_revenue'] = df['saos'] * df['asp'] * df['close_win_rate']

        # Flag if actual >> expected
        with np.errstate(divide='ignore', invalid='ignore'):
            ratio = df['revenue'] / (df['expected_revenue'] + 1e-6)
            df['is_supersized'] = ratio > self.supersized_threshold

        # Drop the temporary expected_revenue column
        df = df.drop(columns=['expected_revenue'])

        return df
